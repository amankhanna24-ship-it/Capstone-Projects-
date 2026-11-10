"""
m3_react_agent.py - a Researcher-and-Summarizer agent built FROM SCRATCH.

No LangChain agents, no LangGraph, no "function calling" magic. Just:

    while not done:
        Thought  ->  the model writes its reasoning and picks an Action
        Action   ->  OUR code parses it and runs the matching Python tool
        Observation -> we paste the tool's result back into the conversation

That loop is ReAct (Reason + Act, Yao et al. 2022).

Run it:
    python m3_react_agent.py "Compare Raptor RAG vs HyDE"

Optional flags:
    --max-iterations 12   --max-tokens 80000   --max-seconds 240
    --provider openai|anthropic
    --list-memory          (show what is stored in long-term memory)
"""

import argparse
import json
import os
import re
import sys
import time

from dotenv import load_dotenv

from llm import LLM
from memory import LongTermMemory, ShortTermMemory, WorkingMemory
from tools import CitationTracker, fetch_page, web_search

load_dotenv()  # reads your .env file into environment variables


# ---------------------------------------------------------------------------
# The system prompt: this is the "contract" that teaches the model ReAct
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a careful research agent. You answer research questions by searching the web,
reading pages, and saving findings as notes. You work in a loop.

TOOLS
- web_search: search the web. Input: {"query": "..."}
- fetch_page: read a web page. Input: {"url": "https://...", "focus": "what you are looking for"}
- save_note: save ONE finding to your notebook. Input: {"note": "a specific fact", "source_ids": [1, 3]}
- finish: stop researching when your notes can answer the question. Input: {"reason": "..."}

FORMAT - every reply must be exactly this shape, nothing else:
Thought: <your reasoning about what you know and what to do next>
Action: <one tool name>
Action Input: <a JSON object on one line>

Then STOP. The system will reply with "Observation: ..." containing the tool result.
Never write an Observation yourself.

STRATEGY
1. Start with a short plan in your first Thought (which sub-questions you need to answer).
2. Search each concept separately when comparing things.
3. Prefer primary sources (papers, official docs) - fetch at least 2 pages, not only snippets.
4. After reading something useful, call save_note. Numbers in [ ] are source ids; cite the ones you used.
5. If an Observation says QUALITY WARNING or ERROR, change your approach (new keywords, different source).
6. Do not repeat a search you already ran.
7. Call finish once you have roughly 6-10 good notes that cover every part of the question.
"""

SUMMARY_PROMPT = """You are the Summarizer. Write the final research summary from the notes below.

Rules:
- Use ONLY the notes. Do not add facts that are not in them.
- Put inline citations like [1] or [2, 4] right after each claim, using the source numbers given.
- Use this markdown structure:
  ## Summary            (3-5 sentences answering the question directly)
  ## Key Findings       (bullet points)
  ## Comparison         (a markdown table if the question compares things; otherwise skip this section)
  ## Limitations        (1-3 bullets: what the research could not confirm)
