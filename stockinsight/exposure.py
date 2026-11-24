"""Operator-reviewed, evidence-scoped relationships used to assess named watchlist events."""

import hashlib
import json
import re
from datetime import date
from urllib.parse import urlsplit

from . import evidence, sources_calendar, universe
from .db import is_fixture, now, uid, write

SCHEMA = """
CREATE TABLE exposure_proposals(
    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
    instrument_id TEXT NOT NULL REFERENCES instruments, entity_type TEXT NOT NULL, entity TEXT NOT NULL,
    relation TEXT NOT NULL, trigger_kind TEXT NOT NULL, counterparty_id TEXT REFERENCES instruments,
    theme_id TEXT REFERENCES themes, legacy_id TEXT REFERENCES exposures,
    passage_id TEXT NOT NULL REFERENCES evidence_passages, quotation TEXT NOT NULL, rationale TEXT NOT NULL,
    expires_on TEXT, created_at TEXT NOT NULL, commit_seq INTEGER NOT NULL REFERENCES commits
);
CREATE TABLE exposure_decisions(
    id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES exposure_proposals,
    state TEXT NOT NULL CHECK(state IN ('approved','revoked')), actor TEXT NOT NULL CHECK(actor='user'),
    observed_at TEXT NOT NULL, reason TEXT NOT NULL, commit_seq INTEGER NOT NULL REFERENCES commits,
    UNIQUE(proposal_id,state)
);
CREATE INDEX exposure_listing_trigger ON exposure_proposals(instrument_id,trigger_kind);
"""

RELATIONS = {
    "supplier": ("Supplier", r"supplier[s]?|suppl(?:y|ies|ied|ying)|manufactur(?:er|ers|ing)"),
    "customer": ("Customer", r"customers?|clients?|purchas(?:es|ed|ing)|buyers?"),
    "competitor": ("Competitor", r"compet(?:es?|ing|ition|itors?|itive)"),
    "geographic": (
        "Geographic dependence",
        r"revenues?|sales|operations?|markets?|manufacturing|production|customers?",
    ),
    "policy": (
        "Policy or regulatory exposure",
        r"polic(?:y|ies)|regulat(?:ion|ions|ory|ed|or)|restrictions?|controls?|tariffs?|rates?|sanctions?|investigat(?:es|ion|ions|ing)",
    ),
    "shared_demand": (
        "Shared demand driver",
        r"demand|spending|depend(?:s|ent|ence)|investments?|capacity|consumption",
    ),
}
KINDS = {
    "issuer_announcement": ("Issuer announcement", {"issuer_news"}),
    "earnings_release": ("Earnings release", {"issuer", "msft_release"}),
    "financial_filing": ("Reported financial filing", {"sec"}),
    "filed_disclosure": ("Filed 8-K item", {"sec_filing"}),
    "regulatory_notice": ("Regulatory notice", {"cma_news"}),
    "shareholder_meeting": ("Shareholder meeting", {"msft_calendar"}),
    "monetary_policy_meeting": ("Federal Reserve policy meeting", {"fed_calendar"}),
    "inflation_release": ("US CPI release", {"bls_calendar"}),
    "employment_release": ("US employment release", {"bls_calendar"}),
}
MACRO = {
    "monetary_policy_meeting": ("Federal Reserve", "FOMC", "US policy rates", "US interest rates"),
    "inflation_release": ("US inflation", "Consumer Price Index", "US CPI"),
    "employment_release": ("US employment", "US labor market", "Employment Situation"),
}
ENTITY_TYPES = {
    "entity": "Named entity",
    "company": "Watched company",
    "theme": "Research theme",
    "geography": "Geography",
    "policy": "Named policy",
}


def _text(value, name, maximum, *, minimum=1):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ValueError(f"Choose a valid {name}.")
    return value.strip()


def _contains(text, phrase):
    return (
        re.search(
            r"(?<!\w)" + re.escape(" ".join(phrase.split())) + r"(?!\w)",
            " ".join(text.split()),
            re.IGNORECASE,
        )
        is not None
    )


