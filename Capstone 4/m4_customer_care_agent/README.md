# NovaShop Customer Care Agent — tool-using agent with human-in-the-loop refunds

## The problem
Support teams spend most of their time on repeat lookups: where's my order, can I get a refund, when will it arrive. FAQ bots can't answer these because the answers depend on live data. A plain LLM can't either: it has no access to the systems, and nothing stops it issuing a refund it shouldn't.

## The approach
An OpenAI function-calling agent with eight strictly typed tools over a mock back office (FastAPI + SQLite). Reads run automatically. Writes (refunds, cancellations) pass a policy check and then need a human supervisor's approval, and every attempt is audited. This is **bounded L2 autonomy**: the agent does the legwork and proposes actions, a person signs off on anything that moves money.

```
 customer ─► CareAgent (agent.py) ── OpenAI function calling ──► model
                │  ▲
                │  └── tool results ◄───────────────────────────────┐
                ▼                                                   │
        validate args (Pydantic: regex / enum / range)              │
                │                                                   │
     ┌──────────┼───────────────────┬───────────────────────┐       │
     ▼          ▼                   ▼                       ▼       │
   READ      READ (parallel)      WRITE                  HANDOFF    │
     │          │           policy pre-check            escalate    │
     │          │           human approval (gate)          │        │
     │          │           audit: REQUESTED/APPROVED/...  │        │
     └──────────┴───────────────────┴───────────────────────┴──► mock_api.py (FastAPI) ─► novashop.db
                                                                     ownership + policy re-checked
     customer memory (Upstash Redis): complaints + past interactions, loaded at chat start
```

## Requirement → implementation

| Requirement | Where | How |
|---|---|---|
| Tool schemas: get_order, get_shipping_status, check_refund_eligibility, issue_refund | `tools.py` → `TOOLS` | Pydantic models converted to OpenAI **strict** schemas (`additionalProperties: false`, all fields required, enums inlined). Plus `list_my_orders`, `check_inventory`, `cancel_order`, `escalate_to_human`. |
| Sequential orchestration | `agent.chat` loop | Each turn's results go back to the model, which chooses the next call (order → shipping; order → eligibility → refund). |
| Parallel orchestration | `agent._execute` | Several read calls in one model turn run at once in a `ThreadPoolExecutor`. Writes always run afterwards, one at a time. |
| Conditional orchestration | `tools._precheck_refund`, `_precheck_cancel` | Enforced in code, not only the prompt: no refund without a passing eligibility check for the same order and reason, and the amount must not exceed `max_refundable`. Cancel only after `get_order` shows PROCESSING. |
| Argument validators | `tools.py` models | Regex `^NS-\d{5}$` on order IDs, enums on refund/cancel/escalation reasons, `0 < amount ≤ 5000` with at most 2 decimals, `extra="forbid"`. Errors go back to the model as `VALIDATION_ERROR` with a hint to ask the customer. |
| Human-in-the-loop gate | `guardrails.ConfirmationGate` | Policy pre-check → approver (keyboard in `chat.py`, scripted in `demo.py`) → only then the API call. Rejections go back to the model with the supervisor's note. |
| Audit log | `guardrails.AuditLog` → `audit.db`, `demo_output/audit_log.csv` | Append-only rows: BLOCKED, REQUESTED, APPROVED, REJECTED, EXECUTED, FAILED, HANDOFF, each with who acted and why. |
| Conversation memory | `CareAgent.messages` | Full message history, including tool calls, for the session. |
| Per-customer memory | `memory.CustomerMemory` (Upstash) | `novashop:customer:<id>` holds complaints (order, issue, status) and recent interaction summaries. Injected into the system prompt at chat start; a resolved complaint is never re-opened by a later lookup. |
| Escalation fallback | `agent._force_escalation` | A confidence score drops on validation errors (−0.2), API failures (−0.35) and not-found (−0.15). Below 0.5 the agent hands off. Trigger phrases (chargeback, solicitor, "speak to a human") force a hand-off even if the model forgets. Hitting the step limit also escalates. |
| Mock APIs over SQLite | `mock_api.py`, `database.py` | Orders, shipping, inventory, eligibility, refund, cancel and escalation endpoints. Every request carries `X-Customer-Id`, and customers only see their own orders. Refund rules are re-checked server-side (defence in depth). |
| 5-scenario demo | `demo.py` → `demo_output/` | See below. |

## The five demo scenarios

| # | Customer | What happens | Shows |
|---|---|---|---|
| 1 | Priya | "Where's NS-10001?" | Sequential reads |
| 2 | Priya | Two orders + "is the blue kettle in stock?" in one message | Parallel reads |
| 3 | James | Cracked headphones → eligibility → refund £129.99 → supervisor **approves** | Conditional write + HITL + audit |
| 4 | Ananya | "Cancel NS-1005" (typo) → validator catches it → corrected → supervisor **rejects** with an alternative | Validators + HITL rejection |
| 5 | James returns | Agent recalls the resolved refund; jacket refund is outside the 14-day change-of-mind window; chargeback threat → high-priority ticket | Memory + policy + escalation |

## Running
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # OpenAI key + Upstash URL/token
python test_offline.py          # 11 checks, no API key needed
python demo.py                  # the five scenarios → demo_output/
python chat.py CUST-0002        # chat yourself and approve actions at the keyboard
uvicorn mock_api:app --port 8000  # optional: explore the API at /docs
```

## Design notes
- **Validation happens twice.** Strict schemas steer the model; Pydantic enforces the rules. OpenAI's docs say strict schemas aren't guaranteed when the model makes parallel calls, so the code never trusts the schema alone.
- **The API doesn't trust the agent.** Ownership and refund rules are checked again server-side, so a prompt-injected or confused agent still can't refund the wrong order or over-refund.
- **Writes run after reads in the same turn.** If the model asks for `get_order` and `cancel_order` together, the order is fetched first so the policy check has fresh data.

## Limitations
- The confidence score is rule-based, not a calibrated probability.
- Approval is synchronous, so the chat waits for the supervisor. A production system would park the action in a queue and resume later.
- Escalation triggers are keyword patterns; a sentiment model would catch more.