- Do NOT write a Sources section - the system adds it automatically.
"""


# ---------------------------------------------------------------------------
# Parsing the model's reply
# ---------------------------------------------------------------------------
def parse_reply(text: str) -> tuple[str, str, dict] | str:
    """
    Pull out Thought / Action / Action Input.
    Returns (thought, action, args) on success, or an error message string.
    """
    thought = re.search(r"Thought:\s*(.*?)(?=\nAction:|\Z)", text, re.S)
    action = re.search(r"Action:\s*([A-Za-z_]+)", text)
    action_input = re.search(r"Action Input:\s*(\{.*\})", text, re.S)

    if not action:
        return "FORMAT ERROR: I could not find 'Action: <tool name>'. Reply using the exact Thought/Action/Action Input format."
    args = {}
    if action_input:
        try:
            args = json.loads(action_input.group(1))
        except json.JSONDecodeError:
            return "FORMAT ERROR: 'Action Input' is not valid JSON. Use double quotes, e.g. {\"query\": \"...\"}."
    elif action.group(1).lower() != "finish":
        return "FORMAT ERROR: missing 'Action Input: {...}' JSON line."
    return (thought.group(1).strip() if thought else ""), action.group(1).lower(), args


# ---------------------------------------------------------------------------
# A tiny trace recorder - this produces the "sample run trace" deliverable
# ---------------------------------------------------------------------------
class Trace:
    COLOURS = {"THOUGHT": "\033[36m", "ACTION": "\033[33m", "OBSERVATION": "\033[90m",
               "SYSTEM": "\033[35m", "FINAL": "\033[32m"}

    def __init__(self, question: str):
        self.question = question
        self.events: list[dict] = []
        self.started = time.time()

    def log(self, kind: str, text: str, step: int | None = None):
        self.events.append({"t": round(time.time() - self.started, 1), "step": step, "kind": kind, "text": text})
        colour = self.COLOURS.get(kind, "")
        shown = text if kind != "OBSERVATION" or len(text) < 700 else text[:700] + " …"
        label = f"[step {step}] {kind}" if step else kind
        print(f"{colour}{label}:\033[0m {shown}\n")

    def save(self, final_markdown: str, stats: dict) -> str:
        os.makedirs("traces", exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "_", self.question.lower()).strip("_")[:40]
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = f"traces/{stamp}_{slug}"

        with open(base + ".json", "w") as f:
            json.dump({"question": self.question, "stats": stats, "events": self.events,
                       "final_output": final_markdown}, f, indent=2)

        md = [f"# Run trace: {self.question}\n",
              "## Run statistics\n",
              "| Metric | Value |", "|---|---|"]
        md += [f"| {k} | {v} |" for k, v in stats.items()]
        md.append("\n## Reasoning loop (Thought → Action → Observation)\n")
        for e in self.events:
            head = f"**Step {e['step']} · {e['kind']}**" if e["step"] else f"**{e['kind']}**"
            body = e["text"] if e["kind"] != "OBSERVATION" or len(e["text"]) < 1500 else e["text"][:1500] + " …[shortened in trace]"
            md.append(f"{head} _(t={e['t']}s)_\n\n```\n{body}\n```\n")
        md.append("## Final output\n")
        md.append(final_markdown)
        with open(base + ".md", "w") as f:
            f.write("\n".join(md))
        return base + ".md"


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------
class ResearchAgent:
    def __init__(self, llm: LLM | None = None, max_iterations: int = 12,
                 max_tokens: int = 80_000, max_seconds: int = 240, long_term: LongTermMemory | None = None):
        self.llm = llm or LLM()
        # --- bounded autonomy: three independent budgets ---
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.max_seconds = max_seconds
        self.long_term = long_term or LongTermMemory()

    def run(self, question: str) -> dict:
        trace = Trace(question)
        tracker = CitationTracker()
        notes = WorkingMemory()
        stm = ShortTermMemory(max_context_tokens=6000)
        tokens_used = 0
        start = time.time()
        searches_done: set[str] = set()

        # ---- 1. Recall from long-term memory -------------------------------
        past = self.long_term.recall(question)
        memory_text = ""
        if past:
            memory_text = "\n\nRELEVANT PAST RESEARCH (from long-term memory - use it as a head start, but verify):\n"
            for p in past:
                memory_text += f"- ({p['timestamp']}) Q: {p['question']}\n  Summary: {p['summary'][:600]}\n"
            trace.log("SYSTEM", f"Recalled {len(past)} past research item(s) from {self.long_term.backend}: "
                                + "; ".join(p["question"] for p in past))
        else:
            trace.log("SYSTEM", f"No related past research in long-term memory ({self.long_term.backend}).")

        stm.add("user", f"Research question: {question}{memory_text}\n\nBegin.")

        # ---- 2. The ReAct loop -----------------------------------------------
        stop_reason = "max_iterations reached"
        step = 0
        for step in range(1, self.max_iterations + 1):
            # Check budgets BEFORE spending more
            elapsed = time.time() - start
            if elapsed > self.max_seconds:
                stop_reason = f"wall-clock budget spent ({elapsed:.0f}s > {self.max_seconds}s)"
                break
            if tokens_used > self.max_tokens * 0.85:   # keep 15% back for the summariser
                stop_reason = f"token budget nearly spent ({tokens_used} tokens)"
                break

            # Remind the agent of its budget and notebook on every turn
            status = (f"\n\n[Status: step {step}/{self.max_iterations}, {tokens_used}/{self.max_tokens} tokens, "
                      f"{elapsed:.0f}/{self.max_seconds}s, {len(notes.notes)} notes saved]")
            convo = [dict(m) for m in stm.messages]
            convo[-1]["content"] += status

            reply, used = self.llm.chat(SYSTEM_PROMPT, convo, max_tokens=700, stop=["Observation:"])
            tokens_used += used

            parsed = parse_reply(reply)
            stm.add("assistant", reply)

            if isinstance(parsed, str):            # model broke the format -> tell it, try again
                trace.log("SYSTEM", parsed, step)
                stm.add("user", f"Observation: {parsed}")
                continue

            thought, action, args = parsed
            trace.log("THOUGHT", thought, step)
            trace.log("ACTION", f"{action} {json.dumps(args)}", step)

            # ---- run the tool ----
            if action == "finish":
                if len(notes.notes) == 0:
                    observation = "You have no saved notes yet. Use save_note for your findings before finishing."
                else:
                    stop_reason = f"agent decided goal was met ({args.get('reason', 'no reason given')})"
                    break
            elif action == "web_search":
                q = args.get("query", "").strip().lower()
                if q in searches_done:
                    observation = "You already ran this exact search. QUALITY WARNING: try different keywords."
                else:
                    searches_done.add(q)
                    observation = web_search(args.get("query", ""), tracker)
            elif action == "fetch_page":
                observation = fetch_page(args.get("url", ""), tracker, focus=args.get("focus", question))
            elif action == "save_note":
                ids = [int(i) for i in args.get("source_ids", []) if str(i).isdigit()]
                unknown = [i for i in ids if i not in tracker.sources]
                observation = notes.save(args.get("note", ""), [i for i in ids if i in tracker.sources])
                if unknown:
                    observation += f" Warning: source ids {unknown} don't exist and were dropped."
            else:
                observation = f"ERROR: unknown tool '{action}'. Valid tools: web_search, fetch_page, save_note, finish."

            trace.log("OBSERVATION", observation, step)
            stm.add("user", f"Observation: {observation}")

        trace.log("SYSTEM", f"Loop stopped after {step} step(s): {stop_reason}")

        # ---- 3. Summarise (separate LLM call = the "Summarizer" role) ----------
        final_md, sum_tokens = self._summarise(question, notes, tracker)
        tokens_used += sum_tokens
        trace.log("FINAL", final_md)

        # ---- 4. Save to long-term memory ------------------------------------
        cited = tracker.cited_ids(final_md)
        mem_id = self.long_term.save_research(
            question, final_md.split("## Sources")[0],
            [tracker.sources[i]["url"] for i in cited if i in tracker.sources])
        trace.log("SYSTEM", f"Saved to long-term memory ({self.long_term.backend}) with id {mem_id}")

        stats = {
            "question": question,
            "model": f"{self.llm.provider}/{self.llm.model}",
            "steps_used": f"{step} / {self.max_iterations}",
            "tokens_used": f"{tokens_used} / {self.max_tokens}",
            "seconds": f"{time.time() - start:.0f} / {self.max_seconds}",
            "stop_reason": stop_reason,
            "notes_saved": len(notes.notes),
            "sources_seen": len(tracker.sources),
            "sources_cited": len(cited),
            "context_trims": stm.trim_events,
            "long_term_memory": self.long_term.backend,
        }
        trace_path = trace.save(final_md, stats)
        print(f"\n📄 Trace saved to {trace_path}")
        return {"summary": final_md, "stats": stats, "trace_path": trace_path}

    def _summarise(self, question: str, notes: WorkingMemory, tracker: CitationTracker) -> tuple[str, int]:
        if not notes.notes:
            # Fallback: the agent ran out of budget before saving notes. Use search snippets instead.
            material = "\n".join(f"- {s['snippet'][:400]} [{sid}]" for sid, s in tracker.sources.items() if s["snippet"])
            material = material or "(nothing was found)"
        else:
            material = notes.as_text()

        prompt = (f"Research question: {question}\n\nNOTES:\n{material}\n\n"
                  f"SOURCE LIST (for reference):\n{tracker.sources_markdown()}")
        body, used = self.llm.chat(SUMMARY_PROMPT, [{"role": "user", "content": prompt}], max_tokens=1500)

        # Citation tracker checks the summary: drop any [n] that doesn't exist.
        body, bad = tracker.remove_invalid_citations(body)
        cited = tracker.cited_ids(body)
        sources = "\n".join(f"{line}  " for line in tracker.sources_markdown(cited).splitlines())
        final = f"# {question}\n\n{body}\n\n## Sources\n{sources}"
        if bad:
            final += "\n\n_Note: removed invalid citation numbers: " + ", ".join(map(str, bad)) + "._"
        return final, used


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="ReAct research agent (from scratch)")
    parser.add_argument("question", nargs="?", default="Compare Raptor RAG vs HyDE")
    parser.add_argument("--max-iterations", type=int, default=12)
    parser.add_argument("--max-tokens", type=int, default=80_000)
    parser.add_argument("--max-seconds", type=int, default=240)
    parser.add_argument("--provider", choices=["openai", "anthropic"], default=None)
    parser.add_argument("--list-memory", action="store_true", help="show long-term memory and exit")
    args = parser.parse_args()

    if args.list_memory:
        ltm = LongTermMemory()
        topics = ltm.list_topics()
        print(f"{len(topics)} item(s) in long-term memory ({ltm.backend}):")
        for t in topics:
            print(f"  {t['timestamp']}  {t['question']}")
        return

    agent = ResearchAgent(llm=LLM(provider=args.provider), max_iterations=args.max_iterations,
                          max_tokens=args.max_tokens, max_seconds=args.max_seconds)
    agent.run(args.question)


if __name__ == "__main__":
    sys.exit(main())
