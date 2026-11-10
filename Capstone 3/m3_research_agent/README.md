# M3 — Autonomous Researcher-and-Summarizer Agent (ReAct, built from scratch)

## The problem
Research is search-heavy and repetitive: open ten tabs, skim, copy, paste, summarise. A single LLM call can't do it, because the work is a loop — search, read, judge, search again, then write up with citations.

## What this agent does
Given a research question, the agent plans a strategy, then runs a **Thought → Action → Observation** loop over a set of tools until its notes cover the question or a budget runs out. A separate Summarizer step turns the notes into a cited report. Each finished task is stored in Upstash Redis so later, related questions start with what was already learned.

```
                ┌──────────── long-term memory (Upstash Redis) ────────────┐
                │ recall similar past research        save finished report │
                ▼                                                          │
question ─► ReAct loop ──► Thought ──► Action ──► tool ──► Observation ─┐  │
                ▲                                                       │  │
                └──────── short-term buffer (trimmed to fit) ◄──────────┘  │
                                   │ save_note                             │
                                   ▼                                       │
                        working memory (notes + source ids)                │
                                   │ finish / budget spent                 │
                                   ▼                                       │
                        Summarizer ─► citation check ─► report + Sources ──┘
```

## How each requirement is met

| Requirement | Where | How |
|---|---|---|
| ReAct loop from scratch | `m3_react_agent.py` → `ResearchAgent.run`, `parse_reply` | Raw SDK calls; the model writes `Thought/Action/Action Input` as text, regex parses it, Python runs the tool. `stop=["Observation:"]` prevents invented tool results. No LangChain agent classes. |
| Web search | `tools.web_search` | Tavily (relevance scores) with DuckDuckGo fallback |
| Page fetch | `tools.fetch_html`, `tools.fetch_page` | `requests` with timeout; content-type check; arXiv PDF → abstract page |
| Content extraction | `tools.extract_content` | BeautifulSoup strips scripts/nav/footer, prefers `<article>`/`<main>`, keeps paragraphs most relevant to a `focus` string |
| Citation tracker | `tools.CitationTracker` | One number per unique URL; strips citations that point to unknown sources; Sources list built by code so URLs can't be hallucinated |
| Short-term memory | `memory.ShortTermMemory` | Conversation buffer with a token budget; oldest observations are compressed first, the task and recent turns are kept |
| Working memory | `memory.WorkingMemory` + `save_note` tool | Agent records findings with source ids; Summarizer writes only from these |
| Long-term memory | `memory.LongTermMemory` | Upstash Redis hash `m3:research`; keyword-overlap recall injected into the first prompt |
| Self-correction | `tools._weak_results_warning`, format/duplicate checks | `QUALITY WARNING` on thin results, `FORMAT ERROR` on malformed replies, refusal of repeated searches, `finish` refused with zero notes |
| Bounded autonomy | `ResearchAgent.__init__` / top of loop | `max_iterations`, `max_tokens` (15% reserved for summary), `max_seconds`; stop reason recorded |
| Structured output | `ResearchAgent._summarise` | Summary, Key Findings, Comparison table, Limitations, inline `[n]` citations, Sources |
| Run trace | `Trace` → `traces/*.md` and `.json` | Every step with timings plus a statistics table |

## Running it
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add OpenAI or Anthropic key, Tavily key, Upstash URL + token
python test_offline.py        # no keys needed; checks the loop logic
python m3_react_agent.py "Compare Raptor RAG vs HyDE"
python m3_react_agent.py --list-memory
```
Flags: `--max-iterations`, `--max-tokens`, `--max-seconds`, `--provider openai|anthropic`.

## How it ties to the module
- **Agents are loops, not calls.** The earlier modules used one-shot prompts and RAG pipelines with a fixed sequence of steps. Here the model decides the next step at run time, based on what it has just seen.
- **Tools are the boundary between reasoning and acting.** The model only produces text; code decides what actually runs. That's where validation, budgets and safety live.
- **Memory has layers.** The context window is finite (short-term), a task needs a scratchpad (working), and useful knowledge should outlast the process (long-term).
- **Autonomy needs limits.** Iteration, token and time budgets make the agent's cost and run time predictable — the same thinking as guardrails on any production AI system.
- **From scratch vs framework.** `bonus_langgraph_agent.py` builds the same agent with LangGraph's prebuilt ReAct agent in about 70 lines. Building it by hand first shows exactly what the framework is doing underneath: the loop, the parsing and the stop conditions.

## Known limitations
- Recall uses keyword overlap, not embeddings, so differently worded questions on the same topic may be missed.
- Pages that need JavaScript return little text; the agent is warned and moves on.
- Token counting in the buffer is an estimate (≈4 characters per token); the overall budget uses the provider's real usage numbers.
