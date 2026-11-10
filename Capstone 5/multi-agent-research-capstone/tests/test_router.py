"""
test_router.py - checks that the Coordinator's dispatcher sends the right specialists.
Run:  pytest -v
"""

import pytest

from crewai_app.coordinator import extract_ticker, plan_research


@pytest.mark.parametrize("question, expected", [
    ("Brief me on NVDA earnings risk", "NVDA"),
    ("What's happening with $msft?", "MSFT"),
    ("Is Nvidia's AI growth priced in?", "NVDA"),
    ("How risky is TSLA before Q3 results?", "TSLA"),
])
def test_ticker_extraction(question, expected):
    assert extract_ticker(question) == expected


def test_broad_request_dispatches_everyone():
    plan = plan_research("Brief me on NVDA earnings risk")
    assert set(plan.specialists) == {"financial_analyst", "risk_assessor",
                                     "news_researcher", "compliance_checker"}


def test_news_only_question_skips_financial_and_risk():
    plan = plan_research("Any latest headlines on AAPL?")
    assert "news_researcher" in plan.specialists
    assert "financial_analyst" not in plan.specialists
    assert "risk_assessor" not in plan.specialists


def test_compliance_checker_always_included():
    plan = plan_research("What is the volatility of AMD?")
    assert "compliance_checker" in plan.specialists
    assert "risk_assessor" in plan.specialists


def test_missing_ticker_raises_helpful_error():
    with pytest.raises(ValueError):
        plan_research("how is the market doing today?")
