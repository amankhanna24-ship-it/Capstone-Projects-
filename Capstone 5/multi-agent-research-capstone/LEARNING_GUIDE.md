# Learning Guide: how this project works, in plain English

This guide is for you if you're still learning Python and agentic AI. It explains
**what** each piece does, **why** it's there and **how** to run it. Read it top to
bottom once, then use it as a reference.

---

## Part 1: The big picture in one minute

Imagine a small **investment research team** at a bank:

- The **head of research** gets a question from a client: *"Brief me on NVDA earnings risk."*
- They don't do it all themselves. They send it to:
  - a **financial analyst**, who looks at revenue, profit and valuation
  - a **risk analyst**, who asks how much the share price could fall
  - a **news researcher**, who checks what's in the headlines
- The head of research combines the three reports into one note.
- **Compliance** reads the note before it goes out. It checks that the note makes no
  promises, cites its sources and carries a disclaimer.
- If compliance finds problems, the note goes back for fixes. Then compliance checks
  it again.

**This project builds that team out of AI agents.** Every person above becomes an
agent. The tools they use (price data, news, a compliance rulebook) sit on a shared
**MCP server**.

---

## Part 2: The key ideas, one at a time

### 2.1 LLM
A **Large Language Model** (for example, Google Gemini or OpenAI's GPT) reads text
and writes text. On its own it can't look up today's share price. It only knows what
it learned during training.

### 2.2 Agent
An **agent** is an LLM that has been given:
- a **role** ("You are a risk analyst"),
- a **goal** ("Explain the downside risk"), and
- **tools** it can choose to use ("get_price_risk_metrics").

The LLM decides *which* tool to call and *when*, reads the result and continues. That
loop is what makes it "agentic": it acts, not just talks.

### 2.3 Tool
A **tool** is a normal Python function the agent is allowed to call, such as
`get_recent_news("NVDA")`. The agent reads the function's **docstring** (the text in
triple quotes) to understand what the tool does. So well-written docstrings make
smarter agents.

### 2.4 MCP (Model Context Protocol)
MCP is a **standard plug** for AI tools. Think of USB-C. Before USB-C, every phone had
its own charger. MCP does the same job for AI tools: write a tool once on an MCP
server, and *any* MCP-compatible agent can use it, whether that's CrewAI, Google ADK,
Flowise, n8n or Claude.

In this project:
- **MCP server** = `mcp_server/server.py`. It *offers* the tools.
- **MCP clients** = our agents. They *use* the tools.
- They talk over HTTP at `http://localhost:8000/mcp`.

### 2.5 FastMCP
FastMCP is a Python library that makes building an MCP server easy. You put
`@mcp.tool` above a function and it becomes an MCP tool:

```python
@mcp.tool
def get_recent_news(ticker: str, limit: int = 8) -> dict:
    """Get recent news headlines about the company..."""
    return data_sources.recent_news(ticker, limit)
```

FastMCP reads the name, the inputs (`ticker: str`) and the docstring, and tells
connecting agents about the tool automatically.

### 2.6 Docker
Docker packs your program and *everything it needs* (Python, libraries) into a
**container**. Think of a sealed lunchbox that tastes the same wherever you open it.
This avoids the classic "but it works on my laptop!" problem.

- `Dockerfile` = the recipe for building the lunchbox.
- `docker-compose.yml` = a short instruction card so one command
  (`docker compose up`) builds and starts it.

### 2.7 MCP Inspector
A free web tool for **testing an MCP server by hand**, without any AI involved. You
connect, see the list of tools, type in inputs, click **Run** and see the output. If a
tool is broken, you find out here before an agent gets confused by it. That's the
"debugging via MCP Inspector" deliverable.

### 2.8 Structured messages (Pydantic)
If agents passed each other free-form chat, the Coordinator would have to hunt for the
important bits. Instead, each specialist must fill in a **form** with fixed boxes
(headline, key points, risks, confidence, sources).

**Pydantic** is the Python library that defines these forms and rejects badly
filled-in ones. See `shared/messages.py`. Think of it as a standard hospital referral
form rather than a handwritten letter.

### 2.9 Coordinator-Dispatcher pattern
The Coordinator:
1. **Decomposes** the question (what is being asked? which company?),
2. **Dispatches** the parts to the right specialists, and
3. **Aggregates** their answers into one note.

We show **two ways** to do the dispatching:
- **CrewAI version:** plain Python rules. If the question mentions "news", send the
  News Researcher. If it says "brief me", send everyone. This is fast, free and
  predictable.
