import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from stockinsight import db
from stockinsight import server_profile as profile


class ServerProfileTests(unittest.TestCase):
    def setUp(self):
        holding = tempfile.TemporaryDirectory()
        self.addCleanup(holding.cleanup)
        self.workspace = Path(holding.name)
        with (
            closing(db.connect(self.workspace / "research.sqlite3")) as research,
            patch.dict(os.environ, {"STOCKINSIGHT_PROFILE": profile.PROFILE}),
        ):
            profile.pulse(research)

    def test_health_requires_all_three_and_pings_only_configured_observer(self):
        url = "https://observer.example/private-check"
        with (
            patch.dict(os.environ, {"STOCKINSIGHT_HEARTBEAT_URL": url}),
            patch.object(profile, "_listener", return_value=True),
            patch.object(profile.http.client, "HTTPSConnection") as channel,
        ):
            channel.return_value.getresponse.return_value.status = 200
            self.assertTrue(all(profile.heartbeat(self.workspace).values()))
            channel.return_value.request.assert_called_once_with(
                "POST", "/private-check", body=b""
            )
            (self.workspace / "scheduler-pulse").unlink()
            with self.assertRaisesRegex(ValueError, "withheld"):
                profile.heartbeat(self.workspace)
            self.assertEqual(channel.return_value.request.call_count, 1)

    def test_guard_reports_cost_and_private_endpoint_conditions_without_disclosing_values(
        self,
    ):
        with patch.dict(
            os.environ,
            {
                "STOCKINSIGHT_OPENAI_API_KEY": "private-api",
                "STOCKINSIGHT_HEARTBEAT_URL": "http://private-token/",
                "STOCKINSIGHT_NOTIFICATION_CHANNEL": "ntfy",
                "STOCKINSIGHT_NTFY_URL": "",
                "STOCKINSIGHT_NTFY_TOKEN": "",
            },
        ):
            result = profile.preflight(self.workspace)
        self.assertFalse(result["no_hosted_model_billing"])
        self.assertFalse(result["observer_configured"])
        self.assertFalse(result["notification_configured"])
        self.assertFalse(result["commissioned"])
        self.assertNotIn("private-api", repr(result))

    def test_local_sqlite_fixture_is_ineligible_for_server_success_heartbeat(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            closing(db.connect(Path(temp) / "research.sqlite3", fixture=True)),
        ):
            self.assertFalse(profile._integrity(Path(temp)))
