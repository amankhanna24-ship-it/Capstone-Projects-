"""
tasks.py - the work orders handed to each agent.

WHAT IS A CREWAI TASK?
----------------------
If an agent is a person, a Task is the job ticket you give them:
  - description      : what to do (be specific!)
  - expected_output  : what "done" looks like
  - agent            : who does it
  - context          : earlier tasks whose results this task can read
  - output_pydantic  : the "form" (from shared/messages.py) the answer must fit

THE RESEARCH -> CRITIQUE -> REFINE PATTERN
------------------------------------------
  Research : specialists gather facts, Coordinator writes a DRAFT
  Critique : Compliance Checker reviews the draft and lists problems
  Refine   : Coordinator fixes those problems
  ...repeat until the critique passes (or we hit a maximum number of rounds)

It's how a human team works: write, get reviewed, improve. The output gets
better without a human having to spot every mistake.
"""

from __future__ import annotations

from crewai import Agent, Task

from shared.messages import CritiqueResult, DispatchPlan, SpecialistFinding

NOTE_TEMPLATE = """
# Research Note: <TICKER> - <short title answering the question>
*Prepared by a multi-agent research system on <date>. Data mode: <live / sample / mixed>.*

## Bottom line
3-4 sentences that directly answer the user's question. End with a neutral
stance: Positive / Neutral / Cautious, and one sentence on why.

## Financial picture
## Earnings outlook
## Risk assessment
## News and sentiment
(Leave out any section whose specialist was not dispatched.)

## Key risks to watch
3-5 bullets.

## Sources
[1] Title - URL
[2] Title - URL

---
*Disclaimer: This note is for educational purposes only and is not investment advice.*
"""

SPECIALIST_INSTRUCTIONS = {
    "financial_analyst": (
        "Analyse the financial health of {ticker}. Use get_company_snapshot, "
        "get_financial_metrics and get_earnings_info. Cover growth, margins, valuation "
        "(P/E vs forward P/E) and what analysts expect for the next earnings."
    ),
    "risk_assessor": (
        "Assess the downside risk of holding {ticker}, especially around the next earnings "
        "release. Use get_price_risk_metrics (period '1y') and get_earnings_info. Explain "
        "volatility, maximum drawdown, daily 95% VaR and beta in plain words. If valuation "
        "is high, say how that raises the cost of disappointing results."
    ),
    "news_researcher": (
        "Find recent news about {ticker} with get_recent_news (limit 8). Group headlines "
        "into 2-4 themes, say whether each theme is positive, negative or mixed, and keep "
        "the URL of every article you mention."
    ),
}


def specialist_task(name: str, agent: Agent, plan: DispatchPlan) -> Task:
    instructions = SPECIALIST_INSTRUCTIONS[name].format(ticker=plan.ticker)
    return Task(
        description=(
            f"User's research question: '{plan.query}'.\n\n{instructions}\n\n"
            "Rules: only use figures that came from your tools. Copy each tool's "
            "'source' (title and url) into your sources list. If a tool returned "
            "data_mode 'sample', set data_mode to 'sample' and say so in a caveat."
        ),
        expected_output="A SpecialistFinding with a headline, 3-6 key points with figures, caveats and sources.",
        agent=agent,
        output_pydantic=SpecialistFinding,
    )


def draft_task(coordinator: Agent, specialist_tasks: list[Task], plan: DispatchPlan) -> Task:
    return Task(
        description=(
            f"User's research question: '{plan.query}' (ticker {plan.ticker}).\n\n"
            "You have structured findings from your specialists (in your context). "
            "Combine them into ONE research note in Markdown using this layout:\n"
            f"{NOTE_TEMPLATE}\n"
            "Rules:\n"
            "- Put a numbered citation like [1] after every figure, and list every source "
            "under '## Sources'.\n"
            "- Use only figures that appear in the findings. Do not invent numbers.\n"
            "- If any finding used sample data, say 'sample data' plainly near the top.\n"
            "- Write for a busy reader: short paragraphs, plain words, British English.\n"
            "- Use cautious wording ('may', 'suggests') - never promise returns."
        ),
        expected_output="The full research note in Markdown, and nothing else.",
        agent=coordinator,
        context=specialist_tasks,
    )


def critique_task(checker: Agent, draft: str, plan: DispatchPlan) -> Task:
    return Task(
        description=(
            f"Review this draft research note answering: '{plan.query}'.\n\n"
            "STEP 1 - Call the check_compliance tool with the COMPLETE draft text.\n"
            "STEP 2 - Add your own review: Is every figure cited? Are risks given fair "
            "weight against positives? Does it answer the user's question directly? Is it "
            "clear for a non-expert?\n"
            "Set passed=True ONLY if the tool reported no BLOCKER issues AND you found no "
            "serious problems.\n\n"
            f"=== DRAFT START ===\n{draft}\n=== DRAFT END ==="
        ),
        expected_output="A CritiqueResult listing blocking issues and specific improvement suggestions.",
        agent=checker,
        output_pydantic=CritiqueResult,
    )


def refine_task(coordinator: Agent, draft: str, critique: CritiqueResult) -> Task:
    issues = "\n".join(f"- {i}" for i in critique.blocking_issues) or "- (none)"
    suggestions = "\n".join(f"- {s}" for s in critique.improvement_suggestions) or "- (none)"
    return Task(
        description=(
            "The Compliance Checker reviewed your draft. Fix EVERY blocking issue and apply "
            "the suggestions where sensible. Keep all existing citations and the same "
            "section layout. Do not add new figures.\n\n"
            f"Blocking issues:\n{issues}\n\nSuggestions:\n{suggestions}\n\n"
            f"=== CURRENT DRAFT ===\n{draft}\n=== END ==="
        ),
        expected_output="The complete revised research note in Markdown, and nothing else.",
        agent=coordinator,
    )
