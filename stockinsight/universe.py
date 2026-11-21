"""A one-way mirror of user-declared instrument snapshots. No provider session."""

import csv
import hashlib
import io
import json
import os
import re
import stat
import time
from datetime import UTC, datetime, timedelta
from itertools import chain
from pathlib import Path

from .db import instant, now, uid, write

SCHEMA = """
CREATE TABLE companies (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, cik TEXT NOT NULL UNIQUE,
    identity_source TEXT NOT NULL, commit_seq INTEGER NOT NULL
);
CREATE TABLE instruments (
    id TEXT PRIMARY KEY, identity_key TEXT NOT NULL UNIQUE, provider_namespace TEXT NOT NULL,
    conid TEXT, ticker TEXT, listing_exchange TEXT, routing_exchange TEXT,
    security_type TEXT, currency TEXT, raw_label TEXT NOT NULL,
    company_id TEXT REFERENCES companies(id), resolution_status TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, commit_seq INTEGER NOT NULL,
    UNIQUE(provider_namespace,conid)
);
CREATE TABLE instrument_aliases (
    instrument_id TEXT NOT NULL REFERENCES instruments(id), ticker TEXT NOT NULL,
    PRIMARY KEY (instrument_id,ticker)
);
CREATE INDEX instrument_listing ON instruments(ticker,listing_exchange,security_type,currency);
CREATE TABLE watchlist_sources (
    id TEXT PRIMARY KEY, alias TEXT NOT NULL, authority TEXT NOT NULL CHECK(authority='external'),
    provider TEXT NOT NULL CHECK(provider='ibkr'), mode TEXT NOT NULL,
    external_list_id TEXT, active_snapshot_id TEXT REFERENCES watchlist_snapshots(id),
    last_observation_id TEXT REFERENCES watchlist_snapshots(id), last_success_at TEXT,
    status TEXT NOT NULL, commit_seq INTEGER NOT NULL
);
CREATE TABLE watchlist_snapshots (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES watchlist_sources(id),
    base_snapshot_id TEXT REFERENCES watchlist_snapshots(id), observed_at TEXT NOT NULL,
    source_updated_at TEXT, provider_version TEXT, mode TEXT NOT NULL, content_hash TEXT,
    entries TEXT NOT NULL, membership_complete INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('candidate','complete','rejected')),
    reason TEXT NOT NULL, added INTEGER NOT NULL, removed INTEGER NOT NULL,
    accepted_at TEXT, acceptance TEXT CHECK(acceptance IN ('automatic','confirmed')),
    commit_seq INTEGER NOT NULL
);
CREATE TABLE source_memberships (
    source_id TEXT NOT NULL REFERENCES watchlist_sources(id),
    instrument_id TEXT NOT NULL REFERENCES instruments(id),
    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
    snapshot_id TEXT NOT NULL REFERENCES watchlist_snapshots(id),
    status TEXT NOT NULL CHECK(status IN ('active','removed')), display_order INTEGER,
    commit_seq INTEGER NOT NULL, PRIMARY KEY(source_id,instrument_id)
);
CREATE INDEX membership_instruments ON source_memberships(instrument_id,status);
CREATE TABLE themes (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, question TEXT NOT NULL,
    author TEXT NOT NULL, created_at TEXT NOT NULL, commit_seq INTEGER NOT NULL
);
CREATE TABLE theme_memberships (
    id TEXT PRIMARY KEY, theme_id TEXT NOT NULL REFERENCES themes(id),
    company_id TEXT REFERENCES companies(id), instrument_id TEXT REFERENCES instruments(id),
    relation TEXT NOT NULL, reason TEXT NOT NULL, evidence_refs TEXT NOT NULL,
    author TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('proposed','accepted')),
    commit_seq INTEGER NOT NULL,
    CHECK ((company_id IS NULL) != (instrument_id IS NULL))
);
CREATE TABLE exposures (
    id TEXT PRIMARY KEY, from_company_id TEXT NOT NULL REFERENCES companies(id),
    to_company_id TEXT NOT NULL REFERENCES companies(id), relation TEXT NOT NULL,
    valid_from TEXT, valid_until TEXT, evidence_refs TEXT NOT NULL, uncertainty TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('proposed','supported')), commit_seq INTEGER NOT NULL,
    CHECK (from_company_id != to_company_id),
    CHECK (valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from),
    CHECK (status != 'supported' OR (valid_from IS NOT NULL AND evidence_refs != '[]'))
);
"""

