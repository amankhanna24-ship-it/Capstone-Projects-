"""
m1_openai_chatbot_demo.py — multi-SDK chatbot with side-by-side answers.

Every message you type goes to every configured provider (OpenAI, Gemini,
Claude). Each keeps its own conversation history, and you see the answers
one after another with tokens, latency and cost for each.

Usage
  python m1_openai_chatbot_demo.py                      # interactive chat
  python m1_openai_chatbot_demo.py --once "your prompt" # one prompt, then exit
  python m1_openai_chatbot_demo.py --mode cot           # start in a strategy
  python m1_openai_chatbot_demo.py --providers openai,claude
  python m1_openai_chatbot_demo.py --mock               # offline test

In-chat commands
  /mode zero-shot | few-shot | cot   switch prompt strategy
  /reset                             clear every provider's history
  /stats                             session totals per provider
  /help, /quit
"""

from __future__ import annotations

import argparse
import textwrap
from collections import defaultdict

from llm_core import LLMProvider, available_providers, safe
from prompting import STRATEGIES, build_prompt

WIDTH = 92


def show(provider_name: str, resp, err: str | None) -> None:
    print("─" * WIDTH)
    if err:
        print(f"[{provider_name}] ERROR  {err}")
        return
    print(resp.summary())
    print("─" * WIDTH)
    for para in resp.text.strip().split("\n"):
        print(textwrap.fill(para, WIDTH) if para else "")


def comparison_table(rows: list[tuple[str, object, str | None]]) -> None:
    print("\n" + "═" * WIDTH)
    print(f"{'provider':<14}{'model':<28}{'in tok':>8}{'out tok':>9}{'latency':>10}{'cost $':>12}")
    for name, r, err in rows:
        if err:
            print(f"{name:<14}{'(failed)':<28}")
            continue
        cost = f"{r.cost_usd:.6f}" if r.cost_usd is not None else "n/a"
        print(f"{name:<14}{r.model[:27]:<28}{r.input_tokens:>8}{r.output_tokens:>9}"
              f"{r.latency_s:>9.2f}s{cost:>12}")
    ok = [(n, r) for n, r, e in rows if not e]
    if len(ok) > 1:
        fastest = min(ok, key=lambda x: x[1].latency_s)[0]
        print(f"fastest: {fastest}", end="")
        priced = [(n, r) for n, r in ok if r.cost_usd is not None]
        if priced:
            print(f"   cheapest: {min(priced, key=lambda x: x[1].cost_usd)[0]}", end="")
        print()
    print("═" * WIDTH + "\n")


class MultiChat:
    def __init__(self, providers: list[LLMProvider], mode: str):
        self.providers = providers
        self.mode = mode
        self.history: dict[str, list[dict]] = {p.name: [] for p in providers}
        self.totals = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "secs": 0.0})

    def ask(self, user_text: str) -> None:
        system, prompt = build_prompt(self.mode, user_text) if self.mode != "zero-shot" \
            else ("You are a helpful, concise assistant.", user_text)
        rows = []
        for p in self.providers:
            msgs = self.history[p.name] + [{"role": "user", "content": prompt}]
            resp, err = safe(p.generate, msgs, system=system)
            show(p.name, resp, err)
            rows.append((p.name, resp, err))
            if not err:
                # keep the plain user text in history, so strategy scaffolding
                # from earlier turns doesn't pile up in the context window
                self.history[p.name] += [{"role": "user", "content": user_text},
                                         {"role": "assistant", "content": resp.text}]
                t = self.totals[p.name]
                t["calls"] += 1; t["in"] += resp.input_tokens; t["out"] += resp.output_tokens
                t["secs"] += resp.latency_s; t["cost"] += resp.cost_usd or 0.0
        comparison_table(rows)

    def stats(self) -> None:
        print(f"\n{'provider':<14}{'calls':>6}{'in tok':>9}{'out tok':>9}{'avg s':>8}{'cost $':>12}")
        for name, t in self.totals.items():
            avg = t["secs"] / t["calls"] if t["calls"] else 0
            print(f"{name:<14}{t['calls']:>6}{t['in']:>9}{t['out']:>9}{avg:>8.2f}{t['cost']:>12.6f}")
        print("(cost is 0 for models without prices in pricing.json)\n")

    def loop(self) -> None:
        names = ", ".join(f"{p.name} ({p.model})" for p in self.providers)
        print(f"Chatting with: {names}\nStrategy: {self.mode}.  Type /help for commands.\n")
        while True:
            try:
                text = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not text:
                continue
            if text in ("/quit", "/exit"):
                break
            if text == "/help":
                print(__doc__.split("In-chat commands")[1])
            elif text == "/reset":
                self.history = {p.name: [] for p in self.providers}
                print("History cleared.\n")
            elif text == "/stats":
                self.stats()
            elif text.startswith("/mode"):
                parts = text.split()
                if len(parts) == 2 and parts[1] in STRATEGIES:
                    self.mode = parts[1]
                    print(f"Strategy now: {self.mode}\n")
                else:
                    print(f"Usage: /mode {' | '.join(STRATEGIES)}\n")
            else:
                self.ask(text)
        self.stats()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", help="send one prompt and exit")
    ap.add_argument("--mode", choices=STRATEGIES, default="zero-shot")
    ap.add_argument("--providers", help="comma-separated subset, e.g. openai,claude")
    ap.add_argument("--mock", action="store_true", help="offline fake providers")
    args = ap.parse_args()

    providers = available_providers(args.providers.split(",") if args.providers else None)
    chat = MultiChat(providers, args.mode)
    if args.once:
        chat.ask(args.once)
    else:
        chat.loop()


if __name__ == "__main__":
    main()
