import json
import ssl
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import URLError

from stockwatch.issuer import FEED_URL, MAX_BYTES, fetch_bulletins, is_bulletin_url, parse_bulletins


FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "issuer-twse-2024.json"
SEEN = "2024-04-06T01:00:00Z"


class IssuerTests(unittest.TestCase):
    def setUp(self):
        self.row = json.loads(FIXTURE.read_bytes())[0]

    def parse(self, rows, seen=SEEN):
        return parse_bulletins(json.dumps(rows).encode(), seen)

    def test_dated_issuer_update_with_independent_clocks_and_locator(self):
        snapshot = parse_bulletins(FIXTURE.read_bytes(), SEEN)
        self.assertEqual(snapshot.report_date, "2024-04-06")
        result, = snapshot.bulletins
        self.assertEqual(result.key, "twse:2330:20240405T212303")
        self.assertEqual(result.published_at, "2024-04-05T13:23:03.000000Z")
        self.assertEqual(result.event_date, "2024-04-03")
        self.assertIn("部分生產線", result.excerpt)
        self.assertIn("已大致復原", result.excerpt)
        self.assertTrue(is_bulletin_url(result.url))
        self.assertIn("b_date=05&e_date=05", result.url)
        self.assertIn("co_id=2330", result.url)
        self.assertEqual(self.parse([self.row, self.row]).bulletins, [result])

    def test_quiet_dated_file_and_malformed_or_stale_feed(self):
        unrelated = {**self.row, "公司代號": "8888"}
        bland = {**self.row, "主旨 ": "董事會公告", "說明": "未發生事故。"}
        self.assertEqual(self.parse([unrelated, bland]).bulletins, [])
        for rows in ([], {}, [{}], [self.row, {**unrelated, "出表日期": "1130405"}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.parse(rows)
        missing = dict(unrelated)
        del missing["主旨 "]
        with self.assertRaisesRegex(ValueError, "schema"):
            self.parse([missing])
        for day in ("2024-04-04T00:00:00Z", "2024-04-08T00:00:00Z"):
            with self.assertRaisesRegex(ValueError, "stale or future"):
                self.parse([self.row], day)
        with self.assertRaisesRegex(ValueError, "filing time"):
            self.parse([{**self.row, "出表日期": "1130405"}], "2024-04-05T02:00:00Z")
        with self.assertRaises(ValueError):
            self.parse([{**self.row, "說明": ""}])
        with self.assertRaisesRegex(ValueError, "size"):
            parse_bulletins(b" " * (MAX_BYTES + 1), SEEN)

    def test_linking_abstains_when_date_is_ambiguous_or_unavailable(self):
        for title in ("強震後續說明", "去年4/3地震說明", "4/3地震與4/4餘震", "12/15地震"):
            row = {**self.row, "主旨 ": title, "說明": "公司進行設備檢查。"}
            with self.subTest(title=title):
                self.assertIsNone(self.parse([row]).bulletins[0].event_date)
        for title in ("113年4月3日地震說明", "2024/4/3地震說明"):
            row = {**self.row, "主旨 ": title}
            self.assertEqual(self.parse([row]).bulletins[0].event_date, "2024-04-03")
        row = {**self.row, "主旨 ": "營收公告", "說明": "台灣4月3日地震後持續檢查設備。"}
        self.assertEqual(self.parse([row]).bulletins[0].event_date, "2024-04-03")
        overseas = {**self.row, "主旨 ": "日本熊本4/3地震最新說明"}
        self.assertIsNone(self.parse([overseas]).bulletins[0].event_date)
        uncertain = {**self.row, "主旨 ": "4/3地震", "說明": "公司正檢查機台。"}
        self.assertIsNone(self.parse([uncertain]).bulletins[0].event_date)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.parse([self.row, {**self.row, "主旨 ": "4月3日地震最新更新"}])

    def test_official_evidence_links_stay_scoped_to_tsmc(self):
        url = self.parse([self.row]).bulletins[0].url
        for invalid in (url.replace("2330", "2331"), url.replace("b_date=05", "b_date=02"),
                        url.replace("off=1", "off=1&off=4"), url.replace(".tw/", ".tw.fake/"),
                        url.replace("https:", "http:")):
            with self.subTest(invalid=invalid):
                self.assertFalse(is_bulletin_url(invalid))
        detail = ("https://mopsov.twse.com.tw/mops/web/ajax_t05st01?firstin=true&step=2&"
                  "TYPEK=sii&co_id=2330&spoke_date=20240405&spoke_time=212303&seq_no=1")
        self.assertTrue(is_bulletin_url(detail))
        self.assertFalse(is_bulletin_url(detail.replace("212303", "999999")))

    def test_network_path_uses_one_bounded_request_and_same_parser(self):
        response = Mock(status=200)
        response.read.return_value = FIXTURE.read_bytes()
        with patch("stockwatch.issuer.build_opener") as opener:
            with_response = opener.return_value.open.return_value
            with_response.__enter__.return_value = response
            snapshot = fetch_bulletins(SEEN)
            request, = opener.return_value.open.call_args.args
            self.assertEqual(request.full_url, FEED_URL)
            self.assertEqual(opener.return_value.open.call_args.kwargs, {"timeout": 15})
            response.read.assert_called_once_with(MAX_BYTES + 1)
        self.assertEqual(snapshot, parse_bulletins(FIXTURE.read_bytes(), SEEN))

    def test_system_tls_fallback_keeps_verification_and_rejects_redirect(self):
        cert = ssl.SSLCertVerificationError()
        cert.verify_message = "Missing Subject Key Identifier"
        with patch("stockwatch.issuer.build_opener") as opener, patch("stockwatch.issuer.subprocess.run") as curl:
            opener.return_value.open.side_effect = URLError(cert)
            curl.return_value = Mock(returncode=0, stdout=FIXTURE.read_bytes() + b"\nSTOCKWATCH_HTTP 200 ")
            self.assertEqual(fetch_bulletins(SEEN), parse_bulletins(FIXTURE.read_bytes(), SEEN))
            args, = curl.call_args.args
            self.assertIn("--max-filesize", args)
            self.assertEqual(args[1], "--disable")
            self.assertNotIn("--insecure", args)
            self.assertNotIn("--location", args)
            curl.return_value.stdout = FIXTURE.read_bytes() + b"\nSTOCKWATCH_HTTP 302 "
            with self.assertRaisesRegex(OSError, "302"):
                fetch_bulletins(SEEN)
            curl.return_value.stdout = b"\nSTOCKWATCH_HTTP 429 120"
            with self.assertRaisesRegex(OSError, "429") as raised:
                fetch_bulletins(SEEN)
            self.assertEqual(raised.exception.headers["Retry-After"], "120")
            curl.reset_mock()
            cert.verify_message = "certificate has expired"
            with self.assertRaises(URLError):
                fetch_bulletins(SEEN)
            curl.assert_not_called()
