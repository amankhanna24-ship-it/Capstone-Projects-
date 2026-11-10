"""
agent.py - the SAME multi-agent system, built with Google's Agent Development Kit (ADK).

WHY BUILD IT TWICE?
-------------------
The capstone asks for a code-first CrewAI OR Google ADK version. We include both
so you can compare two styles - a strong talking point in your write-up:

  CrewAI version  : a Python rule-based DISPATCHER picks the specialists.
                    Predictable and cheap, but only as smart as its keyword list.
  ADK version     : the Coordinator is an LLM. It reads the question and DECIDES
                    which specialists to call (each specialist is a "tool" to it).
                    More flexible, but less predictable and uses more tokens.

Both use the SAME MCP server. That's the payoff of MCP: tools written once,
used by any framework.

HOW TO RUN
----------
    cd adk_app
    adk web                 # opens a chat UI in your browser at http://localhost:8000 ...
                            # ... BUT our MCP server already uses 8000, so use:
    adk web --port 8080
Then pick "research_coordinator" and type: Brief me on NVDA earnings risk

ADK RULE: the folder must contain __init__.py and agent.py, and agent.py must
define a variable called `root_agent`. That's how `adk web` finds your agent.

THE SHAPE OF THIS SYSTEM
------------------------
    root_agent (SequentialAgent: runs its children in order)
    |-- research_coordinator (LlmAgent)       -> RESEARCH: calls specialists, writes draft
    |     |-- financial_analyst  (as a tool)
    |     |-- risk_assessor      (as a tool)
    |     |-- news_researcher    (as a tool)
    |-- critique_refine_loop (LoopAgent: repeats its children)
          |-- compliance_critic (LlmAgent)    -> CRITIQUE (calls exit_loop when happy)
          |-- refiner           (LlmAgent)    -> REFINE
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# Let this file import from the project's "shared" folder
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent  # noqa: E402
from google.adk.agents.callback_context import CallbackContext  # noqa: E402
from google.adk.tools.agent_tool import AgentTool  # noqa: E402
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams  # noqa: E402
from google.adk.tools.tool_context import ToolContext  # noqa: E402
from google.genai import types  # noqa: E402

from shared.config import ADK_MODEL, MAX_REFINE_ROUNDS, MCP_SERVER_URL, OUTPUT_DIR  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: connect to our MCP server, exposing ONLY the named tools
# ---------------------------------------------------------------------------
def mcp_tools(*tool_names: str) -> McpToolset:
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=MCP_SERVER_URL),
        tool_filter=list(tool_names),   # least privilege: each agent sees only its tools
    )


FINDING_FORMAT = (
    "Reply in this exact structure (it mirrors the SpecialistFinding model in shared/messages.py):\n"
    "HEADLINE: one sentence\n"
    "KEY POINTS: 3-6 bullets, each with a figure\n"
    "RISKS/CAVEATS: bullets\n"
    "CONFIDENCE: low | medium | high\n"
    "DATA MODE: live | sample | mixed\n"
    "SOURCES: one line per source as 'title - url', copied from the tool results\n"
    "Only use figures returned by your tools."
)

# ---------------------------------------------------------------------------
# The four specialists
# ---------------------------------------------------------------------------
financial_analyst = LlmAgent(
    name="financial_analyst",
    model=ADK_MODEL,
    description="Analyses growth, margins, valuation and earnings expectations for a ticker.",
    instruction=(
        "You are an experienced equity analyst. For the ticker you are given, call "
        "get_company_snapshot, get_financial_metrics and get_earnings_info. Explain what "
        "the numbers mean in plain English.\n" + FINDING_FORMAT
    ),
    tools=[mcp_tools("get_company_snapshot", "get_financial_metrics", "get_earnings_info")],
)

risk_assessor = LlmAgent(
    name="risk_assessor",
    model=ADK_MODEL,
    description="Measures downside risk: volatility, drawdown, Value-at-Risk, beta and earnings-event risk.",
    instruction=(
        "You are a market-risk specialist. Call get_price_risk_metrics (period '1y') and "
        "get_earnings_info. Translate each risk figure into plain words, and explain how "
        "risk changes around an earnings release. Be balanced, not alarmist.\n" + FINDING_FORMAT
    ),
    tools=[mcp_tools("get_price_risk_metrics", "get_earnings_info", "get_financial_metrics")],
)

news_researcher = LlmAgent(
    name="news_researcher",
    model=ADK_MODEL,
    description="Finds and summarises recent news about a ticker, grouped into themes, with links.",
    instruction=(
        "You are a financial journalist. Call get_recent_news (limit 8). Group headlines "
        "into 2-4 themes, label each positive/negative/mixed, and keep every URL.\n" + FINDING_FORMAT
    ),
    tools=[mcp_tools("get_recent_news", "get_company_snapshot")],
)

# ---------------------------------------------------------------------------
# The Coordinator: decides which specialists to call, then writes the draft
# ---------------------------------------------------------------------------
research_coordinator = LlmAgent(
    name="research_coordinator",
    model=ADK_MODEL,
    description="Plans the research, dispatches specialists and writes the draft note.",
    instruction=(
        "You are the head of an investment research team.\n"
        "STEP 1 - PLAN: Identify the ticker in the user's question. Decide which specialists "
        "are needed: financial_analyst (fundamentals, earnings, valuation), risk_assessor "
        "(volatility, downside, event risk), news_researcher (recent events, sentiment). "
        "For broad requests such as 'brief me' use all three. Start your work by stating "
        "your plan in one line: 'PLAN: ticker=..., specialists=[...], because ...'.\n"
        "STEP 2 - DISPATCH: Call each chosen specialist tool, passing the ticker and the question.\n"
        "STEP 3 - AGGREGATE: Write ONE research note in Markdown with these sections: "
        "'# Research Note: TICKER - title', a line stating the data mode, '## Bottom line' "
        "(end with a neutral stance Positive/Neutral/Cautious), '## Financial picture', "
        "'## Earnings outlook', '## Risk assessment', '## News and sentiment', "
        "'## Key risks to watch', '## Sources' as a numbered list [1] title - url, and finish "
        "with: 'Disclaimer: This note is for educational purposes only and is not investment advice.'\n"
        "Rules: put a citation like [1] after every figure; use only figures from the "
        "specialists; if any used sample data say 'sample data' plainly; British English; "
        "cautious wording, never promise returns. Output only the note after your PLAN line."
    ),
    tools=[AgentTool(agent=financial_analyst),
           AgentTool(agent=risk_assessor),
           AgentTool(agent=news_researcher)],
    output_key="draft_brief",   # saves the answer into shared "state" for the next agents
)


# ---------------------------------------------------------------------------
# Critique -> Refine loop
# ---------------------------------------------------------------------------
def exit_loop(tool_context: ToolContext) -> dict:
    """Call this ONLY when the draft has passed compliance and needs no more changes."""
    tool_context.actions.escalate = True   # tells the LoopAgent to stop
    return {"status": "approved"}


compliance_critic = LlmAgent(
    name="compliance_critic",
    model=ADK_MODEL,
    description="Reviews the draft for compliance, citations, balance and clarity.",
    instruction=(
        "You are a compliance reviewer. Here is the current draft:\n"
        "=== DRAFT ===\n{draft_brief}\n=== END ===\n\n"
        "1. Call check_compliance with the COMPLETE draft text (excluding any PLAN line).\n"
        "2. Add your own review: every figure cited? risks fairly weighted? question answered?\n"
        "3. If the tool shows passed=true AND you found no serious problems, call exit_loop "
        "and reply 'APPROVED'.\n"
        "Otherwise reply with 'BLOCKING ISSUES:' and 'SUGGESTIONS:' as bullet lists. Do not rewrite the note."
    ),
    tools=[mcp_tools("check_compliance"), exit_loop],
    output_key="critique",
)

refiner = LlmAgent(
    name="refiner",
    model=ADK_MODEL,
    description="Rewrites the draft to fix every issue raised by the compliance critic.",
    instruction=(
        "Rewrite the research note to fix every blocking issue and apply sensible suggestions. "
        "Keep the same sections and all citations. Do not add new figures. Output ONLY the full "
        "revised note (no PLAN line, no commentary).\n\n"
        "=== CURRENT DRAFT ===\n{draft_brief}\n=== END ===\n\n"
        "=== CRITIQUE ===\n{critique}\n=== END ==="
    ),
    output_key="draft_brief",   # overwrite the draft with the improved version
)

critique_refine_loop = LoopAgent(
    name="critique_refine_loop",
    sub_agents=[compliance_critic, refiner],
    max_iterations=MAX_REFINE_ROUNDS,
)


# ---------------------------------------------------------------------------
# Publish: after everything finishes, show the final note and save it to outputs/
# (a "callback" is a plain Python function ADK runs at a set moment - no LLM needed)
# ---------------------------------------------------------------------------
def publish_final_note(callback_context: CallbackContext) -> types.Content:
    note = str(callback_context.state.get("draft_brief", "")).strip()
    if note.upper().startswith("PLAN:"):
        note = note.split("\n", 1)[-1].strip()
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = OUTPUT_DIR / f"adk_note_{stamp}.md"
    path.write_text(note, encoding="utf-8")
    return types.Content(role="model", parts=[types.Part(
        text=f"{note}\n\n---\n*Final note saved to `outputs/{path.name}`.*")])


root_agent = SequentialAgent(
    name="research_pipeline",
    description="Research -> Critique -> Refine pipeline for investment research notes.",
    sub_agents=[research_coordinator, critique_refine_loop],
    after_agent_callback=publish_final_note,
)
