"""
m1_cot_reasoning_demo.py — Chain-of-Thought reasoning across providers.

Runs a set of reasoning problems that have one correct numeric answer
(several contain a deliberate trap that rewards slowing down). Each problem
is asked with each prompt strategy, to each provider. The script extracts the
final "ANSWER:" line, checks it, and prints accuracy, tokens, latency and
cost per provider per strategy.

What to look for: CoT usually lifts accuracy on trap questions but costs
more output tokens and time. How much it helps differs by provider and model,
and that trade-off is the point of the exercise.

Usage
  python m1_cot_reasoning_demo.py                     # zero-shot vs cot
  python m1_cot_reasoning_demo.py --strategies zero-shot,few-shot,cot
  python m1_cot_reasoning_demo.py --show-reasoning    # print each CoT answer in full
  python m1_cot_reasoning_demo.py --providers openai --mock
"""

from __future__ import annotations

import argparse
import textwrap
from collections import defaultdict

from llm_core import available_providers, safe
from prompting import STRATEGIES, build_prompt, extract_answer, to_number

PROBLEMS = [
    {"id": "bat-ball",
     "q": "A bat and a ball cost £1.10 in total. The bat costs £1.00 more than the ball. "
          "How much does the ball cost, in pence?",
     "answer": 5},
    {"id": "widgets",
     "q": "If 5 machines take 5 minutes to make 5 widgets, how many minutes would it take "
          "100 machines to make 100 widgets?",
     "answer": 5},
    {"id": "lily-pads",
     "q": "A patch of lily pads doubles in size every day. It takes 48 days to cover the whole "
          "lake. On which day did it cover half the lake?",
     "answer": 47},
    {"id": "ages",
     "q": "Priya is three times as old as her son. In 12 years she will be twice as old as him. "
          "How old is Priya now?",
     "answer": 36},
    {"id": "phases",
     "q": "A project has three phases. Phase 1 takes 4 weeks. Phase 2 starts when phase 1 ends "
          "and takes 50% longer than phase 1. Phase 3 starts 1 week before phase 2 ends and "
          "lasts 3 weeks. How many weeks is it from the start of phase 1 to the end of phase 3?",
     "answer": 12},
    {"id": "notebooks",
     "q": "Notebooks cost £3 each, or £10 for a pack of 4. What is the lowest cost, in pounds, "
          "to buy exactly 10 notebooks?",
     "answer": 26},
]


def is_correct(text: str, expected: float) -> tuple[bool, str | None]:
    got = extract_answer(text)
    num = to_number(got)
    return (num is not None and abs(num - expected) < 1e-6), got


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategies", default="zero-shot,cot")
    ap.add_argument("--providers")
    ap.add_argument("--show-reasoning", action="store_true")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()

    strategies = [s for s in args.strategies.split(",") if s in STRATEGIES]
    providers = available_providers(args.providers.split(",") if args.providers else None)

    # stats[(provider, strategy)] -> totals
    stats = defaultdict(lambda: {"n": 0, "correct": 0, "out": 0, "secs": 0.0, "cost": 0.0, "errors": 0})

    for prob in PROBLEMS:
        print(f"\n■ {prob['id']}: {prob['q']}\n  expected: {prob['answer']}")
        for strategy in strategies:
            system, prompt = build_prompt(strategy, prob["q"])
            for p in providers:
                resp, err = safe(p.generate, prompt, system=system, temperature=0)
                s = stats[(p.name, strategy)]
                s["n"] += 1
                if err:
                    s["errors"] += 1
                    print(f"  {strategy:<10}{p.name:<14} ERROR {err}")
                    continue
                ok, got = is_correct(resp.text, prob["answer"])
                s["correct"] += ok
                s["out"] += resp.output_tokens
                s["secs"] += resp.latency_s
                s["cost"] += resp.cost_usd or 0.0
                mark = "✓" if ok else "✗"
                print(f"  {strategy:<10}{p.name:<14}{mark} answered {got!s:<12}"
                      f"out={resp.output_tokens:<5} {resp.latency_s:.2f}s")
                if args.show_reasoning and strategy == "cot":
                    print(textwrap.indent(textwrap.fill(resp.text, 88), "      │ "))

    print("\n" + "═" * 84)
    print(f"{'provider':<14}{'strategy':<11}{'accuracy':>10}{'avg out tok':>13}"
          f"{'avg latency':>13}{'total cost $':>14}{'errors':>8}")
    for (prov, strat), s in sorted(stats.items()):
        done = s["n"] - s["errors"]
        acc = f"{s['correct']}/{s['n']}"
        avg_out = s["out"] / done if done else 0
        avg_s = s["secs"] / done if done else 0
        print(f"{prov:<14}{strat:<11}{acc:>10}{avg_out:>13.0f}{avg_s:>12.2f}s"
              f"{s['cost']:>14.6f}{s['errors']:>8}")
    print("═" * 84)
    print("Cost shows 0 for models without prices in pricing.json.")


if __name__ == "__main__":
    main()