def _clauses(text):
    return re.split(r"[;!?]\s*|\.\s+|\n+", text)


def _supported(quotation, names, relation):
    for clause in _clauses(quotation):
        if not any(_contains(clause, name) for name in names):
            continue
        if not re.search(r"\b(?:" + RELATIONS[relation][1] + r")\b", clause, re.IGNORECASE):
            continue
        if re.search(
            r"\b(no longer|never|not|ceased|terminated|former|previously|expired|unrelated|could become|might become|denies|denied)\b",
            clause,
            re.IGNORECASE,
        ):
            continue
        action = {"supplier": r"suppl(?:y|ies|ied)", "customer": r"(?:buys?|purchas(?:e|es|ed))\s+from"}.get(
            relation
        )
        if action and any(
            re.search(
                r"\b(?:we|the company)\s+" + action + r"\s+(?:to\s+)?" + re.escape(name) + r"\b",
                clause,
                re.IGNORECASE,
            )
            for name in names
        ):
            continue
        return True
    return False


def _passage(conn, listing, ref):
    row = conn.execute(
        """SELECT p.id,p.text,p.locator,p.financial,d.id AS document_id,d.origin,d.title,d.source_url,
                      d.version_hash,d.fixture,d.received_at,d.retention,
                      (SELECT id FROM source_checks s WHERE s.document_id=d.id AND s.instrument_id=d.instrument_id
                       AND s.status='ok' AND s.provider=d.origin ORDER BY s.finished_at DESC LIMIT 1) AS receipt
                      FROM evidence_passages p JOIN documents d ON d.id=p.document_id WHERE p.id=? AND d.instrument_id=?
                      AND d.fixture=? AND p.available_at<=? AND NOT EXISTS(SELECT 1 FROM documents n
                         WHERE n.instrument_id=d.instrument_id AND n.origin=d.origin AND n.source_url=d.source_url
                         AND n.fixture=d.fixture AND n.commit_seq>d.commit_seq)""",
        (ref, listing, is_fixture(conn), now()),
    ).fetchone()
    if not row or not re.fullmatch(r"[0-9a-f]{64}", row["version_hash"]):
        return None
    row = dict(row)
    if not row["fixture"] and urlsplit(row["source_url"]).scheme != "https":
        return None
    if row["retention"] == "verified_excerpt_and_hash":
        # Several excerpt streams can refer to different paragraphs of one publisher edition.
        route, _, digest = row["origin"].partition(".")
        if (
            route not in {"nvda_excerpt", "msft_excerpt", "msft_transcript", "retained_filing"}
            or digest != hashlib.sha256(row["text"].encode()).hexdigest()
        ):
            return None
        newest = conn.execute(
            """SELECT version_hash FROM documents WHERE instrument_id=? AND source_url=?
                               AND fixture=? ORDER BY commit_seq DESC LIMIT 1""",
            (listing, row["source_url"], row["fixture"]),
        ).fetchone()
        if newest[0] != row["version_hash"]:
            return None
        if not row["fixture"]:
            receipt = conn.execute(
                """SELECT s.id,d.id AS original,d.retention FROM source_checks s JOIN documents d ON d.id=s.document_id
                    WHERE s.instrument_id=? AND d.instrument_id=s.instrument_id AND s.status='ok' AND d.fixture=0
                    AND d.source_url=? AND d.version_hash=? AND ((d.id=? AND s.provider=?) OR
                        (d.retention='full' AND s.provider=d.origin AND d.origin IN ('sec_filing','issuer','msft_release','msft_transcript')))
                    ORDER BY (d.retention='full') DESC,s.finished_at DESC LIMIT 1""",
                (listing, row["source_url"], row["version_hash"], row["document_id"], route),
            ).fetchone()
            if not receipt:
                return None
            row["receipt"] = receipt["id"]
            if receipt["retention"] == "full":
                try:
                    evidence.document_bytes(conn, listing, receipt["original"])
                except (OSError, ValueError):
                    return None
    elif row["retention"] == "full":
        try:
            evidence.document_bytes(conn, listing, row["document_id"])
        except (OSError, ValueError):
            return None
    if not row["fixture"] and not row["receipt"]:
        return None
    row["publisher_url"] = row["source_url"]
    if row["origin"] in {"issuer_news", "cma_news"}:
        try:
            row["publisher_url"] = json.loads(row["locator"]).get("link") or row["source_url"]
        except (ValueError, AttributeError):
            pass
    return row


