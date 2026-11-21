"""Credential boundaries across real loopback origins in one disposable browser profile."""

import os
import tempfile
import unittest
from contextlib import ExitStack, closing
from importlib.util import find_spec
from pathlib import Path

from stockinsight.db import connect
from tests.test_insight_web import served


@unittest.skipUnless(find_spec("playwright"), "Install the browser-test dependency group")
class OriginAuthenticationTest(unittest.TestCase):
    def test_two_private_desks_keep_distinct_credentials_in_one_browser(self):
        from fastapi import FastAPI, Request, Response
        from playwright.sync_api import sync_playwright

        from stockinsight.web import application

        with ExitStack() as stack:
            folder = Path(stack.enter_context(tempfile.TemporaryDirectory()))
            desks = []
            for mode in ("fixture", "ordinary"):
                path = folder / mode / "research.sqlite3"
                with closing(connect(path, fixture=mode == "fixture")):
                    pass
                password = mode + "-synthetic-test"
                port = stack.enter_context(
                    served(lambda p, path=path, password=password: application(path, p, password))
                )
                desks.append((f"http://127.0.0.1:{port}", password))
            # A neutral, test-owned origin answers only whether the request was anonymous.
            # No credential or request content is retained by the test application.
            neutral = FastAPI()

            @neutral.get("/")
            def anonymous(req: Request):
                return Response(
                    "anonymous"
                    if not ({"authorization", "cookie"} & set(req.headers))
                    else "unexpected credentials"
                )

            other = stack.enter_context(served(lambda _: neutral))
            driver = stack.enter_context(sync_playwright())
            channel = os.environ.get("STOCKINSIGHT_TEST_BROWSER", "msedge" if os.name == "nt" else "chromium")
            browser = driver.chromium.launch(channel=channel, headless=True)
            stack.callback(browser.close)
            context = browser.new_context()
            page = context.new_page()
            for origin, password in desks:
                # Populate Chromium's own HTTP authentication cache for this synthetic origin.
                # Supplying an Authorization header in the test would bypass that boundary.
                if context.request.get(origin + "/", max_redirects=0).status == 303:
                    # Reviewed build uses form authentication. Initialize that browser
                    # jar through its normal POST with the required same-origin header.
                    self.assertTrue(
                        context.request.post(
                            origin + "/login", form={"code": password}, headers={"Origin": origin}
                        ).ok
                    )
                    page.goto(origin + "/")
                else:
                    page.goto(origin.replace("://", f"://research:{password}@") + "/")
                self.assertEqual(page.get_by_role("heading", name="Research desk").count(), 1)
            page.goto(f"http://127.0.0.1:{other}/")
            self.assertEqual(page.locator("body").inner_text(), "anonymous")
            for origin, _ in desks:
                self.assertEqual(page.goto(origin + "/status").status, 200)
                self.assertEqual(page.get_by_role("heading", name="Workspace status").count(), 1)
                page.get_by_role("link", name="Companies & themes").click()
                page.get_by_label("One ticker per line").fill("NVDA")
                page.get_by_label("This is the complete selected list").check()
                page.get_by_role("button", name="Import snapshot").click()
                self.assertEqual(page.get_by_role("link", name="NVDA").count(), 1)
            self.assertEqual(context.cookies(), [])
