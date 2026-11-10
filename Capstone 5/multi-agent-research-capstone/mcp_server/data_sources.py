"""
data_sources.py - where the research data comes from.

WHAT THIS FILE DOES
-------------------
Every specialist agent needs facts: prices, financial ratios, news headlines.
This file fetches those facts. It is deliberately kept SEPARATE from the MCP
server (server.py) so that:

  1. We can test the logic on its own (see tests/test_tools.py).
  2. If we ever swap Yahoo Finance for another data provider, only this file
     changes. The agents never notice.

LIVE DATA vs SAMPLE DATA
------------------------
We try to fetch LIVE data from Yahoo Finance using the free `yfinance` library.
If that fails (no internet, Yahoo blocks the request, ticker not found), we fall
back to SAMPLE data so the demo still runs in a classroom.

Sample data is ALWAYS clearly labelled with "data_mode": "sample" so nobody
mistakes it for real market data. The final research note also shows this label.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# Set USE_SAMPLE_DATA=true in your .env file to force offline mode
# (handy when your internet is slow or you are presenting).
FORCE_SAMPLE = os.getenv("USE_SAMPLE_DATA", "false").lower() == "true"

TRADING_DAYS_PER_YEAR = 252  # used to turn daily volatility into yearly volatility


def _now() -> str:
    """Timestamp so every answer says WHEN the data was fetched (good for audit)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _yahoo_source(ticker: str, page: str = "") -> dict:
    """A citation the agents can quote in the final note."""
    url = f"https://finance.yahoo.com/quote/{ticker}/{page}".rstrip("/")
    return {"title": f"Yahoo Finance - {ticker} {page or 'summary'}".strip(), "url": url}


def _sample_source(what: str) -> dict:
    return {"title": f"SAMPLE DATA ({what}) - illustrative only, not real market data",
            "url": "local://sample-data"}


def _ticker(ticker: str):
    """Create a yfinance Ticker object. Imported here so tests run without it."""
    import yfinance as yf
    return yf.Ticker(ticker.upper().strip())


# ---------------------------------------------------------------------------
# 1. Company snapshot (who is this company?)
# ---------------------------------------------------------------------------
def company_snapshot(ticker: str) -> dict:
    ticker = ticker.upper().strip()
    if not FORCE_SAMPLE:
        try:
            info = _ticker(ticker).info or {}
            if info.get("longName") or info.get("shortName"):
                return {
                    "ticker": ticker,
                    "name": info.get("longName") or info.get("shortName"),
                    "sector": info.get("sector"),
                    "industry": info.get("industry"),
                    "market_cap_usd": info.get("marketCap"),
                    "currency": info.get("currency"),
                    "data_mode": "live",
                    "as_of": _now(),
                    "source": _yahoo_source(ticker, "profile"),
                }
        except Exception as err:  # any failure -> fall back to sample data
            print(f"[data_sources] live snapshot failed for {ticker}: {err}")

    return {
        "ticker": ticker,
        "name": f"{ticker} (sample company)",
        "sector": "Technology",
        "industry": "Semiconductors",
        "market_cap_usd": 1_000_000_000_000,
        "currency": "USD",
        "data_mode": "sample",
        "as_of": _now(),
        "source": _sample_source("company snapshot"),
    }


# ---------------------------------------------------------------------------
# 2. Financial metrics (is the business healthy? is it expensive?)
# ---------------------------------------------------------------------------
METRIC_KEYS = {
    "trailing_pe": "trailingPE",
    "forward_pe": "forwardPE",
    "price_to_sales": "priceToSalesTrailing12Months",
    "revenue_growth_yoy": "revenueGrowth",
    "earnings_growth_yoy": "earningsGrowth",
    "gross_margin": "grossMargins",
    "operating_margin": "operatingMargins",
    "profit_margin": "profitMargins",
    "return_on_equity": "returnOnEquity",
    "debt_to_equity": "debtToEquity",
    "free_cash_flow_usd": "freeCashflow",
}


