"""
mock_api.py - NovaShop's pretend back-office APIs (FastAPI over SQLite).

This stands in for the real systems a support agent would call: order
management, the carrier's tracking feed, the refunds service.

Run it on its own:   uvicorn mock_api:app --reload --port 8000
Then open http://127.0.0.1:8000/docs  to click around every endpoint.

Security idea worth noticing: every request carries X-Customer-Id. The API
only shows a customer THEIR OWN orders, so even a confused or tricked agent
can't leak someone else's data. Refund rules are also checked here, not
only in the agent ("defence in depth").
"""

import uuid
from datetime import datetime
from enum import Enum

from fastapi import FastAPI, Header, HTTPException, Path
from pydantic import BaseModel, Field

from database import connect

app = FastAPI(title="NovaShop mock back-office API", version="1.0")

# One shared SQLite connection. The endpoints are `async def`, so FastAPI runs them one at a
# time on its event loop - that keeps SQLite safe when the agent fires parallel requests.
con = connect()

ORDER_ID = r"^NS-\d{5}$"
REFUND_WINDOW_DAYS = 30
CHANGED_MIND_WINDOW_DAYS = 14


class ReasonCode(str, Enum):
    DAMAGED = "DAMAGED"
    WRONG_ITEM = "WRONG_ITEM"
    NOT_RECEIVED = "NOT_RECEIVED"
    LATE_DELIVERY = "LATE_DELIVERY"
    CHANGED_MIND = "CHANGED_MIND"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _owned_order(order_id: str, customer_id: str) -> dict:
    row = con.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    # Same message whether it doesn't exist or belongs to someone else - no data leak.
    if not row or row["customer_id"] != customer_id:
        raise HTTPException(404, f"Order {order_id} not found for this customer")
    return dict(row)


def _refunded_so_far(order_id: str) -> float:
    r = con.execute("SELECT COALESCE(SUM(amount),0) s FROM refunds WHERE order_id=? AND status!='FAILED'",
                    (order_id,)).fetchone()
    return round(r["s"], 2)


def _eligibility(order: dict, reason: ReasonCode) -> dict:
    refunded = _refunded_so_far(order["order_id"])
    max_refundable = round(order["total"] - refunded, 2)
    out = {"order_id": order["order_id"], "reason": reason.value, "order_total": order["total"],
           "already_refunded": refunded, "max_refundable": max(max_refundable, 0.0), "currency": "GBP"}

    def no(why, suggestion=None):
        return {**out, "eligible": False, "explanation": why, "suggestion": suggestion}

    if order["status"] == "CANCELLED":
        return no("Order was cancelled; any refund was issued automatically.")
    if max_refundable <= 0:
        return no("This order has already been refunded in full.")
    if order["status"] == "PROCESSING":
        return no("Order hasn't shipped yet, so it can't be refunded.", "Offer to cancel the order instead.")
    if order["status"] == "SHIPPED":
        ship = con.execute("SELECT eta FROM shipments WHERE order_id=?", (order["order_id"],)).fetchone()
        late_days = (datetime.now() - datetime.fromisoformat(ship["eta"])).days if ship else 0
        if reason in (ReasonCode.NOT_RECEIVED, ReasonCode.LATE_DELIVERY) and late_days >= 3:
            return {**out, "eligible": True, "explanation": f"Parcel is {late_days} days past its ETA."}
        return no("Order is still in transit and within its delivery estimate.",
                  "Share the tracking ETA; a refund for non-delivery is possible 3 days after the ETA.")

    days = (datetime.now() - datetime.fromisoformat(order["delivered_at"])).days
    window = CHANGED_MIND_WINDOW_DAYS if reason == ReasonCode.CHANGED_MIND else REFUND_WINDOW_DAYS
    if days > window:
        return no(f"Delivered {days} days ago; the {reason.value} window is {window} days.",
                  "Policy exceptions need a human supervisor - escalate if the customer wants one.")
    return {**out, "eligible": True, "explanation": f"Delivered {days} days ago, within the {window}-day window."}


# ---------------------------------------------------------------------------
# READ endpoints
# ---------------------------------------------------------------------------
@app.get("/customers/me/orders")
async def list_orders(x_customer_id: str = Header(...)):
    rows = con.execute("SELECT order_id, status, total, placed_at FROM orders WHERE customer_id=? "
                       "ORDER BY placed_at DESC", (x_customer_id,)).fetchall()
    return {"customer_id": x_customer_id, "orders": [dict(r) for r in rows]}


@app.get("/orders/{order_id}")
async def get_order(order_id: str = Path(pattern=ORDER_ID), x_customer_id: str = Header(...)):
    order = _owned_order(order_id, x_customer_id)
    items = con.execute("SELECT i.sku, p.name, p.colour, i.qty, i.unit_price FROM order_items i "
                        "JOIN products p USING (sku) WHERE order_id=?", (order_id,)).fetchall()
    refunds = con.execute("SELECT refund_id, amount, reason, status, created_at FROM refunds "
                          "WHERE order_id=?", (order_id,)).fetchall()
    return {**order, "items": [dict(i) for i in items], "refunds": [dict(r) for r in refunds]}


