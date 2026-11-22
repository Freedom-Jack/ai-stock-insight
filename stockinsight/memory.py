"""User-selected research history, portable case records and evidence-driven case revisions."""

import hashlib
import json
import re

from . import delivery, disclosure, evidence, journal, research, universe, workspace
from .db import is_fixture, now, uid, write

SCHEMA = """
CREATE TABLE research_imports(
 id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL REFERENCES instruments, kind TEXT NOT NULL,
 title TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL, imported_at TEXT NOT NULL,
 commit_seq INTEGER NOT NULL REFERENCES commits, UNIQUE(instrument_id,kind,digest)
);
CREATE TABLE case_updates(
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases, brief_id TEXT NOT NULL REFERENCES briefs,
 claim_no INTEGER NOT NULL, old_ref TEXT NOT NULL REFERENCES evidence_passages,
 new_ref TEXT REFERENCES evidence_passages, document_id TEXT NOT NULL REFERENCES documents,
 relation TEXT NOT NULL, rationale TEXT NOT NULL, origin TEXT NOT NULL, state TEXT NOT NULL,
 job_id TEXT REFERENCES jobs, new_brief TEXT REFERENCES briefs, created_at TEXT NOT NULL,
 commit_seq INTEGER NOT NULL REFERENCES commits, UNIQUE(brief_id,old_ref,document_id,relation)
);
CREATE INDEX case_update_work ON case_updates(state,created_at);
CREATE TABLE dependency_scans(brief_id TEXT REFERENCES briefs,document_id TEXT REFERENCES documents,
 PRIMARY KEY(brief_id,document_id));
"""

LIMIT = 950_000
_SENSITIVE = re.compile(r"(?i)\b(?:bearer\s+[A-Za-z0-9_.-]{12,}|(?:api[_ -]?key|password|access[_ -]?token|account[_ -]?(?:id|number))\s*[:=]\s*\S+|(?:DU|U)\d{5,})\b")


def _encoded(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)


def _portable(value):
    text = _encoded(value)
    if len(text.encode()) > LIMIT:
        raise ValueError("This record exceeds the portable case limit. Use a workspace backup.")
    if _SENSITIVE.search(text) or re.search(r'(?i)(?:[a-z]:\\\\|/(?:home|Users)/[^/ ]+/)',text):
        raise ValueError("Remove private account, credential or local path material before transfer.")
    return text


def export_case(db, case_id):
    c = workspace.case_detail(db,case_id)
    keep = ("id","ticker","company_name","listing_exchange","security_type","currency","cik")
    revisions = []
    for b in c["briefs"]:
        sources = []
        for ref,p in b["sources"].items():
            # Export only the permitted retained passage projection. Never copy a provider session or raw feed.
            sources.append({k:p[k] for k in ("id","document_id","version_hash","title","origin","source_url",
                                              "available_at","received_at","published_at","locator","text","financial")})
        receipts = [{k:r[k] for k in ("id","tool","version","status","started_at","finished_at")} for r in b["receipts"]]
        revisions.append({"id":b["id"],"revision":b["revision"],"method":b["method"],"as_of":b["as_of"],
                          "body":b["body"],"sources":sources,"receipts":receipts,"comparisons":b["comparisons"],
                          "manifest_hash":b["manifest_hash"],"reviewed_at":b["reviewed_at"]})
    notes = [{k:n[k] for k in ("id","brief_id","kind","author","body","created_at","review_on","condition_text","review_of_id")}
             for n in journal.case_notes(db,case_id)["entries"]]
    data = {"case_id":case_id,"listing":{k:c["instrument"].get(k) for k in keep},"question":c["question"],
            "cutoff":c["cutoff"],"fixture":c["fixture"],"revisions":revisions,"journal":notes,
            "gaps":[{k:g[k] for k in ("id","capability","lifecycle","impact","remedy")} for g in c["gaps"]],
            "updates":[dict(r) for r in db.execute("""SELECT brief_id,old_ref,new_ref,new_brief,relation,rationale,origin,state
                                                     FROM case_updates WHERE case_id=? ORDER BY commit_seq""",(case_id,))]}
    payload = _portable(data)
    return {"format":"stockinsight.case.v1","sha256":hashlib.sha256(payload.encode()).hexdigest(),"case":data}


def _pairs(pairs):
    result = dict(pairs)
    if len(result)!=len(pairs):
        raise ValueError("Repeated import field")
    return result


