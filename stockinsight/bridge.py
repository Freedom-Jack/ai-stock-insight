"""Assignment-scoped domain operations and their service-recorded receipts."""

import json
import re

from . import evidence, providers
from .db import is_fixture, now, uid, write
from .research import authorized, encode, renew


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
        "No eligible source passages were found for this listing and cutoff.",
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
    "get_evidence": "Read one exact passage and its provenance by id.",
    "compare_financials": "Compare two returned observations with explicit financial semantics.",
    "historical_consensus": "Check access to pre-release Street consensus.",
    "price_context": "Check access to timed prices for the case instrument.",
    "capture_public": "Capture a release or financial fact from an approved issuer or SEC route.",
}
PARAMETERS = {
    "list_capabilities": set(),
    "search_evidence": set(),
    "get_evidence": {"id"},
    "compare_financials": {"current", "baseline", "kind"},
    "historical_consensus": set(),
    "price_context": set(),
    "capture_public": {"provider"},
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
        if name == "search_evidence":
            found = evidence.search(
                self.db, self.context["instrument"]["id"], self.context["cutoff"], fixture=self.fixture
            )[:24]
            return "ok" if found else "partial", {"passages": found}, [p["id"] for p in found]
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
            return result["status"], data, []
        return "unavailable", {"message": GAPS[name][1]}, []

    def call(self, name, args):
        renew(self.db, self.lease)
        if name not in PARAMETERS or (name == "capture_public" and self.fixture):
            raise ValueError("Tool unavailable in this assignment")
        if not isinstance(args, dict) or set(args) != PARAMETERS[name]:
            raise ValueError("Invalid tool parameters")
        for key, value in args.items():
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", value):
                raise ValueError("Invalid tool parameter")
            if key == "provider" and value not in ("issuer", "sec"):
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
            gap = None
            if status != "ok" and name in GAPS:
                reason, impact, fallback, remedy, example = GAPS[name]
                self.db.execute(
                    "INSERT INTO capability_gaps(id,case_id,capability,status,impact,fallback,"
                    "remedy,acceptance_example,commit_seq) VALUES(?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(case_id,capability,status) DO NOTHING",
                    (uid("gap"), run["case_id"], name, reason, impact, fallback, remedy, example, seq),
                )
                gap = self.db.execute(
                    "SELECT id FROM capability_gaps WHERE case_id=? AND capability=? AND status=?",
                    (run["case_id"], name, reason),
                ).fetchone()[0]
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
                    "1",
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
            return result
