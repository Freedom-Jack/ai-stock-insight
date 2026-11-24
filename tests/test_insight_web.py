"""Exercise the foreground interface over loopback using its rendered HTML forms."""

import socket
import tempfile
import time
import unittest
from base64 import b64encode
from contextlib import ExitStack, closing, contextmanager
from html.parser import HTMLParser
from http.client import HTTPConnection
from importlib.util import find_spec
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode

from stockinsight import db, evidence, universe
from stockinsight.__main__ import DEMO_CUTOFF, DEMO_QUESTION, EXAMPLE


class FormFields(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.values = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "input" and fields.get("type") == "hidden":
            self.values[fields["name"]] = fields["value"]


@contextmanager
def served(app_factory):
    """Serve a test application on a kernel-assigned loopback port."""
    import uvicorn

    with closing(socket.socket()) as channel:
        channel.bind(("127.0.0.1", 0))
        port = channel.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(app_factory(port), proxy_headers=False, log_level="error", lifespan="off")
        )
        worker = Thread(target=server.run, kwargs={"sockets": [channel]}, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            if not server.started:
                raise RuntimeError("Loopback server did not start")
            yield port
        finally:
            server.should_exit = True
            worker.join(5)


@unittest.skipUnless(find_spec("fastapi") and find_spec("uvicorn"), "Install the locked web dependencies")
class PrivateDeskTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "desk.sqlite3"
        with closing(db.connect(self.path, fixture=True)) as conn:
            universe.import_snapshot(conn, EXAMPLE.read_bytes(), complete=True)
            item = next(i for i in universe.universe(conn)["instruments"] if i["ticker"] == "NVDA")
            self.instrument_id = item["id"]
            evidence.seed_fixture(conn, item["id"])
        self.service = self.enterContext(ExitStack())
        self.start_service()

    def start_service(self):
        from stockinsight.web import application

        self.port = self.service.enter_context(
            served(lambda p: application(self.path, p, "example-test-code"))
        )
        self.origin = f"http://127.0.0.1:{self.port}"
        self.auth_headers = {}

    def request(self, path, data=None, **headers):
        with closing(HTTPConnection("127.0.0.1", self.port, timeout=5)) as client:
            headers = {**self.auth_headers, **headers}
            if data is not None:
                headers.setdefault("Origin", self.origin)
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            client.request(
                "POST" if data is not None else "GET",
                path,
                urlencode(data) if data is not None else None,
                headers,
            )
            r = client.getresponse()
            return r.status, dict(r.getheaders()), r.read().decode()

    def sign_in(self):
        self.assertEqual(self.request("/")[0], 401)
        auth = b64encode(b"research:example-test-code").decode("ascii")
        self.auth_headers = {"Authorization": "Basic " + auth}
        status, headers, _ = self.request("/")
        self.assertEqual(status, 200)
        self.assertNotIn("set-cookie", headers)

    def test_form_investigation_citations_duplicate_post_and_review(self):
        self.sign_in()
        status, headers, html = self.request("/")
        self.assertEqual(status, 200)
        self.assertEqual(headers["cache-control"], "no-store")
        fields = FormFields(html).values
        data = {
            **fields,
            "instrument_id": self.instrument_id,
            "question": DEMO_QUESTION,
            "cutoff": DEMO_CUTOFF,
        }
        status, headers, _ = self.request("/actions/ask", data)
        self.assertEqual(status, 303)
        case = headers["location"]
        status, _, html = self.request(case)
        self.assertEqual(status, 200)
        for fragment in (
            "20%",
            "Q2 FY25",
            "shipment moving",
            "pre-release",
            "price_context".replace("_", " "),
            "Method and tool receipts",
            "Missing evidence",
            "Mark this revision reviewed",
        ):
            self.assertIn(fragment, html)
        with closing(db.connect(self.path)) as conn:
            doc = conn.execute("SELECT id FROM documents").fetchone()[0]
        status, headers, saved = self.request(f"/sources/{self.instrument_id}/{doc}")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["content-disposition"])
        self.assertIn('"qualification"', saved)
        fields = FormFields(html).values
        self.assertEqual(self.request("/actions/ask", data)[1]["location"], case)
        with closing(db.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT count(*),reviewed_at FROM inbox").fetchone()[:], (1, None))
        self.assertEqual(
            self.request("/actions/review", {"csrf": fields["csrf"], "brief": fields["brief"]})[0], 303
        )
        self.assertIn("Marked reviewed", self.request(case)[2])
        for route in ("/universe", "/status", "/companies/" + self.instrument_id):
            self.assertEqual(self.request(route)[0], 200)

    def test_host_origin_session_csrf_and_rejected_watchlist(self):
        self.assertEqual(self.request("/")[0], 401)
        self.assertEqual(self.request("/", Host="other.invalid")[0], 403)
        self.assertEqual(self.request("/actions/import", {})[0], 401)
        self.assertEqual(
            self.request("/login", {"code": "example-test-code"}, Origin="https://other.invalid")[0], 403
        )
        self.sign_in()
        self.assertEqual(self.request("/actions/import", {"entries": "AMD"})[0], 403)
        csrf = FormFields(self.request("/universe")[2]).values["csrf"]
        data = {"csrf": csrf, "entries": "ticker,quantity\nNVDA,30987654", "complete": "yes"}
        self.assertEqual(self.request("/actions/import", data, Origin="https://other.invalid")[0], 403)
        self.assertEqual(self.request("/actions/import", data)[0], 303)
        status, _, html = self.request("/universe")
        self.assertEqual(status, 200)
        self.assertIn("rejected", html)
        self.assertNotIn("30987654", html)
        with closing(db.connect(self.path)) as conn:
            self.assertNotIn("30987654", " ".join(conn.iterdump()))
            self.assertEqual(len(universe.universe(conn)["instruments"]), 2)

    def test_duplicate_continuation_form_and_fresh_revision(self):
        from stockinsight import research

        self.sign_in()
        with closing(db.connect(self.path)) as conn:
            job = research.ask(conn, self.instrument_id, DEMO_QUESTION, cutoff=DEMO_CUTOFF)
            self.assertIsNotNone(research.run_job(conn, job))
            case = conn.execute("SELECT case_id FROM jobs WHERE id=?", (job,)).fetchone()[0]
        route = "/cases/" + case
        form = FormFields(self.request(route)[2]).values
        self.assertEqual(self.request("/actions/continue", form)[0], 303)
        self.service.close()
        self.start_service()
        self.sign_in()
        form["csrf"] = FormFields(self.request(route)[2]).values["csrf"]
        self.assertEqual(self.request("/actions/continue", form)[0], 303)
        with closing(db.connect(self.path)) as conn:
            self.assertEqual(
                [
                    conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                    for table in ("jobs", "briefs", "inbox")
                ],
                [2, 2, 2],
            )
            job = research.continuation(conn, case, request_key=form["key"], expected_revision=1)
            self.assertEqual(
                conn.execute("SELECT base_revision FROM jobs WHERE id=?", (job,)).fetchone()[0], 1
            )
        stale = {**form, "key": db.uid("request")}
        self.assertEqual(self.request("/actions/continue", stale)[0], 400)
        fresh = FormFields(self.request(route)[2]).values
        self.assertEqual(self.request("/actions/continue", fresh)[0], 303)
        with closing(db.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT revision FROM cases WHERE id=?", (case,)).fetchone()[0], 3)

    def test_candidate_preview_names_source_and_changed_listing(self):
        self.sign_in()
        token = FormFields(self.request("/universe")[2]).values["csrf"]
        self.assertEqual(
            self.request(
                "/actions/import",
                {
                    "csrf": token,
                    "entries": "ticker,listing_exchange,security_type,currency\nNVDA,NASDAQ,STK,USD",
                    "complete": "yes",
                },
            )[0],
            303,
        )
        page = self.request("/universe")[2]
        self.assertIn("(personal)", page)
        self.assertIn("Remove · MSFT · NASDAQ", page)
        self.assertIn("Accept replacement", page)
