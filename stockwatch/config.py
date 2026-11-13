"""Local monitor settings. Only public watchlist data goes into ingestion."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkstemp

from .model import now
from .relevance import Watchlist, load_watchlist, portfolio_context


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
DEFAULT_CONFIG = Path(".stockwatch/config.json")
SAMPLE_PORTFOLIO = EXAMPLES / "sample-allocation.json"
FORMAT = "stockwatch-config-v1"
KEYS = {"format", "watchlist", "tickers", "min_magnitude", "radius_km", "portfolio"}


@dataclass(frozen=True)
class Settings:
    watchlist: Watchlist
    watchlist_path: Path
    portfolio: Path | None

    @property
    def tickers(self):
        return self.watchlist.tickers


def _document(path, allow_missing=False):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        if allow_missing or path == DEFAULT_CONFIG.resolve():
            return {"format": FORMAT}
        raise
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.keys() - KEYS:
        raise ValueError(f"Expected a {FORMAT} settings file at {path}")
    return data


def _path(base, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected a file path in monitor configuration")
    return (base / Path(value).expanduser()).resolve()


def _resolve(path, data):
    source = _path(path.parent, data["watchlist"]) if "watchlist" in data else EXAMPLES / "watchlist.json"
    watchlist = load_watchlist(source, tickers=data.get("tickers"), min_magnitude=data.get("min_magnitude"),
                               radius_km=data.get("radius_km"))
    portfolio = data.get("portfolio", "sample")
    if portfolio == "sample":
        portfolio = SAMPLE_PORTFOLIO
    elif portfolio is not None:
        portfolio = _path(path.parent, portfolio)
    if path in {source, portfolio}:
        raise ValueError("Use separate files for settings, relationship evidence and positions")
    return Settings(watchlist, source, portfolio)


def load_config(path=DEFAULT_CONFIG) -> Settings:
    path = Path(path).expanduser().resolve()
    return _resolve(path, _document(path))


def _save(path, edits):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the lock on a separate inode. Replacing the JSON is atomic even for
    # readers that do not acquire a lock. The OS releases the lock after a crash.
    with path.with_name(path.name + ".lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        data = _document(path, allow_missing=True)
        data.update(edits)
        settings = _resolve(path, data)
        if "portfolio" in edits and settings.portfolio:
            portfolio_context(settings.portfolio, settings.tickers, now())
        fd, name = mkstemp(dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as candidate:
                json.dump(data, candidate, indent=2, allow_nan=False)
                candidate.write("\n")
                candidate.flush()
                os.fsync(candidate.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return settings


def configure(args):
    path = args.config.expanduser().resolve()
    edits = {key: getattr(args, key) for key in ("min_magnitude", "radius_km") if getattr(args, key) is not None}
    if args.watchlist is not None:
        edits["watchlist"] = str(args.watchlist.expanduser().resolve())
    if args.tickers is not None:
        tickers = [item.strip().upper() for item in args.tickers.split(",")]
        if not all(tickers):
            raise ValueError("Supply comma-separated ticker symbols, for example AMD,NVDA")
        edits["tickers"] = sorted(set(tickers))
    elif args.all_tickers:
        edits["tickers"] = None
    if args.watchlist_only:
        edits["portfolio"] = None
    elif args.sample_portfolio:
        edits["portfolio"] = "sample"
    elif args.portfolio is not None:
        edits["portfolio"] = str(args.portfolio.expanduser().resolve())
    settings = _save(path, edits) if edits else load_config(path)
    if edits:
        print(f"Saved settings to {path}")
    elif path.exists():
        print(f"Settings at {path}")
    else:
        print(f"Using built-in settings. Configuration changes will be saved to {path}")
    print(f"Watchlist: {', '.join(settings.tickers)}")
    print(f"Relationship evidence: {settings.watchlist_path}")
    print(f"Screen: M{settings.watchlist.min_magnitude:g}+ within {settings.watchlist.radius_km:g} km")
    print(f"Coverage: {settings.watchlist.coverage(now())}")
    if settings.portfolio == SAMPLE_PORTFOLIO:
        print("Portfolio: hypothetical sample allocation (fixed USD amounts)")
    elif settings.portfolio:
        print(f"Portfolio: local file {settings.portfolio}")
    else:
        print("Portfolio: watchlist only")


def add_configure_command(sub):
    parser = sub.add_parser("configure", help="show or update local monitor settings")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--watchlist", type=Path, help="dated relationship evidence JSON")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--tickers", help="comma-separated symbols from the evidence file")
    selection.add_argument("--all-tickers", action="store_true", help="select every documented symbol")
    parser.add_argument("--radius-km", type=float)
    parser.add_argument("--min-magnitude", type=float)
    positions = parser.add_mutually_exclusive_group()
    positions.add_argument("--portfolio", type=Path, help="local dated positions JSON")
    positions.add_argument("--sample-portfolio", action="store_true", help="use the default hypothetical allocation")
    positions.add_argument("--watchlist-only", action="store_true", help="omit portfolio amounts")
    parser.set_defaults(run=configure)
