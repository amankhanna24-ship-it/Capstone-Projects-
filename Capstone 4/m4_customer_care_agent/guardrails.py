"""
guardrails.py - the confirmation gate and the audit log.

THE GATE
    Any WRITE tool (refund, cancel) goes through three checks, in order:
      1. argument validation (done in agent.py with the Pydantic model)
      2. policy pre-check    (e.g. "did you check eligibility first?")
      3. human approval      (a supervisor says yes or no, with a note)
    Only then does the API get called. This is "bounded L2 autonomy":
    the agent proposes, a human disposes.

THE AUDIT LOG
    Every write attempt is recorded in audit.db, whatever happens:
    BLOCKED, REQUESTED, APPROVED, REJECTED, EXECUTED, FAILED, plus HANDOFF
    for escalations. Nothing is ever deleted - it's an append-only record.
"""

import csv
import json
import os
import sqlite3
from datetime import datetime

AUDIT_DB = os.getenv("AUDIT_DB", "audit.db")


class AuditLog:
    def __init__(self, path: str = AUDIT_DB):
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.execute("""CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, session_id TEXT, customer_id TEXT,
            tool TEXT, args TEXT, status TEXT, actor TEXT, note TEXT, result TEXT)""")
        self.con.commit()

    def log(self, session_id, customer_id, tool, args, status, actor="agent", note="", result=None):
        self.con.execute(
            "INSERT INTO audit_log (ts, session_id, customer_id, tool, args, status, actor, note, result) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), session_id, customer_id, tool,
             json.dumps(args, default=str), status, actor, note,
             json.dumps(result, default=str) if result is not None else None))
        self.con.commit()

    def rows(self, session_id: str | None = None) -> list[dict]:
        cur = self.con.execute("SELECT * FROM audit_log" + (" WHERE session_id=?" if session_id else "") +
                               " ORDER BY id", (session_id,) if session_id else ())
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def export_csv(self, path: str) -> str:
        rows = self.rows()
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["id"])
            w.writeheader()
            w.writerows(rows)
        return path


# ---------------------------------------------------------------------------
# Approvers: who says yes or no
# ---------------------------------------------------------------------------
def cli_approver(request: dict) -> tuple[bool, str, str]:
    """Asks a person at the keyboard. Used in chat.py."""
    print("\n" + "=" * 64)
    print("🛑  APPROVAL NEEDED (human-in-the-loop)")
    print(f"    Action : {request['summary']}")
    print(f"    Tool   : {request['tool']}  args={request['args']}")
    print("=" * 64)
    answer = input("Approve? [y/N] ").strip().lower()
    note = input("Note (optional): ").strip()
    return answer in ("y", "yes"), os.getenv("SUPERVISOR_NAME", "supervisor"), note


class ScriptedApprover:
    """Pre-decided answers so the demo is repeatable. Pops one decision per request."""

    def __init__(self, decisions: list[tuple[bool, str]], name: str = "supervisor.demo"):
        self.decisions = list(decisions)
        self.name = name

    def __call__(self, request: dict) -> tuple[bool, str, str]:
        approved, note = self.decisions.pop(0) if self.decisions else (False, "no scripted decision left")
        verdict = "APPROVED ✅" if approved else "REJECTED ❌"
        print(f"\n   🛑 APPROVAL NEEDED: {request['summary']}\n   👤 {self.name}: {verdict} {note}")
        return approved, self.name, note


class ConfirmationGate:
    def __init__(self, approver, audit: AuditLog):
        self.approver = approver
        self.audit = audit

    def authorise(self, session_id: str, ctx, tool, args) -> tuple[bool, str]:
        """Returns (allowed, message_for_the_agent)."""
        dumped = args.model_dump(mode="json")

        # 2. policy pre-check
        problem = tool.precheck(args, ctx) if tool.precheck else None
        if problem:
            self.audit.log(session_id, ctx.customer_id, tool.name, dumped, "BLOCKED", "policy", problem)
            return False, f"BLOCKED by policy: {problem}"

        # 3. human approval
        summary = tool.describe(args, ctx) if tool.describe else f"{tool.name} {dumped}"
        self.audit.log(session_id, ctx.customer_id, tool.name, dumped, "REQUESTED", "agent", summary)
        approved, who, note = self.approver({"tool": tool.name, "args": dumped, "summary": summary})
        self.audit.log(session_id, ctx.customer_id, tool.name, dumped,
                       "APPROVED" if approved else "REJECTED", who, note)
        if not approved:
            return False, f"REJECTED by human supervisor {who}. Note: {note or 'none given'}"
        ctx.approver_name = who
        return True, "approved"
