import argparse
import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import chdir, redirect_stdout
from pathlib import Path

from stockwatch.config import DEFAULT_CONFIG, EXAMPLES, SAMPLE_PORTFOLIO, add_configure_command, load_config
from stockwatch.relevance import portfolio_context


class ConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.config = self.folder / "my settings.json"
        self.parser = argparse.ArgumentParser()
        add_configure_command(self.parser.add_subparsers(required=True))

    def edit(self, *args):
        options = self.parser.parse_args(["configure", "--config", str(self.config), *map(str, args)])
        options.run(options)

    def test_defaults_work_offline_for_live_and_replay_dates(self):
        with chdir(self.folder):
            settings = load_config()
            self.assertFalse(DEFAULT_CONFIG.exists())
        self.assertEqual(settings.tickers, ("AMD", "NVDA"))
        self.assertEqual(settings.portfolio, SAMPLE_PORTFOLIO)
        for cutoff in ("2024-04-03T00:15:00Z", "2026-11-05T20:00:00Z"):
            text = portfolio_context(settings.portfolio, settings.tickers, cutoff)
            self.assertIn("Hypothetical sample allocation", text)
            self.assertIn("$15,000.00", text)
            self.assertIn("(15.00%)", text)
        dated = portfolio_context(EXAMPLES / "portfolio.json", settings.tickers, "2026-11-05T20:00:00Z")
        self.assertIn("older than seven days", dated)
        with self.assertRaises(FileNotFoundError):
            load_config(self.config)

    def test_select_then_update_without_losing_settings_or_evidence(self):
        with redirect_stdout(io.StringIO()) as output:
            self.edit("--tickers", "nvda", "--radius-km", "150", "--watchlist-only")
            self.edit("--min-magnitude", "6.7")
        settings = load_config(self.config)
        self.assertEqual((settings.tickers, settings.watchlist.min_magnitude, settings.watchlist.radius_km),
                         (("NVDA",), 6.7, 150))
        self.assertIsNone(settings.portfolio)
        self.assertIn("watchlist only", output.getvalue())
        links = settings.watchlist.match({"latitude": 23.819, "longitude": 121.5616, "magnitude": 7.4},
                                         "2024-04-03T00:15:00Z")
        self.assertEqual([row["ticker"] for row in links], ["NVDA"])
        self.assertIn("sec.gov", links[0]["source_url"])
        with redirect_stdout(io.StringIO()):
            self.edit("--all-tickers", "--sample-portfolio")
        self.assertEqual(load_config(self.config).tickers, ("AMD", "NVDA"))
        self.assertEqual(load_config(self.config).portfolio, SAMPLE_PORTFOLIO)

    def test_invalid_edits_leave_existing_settings_in_place(self):
        with redirect_stdout(io.StringIO()):
            self.edit("--tickers", "AMD")
        before = self.config.read_bytes()
        for flags, expected in ((("--tickers", "UNKNOWN"), "No documented relationship"),
                                (("--min-magnitude", "nan"), "must be a number"),
                                (("--radius-km", "-1"), "must be a number"),
                                (("--portfolio", self.config), "separate files")):
            with self.subTest(flags=flags), self.assertRaisesRegex(ValueError, expected):
                self.edit(*flags)
            self.assertEqual(self.config.read_bytes(), before)
        private = self.folder / "positions.json"
        private.write_bytes((EXAMPLES / "portfolio.json").read_bytes())
        self.config = private
        with self.assertRaisesRegex(ValueError, "settings file"):
            self.edit("--tickers", "AMD")
        self.assertEqual(private.read_bytes(), (EXAMPLES / "portfolio.json").read_bytes())

    def test_custom_evidence_relative_to_config_and_partial_coverage(self):
        doc = json.loads((EXAMPLES / "watchlist.json").read_bytes())
        # Synthetic relationships exercise how a name can expire before its peers.
        doc["sites"][0]["editions"][0]["relationships"][0]["ticker"] = "EXAMPLE"
        source = self.folder / "relationships.json"
        source.write_text(json.dumps(doc), encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            self.edit("--watchlist", source, "--portfolio", EXAMPLES / "portfolio.json")
        stored = json.loads(self.config.read_bytes())
        stored["watchlist"] = source.name
        self.config.write_text(json.dumps(stored), encoding="utf-8")
        settings = load_config(self.config)
        self.assertEqual(settings.watchlist_path, source.resolve())
        self.assertEqual(settings.portfolio, EXAMPLES / "portfolio.json")
        self.assertEqual(settings.tickers, ("AMD", "EXAMPLE", "NVDA"))
        gaps = settings.watchlist.coverage_gaps("2026-11-05T20:00:00Z")
        self.assertEqual(gaps, ["No active supplier relationship for EXAMPLE"])

    def test_concurrent_edits_retain_both_fields(self):
        with redirect_stdout(io.StringIO()), ThreadPoolExecutor(2) as pool:
            edits = [pool.submit(self.edit, "--tickers", "AMD"), pool.submit(self.edit, "--radius-km", "25")]
            for edit in edits:
                edit.result(timeout=15)
        settings = load_config(self.config)
        self.assertEqual(settings.watchlist.radius_km, 25)
        self.assertEqual(settings.tickers, ("AMD",))
