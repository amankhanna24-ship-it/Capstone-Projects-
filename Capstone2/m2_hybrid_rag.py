"""
m2_hybrid_rag.py — hybrid retrieval (BM25 + semantic) fused with RRF, then cross-encoder rerank.

    # one question, default pipeline: BM25 top-50 + semantic top-50 -> RRF -> Cohere rerank -> top-5
    python m2_hybrid_rag.py "What happened in INC-4821?"

    # see every stage side by side (semantic vs BM25 vs hybrid vs hybrid+rerank)
    python m2_hybrid_rag.py "Can I work from abroad for a few weeks?" --compare

    # advanced modes
    python m2_hybrid_rag.py "dodgy link in an email" --multi-query      # LLM rewrites + RRF over all lists
    python m2_hybrid_rag.py "promote postgres replica" --hyde           # embed a hypothetical answer

    # interactive chat with conversation memory (type /help inside)
    python m2_hybrid_rag.py

Two-stage retrieval
    stage 1 (recall)    bi-encoder + BM25, cheap, top-50 candidates each, fused with RRF
    stage 2 (precision) cross-encoder reads (question, chunk) pairs together, keeps top-5
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field, replace

from langsmith import traceable

from kb_common import (
    Hit,
    Timer,
    allowed_ids,
    answer_with_citations,
    audit_log,
    build_where,
    current_trace_id,
    get_bm25,
    hits_summary,
    hits_to_trace,
    llm_text,
    OFFLINE,
    print_answer,
    print_hits,
    rerank,
    rrf_fuse,
    semantic_search,
)


@dataclass
class RetrievalConfig:
    mode: str = "hybrid"  # semantic | bm25 | hybrid
    k_candidates: int = 50  # stage-1 depth per retriever
    top_n: int = 5  # what the LLM finally sees
    rerank: bool = True
    multi_query: bool = False
    n_queries: int = 3
    hyde: bool = False
    rrf_weights: dict[str, float] = field(default_factory=dict)  # e.g. {"bm25": 1.0, "semantic": 1.2}
    where: dict | None = None  # Chroma metadata filter, also applied to BM25

    def name(self) -> str:
        parts = [self.mode]
        if self.multi_query:
            parts.append("multiquery")
        if self.hyde:
            parts.append("hyde")
        if self.rerank:
            parts.append("rerank")
        return "+".join(parts)


# --------------------------------------------------------------------------
# Query transformations
# --------------------------------------------------------------------------
MULTI_QUERY_SYSTEM = """You rewrite search queries for an internal company knowledge base
(policies, contracts, IT runbooks, incident tickets). Produce {n} alternative phrasings of the
user's question that would help find the answer: use synonyms, formal policy wording, and
expand abbreviations. Keep any IDs (e.g. INC-4821, RB-DB-003) exactly as written.
Return one query per line, no numbering, nothing else."""

HYDE_SYSTEM = """Write a short passage (3-4 sentences) that could plausibly appear in a company
policy, contract, runbook or incident ticket and that answers the question. Invent plausible
details if needed — this text is only used to search, never shown to the user."""

CONDENSE_SYSTEM = """Given a conversation and a follow-up question, rewrite the follow-up as a
standalone question that contains all context needed to search for it. Return only the question."""


@traceable(run_type="chain", name="multi_query_rewrite")
def generate_queries(question: str, n: int = 3) -> list[str]:
    if OFFLINE:
        return []
    raw = llm_text(MULTI_QUERY_SYSTEM.format(n=n), question, temperature=0.3)
    qs = [q.strip(" -•\t") for q in raw.splitlines() if q.strip()]
    return [q for q in qs if q.lower() != question.lower()][:n]


@traceable(run_type="chain", name="hyde_generate")
def hyde_document(question: str) -> str:
    return llm_text(HYDE_SYSTEM, question, temperature=0.2)


@traceable(run_type="chain", name="condense_question")
def condense(question: str, history: list[tuple[str, str]]) -> str:
    if not history or OFFLINE:
        return question
    convo = "\n".join(f"User: {q}\nAssistant: {a[:400]}" for q, a in history[-3:])
    return llm_text(CONDENSE_SYSTEM, f"Conversation:\n{convo}\n\nFollow-up: {question}").strip()


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------
@traceable(run_type="retriever", name="retrieve", process_outputs=hits_to_trace)
def retrieve(question: str, cfg: RetrievalConfig) -> list[Hit]:
    queries = [question]
    if cfg.multi_query:
        queries += generate_queries(question, cfg.n_queries)

    allowed = allowed_ids(cfg.where)  # BM25 must respect the same filter as Chroma
    if allowed is not None and not allowed:
        return []  # filter excludes everything

    ranked: dict[str, list[Hit]] = {}
    for i, q in enumerate(queries):
        suffix = "" if i == 0 else f":q{i}"
        if cfg.mode in ("bm25", "hybrid"):
            ranked[f"bm25{suffix}"] = get_bm25().search(q, cfg.k_candidates, allowed, label=f"bm25{suffix}")
        if cfg.mode in ("semantic", "hybrid"):
            embed_text = hyde_document(q) if (cfg.hyde and i == 0) else None
            ranked[f"semantic{suffix}"] = semantic_search(
                q, cfg.k_candidates, cfg.where, embed_text=embed_text, label=f"semantic{suffix}"
            )

    if len(ranked) == 1:
        candidates = next(iter(ranked.values()))
    else:
        weights = {
            name: cfg.rrf_weights.get(name.split(":")[0], 1.0) for name in ranked
        }  # same weight for every rewrite of a retriever
        candidates = rrf_fuse(ranked, weights=weights)[: cfg.k_candidates]

    if cfg.rerank:
        return rerank(question, candidates, top_n=cfg.top_n)
    return candidates[: cfg.top_n]


# --------------------------------------------------------------------------
# One chat turn: condense -> retrieve -> answer -> audit
# --------------------------------------------------------------------------
@traceable(run_type="chain", name="kb_chat_turn")
def ask(question: str, cfg: RetrievalConfig, history: list[tuple[str, str]] | None = None) -> dict:
    standalone = condense(question, history or [])
    with Timer() as t_ret:
        hits = retrieve(standalone, cfg)
    with Timer() as t_gen:
        result = answer_with_citations(standalone, hits)
    result.update(
        {
            "question": question,
            "standalone_question": standalone,
            "hits": hits,
            "retrieval_ms": round(t_ret.ms),
            "generation_ms": round(t_gen.ms),
        }
    )
    audit_log(
        {
            "question": question,
            "standalone_question": standalone,
            "pipeline": cfg.name(),
            "filter": cfg.where,
            "retrieved": hits_summary(hits),
            "answer": result["answer"],
            "citations": result["citations"],
            "invalid_citations": result["invalid_citations"],
            "retrieval_ms": result["retrieval_ms"],
            "generation_ms": result["generation_ms"],
            "langsmith_trace_id": current_trace_id(),
        }
    )
    return result


def run_ask(question: str, cfg: RetrievalConfig, history=None) -> dict:
    """Call ask() with LangSmith tags/metadata so runs can be grouped on a dashboard."""
    return ask(
        question,
        cfg,
        history,
        langsmith_extra={"tags": ["kb-chatbot", cfg.name()], "metadata": {"pipeline": cfg.name(), "filter": cfg.where}},
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def compare(question: str, base: RetrievalConfig) -> None:
    """Show what each stage contributes for one question."""
    variants = [
        replace(base, mode="semantic", rerank=False, multi_query=False, hyde=False),
        replace(base, mode="bm25", rerank=False, multi_query=False, hyde=False),
        replace(base, mode="hybrid", rerank=False, multi_query=False, hyde=False),
        replace(base, mode="hybrid", rerank=True, multi_query=False, hyde=False),
        replace(base, mode="hybrid", rerank=True, multi_query=True, hyde=False),
    ]
    print(f"\nQ: {question}")
    for v in variants:
        with Timer() as t:
            hits = retrieve(question, v)
        print(f"\n{v.name():<28} {t.ms:7.0f} ms   ->  " + ", ".join(h.doc_id for h in hits))
        for h in hits[:3]:
            print(f"      {h.label()[:72]}   ranks={h.ranks}")


def chat(cfg: RetrievalConfig) -> None:
    print("Knowledge-base chat. Commands: /mode semantic|bm25|hybrid, /rerank on|off, /mq on|off, "
          "/hyde on|off, /sources, /reset, /quit")
    history: list[tuple[str, str]] = []
    last: dict | None = None
    while True:
        try:
            q = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            continue
        if q.startswith("/"):
            cmd, *arg = q.split()
            val = arg[0] if arg else ""
            if cmd == "/quit":
                break
            elif cmd == "/reset":
                history.clear()
                print("memory cleared")
            elif cmd == "/mode" and val in ("semantic", "bm25", "hybrid"):
                cfg.mode = val
            elif cmd == "/rerank":
                cfg.rerank = val == "on"
            elif cmd == "/mq":
                cfg.multi_query = val == "on"
            elif cmd == "/hyde":
                cfg.hyde = val == "on"
            elif cmd == "/sources" and last:
                print_hits(last["hits"], "Context passages used")
            print(f"pipeline = {cfg.name()}")
            continue
        last = run_ask(q, cfg, history)
        if last["standalone_question"] != q:
            print(f"(searched for: {last['standalone_question']})")
        print_answer(last)
        print(f"retrieval {last['retrieval_ms']} ms · generation {last['generation_ms']} ms")
        history.append((q, last["answer"]))


def config_from_args(a: argparse.Namespace) -> RetrievalConfig:
    return RetrievalConfig(
        mode=a.mode,
        k_candidates=a.k,
        top_n=a.top_n,
        rerank=not a.no_rerank,
        multi_query=a.multi_query,
        hyde=a.hyde,
        where=build_where(department=a.department, doc_type=a.doc_type, latest_only=a.latest_only),
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question", nargs="?", help="omit for interactive chat")
    ap.add_argument("--mode", default="hybrid", choices=["semantic", "bm25", "hybrid"])
    ap.add_argument("--k", type=int, default=50, help="stage-1 candidates per retriever")
    ap.add_argument("--top-n", type=int, default=5, help="chunks passed to the LLM")
    ap.add_argument("--no-rerank", action="store_true")
    ap.add_argument("--multi-query", action="store_true")
    ap.add_argument("--hyde", action="store_true")
    ap.add_argument("--department")
    ap.add_argument("--doc-type")
    ap.add_argument("--latest-only", action="store_true", help="ignore superseded document versions")
    ap.add_argument("--compare", action="store_true", help="show each retrieval stage side by side")
    ap.add_argument("--show-context", action="store_true", help="print the passages sent to the LLM")
    a = ap.parse_args()
    cfg = config_from_args(a)

    if a.question and a.compare:
        compare(a.question, cfg)
    elif a.question:
        res = run_ask(a.question, cfg)
        if a.show_context:
            print_hits(res["hits"], f"Context ({cfg.name()})")
        print_answer(res)
        print(f"pipeline {cfg.name()} · retrieval {res['retrieval_ms']} ms · generation {res['generation_ms']} ms")
    else:
        chat(cfg)