def financial_metrics(ticker: str) -> dict:
    ticker = ticker.upper().strip()
    if not FORCE_SAMPLE:
        try:
            info = _ticker(ticker).info or {}
            metrics = {ours: info.get(theirs) for ours, theirs in METRIC_KEYS.items()}
            if any(v is not None for v in metrics.values()):
                return {
                    "ticker": ticker,
                    "metrics": metrics,
                    "note": "Ratios are decimals: 0.55 means 55%.",
                    "data_mode": "live",
                    "as_of": _now(),
                    "source": _yahoo_source(ticker, "key-statistics"),
                }
        except Exception as err:
            print(f"[data_sources] live metrics failed for {ticker}: {err}")

    return {
        "ticker": ticker,
        "metrics": {
            "trailing_pe": 50.0, "forward_pe": 32.0, "price_to_sales": 25.0,
            "revenue_growth_yoy": 0.60, "earnings_growth_yoy": 0.70,
            "gross_margin": 0.72, "operating_margin": 0.58, "profit_margin": 0.52,
            "return_on_equity": 0.90, "debt_to_equity": 15.0,
            "free_cash_flow_usd": 60_000_000_000,
        },
        "note": "Ratios are decimals: 0.55 means 55%.",
        "data_mode": "sample",
        "as_of": _now(),
        "source": _sample_source("financial metrics"),
    }


# ---------------------------------------------------------------------------
# 3. Price risk metrics (how bumpy is the ride?)
# ---------------------------------------------------------------------------
def _sample_prices(days: int = TRADING_DAYS_PER_YEAR) -> pd.Series:
    """A made-up price path (a 'random walk'). Seeded so it is the same every run."""
    rng = np.random.default_rng(seed=42)
    daily_returns = rng.normal(loc=0.0015, scale=0.03, size=days)
    prices = 100 * np.cumprod(1 + daily_returns)
    index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    return pd.Series(prices, index=index, name="Close")


def compute_risk_metrics(prices: pd.Series) -> dict:
    """
    Pure maths - no internet needed - so we can test it.

    - daily_returns:   % change from one day to the next
    - volatility:      how much returns swing around (standard deviation),
                       scaled up to a yearly figure
    - max_drawdown:    the worst fall from a peak to a later low
    - VaR 95%:         "on 95% of days, the loss was no worse than X%"
    """
    prices = prices.dropna()
    if len(prices) < 20:
        raise ValueError("Need at least 20 price points to compute risk metrics.")

    daily_returns = prices.pct_change().dropna()
    volatility = float(daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))

    running_peak = prices.cummax()
    drawdowns = prices / running_peak - 1
    max_drawdown = float(drawdowns.min())

    var_95 = float(np.percentile(daily_returns, 5))
    period_return = float(prices.iloc[-1] / prices.iloc[0] - 1)

    return {
        "annualised_volatility": round(volatility, 4),
        "max_drawdown": round(max_drawdown, 4),
        "daily_var_95": round(var_95, 4),
        "period_return": round(period_return, 4),
        "worst_day": round(float(daily_returns.min()), 4),
        "best_day": round(float(daily_returns.max()), 4),
        "observations": int(len(prices)),
    }


def price_risk_metrics(ticker: str, period: str = "1y") -> dict:
    ticker = ticker.upper().strip()
    if not FORCE_SAMPLE:
        try:
            t = _ticker(ticker)
            history = t.history(period=period)
            if history is not None and len(history) >= 20:
                metrics = compute_risk_metrics(history["Close"])
                metrics["beta_vs_market"] = (t.info or {}).get("beta")
                return {
                    "ticker": ticker,
                    "period": period,
                    "metrics": metrics,
                    "note": "Decimals: -0.35 max drawdown means the price fell 35% from a peak.",
                    "data_mode": "live",
                    "as_of": _now(),
                    "source": _yahoo_source(ticker, "history"),
                }
        except Exception as err:
            print(f"[data_sources] live price history failed for {ticker}: {err}")

    metrics = compute_risk_metrics(_sample_prices())
    metrics["beta_vs_market"] = 1.7
    return {
        "ticker": ticker,
        "period": period,
        "metrics": metrics,
        "note": "Decimals: -0.35 max drawdown means the price fell 35% from a peak.",
        "data_mode": "sample",
        "as_of": _now(),
        "source": _sample_source("price history"),
    }