@app.get("/orders/{order_id}/shipping")
async def get_shipping(order_id: str = Path(pattern=ORDER_ID), x_customer_id: str = Header(...)):
    order = _owned_order(order_id, x_customer_id)
    ship = con.execute("SELECT * FROM shipments WHERE order_id=?", (order_id,)).fetchone()
    if not ship:
        return {"order_id": order_id, "status": "NOT_SHIPPED",
                "detail": f"Order is {order['status']}; no shipment has been created yet."}
    return dict(ship)


@app.get("/orders/{order_id}/refund-eligibility")
async def refund_eligibility(reason: ReasonCode, order_id: str = Path(pattern=ORDER_ID),
                       x_customer_id: str = Header(...)):
    return _eligibility(_owned_order(order_id, x_customer_id), reason)


@app.get("/inventory")
async def inventory(q: str):
    words = [w for w in q.lower().split() if len(w) > 2]
    rows = con.execute("SELECT * FROM products").fetchall()
    hits = [dict(r) for r in rows
            if all(w in (r["name"] + " " + r["colour"]).lower() for w in words)]
    if not hits:  # loosen: any word matches
        hits = [dict(r) for r in rows if any(w in (r["name"] + " " + r["colour"]).lower() for w in words)]
    return {"query": q, "results": hits}


# ---------------------------------------------------------------------------
# WRITE endpoints (the agent may only reach these after human approval)
# ---------------------------------------------------------------------------
class RefundIn(BaseModel):
    amount: float = Field(gt=0, le=5000)
    reason: ReasonCode
    approved_by: str = Field(min_length=2)     # who approved it - required


@app.post("/orders/{order_id}/refund")
async def issue_refund(body: RefundIn, order_id: str = Path(pattern=ORDER_ID), x_customer_id: str = Header(...)):
    order = _owned_order(order_id, x_customer_id)
    elig = _eligibility(order, body.reason)            # re-check here: never trust the caller
    if not elig["eligible"]:
        raise HTTPException(409, f"Not eligible: {elig['explanation']}")
    if round(body.amount, 2) > elig["max_refundable"]:
        raise HTTPException(422, f"Amount {body.amount} exceeds max refundable {elig['max_refundable']}")
    refund_id = "RF-" + uuid.uuid4().hex[:6].upper()
    con.execute("INSERT INTO refunds VALUES (?,?,?,?, 'PROCESSING', ?, ?)",
                (refund_id, order_id, round(body.amount, 2), body.reason.value,
                 datetime.now().isoformat(timespec="seconds"), f"approved by {body.approved_by}"))
    con.commit()
    return {"refund_id": refund_id, "order_id": order_id, "amount": round(body.amount, 2), "currency": "GBP",
            "status": "PROCESSING", "expected_in_account": "3-5 working days"}


class CancelIn(BaseModel):
    approved_by: str = Field(min_length=2)


@app.post("/orders/{order_id}/cancel")
async def cancel_order(body: CancelIn, order_id: str = Path(pattern=ORDER_ID), x_customer_id: str = Header(...)):
    order = _owned_order(order_id, x_customer_id)
    if order["status"] != "PROCESSING":
        raise HTTPException(409, f"Only PROCESSING orders can be cancelled (this one is {order['status']}).")
    con.execute("UPDATE orders SET status='CANCELLED' WHERE order_id=?", (order_id,))
    refund_id = "RF-" + uuid.uuid4().hex[:6].upper()
    con.execute("INSERT INTO refunds VALUES (?,?,?, 'CANCELLATION', 'PROCESSING', ?, ?)",
                (refund_id, order_id, order["total"], datetime.now().isoformat(timespec="seconds"),
                 f"auto refund on cancel, approved by {body.approved_by}"))
    con.commit()
    return {"order_id": order_id, "status": "CANCELLED", "refund_id": refund_id, "refund_amount": order["total"]}


class EscalationIn(BaseModel):
    reason: str = Field(min_length=3, max_length=200)
    summary: str = Field(min_length=10, max_length=2000)
    order_id: str | None = Field(default=None, pattern=ORDER_ID)
    priority: str = Field(default="normal", pattern="^(normal|high)$")


@app.post("/escalations")
async def escalate(body: EscalationIn, x_customer_id: str = Header(...)):
    ticket_id = "TCK-" + uuid.uuid4().hex[:5].upper()
    con.execute("INSERT INTO escalations VALUES (?,?,?,?,?,?,?)",
                (ticket_id, x_customer_id, body.order_id, body.reason, body.summary, body.priority,
                 datetime.now().isoformat(timespec="seconds")))
    con.commit()
    return {"ticket_id": ticket_id, "priority": body.priority,
            "expected_response": "within 2 hours" if body.priority == "high" else "within 24 hours"}
