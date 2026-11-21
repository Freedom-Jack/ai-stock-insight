"""Read models shared by the private interface and local CLI."""

import json

from . import evidence, universe
from .db import is_fixture


def cases(db):
    return [
        dict(row)
        for row in db.execute("""
        SELECT c.*,i.ticker,(SELECT j.state FROM jobs j WHERE j.case_id=c.id
          ORDER BY j.created_at DESC,j.rowid DESC LIMIT 1) AS state
        FROM cases c JOIN instruments i ON i.id=c.instrument_id
        ORDER BY c.commit_seq DESC LIMIT 200""")
    ]


def case_detail(db, case_id):
    case = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if not case:
        raise ValueError("Unknown case")
    item = universe.instrument(db, case["instrument_id"], active=False)
    jobs = [
        dict(row)
        for row in db.execute(
            "SELECT id,state,detail,created_at FROM jobs WHERE case_id=? ORDER BY created_at DESC,rowid DESC",
            (case_id,),
        )
    ]
    gaps = [dict(row) for row in db.execute("SELECT * FROM capability_gaps WHERE case_id=?", (case_id,))]
    briefs = []
    for row in db.execute(
        "SELECT b.*,i.reviewed_at FROM briefs b JOIN inbox i ON i.brief_id=b.id "
        "WHERE b.case_id=? ORDER BY b.revision DESC",
        (case_id,),
    ):
        manifest = json.loads(row["manifest"])
        passages = {
            ref: evidence.get(db, item["id"], ref, case["cutoff"], fixture=is_fixture(db))
            for ref in manifest["passages"]
        }
        receipts = []
        for r in db.execute("SELECT * FROM receipts WHERE run_id=? ORDER BY commit_seq", (row["run_id"],)):
            receipts.append({**dict(r), "output": json.loads(r["output"])})
        briefs.append(
            {
                **dict(row),
                "body": json.loads(row["body"]),
                "manifest": manifest,
                "sources": passages,
                "receipts": receipts,
                "comparisons": [
                    r["output"]["data"]
                    for r in receipts
                    if r["tool"] == "compare_financials" and r["status"] == "ok"
                ],
            }
        )
    return {
        **dict(case),
        "instrument": item,
        "jobs": jobs,
        "briefs": briefs,
        "gaps": gaps,
        "fixture": is_fixture(db),
    }