# ---------------------------------------------------------------------------
# 4. Earnings information (when is the next results day?)
# ---------------------------------------------------------------------------
def earnings_info(ticker: str) -> dict:
    ticker = ticker.upper().strip()
    if not FORCE_SAMPLE:
        try:
            t = _ticker(ticker)
            calendar = t.calendar or {}
            if isinstance(calendar, pd.DataFrame):  # older yfinance versions
                calendar = calendar.to_dict()
            dates = calendar.get("Earnings Date") or []
            if not isinstance(dates, list):
                dates = [dates]
            info = t.info or {}
            result = {
                "ticker": ticker,
                "next_earnings_dates": [str(d) for d in dates],
                "eps_estimate_avg": calendar.get("Earnings Average"),
                "revenue_estimate_avg": calendar.get("Revenue Average"),
                "trailing_eps": info.get("trailingEps"),
                "forward_eps": info.get("forwardEps"),
                "analyst_recommendation": info.get("recommendationKey"),
                "number_of_analysts": info.get("numberOfAnalystOpinions"),
                "data_mode": "live",
                "as_of": _now(),
                "source": _yahoo_source(ticker, "analysis"),
            }
            if result["next_earnings_dates"] or result["trailing_eps"] is not None:
                return result
        except Exception as err:
            print(f"[data_sources] live earnings failed for {ticker}: {err}")

    return {
        "ticker": ticker,
        "next_earnings_dates": ["(sample) in about 3 weeks"],
        "eps_estimate_avg": 1.00,
        "revenue_estimate_avg": 50_000_000_000,
        "trailing_eps": 3.00,
        "forward_eps": 4.50,
        "analyst_recommendation": "buy",
        "number_of_analysts": 50,
        "data_mode": "sample",
        "as_of": _now(),
        "source": _sample_source("earnings calendar"),
    }


# ---------------------------------------------------------------------------
# 5. Recent news (what is the market talking about?)
# ---------------------------------------------------------------------------
def _parse_news_item(item: dict) -> dict | None:
    """yfinance changed its news format in 2025, so we handle old and new shapes."""
    content = item.get("content") or item  # new format nests everything in "content"
    title = content.get("title")
    if not title:
        return None
    url = (
        (content.get("canonicalUrl") or {}).get("url")
        or (content.get("clickThroughUrl") or {}).get("url")
        or content.get("link")
    )
    publisher = (content.get("provider") or {}).get("displayName") or content.get("publisher")
    published = content.get("pubDate") or content.get("providerPublishTime")
    if isinstance(published, (int, float)):
        published = datetime.fromtimestamp(published, tz=timezone.utc).strftime("%Y-%m-%d")
    return {
        "title": title,
        "publisher": publisher,
        "published": str(published) if published else None,
        "url": url,
        "summary": content.get("summary") or "",
    }


def recent_news(ticker: str, limit: int = 8) -> dict:
    ticker = ticker.upper().strip()
    limit = max(1, min(int(limit), 20))
    if not FORCE_SAMPLE:
        try:
            raw = _ticker(ticker).news or []
            articles = [a for a in (_parse_news_item(i) for i in raw) if a][:limit]
            if articles:
                return {"ticker": ticker, "articles": articles, "data_mode": "live", "as_of": _now()}
        except Exception as err:
            print(f"[data_sources] live news failed for {ticker}: {err}")

    sample = [
        ("Chipmaker's data-centre revenue expected to dominate upcoming results", "positive"),
        ("Analysts debate whether AI spending by cloud firms can stay this high", "mixed"),
        ("New export restrictions could limit sales of advanced chips to some markets", "negative"),
        ("Supply of advanced packaging capacity remains tight, say suppliers", "mixed"),
        ("Options market prices a large share-price move around earnings day", "neutral"),
    ]
    articles = [
        {"title": f"[SAMPLE] {title}", "publisher": "Sample Newswire",
         "published": None, "url": "local://sample-data", "summary": f"Illustrative {tone} headline."}
        for title, tone in sample[:limit]
    ]
    return {"ticker": ticker, "articles": articles, "data_mode": "sample", "as_of": _now()}
