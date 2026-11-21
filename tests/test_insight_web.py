"""Exercise the foreground interface over loopback using its rendered HTML forms."""

from contextlib import closing
from html.parser import HTMLParser
from http.client import HTTPConnection
from importlib.util import find_spec
from pathlib import Path
import socket
import tempfile
from threading import Thread
import time
import unittest
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


@unittest.skipUnless(find_spec("fastapi") and find_spec("uvicorn"), "Install the locked web dependencies")
class PrivateDeskTest(unittest.TestCase):
    def setUp(self):
        import uvicorn
        from stockinsight.web import application

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "desk.sqlite3"
        with closing(db.connect(self.path, fixture=True)) as conn:
            universe.import_snapshot(conn, EXAMPLE.read_bytes(), complete=True)
            item = next(i for i in universe.universe(conn)["instruments"] if i["ticker"] == "NVDA")
            self.instrument_id = item["id"]
            evidence.seed_fixture(conn, item["id"])
        channel = socket.socket()
        channel.bind(("127.0.0.1", 0))
        self.port = channel.getsockname()[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.server = uvicorn.Server(
            uvicorn.Config(
                application(self.path, self.port, "example-test-code"),
                proxy_headers=False,
                log_level="error",
                lifespan="off",
            )
        )
        worker = Thread(target=self.server.run, kwargs={"sockets": [channel]}, daemon=True)
        worker.start()

        def stop():
            self.server.should_exit = True
            worker.join(5)
            channel.close()

        self.addCleanup(stop)
        deadline = time.monotonic() + 5
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.server.started)
        self.cookie = ""

    def request(self, path, data=None, **headers):
        with closing(HTTPConnection("127.0.0.1", self.port, timeout=5)) as client:
            headers = {"Cookie": self.cookie, **headers}
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
        status, headers, _ = self.request("/login", {"code": "example-test-code"})
        self.assertEqual(status, 303)
        cookie = headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.cookie = cookie.split(";")[0]

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
        self.assertEqual(self.request("/")[0], 303)
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
