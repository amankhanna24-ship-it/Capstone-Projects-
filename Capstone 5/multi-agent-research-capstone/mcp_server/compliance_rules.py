"""
compliance_rules.py - a rule book the Compliance Checker agent uses.

WHY RULES AND NOT JUST AN LLM?
------------------------------
LLMs are great at judgement but can be inconsistent. Compliance needs some
checks that ALWAYS give the same answer - for example "does the note contain
a disclaimer?". Those are simple, predictable Python checks. The Compliance
Checker agent combines these hard rules with its own judgement.

This is a common pattern in real AI systems: "deterministic guardrails + LLM
reasoning". It also makes the system easier to audit, because a reviewer can
read exactly what the rules are.

NOTE: These rules are a teaching example inspired by general principles for
fair, balanced investment communications. They are NOT a complete legal or
regulatory rule set.
"""

from __future__ import annotations

import re

# Phrases that promise outcomes nobody can promise.
PROHIBITED_PHRASES = [
    "guaranteed return", "guaranteed profit", "risk-free", "risk free",
    "can't lose", "cannot lose", "sure thing", "no downside",
    "will definitely", "certain to rise", "100% safe", "get rich",
]

# Words that sound too absolute. Not banned, but flagged as a warning.
ABSOLUTE_WORDS = ["always", "never", "certainly", "undoubtedly", "definitely"]

# The note must contain at least one of these, so readers know it is not advice.
DISCLAIMER_MARKERS = ["not investment advice", "not financial advice",
                      "for educational purposes", "for informational purposes"]

# Words showing that risks are discussed (balance check).
RISK_MARKERS = ["risk", "downside", "uncertain", "volatil", "could fall", "headwind"]

# A citation looks like [1], [2] ... or a web link.
CITATION_PATTERN = re.compile(r"\[\d+\]|https?://|local://sample-data")


def run_compliance_checks(text: str) -> dict:
    """
    Check a draft research note and return a structured verdict.

    Returns a dictionary like:
        {"passed": False,
         "issues":   ["BLOCKER: ...", ...],   # must be fixed
         "warnings": ["WARNING: ...", ...],   # should be looked at
         "checks_run": [...]}
    """
    lower = text.lower()
    issues: list[str] = []
    warnings: list[str] = []

    # Rule 1 - no promises of returns
    for phrase in PROHIBITED_PHRASES:
        if phrase in lower:
            issues.append(f"BLOCKER: prohibited promissory phrase found: '{phrase}'.")

    # Rule 2 - must carry a disclaimer
    if not any(marker in lower for marker in DISCLAIMER_MARKERS):
        issues.append("BLOCKER: no disclaimer. Add 'This note is for educational purposes "
                      "only and is not investment advice.'")

    # Rule 3 - must cite sources
    citations = CITATION_PATTERN.findall(text)
    if len(citations) < 2:
        issues.append(f"BLOCKER: only {len(citations)} citation(s) found. Every key figure "
                      "needs a numbered source like [1].")

    # Rule 4 - must discuss risks (a balanced view)
    if not any(marker in lower for marker in RISK_MARKERS):
        issues.append("BLOCKER: the note does not discuss risks or downside.")

    # Rule 5 - sample data must be disclosed
    if "local://sample-data" in lower and "sample data" not in lower.replace("local://sample-data", ""):
        issues.append("BLOCKER: the note uses sample data but does not say so in plain words.")

    # Warning - over-confident language
    found_absolute = sorted({w for w in ABSOLUTE_WORDS if re.search(rf"\b{w}\b", lower)})
    if found_absolute:
        warnings.append(f"WARNING: absolute language used ({', '.join(found_absolute)}). "
                        "Prefer 'may', 'could', 'suggests'.")

    # Warning - personal recommendation wording
    if re.search(r"\byou should (buy|sell)\b", lower):
        warnings.append("WARNING: personal recommendation wording ('you should buy/sell'). "
                        "Use a neutral rating such as 'Positive / Neutral / Cautious'.")

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "citations_found": len(citations),
        "checks_run": ["prohibited_phrases", "disclaimer", "citations",
                       "risk_balance", "sample_data_disclosure",
                       "absolute_language", "personal_recommendation"],
    }
