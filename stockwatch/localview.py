"""A self-contained public alert inbox, published as a local HTML file."""

import base64
import hashlib
import html
import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import mkstemp
from urllib.parse import urlsplit

from .model import utc
from .monitor import SOURCES, coverage
from .store import ENTRY, coverage_gaps


LIMIT = 40
STYLE = Path(__file__).with_name("inbox.css")
SCRIPT = """
const badge = document.querySelector('#health-badge');
const warning = document.querySelector('#heartbeat-warning');
const deadline = Number(warning.dataset.deadline);
function checkClock() {
  if (deadline && Date.now() > deadline) {
    warning.hidden = false;
    badge.textContent = 'Heartbeat overdue';
    badge.className = 'badge warn';
    document.title = 'Coverage warning | Stockwatch';
  }
}
checkClock();
setInterval(checkClock, 1000);
setTimeout(() => location.reload(), 30000);
"""


def _text(value):
    return html.escape(str(value), quote=True)


def _source(url, label):
    # Evidence URLs can come from user-supplied relationship files. Render a
    # plain label for anything that cannot safely be opened as an HTTPS link.
    label = _text(label)
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or not parts.hostname or parts.username is not None
                or parts.password is not None or "\\" in url
                or any(char.isspace() or ord(char) < 32 for char in url)):
            return label
        _ = parts.port  # Reject a malformed or out-of-range port.
    except (TypeError, ValueError):
        return label
    return f'<a href="{_text(url)}" target="_blank" rel="noopener noreferrer">{label}</a>'


def _time(value):
    stamp = utc(value)
    return f'<time datetime="{stamp}">{stamp[:10]} · {stamp[11:19]} UTC</time>'


def _relationships(links):
    sources = []
    for link in links:
        filing = _source(link["source_url"], link["locator"])
        site = _source(link["site_url"], link["site"])
        point = _source(link["coordinates_url"], "Screening coordinates")
        sources.append(f"<li><strong>{_text(link['ticker'])}</strong> · {_text(link['scope'])} "
                       f"{_text(link['limit'])} {filing} · {site} · {point}</li>")
    return '<details><summary>Supplier relationships</summary><ul>' + "".join(sources) + "</ul></details>"


def _alert(row):
    facts = json.loads(row["facts"])
    links = json.loads(row["links"])
    tickers = " / ".join(sorted({link["ticker"] for link in links}))
    status = row["status"]
    kind = row["kind"]
    if kind == "issuer_candidate":
        label = f"Issuer statement for review · {status}"
        body = f'<blockquote>{_text(facts["excerpt"])}</blockquote><p>{_text(facts["uncertainty"])}</p>'
        next_check = facts["next_check"]
    elif kind == "operator_update":
        label = f"Assessed · {status}"
        body = (f'<p>{_text(facts["uncertainty"])}</p>'
                f'<p class="stamp">{_text(facts["locator"])} {_text(facts["clock_basis"])}</p>')
        next_check = facts["next_check"]
    elif status == "withdrawn":
        label = "Watch withdrawn"
        body = "<p>The revised hazard falls outside this watch’s original screen.</p>"
        next_check = "Check the revised USGS evidence before reopening the watch."
    else:
        label = "Conditional watch"
        sites = {link["site"]: link for link in links}
        body = "".join(f"<p>{_text(link['supplier'])} · {_text(link['site'])} · "
                       f"{_text(link['distance_km'])} km to the regional screening point.</p>"
                       for link in sites.values())
        body += "<p>Fab disruption and customer shipment effects remain unconfirmed.</p>"
        next_check = "Check TSMC’s next operations statement for evacuation, tool downtime or recovery."
    evidence_label = "USGS observation" if row["source"] == "USGS" else "Issuer disclosure"
    return f"""
<article>
  <div class="meta"><span class="type">{_text(label)}</span><span>{_text(tickers)}</span></div>
  <h3>{_text(row['title'])}</h3>
  <p class="stamp">{_text(row['source'])} · source version {_time(row['revision'])}</p>
  {body}
  <p><strong>Next check</strong> &nbsp;{_text(next_check)}</p>
  <div class="evidence">{_source(row['url'], evidence_label)}<span>Received {_time(row['seen_at'])}</span></div>
  {_relationships(links)}
</article>"""