- **ADK version:** the LLM reads the question and decides. This is more flexible
  (it understands unusual wording) but less predictable, and it costs more.

### 2.10 Research → Critique → Refine
This is how good writing happens in real life: **draft → review → improve**.
1. **Research:** specialists gather facts, and the Coordinator writes a draft.
2. **Critique:** the Compliance Checker reviews the draft and lists problems.
3. **Refine:** the Coordinator fixes the problems.
4. Repeat steps 2 and 3 until the draft passes, up to a maximum of two rounds, so it
   can't loop forever.

### 2.11 CrewAI vs Google ADK
Both are Python **frameworks** for building agents. A framework is a ready-made kit,
so you don't have to write everything from scratch.

| | CrewAI | Google ADK |
|---|---|---|
| Style | A "crew" of role-playing agents doing tasks | Agents arranged in a tree |
| Main building blocks | `Agent`, `Task`, `Crew` | `LlmAgent`, `SequentialAgent`, `LoopAgent` |
| Built-in chat UI | No (we use the terminal) | Yes (`adk web`) |

### 2.12 Flowise / n8n (visual tools)
These let you build agent workflows by **dragging boxes and drawing arrows**, with no
code. We rebuild the same system visually. It uses the same MCP server, which shows
the value of MCP.

---

## Part 3: A tour of every file

Open the project in VS Code and follow along.

### The MCP server: `mcp_server/`

| File | What it does | What to look at |
|---|---|---|
| `data_sources.py` | Fetches data from Yahoo Finance (using the `yfinance` library). If that fails, it returns **sample data**, clearly labelled. | `compute_risk_metrics()`: the maths for volatility, drawdown and VaR, with comments. |
| `compliance_rules.py` | A rulebook. It checks a note for banned phrases ("guaranteed return"), a missing disclaimer, missing citations and missing risk discussion. | `run_compliance_checks()`: each rule is just a few lines. |
| `server.py` | Turns the functions above into **6 MCP tools** using `@mcp.tool`. It also has a `/health` web page that Docker uses to check the server is alive. | The docstrings: the AI reads these! |

**Why split `data_sources.py` from `server.py`?** So we can test the logic without
starting a server, and so we could swap data providers without touching the server.

### Shared code: `shared/`

| File | What it does |
|---|---|
| `config.py` | Reads settings (API key, model name, server URL) from your `.env` file. |
| `messages.py` | The **forms** agents fill in: `DispatchPlan`, `SpecialistFinding`, `CritiqueResult` and `Source`. |

### CrewAI version: `crewai_app/`

| File | What it does |
|---|---|
| `coordinator.py` | The **dispatcher**. It finds the ticker in the question (e.g. NVDA) and picks the specialists using keyword rules. |
| `agents.py` | Creates the **5 agents** (4 specialists + Coordinator). `TOOLS_FOR` says which tools each agent may use. |
| `tasks.py` | The **work orders**: one per specialist, plus draft, critique and refine. The note layout is in `NOTE_TEMPLATE`. |
| `main.py` | **Runs everything** in 7 numbered steps (see Part 4). It saves the note and the audit trail to `outputs/`. |

### Google ADK version: `adk_app/research_coordinator/`

| File | What it does |
|---|---|
| `agent.py` | The whole system in one file. The Coordinator uses the 3 specialists as **tools** (`AgentTool`). A `LoopAgent` repeats Critique → Refine. The critic calls `exit_loop` when it's satisfied. |
| `__init__.py` | One line that ADK needs to find `agent.py`. |

### Other files

| File | What it does |
|---|---|
| `Dockerfile` / `docker-compose.yml` / `.dockerignore` | Package and run the MCP server in Docker. |
| `requirements.txt` | The list of Python libraries to install. `requirements-mcp.txt` is the smaller list for the server only. |
| `.env.example` | A template for your settings. Copy it to `.env` and add your key. **Never share `.env`.** |
| `.gitignore` | Stops `.env` and junk files being uploaded to GitHub. |
| `scripts/check_mcp_server.py` | Tests the server like an agent would, but **without an LLM**. |
| `tests/` | Automatic checks. Run `pytest -v` and you should see 20 tests pass. |
| `.vscode/launch.json` | Lets you run things with **F5** in VS Code. |
| `visual_workflow/FLOWISE_BUILD_GUIDE.md` | Click-by-click instructions for the Flowise version. |

---

## Part 4: What happens when you ask "Brief me on NVDA earnings risk"

Follow it in `crewai_app/main.py`:

1. **Plan.** `plan_research()` finds `NVDA`. "Brief" counts as a broad request, so
   all 3 research specialists are dispatched, plus the Compliance Checker.
