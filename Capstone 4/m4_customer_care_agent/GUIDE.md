# Step-by-step guide: the NovaShop Customer Care Agent in VS Code

Same set-up as Capstone 3, so most of this will feel familiar. Commands go in the VS Code terminal (**View → Terminal**).

---

## Part 1 — The ideas in plain English

**Function calling.** In Capstone 3 the model wrote `Action: web_search` as text and we parsed it with regex. Here we use OpenAI's built-in version. We send the model a list of tools with exact argument schemas, and it replies with a structured request: `get_order({"order_id": "NS-10004"})`. No parsing, fewer format mistakes.

**Read vs write.** Looking up an order can't hurt anyone, so it runs automatically. Issuing a refund moves money, so it stops and asks a human. That split is the heart of the assignment:

| Kind | Tools | What happens |
|---|---|---|
| Read | get_order, get_shipping_status, check_refund_eligibility, check_inventory, list_my_orders | Runs straight away |
| Write | issue_refund, cancel_order | Policy check → human approval → runs → audited |
| Hand-off | escalate_to_human | Creates a ticket for a person → audited |

**Three orchestration patterns**
- *Sequential:* one step needs the last one's answer. Get the order, then check eligibility, then refund.
- *Parallel:* independent questions asked at once. "Status of order A, order B and is the kettle in stock?" means three lookups running together.
- *Conditional:* only do X if Y. Only refund if eligibility said yes. This is enforced in code, so even a model that skips the check gets blocked.

**Validators** are the bouncers at the door. The model might send `NS-1005` (four digits), a reason like `BORED`, or £10.555. Pydantic rejects each one before the API ever sees it, and the agent is told to ask the customer rather than guess.

**Escalation.** The agent keeps a confidence score that starts at 1.0. Each error knocks it down; below 0.5 it hands over to a person. Words like "chargeback" or "solicitor" trigger an immediate hand-off.

**What each file does**

| File | Job |
|---|---|
| `database.py` | Builds `novashop.db` (SQLite) with 3 customers, 6 orders, products, shipments |
| `mock_api.py` | FastAPI "company systems": orders, shipping, refunds, cancellations, tickets |
| `tools.py` | Tool schemas, validators, policy pre-checks, API calls |
| `guardrails.py` | The approval gate and the audit log |
| `memory.py` | Per-customer memory in Upstash Redis |
| `llm.py` | OpenAI function-calling wrapper |
| `agent.py` | The loop, parallel execution, confidence and escalation |
| `demo.py` | Runs the 5 scenarios and saves the evidence |
| `chat.py` | Chat to it yourself and approve refunds at the keyboard |
| `test_offline.py` | 11 checks with a fake model, no key needed |

---

## Part 2 — Set up (10 minutes)

**Step 1. Unzip into your course folder and open it.** Unzipping creates a folder called `m4_customer_care_agent`. In VS Code, **File → Open Folder…** and pick that folder itself (not its parent; that was the snag last time). Check that `agent.py` appears at the top level of the explorer.

**Step 2. Virtual environment**
```bash
python3 -m venv .venv
source .venv/bin/activate
```
Then `Cmd+Shift+P` → **Python: Select Interpreter** → the one with `.venv`.

**Step 3. Install**
```bash
pip install -r requirements.txt
```

**Step 4. Rehearsal, no keys needed**
```bash
python test_offline.py
```
You want 11 ticks and `ALL TESTS PASSED`. You'll also see two approval prompts answered by a scripted supervisor: one approved, one rejected.

---

## Part 3 — Keys (5 minutes)

```bash
cp .env.example .env
```
Open `.env` and fill in:
- `OPENAI_API_KEY`: same key as before.
- `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`: you can reuse the Capstone 3 database. This project's keys start with `novashop:` so nothing collides.
- `SUPERVISOR_NAME`: your name, as it should appear in the audit log when you approve things.

---

