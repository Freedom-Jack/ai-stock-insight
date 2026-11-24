"""Local desktop MCP transport for a personal desk or an isolated historical replay."""

import argparse
import asyncio
import importlib.util
import json
import os
import sqlite3
import sys
from contextlib import closing, contextmanager
from pathlib import Path

from . import assistant, assistant_mcp, backup, db


def personal_directory():
    return backup._local_path(Path(os.environ["LOCALAPPDATA"]) / "StockInsight" / "personal")


@contextmanager
def workspace_connection(directory, personal=False):
    path = backup._local_path(directory / "research.sqlite3")
    if personal and path.parent != personal_directory():
        raise ValueError("Choose this Windows user's personal Stock Insight desk.")
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, isolation_level=None)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        profile = assistant.profile(conn)
        if personal and (db.is_fixture(conn) or profile["replay_clock"]):
            raise ValueError("The personal desk cannot target a replay.")
        if not personal and (not db.is_fixture(conn) or profile["label"] != "Historical replay · company"):
            raise ValueError("Choose a dedicated historical company replay.")
        if not profile["enabled"] or not assistant_mcp.token(path):
            raise ValueError("Enable the selected desk under the current Windows account first.")
        yield conn


def package(directory, personal=False):
    # Only the local generated manifest contains the machine-specific paths.
    with workspace_connection(directory, personal):
        pass
    root = backup._local_path(directory / "desktop-marketplace")
    name = "stock-insight" if personal else "stock-insight-replay"
    display = "Stock Insight" if personal else "Stock Insight Replay"
    plugin = root / "plugins" / name
    files = {
        root / ".agents/plugins/marketplace.json": {
            "name": "stock-insight-personal" if personal else "stock-insight-local",
            "interface": {"displayName": "Stock Insight Personal" if personal else "Stock Insight Local"},
            "plugins": [{
                "name": name, "source": {"source": "local", "path": "./plugins/" + name},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }],
        },
        plugin / ".codex-plugin/plugin.json": {
            "name": name, "version": "0.1.0",
            "description": "Read public evidence and submit research for your personal watchlist." if personal else "Research and follow up on an isolated historical earnings replay.",
            "mcpServers": "./.mcp.json",
            "interface": {"displayName": display},
        },
        plugin / ".mcp.json": {
            "mcpServers": {name: {
                "command": sys.executable,
                "args": ["-B", "-m", "stockinsight.desktop_mcp", "serve"] +
                        (["--personal"] if personal else ["--directory", str(directory.resolve())]),
                "cwd": str(Path(__file__).resolve().parents[1]),
            }},
        },
    }
    for path, contents in files.items():
        path = backup._local_path(path)
        serialized = json.dumps(contents, ensure_ascii=False, indent=2) + "\n"
        if path.exists():
            if path.read_text(encoding="utf-8") != serialized:
                raise ValueError(f"Existing manifest differs: {path}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
    return root


async def serve(directory, personal=False):
    from mcp import types
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    with workspace_connection(directory, personal):
        pass
    server = Server(
        "Stock Insight" if personal else "Stock Insight Replay",
        instructions="Use monitor_health to find the job. Claim it, read its frozen passages, compare financials "
        "and submit citations. For a follow-up use request_followup with the same case ID, then investigate it.",
    )

    @server.list_tools()
    async def list_tools():
        with workspace_connection(directory, personal) as conn:
            tools = assistant_mcp.rpc(conn, "tools/list", {})["tools"]
        return [types.Tool.model_validate(tool) for tool in tools if tool["name"] != "capture_public"]

    @server.call_tool()
    async def call_tool(name, arguments):
        if name == "capture_public":
            raise ValueError("Desktop research uses the case's saved evidence.")
        with workspace_connection(directory, personal) as conn:
            result = assistant_mcp.rpc(conn, "tools/call", {"name": name, "arguments": arguments})
        return types.CallToolResult.model_validate(result)

    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("package", "serve"))
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--directory", type=Path, help="Isolated historical replay")
    target.add_argument("--personal", action="store_true", help="Current Windows user's live personal desk")
    args = parser.parse_args(argv)
    try:
        if args.action == "package":
            if not importlib.util.find_spec("mcp"):
                parser.error("Install the locked fiscal extra for desktop MCP.")
            print(package(personal_directory() if args.personal else args.directory, args.personal))
        else:
            asyncio.run(serve(personal_directory() if args.personal else args.directory, args.personal))
    except (ValueError, sqlite3.Error, OSError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
