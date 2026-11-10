"""
tools.py - the agent's tool suite: schemas, validators and the code that calls the API.

Three ideas live in this file:

1. STRICT SCHEMAS. Each tool's arguments are a Pydantic model. From that one
   model we generate the JSON schema the LLM sees (OpenAI function calling)
   AND we validate whatever the LLM sends back. One source of truth.

2. VALIDATORS. Regex on order IDs (NS-12345), enums on reason codes,
   numeric ranges on amounts. A bad argument never reaches the API.

3. TOOL KINDS.
      read    -> runs automatically (get_order, get_shipping_status, ...)
      write   -> must pass the policy pre-check AND a human approval
      handoff -> escalation to a human; no approval needed, but always logged
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator

ORDER_ID_PATTERN = r"^NS-\d{5}$"


# ---------------------------------------------------------------------------
# Enums (the only values the model is allowed to use)
# ---------------------------------------------------------------------------
class RefundReason(str, Enum):
    DAMAGED = "DAMAGED"
    WRONG_ITEM = "WRONG_ITEM"
    NOT_RECEIVED = "NOT_RECEIVED"
    LATE_DELIVERY = "LATE_DELIVERY"
    CHANGED_MIND = "CHANGED_MIND"


class CancelReason(str, Enum):
    CHANGED_MIND = "CHANGED_MIND"
    ORDERED_BY_MISTAKE = "ORDERED_BY_MISTAKE"
    FOUND_CHEAPER = "FOUND_CHEAPER"
    DELIVERY_TOO_SLOW = "DELIVERY_TOO_SLOW"
    OTHER = "OTHER"


class EscalationReason(str, Enum):
    CUSTOMER_REQUESTED_HUMAN = "CUSTOMER_REQUESTED_HUMAN"
    LEGAL_OR_CHARGEBACK_THREAT = "LEGAL_OR_CHARGEBACK_THREAT"
    POLICY_EXCEPTION_REQUESTED = "POLICY_EXCEPTION_REQUESTED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    REPEATED_FAILURES = "REPEATED_FAILURES"
    OTHER = "OTHER"


class Priority(str, Enum):
    normal = "normal"
    high = "high"


# ---------------------------------------------------------------------------
# Argument models = schemas + validators
# ---------------------------------------------------------------------------
class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")   # unknown arguments are an error


class NoArgs(Strict):
    pass


class OrderArgs(Strict):
    order_id: str = Field(pattern=ORDER_ID_PATTERN,
                          description="NovaShop order ID: 'NS-' followed by exactly 5 digits, e.g. NS-10001")

    @field_validator("order_id", mode="before")
    @classmethod
    def upper(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class RefundEligibilityArgs(OrderArgs):
    reason: RefundReason = Field(description="Why the customer wants a refund")


class IssueRefundArgs(OrderArgs):
    reason: RefundReason = Field(description="Must match the reason used in check_refund_eligibility")
    amount: float = Field(gt=0, le=5000, description="Refund amount in GBP, max 2 decimal places, "
                                                       "never more than max_refundable")

    @field_validator("amount")
    @classmethod
    def two_decimals(cls, v):
        if round(v, 2) != v:
            raise ValueError("amount must have at most 2 decimal places")
        return v


class CancelArgs(OrderArgs):
    reason: CancelReason


class InventoryArgs(Strict):
    product_query: str = Field(min_length=2, max_length=60, pattern=r"^[A-Za-z0-9 .\-]+$",
                               description="Product name and/or colour, e.g. 'blue kettle'")


class EscalateArgs(Strict):
    reason: EscalationReason
    summary: str = Field(min_length=10, max_length=600,
                         description="Hand-over note for the human agent: what the customer wants, what was tried")
    order_id: str | None = Field(pattern=ORDER_ID_PATTERN, description="Related order, or null")
    priority: Priority = Field(description="'high' for legal/chargeback threats or vulnerable customers")


def openai_schema(model: type[BaseModel]) -> dict:
    """
    Turn a Pydantic model into an OpenAI 'strict' JSON schema:
    inline $refs, drop titles/defaults, forbid extra keys, mark every field required.
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def clean(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return clean(defs[node["$ref"].split("/")[-1]])
            node = {k: clean(v) for k, v in node.items() if k not in ("title", "default")}
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}).keys())
                node.setdefault("properties", {})
            return node
        if isinstance(node, list):
            return [clean(x) for x in node]
        return node

    return clean(raw)


# ---------------------------------------------------------------------------
# Talking to the mock API
# ---------------------------------------------------------------------------
class ApiClient:
    def __init__(self, customer_id: str, base_url: str | None = None):
        self.base = (base_url or os.getenv("NOVASHOP_API", "http://127.0.0.1:8000")).rstrip("/")
        self.s = requests.Session()
        self.s.headers["X-Customer-Id"] = customer_id

    def call(self, method: str, path: str, **kwargs) -> dict:
        try:
            r = self.s.request(method, self.base + path, timeout=10, **kwargs)
        except requests.RequestException as e:
            return {"error": f"API unreachable: {e}", "error_type": "api_down"}
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            kind = "not_found" if r.status_code == 404 else "rejected" if r.status_code in (409, 422) else "api_error"
            return {"error": str(detail), "error_type": kind, "http_status": r.status_code}
        return r.json()