IDENTITY_MIGRATION = """
CREATE TABLE watchlist_previews (
    snapshot_id TEXT PRIMARY KEY REFERENCES watchlist_snapshots(id),
    bindings_hash TEXT NOT NULL, affected TEXT NOT NULL
);
CREATE TABLE instrument_corrections (
    snapshot_id TEXT NOT NULL REFERENCES watchlist_snapshots(id),
    instrument_id TEXT NOT NULL REFERENCES instruments(id),
    before_fields TEXT NOT NULL, after_fields TEXT NOT NULL,
    commit_seq INTEGER NOT NULL REFERENCES commits(seq),
    PRIMARY KEY(snapshot_id,instrument_id)
);
"""

MAX_BYTES = 1024 * 1024
MAX_ROWS = 5000
FIELDS = ("ticker", "conid", "security_type", "listing_exchange", "routing_exchange", "currency")
LISTING = ("ticker", "listing_exchange", "security_type", "currency")
# Curated common-share listing identities, backed by the linked filing cover pages.
_ISSUERS = {
    ("NVDA", "NASDAQ", "STK", "USD"): (
        "NVIDIA Corporation",
        "0001045810",
        "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000021/nvda-20260125.htm",
    ),
    ("MSFT", "NASDAQ", "STK", "USD"): (
        "Microsoft Corporation",
        "0000789019",
        "https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm",
    ),
}
_FIELDS_RX = {
    "ticker": r"[A-Z0-9]{1,10}(?:[.-][A-Z0-9]{1,4})?",
    "conid": r"[0-9]{1,20}",
    "security_type": r"[A-Z]{2,8}",
    "listing_exchange": r"[A-Z][A-Z0-9.]{0,14}",
    "routing_exchange": r"[A-Z][A-Z0-9.]{0,14}",
    "currency": r"[A-Z]{3}",
}
_ACCOUNT = re.compile(r"(?:[UFD]|DU|DF|FA|I|FAM|UAM|UAF)[0-9]{4,}", re.IGNORECASE)
_PRIVATE_LABELS = {
    "ACCOUNT",
    "ACCOUNTS",
    "ACCOUNTID",
    "BALANCE",
    "CASH",
    "PASSWORD",
    "POSITIONS",
    "POSITION",
    "QUANTITY",
    "PNL",
    "HOLDINGS",
    "PORTFOLIO",
}


def read_file(path):
    """Read the selected regular file after a stable interval; never retain its path."""
    try:
        if not stat.S_ISREG(Path(path).stat().st_mode):
            raise ValueError("Select a regular instrument file.")
        with Path(path).open("rb") as handle:
            first = os.fstat(handle.fileno())
            if not stat.S_ISREG(first.st_mode) or first.st_size > MAX_BYTES:
                raise ValueError("Select an instrument file of at most 1 MiB.")
            time.sleep(2)
            data = handle.read(MAX_BYTES + 1)
            last = Path(path).stat()
            if (first.st_dev, first.st_ino, first.st_size, first.st_mtime_ns) != (
                last.st_dev,
                last.st_ino,
                last.st_size,
                last.st_mtime_ns,
            ) or len(data) != first.st_size:
                raise ValueError("The selected file changed during import. Retry once it is stable.")
    except OSError:
        raise ValueError("The selected instrument file is unavailable.") from None
    return data


def _project(fields):
    entry = {}
    for field in FIELDS:
        original = fields.get(field, "").strip()
        value = original.upper()
        if value and (
            not original.isascii()
            or not re.fullmatch(_FIELDS_RX[field], value, re.ASCII)
            or _ACCOUNT.search(value)
            or (value in _PRIVATE_LABELS and not (field in {"ticker", "security_type"} and value == "CASH"))
        ):
            raise ValueError("An instrument field contains an unsupported identifier.")
        entry[field] = value or None
    if not entry["conid"] and not entry["ticker"]:
        raise ValueError("Each row needs an instrument symbol or contract ID.")
    if entry["ticker"] and entry["ticker"].isdigit() and not entry["listing_exchange"]:
        raise ValueError("A numeric symbol requires a listing exchange.")
    if entry["listing_exchange"] == "SMART":
        raise ValueError("SMART is a routing exchange. Supply it in routing_exchange.")
    return entry


