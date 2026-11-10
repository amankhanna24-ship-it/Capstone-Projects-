# Building the visual workflow in Flowise

This is the "no-code" twin of the Python version. You drag boxes (nodes) on a
canvas and join them with lines, instead of writing code. It uses **the same MCP
server**, which shows that one set of tools can serve both code-first and visual
systems.

> **Why is there no ready-made JSON file here?** Flowise's export format changes
> between versions, and a hand-written file often won't import. It's quicker and
> more reliable to build the flow in the UI (about 30-40 minutes) and then
> **export** it yourself. The exported file is your deliverable, and building it
> yourself is the learning.
>
> Node names below match Flowise **Agentflow V2** (Flowise 3.x). If your version
> labels something slightly differently, look for the nearest match.

---

## 1. Start Flowise and the MCP server

```bash
# Terminal 1 - the MCP server (from the project folder)
docker compose up --build        # or: python -m mcp_server.server

# Terminal 2 - Flowise (needs Node.js 18 or 20)
npx flowise start
```

Open **http://localhost:3000**.

**Which MCP address do I use?**

| Flowise is running...          | MCP server URL to enter                 |
|--------------------------------|-----------------------------------------|
| with `npx` on your laptop      | `http://localhost:8000/mcp`             |
| inside Docker                  | `http://host.docker.internal:8000/mcp`  |

## 2. Add your LLM key

**Credentials → Add Credential → Google Gemini** (or OpenAI). Paste the same key
you put in `.env`.

## 3. Create the Agentflow

**Agentflows → Add New**. Name it `Multi-Agent Research (Flowise)`.

The finished flow:

```
Start
  │
  ▼
Coordinator Router (Condition Agent) ── "news only" ──► News Researcher ──┐
  │ "full brief"                                                            │
  ▼                                                                         │
Financial Analyst ─► Risk Assessor ─► News Researcher (full) ──────────────┤
                                                                            ▼
                                                       Coordinator (Agent: writes draft)
                                                                            │
                                                                            ▼
                                                 ┌──── Compliance Critic (Agent) ◄──┐
                                                 │            │                     │
                                                 │   Condition: contains "APPROVED"?│
                                                 │     yes │          no │          │
                                                 │         ▼             ▼          │
                                                 │   Direct Reply     Refiner ─► Loop (max 2)
```

### Node-by-node settings

**a) Start**
- Input type: Chat input.
- Add a Flow State variable `draft` (empty). This is the flow's shared memory,
  like ADK's `state`.

**b) Coordinator Router: Condition Agent**
- Model: Gemini (e.g. `gemini-2.5-flash`), temperature 0.
- Instructions: *"Decide what kind of research the user wants."*
- Scenarios:
  1. `Full research brief (fundamentals, risk and news)`
  2. `News only`
- This is the **Coordinator-Dispatcher**. It sends the work down the right branch.

**c) Financial Analyst: Agent node**
- Model: Gemini, temperature 0.2.
- Tools → **Custom MCP**. Server config:
  ```json
  { "url": "http://localhost:8000/mcp" }
  ```
  Click refresh and tick only **get_company_snapshot**, **get_financial_metrics** and
  **get_earnings_info**.
- System message: copy the financial analyst instruction from
  `adk_app/research_coordinator/agent.py` (include the reply structure).
- User message: insert the Start node's question using the `{{ }}` variable picker.

**d) Risk Assessor: Agent node**
- Custom MCP with **get_price_risk_metrics**, **get_earnings_info** and
  **get_financial_metrics** only.
- Copy the instruction from `agent.py`.

**e) News Researcher: Agent node** (one on each branch, or connect both branches to one)
- Custom MCP with **get_recent_news** and **get_company_snapshot** only.

**f) Coordinator: Agent node (no tools)**
- User message: insert the outputs of the three specialist nodes with `{{ }}`.
- System message: copy the `research_coordinator` instruction from `agent.py`
  (sections, citations, disclaimer).
- Update Flow State: set `draft` = this node's output.

**g) Compliance Critic: Agent node**
- Custom MCP with **check_compliance** only.
- Instruction: *"Call check_compliance with the full draft below. If it passes and
  you find no serious problems, reply with the single word APPROVED. Otherwise list
  BLOCKING ISSUES and SUGGESTIONS."* Then insert `{{ $flow.state.draft }}`.

**h) Condition**
- If Compliance Critic output **contains** `APPROVED` → go to **Direct Reply**.
- Else → go to **Refiner**.

**i) Refiner: Agent node**
- Instruction: copy the `refiner` instruction from `agent.py`. Insert the draft and
  the critic's output.
- Update Flow State: `draft` = this node's output.

**j) Loop**
- Loop back to: **Compliance Critic**. Max loop count: **2**.
  This is **Research → Critique → Refine**, drawn as a picture.

**k) Direct Reply**
- Message: `{{ $flow.state.draft }}`

## 4. Test it

Click the chat bubble (top right) and type:

```
Brief me on NVDA earnings risk
```

Click each node in the execution trace to see what it received and returned. Take
**screenshots** of the canvas and of a finished run for your submission.

## 5. Export your deliverable

Open the flow → **Settings (cog) → Export**. Save the file in this folder as:

```
visual_workflow/flowise_multi_agent_research.json
```

## Optional: the n8n version

n8n works the same way:
- **Chat Trigger** → **AI Agent** nodes (one per specialist).
- Each agent gets an **MCP Client Tool**: endpoint `http://localhost:8000/mcp`,
  transport "HTTP Streamable", and only that specialist's tools.
- An **If** node checks for "APPROVED".

Export it from **⋯ → Download**.

## How the visual version mirrors the code

| Concept                    | CrewAI file                    | ADK file            | Flowise node              |
|----------------------------|--------------------------------|---------------------|---------------------------|
| Coordinator-Dispatcher     | `crewai_app/coordinator.py`    | `research_coordinator` | Condition Agent         |
| Specialists + MCP tools    | `crewai_app/agents.py`         | 3 `LlmAgent`s       | Agent + Custom MCP        |
| Aggregation into a brief   | `draft_task` in `tasks.py`     | `research_coordinator` | Coordinator Agent      |
| Critique                   | `critique_task`                | `compliance_critic` | Compliance Critic Agent   |
| Refine + loop              | loop in `main.py`              | `LoopAgent`         | Refiner + Loop node       |
| Shared memory              | `trace` dict                   | session `state`     | Flow State                |
