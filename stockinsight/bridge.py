"""Assignment-scoped domain operations and their service-recorded receipts."""

import json
import re

from . import announcement_research, evidence, gaps, providers
from .db import is_fixture, now, uid, write
from .research import authorized, encode, renew

SEARCH_LIMIT = 24
GAPS = {
    "historical_consensus": (
        "history_missing",
        "A pre-release Street surprise cannot be measured.",
        "Compare the issuer's reported periods.",
        "Verify access to a timestamped historical consensus series.",
        "Return an estimate captured before the release for the same fiscal period, basis and currency.",
    ),
    "price_context": (
        "not_connected",
        "The reported decline, its interval and entry timing remain unverified.",
        "Limit analysis to dated company evidence.",
        "Connect a permitted instrument-level price series.",
        "Return aligned observations, currency, adjustment basis, delay, benchmark and market session.",
    ),
    "search_evidence": (
        "history_missing",
        "The retrieved passages have not established the requested observations for this listing and cutoff.",
        "Keep the question open.",
        "Capture a permitted primary source with verified availability.",
        "Retrieve a versioned, relevant passage available by the case cutoff.",
    ),
    "compare_financials": (
        "semantics_unverified",
        "A like-for-like financial difference could not be computed.",
        "Read the separate issuer observations.",
        "Obtain inputs with compatible financial definitions.",
        "Return a reproducible comparison with both exact input versions and bases.",
    ),
    "capture_public": (
        "temporarily_unavailable",
        "The requested primary source could not be verified.",
        "Use eligible saved passages.",
        "Review the source adapter's access and retry after its cooldown.",
        "Retain a newly checked primary-source version under the resolved issuer identity.",
    ),
}

TOOLS = {
    "list_capabilities": "Inspect the research tools available to this assignment.",
    "search_evidence": "Read saved passages for this instrument and its information cutoff.",
    "next_evidence_page": "Continue a scoped search at its frozen commit boundary using the previous page's next_cursor.",
    "get_evidence": "Read one exact passage and its provenance by id.",
    "compare_financials": "Compare two returned observations with explicit financial semantics.",
    "historical_consensus": "Check access to pre-release Street consensus.",
    "price_context": "Check access to timed prices for the case instrument.",
    "capture_public": "Capture a release or financial fact from an approved issuer or SEC route.",
    "record_gap": "Record a missing metric and fiscal period against this run's latest scoped evidence search.",
}
PARAMETERS = {
    "list_capabilities": set(),
    "search_evidence": set(),
    "next_evidence_page": {"cursor"},
    "get_evidence": {"id"},
    "compare_financials": {"current", "baseline", "kind"},
    "historical_consensus": set(),
    "price_context": set(),
    "capture_public": {"provider"},
    "record_gap": {"metric", "period", "attempt_receipt_id"},
}


