"""Scripted Responses transport checks. No model service or billable call."""

import json
import os
import unittest
from unittest.mock import patch

from stockinsight import executor

SETTINGS = {
    "STOCKINSIGHT_API_BILLING": "approved",
    "STOCKINSIGHT_OPENAI_API_KEY": "private-test-marker",
    "STOCKINSIGHT_MODEL": "contract-model",
    "STOCKINSIGHT_REASONING_EFFORT": "low",
    "STOCKINSIGHT_MAX_REQUESTS": "4",
}
CONTEXT = {
    "instrument": {"id": "i", "ticker": "DEMO", "local_path": "unrelated-file-marker"},
    "method": "investigate/1",
    "lease_token": "lease-marker",
}
BRIEF = {
    "status": "blocked",
    "passage_ids": [],
    "calculations": [],
    "gaps": ["gap-price"],
}


def reply(name, args, n=1):
    return {
        "model": "contract-model-1",
        "status": "completed",
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "output": [
            {"type": "reasoning", "id": f"reason-{n}", "encrypted_content": "opaque", "summary": []},
            {"type": "function_call", "name": name, "call_id": f"call-{n}", "arguments": json.dumps(args)},
        ],
    }


class ExecutorContract(unittest.TestCase):
    def test_scripted_responses_investigation_reaches_application_acceptance(self):
        from stockinsight import evidence, providers, research
        from tests.test_insight_evidence import sec_packet, workspace

        conn, listings = workspace()
        self.addCleanup(conn.close)
        listing = listings["NVDA"]
        config = {**SETTINGS, "STOCKINSIGHT_SEC_CONTACT": "example@example.org"}
        observed = []

        def transport(body, key, timeout):
            # Only the Responses transport and upstream SEC packet are scripted.
            # This consumer discovers IDs from the same envelopes a worker sees.
            request = json.loads(body)
            history = request["input"]
            if len(history) == 1:
                return reply("search_evidence", {})
            envelope = json.loads(history[-1]["output"])
            observed.append(envelope["status"])
            if len(observed) == 1:
                return reply("get_evidence", {"id": envelope["data"]["passages"][0]["id"]}, n=2)
            passage = envelope["data"]
            return reply(
                "submit_brief",
                {
                    "status": "complete",
                    "passage_ids": [passage["id"]],
                    "calculations": [],
                    "gaps": [],
                },
                n=3,
            )

        with (
            patch.dict(os.environ, config, clear=True),
            patch.object(providers, "_fetch", return_value=json.dumps(sec_packet()).encode()),
            patch.object(executor, "_post", side_effect=transport),
        ):
            self.assertEqual(evidence.capture_public(conn, listing, "sec")["status"], "ok")
            job = research.ask(conn, listing["id"], "What quarterly revenue is in the saved filing?")
            brief = research.run_job(conn, job)
        self.assertTrue(brief)
        self.assertEqual(observed, ["ok", "ok"])
        manifest = json.loads(conn.execute("SELECT manifest FROM briefs WHERE id=?", (brief,)).fetchone()[0])
        self.assertEqual(manifest["runtime"]["requests_attempted"], 3)
        self.assertEqual(manifest["runtime"]["actual_model"], "contract-model-1")
        self.assertEqual(len(manifest["versions"]), 1)

    def test_fixture_rejects_unrelated_questions_instead_of_accepting_a_canned_answer(self):
        with self.assertRaises(executor.ExecutorError) as err:
            executor.execute("When is the next shareholder meeting?", CONTEXT, self.fail, fixture=True)
        self.assertEqual("fixture_scope", err.exception.code)

    def test_requires_explicit_configuration_even_with_ambient_api_key(self):
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "ambient"}, clear=True),
            patch.object(executor, "_post") as post,
        ):
            self.assertFalse(executor.preflight()["enabled"])
            with self.assertRaises(executor.ExecutorError) as err:
                executor.execute("Question?", CONTEXT, self.fail)
            self.assertEqual("not_configured", err.exception.code)
            post.assert_not_called()

    def test_scoped_function_round_trip_records_actual_usage_and_filters_private_state(self):
        sent = []
        invoked = []

        def transport(body, key, timeout):
            self.assertEqual(SETTINGS["STOCKINSIGHT_OPENAI_API_KEY"], key)
            self.assertNotIn(key, body.decode())
            self.assertNotIn("lease-marker", body.decode())
            self.assertNotIn("unrelated-file-marker", body.decode())
            payload = json.loads(body)
            sent.append(payload)
            self.assertFalse(payload["store"])
            self.assertTrue(all(t["type"] == "function" and t["strict"] for t in payload["tools"]))
            self.assertEqual(
                set(executor._FUNCTIONS) - {"capture_public"}, {t["name"] for t in payload["tools"]}
            )
            self.assertFalse(payload["parallel_tool_calls"])
            self.assertLessEqual(timeout, 60)
            if len(sent) == 1:
                return reply("price_context", {})
            self.assertEqual(payload["input"][-1]["call_id"], "call-1")
            self.assertEqual(payload["input"][-3]["encrypted_content"], "opaque")
            self.assertIn("gap-price", payload["input"][-1]["output"])
            return reply("submit_brief", BRIEF, n=2)

        def domain(name, args):
            invoked.append(name)
            return {"status": "unavailable", "data": {}, "receipt_id": "r1", "gap_id": "gap-price"}

        with patch.dict(os.environ, SETTINGS, clear=True), patch.object(executor, "_post", transport):
            result = executor.execute("What moved?", CONTEXT, domain)
        self.assertEqual("blocked", result["status"])
        self.assertEqual(["gap-price"], result["gaps"])
        self.assertEqual(["price_context"], invoked)
        self.assertEqual(result.runtime["actual_model"], "contract-model-1")
        self.assertEqual(result.runtime["requests_attempted"], 2)
        self.assertEqual(result.runtime["usage"], {"input_tokens": 20, "output_tokens": 10})
        self.assertNotIn(SETTINGS["STOCKINSIGHT_OPENAI_API_KEY"], repr(result.runtime))

    def test_unsupported_calls_and_arguments_never_reach_dispatch(self):
        responses = [
            reply("open_local_file", {"id": "i"}),
            reply("get_evidence", {"id": "p1", "run_id": "another-run"}),
            reply("get_evidence", {"id": ["p1"]}),
            reply("capture_public", {"provider": "sec"}),
            reply("compare_financials", {"current": "p1", "baseline": "p2", "kind": "custom"}),
            {"model": "contract-model-1", "output": [], "status": "incomplete"},
        ]
        for response in responses:
            with (
                self.subTest(response=response),
                patch.dict(os.environ, SETTINGS, clear=True),
                patch.object(executor, "_post", return_value=response),
            ):
                with self.assertRaises(executor.ExecutorError):
                    executor.execute("Question?", CONTEXT, self.fail)

    def test_request_and_input_limits_stop_before_unapproved_work(self):
        settings = {**SETTINGS, "STOCKINSIGHT_MAX_REQUESTS": "2"}
        requests, tools = [], []

        def transport(body, *_):
            payload = json.loads(body)
            requests.append(payload)
            return reply("list_capabilities", {}, n=len(requests))

        def domain(name, args):
            tools.append(name)
            return {"status": "ok", "data": {}}

        with patch.dict(os.environ, settings, clear=True), patch.object(executor, "_post", transport):
            with self.assertRaises(executor.ExecutorError) as err:
                executor.execute("Q", CONTEXT, domain)
            self.assertEqual(err.exception.code, "budget_exhausted")
            self.assertEqual(len(requests), 2)
            self.assertEqual(len(tools), 1)
            self.assertEqual(requests[-1]["tool_choice"]["name"], "submit_brief")
            with self.assertRaises(executor.ExecutorError):
                executor.execute("x" * executor.MAX_INPUT_BYTES, CONTEXT, domain)
            self.assertEqual(len(requests), 2)

    def test_http_failures_and_redirects_are_typed_and_do_not_disclose_response(self):
        for status, code in ((302, "provider_error"), (401, "authentication"), (429, "rate_limited")):
            with self.subTest(status=status), patch.object(executor.http.client, "HTTPSConnection") as new:
                upstream = new.return_value.getresponse.return_value
                upstream.status = status
                with self.assertRaises(executor.ExecutorError) as err:
                    executor._post(b"{}", "secret", 5)
                self.assertEqual(code, err.exception.code)
                self.assertNotIn("secret", str(err.exception))
                upstream.read.assert_not_called()
                new.return_value.request.assert_called_once()
                new.return_value.close.assert_called_once()

    def test_empty_and_malformed_successful_http_responses_do_not_create_results(self):
        for raw in (b"", b"not JSON", b"x" * (executor.MAX_RESPONSE_BYTES + 1)):
            with self.subTest(length=len(raw)), patch.object(executor.http.client, "HTTPSConnection") as new:
                upstream = new.return_value.getresponse.return_value
                upstream.status = 200
                upstream.read.return_value = raw
                with self.assertRaises(executor.ExecutorError) as err:
                    executor._post(b"{}", "secret", 5)
                self.assertEqual("invalid_response", err.exception.code)
