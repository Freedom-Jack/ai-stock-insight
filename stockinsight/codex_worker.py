"""Explicit read-only check of the installed Codex app-server account and quota."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading


def _rpc(process, request_id, method, params):
    request = {"id": request_id, "method": method, "params": params}
    process.stdin.write(json.dumps(request).encode("ascii") + b"\n")
    process.stdin.flush()
    for _ in range(64):
        raw = process.stdout.readline(512_001)
        if not raw or len(raw) > 512_000:
            break
        message = json.loads(raw)
        if message.get("id") == request_id and "method" not in message:
            return message.get("result")
    return None


def _summarize(account_reply, limit_reply):
    account = (account_reply or {}).get("account") or {}
    auth = account.get("type")
    plan = account.get("planType")
    limit = (limit_reply or {}).get("rateLimits") or {}
    credits = limit.get("credits") or {}

    def percent(key):
        number = (limit.get(key) or {}).get("usedPercent")
        return number if type(number) is int and 0 <= number <= 100 else None

    return {
        "account_read": isinstance(account_reply, dict),
        "authentication": auth
        if auth in ("chatgpt", "apiKey", "amazonBedrock")
        else "unverified",
        "plan": plan
        if plan
        in {
            "free",
            "go",
            "plus",
            "pro",
            "prolite",
            "team",
            "business",
            "enterprise",
            "edu",
            "edu_plus",
            "edu_pro",
        }
        else "unknown",
        "limits_read": bool(limit),
        "primary_used_percent": percent("primary"),
        "secondary_used_percent": percent("secondary"),
        "has_credits": credits.get("hasCredits")
        if type(credits.get("hasCredits")) is bool
        else None,
        "unlimited_credits": credits.get("unlimited")
        if type(credits.get("unlimited")) is bool
        else None,
        "included_only_enforced": False,
        "host_tools_only_enforced": False,
        "hosted_codex_enabled": False,
    }


def probe():
    """Never create a thread, start a turn, refresh credentials or redeem credits."""
    binary = shutil.which("codex.exe" if os.name == "nt" else "codex")
    account = limits = None
    if binary:
        try:
            with subprocess.Popen(
                [binary, "app-server", "--stdio"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ) as process:
                deadline = threading.Timer(25, process.kill)
                deadline.start()
                try:
                    init = {
                        "clientInfo": {
                            "name": "stockinsight",
                            "title": "Stock Insight",
                            "version": "0.2",
                        }
                    }
                    if isinstance(_rpc(process, 1, "initialize", init), dict):
                        process.stdin.write(b'{"method":"initialized"}\n')
                        account = _rpc(
                            process, 2, "account/read", {"refreshToken": False}
                        )
                        if (
                            isinstance(account, dict)
                            and (account.get("account") or {}).get("type") == "chatgpt"
                        ):
                            limits = _rpc(process, 3, "account/rateLimits/read", None)
                finally:
                    deadline.cancel()
                    process.kill()
                    process.wait()
        except (OSError, ValueError):
            pass
    return _summarize(account, limits)


if __name__ == "__main__":
    print(json.dumps(probe(), indent=2))