def _page(db, cutoff, replay):
    from .followup import unlinked

    run, health, warnings = coverage(db, cutoff)
    rows = db.execute(ENTRY + " WHERE seen_at<=? ORDER BY seen_at DESC, sequence DESC LIMIT ?",
                      (cutoff, LIMIT)).fetchall()
    unassigned = unlinked(db, cutoff)
    state = run.get("state")
    if replay:
        # Source health and monitor heartbeat each retain only their latest
        # checkpoint. A later checkpoint cannot describe an earlier replay.
        run = run if run.get("at", "") <= cutoff else {}
        health = {source: record for source, record in health.items() if record["attempt"] <= cutoff}
        warnings = list(run.get("gaps", []))
        warnings.extend(f"{source} collection failed. {record['error']}"
                        for source, record in health.items() if record["error"])
    if warnings:
        status, tone = "Coverage warning", "warn"
    elif replay:
        status, tone = "Historical replay", "neutral"
    elif state == "running":
        status, tone = "Monitoring", "ok"
    else:
        status, tone = "One-time snapshot", "neutral"
    warning_list = "".join(f'<li class="warning">{_text(message)}</li>' for message in warnings)
    gaps = coverage_gaps(db, as_of=cutoff)
    previous_gaps = ""
    if gaps:
        notes = "".join(f"<li>{_text(gap)}</li>" for gap in gaps)
        previous_gaps = f'<section class="gaps"><h3>Past coverage gaps</h3><ul>{notes}</ul></section>'
    deadline = 0
    if state == "running" and not replay:
        deadline = round((datetime.fromisoformat(run["at"]).timestamp() + run["interval"] + 120) * 1000)
    health_rows = []
    for source in SOURCES:
        record = health.get(source) or {}
        missing = "No receipt at this cutoff" if replay else "Awaiting first receipt"
        receipt = _time(record["last_ok"]) if record.get("last_ok") else missing
        failure = ' <span class="failure">Failed</span>' if record.get("error") else ""
        health_rows.append(f"<div><dt>{_text(source)}{failure}</dt><dd>{receipt}</dd></div>")
    alerts = "".join(_alert(row) for row in rows)
    if not alerts:
        alerts = '<div class="empty">No watch or issuer follow-up has reached this inbox.</div>'
    unassigned_html = ""
    if unassigned:
        items = "".join(f"<li>{_source(row['url'], row['title'])}<p>{_text(row['reason'])} · "
                        f"{_time(row['published_at'])}</p></li>" for row in unassigned)
        unassigned_html = f'<section><h2>Unassigned issuer statements</h2><ul class="unassigned">{items}</ul></section>'
    time_label = "Simulated receipt cutoff" if replay else "Updated"
    script = "" if replay else f"<script>{SCRIPT}</script>"
    digest = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    policy = f"default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-{digest}'; base-uri 'none'; form-action 'none'"
    coverage_text = f'<p class="scope">{_text(run["coverage"])}</p>' if run.get("coverage") else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{policy}"><meta name="referrer" content="no-referrer">
<title>Alert inbox | Stockwatch</title><style>{STYLE.read_text(encoding='utf-8')}</style></head><body>
<header><div class="wrap brand">Stockwatch</div></header>
<main class="wrap">
<div class="mast"><h1>Alert inbox</h1><div class="asof">{time_label}<br>{_time(cutoff)}</div></div>
<ul class="warnings" aria-live="polite">{warning_list}
<li id="heartbeat-warning" class="warning" data-deadline="{deadline}" hidden>Monitor heartbeat overdue. Check the collector and whether this computer was asleep.</li></ul>
<div class="layout"><aside>
  <h2>Coverage</h2><span class="badge {tone}" id="health-badge">{status}</span>
  {coverage_text}
  <h3>Last successful collection</h3><dl>{''.join(health_rows)}</dl>{previous_gaps}
</aside><div class="stream"><section><h2>Latest alerts</h2>{alerts}</section>{unassigned_html}</div></div>
</main>{script}</body></html>"""


def write_view(db, path: Path, cutoff: str, *, replay=False):
    """Publish one consistent public ledger snapshot, leaving the old page intact on failure."""
    start_read = not db.in_transaction
    if start_read:
        db.execute("BEGIN")
    try:
        markup = _page(db, utc(cutoff), replay)
    finally:
        if start_read:
            db.rollback()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = mkstemp(dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(markup)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
