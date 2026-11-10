"""
server.py - our custom MCP server, built with FastMCP.

WHAT IS AN MCP SERVER? (plain English)
--------------------------------------
MCP = Model Context Protocol. Think of it like a USB-C port for AI tools.
Any AI agent that "speaks MCP" (CrewAI, Google ADK, Flowise, n8n, Claude,
MCP Inspector ...) can plug into this server and use its tools - without us
writing special code for each framework.

So we write our tools ONCE, here, and both our code-first agents and our
visual Flowise workflow reuse them. That is the main reason MCP exists.

HOW FASTMCP HELPS
-----------------
FastMCP turns an ordinary Python function into an MCP tool with one line:
`@mcp.tool`. It reads the function's name, its type hints and its docstring,
and tells the AI: "here is a tool called X, it needs these inputs, and here
is what it does". The docstring matters - the LLM reads it to decide WHEN to
use the tool, so we write docstrings for the AI as much as for humans.

HOW TO RUN
----------
    python -m mcp_server.server            # starts on http://localhost:8000/mcp
    docker compose up --build              # same thing, inside Docker
"""

from __future__ import annotations

import os
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_server import data_sources
from mcp_server.compliance_rules import run_compliance_checks

# Create the server. The "instructions" text is shown to any AI that connects.
mcp = FastMCP(
    name="financial-research-tools",
    instructions=(
        "Tools for investment research. Every tool returns a 'source' or 'url' "
        "field - always cite it. If 'data_mode' is 'sample', say clearly that "
        "the figures are illustrative sample data."
    ),
)

# Type hints with descriptions. The AI sees these descriptions too.
Ticker = Annotated[str, Field(description="Stock ticker symbol, e.g. 'NVDA' or 'MSFT'.")]


# ---------------------------------------------------------------------------
# TOOLS used by the Financial Analyst
# ---------------------------------------------------------------------------
@mcp.tool(tags={"financial"})
def get_company_snapshot(ticker: Ticker) -> dict:
    """Get the company's name, sector, industry and market capitalisation.
    Use this first to confirm which company a ticker refers to."""
    return data_sources.company_snapshot(ticker)


@mcp.tool(tags={"financial"})
def get_financial_metrics(ticker: Ticker) -> dict:
    """Get valuation and profitability ratios: P/E, forward P/E, revenue growth,
    margins, return on equity, debt-to-equity and free cash flow.
    Ratios are decimals (0.55 = 55%)."""
    return data_sources.financial_metrics(ticker)


@mcp.tool(tags={"financial", "risk"})
def get_earnings_info(ticker: Ticker) -> dict:
    """Get the next earnings date, analyst EPS and revenue estimates, trailing and
    forward EPS, and the consensus analyst recommendation."""
    return data_sources.earnings_info(ticker)


# ---------------------------------------------------------------------------
# TOOLS used by the Risk Assessor
# ---------------------------------------------------------------------------
@mcp.tool(tags={"risk"})
def get_price_risk_metrics(
    ticker: Ticker,
    period: Annotated[str, Field(description="Look-back window: '6mo', '1y', '2y' or '5y'.")] = "1y",
) -> dict:
    """Calculate price-based risk: annualised volatility, maximum drawdown,
    95% daily Value-at-Risk, best/worst day, period return and beta vs the market."""
    if period not in {"3mo", "6mo", "1y", "2y", "5y"}:
        period = "1y"
    return data_sources.price_risk_metrics(ticker, period)


# ---------------------------------------------------------------------------
# TOOLS used by the News Researcher
# ---------------------------------------------------------------------------
@mcp.tool(tags={"news"})
def get_recent_news(
    ticker: Ticker,
    limit: Annotated[int, Field(description="How many articles to return (1-20).", ge=1, le=20)] = 8,
) -> dict:
    """Get recent news headlines about the company, each with publisher, date and URL."""
    return data_sources.recent_news(ticker, limit)


# ---------------------------------------------------------------------------
# TOOLS used by the Compliance Checker
# ---------------------------------------------------------------------------
@mcp.tool(tags={"compliance"})
def check_compliance(
    text: Annotated[str, Field(description="The full draft research note to check.")],
) -> dict:
    """Run rule-based compliance checks on a draft research note: prohibited
    promissory language, missing disclaimer, missing citations, missing risk
    discussion and undisclosed sample data. Returns passed=True/False, blocking
    issues and warnings."""
    return run_compliance_checks(text)


# ---------------------------------------------------------------------------
# A plain web page for health checks (used by Docker to see if we're alive)
# ---------------------------------------------------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "financial-research-tools"})


if __name__ == "__main__":
    # "http" = Streamable HTTP transport. Agents connect to http://<host>:<port>/mcp
    # Inside Docker we must listen on 0.0.0.0 (all network interfaces), not just localhost.
    mcp.run(
        transport="http",
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=int(os.getenv("MCP_PORT", "8000")),
    )
