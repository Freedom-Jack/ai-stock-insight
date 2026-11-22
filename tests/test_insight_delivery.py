"""Durable outbox, channel and retry behavior without a real external recipient."""

import os
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from stockinsight import db as store
from stockinsight import delivery

STAMP = "2026-02-01T12:00:00Z"
LATER = "2026-02-01T12:04:00Z"
DETAIL = {
    "key": "brief:first",
    "title": "PRIVATE thesis",
    "message": "PRIVATE values",
    "report_path": "/goals/reports/dispatch_abc",
}
CONFIG = {
    "STOCKINSIGHT_NOTIFICATION_CHANNEL": "ntfy",
    "STOCKINSIGHT_NTFY_URL": "https://example.test/private",
    "STOCKINSIGHT_NTFY_TOKEN": "secret-credential",
}


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "research.sqlite3"
        self.db = store.connect(self.path)
        self.addCleanup(self.db.close)
        self.enterContext(patch.dict(os.environ, CONFIG))

    def test_enqueue_joins_transaction_freezes_key_and_limits_targets(self):
        with self.assertRaisesRegex(ValueError, "rollback"), store.write(self.db):
            delivery.enqueue(self.db, **DETAIL, at=STAMP)
            raise ValueError("rollback")
        self.assertEqual(delivery.dashboard(self.db)["notices"], [])
        first = delivery.enqueue(self.db, **DETAIL, at=STAMP)
        self.assertEqual(first, delivery.enqueue(self.db, **DETAIL, at=LATER))
        with self.assertRaisesRegex(ValueError, "different"):
            delivery.enqueue(self.db, **{**DETAIL, "report_path": "/status"})
        for value in [
            "https://bad.test",
            "//bad.test",
            "/redirect?to=https://example.test",
            "/cases/..",
            "/cases/x%0a",
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                delivery.enqueue(
                    self.db, **{**DETAIL, "key": "other", "report_path": value}
                )
        delivery.enqueue(
            self.db,
            **{
                **DETAIL,
                "key": "goal:method",
                "report_path": "/methods?instrument_id=i_safe#report_abc",
            },
        )

    def test_declined_channel_retries_same_frozen_report_and_acceptance_is_not_display(
        self,
    ):
        ident = delivery.enqueue(self.db, **DETAIL, at=STAMP)
        with patch.object(delivery.http.client, "HTTPSConnection") as channel:
            conn = channel.return_value
            reply = conn.getresponse.return_value
            reply.status = 403
            self.assertEqual(delivery.tick(self.db, at=STAMP), "failed")
            self.assertIsNone(delivery.tick(self.db, at=STAMP))
            reply.status = 200
            reply.read.return_value = (
                b'{"event":"message","id":"safe-id","topic":"private"}'
            )
            self.assertEqual(delivery.tick(self.db, at=LATER), "accepted")
            self.assertIsNone(delivery.tick(self.db, at=LATER))
            for call in conn.request.call_args_list:
                self.assertNotIn("PRIVATE", repr(call))
                self.assertNotIn(DETAIL["report_path"], repr(call))
        view = delivery.dashboard(self.db)
        notice = view["notices"][0]
        self.assertEqual((notice["id"], notice["state"]), (ident, "accepted"))
        self.assertIsNone(notice["shown_at"])
        self.assertIsNone(notice["open_requested_at"])
        self.assertEqual(
            sorted(r["outcome"] for r in view["attempts"]), ["accepted", "failed"]
        )
        self.assertNotIn("secret-credential", repr(view))

    def test_lost_ack_or_crash_requires_operator_confirmation_and_fences_late_receipt(
        self,
    ):
        ident = delivery.enqueue(self.db, **DETAIL, at=STAMP)
        first, _ = delivery._claim(self.db, store.instant(STAMP), "ntfy")
        self.assertIsNone(delivery.tick(self.db, at=LATER))
        self.assertEqual(
            delivery.dashboard(self.db)["notices"][0]["state"], "uncertain"
        )
        with patch.object(delivery, "now", return_value=LATER):
            with self.assertRaisesRegex(ValueError, "duplicate"):
                delivery.action(self.db, "delivery-retry", {"id": ident})
            delivery.action(self.db, "delivery-retry", {"id": ident, "confirm": "1"})
            second, _ = delivery._claim(self.db, store.instant(LATER), "ntfy")
            self.assertFalse(delivery._finish(self.db, first, "shown", "late"))
            self.assertTrue(
                delivery._finish(
                    self.db,
                    second,
                    "shown",
                    "observed",
                    observation={"centre_visible": True},
                )
            )
            self.assertFalse(delivery._finish(self.db, second, "shown", "duplicate"))
        self.assertEqual(len(delivery.dashboard(self.db)["attempts"]), 2)

    def test_single_claim_across_workers_disabled_fixture_expiry(self):
        delivery.enqueue(self.db, **DETAIL, at=STAMP)
        claims = []
        gate = threading.Barrier(2)

        def worker():
            with closing(store.connect(self.path)) as db:
                gate.wait()
                claims.append(delivery._claim(db, store.instant(STAMP), "ntfy"))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(bool(result) for result in claims), 1)
        delivery.action(self.db, "delivery-configure", {"enabled": "0"})
        delivery.tick(self.db, at="2026-02-10T00:00:00Z")
        self.assertEqual(delivery.dashboard(self.db)["notices"][0]["state"], "expired")
        self.assertEqual(len(delivery.dashboard(self.db)["attempts"]), 1)
        with (
            closing(store.connect(":memory:", fixture=True)) as fixture,
            patch.object(delivery, "_ntfy") as external,
        ):
            delivery.enqueue(fixture, **DETAIL, at=STAMP)
            self.assertIsNone(delivery.tick(fixture, at=STAMP))
            external.assert_not_called()

    def test_ambiguous_wire_status_never_triggers_automatic_resend(self):
        delivery.enqueue(self.db, **DETAIL, at=STAMP)
        with patch.object(delivery.http.client, "HTTPSConnection") as channel:
            channel.return_value.getresponse.side_effect = TimeoutError
            self.assertEqual(delivery.tick(self.db, at=STAMP), "uncertain")
            self.assertIsNone(delivery.tick(self.db, at=LATER))
            self.assertEqual(channel.return_value.request.call_count, 1)