@dataclass
class Context:
    """Everything a tool needs to know about the current conversation."""
    customer_id: str
    api: ApiClient
    approver_name: str = ""
    orders_seen: dict = field(default_factory=dict)        # order_id -> last get_order result
    eligibility: dict = field(default_factory=dict)        # (order_id, reason) -> eligibility result


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
def _list_orders(a: NoArgs, ctx: Context):
    return ctx.api.call("GET", "/customers/me/orders")


def _get_order(a: OrderArgs, ctx: Context):
    res = ctx.api.call("GET", f"/orders/{a.order_id}")
    if "error" not in res:
        ctx.orders_seen[a.order_id] = res
    return res


def _get_shipping(a: OrderArgs, ctx: Context):
    return ctx.api.call("GET", f"/orders/{a.order_id}/shipping")


def _check_eligibility(a: RefundEligibilityArgs, ctx: Context):
    res = ctx.api.call("GET", f"/orders/{a.order_id}/refund-eligibility", params={"reason": a.reason.value})
    if "error" not in res:
        ctx.eligibility[(a.order_id, a.reason.value)] = res
    return res


def _check_inventory(a: InventoryArgs, ctx: Context):
    return ctx.api.call("GET", "/inventory", params={"q": a.product_query})


def _issue_refund(a: IssueRefundArgs, ctx: Context):
    return ctx.api.call("POST", f"/orders/{a.order_id}/refund",
                        json={"amount": a.amount, "reason": a.reason.value, "approved_by": ctx.approver_name})


def _cancel(a: CancelArgs, ctx: Context):
    return ctx.api.call("POST", f"/orders/{a.order_id}/cancel", json={"approved_by": ctx.approver_name})


def _escalate(a: EscalateArgs, ctx: Context):
    return ctx.api.call("POST", "/escalations", json={
        "reason": a.reason.value, "summary": a.summary, "order_id": a.order_id, "priority": a.priority.value})


# ---------------------------------------------------------------------------
# Policy pre-checks for WRITE tools (conditional orchestration, enforced in code)
# Return None if OK, or a string explaining why the action is blocked.
# ---------------------------------------------------------------------------
def _precheck_refund(a: IssueRefundArgs, ctx: Context) -> str | None:
    elig = ctx.eligibility.get((a.order_id, a.reason.value))
    if not elig:
        return (f"Call check_refund_eligibility for {a.order_id} with reason {a.reason.value} "
                f"before issue_refund.")
    if not elig.get("eligible"):
        return f"Order is not eligible: {elig.get('explanation')}"
    if a.amount > elig["max_refundable"]:
        return f"Amount £{a.amount} is more than the maximum refundable £{elig['max_refundable']}."
    return None


def _precheck_cancel(a: CancelArgs, ctx: Context) -> str | None:
    order = ctx.orders_seen.get(a.order_id)
    if not order:
        return f"Call get_order for {a.order_id} before cancel_order."
    if order["status"] != "PROCESSING":
        return f"Only PROCESSING orders can be cancelled; {a.order_id} is {order['status']}."
    return None


@dataclass
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    kind: str                                     # "read" | "write" | "handoff"
    run: Callable
    precheck: Callable | None = None
    describe: Callable | None = None              # one-line summary shown to the human approver

    def openai_spec(self, strict: bool = True) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": openai_schema(self.args_model), "strict": strict}}


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("list_my_orders", "List the current customer's orders (use when they don't know the order ID).",
         NoArgs, "read", _list_orders),
    Tool("get_order", "Get an order's status, items, total and any refunds.", OrderArgs, "read", _get_order),
    Tool("get_shipping_status", "Get carrier, tracking number, current location and ETA for an order.",
         OrderArgs, "read", _get_shipping),
    Tool("check_refund_eligibility", "Check whether an order can be refunded for a given reason and the "
         "maximum refundable amount. ALWAYS call this before issue_refund.",
         RefundEligibilityArgs, "read", _check_eligibility),
    Tool("check_inventory", "Check stock and restock date for a product by name/colour.",
         InventoryArgs, "read", _check_inventory),
    Tool("issue_refund", "Issue a refund. WRITE ACTION: needs supervisor approval. Only after "
         "check_refund_eligibility says eligible.", IssueRefundArgs, "write", _issue_refund,
         precheck=_precheck_refund,
         describe=lambda a, ctx: f"Refund £{a.amount:.2f} on {a.order_id} ({a.reason.value}) for {ctx.customer_id}"),
    Tool("cancel_order", "Cancel an order that has not shipped (status PROCESSING). WRITE ACTION: needs "
         "supervisor approval. Call get_order first.", CancelArgs, "write", _cancel, precheck=_precheck_cancel,
         describe=lambda a, ctx: f"Cancel {a.order_id} ({a.reason.value}) for {ctx.customer_id}, full auto-refund"),
    Tool("escalate_to_human", "Hand the conversation to a human agent and create a ticket. Use when the "
         "customer asks for a person, threatens legal action/chargeback, wants a policy exception, or you "
         "cannot resolve the issue.", EscalateArgs, "handoff", _escalate),
]}
