"""Offline acceptance run through the same collectors and delivery path as start."""

import json
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .config import EXAMPLES, load_config
from .issuer import parse_bulletins
from .localview import write_view
from .model import utc
from .monitor import DEFAULT_INTERVAL, cycle, heartbeat, scheduler_lock, set_setting, setting
from .report import report
from .store import connect


FIRST = utc("2024-04-03T00:15:00Z")
FOLLOW_UP = utc("2024-04-06T01:00:00Z")


def _unavailable(_seen):
    raise OSError("simulated TWSE outage during the first replay cycle")


def monitor_demo(path, watchlist_only, config):
    path = path or Path(".stockwatch/monitor-demo.sqlite3")
    settings = load_config(config)
    if watchlist_only:
        settings = replace(settings, portfolio=None)
    quake = (EXAMPLES / "usgs-taiwan-2024.geojson").read_bytes()
    disclosure = (EXAMPLES / "issuer-twse-2024.json").read_bytes()
    # Only the historical quake and issuer statement are investment evidence.
    # A synthetic quiet response exercises a later healthy collection cycle.
    quiet = json.dumps({"type": "FeatureCollection", "features": [], "metadata": {
        "status": 200, "count": 0, "generated": int(datetime.fromisoformat(FOLLOW_UP).timestamp() * 1000),
    }}).encode()
    view = Path(str(path) + ".alerts.html").resolve()
    with scheduler_lock(path), closing(connect(path, "monitor-demo")) as db:
        fingerprint = setting(db, "replay_watchlist")
        if fingerprint and fingerprint != settings.watchlist.fingerprint:
            raise ValueError("this replay has a different watchlist. Use --db with a new demo database.")
        set_setting(db, "replay_watchlist", settings.watchlist.fingerprint)
        stage = setting(db, "replay_stage", 0)
        print("MONITOR REPLAY | simulated UTC receipts. USGS and TSMC evidence, with an injected source outage.")
        if stage == 0:
            print("\nApril 3 | earthquake collection and issuer source failure")
            first = cycle(db, settings, clock=lambda: FIRST, quake_fetch=lambda: quake, issuer_fetch=_unavailable)
            if "USGS" not in first:
                raise ValueError("the replay could not collect the historical earthquake")
            heartbeat(db, "replay", lambda: FIRST, DEFAULT_INTERVAL, settings.watchlist)
            set_setting(db, "replay_stage", 1)
        print("\nApril 6 | quiet USGS test response and a reconstructed TWSE daily edition")
        counts = cycle(db, settings, clock=lambda: FOLLOW_UP, quake_fetch=lambda: quiet,
                       issuer_fetch=lambda seen: parse_bulletins(disclosure, seen))
        if len(counts) != 2:
            raise ValueError("replay follow-up cycle failed. Inspect its source warning.")
        heartbeat(db, "replay", lambda: FOLLOW_UP, DEFAULT_INTERVAL, settings.watchlist)
        set_setting(db, "replay_stage", 2)
        write_view(db, view, FOLLOW_UP, replay=True)
        print(f"Follow-up cycle added {counts['TSMC'][0]} issuer documents and {counts['TSMC'][1]} linked alerts.")
        if stage == 2:
            print("Saved replay history")
            report(db, FOLLOW_UP, history=True, portfolio=settings.portfolio)
        print(f"Replay inbox: {view.as_uri()}")
