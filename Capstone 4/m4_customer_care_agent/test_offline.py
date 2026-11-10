"""
test_offline.py - checks the whole system WITHOUT an OpenAI key.

A FakeLLM plays pre-written tool calls; everything else is real: the FastAPI
backend, SQLite, validators, the confirmation gate, the audit log, memory.

    python test_offline.py        ->  should end with ALL TESTS PASSED
"""

import json
import os
import tempfile

# Work in a throwaway folder so the tests never touch your real files
os.chdir(tempfile.mkdtemp())
os.environ["NOVASHOP_DB"] = "test_novashop.db"
os.environ["AUDIT_DB"] = "test_audit.db"
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

import sys  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import CareAgent                                # noqa: E402
from database import seed                                  # noqa: E402
from guardrails import AuditLog, ScriptedApprover          # noqa: E402
from llm import LLMReply, ToolCall                         # noqa: E402
from memory import CustomerMemory                          # noqa: E402
from run_api import start_background                       # noqa: E402
from tools import TOOLS, openai_schema, IssueRefundArgs    # noqa: E402

seed()
BASE = start_background(8765)


class FakeLLM:
    """Each script item is either a string (final answer) or a list of (tool_name, args) calls."""

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    def complete(self, messages, tools):
        self.seen.append(messages[-1])
        step = self.script.pop(0)
        if isinstance(step, str):
            return LLMReply(step)
        return LLMReply("", [ToolCall(f"call_{i}_{len(self.script)}", name, json.dumps(args))
                             for i, (name, args) in enumerate(step)])


def make(cid, script, decisions=(), memory=None, audit=None):
    return CareAgent(cid, FakeLLM(script), ScriptedApprover(list(decisions)), memory=memory or CustomerMemory(),
                     audit=audit or AuditLog(), api_base=BASE, on_event=lambda *_: None)


def tool_results(agent):
    return [json.loads(m["content"]) for m in agent.messages if m["role"] == "tool"]


def run():
    audit, memory = AuditLog(), CustomerMemory()

    # 1. strict schema generation
    s = openai_schema(IssueRefundArgs)
    assert s["additionalProperties"] is False and set(s["required"]) == {"order_id", "reason", "amount"}
    assert s["properties"]["order_id"]["pattern"] == r"^NS-\d{5}$" and "enum" in s["properties"]["reason"]
    assert all(t.openai_spec()["function"]["strict"] for t in TOOLS.values())
    print("✓ strict tool schemas generated from Pydantic")

    # 2. sequential read
    a = make("CUST-0001", [[("get_order", {"order_id": "NS-10001"})],
                           [("get_shipping_status", {"order_id": "NS-10001"})], "Arriving soon"],
             memory=memory, audit=audit)
    assert a.chat("where is NS-10001") == "Arriving soon"
    r = tool_results(a)
    assert r[0]["status"] == "SHIPPED" and r[1]["carrier"] == "Royal Mail"
    print("✓ sequential lookup (get_order → get_shipping_status)")

    # 3. parallel read + ownership guard
    a = make("CUST-0001", [[("get_order", {"order_id": "NS-10002"}), ("get_order", {"order_id": "NS-10003"}),
                            ("check_inventory", {"product_query": "blue kettle"}),
                            ("get_order", {"order_id": "NS-10004"})], "done"], memory=memory, audit=audit)
    a.chat("two orders and a kettle")
    r = tool_results(a)
    assert r[0]["status"] == "DELIVERED" and r[1]["status"] == "PROCESSING"
    assert r[2]["results"][0]["stock"] == 0
    assert r[3]["error_type"] == "not_found", "must not see another customer's order"
    print("✓ parallel tool calls + customer can't see other customers' orders")

    # 4. validators
    a = make("CUST-0003", [[("cancel_order", {"order_id": "NS-1005", "reason": "ORDERED_BY_MISTAKE"}),
                            ("issue_refund", {"order_id": "NS-10005", "reason": "BORED", "amount": 10.555})],
                           "Please check the order number"], memory=memory, audit=audit)
    a.chat("cancel NS-1005")
    r = tool_results(a)
    assert r[0]["error"] == "VALIDATION_ERROR" and "order_id" in r[0]["details"][0]
    assert r[1]["error"] == "VALIDATION_ERROR" and len(r[1]["details"]) == 2   # bad enum + 3 decimals
    print("✓ validators: regex order ID, enum reason, 2-decimal amount")

    # 5. policy pre-check blocks refund without eligibility check
    a = make("CUST-0002", [[("issue_refund", {"order_id": "NS-10004", "reason": "DAMAGED", "amount": 129.99})],
                           "ok"], memory=memory, audit=audit)
    a.chat("refund now")
    assert "BLOCKED by policy" in tool_results(a)[0]["message"]
    print("✓ conditional orchestration enforced: refund blocked until eligibility checked")

    # 6. refund approved -> executed
    a = make("CUST-0002", [[("get_order", {"order_id": "NS-10004"})],
                           [("check_refund_eligibility", {"order_id": "NS-10004", "reason": "DAMAGED"})],
                           [("issue_refund", {"order_id": "NS-10004", "reason": "DAMAGED", "amount": 129.99})],
                           "Refund done"], decisions=[(True, "ok")], memory=memory, audit=audit)
    a.chat("broken headphones")
    refund = tool_results(a)[2]
    assert refund["refund_id"].startswith("RF-") and refund["amount"] == 129.99
    a.end_session()
    print("✓ refund: eligibility → human approval → executed")

    # 7. over-refund blocked (already refunded in full)
    a = make("CUST-0002", [[("check_refund_eligibility", {"order_id": "NS-10004", "reason": "DAMAGED"})], "x"],
             memory=memory, audit=audit)
    a.chat("again")
    assert tool_results(a)[0]["eligible"] is False
    print("✓ second refund on same order refused (already refunded in full)")

    # 8. cancel rejected by human
    a = make("CUST-0003", [[("get_order", {"order_id": "NS-10005"}),
                            ("cancel_order", {"order_id": "NS-10005", "reason": "ORDERED_BY_MISTAKE"})],
                           "Sorry"], decisions=[(False, "already picked")], memory=memory, audit=audit)
    a.chat("cancel NS-10005")
    assert "REJECTED" in tool_results(a)[1]["message"]
    print("✓ cancel: human REJECTS → not executed (get_order ran first in the same turn)")

    # 9. memory recall + chargeback trigger forces escalation even if the model doesn't
    a = make("CUST-0002", ["I understand", ], memory=memory, audit=audit)
    assert "RESOLVED" in a.messages[0]["content"], "previous refund should be in the system prompt"
    reply = a.chat("I'll raise a chargeback with my bank")
    assert "TCK-" in reply and a.escalated_ticket
    print("✓ long-term memory recalled + chargeback trigger forces escalation")

    # 10. low confidence -> escalation
    bad = [("get_order", {"order_id": "bad"})]
    a = make("CUST-0001", [bad, bad, bad, "never reached"], memory=memory, audit=audit)
    reply = a.chat("help")
    assert a.escalated_ticket and a.confidence < 0.5
    print("✓ repeated failures drop confidence → automatic escalation")

    # 11. audit log has the full story
    statuses = [r["status"] for r in audit.rows()]
    for s in ("BLOCKED", "REQUESTED", "APPROVED", "EXECUTED", "REJECTED", "HANDOFF"):
        assert s in statuses, (s, statuses)
    print("✓ audit log records BLOCKED / REQUESTED / APPROVED / EXECUTED / REJECTED / HANDOFF")

    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    run()