class Bridge:
    def __init__(self, db, lease):
        self.db = db
        self.lease = lease
        self.context = json.loads(authorized(db, lease)["context"])
        self.fixture = is_fixture(db)

    def catalog(self):
        return [
            {
                "id": name,
                "description": desc,
                "status": "limited" if name in ("price_context", "historical_consensus") else "available",
            }
            for name, desc in TOOLS.items()
            if name != "capture_public" or not self.fixture
        ]

    def _passage(self, passage_id):
        # Access to an exact record requires the id to have been returned within
        # this run. Knowing an id from another question grants no read authority.
        rows = self.db.execute(
            "SELECT output FROM receipts WHERE run_id=? AND status='ok'", (self.lease.run_id,)
        )
        if not any(passage_id in json.loads(row[0])["evidence_ids"] for row in rows):
            raise ValueError("Passage outside the run read-set")
        return evidence.get(
            self.db,
            self.context["instrument"]["id"],
            passage_id,
            self.context["cutoff"],
            fixture=self.fixture,
        )

    def _perform(self, name, args):
        if name == "list_capabilities":
            return "ok", {"capabilities": self.catalog(), "providers": providers.capabilities()}, []
        if name in ("search_evidence", "next_evidence_page"):
            if name == "next_evidence_page":
                row = self.db.execute(
                    "SELECT output FROM receipts WHERE id=? AND run_id=? AND tool IN ('search_evidence','next_evidence_page') AND status='ok'",
                    (args["cursor"], self.lease.run_id),
                ).fetchone()
                prior = json.loads(row[0])["data"] if row else {}
                if prior.get("next_cursor") != args["cursor"] or not prior.get("has_more"):
                    raise ValueError("Cursor unavailable for this search and assignment.")
                page, watermark = prior["page"] + 1, prior["evidence_commit_seq"]
            else:
                page = 1
                watermark = self.db.execute("SELECT max(seq) FROM commits").fetchone()[0]
            matches = evidence.search(
                self.db,
                self.context["instrument"]["id"],
                self.context["cutoff"],
                fixture=self.fixture,
                commit_seq=watermark,
                origin="issuer_news" if self.context.get("method") == announcement_research.METHOD else None,
                limit=SEARCH_LIMIT + 1,
                offset=(page - 1) * SEARCH_LIMIT,
            )
            found = matches[:SEARCH_LIMIT]
            data = {
                "passages": found,
                "limit": SEARCH_LIMIT,
                "has_more": len(matches) > SEARCH_LIMIT,
                "page": page,
                "evidence_commit_seq": watermark,
            }
            return "ok" if found else "partial", data, [p["id"] for p in found]
        if name == "get_evidence":
            passage = self._passage(args["id"])
            return "ok", passage, [passage["id"]]
        if name == "compare_financials":
            a, b = self._passage(args["current"]), self._passage(args["baseline"])
            result = evidence.compare(a, b, args["kind"])
            return "ok", result, [a["id"], b["id"]]
        if name == "capture_public":
            result = evidence.capture_public(self.db, self.context["instrument"], provider=args["provider"])
            # Capture is not a read. The assignment must retrieve eligible
            # passages under its own cutoff before it can cite anything.
            data = {
                key: result[key]
                for key in ("message", "receipt_id", "document_id", "cached", "checked_at", "retry_at")
                if key in result
            }
            data["provider"] = args["provider"]
            return result["status"], data, []
        if name == "record_gap":
            # Its referenced read is checked atomically with appending the declaration below.
            return "ok", {}, []
        return "unavailable", {"message": GAPS[name][1]}, []

    def call(self, name, args):
        renew(self.db, self.lease)
        if name not in PARAMETERS or (name == "capture_public" and self.fixture):
            raise ValueError("Tool unavailable in this assignment")
        if not isinstance(args, dict) or set(args) != PARAMETERS[name]:
            raise ValueError("Invalid tool parameters")
        for key, value in args.items():
            if key == "period" and name == "record_gap" and isinstance(value, str) and 1 <= len(value) <= 64:
                continue
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", value):
                raise ValueError("Invalid tool parameter")
            if key == "provider" and value not in ("issuer", "sec", "issuer_news"):
                raise ValueError("Source route unavailable")
        count = self.db.execute(
            "SELECT count(*) FROM receipts WHERE run_id=?", (self.lease.run_id,)
        ).fetchone()[0]
        if count >= 20:
            raise ValueError("Research tool budget exhausted")
        started, receipt = now(), uid("receipt")
        try:
            status, data, ids = self._perform(name, args)
        except ValueError as exc:
            if name != "compare_financials":
                raise
            status, data, ids = "invalid_input", {"message": str(exc)}, []
        with write(self.db) as seq:
            run = authorized(self.db, self.lease)
            if name == "record_gap":
                data = gaps.missing_input(self.db, run["id"], args)
            if name in ("search_evidence", "next_evidence_page"):
                data["next_cursor"] = receipt if data["has_more"] else None
            gap = gaps.register(self.db, run, name, args, status, data, GAPS, seq)
            result = {
                "status": status,
                "receipt_id": receipt,
                "data": data,
                "evidence_ids": ids,
                "gap_id": gap,
                "coverage": name,
                "freshness": "see input timestamps" if ids else "unverified",
                "warnings": data.get("warnings", []),
                "retry_after": data.get("retry_at"),
                "trace": "service_recorded",
            }
            self.db.execute(
                "INSERT INTO receipts VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    receipt,
                    self.lease.run_id,
                    name,
                    "2" if name in ("search_evidence", "next_evidence_page") else "1",
                    encode(args),
                    started,
                    now(),
                    status,
                    encode(result),
                    seq,
                ),
            )
            if gap:
                self.db.execute("INSERT INTO gap_attempts VALUES(?,?)", (gap, receipt))
                if name == "record_gap":
                    self.db.execute(
                        "INSERT OR IGNORE INTO gap_attempts VALUES(?,?)", (gap, data["attempt_receipt_id"])
                    )
            gaps.reconcile(self.db, run, name, args, result, seq)
            pending = gaps.outstanding(self.db, run, [{"commit_seq": seq}])
            result["outstanding_gap_ids"] = sorted(pending)
            result["outstanding_inputs"] = gaps.describe(self.db, run["case_id"], pending)
            self.db.execute("UPDATE receipts SET output=? WHERE id=?", (encode(result), receipt))
            return result
