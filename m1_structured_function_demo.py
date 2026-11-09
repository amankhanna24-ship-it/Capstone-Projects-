"""
m1_structured_function_demo.py — structured JSON output and function calling.

Part A — Structured output
  A Pydantic model (JobPosting) is turned into a JSON Schema and sent to each
  provider using its own native mechanism:
      OpenAI  -> text.format = json_schema (strict)
      Gemini  -> response_mime_type + response_json_schema
      Claude  -> output_config.format = json_schema
  The reply is then validated with Pydantic. If validation fails we retry once
  with the error message. Each result is also checked field by field against
  the known correct values.

Part B — Function calling
  One tool (convert_currency) is defined once and handed to all three
  providers. The dispatch loop in llm_core.run_tools() runs it whenever the
  model asks, sends the result back, and repeats until the model answers.

Usage
  python m1_structured_function_demo.py            # both parts
  python m1_structured_function_demo.py --part a   # structured only
  python m1_structured_function_demo.py --part b   # tools only
  python m1_structured_function_demo.py --mock
"""

from __future__ import annotations

import argparse
import json
from typing import Literal, Optional

from pydantic import BaseModel, Field

from llm_core import Tool, available_providers, safe, strict_schema


# ===========================================================================
# Part A — the schema
# ===========================================================================
class JobPosting(BaseModel):
    title: str = Field(description="Job title exactly as advertised")
    company: str
    location: str = Field(description="City or region")
    remote_policy: Literal["remote", "hybrid", "onsite"]
    salary_min: Optional[int] = Field(description="Annual, whole currency units; null if absent")
    salary_max: Optional[int] = Field(description="Annual, whole currency units; null if absent")
    currency: str = Field(description="ISO 4217 code, e.g. GBP")
    years_experience: Optional[int] = Field(description="Minimum years required; null if absent")
    skills: list[str] = Field(description="Technical skills named in the advert")


JOB_AD = """\
Brightwave Analytics is hiring a Senior Data Engineer to join our Manchester office.
We work hybrid, with three days a week on site. You'll need at least 5 years'
experience building data pipelines, strong Python and SQL, and hands-on experience
with Airflow and Snowflake. Salary £70,000–£85,000 plus bonus. Apply by 30 November."""

EXTRACT_PROMPT = f"Extract the job details from this advert.\n\n{JOB_AD}"
EXTRACT_SYSTEM = "You extract structured data from job adverts. Use only facts stated in the text."

EXPECTED_SKILLS = {"python", "sql", "airflow", "snowflake"}


def score_job(job: JobPosting) -> tuple[float, dict[str, bool]]:
    """Field-by-field check against the known right answers. Returns (0..1, detail)."""
    skills = {s.lower().strip() for s in job.skills}
    checks = {
        "title": job.title.strip().lower() == "senior data engineer",
        "company": job.company.strip().lower() == "brightwave analytics",
        "location": "manchester" in job.location.lower(),
        "remote_policy": job.remote_policy == "hybrid",
        "salary_min": job.salary_min == 70000,
        "salary_max": job.salary_max == 85000,
        "currency": job.currency.upper() == "GBP",
        "years_experience": job.years_experience == 5,
        "skills": EXPECTED_SKILLS.issubset(skills),
    }
    return sum(checks.values()) / len(checks), checks


def part_a(providers) -> None:
    print("PART A — structured output with JSON Schema + Pydantic")
    print("Schema sent to every provider:")
    print(json.dumps(strict_schema(JobPosting), indent=2)[:900], "...\n")
    for p in providers:
        result, err = safe(p.generate_structured, EXTRACT_PROMPT, JobPosting, system=EXTRACT_SYSTEM)
        print("─" * 80)
        if err:
            print(f"[{p.name}] FAILED validation or call: {err}")
            continue
        job, resp = result
        score, checks = score_job(job)
        print(resp.summary())
        print(job.model_dump_json(indent=2))
        wrong = [k for k, ok in checks.items() if not ok]
        print(f"field accuracy: {score:.0%}" + (f"   wrong: {', '.join(wrong)}" if wrong else ""))
    print()


# ===========================================================================
# Part B — one tool and the dispatch loop
# ===========================================================================
# Fixed demo rates so results are reproducible. Not live market rates.
DEMO_RATES_PER_GBP = {"GBP": 1.0, "EUR": 1.17, "USD": 1.30, "INR": 112.0}


def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    f, t = from_currency.upper(), to_currency.upper()
    if f not in DEMO_RATES_PER_GBP or t not in DEMO_RATES_PER_GBP:
        raise ValueError(f"unsupported currency; use one of {list(DEMO_RATES_PER_GBP)}")
    converted = amount / DEMO_RATES_PER_GBP[f] * DEMO_RATES_PER_GBP[t]
    return {"amount": amount, "from": f, "to": t, "converted": round(converted, 2),
            "note": "fixed demo rates"}


CURRENCY_TOOL = Tool(
    name="convert_currency",
    description="Convert an amount between GBP, EUR, USD and INR using the company's reference rates.",
    parameters={
        "type": "object",
        "properties": {
            "amount": {"type": "number", "description": "Amount in the source currency"},
            "from_currency": {"type": "string", "description": "ISO code, e.g. INR"},
            "to_currency": {"type": "string", "description": "ISO code, e.g. GBP"},
        },
        "required": ["amount", "from_currency", "to_currency"],
        "additionalProperties": False,
    },
    function=convert_currency,
)

TOOL_PROMPT = ("A candidate in Bangalore is asking for ₹28,00,000 a year. Our UK salary band "
               "for the role is £24,000 to £30,000. Convert the ask to GBP using the reference "
               "rates and tell me in two sentences whether it fits the band.")
TOOL_SYSTEM = "You are a recruitment assistant. Always use the tool for currency conversion; never estimate rates."
TOOL_EXPECTED_GBP = 25000.0   # 2,800,000 / 112


def part_b(providers) -> None:
    print("PART B — function calling: one tool, one dispatch loop, three SDKs")
    print(f"prompt: {TOOL_PROMPT}\n")
    for p in providers:
        resp, err = safe(p.run_tools, TOOL_PROMPT, [CURRENCY_TOOL], system=TOOL_SYSTEM)
        print("─" * 80)
        if err:
            print(f"[{p.name}] ERROR {err}")
            continue
        print(resp.summary())
        for i, step in enumerate(resp.tool_trace, 1):
            print(f"  tool call {i}: {step['tool']}({json.dumps(step['args'])})")
            print(f"           -> {json.dumps(step['result'])}")
        if not resp.tool_trace:
            print("  (model answered without calling the tool)")
        right_args = any(
            isinstance(s["result"], dict) and abs(s["result"].get("converted", 0) - TOOL_EXPECTED_GBP) < 1
            for s in resp.tool_trace)
        print(f"  correct conversion via tool: {'yes' if right_args else 'no'}")
        print(f"  final answer: {resp.text.strip()}")
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["a", "b", "both"], default="both")
    ap.add_argument("--providers")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()
    providers = available_providers(args.providers.split(",") if args.providers else None)
    if args.part in ("a", "both"):
        part_a(providers)
    if args.part in ("b", "both"):
        part_b(providers)


if __name__ == "__main__":
    main()