def _names(item):
    name = item.get("company_name") or item.get("raw_label") or item["ticker"]
    shortened = re.sub(
        r"[\s,]+(?:corporation|incorporated|inc\.?|corp\.?|plc)\.?$", "", name, flags=re.IGNORECASE
    ).strip()
    return tuple(
        dict.fromkeys(v for v in (name, shortened, "$" + item["ticker"] if item.get("ticker") else None) if v)
    )


def _target(conn, listing, data):
    kind = data.get("entity_type")
    if kind not in ENTITY_TYPES:
        raise ValueError("Choose the kind of entity or theme.")
    counterparty = theme = None
    if kind == "company":
        counterparty = universe.instrument(conn, data.get("counterparty", ""))
        if not counterparty.get("company_id") or counterparty["company_id"] == listing["company_id"]:
            raise ValueError("Choose a distinct resolved counterparty issuer.")
        names = _names(counterparty)
    elif kind == "theme":
        theme = conn.execute("SELECT id,name FROM themes WHERE id=?", (data.get("theme"),)).fetchone()
        if not theme:
            raise ValueError("Choose a saved research theme.")
        names = (theme["name"],)
    else:
        name = _text(data.get("entity"), "named subject", 100, minimum=2)
        if not re.search(r"\w", name) or name.casefold() in {
            "company",
            "issuer",
            "entity",
            "policy",
            "market",
            "customer",
            "supplier",
            "geography",
            "theme",
        }:
            raise ValueError("Identify a specific subject.")
        names = (name,)
    return kind, names, counterparty, theme


def _propose(conn, data):
    relation, trigger = data.get("relation"), data.get("trigger_kind")
    if relation not in RELATIONS or trigger not in KINDS:
        raise ValueError("Choose a supported relationship and trigger.")
    rationale = _text(data.get("rationale"), "reason", 900)
    expires = data.get("expires_on") or None
    if expires and (
        not isinstance(expires, str)
        or date.fromisoformat(expires).isoformat() != expires
        or expires < now()[:10]
    ):
        raise ValueError("Choose a valid current or future expiry day.")
    with write(conn) as seq:
        listing = universe.instrument(conn, data.get("instrument_id", ""))
        kind, names, other, theme = _target(conn, listing, data)
        passage = _passage(conn, listing["id"], data.get("passage_id", ""))
        if not passage or passage["financial"]:
            raise ValueError("Use a current narrative passage for the selected listing.")
        quote = data.get("quotation") or passage["text"]
        if (
            not isinstance(quote, str)
            or not 1 <= len(quote.strip()) <= 2400
            or quote.strip() not in passage["text"]
        ):
            raise ValueError("Choose an exact, bounded quotation from this passage.")
        quote = quote.strip()
        if not any(
            _supported(part, names, relation)
            and any(
                part in clause and _supported(clause, names, relation) for clause in _clauses(passage["text"])
            )
            for part in _clauses(quote)
        ):
            raise ValueError("The quotation must name the subject and describe the selected relationship.")
        entity = names[0]
        legacy = None
        if other and listing.get("company_id"):
            legacy = conn.execute(
                """SELECT e.id FROM exposures e WHERE e.from_company_id=? AND e.to_company_id=?
                                AND e.relation=? AND EXISTS(SELECT 1 FROM json_each(e.evidence_refs) WHERE value=?)
                                ORDER BY e.commit_seq DESC LIMIT 1""",
                (listing["company_id"], other["company_id"], relation, passage["id"]),
            ).fetchone()
        values = (
            listing["id"],
            kind,
            entity,
            relation,
            trigger,
            other["id"] if other else None,
            theme["id"] if theme else None,
            legacy["id"] if legacy else None,
            passage["id"],
            quote,
            rationale,
            expires,
        )
        fingerprint = hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()
        conn.execute(
            """INSERT INTO exposure_proposals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(fingerprint) DO NOTHING""",
            (uid("relationship"), fingerprint, *values, now(), seq),
        )


