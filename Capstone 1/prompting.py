"""
prompting.py — the prompt-strategy switcher.

The same task can be asked three ways:

  zero-shot  just the question
  few-shot   a handful of worked examples first, so the model copies the pattern
  cot        "Chain-of-Thought": ask the model to reason step by step before answering

Every strategy asks for the final answer on a last line "ANSWER: ...",
so we can pull it out and check it automatically, whichever provider answered.
"""

from __future__ import annotations

import re

STRATEGIES = ("zero-shot", "few-shot", "cot")

ANSWER_RULE = "Give your final answer on the last line in the form: ANSWER: <answer>"

# Generic examples used when a task doesn't bring its own.
DEFAULT_EXAMPLES = [
    ("A team of 4 reviews 6 CVs each per day. How many CVs do they review in 5 days?",
     "4 x 6 = 24 per day; 24 x 5 = 120.\nANSWER: 120"),
    ("A contract runs from 1 March to 31 May inclusive. How many months is that?",
     "March, April, May.\nANSWER: 3"),
]

SYSTEM_PROMPTS = {
    "zero-shot": "You are a precise assistant. Answer directly and briefly.",
    "few-shot": "You are a precise assistant. Follow the format of the examples exactly.",
    "cot": "You are a careful analyst. Reason step by step before committing to an answer.",
}


def build_prompt(strategy: str, question: str,
                 examples: list[tuple[str, str]] | None = None) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the chosen strategy."""
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of {STRATEGIES}")

    if strategy == "zero-shot":
        user = f"{question}\n\n{ANSWER_RULE}"

    elif strategy == "few-shot":
        shots = examples or DEFAULT_EXAMPLES
        demo = "\n\n".join(f"Q: {q}\nA: {a}" for q, a in shots)
        user = f"Here are some examples.\n\n{demo}\n\nNow answer this one.\n\nQ: {question}\nA:"

    else:  # cot
        user = (f"{question}\n\nWork through this step by step. Number your steps, "
                f"check your working, then stop.\n{ANSWER_RULE}")

    return SYSTEM_PROMPTS[strategy], user


def extract_answer(text: str) -> str | None:
    """Pull out the text after the last 'ANSWER:'. Returns None if absent."""
    hits = re.findall(r"ANSWER:\s*(.+)", text or "", flags=re.IGNORECASE)
    if not hits:
        return None
    return hits[-1].strip().strip("*`. ").strip()


def to_number(s: str | None) -> float | None:
    """'£82,500.00' -> 82500.0. Returns None if no number is found."""
    if not s:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", s)
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None
