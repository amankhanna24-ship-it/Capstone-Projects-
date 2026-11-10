"""
check_mcp_server.py - a quick "is the server working?" test. No LLM, no API key needed.

It connects to the running MCP server exactly like an agent would, lists the
tools, and calls a couple of them.

Run it (with the server already running in another terminal):
    python scripts/check_mcp_server.py
    python scripts/check_mcp_server.py MSFT
"""

import asyncio
import json
import os
import sys

from fastmcp import Client

URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")


def _as_dict(result):
    """FastMCP versions return results slightly differently; this handles both."""
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured.get("result", structured)
    return {"raw": str(result)}


async def main(ticker: str) -> None:
    async with Client(URL) as client:
        tools = await client.list_tools()
        print(f"Connected to {URL}")
        print(f"Found {len(tools)} tools:")
        for tool in tools:
            print(f"  - {tool.name}")

        print(f"\nCalling get_price_risk_metrics('{ticker}') ...")
        risk = _as_dict(await client.call_tool("get_price_risk_metrics", {"ticker": ticker}))
        print(json.dumps(risk, indent=2, default=str))

        print("\nCalling check_compliance on a deliberately bad sentence ...")
        verdict = _as_dict(await client.call_tool(
            "check_compliance", {"text": "NVDA is a guaranteed return. Buy now!"}))
        print(json.dumps(verdict, indent=2))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "NVDA"))
