"""
test_tools.py - automatic checks for the MCP server's logic.

Run:  pytest -v

Tests are small programs that check your code does what you think. They need
no API key and no internet (we force sample data), so they run anywhere.
"""

import os

os.environ["USE_SAMPLE_DATA"] = "true"   # must be set before importing data_sources

import pandas as pd
import pytest

from mcp_server import data_sources
from mcp_server.compliance_rules import run_compliance_checks

GOOD_NOTE = """
# Research Note: NVDA - Earnings risk
Data mode: sample data (illustrative).
Revenue grew 60% [1]. Volatility is 45% a year [2], so the share price could fall sharply
if results disappoint. Key risk: export restrictions.
## Sources
[1] SAMPLE DATA - local://sample-data
[2] SAMPLE DATA - local://sample-data
Disclaimer: This note is for educational purposes only and is not investment advice.
"""


# ---------- risk maths ----------
def test_max_drawdown_is_calculated_correctly():
    # Price goes 100 -> 120 (peak) -> 60 (trough) -> 90. Worst fall = 60/120 - 1 = -50%
    prices = pd.Series([100, 110, 120, 100, 80, 60, 70, 80, 90] + [90] * 15, dtype=float)
    metrics = data_sources.compute_risk_metrics(prices)
    assert metrics["max_drawdown"] == pytest.approx(-0.5)


def test_flat_prices_have_zero_volatility():
    metrics = data_sources.compute_risk_metrics(pd.Series([100.0] * 30))
    assert metrics["annualised_volatility"] == 0


def test_too_few_prices_raises_error():
    with pytest.raises(ValueError):
        data_sources.compute_risk_metrics(pd.Series([1.0, 2.0, 3.0]))


# ---------- sample-data fallback ----------
@pytest.mark.parametrize("fetch", [
    data_sources.company_snapshot, data_sources.financial_metrics,
    data_sources.price_risk_metrics, data_sources.earnings_info,
])
def test_sample_data_is_clearly_labelled(fetch):
    result = fetch("NVDA")
    assert result["data_mode"] == "sample"
    assert "SAMPLE" in result["source"]["title"]


def test_news_returns_requested_number_of_articles():
    result = data_sources.recent_news("NVDA", limit=3)
    assert len(result["articles"]) == 3
    assert all(a["url"] for a in result["articles"])


# ---------- compliance rules ----------
def test_good_note_passes():
    verdict = run_compliance_checks(GOOD_NOTE)
    assert verdict["passed"], verdict["issues"]


def test_promise_of_returns_is_blocked():
    verdict = run_compliance_checks(GOOD_NOTE + "\nThis is a guaranteed return.")
    assert not verdict["passed"]
    assert any("guaranteed return" in i for i in verdict["issues"])


def test_missing_disclaimer_is_blocked():
    note = GOOD_NOTE.replace("not investment advice", "").replace("for educational purposes", "")
    verdict = run_compliance_checks(note)
    assert any("disclaimer" in i for i in verdict["issues"])


def test_absolute_language_gives_warning_not_blocker():
    verdict = run_compliance_checks(GOOD_NOTE + "\nThe stock always recovers.")
    assert verdict["passed"]
    assert verdict["warnings"]