def _parse(raw):
    if not isinstance(raw,str) or len(raw.encode()) > LIMIT:
        raise ValueError("Import exceeds the selected-record limit")
    try:
        return json.loads(raw,object_pairs_hook=_pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError("Invalid number")))
    except (json.JSONDecodeError,RecursionError,UnicodeError) as exc:
        raise ValueError("Invalid selected research JSON.") from exc


def import_record(db, instrument_id, raw, kind, title):
    item = universe.instrument(db,instrument_id)
    doc = _parse(raw)
    if kind == "conversation":
        # Explicitly selected message list; preserve attribution and source order. Assistant text is a candidate.
        if isinstance(doc,dict) and set(doc)=={"messages"}:
            doc = doc["messages"]
        if not isinstance(doc,list) or not 1<=len(doc)<=200:
            raise ValueError("Choose a JSON list of selected messages")
        for m in doc:
            if not isinstance(m,dict) or set(m)!={"role","content"} or m["role"] not in ("assistant","user") or (
                not isinstance(m["content"],str) or not 1<=len(m["content"].strip())<=16000):
                raise ValueError("Each selected message requires an author role and text")
    elif kind == "case":
        if not isinstance(doc,dict) or set(doc)!={"format","case","sha256"} or doc["format"]!="stockinsight.case.v1":
            raise ValueError("Choose a Stock Insight case export")
        data = doc["case"]
        if not isinstance(data,dict) or set(data)!={"case_id","listing","question","cutoff","fixture","revisions","journal","gaps","updates"}:
            raise ValueError("Incomplete case package")
        if hashlib.sha256(_portable(data).encode()).hexdigest()!=doc["sha256"]:
            raise ValueError("The case package checksum differs")
        if type(data["fixture"]) is not bool or data["fixture"]!=is_fixture(db):
            raise ValueError("Import a case into its matching personal or fixture profile")
        if not isinstance(data["listing"],dict) or any(data["listing"].get(k)!=item.get(k)
            for k in ("ticker","listing_exchange","security_type","currency","cik")):
            raise ValueError("Choose the case's exact watched listing")
        if not isinstance(data["revisions"],list) or len(data["revisions"])>256 or not isinstance(data["question"],str):
            raise ValueError("Invalid archived research record")
        for b in data["revisions"]:
            try:
                refs={p["id"] for p in b["sources"] if re.fullmatch("[0-9a-f]{64}",p["version_hash"])}
                if len(refs)!=len(b["sources"]) or not all(set(c["evidence_refs"])<=refs for c in b["body"]["claims"]):
                    raise ValueError("Archived citation is missing")
            except (TypeError,KeyError) as exc:
                raise ValueError("Invalid archived citation structure") from exc
        title=data["question"][:180]
    else:
        raise ValueError("Unknown import kind")
    if not title or not isinstance(title,str) or len(title)>180:
        raise ValueError("Supply a short title")
    _portable(title)
    payload = _portable(doc)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    with write(db) as seq:
        db.execute("INSERT OR IGNORE INTO research_imports VALUES(?,?,?,?,?,?,?,?)",
                   (uid("import"),instrument_id,kind,title,digest,payload,now(),seq))
        return db.execute("SELECT id FROM research_imports WHERE instrument_id=? AND kind=? AND digest=?",
                          (instrument_id,kind,digest)).fetchone()[0]


def recall(db,instrument_id):
    imports = [dict(r) for r in db.execute("""SELECT id,kind,title,imported_at FROM research_imports
             WHERE instrument_id=? ORDER BY commit_seq DESC LIMIT 30""",(instrument_id,))]
    questions = [dict(r) for r in db.execute("""SELECT question,report_id FROM goal_followups WHERE instrument_id=?
             ORDER BY created_at DESC,id LIMIT 6""",(instrument_id,))]
    excerpts=[]
    for record in imports[:3]:
        payload=get_import(db,record["id"])["payload"]
        if record["kind"]=="conversation":
            excerpts.extend({"import_id":record["id"],"author":m["role"],"candidate":m["content"][:400]}
                            for m in payload[-3:])
        else:
            excerpts.append({"import_id":record["id"],"author":"archived case","candidate":payload["case"]["question"][:400]})
    return {"imports":imports,"questions":questions,"attributed_context":excerpts}


