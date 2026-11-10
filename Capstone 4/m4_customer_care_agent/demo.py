"""
demo.py - the five customer scenarios, from simple lookup to refund-with-approval.

    python demo.py

What it does:
    1. Resets the database, audit log and customer memory (so every run starts clean)
    2. Starts the mock API in the background
    3. Plays each scenario's customer messages to the agent
    4. A scripted "supervisor" approves or rejects write actions, so the run is repeatable
       (use  python demo.py --interactive  to approve them yourself)
    5. Saves demo_output/demo_transcript.md, audit_log.csv and customer_memory_snapshot.json

Scenario map (which brief requirement each one shows):
    1  Lookup              - sequential read tools (order -> shipping)
    2  Multi-question      - PARALLEL read tools (two orders + stock check at once)
    3  Damaged item        - CONDITIONAL refund: eligibility -> refund -> human APPROVES -> audit
    4  Cancel with typo    - VALIDATOR catches bad order ID; cancel -> human REJECTS
    5  Returning customer  - MEMORY recall; ineligible refund; chargeback threat -> ESCALATION
"""

import argparse
import json
import os
import shutil
import sys

from dotenv import load_dotenv

load_dotenv()

SCENARIOS = [
    {"title": "Order status lookup", "customer": ("CUST-0001", "Priya Sharma"),
     "messages": ["Hi, where's my order NS-10001? When will it arrive?"],
     "decisions": []},
    {"title": "Two orders and a stock check in one message", "customer": ("CUST-0001", "Priya Sharma"),
     "messages": ["I've also got orders NS-10002 and NS-10003 - what's happening with both? "
                  "And is the blue kettle back in stock?"],
     "decisions": []},
    {"title": "Damaged item - refund with approval", "customer": ("CUST-0002", "James Wilson"),
     "messages": ["My headphones from order NS-10004 arrived with a cracked headband. I'd like a refund please."],
     "decisions": [(True, "Damage reported within window - approved")]},
    {"title": "Cancellation with a typo - supervisor rejects", "customer": ("CUST-0003", "Ananya Rao"),
     "messages": ["Please cancel order NS-1005, I ordered it by mistake.",
                  "Sorry, it's NS-10005."],
     "decisions": [(False, "Already picked in the warehouse - offer a free returns label once it arrives")]},
    {"title": "Returning customer, out-of-policy refund, escalation", "customer": ("CUST-0002", "James Wilson"),
     "messages": ["Hi, it's me again. Has my headphones refund gone through? Also I want a refund on my rain "
                  "jacket, order NS-10006 - I just don't like it.",
                  "That's ridiculous. If you won't refund it I'll raise a chargeback with my bank."],
     "decisions": []},
]


def reset_state(out_dir: str):
    for f in ("audit.db", "customer_memory.json"):
        if os.path.exists(f):
            os.remove(f)
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir)
    from database import seed
    seed()          # drops and refills the tables in place (safe even if the API is already running)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interactive", action="store_true", help="approve write actions yourself")
    parser.add_argument("--only", type=int, help="run just one scenario (1-5)")
    args = parser.parse_args()

    out_dir = "demo_output"
    reset_state(out_dir)

    # Clear Upstash memory for the demo customers so the run is repeatable
    from memory import PREFIX, CustomerMemory
    memory = CustomerMemory()
    if memory.redis:
        memory.redis.delete(*[PREFIX + c for c in ("CUST-0001", "CUST-0002", "CUST-0003")])

    from agent import CareAgent
    from guardrails import AuditLog, ScriptedApprover, cli_approver
    from llm import OpenAIChat
    from run_api import start_background

    base = start_background(8000)
    llm, audit = OpenAIChat(), AuditLog()
    transcript = [f"# NovaShop Customer Care Agent — demo run\n\nModel: `{llm.model}` · "
                  f"memory: `{memory.backend}` · approvals: "
                  f"`{'interactive' if args.interactive else 'scripted supervisor'}`\n"]

    for n, sc in enumerate(SCENARIOS, 1):
        if args.only and n != args.only:
            continue
        cid, name = sc["customer"]
        header = f"SCENARIO {n}: {sc['title']}  ({name}, {cid})"
        print("\n" + "#" * 78 + f"\n# {header}\n" + "#" * 78)
        transcript.append(f"\n---\n\n## Scenario {n}: {sc['title']}\n\n_Customer: {name} ({cid})_\n")

        events: list[str] = []

        def on_event(line, events=events):
            print(line)
            events.append(line.strip())

        approver = cli_approver if args.interactive else ScriptedApprover(sc["decisions"])
        agent = CareAgent(cid, llm, approver, memory=memory, audit=audit, api_base=base,
                          customer_name=name, on_event=on_event)
        transcript.append("```\n" + events.pop(0) + "\n```\n")    # the memory line

        for msg in sc["messages"]:
            print(f"\n🧑 {name}: {msg}")
            reply = agent.chat(msg)
            print(f"\n🤖 Nova: {reply}")
            transcript.append(f"**🧑 Customer:** {msg}\n")
            if events:
                transcript.append("```\n" + "\n".join(events) + "\n```\n")
                events.clear()
            transcript.append(f"**🤖 Nova:** {reply}\n")

        summary = agent.end_session()
        transcript.append(f"_Saved to customer memory:_ {summary}  \n_Final confidence:_ {agent.confidence:.2f}\n")

    # ---- outputs ----
    audit.export_csv(f"{out_dir}/audit_log.csv")
    rows = audit.rows()
    transcript.append("\n---\n\n## Audit log (all write and hand-off actions)\n\n"
                      "| # | Time | Customer | Tool | Status | By | Note |\n|---|---|---|---|---|---|---|")
    transcript += [f"| {r['id']} | {r['ts'][11:]} | {r['customer_id']} | {r['tool']} | **{r['status']}** | "
                   f"{r['actor']} | {(r['note'] or '').replace('|', '/')[:90]} |" for r in rows]
    with open(f"{out_dir}/demo_transcript.md", "w") as f:
        f.write("\n".join(transcript) + "\n")
    with open(f"{out_dir}/customer_memory_snapshot.json", "w") as f:
        json.dump({c: memory.load(c) for c in ("CUST-0001", "CUST-0002", "CUST-0003")}, f, indent=2)

    print(f"\n📄 Saved {out_dir}/demo_transcript.md, audit_log.csv, customer_memory_snapshot.json")


if __name__ == "__main__":
    sys.exit(main())
