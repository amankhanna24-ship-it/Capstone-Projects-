"""
agents.py - the team members (agents) and which tools each is allowed to use.

WHAT IS A CREWAI AGENT?
-----------------------
An agent = an LLM + a job description + some tools. In CrewAI you describe it
like hiring a person:
  - role       : job title
  - goal       : what success looks like
  - backstory  : experience and habits (this shapes HOW it works)
  - tools      : what it is allowed to use

WHY SPECIALISTS?
----------------
A single "do-everything" agent gets confused and is hard to check. Giving each
agent ONE job and ONLY the tools for that job makes it better at the job and
makes it obvious who said what. This is the "principle of least privilege" -
the News Researcher can't run compliance checks, and the Compliance Checker
can't fetch prices.
"""

from __future__ import annotations

from crewai import LLM, Agent

from shared.config import CREWAI_MODEL

# Which MCP tools each specialist may use
TOOLS_FOR = {
    "financial_analyst": ["get_company_snapshot", "get_financial_metrics", "get_earnings_info"],
    "risk_assessor": ["get_price_risk_metrics", "get_earnings_info", "get_financial_metrics"],
    "news_researcher": ["get_recent_news", "get_company_snapshot"],
    "compliance_checker": ["check_compliance"],
    "coordinator": [],  # the Coordinator writes; it doesn't fetch data itself
}


def make_llm() -> LLM:
    # Low temperature = more factual, less "creative". Right for research.
    return LLM(model=CREWAI_MODEL, temperature=0.2)


# Settings shared by every agent:
#  - max_retry_limit: if a Gemini call fails (e.g. "Server disconnected"), retry this agent
#    up to 5 times instead of CrewAI's default of 2. Free-tier connections drop now and then.
#  - max_rpm: at most 10 requests per minute per agent, so we don't hammer the free tier
#    (bursts of requests are a common cause of dropped connections and 429 errors).
#  - allow_delegation=False: specialists don't hand work to each other; the Coordinator decides.
COMMON = dict(verbose=True, allow_delegation=False, max_retry_limit=5, max_rpm=10)


def _pick(tools_by_name: dict, names: list[str]) -> list:
    missing = [n for n in names if n not in tools_by_name]
    if missing:
        raise RuntimeError(f"MCP server is missing tools {missing}. Is the server running?")
    return [tools_by_name[n] for n in names]


def build_agents(tools_by_name: dict) -> dict[str, Agent]:
    llm = make_llm()

    financial_analyst = Agent(
        role="Financial Analyst",
        goal="Explain the company's financial health, growth and valuation using real figures.",
        backstory=(
            "You are an equity analyst with 10 years' experience covering technology "
            "companies. You never guess numbers: every figure you quote comes from a tool "
            "result, and you note the source. You explain what a ratio MEANS, not just its value."
        ),
        tools=_pick(tools_by_name, TOOLS_FOR["financial_analyst"]),
        llm=llm, **COMMON,
    )

    risk_assessor = Agent(
        role="Risk Assessor",
        goal="Measure and explain the downside risks of holding the stock, especially around earnings.",
        backstory=(
            "You are a market-risk specialist. You think about what could go wrong. "
            "You translate volatility, drawdown and Value-at-Risk into plain language "
            "(e.g. 'on a bad day, the stock has fallen more than 4%'). You are sceptical "
            "and balanced, never alarmist."
        ),
        tools=_pick(tools_by_name, TOOLS_FOR["risk_assessor"]),
        llm=llm, **COMMON,
    )

    news_researcher = Agent(
        role="News Researcher",
        goal="Find and summarise the recent news that matters for the stock, with links.",
        backstory=(
            "You are a financial journalist. You separate signal from noise, group "
            "headlines into themes, and always keep the link to each article so readers "
            "can check it."
        ),
        tools=_pick(tools_by_name, TOOLS_FOR["news_researcher"]),
        llm=llm, **COMMON,
    )

    compliance_checker = Agent(
        role="Compliance Checker and Critic",
        goal="Make sure the research note is fair, balanced, properly cited and safe to publish.",
        backstory=(
            "You work in a compliance team. You ALWAYS run the check_compliance tool on the "
            "full draft, then add your own judgement: Is every number cited? Are risks given "
            "fair weight? Does the note answer the original question? You give specific, "
            "actionable feedback."
        ),
        tools=_pick(tools_by_name, TOOLS_FOR["compliance_checker"]),
        llm=llm, **COMMON,
    )

    coordinator = Agent(
        role="Research Coordinator",
        goal="Combine the specialists' findings into one clear, cited research note that answers the user's question.",
        backstory=(
            "You are the head of research. You don't fetch data yourself - you trust your "
            "specialists' structured findings, resolve any contradictions, and write for a "
            "busy reader. You keep every citation and you never add numbers that aren't in "
            "the findings."
        ),
        tools=[],
        llm=llm, **COMMON,
    )

    return {
        "financial_analyst": financial_analyst,
        "risk_assessor": risk_assessor,
        "news_researcher": news_researcher,
        "compliance_checker": compliance_checker,
        "coordinator": coordinator,
    }
