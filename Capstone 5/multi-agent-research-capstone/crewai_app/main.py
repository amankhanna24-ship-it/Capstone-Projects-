"""
main.py - runs the whole CrewAI multi-agent system from start to finish.

HOW TO RUN (the MCP server must already be running):
    python -m crewai_app.main "Brief me on NVDA earnings risk"
    python -m crewai_app.main "What's the latest news on Microsoft?"

WHAT HAPPENS, STEP BY STEP
--------------------------
  1. PLAN      The dispatcher reads the question and picks specialists.
  2. CONNECT   We connect to our MCP server and load its tools.
  3. RESEARCH  Specialists use their tools and fill in SpecialistFinding forms.
               The Coordinator turns those into a draft note.
  4. CRITIQUE  The Compliance Checker reviews the draft.
  5. REFINE    If there are problems, the Coordinator fixes them. Repeat 4-5.
  6. GATE      One last rule-based compliance check (no LLM involved).
  7. SAVE      The note (.md) and a full audit trail (_trace.json) go to outputs/.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime

# HEARTBEAT: print one line for every web request (calls to Gemini AND to our MCP server).
# Without this, a slow model or a rate-limit retry looks exactly like a frozen program.
#   ... "POST .../models/gemini-...:generateContent "HTTP/1.1 200 OK""  -> Gemini answered
#   ... "HTTP/1.1 429 Too Many Requests"                                -> free-tier limit; it will wait and retry
#   ... "POST http://localhost:8000/mcp "HTTP/1.1 200 OK""              -> an agent used a tool
logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logging.getLogger("httpx").setLevel(logging.INFO)

from crewai import Crew, Process
from crewai_tools import MCPServerAdapter

from crewai_app.agents import build_agents
from crewai_app.coordinator import plan_research
from crewai_app.tasks import critique_task, draft_task, refine_task, specialist_task
from shared.config import MAX_REFINE_ROUNDS, MCP_SERVER_URL, OUTPUT_DIR
from shared.messages import CritiqueResult


def banner(text: str) -> None:
    print("\n" + "=" * 70 + f"\n  {text}\n" + "=" * 70)


def clean_markdown(text: str) -> str:
    """LLMs sometimes wrap their answer in ```markdown ... ``` - remove that."""
    text = text.strip()
    text = re.sub(r"^```(?:markdown|md)?\s*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)
    return text.strip()


def final_compliance_gate(tools_by_name: dict, note: str) -> dict:
    """Call the MCP check_compliance tool directly - no LLM, so the result can be trusted."""
    raw = tools_by_name["check_compliance"].run(text=note)
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"passed": "unknown", "raw": str(raw)}


def run(query: str, ticker: str | None = None) -> tuple[str, dict]:
    trace: dict = {"query": query, "started": datetime.now().isoformat(timespec="seconds")}

    # ---- 1. PLAN ---------------------------------------------------------
    banner("1. COORDINATOR: planning the research")
    plan = plan_research(query, ticker)
    trace["dispatch_plan"] = plan.model_dump()
    print(f"Ticker: {plan.ticker}\nSpecialists: {plan.specialists}\nWhy: {plan.reasoning}")

    # ---- 2. CONNECT to the MCP server -----------------------------------
    banner(f"2. Connecting to MCP server at {MCP_SERVER_URL}")
    server_params = {"url": MCP_SERVER_URL, "transport": "streamable-http"}
    with MCPServerAdapter(server_params, connect_timeout=60) as mcp_tools:
        tools_by_name = {tool.name: tool for tool in mcp_tools}
        print(f"Loaded tools: {sorted(tools_by_name)}")
        agents = build_agents(tools_by_name)

        # ---- 3. RESEARCH --------------------------------------------------
        banner("3. RESEARCH: specialists gather findings, Coordinator drafts")
        researchers = [s for s in plan.specialists if s != "compliance_checker"]
        s_tasks = [specialist_task(name, agents[name], plan) for name in researchers]
        d_task = draft_task(agents["coordinator"], s_tasks, plan)

        research_crew = Crew(
            agents=[agents[n] for n in researchers] + [agents["coordinator"]],
            tasks=s_tasks + [d_task],
            process=Process.sequential,
            verbose=True,
        )
        research_result = research_crew.kickoff()

        findings = []
        for name, task_output in zip(researchers, research_result.tasks_output):
            structured = task_output.pydantic.model_dump() if task_output.pydantic else {"raw": task_output.raw}
            findings.append({"specialist": name, "finding": structured})
        trace["specialist_findings"] = findings

        draft = clean_markdown(research_result.raw)
        trace["rounds"] = [{"round": 0, "type": "draft", "text": draft}]

        # ---- 4 & 5. CRITIQUE -> REFINE loop ------------------------------
        for round_no in range(1, MAX_REFINE_ROUNDS + 1):
            banner(f"4. CRITIQUE round {round_no}: Compliance Checker reviews the draft")
            critique_crew = Crew(
                agents=[agents["compliance_checker"]],
                tasks=[critique_task(agents["compliance_checker"], draft, plan)],
                verbose=True,
            )
            critique_output = critique_crew.kickoff()
            critique = critique_output.pydantic or CritiqueResult(
                passed=False, blocking_issues=["Critic did not return a structured result."],
                rule_check_output=critique_output.raw[:500])
            trace["rounds"].append({"round": round_no, "type": "critique", **critique.model_dump()})
            print(f"Passed: {critique.passed} | Issues: {critique.blocking_issues}")

            if critique.passed:
                print("Critique passed - no more refinement needed.")
                break

            banner(f"5. REFINE round {round_no}: Coordinator fixes the issues")
            refine_crew = Crew(
                agents=[agents["coordinator"]],
                tasks=[refine_task(agents["coordinator"], draft, critique)],
                verbose=True,
            )
            draft = clean_markdown(refine_crew.kickoff().raw)
            trace["rounds"].append({"round": round_no, "type": "refined_draft", "text": draft})

        # ---- 6. FINAL GATE -----------------------------------------------
        banner("6. FINAL GATE: rule-based compliance check (no LLM)")
        gate = final_compliance_gate(tools_by_name, draft)
        trace["final_compliance_gate"] = gate
        print(json.dumps(gate, indent=2))

    status = "PASSED" if gate.get("passed") is True else "NEEDS HUMAN REVIEW"
    final_note = f"{draft}\n\n> **Automated compliance gate:** {status}\n"
    trace["finished"] = datetime.now().isoformat(timespec="seconds")
    return final_note, trace


def save(note: str, trace: dict, ticker: str) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    note_path = OUTPUT_DIR / f"crewai_{ticker}_{stamp}.md"
    trace_path = OUTPUT_DIR / f"crewai_{ticker}_{stamp}_trace.json"
    note_path.write_text(note, encoding="utf-8")
    trace_path.write_text(json.dumps(trace, indent=2, default=str), encoding="utf-8")
    banner("7. SAVED")
    print(f"Research note : {note_path}\nAudit trail   : {trace_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-agent investment research (CrewAI)")
    parser.add_argument("query", nargs="?", default="Brief me on NVDA earnings risk")
    parser.add_argument("--ticker", help="Override the ticker found in the question")
    args = parser.parse_args()

    note, trace = run(args.query, args.ticker)
    print("\n" + note)
    save(note, trace, trace["dispatch_plan"]["ticker"])
