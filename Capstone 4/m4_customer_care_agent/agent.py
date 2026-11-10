"""
agent.py - the NovaShop Customer Care Agent.

The loop, in plain words:

    customer says something
    └─► model replies with either:
          (a) text  -> that's the answer, show it to the customer
          (b) one or more tool calls ->
                 validate every argument (Pydantic)        ← bad args never reach the API
                 READ tools    -> run straight away, in PARALLEL if there are several
                 WRITE tools   -> policy pre-check → human approval → run → audit
                 HANDOFF tool  -> create escalation ticket → audit
              feed the results back to the model and go round again

Around that loop sit two safety nets:
    • confidence score - drops on validation errors / API failures; below 0.5
      the agent stops trying and escalates to a human
    • escalation triggers - "chargeback", "solicitor", "speak to a human" etc.
      force a hand-off even if the model forgets
"""

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from pydantic import ValidationError

from guardrails import AuditLog, ConfirmationGate
from memory import CustomerMemory
from tools import TOOLS, ApiClient, Context, EscalateArgs

SYSTEM_PROMPT = """You are Nova, the customer care agent for NovaShop, a UK online homeware shop.
Today is {today}. You are chatting with {name} (customer ID {customer_id}); they are already signed in.

CUSTOMER HISTORY (from long-term memory):
{history}

RULES
1. Never guess order, shipping or stock details. Look them up with tools. If you need an order ID you
   don't have, ask for it or use list_my_orders.
2. If you need several independent facts, request all those tool calls in the same turn - they run in parallel.
3. Refunds, in this order: get_order -> check_refund_eligibility -> issue_refund ONLY if eligible.
   Refund the max_refundable amount unless the customer asks for less.
4. Cancellations: get_order -> cancel_order ONLY if status is PROCESSING.
5. issue_refund and cancel_order are sent to a human supervisor for approval automatically.
   If an action comes back REJECTED, explain kindly, pass on any alternative the supervisor suggested,
   and do not try the same action again.
6. If a tool returns VALIDATION_ERROR or "not found", don't invent a corrected value: ask the customer to check.
7. Use escalate_to_human when: the customer asks for a person; they threaten legal action or a chargeback
   (priority high); they want an exception to policy; or you can't resolve it after two tries.
   Give them the ticket number and the expected response time.
8. Be warm, brief and plain-spoken, in British English. Money in GBP (£). Never mention tool names,
   JSON, or internal codes like DAMAGED to the customer.
"""

ESCALATION_TRIGGERS = [
    (r"\b(charge ?back|dispute (it|the payment) with my bank)\b", "LEGAL_OR_CHARGEBACK_THREAT", "high"),
    (r"\b(solicitor|lawyer|legal action|small claims|trading standards|ombudsman|sue)\b",
     "LEGAL_OR_CHARGEBACK_THREAT", "high"),
    (r"\b(speak|talk) to (a |an )?(human|person|manager|supervisor|someone real)\b|\breal person\b",
     "CUSTOMER_REQUESTED_HUMAN", "normal"),
]
CONFIDENCE_FLOOR = 0.5