def _state(conn, ident):
    row = conn.execute(
        "SELECT state,observed_at FROM exposure_decisions WHERE proposal_id=? ORDER BY commit_seq DESC LIMIT 1",
        (ident,),
    ).fetchone()
    return (row["state"], row["observed_at"]) if row else ("proposed", None)


def _in_effect(conn, proposal):
    stamp = now()
    if proposal["expires_on"] and proposal["expires_on"] < stamp[:10]:
        return False
    if not proposal["legacy_id"]:
        return True
    return bool(
        conn.execute(
            """SELECT 1 FROM exposures WHERE id=? AND (valid_from IS NULL OR valid_from<=?)
                            AND (valid_until IS NULL OR valid_until>?)""",
            (proposal["legacy_id"], stamp, stamp),
        ).fetchone()
    )


def _decide(conn, data, state):
    with write(conn) as seq:
        proposal = conn.execute(
            "SELECT * FROM exposure_proposals WHERE id=?", (data.get("proposal"),)
        ).fetchone()
        if not proposal:
            raise ValueError("Choose a saved relationship.")
        previous, _ = _state(conn, proposal["id"])
        if previous == state:
            return
        if previous == "revoked":
            raise ValueError("A withdrawn relationship requires a new review proposal.")
        if state == "approved":
            universe.instrument(conn, proposal["instrument_id"])
            if proposal["counterparty_id"]:
                universe.instrument(conn, proposal["counterparty_id"])
            if not _in_effect(conn, proposal) or not _passage(
                conn, proposal["instrument_id"], proposal["passage_id"]
            ):
                raise ValueError("The cited edition is no longer current and verified.")
            reason = "The operator reviewed the quoted evidence and approved the proposed trigger."
        else:
            reason = _text(data.get("reason"), "withdrawal reason", 600)
        conn.execute(
            "INSERT INTO exposure_decisions VALUES(?,?,?,'user',?,?,?)",
            (uid("exposure_review"), proposal["id"], state, now(), reason, seq),
        )


def action(conn, action, data):
    if action == "exposure-propose":
        _propose(conn, data)
    elif action in ("exposure-approve", "exposure-revoke"):
        _decide(conn, data, "approved" if action == "exposure-approve" else "revoked")
    else:
        raise ValueError("Unknown relationship action.")
    return "/exposures"


def _approved(conn, listing_id, trigger=None):
    return conn.execute(
        """SELECT p.*,a.observed_at AS approved_at FROM exposure_proposals p JOIN exposure_decisions a
                          ON a.proposal_id=p.id AND a.state='approved' WHERE p.instrument_id=? AND (? IS NULL OR p.trigger_kind=?)
                          AND NOT EXISTS(SELECT 1 FROM exposure_decisions r WHERE r.proposal_id=p.id AND r.state='revoked')""",
        (listing_id, trigger, trigger),
    )