2. **Connect.** `MCPServerAdapter` connects to the MCP server and loads its 6 tools.
3. **Research.**
   - The Financial Analyst calls `get_company_snapshot`, `get_financial_metrics` and
     `get_earnings_info`, then fills in a `SpecialistFinding` form.
   - The Risk Assessor calls `get_price_risk_metrics` and `get_earnings_info`.
   - The News Researcher calls `get_recent_news`.
   - The Coordinator reads all three forms and writes a **draft note** with [1], [2]
     citations.
4. **Critique.** The Compliance Checker calls `check_compliance` with the draft and
   adds its own review. Result: `CritiqueResult(passed=False, blocking_issues=[...])`.
5. **Refine.** The Coordinator fixes the issues. Then steps 4 and 5 repeat, at most
   twice.
6. **Final gate.** One last `check_compliance` call is made directly, with **no LLM**,
   so the result can be trusted.
7. **Save.** Two files go into `outputs/`:
   - `crewai_NVDA_<date>.md`, the research note (your demo output)
   - `crewai_NVDA_<date>_trace.json`, the **audit trail**: who did what, and every
     draft and critique

---

## Part 5: Setting up in VS Code, step by step

### 5.1 Install these once
1. **Python 3.11 or newer**: https://www.python.org/downloads/ (on Windows, tick
   "Add Python to PATH").
2. **VS Code**, plus the **Python** extension from Microsoft.
3. **Docker Desktop**: https://www.docker.com/products/docker-desktop/ (start it
   before running Docker commands).
4. **Node.js 18 or newer** (LTS version): https://nodejs.org (needed for MCP
   Inspector and Flowise).
5. A free **Gemini API key**: https://aistudio.google.com/apikey

### 5.2 Open the project
Unzip the project, then in VS Code choose **File → Open Folder** and pick
`multi-agent-research-capstone`. Open a terminal with **Terminal → New Terminal**.

### 5.3 Create a virtual environment
A virtual environment is a private box of libraries for this project only, so it
won't clash with other projects.

```bash
python -m venv .venv
```
Then **activate** it:
- **Mac/Linux:** `source .venv/bin/activate`
- **Windows (PowerShell):** `.venv\Scripts\Activate.ps1`
  If you get a "running scripts is disabled" error, first run
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

You'll see `(.venv)` at the start of the terminal line. That means it worked.

VS Code may ask *"Select interpreter?"*. Choose the one inside `.venv`. On Windows,
if VS Code can't find it, press Ctrl+Shift+P → "Python: Select Interpreter" →
`.venv\Scripts\python.exe`.

### 5.4 Install the libraries
```bash
pip install -r requirements.txt
```
This takes a few minutes the first time.

### 5.5 Add your key
```bash
cp .env.example .env          # Windows: copy .env.example .env
```
Open `.env` and paste your Gemini key into **both** `GEMINI_API_KEY` and
`GOOGLE_API_KEY`.

### 5.6 Run things in this order

| Step | Command | What you should see |
|---|---|---|
| 1. Tests | `pytest -v` | `20 passed` |
| 2. Server | `docker compose up --build` (leave it running) | `Uvicorn running on http://0.0.0.0:8000` |
| 3. Server check | **New terminal**, activate `.venv`, run `python scripts/check_mcp_server.py` | A list of 6 tools and some JSON |
| 4. Inspector | `npx @modelcontextprotocol/inspector` | A browser page opens. Choose **Streamable HTTP**, enter `http://localhost:8000/mcp`, click **Connect**, then **Tools → List Tools**. Try one. **Screenshot this for your submission.** |
| 5. CrewAI demo | `python -m crewai_app.main "Brief me on NVDA earnings risk"` | Agents "thinking" in the terminal, then the final note. Takes 1-3 minutes. |
| 6. ADK demo | `cd adk_app` then `adk web --port 8080` | Open http://localhost:8080, pick `research_coordinator` and ask the question. The **Events** tab shows each agent's step. |
| 7. Flowise | See `visual_workflow/FLOWISE_BUILD_GUIDE.md` | The same note, made by the visual workflow |

No Docker? You can run the server directly instead with `python -m mcp_server.server`.

---

## Part 6: Common errors and how to fix them

