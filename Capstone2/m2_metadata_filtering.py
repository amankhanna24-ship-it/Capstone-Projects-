"""
m2_metadata_filtering.py — precision retrieval with metadata filters.

    python m2_metadata_filtering.py --demo                     # run every scenario below
    python m2_metadata_filtering.py "hotel cap in London" --as-of 2025-06-01
    python m2_metadata_filtering.py "Acme uptime" --user arjun   # tenant-aware: IT user, no Legal docs
    python m2_metadata_filtering.py "P1 database incidents in 2026" --self-query

Filters (all pushed down into Chroma's `where` AND applied to BM25, so both legs agree):
    --department HR|Finance|IT|Legal      tenant / ownership
    --doc-type policy|contract|runbook|faq|ticket
    --date-from / --date-to YYYY-MM-DD    effective-date window (e.g. tickets opened in Q1)
    --as-of YYYY-MM-DD                    the version that was IN FORCE on that day
    --latest-only                         only the current version of each document
    --user NAME                           simulated SSO identity from data/users.json:
                                          sees 'company' docs + its own departments' docs
    --self-query                          let the LLM extract filters from the question itself

Why it matters: the expense policy exists in two versions. Without a filter the retriever
happily mixes the 2024 hotel cap (GBP 150) with the 2026 one (GBP 180). With `--latest-only`
or `--as-of` the answer is precise and auditable.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Literal, Optional

from langsmith import traceable
from pydantic import BaseModel, Field

from kb_common import DATA_DIR, OFFLINE, build_where, get_llm, print_answer, print_hits
from m2_hybrid_rag import RetrievalConfig, retrieve, run_ask

DEPARTMENTS = ["HR", "Finance", "IT", "Legal"]
DOC_TYPES = ["policy", "contract", "runbook", "faq", "ticket", "web"]


# --------------------------------------------------------------------------
# Tenant-aware access filter
# --------------------------------------------------------------------------
def load_users() -> dict:
    return json.loads((DATA_DIR / "users.json").read_text(encoding="utf-8"))["users"]


def tenant_clause(user: str) -> dict:
    """Company-wide documents OR documents owned by one of the user's departments.

    This clause is ALWAYS added on top of whatever the user asks for, so a user
    cannot widen their own access by passing --department.
    """
    users = load_users()
    if user not in users:
        raise SystemExit(f"Unknown user '{user}'. Known: {', '.join(users)}")
    depts = users[user]["departments"]
    dept_clause = {"department": depts[0]} if len(depts) == 1 else {"department": {"$in": depts}}
    return {"$or": [{"visibility": "company"}, dept_clause]}


# --------------------------------------------------------------------------
# Self-query: LLM turns natural language into a structured filter
# --------------------------------------------------------------------------
class SearchSpec(BaseModel):
    """Structured search request extracted from a user question."""

    query: str = Field(description="The question rewritten without the filter words, for semantic/keyword search")
    department: Optional[Literal["HR", "Finance", "IT", "Legal"]] = Field(None, description="Owning department if stated or obvious")
    doc_type: Optional[Literal["policy", "contract", "runbook", "faq", "ticket"]] = Field(None, description="Document type if stated or obvious (incidents = ticket)")
    date_from: Optional[str] = Field(None, description="YYYY-MM-DD lower bound on the document/ticket date, only if a period is mentioned")
    date_to: Optional[str] = Field(None, description="YYYY-MM-DD upper bound, only if a period is mentioned")
    as_of: Optional[str] = Field(None, description="YYYY-MM-DD if the user asks which rule applied on a specific past date")


@traceable(run_type="chain", name="self_query_extract")
def extract_filters(question: str) -> SearchSpec:
    if OFFLINE:
        return SearchSpec(query=question)
    llm = get_llm().with_structured_output(SearchSpec)
    prompt = (
        f"Today is {date.today().isoformat()}. Extract search filters from this question about the company "
        f"knowledge base. Only set a filter when the question clearly implies it.\n\nQuestion: {question}"
    )
    spec: SearchSpec = llm.invoke(prompt)
    # validate dates: a bad date must not silently become "no filter"
    for fld in ("date_from", "date_to", "as_of"):
        val = getattr(spec, fld)
        if val:
            try:
                date.fromisoformat(val)
            except ValueError:
                setattr(spec, fld, None)
    return spec


# --------------------------------------------------------------------------
# Build the filter for one request
# --------------------------------------------------------------------------
def make_where(department=None, doc_type=None, date_from=None, date_to=None, as_of=None,
               latest_only=False, user=None) -> dict | None:
    return build_where(
        department=department,
        doc_type=doc_type,
        date_from=date_from,
        date_to=date_to,
        as_of=as_of,
        latest_only=latest_only,
        extra=tenant_clause(user) if user else None,
    )


def show(title: str, question: str, where: dict | None, answer: bool = True) -> None:
    print("\n" + "#" * 78)
    print(f"# {title}")
    print(f"# Q: {question}")
    print(f"# where = {json.dumps(where)}")
    cfg = RetrievalConfig(where=where)
    if answer:
        res = run_ask(question, cfg)
        print_hits(res["hits"], "Context passages")
        print_answer(res)
    else:
        print_hits(retrieve(question, cfg), "Retrieved")


# --------------------------------------------------------------------------
# Demo scenarios
# --------------------------------------------------------------------------
def demo() -> None:
    q = "What is the maximum hotel rate per night in London?"
    show("1a. No filter — both policy versions compete", q, None)
    show("1b. latest_only — current version only", q, make_where(latest_only=True))
    show("1c. as_of 2025-06-01 — the rule that applied last year", q, make_where(as_of="2025-06-01"))

    q = "How much notice is needed to terminate?"
    show("2a. Ambiguous question, no filter", q, None, answer=False)
    show("2b. Department = Legal (contracts only)", q, make_where(department="Legal"), answer=False)

    q = "VPN error 809"
    show("3a. doc_type = runbook (how to fix)", q, make_where(doc_type="runbook"), answer=False)
    show("3b. doc_type = ticket (what happened before)", q, make_where(doc_type="ticket"), answer=False)

    q = "database outage"
    show("4. Date window: tickets opened in H1 2026",
         q, make_where(doc_type="ticket", date_from="2026-01-01", date_to="2026-06-30"), answer=False)

    q = "What uptime does Acme Cloud guarantee?"
    show("5a. Tenant-aware: user 'arjun' (IT) cannot see Legal contracts", q, make_where(user="arjun"))
    show("5b. Tenant-aware: user 'meera' (Legal)", q, make_where(user="meera"))

    q = "Show me P1 or P2 database incidents from the first half of 2026"
    spec = extract_filters(q)
    print("\n" + "#" * 78)
    print(f"# 6. Self-query extraction\n# Q: {q}\n# LLM extracted: {spec.model_dump(exclude_none=True)}")
    show("6. Self-query result", spec.query,
         make_where(spec.department, spec.doc_type, spec.date_from, spec.date_to, spec.as_of), answer=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question", nargs="?")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--department", choices=DEPARTMENTS)
    ap.add_argument("--doc-type", choices=DOC_TYPES)
    ap.add_argument("--date-from")
    ap.add_argument("--date-to")
    ap.add_argument("--as-of")
    ap.add_argument("--latest-only", action="store_true")
    ap.add_argument("--user", help="simulated identity from data/users.json")
    ap.add_argument("--self-query", action="store_true", help="LLM extracts filters from the question")
    a = ap.parse_args()

    if a.demo or not a.question:
        demo()
    else:
        question = a.question
        dept, dtype, dfrom, dto, asof = a.department, a.doc_type, a.date_from, a.date_to, a.as_of
        if a.self_query:
            spec = extract_filters(question)
            print(f"self-query -> {spec.model_dump(exclude_none=True)}")
            question = spec.query
            dept, dtype = dept or spec.department, dtype or spec.doc_type
            dfrom, dto, asof = dfrom or spec.date_from, dto or spec.date_to, asof or spec.as_of
        show("Filtered query", question, make_where(dept, dtype, dfrom, dto, asof, a.latest_only, a.user))