def monitor_targets(conn, subject_listing):
    """List only eligible issuer routes needed for current, explicitly approved counterparties."""
    try:
        subject = universe.instrument(
            conn, subject_listing if isinstance(subject_listing, str) else subject_listing["id"]
        )
    except ValueError:
        return []
    selected = {}
    for proposal in _approved(conn, subject["id"]):
        kind = proposal["trigger_kind"]
        if (
            not proposal["counterparty_id"]
            or kind not in KINDS
            or kind in MACRO
            or not _in_effect(conn, proposal)
        ):
            continue
        try:
            peer = universe.instrument(conn, proposal["counterparty_id"])
        except ValueError:
            continue
        if not _passage(conn, subject["id"], proposal["passage_id"]):
            continue
        routes = {"issuer"} if is_fixture(conn) else sources_calendar.recommended(peer).keys()
        for provider in KINDS[kind][1].intersection(routes):
            if sources_calendar.eligible(peer, provider):
                selected[peer["id"], provider] = (peer, provider)
    return [selected[key] for key in sorted(selected)]


def for_event(conn, listing, event_version_id):
    try:
        listing = universe.instrument(conn, listing["id"] if not isinstance(listing, str) else listing)
    except ValueError:
        return []
    event = conn.execute(
        """SELECT e.* FROM event_versions e WHERE e.id=? AND e.state NOT IN ('unknown','cancelled')
                       AND NOT EXISTS(SELECT 1 FROM event_versions newer WHERE newer.supersedes=e.id)""",
        (event_version_id,),
    ).fetchone()
    if not event or event["kind"] not in KINDS:
        return []
    observed = _passage(conn, event["instrument_id"], event["source_ref"])
    if not observed or observed["origin"] not in KINDS[event["kind"]][1]:
        return []
    result = []
    for p in _approved(conn, listing["id"], event["kind"]):
        if not _in_effect(conn, p):
            continue
        names = (p["entity"],)
        if p["counterparty_id"]:
            try:
                other = universe.instrument(conn, p["counterparty_id"])
            except ValueError:
                continue
            if event["instrument_id"] not in (listing["id"], other["id"]):
                continue
            names = _names(other)
        elif event["instrument_id"] != listing["id"]:
            continue
        exact_issuer = p["counterparty_id"] == event["instrument_id"] and event["kind"] in {
            "issuer_announcement",
            "earnings_release",
            "financial_filing",
            "filed_disclosure",
            "shareholder_meeting",
        }
        macro = event["kind"] in MACRO and p["entity"].casefold() in {
            a.casefold() for a in MACRO[event["kind"]]
        }
        if not exact_issuer and not macro and not any(_contains(observed["text"], name) for name in names):
            continue
        support = _passage(conn, listing["id"], p["passage_id"])
        if (
            not support
            or support["version_hash"] == observed["version_hash"]
            or support["publisher_url"] == observed["publisher_url"]
            or support["receipt"]
            and support["receipt"] == observed["receipt"]
            or " ".join(support["text"].split()).casefold() == " ".join(observed["text"].split()).casefold()
        ):
            continue
        result.append(
            {
                "id": p["id"],
                "entity": p["entity"],
                "relation": p["relation"],
                "reason": p["rationale"],
                "quotation": p["quotation"],
                "passage_id": p["passage_id"],
                "event_passage_id": observed["id"],
                "approved_at": p["approved_at"],
                "underlying_document": support["document_id"],
                "source_receipt": support["receipt"],
                "event_receipt": observed["receipt"],
                "legacy_id": p["legacy_id"],
            }
        )
    return result