| Error message (or symptom) | What it means | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'crewai'` | Libraries aren't installed, or `.venv` isn't active | Activate `.venv` (step 5.3), then run `pip install -r requirements.txt` |
| `ModuleNotFoundError: No module named 'shared'` | You ran the command from the wrong folder | Run from the project's main folder, using `python -m crewai_app.main` (with `-m`) |
| `Connection refused` / `Failed to connect ... 8000` | The MCP server isn't running | Start it (step 2) and check that http://localhost:8000/health shows `ok` |
| `API key not valid` / `401` | The key is wrong or missing | Check `.env`, with no quotes and no spaces around `=` |
| `429 Resource exhausted` / rate limit | The free tier sends too many requests too fast | Wait a minute and try again. Set `MAX_REFINE_ROUNDS=1` in `.env` |
| `port is already allocated` | Something else is using port 8000 | Stop the other program, or change to `"8001:8000"` in `docker-compose.yml` and set `MCP_SERVER_URL=http://localhost:8001/mcp` |
| The note says "SAMPLE DATA" | Yahoo Finance couldn't be reached | That's the safety fallback working. Check your internet connection, or present it as offline mode. |
| `ImportError ... AuthorizationCodeResult` (FastMCP) | Library versions clash | `pip install "fastmcp>=2.12,<4" "mcp>=1.30,<2"` |
| ADK web is blank / shows no agents | You started it from the wrong folder | Run `adk web` from **inside** `adk_app/` |

---

## Part 7: Questions an assessor might ask (and how to answer)

**Q: Why not use one agent with all the tools?**
A single agent juggling every job gets confused. It's weak at each step and hard to
audit. Specialists with narrow tools do each job better, and the trace file shows
exactly who said what.

**Q: Why use MCP instead of normal Python functions?**
With MCP, the tools are written once and reused by CrewAI, ADK, Flowise and MCP
Inspector. The server also runs separately in Docker, so tools can be updated or
scaled without touching the agents.

**Q: How do you stop the AI making up numbers?**
In three ways. Specialists are told to use only tool figures and to copy each tool's
source. Every figure needs a citation. And the compliance rules block notes without
enough citations.

**Q: Why is compliance partly rule-based rather than all LLM?**
LLMs can be inconsistent. Fixed rules always give the same answer and are easy to
audit. The LLM adds judgement on top, such as "are the risks fairly weighted?"

**Q: What stops the Critique → Refine loop running forever?**
`MAX_REFINE_ROUNDS` in `.env` (default 2). The CrewAI loop and ADK's `LoopAgent` both
respect it.

**Q: What's the difference between your two coordinators?**
The CrewAI one uses keyword rules: predictable, free and testable. The ADK one lets
the LLM decide: it handles unusual wording but is less predictable. Choosing between
them is a trade-off between control and flexibility.

**Q: What would you improve for production?**
A licensed data feed instead of Yahoo, a human approval step before publishing,
parallel specialists for speed, cost tracking, and a fuller compliance rulebook.

---

## Part 8: Glossary

| Term | Meaning |
|---|---|
| **Agentic AI** | AI that takes actions (calls tools, makes decisions) rather than only answering. |
| **API key** | A password that lets your code use an online service, such as Gemini. |
| **Audit trail** | A record of every step, so a human can check how a result was reached. |
| **Container** | A packaged, portable copy of a program and everything it needs (Docker). |
| **Docstring** | The text in triple quotes under a function, explaining what it does. |
| **Drawdown** | How far a price fell from its highest point. −35% means it lost 35% from a peak. |
| **Guardrail** | A rule that stops an AI doing something unsafe or wrong. |
| **Least privilege** | Give each part of a system only the access it needs. |
| **MCP** | Model Context Protocol: the standard way for AI agents to use tools. |
| **Pydantic** | A Python library for defining and checking data "forms". |
| **Temperature** | How "creative" an LLM is. Low (0.2) means more factual and consistent. |
| **Ticker** | A stock's short code, e.g. NVDA for NVIDIA. |
| **Transport** | How client and server talk. We use "Streamable HTTP". |
| **VaR (Value at Risk)** | "On 95% of days, the loss was no worse than X%." |
| **Virtual environment** | A private folder of Python libraries for one project. |
| **Volatility** | How much a price swings. Higher means a bumpier ride. |

---

## Your submission checklist

- [ ] `pytest -v` shows 20 passed (screenshot)
- [ ] The MCP server running in Docker (screenshot of `docker compose up` or Docker Desktop)
- [ ] MCP Inspector connected and running a tool (screenshot)
- [ ] CrewAI demo output: the `.md` note and `_trace.json` from `outputs/`
- [ ] The ADK web UI showing the agent events (screenshot)
- [ ] The Flowise canvas (screenshot) and the exported JSON in `visual_workflow/`
- [ ] README.md explaining the architecture (already done; add your name)
