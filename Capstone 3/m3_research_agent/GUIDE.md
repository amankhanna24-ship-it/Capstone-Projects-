# Step-by-step guide: building and running the M3 research agent in VS Code

This guide assumes a Mac, VS Code and Python 3 already installed. Every command goes in the VS Code terminal (**View → Terminal**, or `` Ctrl+` ``).

---

## Part 1 — The idea in plain English

A normal chatbot call is one question in, one answer out. Research doesn't work like that. You search, skim a result, realise you need something else, search again, read a page properly, jot down a note, and only then write it up.

A **ReAct agent** gives the model that same loop:

```
Thought:      "I need to know what RAPTOR is first."
Action:       web_search {"query": "RAPTOR RAG recursive tree"}
Observation:  (our Python code runs the search and pastes the results back)
Thought:      "Result [2] is the original paper. I'll read it."
Action:       fetch_page {"url": "https://arxiv.org/abs/..."}
Observation:  (cleaned page text)
...repeat until it calls finish, or a budget runs out...
```

The model never touches the internet itself. It only *writes text saying which tool it wants*. Your code reads that text, runs the tool, and feeds the result back. That's the whole trick, and it's what "from scratch" means in the assignment.

**What each file does**

| File | Its job | Analogy |
|---|---|---|
| `llm.py` | Sends text to OpenAI or Claude, returns the reply | The phone line to the model |
| `tools.py` | Search, fetch page, clean HTML, number the sources | The agent's hands |
| `memory.py` | Short-term buffer, notebook, Upstash Redis | Desk, notepad and filing cabinet |
| `m3_react_agent.py` | The loop, the budgets, the summariser, the trace | The brain's routine |
| `test_offline.py` | Runs everything with a fake model, no keys | A rehearsal |
| `bonus_langgraph_agent.py` | Same agent in LangGraph | For comparison |

---

## Part 2 — Set up the project (15 minutes)

### Step 1. Put the folder somewhere sensible
Unzip `m3_research_agent.zip` into, say, `~/Projects/`. In VS Code: **File → Open Folder…** and pick `m3_research_agent`.

### Step 2. Create a virtual environment
A virtual environment is a private box of Python packages just for this project, so it can't clash with your other projects.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Your terminal prompt should now start with `(.venv)`. If you ever open a new terminal, run the `source` line again.

Then tell VS Code to use it: `Cmd+Shift+P` → **Python: Select Interpreter** → pick the one with `.venv` in its path.

### Step 3. Install the packages
```bash
pip install -r requirements.txt
```
If anything fails to install on Python 3.14, the quickest fix is a 3.12 environment: `brew install python@3.12`, then `python3.12 -m venv .venv` and repeat.

### Step 4. Prove the plumbing works (no keys needed)
```bash
python test_offline.py
```
You should see seven ticks and `ALL TESTS PASSED`. Scroll up and you'll see a full Thought → Action → Observation run with a scripted fake model, including a deliberate format mistake and a repeated search that the agent gets told off for. Read it; it's the best explanation of the loop you'll get.

---

## Part 3 — Get your three keys (10 minutes)

### Step 5. Make your `.env` file
```bash
cp .env.example .env
```
Open `.env` in VS Code. You'll fill in three things. Never submit this file — it holds your passwords.

### Step 6. Model key
- **OpenAI**: platform.openai.com → API keys → create. Paste into `OPENAI_API_KEY`.
- **Or Claude**: console.anthropic.com → API keys. Paste into `ANTHROPIC_API_KEY` and set `LLM_PROVIDER=anthropic`.

If you get a "model not found" error, change `OPENAI_MODEL` / `ANTHROPIC_MODEL` to a model your account lists. Nothing else needs to change.

### Step 7. Search key (Tavily)
Sign up at tavily.com (free tier), copy the key into `TAVILY_API_KEY`. Tavily is built for agents and returns a relevance score per result, which the agent uses to spot weak searches. If you leave it blank the code falls back to DuckDuckGo, which needs no key but is less reliable.

### Step 8. Upstash Redis (long-term memory)
1. console.upstash.com → sign up → **Create Database** → Redis, free plan, any region close to you (Mumbai is fine).
2. Open the database, scroll to the **REST API** section.
3. Copy `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` into `.env`.

Without these the agent still runs but saves memory to `local_memory.json` and prints a warning. For the submission you want Upstash.

---

## Part 4 — Run it for real

### Step 9. The assignment question
```bash
python m3_react_agent.py "Compare Raptor RAG vs HyDE"
```
It takes one to three minutes. Watch the colours: cyan is the model thinking, yellow is the tool it picked, grey is what came back, green is the final cited summary.

When it ends you'll see `📄 Trace saved to traces/....md`. **That markdown file is your "sample run trace" deliverable.** There's a `.json` twin with the same data in machine-readable form.

### Step 10. Prove long-term memory works
Run a related question:
```bash
python m3_react_agent.py "How does RAPTOR handle long documents?"
```
Near the top of the output you should see `SYSTEM: Recalled 1 past research item(s) from upstash`. That's the agent pulling last run's findings out of Redis. Then:
```bash
python m3_react_agent.py --list-memory
```
You can also see the data in the Upstash console → **Data Browser** → key `m3:research`. A screenshot of that is good evidence for your submission.

### Step 11. Prove the budgets work
```bash
python m3_react_agent.py "Compare Raptor RAG vs HyDE" --max-iterations 3
python m3_react_agent.py "Compare Raptor RAG vs HyDE" --max-seconds 20
```
The stop reason in the trace's statistics table will say which budget was hit, and you still get a summary from whatever it found. That's "bounded autonomy".

### Step 12 (optional). The LangGraph comparison
```bash
python bonus_langgraph_agent.py "Compare Raptor RAG vs HyDE"
```

---

## Part 5 — Understand the code (read in this order)

1. **`m3_react_agent.py` → `SYSTEM_PROMPT`.** This is the contract. It lists the tools and insists on the exact `Thought / Action / Action Input` format.
2. **`parse_reply()`.** Three regular expressions pull out the thought, the tool name and the JSON. If the model gets the format wrong, we don't crash; we send back a `FORMAT ERROR` observation and let it try again.
3. **`ResearchAgent.run()`.** The `for step in range(...)` loop is the ReAct loop. Note the budget checks at the top of each turn, and `stop=["Observation:"]` on the model call — that stops the model inventing its own tool results.
4. **The `if action == ...` block.** This is where text becomes action. `web_search` and `fetch_page` hit the web; `save_note` writes to working memory; `finish` ends the loop (but only if there's at least one note).
5. **`_summarise()`.** A second, separate model call — the "Summarizer". It only sees the notes, so it can't drift off into things it never researched. Afterwards the citation tracker deletes any `[n]` that doesn't match a real source, and the Sources list is built by code, not the model, so URLs can't be made up.
6. **`memory.py`.** `ShortTermMemory._trim()` shrinks old observations once the conversation passes ~6,000 tokens. `LongTermMemory.recall()` matches past questions by shared keywords.
7. **`tools.py` → `_weak_results_warning()`.** Three plain rules (too few results, low scores, keywords missing). When any trips, the observation carries a `QUALITY WARNING`, and the prompt tells the model to change tack. That's the self-correction.

---

## Part 6 — When things go wrong

| You see | What it means | Fix |
|---|---|---|
| `command not found: python` | Mac uses `python3` outside the venv | Activate the venv (Step 2) |
| `ModuleNotFoundError` | Packages installed in a different Python | Activate venv, re-run `pip install -r requirements.txt`, re-select interpreter |
| `AuthenticationError` / 401 | Key wrong or not loaded | Check `.env` is in the project folder and has no quotes or spaces round `=` |
| `model ... does not exist` | Model name not on your account | Change `OPENAI_MODEL` in `.env` |
| `UPSTASH... not set` warning | Redis keys missing | Step 8 |
| Lots of `FORMAT ERROR` | Small model struggling with the format | Use a stronger model, or lower `temperature` |
| Agent stops at max iterations with few notes | Budget too tight | `--max-iterations 15` |

---

## Part 7 — What to submit

- `m3_react_agent.py`, `tools.py`, `memory.py`, `llm.py`
- `requirements.txt`, `.env.example`, `README.md`
- `traces/<date>_compare_raptor_rag_vs_hyde.md` (your real run from Step 9)
- Optional: `test_offline.py`, `bonus_langgraph_agent.py`, screenshot of the Upstash Data Browser

**Do not submit** `.env`, `.venv/` or `local_memory.json`.