def case_context(db,case):
    return {
        "updates":[dict(r) for r in db.execute("""SELECT u.*,b.revision FROM case_updates u JOIN briefs b ON b.id=u.brief_id
                     WHERE u.case_id=? ORDER BY u.commit_seq DESC""",(case["id"],))],
        "sources":disclosure.sources(db,case["instrument"]["id"]) if not is_fixture(db) and case["briefs"] else [],
    }


def action(db,command,data):
    if command=="memory-import":
        record=import_record(db,data.get("listing",""),data.get("raw",""),data.get("kind",""),data.get("title",""))
        return "/memory/"+record
    if command=="memory-attach":
        case=workspace.case_detail(db,data.get("case",""))
        ordinal=int(data.get("claim",""))
        b=case["briefs"][0] if case["briefs"] else None
        if not b or b["id"]!=data.get("brief") or b["method"]!=research.METHOD or not 0<=ordinal<len(b["body"]["claims"]):
            raise ValueError("Choose a current financial claim")
        if data.get("relation") not in ("qualification","counterevidence") or not 1<=len(data.get("rationale","").strip())<=1000:
            raise ValueError("Describe the relationship to the claim")
        ref=disclosure.capture(db,case["instrument"]["id"],data.get("url",""),data.get("quote",""))
        link_update(db,b["id"],ordinal,ref,data["relation"],data["rationale"])
        return "/cases/"+case["id"]
    raise ValueError("Unknown memory operation")


def get_import(db,ident):
    row=db.execute("SELECT * FROM research_imports WHERE id=?",(ident,)).fetchone()
    if not row:
        raise ValueError("Unknown selected import")
    return {**dict(row),"payload":json.loads(row["payload"])}


def link_update(db, brief_id, claim_no, new_ref, relation, rationale):
    if relation not in ("qualification","counterevidence") or not 1<=len(rationale.strip())<=1000:
        raise ValueError("Identify the evidentiary relationship and reason")
    b = db.execute("""SELECT b.*,c.instrument_id,c.cutoff FROM briefs b JOIN cases c ON c.id=b.case_id
                      WHERE b.id=? AND b.revision=c.revision""",(brief_id,)).fetchone()
    if not b or b["method"]!=research.METHOD:
        raise ValueError("Choose the current financial case revision")
    src=evidence.get(db,b["instrument_id"],new_ref,b["cutoff"],fixture=is_fixture(db))
    claims=json.loads(b["body"])["claims"]
    if not 0<=claim_no<len(claims) or not claims[claim_no]["evidence_refs"] or src["financial"] or not evidence.still_supported(db,src,b["cutoff"]):
        raise ValueError("Choose a current primary narrative and a supported claim")
    old=claims[claim_no]["evidence_refs"][0]
    if new_ref in set(json.loads(b["manifest"])["passages"]):
        raise ValueError("This source was already read in the selected revision")
    with write(db) as seq:
        _record(db,seq,b,claim_no,old,new_ref,src["document_id"],relation,rationale,"operator")


def _record(db,seq,b,ordinal,old,new,doc,relation,rationale,origin):
    db.execute("""INSERT OR IGNORE INTO case_updates VALUES(?,?,?,?,?,?,?,?,?,?,'pending',NULL,NULL,?,?)""",
               (uid("update"),b["case_id"],b["id"],ordinal,old,new,doc,relation,rationale,origin,now(),seq))


def attachments(db,case_id,revision,cutoff):
    rows=db.execute("""SELECT u.new_ref,u.relation FROM case_updates u JOIN briefs b ON b.id=u.brief_id
        WHERE u.case_id=? AND b.revision<=? AND u.new_ref IS NOT NULL ORDER BY u.commit_seq DESC""",(case_id,revision))
    listing=db.execute("SELECT instrument_id FROM cases WHERE id=?",(case_id,)).fetchone()[0]
    result={}
    for row in rows:
        p=evidence.get(db,listing,row["new_ref"],cutoff,fixture=is_fixture(db))
        if evidence.still_supported(db,p,cutoff):
            result.setdefault(p["id"],row["relation"])
    return result


