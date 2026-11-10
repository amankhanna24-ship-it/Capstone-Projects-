"""
m1_comparison_report.py — 5 prompts x 3 providers, scored on accuracy, cost, latency.

Each prompt exercises a different Module 1 concept and has an automatic
checker, so the accuracy score is objective and repeatable:

  1. cot-arithmetic     Chain-of-Thought on a multi-step word problem
  2. zero-shot-logic    a small deduction puzzle, asked plainly
  3. few-shot-classify  ticket routing, taught by examples
  4. json-extraction    structured output against a Pydantic schema (field-level score)
  5. long-context       find one fact buried in ~6,000 words (context handling)

Outputs (in reports/):
  comparison_report.md   the report, with tables and data-driven observations
  results.csv            one row per provider x prompt x run
  responses.jsonl        every raw answer, for your appendix or a re-check

Usage
  python m1_comparison_report.py               # 1 run of each prompt
  python m1_comparison_report.py --runs 3      # average latency/cost over 3 runs (recommended)
  python m1_comparison_report.py --mock        # offline test of the pipeline (fake numbers)

Composite score: accuracy 50%, cost 25%, latency 25%, each scaled 0-1 across the
providers in the run. Change WEIGHTS below if your brief weights them differently.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from llm_core import ROOT, available_providers, mock_mode, safe
from m1_structured_function_demo import EXTRACT_PROMPT, EXTRACT_SYSTEM, JobPosting, score_job
from prompting import build_prompt, extract_answer, to_number

WEIGHTS = {"accuracy": 0.50, "cost": 0.25, "latency": 0.25}
REPORT_DIR = ROOT / "reports"

# ---------------------------------------------------------------------------
# Prompt 3 examples (few-shot)
# ---------------------------------------------------------------------------
TICKET_EXAMPLES = [
    ("Ticket: 'My invoice shows the wrong VAT number.' Categories: billing, technical, account, other.",
     "ANSWER: billing"),
    ("Ticket: 'I need to change the email address on my login.' Categories: billing, technical, account, other.",
     "ANSWER: account"),
    ("Ticket: 'The dashboard shows a 500 error when I filter by date.' Categories: billing, technical, account, other.",
     "ANSWER: technical"),
    ("Ticket: 'Do you have an office in Leeds?' Categories: billing, technical, account, other.",
     "ANSWER: other"),
]


# ---------------------------------------------------------------------------
# Prompt 5: build a long document with one fact hidden ~70% of the way in
# ---------------------------------------------------------------------------
NEEDLE = "The internal code name for the Q3 vendor review is BLUE HERON."


def build_haystack(words_target: int = 6000) -> str:
    rnd = random.Random(42)  # fixed seed: identical document every run
    subjects = ["The procurement team", "Each business unit", "The finance office",
                "Regional managers", "The compliance function", "Vendor owners",
                "The steering group", "Internal audit"]
    verbs = ["reviews", "documents", "approves", "monitors", "reconciles", "escalates",
             "records", "assesses"]
    objects = ["supplier contracts", "purchase orders above threshold", "renewal dates",
               "service-level breaches", "risk ratings", "invoice exceptions",
               "onboarding checklists", "termination notices"]
    tails = ["on a monthly basis.", "before the quarter closes.", "in line with policy 4.2.",
             "using the shared tracker.", "with sign-off from the budget holder.",
             "and reports exceptions to the steering group."]
    sentences, count = [], 0
    while count < words_target:
        s = f"{rnd.choice(subjects)} {rnd.choice(verbs)} {rnd.choice(objects)} {rnd.choice(tails)}"
        sentences.append(s)
        count += len(s.split())
    sentences.insert(int(len(sentences) * 0.7), NEEDLE)
    paras = [" ".join(sentences[i:i + 8]) for i in range(0, len(sentences), 8)]
    return "\n\n".join(paras)


# ---------------------------------------------------------------------------
# The five test cases. Each returns (score 0..1, short note) from a reply.
# ---------------------------------------------------------------------------
def check_number(expected: float):
    def _check(text: str):
        got = extract_answer(text)
        n = to_number(got)
        ok = n is not None and abs(n - expected) < 0.01
        return float(ok), f"answered {got!r}, expected {expected:g}"
    return _check


def check_word(expected: str):
    def _check(text: str):
        got = (extract_answer(text) or "").lower()
        ok = got.split()[0].strip(".,") == expected if got else False
        return float(ok), f"answered {got!r}, expected {expected!r}"
    return _check


def check_contains(needle: str):
    def _check(text: str):
        got = extract_answer(text) or text
        ok = needle.lower() in got.lower()
        return float(ok), f"answered {got[:60]!r}"
    return _check


def make_cases() -> list[dict]:
    def prompt(strategy, q, examples=None):
        return build_prompt(strategy, q, examples)

    sys_cot, p_cot = prompt("cot",
        "A recruitment agency makes 18 placements in March. In April it makes 50% more "
        "placements than in March. In May it makes 6 fewer than in April. Each placement "
        "earns a fee of £1,250. What is the total fee income, in pounds, for March to May?")
    sys_logic, p_logic = prompt("zero-shot",
        "Asha, Ben and Chen each own exactly one pet: a cat, a dog or a parrot, all different. "
        "Asha does not own the dog. Ben owns neither the dog nor the cat. Who owns the cat? "
        "Answer with the name only.")
    sys_fs, p_fs = prompt("few-shot",
        "Ticket: 'I was charged twice for my October subscription, please refund one payment.' "
        "Categories: billing, technical, account, other.", TICKET_EXAMPLES)
    haystack = build_haystack()
    sys_lc = "You answer questions using only the document provided."
    p_lc = (f"<document>\n{haystack}\n</document>\n\nWhat is the internal code name for the "
            "Q3 vendor review? Give your final answer on the last line in the form: ANSWER: <answer>")

    return [
        {"id": "cot-arithmetic", "concept": "Chain-of-Thought", "kind": "text",
         "system": sys_cot, "prompt": p_cot, "check": check_number(82500)},
        {"id": "zero-shot-logic", "concept": "Zero-shot reasoning", "kind": "text",
         "system": sys_logic, "prompt": p_logic, "check": check_word("asha")},
        {"id": "few-shot-classify", "concept": "Few-shot prompting", "kind": "text",
         "system": sys_fs, "prompt": p_fs, "check": check_word("billing")},
        {"id": "json-extraction", "concept": "Structured output (JSON Schema + Pydantic)",
         "kind": "structured", "system": EXTRACT_SYSTEM, "prompt": EXTRACT_PROMPT},
        {"id": "long-context", "concept": f"Context handling (~{len(haystack.split()):,} words)",
         "kind": "text", "system": sys_lc, "prompt": p_lc, "check": check_contains("blue heron")},
    ]


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
def run_case(provider, case: dict) -> dict:
    row = {"provider": provider.name, "model": provider.model, "prompt_id": case["id"]}
    if case["kind"] == "structured":
        result, err = safe(provider.generate_structured, case["prompt"], JobPosting,
                           system=case["system"])
        if err:
            return {**row, "error": err, "accuracy": 0.0, "note": "invalid JSON or call failed"}
        job, resp = result
        acc, checks = score_job(job)
        wrong = [k for k, ok in checks.items() if not ok]
        note = "all fields correct" if not wrong else "wrong: " + ", ".join(wrong)
        text = job.model_dump_json()
    else:
        resp, err = safe(provider.generate, case["prompt"], system=case["system"], temperature=0)
        if err:
            return {**row, "error": err, "accuracy": 0.0, "note": "call failed"}
        acc, note = case["check"](resp.text)
        text = resp.text
    return {**row, "error": None, "accuracy": acc, "note": note,
            "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
            "latency_s": round(resp.latency_s, 3), "cost_usd": resp.cost_usd, "response": text}


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def scale(values: dict[str, float | None], higher_is_better: bool) -> dict[str, float | None]:
    """Min-max scale to 0..1 across providers, 1 = best."""
    known = {k: v for k, v in values.items() if v is not None}
    if not known:
        return {k: None for k in values}
    lo, hi = min(known.values()), max(known.values())
    out = {}
    for k, v in values.items():
        if v is None:
            out[k] = None
        elif hi == lo:
            out[k] = 1.0
        else:
            s = (v - lo) / (hi - lo)
            out[k] = s if higher_is_better else 1 - s
    return out


def fmt_cost(c):
    return "n/a" if c is None else f"${c:.6f}"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def write_report(rows: list[dict], providers, cases, runs: int, mock: bool) -> Path:
    REPORT_DIR.mkdir(exist_ok=True)
    by = defaultdict(list)
    for r in rows:
        by[(r["provider"], r["prompt_id"])].append(r)

    names = [p.name for p in providers]
    summary = {}
    for n in names:
        mine = [r for r in rows if r["provider"] == n]
        ok = [r for r in mine if not r["error"]]
        # accuracy: average of per-prompt means, so each prompt weighs the same
        per_prompt_acc = [mean([r["accuracy"] for r in by[(n, c["id"])]]) for c in cases]
        costs = [r["cost_usd"] for r in ok]
        summary[n] = {
            "model": next(p.model for p in providers if p.name == n),
            "accuracy": mean(per_prompt_acc),
            "latency": mean([r["latency_s"] for r in ok]),
            "cost_per_call": mean(costs) if costs and None not in costs else None,
            "total_cost": sum(costs) if costs and None not in costs else None,
            "in_tok": sum(r["input_tokens"] for r in ok),
            "out_tok": sum(r["output_tokens"] for r in ok),
            "errors": len(mine) - len(ok),
            "calls": len(mine),
        }

    s_acc = scale({n: summary[n]["accuracy"] for n in names}, True)
    s_cost = scale({n: summary[n]["cost_per_call"] for n in names}, False)
    s_lat = scale({n: summary[n]["latency"] for n in names}, False)
    for n in names:
        parts = [(WEIGHTS["accuracy"], s_acc[n]), (WEIGHTS["cost"], s_cost[n]),
                 (WEIGHTS["latency"], s_lat[n])]
        usable = [(w, v) for w, v in parts if v is not None]
        tw = sum(w for w, _ in usable)
        summary[n]["composite"] = sum(w * v for w, v in usable) / tw if tw else None
    ranked = sorted(names, key=lambda n: summary[n]["composite"] or -1, reverse=True)

    L: list[str] = []
    L.append("# Multi-SDK LLM Comparison Report")
    L.append("")
    if mock:
        L.append("> **MOCK RUN — these numbers come from offline fake providers and are "
                 "meaningless. Re-run without `--mock` before submitting.**")
        L.append("")
    L.append(f"Generated {datetime.now():%d %B %Y, %H:%M} · {len(cases)} prompts × "
             f"{len(names)} providers × {runs} run(s) = {len(rows)} calls")
    L.append("")
    L.append("## 1. Set-up")
    L.append("")
    L.append("| Provider | Model | SDK path |")
    L.append("|---|---|---|")
    sdk = {"openai": "OpenAI Responses API", "gemini": "google-genai `generate_content`",
           "claude": "Anthropic Messages API"}
    for n in names:
        L.append(f"| {n} | `{summary[n]['model']}` | {sdk.get(n, 'mock')} |")
    L.append("")
    L.append("Text prompts were sent with temperature 0 where the provider supports it. "
             "Latency is wall-clock time for the full API call from this machine. Cost is "
             "calculated from returned token counts and the per-million-token prices in "
             "`pricing.json`; it shows n/a where no price was entered.")
    L.append("")
    L.append("## 2. Test prompts")
    L.append("")
    L.append("| # | Prompt | Module 1 concept | How it is scored |")
    L.append("|---|---|---|---|")
    how = {"cot-arithmetic": "Final number must equal 82,500",
           "zero-shot-logic": "Final answer must be Asha",
           "few-shot-classify": "Label must be billing",
           "json-extraction": "Valid against schema, then 9 fields checked; score = share correct",
           "long-context": "Answer must contain BLUE HERON"}
    for i, c in enumerate(cases, 1):
        L.append(f"| {i} | `{c['id']}` | {c['concept']} | {how[c['id']]} |")
    L.append("")

    L.append("## 3. Overall results")
    L.append("")
    L.append("| Rank | Provider | Accuracy | Avg latency | Avg cost / call | Total cost | "
             "Tokens in / out | Errors | Composite |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for i, n in enumerate(ranked, 1):
        s = summary[n]
        acc = f"{s['accuracy']:.0%}" if s["accuracy"] is not None else "n/a"
        lat = f"{s['latency']:.2f}s" if s["latency"] is not None else "n/a"
        comp = f"{s['composite']:.2f}" if s["composite"] is not None else "n/a"
        L.append(f"| {i} | {n} | {acc} | {lat} | {fmt_cost(s['cost_per_call'])} | "
                 f"{fmt_cost(s['total_cost'])} | {s['in_tok']:,} / {s['out_tok']:,} | "
                 f"{s['errors']}/{s['calls']} | {comp} |")
    L.append("")
    L.append(f"Composite = {WEIGHTS['accuracy']:.0%} accuracy + {WEIGHTS['cost']:.0%} cost + "
             f"{WEIGHTS['latency']:.0%} latency, each scaled 0–1 across providers (1 = best). "
             "If no prices are set, cost is left out and the weights re-normalise.")
    L.append("")

    L.append("## 4. Results by prompt")
    L.append("")
    for c in cases:
        L.append(f"### {c['id']} — {c['concept']}")
        L.append("")
        L.append("| Provider | Accuracy | Avg latency | Avg cost | Tokens in / out (avg) | Note (last run) |")
        L.append("|---|---|---|---|---|---|")
        for n in names:
            rs = by[(n, c["id"])]
            ok = [r for r in rs if not r["error"]]
            acc = mean([r["accuracy"] for r in rs])
            lat = mean([r["latency_s"] for r in ok])
            costs = [r["cost_usd"] for r in ok]
            cost = mean(costs) if costs and None not in costs else None
            tin = mean([r["input_tokens"] for r in ok])
            tout = mean([r["output_tokens"] for r in ok])
            note = (rs[-1]["error"] or rs[-1]["note"]).replace("|", "/")[:90]
            L.append(f"| {n} | {acc:.0%} | " + (f"{lat:.2f}s" if lat else "—") +
                     f" | {fmt_cost(cost)} | " +
                     (f"{tin:,.0f} / {tout:,.0f}" if tin is not None else "—") + f" | {note} |")
        L.append("")

    L.append("## 5. Observations from the data")
    L.append("")
    valid = [n for n in names if summary[n]["latency"] is not None]
    if valid:
        best_acc = max(valid, key=lambda n: summary[n]["accuracy"] or 0)
        fastest = min(valid, key=lambda n: summary[n]["latency"])
        slowest = max(valid, key=lambda n: summary[n]["latency"])
        L.append(f"- **Most accurate:** {best_acc} ({summary[best_acc]['accuracy']:.0%} across the five prompts).")
        L.append(f"- **Fastest on average:** {fastest} ({summary[fastest]['latency']:.2f}s), "
                 f"against {slowest} at {summary[slowest]['latency']:.2f}s.")
        priced = [n for n in valid if summary[n]["total_cost"] is not None]
        if priced:
            cheap = min(priced, key=lambda n: summary[n]["total_cost"])
            dear = max(priced, key=lambda n: summary[n]["total_cost"])
            L.append(f"- **Cheapest overall:** {cheap} ({fmt_cost(summary[cheap]['total_cost'])} "
                     f"for all calls), against {dear} at {fmt_cost(summary[dear]['total_cost'])}.")
        else:
            L.append("- **Cost:** not compared, as no prices were entered in `pricing.json`.")
        # CoT verbosity
        cot = {n: mean([r["output_tokens"] for r in by[(n, 'cot-arithmetic')] if not r["error"]])
               for n in valid}
        cot = {k: v for k, v in cot.items() if v}
        if len(cot) > 1:
            hi, lo = max(cot, key=cot.get), min(cot, key=cot.get)
            L.append(f"- **Chain-of-Thought verbosity:** on the CoT prompt {hi} used "
                     f"{cot[hi]:,.0f} output tokens on average against {cot[lo]:,.0f} for {lo}. "
                     "Output tokens are the expensive ones, so reasoning style feeds straight into cost.")
        lc = {n: mean([r["input_tokens"] for r in by[(n, 'long-context')] if not r["error"]])
              for n in valid}
        lc = {k: v for k, v in lc.items() if v}
        if lc:
            L.append("- **Tokenisers differ:** the same long-context document counted as " +
                     ", ".join(f"{v:,.0f} input tokens for {k}" for k, v in lc.items()) +
                     ". The same text can therefore cost different amounts before any answer is written.")
        misses = [(n, c["id"]) for n in names for c in cases
                  if mean([r["accuracy"] for r in by[(n, c["id"])]]) < 1]
        if misses:
            L.append("- **Misses:** " + "; ".join(f"{n} on `{cid}`" for n, cid in misses) + ".")
        errs = [n for n in names if summary[n]["errors"]]
        if errs:
            L.append("- **Errors:** " + ", ".join(f"{n} ({summary[n]['errors']})" for n in errs) +
                     ". See `results.csv` for the messages.")
    L.append("")
    L.append("## 6. Interpretation and recommendation")
    L.append("")
    L.append("_Write this section yourself from the tables above. Suggested points: which "
             "provider you would choose for which job (reasoning, extraction, long documents, "
             "high volume), where the accuracy differences actually mattered, how stable "
             "latency was across runs, and what the abstraction layer made easy or hard._")
    L.append("")
    L.append("## 7. Limitations")
    L.append("")
    L.append(f"- Five prompts and {runs} run(s) per prompt is a small sample; one wrong answer "
             "moves accuracy by 20 points.")
    L.append("- Latency depends on network, region and provider load at the time of the run.")
    L.append("- Results apply to the specific model versions listed in section 1, not to each "
             "provider's whole range.")
    L.append("- Some checks are strict on format (for example, the final `ANSWER:` line), so a "
             "correct answer in the wrong format scores zero. That is deliberate: format "
             "reliability is part of what is being compared.")
    L.append("")
    L.append("Raw data: `reports/results.csv` and `reports/responses.jsonl`.")

    path = REPORT_DIR / "comparison_report.md"
    path.write_text("\n".join(L))
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--providers")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()

    providers = available_providers(args.providers.split(",") if args.providers else None)
    cases = make_cases()
    rows: list[dict] = []
    total = len(cases) * len(providers) * args.runs
    i = 0
    for run in range(1, args.runs + 1):
        for c in cases:
            for p in providers:
                i += 1
                r = run_case(p, c)
                r["run"] = run
                rows.append(r)
                status = "ERR" if r["error"] else f"{r['accuracy']:.0%}"
                print(f"[{i:>3}/{total}] run {run} {c['id']:<18}{p.name:<14}{status:>5}  "
                      f"{r.get('latency_s', 0) or 0:.2f}s  {r['note'][:50]}")

    REPORT_DIR.mkdir(exist_ok=True)
    fields = ["run", "provider", "model", "prompt_id", "accuracy", "latency_s", "input_tokens",
              "output_tokens", "cost_usd", "note", "error"]
    with (REPORT_DIR / "results.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with (REPORT_DIR / "responses.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    path = write_report(rows, providers, cases, args.runs, mock_mode())
    print(f"\nReport written to {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
