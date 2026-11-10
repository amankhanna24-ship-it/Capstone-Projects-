"""
chat.py - talk to the agent yourself, and approve/reject write actions at the keyboard.

    python chat.py                 (chat as Priya, CUST-0001)
    python chat.py CUST-0002       (chat as James)

Type 'quit' to end the chat (that's when the interaction is saved to memory).
Try:  "where's NS-10001?"   "refund NS-10004, it's broken"   "I want to speak to a human"
"""

import sys

from dotenv import load_dotenv

load_dotenv()

from agent import CareAgent             # noqa: E402
from guardrails import cli_approver     # noqa: E402
from llm import OpenAIChat              # noqa: E402
from run_api import start_background    # noqa: E402

NAMES = {"CUST-0001": "Priya Sharma", "CUST-0002": "James Wilson", "CUST-0003": "Ananya Rao"}

if __name__ == "__main__":
    cid = sys.argv[1] if len(sys.argv) > 1 else "CUST-0001"
    base = start_background(8000)
    agent = CareAgent(cid, OpenAIChat(), cli_approver, api_base=base, customer_name=NAMES.get(cid, cid))
    print(f"\nChatting as {NAMES.get(cid, cid)} ({cid}). Type 'quit' to finish.\n")
    while True:
        text = input("🧑 You: ").strip()
        if text.lower() in ("quit", "exit", "q"):
            print("Saved to memory:", agent.end_session())
            break
        if text:
            print(f"\n🤖 Nova: {agent.chat(text)}\n")