def _candidates(conn, listings, themes):
    from . import goals

    scope_ids = {item["id"] for plan in goals.active(conn) for item in goals.listings(conn, plan["scope"])}
    if not scope_ids:
        return []
    named = [("theme", t["name"], (t["name"],), None, t["id"]) for t in themes]
    named += [
        ("geography", name, (name,), None, None)
        for name in ("China", "Taiwan", "Japan", "European Union", "United Kingdom", "United States")
    ]
    named += [
        ("policy", name, (name,), None, None)
        for name in ("export controls", "Federal Reserve", "US interest rates", "US inflation")
    ]
    candidates = []
    companies = {i["id"]: i for i in listings}
    for item in listings:
        if item["id"] not in scope_ids:
            continue
        peers = [
            ("company", _names(i)[0], _names(i), i["id"], None)
            for i in companies.values()
            if i.get("company_id") and i["company_id"] != item["company_id"]
        ]
        recent = conn.execute(
            """SELECT e.id,e.kind,e.source_ref FROM event_versions e WHERE e.instrument_id=?
                            AND e.state NOT IN ('cancelled','unknown') AND NOT EXISTS(SELECT 1 FROM event_versions x WHERE x.supersedes=e.id)
                            ORDER BY e.commit_seq DESC,e.id LIMIT 35""",
            (item["id"],),
        )
        for event in recent:
            passage = _passage(conn, item["id"], event["source_ref"])
            if (
                not passage
                or event["kind"] not in KINDS
                or passage["origin"] not in KINDS[event["kind"]][1]
                or passage["financial"]
                or len(passage["text"]) > 2400
            ):
                continue
            for kind, name, names, other, theme in [*peers, *named]:
                if not any(_contains(passage["text"], n) for n in names):
                    continue
                options = {
                    "geography": ("geographic",),
                    "policy": ("policy",),
                    "theme": ("shared_demand", "policy"),
                    "company": ("supplier", "customer", "competitor", "shared_demand"),
                }[kind]
                relation = next((r for r in options if _supported(passage["text"], names, r)), None)
                if relation:
                    candidates.append(
                        {
                            "listing": item,
                            "entity_type": kind,
                            "entity": name,
                            "relation": relation,
                            "counterparty": other,
                            "theme": theme,
                            "passage": passage,
                            "event_id": event["id"],
                            "trigger_kind": event["kind"],
                        }
                    )
                    break
            if len(candidates) >= 24:
                return candidates
    return candidates


def dashboard(conn):
    saved = universe.universe(conn)
    choices = []
    for item in saved["instruments"]:
        refs = conn.execute(
            """SELECT p.id FROM evidence_passages p JOIN documents d ON d.id=p.document_id WHERE
                          d.instrument_id=? AND p.financial IS NULL AND d.fixture=? AND NOT EXISTS(SELECT 1 FROM documents n
                          WHERE n.instrument_id=d.instrument_id AND n.origin=d.origin AND n.source_url=d.source_url AND n.commit_seq>d.commit_seq)
                          ORDER BY d.commit_seq DESC,p.locator LIMIT 20""",
            (item["id"], is_fixture(conn)),
        )
        passages = [p for r in refs if (p := _passage(conn, item["id"], r[0]))]
        choices.append({"listing": item, "passages": passages})
    proposals = []
    for row in conn.execute("""SELECT p.*,i.ticker,d.title,d.origin,d.source_url,d.version_hash,d.received_at FROM exposure_proposals p
                            JOIN instruments i ON i.id=p.instrument_id JOIN evidence_passages ep ON ep.id=p.passage_id
                            JOIN documents d ON d.id=ep.document_id ORDER BY p.commit_seq DESC"""):
        active = any(i["id"] == row["instrument_id"] for i in saved["instruments"])
        current = _in_effect(conn, row) and bool(_passage(conn, row["instrument_id"], row["passage_id"]))
        decisions = [
            dict(d)
            for d in conn.execute(
                "SELECT * FROM exposure_decisions WHERE proposal_id=? ORDER BY commit_seq DESC", (row["id"],)
            )
        ]
        proposals.append(
            {
                **dict(row),
                "decisions": decisions,
                "state": decisions[0]["state"] if decisions else "proposed",
                "current": current,
                "active": active,
            }
        )
    return {
        "choices": choices,
        "instruments": saved["instruments"],
        "themes": saved["themes"],
        "proposals": proposals,
        "candidates": _candidates(conn, saved["instruments"], saved["themes"]),
        "relations": {k: v[0] for k, v in RELATIONS.items()},
        "entity_types": ENTITY_TYPES,
        "trigger_kinds": {k: v[0] for k, v in KINDS.items()},
    }