## Part 4 — Run it

**Step 5. Look at the pretend company systems (optional but worth five minutes)**
```bash
uvicorn mock_api:app --port 8000
```
Open http://127.0.0.1:8000/docs. Expand `GET /orders/{order_id}` → **Try it out** → order `NS-10004`, X-Customer-Id `CUST-0002` → **Execute**. That's exactly what the agent does. Now try `CUST-0001` with the same order: you get 404, because customers only see their own orders. Press `Ctrl+C` to stop.

**Step 6. The five-scenario demo (main deliverable)**
```bash
python demo.py
```
It takes about a minute. It resets the data, starts the API, plays all five conversations and prints every tool call. When a write comes up you'll see `🛑 APPROVAL NEEDED` and the scripted supervisor's decision.

It saves three files in `demo_output/`:
- `demo_transcript.md`: the full conversations with tool calls and the audit table. This is your demo run.
- `audit_log.csv`: every write action and hand-off.
- `customer_memory_snapshot.json`: what the agent remembers about each customer.

Want to be the supervisor yourself? Run `python demo.py --interactive`. To run just one scenario: `python demo.py --only 3`.

**Step 7. Chat with it**
```bash
python chat.py CUST-0002
```
Try "where's NS-10004?", "it arrived broken, refund please" (you'll be asked to approve), then "I want to speak to a manager". Type `quit` to finish; that's when the conversation is saved to memory. Run `python chat.py CUST-0002` again and ask "what happened last time?"

**Step 8. Check Redis.** Upstash console → **Data Browser** → `novashop:customer:CUST-0002`. Take a screenshot for your submission.

**Step 9 (optional).** `python bonus_langchain_agent.py` runs the same tools through LangGraph. `FLOWISE.md` covers the Flowise version.

---

## Part 5 — Reading the code (in this order)

1. **`tools.py`, the `IssueRefundArgs` class.** Five lines that define what a refund request may contain. `openai_schema()` turns it into what the model sees; the same class validates what comes back.
2. **`tools.py`, `_precheck_refund`.** The conditional rule written as plain `if` statements.
3. **`guardrails.py`, `ConfirmationGate.authorise`.** Policy check, then log REQUESTED, ask the human, then log APPROVED or REJECTED.
4. **`agent.py`, `chat()`.** The loop: ask the model; if it wants tools, run them and go round again; if it writes text, that's the reply.
5. **`agent.py`, `_execute()`.** Validation, the parallel thread pool for reads, and writes one by one.
6. **`agent.py`, `_after_tool()`.** Confidence scoring and the complaint tracking that feeds memory.
7. **`mock_api.py`, `_eligibility()`.** The refund policy: 30 days, or 14 for change of mind; nothing if already refunded; cancel instead if not shipped.

---

## Part 6 — Troubleshooting

| You see | Fix |
|---|---|
| `No such file or directory: requirements.txt` | You're in the parent folder: `cd m4_customer_care_agent` |
| `address already in use` / port 8000 | An old API is still running. Close that terminal, or `lsof -ti:8000 \| xargs kill` |
| `Model rejected strict schemas` warning | Harmless. The code retries without strict mode and Pydantic still validates |
| `AuthenticationError` | Check `OPENAI_API_KEY` in `.env` |
| Agent refunds without asking you | It can't. Check `audit_log.csv` and you'll see REQUESTED/APPROVED before every EXECUTED |
| Answers differ between runs | Normal for LLMs. The scripted supervisor and reset data keep everything else the same |

---

## Part 7 — What to submit
- All `.py` files, `requirements.txt`, `.env.example`, `README.md`
- `demo_output/demo_transcript.md`, `demo_output/audit_log.csv`, `demo_output/customer_memory_snapshot.json`
- Screenshots: Upstash Data Browser, FastAPI `/docs` page, and Flowise canvas if you build it

Don't submit `.env`, `.venv/` or the `.db` files.
