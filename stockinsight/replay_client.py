"""Call the enabled Stock Insight Replay plugin from an authorized local task.

Read one JSON object with name and arguments from stdin. Use tools/list for
discovery. The installed server owns workspace selection and all data access.
"""

import asyncio
import json
import shutil
import subprocess
import sys


def permitted(config, name):
    allowed = config.get("enabled_tools")
    return (allowed is None or name in allowed) and name not in (config.get("disabled_tools") or ())


async def request(config, name, arguments):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    if not config.get("enabled"):
        raise ValueError("Stock Insight Replay is disabled in this environment.")
    transport = config["transport"]
    if transport["type"] != "stdio" or transport.get("env") or transport.get("env_vars"):
        raise ValueError("Expected the installed local replay configuration.")
    if name != "tools/list" and not permitted(config, name):
        raise ValueError("This tool is disabled in the local configuration.")
    launch = StdioServerParameters(command=transport["command"], args=transport["args"], cwd=transport["cwd"])
    async with stdio_client(launch) as (reader, writer), ClientSession(reader, writer) as session:
        await session.initialize()
        if name == "tools/list":
            items = (await session.list_tools()).tools
            return {"tools": [t.model_dump(exclude_none=True) for t in items if permitted(config, t.name)]}
        result = await session.call_tool(name, arguments)
        return result.model_dump(exclude_none=True)


def main():
    command = shutil.which("codex")
    if not command:
        sys.exit("The local Codex CLI is required to discover the enabled replay plugin.")
    try:
        message = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
        if not isinstance(message, dict) or not isinstance(message.get("name"), str):
            raise ValueError("Supply a JSON object with a tool name.")
        arguments = message.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("Supply tool arguments as a JSON object.")
        reply = subprocess.run([command, "mcp", "get", "stock-insight-replay", "--json"],
                               capture_output=True, encoding="utf-8")
        if reply.returncode:
            raise ValueError("Stock Insight Replay is unavailable in this local configuration.")
        output = asyncio.run(request(json.loads(reply.stdout), message["name"], arguments))
        print(json.dumps(output, ensure_ascii=True))
        return int(bool(output.get("isError")))
    except (ValueError, OSError) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    sys.exit(main())
