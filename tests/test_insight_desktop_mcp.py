"""Exercise the private desktop launch manifest with a real MCP subprocess."""

import importlib.util
import json
import os
import secrets
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from stockinsight import assistant, assistant_mcp, db, desktop_mcp, replay


class Scope(unittest.TestCase):
    def test_refuse_missing_and_personal_database(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            with self.assertRaises(sqlite3.OperationalError):
                desktop_mcp.package(directory)
            path = directory / "research.sqlite3"
            self.assertFalse(path.exists())
            with closing(db.connect(path, fixture=False)) as conn:
                assistant.configure(conn, "Historical replay · company")
            with self.assertRaisesRegex(ValueError, "dedicated"):
                desktop_mcp.package(directory)
            self.assertFalse((directory / "desktop-marketplace").exists())


@unittest.skipUnless(os.name == "nt" and importlib.util.find_spec("mcp"), "requires Windows DPAPI and fiscal extra")
class DesktopTransport(unittest.IsolatedAsyncioTestCase):
    async def test_manifest_claim_research_and_follow_up(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            path = directory / "research.sqlite3"
            with closing(replay.workspace(directory, "company")) as conn:
                job = replay.advance(conn, "company")["jobs"][0]["id"]
            with self.assertRaisesRegex(ValueError, "Enable"):
                desktop_mcp.package(directory)
            assistant_mcp.token(path, create=True)
            market = desktop_mcp.package(directory)
            self.assertEqual(desktop_mcp.package(directory), market)
            manifest = market / "plugins/stock-insight-replay/.mcp.json"
            launch = json.loads(manifest.read_text(encoding="utf-8"))["mcpServers"]["stock-insight-replay"]
            async with stdio_client(StdioServerParameters(**launch)) as (r, w), ClientSession(r, w) as session:
                await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                self.assertEqual(tools, assistant_mcp.TOOLS.keys() - {"capture_public"})

                async def call(name, **args):
                    result = await session.call_tool(name, args)
                    self.assertFalse(result.isError, result.content)
                    return json.loads(result.content[0].text)

                self.assertEqual((await call("monitor_health"))["pending"][0]["job_id"], job)
                for followup in (False, True):
                    current_job = job
                    if followup:
                        with closing(db.connect(path, fixture=True)) as conn:
                            self.assertEqual(replay.advance(conn, "company")["step"], "filing")
                        request = dict(case_id=job, question="What changes if demand slows?", request_key="follow-1")
                        reply = await call("request_followup", **request)
                        self.assertEqual(reply, await call("request_followup", **request))
                        current_job = reply["job_id"]
                    args = dict(job_id=current_job, worker_key=secrets.token_hex(20))
                    self.assertEqual((await call("claim_research", **args))["case_id"], job)
                    passages = [
                        await call("read_evidence", **args, passage_id=item["id"])
                        for item in await call("list_evidence", **args)
                    ]
                    periods = {p["financial"]["period_label"]: p["id"] for p in passages if p.get("financial")}
                    calc = await call("compare_financials", **args, current=periods["Q2 FY25"], baseline=periods["Q1 FY25"])
                    self.assertEqual((calc["difference"], calc["percent_change"]), ("3996", "15.3433"))
                    self.assertEqual(any(p["origin"] == "historical_filing" for p in passages), followup)
                    submission = dict(
                        **args, passage_ids=[p["id"] for p in passages], calculation_ids=[calc["receipt"]],
                        hypothesis="Growing shipments could lift next-quarter revenue.",
                        alternative="Order timing could account for some of the increase.",
                        next_check="Read the next quarter's revenue and inventory disclosure.",
                    )
                    result = await call("accept_research", **submission)
                    self.assertEqual(result, await call("accept_research", **submission))
                    self.assertEqual(len(result["citations"]), 3 if followup else 2)
                self.assertEqual([j["state"] for j in (await call("read_case", case_id=job))["jobs"]], ["accepted"] * 2)
                with closing(db.connect(path, fixture=True)) as conn:
                    self.assertEqual(len(assistant.case(conn, job)["jobs"]), 2)
                    conn.execute("UPDATE assistant_profile SET enabled=0")
                self.assertTrue((await session.call_tool("monitor_health", {})).isError)