def _scan(db):
    # Compare only editions of documents actually cited by the most recent accepted interpretation.
    rows=db.execute("""SELECT DISTINCT b.id,b.case_id,c.instrument_id,c.cutoff,n.id AS new_doc,n.origin,n.source_url
        FROM briefs b JOIN cases c ON c.id=b.case_id AND c.revision=b.revision
        JOIN claim_evidence ce ON ce.brief_id=b.id JOIN evidence_passages p ON p.id=ce.passage_id
        JOIN documents o ON o.id=p.document_id JOIN documents n ON n.instrument_id=o.instrument_id
           AND n.origin=o.origin AND n.source_url=o.source_url AND n.commit_seq>b.commit_seq
        WHERE NOT EXISTS(SELECT 1 FROM dependency_scans x WHERE x.brief_id=b.id AND x.document_id=n.id)
          AND EXISTS(SELECT 1 FROM source_memberships m WHERE m.instrument_id=c.instrument_id AND m.status='active')
        AND NOT EXISTS(SELECT 1 FROM documents newer WHERE newer.instrument_id=n.instrument_id AND newer.origin=n.origin
          AND newer.source_url=n.source_url AND newer.commit_seq>n.commit_seq AND EXISTS(SELECT 1 FROM evidence_passages
            WHERE document_id=newer.id AND (c.cutoff IS NULL OR available_at<=c.cutoff)))
        AND EXISTS(SELECT 1 FROM evidence_passages np WHERE np.document_id=n.id AND (c.cutoff IS NULL OR np.available_at<=c.cutoff))
        ORDER BY n.commit_seq LIMIT 12""").fetchall()
    if not rows:
        return
    with write(db) as seq:
        for b in rows:
            if not db.execute("INSERT OR IGNORE INTO dependency_scans VALUES(?,?)",(b["id"],b["new_doc"])).rowcount:
                continue
            for ordinal,ref in db.execute("SELECT ordinal,passage_id FROM claim_evidence WHERE brief_id=?",(b["id"],)):
                p=evidence.get(db,b["instrument_id"],ref,b["cutoff"],fixture=is_fixture(db))
                if (p["origin"],p["source_url"])==(b["origin"],b["source_url"]) and not evidence.still_supported(db,p,b["cutoff"]):
                    _record(db,seq,b,ordinal,ref,None,b["new_doc"],"source_revision",
                            "A cited observation or its qualifying context changed in a later source edition.","source_check")
                    break


def tick(db):
    _scan(db)
    row = db.execute("""SELECT u.*,c.revision,c.instrument_id,b.revision AS base,b.method,b.reviewed_at AS old_review
        FROM case_updates u JOIN cases c ON c.id=u.case_id JOIN
        (SELECT b.*,i.reviewed_at FROM briefs b JOIN inbox i ON i.brief_id=b.id) b ON b.id=u.brief_id
        WHERE u.state IN ('pending','queued') ORDER BY u.commit_seq LIMIT 1""").fetchone()
    if not row:
        return None
    ident=row["id"]
    if not row["job_id"]:
        if db.execute("""SELECT count(*) FROM jobs j JOIN case_updates u ON u.id=j.request_key
                      WHERE j.created_at>=?""",(now()[:10],)).fetchone()[0]>=6:
            return None
        if row["revision"]!=row["base"]:
            db.execute("UPDATE case_updates SET state='superseded' WHERE id=?",(ident,))
            return ident
        try:
            job=research.continuation(db,row["case_id"],request_key=ident,expected_revision=row["base"])
        except ValueError:
            db.execute("UPDATE case_updates SET state='needs_review' WHERE id=?",(ident,))
            return ident
        db.execute("UPDATE case_updates SET state='queued',job_id=? WHERE id=?",(job,ident))
    else:
        job=row["job_id"]
    current=db.execute("SELECT state FROM jobs WHERE id=?",(job,)).fetchone()[0]
    if current in ("ready","leased"):
        from . import local_research
        try:
            research.run_job(db,job,engine="device" if not is_fixture(db) and local_research.model_available() else "local")
        except ValueError:
            pass  # Queued contention and the durable terminal job detail are handled separately below.
    current=db.execute("SELECT state FROM jobs WHERE id=?",(job,)).fetchone()[0]
    if current in ("ready","leased"):
        return None
    with write(db):
        brief=db.execute("SELECT b.id FROM briefs b JOIN runs r ON r.id=b.run_id WHERE r.job_id=?",(job,)).fetchone()
        db.execute("UPDATE case_updates SET state=?,new_brief=? WHERE id=?",("revised" if brief else "needs_review",
                   brief[0] if brief else None,ident))
        delivery.enqueue(db,key="case-update:"+ident,title="Research correction" if row["old_review"] else "Research revision",
                         message="New evidence affects an earlier research assessment.",report_path="/cases/"+row["case_id"])
    return ident
