"""
memory.py - per-customer memory in Upstash Redis.

Two kinds of memory:

  Conversation memory (short-term) - the message list inside CareAgent.
      Lives only while the chat is open.

  Customer memory (long-term) - this file. One Redis key per customer:
        novashop:customer:CUST-0002  ->  JSON {
            "complaints":   [{order_id, issue, status, detail, opened, updated}],
            "interactions": [{ts, summary}]           (last 10 kept)
        }
      Loaded at the start of every chat, so the agent can say
      "I can see we spoke last week about your headphones".

If Upstash keys are missing it falls back to customer_memory.json so you can
practise offline. Use Upstash for the submission.
"""

import json
import os
from datetime import datetime

PREFIX = "novashop:customer:"


class CustomerMemory:
    def __init__(self, local_path: str = "customer_memory.json"):
        url, token = os.getenv("UPSTASH_REDIS_REST_URL"), os.getenv("UPSTASH_REDIS_REST_TOKEN")
        self.local_path = local_path
        if url and token:
            from upstash_redis import Redis
            self.redis = Redis(url=url, token=token)
            self.backend = "upstash"
        else:
            self.redis = None
            self.backend = "local-file"
            print("⚠️  Upstash not configured - customer memory goes to customer_memory.json")

    # -- storage ---------------------------------------------------------------
    def load(self, customer_id: str) -> dict:
        if self.redis:
            raw = self.redis.get(PREFIX + customer_id)
        else:
            data = json.load(open(self.local_path)) if os.path.exists(self.local_path) else {}
            raw = data.get(customer_id)
        if not raw:
            return {"complaints": [], "interactions": []}
        return json.loads(raw) if isinstance(raw, str) else raw

    def save(self, customer_id: str, mem: dict):
        mem["interactions"] = mem["interactions"][-10:]
        if self.redis:
            self.redis.set(PREFIX + customer_id, json.dumps(mem))
        else:
            data = json.load(open(self.local_path)) if os.path.exists(self.local_path) else {}
            data[customer_id] = json.dumps(mem)
            json.dump(data, open(self.local_path, "w"), indent=2)

    # -- what the agent uses -------------------------------------------------------
    def upsert_complaint(self, customer_id: str, order_id: str, issue: str, status: str, detail: str):
        mem = self.load(customer_id)
        now = datetime.now().isoformat(timespec="minutes")
        for c in mem["complaints"]:
            if c["order_id"] == order_id and c["issue"] == issue:
                if c["status"] == "RESOLVED" and status in ("OPEN", "INELIGIBLE"):
                    break      # a later lookup must not re-open a complaint we already fixed
                c.update(status=status, detail=detail, updated=now)
                break
        else:
            mem["complaints"].append({"order_id": order_id, "issue": issue, "status": status,
                                      "detail": detail, "opened": now, "updated": now})
        self.save(customer_id, mem)

    def add_interaction(self, customer_id: str, summary: str):
        mem = self.load(customer_id)
        mem["interactions"].append({"ts": datetime.now().isoformat(timespec="minutes"), "summary": summary})
        self.save(customer_id, mem)

    def context_text(self, customer_id: str) -> str:
        mem = self.load(customer_id)
        if not mem["complaints"] and not mem["interactions"]:
            return "No previous interactions on record."
        lines = []
        if mem["complaints"]:
            lines.append("Complaints on record:")
            lines += [f"- {c['order_id']} {c['issue']}: {c['status']} - {c['detail']} (updated {c['updated']})"
                      for c in mem["complaints"]]
        if mem["interactions"]:
            lines.append("Recent interactions:")
            lines += [f"- {i['ts']}: {i['summary']}" for i in mem["interactions"][-5:]]
        return "\n".join(lines)