class CareAgent:
    def __init__(self, customer_id: str, llm, approver, memory: CustomerMemory | None = None,
                 audit: AuditLog | None = None, api_base: str | None = None, max_steps: int = 8,
                 customer_name: str = "", on_event=print):
        self.session_id = "S-" + uuid.uuid4().hex[:6]
        self.customer_id = customer_id
        self.llm = llm
        self.memory = memory or CustomerMemory()
        self.audit = audit or AuditLog()
        self.gate = ConfirmationGate(approver, self.audit)
        self.ctx = Context(customer_id=customer_id, api=ApiClient(customer_id, api_base))
        self.max_steps = max_steps
        self.on_event = on_event
        self.confidence = 1.0
        self.escalated_ticket = None
        self.actions: list[str] = []          # plain-English log for the session summary
        self.tools = list(TOOLS.values())

        history = self.memory.context_text(customer_id)
        self.on_event(f"   🧠 memory ({self.memory.backend}): " + history.replace("\n", "\n      "))
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT.format(
            today=date.today().isoformat(), name=customer_name or customer_id,
            customer_id=customer_id, history=history)}]

    # ------------------------------------------------------------------ chat turn
    def chat(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        trigger = self._detect_trigger(user_text)
        if trigger and not self.escalated_ticket:
            self.on_event(f"   🚩 escalation trigger detected: {trigger[0]}")
            self.messages.append({"role": "system", "content":
                f"GUARDRAIL: escalation required ({trigger[0]}). Call escalate_to_human now with "
                f"reason {trigger[0]} and priority {trigger[1]}, then tell the customer the ticket number."})

        for _ in range(self.max_steps):
            reply = self.llm.complete(self.messages, self.tools)

            if not reply.tool_calls:                         # (a) a plain answer
                if trigger and not self.escalated_ticket:    # model ignored the guardrail -> do it ourselves
                    return self._force_escalation(trigger[0], trigger[1], "Trigger phrase in customer message")
                self.messages.append({"role": "assistant", "content": reply.content})
                return reply.content

            # (b) tool calls: record the request exactly as the API expects it
            self.messages.append({"role": "assistant", "content": reply.content or None, "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                for c in reply.tool_calls]})
            for call, result in zip(reply.tool_calls, self._execute(reply.tool_calls)):
                self.messages.append({"role": "tool", "tool_call_id": call.id,
                                      "content": json.dumps(result, default=str)})

            if self.confidence < CONFIDENCE_FLOOR and not self.escalated_ticket:
                return self._force_escalation("LOW_CONFIDENCE", "normal",
                                              f"Confidence fell to {self.confidence:.2f} after repeated errors")

        return self._force_escalation("REPEATED_FAILURES", "normal", f"No answer after {self.max_steps} steps")

    # ------------------------------------------------------------------ orchestration
    def _execute(self, calls) -> list[dict]:
        """READ/HANDOFF calls run in parallel; WRITE calls run one at a time afterwards (each needs approval)."""
        results: list[dict | None] = [None] * len(calls)
        parsed = [self._validate(c) for c in calls]

        auto = [i for i, (tool, args, err) in enumerate(parsed) if not err and tool.kind != "write"]
        if len(auto) > 1:
            self.on_event(f"   ⚡ running {len(auto)} tool calls in parallel")
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {i: pool.submit(parsed[i][0].run, parsed[i][1], self.ctx) for i in auto}
            for i, f in futures.items():
                results[i] = f.result()

        for i, (tool, args, err) in enumerate(parsed):
            if err:
                results[i] = err
            elif tool.kind == "write":
                results[i] = self._run_write(tool, args)

        for i, (tool, args, err) in enumerate(parsed):        # bookkeeping, in order, on the main thread
            name = tool.name if tool else calls[i].name
            self._log_call(name, calls[i].arguments, results[i])
            if not err:
                self._after_tool(tool, args, results[i])
        return results

    def _validate(self, call):
        tool = TOOLS.get(call.name)
        if not tool:
            self.confidence -= 0.2
            return None, None, {"error": "UNKNOWN_TOOL", "detail": f"No tool called {call.name}"}
        try:
            args = tool.args_model.model_validate(json.loads(call.arguments or "{}"))
            return tool, args, None
        except (ValidationError, json.JSONDecodeError) as e:
            self.confidence -= 0.2
            details = ([f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()]
                       if isinstance(e, ValidationError) else [str(e)])
            return tool, None, {"error": "VALIDATION_ERROR", "details": details,
                                "hint": "Ask the customer to confirm the value rather than guessing."}

    def _run_write(self, tool, args) -> dict:
        allowed, message = self.gate.authorise(self.session_id, self.ctx, tool, args)
        if not allowed:
            return {"status": "NOT_EXECUTED", "message": message}
        result = tool.run(args, self.ctx)
        self.audit.log(self.session_id, self.customer_id, tool.name, args.model_dump(mode="json"),
                       "FAILED" if "error" in result else "EXECUTED", self.ctx.approver_name,
                       result.get("error", ""), result)
        return result

    # ------------------------------------------------------------------ memory + confidence
    def _after_tool(self, tool, args, result):
        err = result.get("error_type")
        if err == "api_down" or err == "api_error":
            self.confidence -= 0.35
        elif err == "not_found":
            self.confidence -= 0.15
        elif "error" not in result:
            self.confidence = min(1.0, self.confidence + 0.05)

        cid, mem = self.customer_id, self.memory
        if tool.name == "check_refund_eligibility" and "error" not in result:
            mem.upsert_complaint(cid, args.order_id, args.reason.value,
                                 "OPEN" if result["eligible"] else "INELIGIBLE", result["explanation"])
            self.actions.append(f"checked refund for {args.order_id} ({args.reason.value}): "
                                f"{'eligible' if result['eligible'] else 'not eligible'}")
        elif tool.name == "issue_refund":
            if result.get("refund_id"):
                mem.upsert_complaint(cid, args.order_id, args.reason.value, "RESOLVED",
                                     f"refund {result['refund_id']} £{result['amount']:.2f} processing")
                self.actions.append(f"refund {result['refund_id']} £{result['amount']:.2f} on {args.order_id}")
            elif result.get("status") == "NOT_EXECUTED":
                mem.upsert_complaint(cid, args.order_id, args.reason.value, "OPEN", result["message"][:200])
                self.actions.append(f"refund on {args.order_id} not executed ({result['message'][:80]})")
        elif tool.name == "cancel_order":
            outcome = "cancelled" if result.get("status") == "CANCELLED" else f"not cancelled ({result.get('message', result.get('error', ''))[:80]})"
            self.actions.append(f"cancel {args.order_id}: {outcome}")
        elif tool.name == "escalate_to_human" and result.get("ticket_id"):
            self.escalated_ticket = result["ticket_id"]
            mem.upsert_complaint(cid, args.order_id or "GENERAL", "ESCALATION", "ESCALATED",
                                 f"{result['ticket_id']} ({args.reason.value}): {args.summary[:150]}")
            self.actions.append(f"escalated to human, ticket {result['ticket_id']} ({args.reason.value})")
            self.audit.log(self.session_id, cid, tool.name, args.model_dump(mode="json"), "HANDOFF",
                           "agent", args.reason.value, result)
        elif tool.name in ("get_order", "get_shipping_status") and "error" not in result:
            self.actions.append(f"looked up {args.order_id}")

    def _force_escalation(self, reason: str, priority: str, why: str) -> str:
        self.on_event(f"   🆘 forcing escalation: {why}")
        last_user = next(m["content"] for m in reversed(self.messages) if m["role"] == "user")
        args = EscalateArgs(reason=reason, priority=priority, order_id=None,
                            summary=f"{why}. Customer's last message: {last_user[:400]}")
        tool = TOOLS["escalate_to_human"]
        result = tool.run(args, self.ctx)
        self._log_call(tool.name, args.model_dump_json(), result)
        self._after_tool(tool, args, result)
        ticket = result.get("ticket_id", "pending")
        text = (f"I'm sorry I haven't been able to sort this out for you. I've passed your conversation to a "
                f"member of our team (reference {ticket}) and they'll be in touch "
                f"{result.get('expected_response', 'shortly')}.")
        self.messages.append({"role": "assistant", "content": text})
        return text

    @staticmethod
    def _detect_trigger(text: str):
        for pattern, reason, priority in ESCALATION_TRIGGERS:
            if re.search(pattern, text, re.I):
                return reason, priority
        return None

    def _log_call(self, name, arguments, result):
        short = json.dumps(result, default=str)
        self.on_event(f"   🔧 {name}({arguments}) → {short[:260]}{'…' if len(short) > 260 else ''}")

    # ------------------------------------------------------------------ end of chat
    def end_session(self) -> str:
        summary = "; ".join(self.actions) if self.actions else "general enquiry, no actions taken"
        self.memory.add_interaction(self.customer_id, summary)
        return summary
