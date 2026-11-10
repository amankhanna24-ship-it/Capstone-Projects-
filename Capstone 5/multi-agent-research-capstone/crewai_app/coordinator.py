"""
coordinator.py - the DISPATCHER half of the Coordinator.

THE COORDINATOR-DISPATCHER PATTERN (plain English)
--------------------------------------------------
Think of a newspaper editor. A question comes in: "Brief me on NVDA earnings
risk". The editor does not write everything alone. They:

  1. DECOMPOSE   - work out what the question is really asking about
  2. DISPATCH    - send the right reporters (specialists) out
  3. AGGREGATE   - combine their reports into one story

This file does steps 1 and 2. It is plain Python rules, not an LLM, on purpose:
  - it is fast and free (no API call)
  - it always gives the same answer for the same question (predictable)
  - it is easy to test and to explain in an audit

Step 3 (aggregate) is done by the Coordinator AGENT in agents.py, because
writing a good summary needs an LLM's language skills.

(The Google ADK version in adk_app/ shows the other style: there, an LLM
decides which specialists to call. Comparing the two is a good discussion
point for your capstone write-up.)
"""

from __future__ import annotations

import re

from shared.messages import DispatchPlan

# Words in the question -> which specialist should handle it
ROUTING_KEYWORDS: dict[str, list[str]] = {
    "financial_analyst": [
        "earnings", "revenue", "margin", "profit", "valuation", "p/e", "pe ratio",
        "eps", "growth", "financial", "fundamental", "cash flow", "balance sheet", "guidance",
    ],
    "risk_assessor": [
        "risk", "volatil", "drawdown", "downside", "exposure", "beta", "var",
        "safe", "crash", "hedge", "uncertain",
    ],
    "news_researcher": [
        "news", "latest", "recent", "headline", "sentiment", "announce",
        "event", "regulat", "export", "earnings",   # earnings season is always newsworthy
    ],
}

# If the question uses one of these words, the user wants the full picture
BROAD_REQUEST_WORDS = ["brief", "overview", "report", "full", "research note",
                       "deep dive", "analyse", "analyze", "summary", "everything"]

# A few company names people type instead of tickers
COMPANY_TO_TICKER = {
    "nvidia": "NVDA", "apple": "AAPL", "microsoft": "MSFT", "amazon": "AMZN",
    "alphabet": "GOOGL", "google": "GOOGL", "meta": "META", "tesla": "TSLA",
    "amd": "AMD", "intel": "INTC", "netflix": "NFLX", "tsmc": "TSM",
}

# Upper-case words that are NOT tickers
NOT_TICKERS = {"I", "A", "AI", "CEO", "CFO", "EPS", "PE", "VAR", "US", "UK", "EU",
               "USA", "ETF", "IPO", "Q1", "Q2", "Q3", "Q4", "YOY", "ESG", "GDP"}

# The Compliance Checker always runs - no note leaves the building unchecked
ALWAYS_INCLUDED = "compliance_checker"


def extract_ticker(query: str) -> str | None:
    """Find the stock ticker in a question, e.g. 'NVDA' in 'Brief me on NVDA risk'."""
    # 1. "$NVDA" style
    dollar = re.search(r"\$([A-Za-z]{1,5})\b", query)
    if dollar:
        return dollar.group(1).upper()
    # 2. A word in CAPITALS, 1-5 letters long, that isn't a common abbreviation
    for word in re.findall(r"\b[A-Z]{1,5}\b", query):
        if word not in NOT_TICKERS:
            return word
    # 3. A company name we recognise
    lower = query.lower()
    for name, ticker in COMPANY_TO_TICKER.items():
        if re.search(rf"\b{name}\b", lower):
            return ticker
    return None


def plan_research(query: str, ticker: str | None = None) -> DispatchPlan:
    """Decide which specialists to send, and explain why (for the audit trail)."""
    ticker = (ticker or extract_ticker(query) or "").upper()
    if not ticker:
        raise ValueError("I couldn't find a ticker in your question. Try e.g. "
                         "'Brief me on NVDA earnings risk' or pass --ticker NVDA.")

    lower = query.lower()
    chosen: list[str] = []
    focus: list[str] = []

    for specialist, keywords in ROUTING_KEYWORDS.items():
        hits = [k for k in keywords if k in lower]
        if hits:
            chosen.append(specialist)
            focus.extend(hits)

    broad = any(word in lower for word in BROAD_REQUEST_WORDS)
    if broad or not chosen:
        chosen = list(ROUTING_KEYWORDS.keys())  # send everyone
        reason = ("Broad research request" if broad else "No specific theme detected") + \
                 " - dispatching all specialists for a complete picture."
    else:
        reason = f"Matched themes {sorted(set(focus))} - dispatching only the relevant specialists."

    chosen.append(ALWAYS_INCLUDED)
    reason += " Compliance Checker always reviews the final note."

    return DispatchPlan(
        query=query,
        ticker=ticker,
        specialists=chosen,
        focus=sorted(set(focus)),
        reasoning=reason,
    )