def _parse(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("The snapshot exceeds the supported input size.")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("Use UTF-8 instrument text or CSV.") from None
    if not content.strip():
        return []
    reader = csv.reader(io.StringIO(content, newline=""), strict=True)
    try:
        first = next(reader)
        header = [cell.strip().lower() for cell in first]
        if len(first) > 1 or (len(header) == 1 and header[0] in FIELDS):
            if (
                len(header) != len(set(header))
                or not set(header) <= set(FIELDS)
                or not {"ticker", "conid"}.intersection(header)
            ):
                raise ValueError("Unsupported header. Use an instrument-only CSV.")
            rows = reader
        else:
            header = ["ticker"]
            rows = chain([first], reader)
        entries = []
        for number, row in enumerate(rows, 1):
            if number > MAX_ROWS:
                raise ValueError("The snapshot exceeds the instrument row limit.")
            if len(row) != len(header):
                raise ValueError("Incomplete row or unexpected columns in instrument input.")
            entries.append(_project(dict(zip(header, row))))
        return _deduplicate(entries)
    except csv.Error:
        raise ValueError("Malformed instrument CSV.") from None


def _key(entry, source_id):
    if entry["conid"]:
        return "ibkr:" + entry["conid"]
    listing = tuple(entry[k] for k in ("ticker", "listing_exchange", "security_type", "currency"))
    if all(listing) and listing[2] in {"STK", "ADR", "ETF"}:
        return "listing:" + ":".join(listing)
    return "provisional:" + source_id + ":" + json.dumps(entry, sort_keys=True)


def _deduplicate(entries):
    """Coalesce compatible repeated rows without merging two distinct contracts."""
    contracts = {}
    for entry in entries:
        if entry["conid"]:
            listing = _key({**entry, "conid": None}, "")
            if listing.startswith("listing:"):
                contracts.setdefault(listing, set()).add(entry["conid"])
    unique = {}
    for entry in entries:
        key = _key(entry, "")
        if key in contracts:
            if len(contracts[key]) > 1:
                raise ValueError("A listing matches several contract IDs. Clarify the ambiguous row.")
            entry = {**entry, "conid": next(iter(contracts[key]))}
            key = _key(entry, "")
        previous = unique.get(key)
        if previous:
            if any(entry[f] and previous[f] and entry[f] != previous[f] for f in FIELDS):
                raise ValueError("Conflicting metadata for a repeated instrument identity.")
            entry = {f: entry[f] or previous[f] for f in FIELDS}
        unique[key] = entry
    return list(unique.values())


def _issuer(entry):
    return _ISSUERS.get(tuple(entry[k] for k in ("ticker", "listing_exchange", "security_type", "currency")))


def _row(conn, table, item_id):
    # Only private callers choose a table name.
    return conn.execute(f"SELECT * FROM {table} WHERE id=?", (item_id,)).fetchone()


def _snapshot(conn, snapshot_id):
    snap = dict(_row(conn, "watchlist_snapshots", snapshot_id))
    snap["entries"] = json.loads(snap["entries"])
    snap["membership_complete"] = bool(snap["membership_complete"])
    source = _row(conn, "watchlist_sources", snap["source_id"])
    preview = conn.execute(
        "SELECT affected,bindings_hash FROM watchlist_previews WHERE snapshot_id=?", (snapshot_id,)
    ).fetchone()
    snap["source_alias"] = source["alias"]
    snap["affected"] = json.loads(preview["affected"]) if preview else []
    snap["confirmable"] = bool(
        preview
        and snap["membership_complete"]
        and snap["state"] == "candidate"
        and source["last_observation_id"] == snapshot_id
        and source["active_snapshot_id"] == snap["base_snapshot_id"]
    )
    if snap["state"] == "candidate" and not preview:
        snap["reason"] = "Import this snapshot again to review its current identity bindings."
    elif snap["confirmable"]:
        try:
            _, _, binding_hash, _ = _identity_plan(conn, snap["source_id"], snap["entries"])
            snap["confirmable"] = binding_hash == preview["bindings_hash"]
        except ValueError:
            snap["confirmable"] = False
        if not snap["confirmable"]:
            snap["reason"] = "Identity bindings changed. Import a fresh snapshot before confirmation."
    return snap


def _source(conn, source_id, mode, seq):
    if (
        not isinstance(source_id, str)
        or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", source_id)
        or _ACCOUNT.search(source_id)
        or source_id.upper() in _PRIVATE_LABELS
    ):
        raise ValueError("Use a short local source ID such as personal.")
    if mode not in {"manual_snapshot", "file"}:
        raise ValueError("Unsupported watchlist transport.")
    alias = "My IBKR Client Portal/Mobile watchlist" if source_id == "personal" else source_id
    conn.execute(
        """INSERT INTO watchlist_sources(id,alias,authority,provider,mode,status,commit_seq)
                    VALUES (?,?,'external','ibkr',?,'unavailable',?)
                    ON CONFLICT(id) DO NOTHING""",
        (source_id, alias, mode, seq),
    )
    return _row(conn, "watchlist_sources", source_id)


def rename_source(conn, source_id, alias):
    """A display alias can change independently of the external list's local identity."""
    if (
        not isinstance(alias, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 /()_.-]{0,79}", alias)
        or _ACCOUNT.search(alias)
    ):
        raise ValueError("Use a short local list label without account identifiers.")
    with write(conn) as seq:
        if not conn.execute(
            "UPDATE watchlist_sources SET alias=?,commit_seq=? WHERE id=?", (alias, seq, source_id)
        ).rowcount:
            raise ValueError("Unknown watchlist source.")


def _instrument_id(conn, entry, source_id):
    key = _key(entry, source_id)
    row = conn.execute("SELECT id FROM instruments WHERE identity_key=?", (key,)).fetchone()
    by_key = row["id"] if row else None
    if any(not entry[f] for f in LISTING) or entry["security_type"] not in {"STK", "ADR", "ETF"}:
        return by_key
    matches = conn.execute(
        """SELECT id,conid FROM instruments WHERE ticker=?
                              AND listing_exchange=? AND security_type=? AND currency=?""",
        tuple(entry[f] for f in LISTING),
    ).fetchall()
    if len(matches) > 1:
        raise ValueError("The supplied listing has conflicting saved contract bindings.")
    if matches:
        matched = matches[0]
        if (by_key and matched["id"] != by_key) or (
            entry["conid"] and matched["conid"] and entry["conid"] != matched["conid"]
        ):
            raise ValueError("The supplied listing and contract refer to different saved identities.")
        return matched["id"]
    return by_key


def _materialize(conn, values, old, source_id, stamp, seq):
    prev_id = old["id"] if old else None
    key = _key(values, source_id)
    issuer = _issuer(values)
    company_id = old["company_id"] if old and values["conid"] else None
    status = "unclassified" if values["security_type"] not in (None, "STK", "ADR") else "provisional"
    if issuer:
        name, cik, identity_source = issuer
        conn.execute(
            """INSERT INTO companies VALUES(?,?,?,?,?) ON CONFLICT(cik) DO NOTHING""",
            (uid("company"), name, cik, identity_source, seq),
        )
        company_id = conn.execute("SELECT id FROM companies WHERE cik=?", (cik,)).fetchone()[0]
        status = "resolved"
    elif values["security_type"] in ("STK", "ADR") and (values["conid"] or key.startswith("listing:")):
        status = "identified_listing"
    instrument_id = prev_id or uid("ins")
    columns = (
        "identity_key",
        *FIELDS,
        "raw_label",
        "company_id",
        "resolution_status",
        "updated_at",
        "commit_seq",
    )
    data = (
        key,
        *(values[f] for f in FIELDS),
        values["ticker"] or values["conid"],
        company_id,
        status,
        stamp,
        seq,
    )
    if old:
        update = ",".join(f"{col}=?" for col in columns)
        conn.execute(f"UPDATE instruments SET {update} WHERE id=?", (*data, instrument_id))
    else:
        cols = ("id", "provider_namespace", "created_at", *columns)
        conn.execute(
            f"INSERT INTO instruments({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
            (instrument_id, "ibkr", stamp, *data),
        )
    if values["ticker"]:
        conn.execute(
            "INSERT OR IGNORE INTO instrument_aliases VALUES (?,?)", (instrument_id, values["ticker"])
        )
    return instrument_id


def _label(values):
    listing = " · ".join(values[k] for k in LISTING if values[k])
    contract = "IBKR contract " + values["conid"] if values["conid"] else ""
    return " · ".join(filter(None, [listing, contract]))


def _identity_plan(conn, source_id, entries):
    """Resolve once against a locked database. Bind the preview to every touched identity."""
    active = {
        r["id"]: r
        for r in conn.execute(
            """SELECT i.* FROM instruments i JOIN source_memberships m ON m.instrument_id=i.id
           WHERE m.source_id=? AND m.status='active' ORDER BY i.id""",
            (source_id,),
        )
    }
    actions, bindings, resolved = [], [], []
    selected, listings = set(), {}
    weak_symbols = set()
    for entry in entries:
        saved_id = _instrument_id(conn, entry, source_id)
        old = _row(conn, "instruments", saved_id) if saved_id else None
        values = {f: entry[f] or (old[f] if old else None) for f in FIELDS}
        # Routing is source-specific. Preserve the first route on the shared
        # row; each snapshot retains its own observed route in full.
        if old and old["routing_exchange"]:
            values["routing_exchange"] = old["routing_exchange"]
        if old and values != entry:
            _instrument_id(conn, values, source_id)
        key = _key(values, source_id)
        if values["ticker"] == "CASH" and not (
            all(values[k] for k in LISTING) and values["security_type"] in {"STK", "ADR", "ETF"}
        ):
            raise ValueError("A label shared with account reports requires a fully specified stock listing.")
        listing = tuple(values[k] for k in LISTING)
        if all(listing) and values["security_type"] in {"STK", "ETF", "ADR"}:
            if listing in listings and listings[listing] != values["conid"]:
                raise ValueError("The same listing has conflicting supplied contract IDs.")
            listings[listing] = values["conid"]
        if saved_id and saved_id in selected:
            raise ValueError("Several supplied entries would overwrite the same instrument.")
        if saved_id:
            selected.add(saved_id)
        if key.startswith("provisional:"):
            weak_symbols.add(values["ticker"])
        other_sources = []
        if old:
            other_sources = [
                r[0]
                for r in conn.execute(
                    """SELECT source_id FROM source_memberships WHERE instrument_id=? AND status='active'
                   AND source_id!=? ORDER BY source_id""",
                    (saved_id, source_id),
                )
            ]
        corrected = bool(old and any(old[k] and old[k] != values[k] for k in LISTING))
        if old and old["company_id"]:
            issuer = _issuer(values)
            company = _row(conn, "companies", old["company_id"])
            if (issuer and company["cik"] != issuer[1]) or (corrected and not issuer):
                raise ValueError("A saved issuer identity conflicts with the supplied contract metadata.")
        if corrected:
            if other_sources:
                raise ValueError("The correction conflicts with another source's active instrument binding.")
            if not old["company_id"] and _issuer(values):
                raise ValueError("A listing correction cannot assign a different issuer to its history.")
            owns_history = conn.execute(
                "SELECT 1 FROM source_memberships WHERE source_id=? AND instrument_id=?",
                (source_id, saved_id),
            ).fetchone()
            if not owns_history:
                raise ValueError("Only a source with prior membership can propose an identity correction.")
            actions.append(
                {"action": "correct", "instrument_id": saved_id, "label": f"{_label(old)} → {_label(values)}"}
            )
        if saved_id not in active:
            actions.append({"action": "add", "instrument_id": saved_id, "label": _label(values)})
        before = {k: old[k] for k in (*FIELDS, "company_id")} if old else None
        bindings.append([saved_id, before, other_sources, key])
        resolved.append((values, old, corrected))
    weakened = False
    for saved_id, old in active.items():
        if saved_id not in selected:
            actions.append({"action": "remove", "instrument_id": saved_id, "label": _label(old)})
            weakened |= old["ticker"] in weak_symbols and not old["identity_key"].startswith("provisional:")
    encoded = json.dumps([bindings, actions], separators=(",", ":"), sort_keys=True)
    return resolved, actions, hashlib.sha256(encoded.encode()).hexdigest(), weakened


def _activate(conn, snap, seq, resolved, *, confirmation=False):
    source_id, stamp = snap["source_id"], snap["observed_at"]
    for order, (values, old, corrected) in enumerate(resolved):
        if corrected and not confirmation:
            raise ValueError("An instrument correction requires explicit review.")
        instrument_id = _materialize(conn, values, old, source_id, stamp, seq)
        if corrected:
            updated = _row(conn, "instruments", instrument_id)
            conn.execute(
                "INSERT INTO instrument_corrections VALUES(?,?,?,?,?)",
                (
                    snap["id"],
                    old["id"],
                    json.dumps({f: old[f] for f in (*FIELDS, "company_id")}),
                    json.dumps({f: updated[f] for f in (*FIELDS, "company_id")}),
                    seq,
                ),
            )
        conn.execute(
            """INSERT INTO source_memberships VALUES (?,?,?,?,?,'active',?,?)
                        ON CONFLICT(source_id,instrument_id) DO UPDATE SET
                        last_seen_at=excluded.last_seen_at,snapshot_id=excluded.snapshot_id,
                        status='active',display_order=excluded.display_order,commit_seq=excluded.commit_seq""",
            (source_id, instrument_id, stamp, stamp, snap["id"], order, seq),
        )
    conn.execute(
        """UPDATE source_memberships SET status='removed', snapshot_id=?, commit_seq=?
                    WHERE source_id=? AND snapshot_id!=? AND status='active'""",
        (snap["id"], seq, source_id, snap["id"]),
    )
    conn.execute(
        """UPDATE watchlist_sources SET active_snapshot_id=?,last_success_at=?,status='ready',
                    commit_seq=? WHERE id=?""",
        (snap["id"], stamp, seq, source_id),
    )
    conn.execute(
        """UPDATE watchlist_snapshots SET state='complete',accepted_at=?,acceptance=?,commit_seq=?
                    WHERE id=?""",
        (now(), "confirmed" if confirmation else "automatic", seq, snap["id"]),
    )


def import_snapshot(conn, raw, *, complete, source_id="personal", mode="manual_snapshot"):
    """Project before opening a transaction. Rejected input retains only a safe diagnosis."""
    problem = ""
    try:
        entries = _parse(raw)
    except ValueError as exc:
        entries = []
        problem = str(exc)
    return _store_snapshot(conn, entries, source_id, mode, complete, problem)


def import_file(conn, path, *, complete, source_id="personal"):
    try:
        raw = read_file(path)
    except ValueError:
        return _store_snapshot(
            conn,
            [],
            source_id,
            "file",
            complete,
            "Unable to read a stable regular instrument file within the size limit.",
            unavailable=True,
        )
    return import_snapshot(conn, raw, complete=complete, source_id=source_id, mode="file")


def _store_snapshot(conn, entries, source_id, mode, complete, problem, *, unavailable=False):
    if type(complete) is not bool:
        raise ValueError("Declare whether this represents the complete selected list.")
    projected = json.dumps(entries, separators=(",", ":"), sort_keys=True)
    digest = None if problem else hashlib.sha256(projected.encode()).hexdigest()
    with write(conn) as seq:
        source = _source(conn, source_id, mode, seq)
        try:
            resolved, affected, binding_hash, weakened = _identity_plan(conn, source_id, entries)
        except ValueError as exc:
            entries, projected, digest = [], "[]", None
            resolved, affected, binding_hash, weakened = [], [], None, False
            problem = str(exc)
        prev = _row(conn, "watchlist_snapshots", source["last_observation_id"])
        stamp = now()
        if (
            prev
            and prev["content_hash"] == digest
            and prev["membership_complete"] == complete
            and (digest is not None or prev["reason"] == problem)
            and prev["mode"] == mode
        ):
            if prev["state"] == "complete":
                conn.execute(
                    "UPDATE watchlist_sources SET last_success_at=?,commit_seq=? WHERE id=?",
                    (stamp, seq, source_id),
                )
                return _snapshot(conn, prev["id"])
            saved = conn.execute(
                "SELECT bindings_hash FROM watchlist_previews WHERE snapshot_id=?", (prev["id"],)
            ).fetchone()
            if (prev["state"] == "rejected" and problem) or (
                prev["state"] == "candidate" and saved and saved["bindings_hash"] == binding_hash
            ):
                return _snapshot(conn, prev["id"])
        added = sum(a["action"] == "add" for a in affected)
        removed = sum(a["action"] == "remove" for a in affected)
        active_count = conn.execute(
            "SELECT count(*) FROM source_memberships WHERE source_id=? AND status='active'", (source_id,)
        ).fetchone()[0]
        if problem:
            state, reason = "rejected", problem
            added = removed = 0
        elif not complete:
            state, reason = "candidate", "Partial observation. Supply a complete selected list."
        elif not entries:
            state, reason = "candidate", "Empty replacement requires review."
        elif any(a["action"] == "correct" for a in affected):
            state, reason = "candidate", "Review the proposed correction to a saved instrument identity."
        elif weakened:
            state, reason = "candidate", "Replacement omits identifiers from a previously identified listing."
        elif active_count and removed >= active_count / 2:
            state, reason = "candidate", "Replacement removes at least half the active membership."
        else:
            state, reason = "candidate", ""
        snap_id = uid("snapshot")
        conn.execute(
            """INSERT INTO watchlist_snapshots
            (id,source_id,base_snapshot_id,observed_at,mode,content_hash,entries,membership_complete,
             state,reason,added,removed,commit_seq) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                snap_id,
                source_id,
                source["active_snapshot_id"],
                stamp,
                mode,
                digest,
                projected,
                int(complete),
                state,
                reason,
                added,
                removed,
                seq,
            ),
        )
        status = "unavailable" if unavailable else "needs_review"
        conn.execute(
            """UPDATE watchlist_sources SET mode=?,last_observation_id=?,status=?,
                        commit_seq=? WHERE id=?""",
            (mode, snap_id, status, seq, source_id),
        )
        if state == "candidate" and reason:
            conn.execute(
                "INSERT INTO watchlist_previews VALUES(?,?,?)", (snap_id, binding_hash, json.dumps(affected))
            )
        if not reason:
            _activate(conn, _snapshot(conn, snap_id), seq, resolved)
        return _snapshot(conn, snap_id)


def accept_candidate(conn, snapshot_id):
    with write(conn) as seq:
        row = _row(conn, "watchlist_snapshots", snapshot_id)
        if not row:
            raise ValueError("Unknown snapshot.")
        snap = _snapshot(conn, snapshot_id)
        source = _row(conn, "watchlist_sources", snap["source_id"])
        if source["active_snapshot_id"] == snapshot_id:
            return snap
        if (
            snap["state"] != "candidate"
            or not snap["membership_complete"]
            or source["last_observation_id"] != snapshot_id
            or source["active_snapshot_id"] != snap["base_snapshot_id"]
        ):
            raise ValueError("Only the latest complete replacement candidate can be confirmed.")
        preview = conn.execute(
            "SELECT bindings_hash FROM watchlist_previews WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
        try:
            resolved, _, current_hash, _ = _identity_plan(conn, snap["source_id"], snap["entries"])
            if not preview or current_hash != preview["bindings_hash"]:
                raise ValueError("Identity bindings changed. Import a fresh snapshot before confirmation.")
        except ValueError as exc:
            conn.execute(
                "UPDATE watchlist_snapshots SET state='rejected',reason=?,commit_seq=? WHERE id=?",
                (str(exc), seq, snapshot_id),
            )
            return _snapshot(conn, snapshot_id)
        _activate(conn, snap, seq, resolved, confirmation=True)
        return _snapshot(conn, snapshot_id)


_INSTRUMENTS = """SELECT i.*, c.name AS company_name,c.cik,c.identity_source
                  FROM instruments i LEFT JOIN companies c ON c.id=i.company_id"""


def _with_sources(conn, row):
    result = dict(row)
    result.pop("identity_key")
    result["source_ids"] = [
        r[0]
        for r in conn.execute(
            """SELECT source_id FROM source_memberships WHERE instrument_id=? AND status='active'
           ORDER BY source_id""",
            (row["id"],),
        )
    ]
    return result


def instrument(conn, instrument_id, *, active=True):
    row = conn.execute(_INSTRUMENTS + " WHERE i.id=?", (instrument_id,)).fetchone()
    if row is None:
        raise ValueError("Unknown instrument.")
    selected = _with_sources(conn, row)
    if active and not selected["source_ids"]:
        raise ValueError("Instrument is outside active watchlist membership.")
    return selected


def _text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("Supply nonempty research text within the field limit.")
    return value.strip()


def create_theme(conn, name, question):
    """A user-owned research question; creating it has no impact on source membership."""
    name, question = _text(name, 120), _text(question, 2000)
    with write(conn) as seq:
        theme_id = uid("theme")
        if conn.execute("SELECT 1 FROM themes WHERE name=?", (name,)).fetchone():
            raise ValueError("A theme with that name already exists.")
        conn.execute("INSERT INTO themes VALUES(?,?,?,'user',?,?)", (theme_id, name, question, now(), seq))
        return theme_id


def _passage_refs(conn, evidence_ids):
    if not isinstance(evidence_ids, (tuple, list)) or len(evidence_ids) > 50:
        raise ValueError("Supply up to 50 saved passage IDs.")
    for ref in evidence_ids:
        if not isinstance(ref, str) or not _row(conn, "evidence_passages", ref):
            raise ValueError("Unknown evidence passage.")
    return json.dumps(list(dict.fromkeys(evidence_ids)))


def link_theme(
    conn, theme_id, *, reason, company_id=None, instrument_id=None, proposed=False, evidence_ids=()
):
    reason = _text(reason, 2000)
    if bool(company_id) == bool(instrument_id):
        raise ValueError("Select a single company or instrument for this theme.")
    with write(conn) as seq:
        if not _row(conn, "themes", theme_id):
            raise ValueError("Unknown theme.")
        subject = (
            _row(conn, "companies", company_id) if company_id else _row(conn, "instruments", instrument_id)
        )
        if not subject:
            raise ValueError("Unknown theme subject.")
        link_id = uid("theme_member")
        refs = _passage_refs(conn, evidence_ids)
        conn.execute(
            """INSERT INTO theme_memberships VALUES(?,?,?,?,'research_subject',?,?,'user',?,?)""",
            (
                link_id,
                theme_id,
                company_id,
                instrument_id,
                reason,
                refs,
                "proposed" if proposed else "accepted",
                seq,
            ),
        )
        return link_id


def record_exposure(
    conn,
    from_company_id,
    to_company_id,
    *,
    relation,
    uncertainty,
    valid_from=None,
    valid_until=None,
    evidence_ids=(),
    supported=False,
):
    relation, uncertainty = _text(relation, 120), _text(uncertainty, 2000)
    start = instant(valid_from) if valid_from is not None else None
    end = instant(valid_until) if valid_until is not None else None
    if (start and end and end <= start) or (supported and not (start and evidence_ids)):
        raise ValueError("A supported relationship needs a valid interval and dated evidence.")
    with write(conn) as seq:
        if (
            from_company_id == to_company_id
            or not _row(conn, "companies", from_company_id)
            or not _row(conn, "companies", to_company_id)
        ):
            raise ValueError("Select two distinct saved companies.")
        refs = _passage_refs(conn, evidence_ids)
        exposure_id = uid("exposure")
        conn.execute(
            "INSERT INTO exposures VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                exposure_id,
                from_company_id,
                to_company_id,
                relation,
                start,
                end,
                refs,
                uncertainty,
                "supported" if supported else "proposed",
                seq,
            ),
        )
        return exposure_id


def universe(conn):
    sources, candidates = [], []
    for row in conn.execute("SELECT * FROM watchlist_sources ORDER BY id"):
        source = dict(row)
        observed = source["last_success_at"]
        source["stale"] = not observed or datetime.now(UTC) - datetime.fromisoformat(observed) > timedelta(
            days=7
        )
        if source["status"] == "ready" and source["stale"]:
            source["status"] = "stale"
        sources.append(source)
        if source["last_observation_id"] != source["active_snapshot_id"]:
            candidates.append(_snapshot(conn, source["last_observation_id"]))
    instruments = [
        _with_sources(conn, row)
        for row in conn.execute(
            _INSTRUMENTS
            + """ WHERE EXISTS (SELECT 1 FROM source_memberships sm
                          WHERE sm.instrument_id=i.id AND sm.status='active') ORDER BY i.raw_label,i.id"""
        )
    ]
    return {
        "sources": sources,
        "instruments": instruments,
        "candidates": candidates,
        "themes": [dict(r) for r in conn.execute("SELECT * FROM themes ORDER BY name")],
        "theme_memberships": [dict(r) for r in conn.execute("SELECT * FROM theme_memberships ORDER BY id")],
        "exposures": [dict(r) for r in conn.execute("SELECT * FROM exposures ORDER BY id")],
    }
