"""
m2_eval_langsmith.py — measure precision, recall, MRR and latency for every retrieval
pipeline, locally and as LangSmith experiments; then replay the failures.

    python m2_eval_langsmith.py                         # local table for all pipelines
    python m2_eval_langsmith.py --pipelines hybrid_rrf hybrid_rrf_rerank
    python m2_eval_langsmith.py --langsmith             # also upload dataset + run experiments
    python m2_eval_langsmith.py --langsmith --with-answers   # + answer generation & citation checks
    python m2_eval_langsmith.py --replay results/failures.jsonl   # explain each failure stage by stage

Golden set: data/eval/golden.jsonl  -> {"question", "relevant_doc_ids": [...], "kind"}
Relevance is judged at document level: a retrieved chunk counts as relevant when its
doc_id (or, for RAPTOR summaries, any of its doc_ids) is in relevant_doc_ids.

Metrics (k = top_n, default 5)
    precision@k  share of the k chunks that come from a relevant document
    recall@k     share of the relevant documents that appear in the k chunks
    mrr          1 / rank of the first relevant chunk (0 if none)
    latency_ms   wall-clock retrieval time (LangSmith also records it per trace)
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from langsmith import traceable

from kb_common import (
    DATA_DIR,
    RESULTS_DIR,
    Hit,
    Timer,
    answer_with_citations,
    current_trace_id,
    get_bm25,
    rerank,
    rrf_fuse,
    semantic_search,
)
from m2_hybrid_rag import RetrievalConfig, retrieve

GOLDEN = DATA_DIR / "eval" / "golden.jsonl"
DATASET_NAME = "m2-kb-chatbot-golden"
TOP_N = 5

PIPELINES: dict[str, RetrievalConfig | str] = {
    "semantic": RetrievalConfig(mode="semantic", rerank=False),
    "bm25": RetrievalConfig(mode="bm25", rerank=False),
    "hybrid_rrf": RetrievalConfig(mode="hybrid", rerank=False),
    "hybrid_rrf_rerank": RetrievalConfig(mode="hybrid", rerank=True),
    "multiquery_rerank": RetrievalConfig(mode="hybrid", rerank=True, multi_query=True),
    "hyde_rerank": RetrievalConfig(mode="hybrid", rerank=True, hyde=True),
    "raptor_collapsed": "raptor",
}


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------
def hit_doc_ids(h: Hit) -> set[str]:
    ids = h.metadata.get("doc_ids") or h.metadata.get("doc_id", "")
    return {d for d in str(ids).split(",") if d}


def score(hits: list[Hit], relevant: list[str], k: int = TOP_N) -> dict:
    rel = set(relevant)
    top = hits[:k]
    flags = [bool(hit_doc_ids(h) & rel) for h in top]
    found = set().union(*(hit_doc_ids(h) for h in top)) & rel if top else set()
    first = next((i for i, f in enumerate(flags, start=1) if f), None)
    return {
        "precision": sum(flags) / len(top) if top else 0.0,
        "recall": len(found) / len(rel) if rel else 0.0,
        "mrr": 1.0 / first if first else 0.0,
    }


# --------------------------------------------------------------------------
# Running a pipeline
# --------------------------------------------------------------------------
def run_pipeline(name: str, question: str) -> list[Hit]:
    spec = PIPELINES[name]
    if spec == "raptor":
        from m2_raptor_rag import retrieve_collapsed

        return retrieve_collapsed(question, top_k=TOP_N)
    return retrieve(question, replace(spec, top_n=TOP_N))


@traceable(run_type="chain", name="eval_case")
def eval_case(pipeline: str, question: str) -> dict:
    with Timer() as t:
        hits = run_pipeline(pipeline, question)
    return {"hits": hits, "latency_ms": t.ms, "trace_id": current_trace_id()}


def load_golden() -> list[dict]:
    return [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()]


def local_eval(pipelines: list[str]) -> None:
    golden = load_golden()
    rows, failures = [], []
    for p in pipelines:
        print(f"\n▶ {p}")
        for g in golden:
            out = eval_case(p, g["question"], langsmith_extra={"tags": ["eval", p], "metadata": {"pipeline": p, "qid": g["id"]}})
            m = score(out["hits"], g["relevant_doc_ids"])
            row = {"pipeline": p, "qid": g["id"], "kind": g.get("kind", ""), **m,
                   "latency_ms": round(out["latency_ms"]), "retrieved": "|".join(h.doc_id for h in out["hits"])}
            rows.append(row)
            mark = "✓" if m["recall"] == 1 else ("~" if m["recall"] > 0 else "✗")
            print(f"  {mark} {g['id']} P={m['precision']:.2f} R={m['recall']:.2f} MRR={m['mrr']:.2f} "
                  f"{row['latency_ms']:>5} ms  {g['question'][:55]}")
            if m["recall"] < 1:
                failures.append({**g, "pipeline": p, "retrieved": row["retrieved"].split("|"),
                                 "metrics": m, "langsmith_trace_id": out["trace_id"]})

    # ---- summary table
    print(f"\n{'pipeline':<20} {'P@5':>6} {'R@5':>6} {'MRR':>6} {'p50 ms':>8} {'p95 ms':>8}")
    print("-" * 60)
    summary = []
    for p in pipelines:
        r = [x for x in rows if x["pipeline"] == p]
        lat = sorted(x["latency_ms"] for x in r)
        s = {
            "pipeline": p,
            "precision@5": statistics.mean(x["precision"] for x in r),
            "recall@5": statistics.mean(x["recall"] for x in r),
            "mrr": statistics.mean(x["mrr"] for x in r),
            "p50_ms": lat[len(lat) // 2],
            "p95_ms": lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))],
        }
        summary.append(s)
        print(f"{p:<20} {s['precision@5']:>6.2f} {s['recall@5']:>6.2f} {s['mrr']:>6.2f} {s['p50_ms']:>8} {s['p95_ms']:>8}")

    # ---- by question type (where does each technique win?)
    kinds = sorted({x["kind"] for x in rows})
    print(f"\nrecall@5 by question kind\n{'pipeline':<20} " + " ".join(f"{k:>11}" for k in kinds))
    for p in pipelines:
        vals = []
        for k in kinds:
            r = [x["recall"] for x in rows if x["pipeline"] == p and x["kind"] == k]
            vals.append(f"{statistics.mean(r):>11.2f}" if r else f"{'-':>11}")
        print(f"{p:<20} " + " ".join(vals))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(RESULTS_DIR / f"eval_{ts}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(RESULTS_DIR / f"summary_{ts}.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    with open(RESULTS_DIR / "failures.jsonl", "w", encoding="utf-8") as f:
        for x in failures:
            f.write(json.dumps(x) + "\n")
    print(f"\nsaved results/eval_{ts}.csv, results/summary_{ts}.json, results/failures.jsonl ({len(failures)} failures)")


# --------------------------------------------------------------------------
# LangSmith experiments
# --------------------------------------------------------------------------
def ensure_dataset(client) -> None:
    golden = load_golden()
    if client.has_dataset(dataset_name=DATASET_NAME):
        print(f"[langsmith] dataset '{DATASET_NAME}' exists — reusing it")
        return
    ds = client.create_dataset(DATASET_NAME, description="Capstone 2 golden retrieval questions")
    client.create_examples(
        dataset_id=ds.id,
        examples=[
            {
                "inputs": {"question": g["question"]},
                "outputs": {"relevant_doc_ids": g["relevant_doc_ids"]},
                "metadata": {"qid": g["id"], "kind": g.get("kind", "")},
            }
            for g in golden
        ],
    )
    print(f"[langsmith] created dataset '{DATASET_NAME}' with {len(golden)} examples")


def _hits_from(outputs: dict) -> list[Hit]:
    return [Hit(d["chunk_id"], "", {"doc_id": d["doc_id"], "doc_ids": d.get("doc_ids", "")}) for d in outputs["retrieved"]]


def precision_at_5(outputs: dict, reference_outputs: dict) -> dict:
    return {"key": "precision@5", "score": score(_hits_from(outputs), reference_outputs["relevant_doc_ids"])["precision"]}


def recall_at_5(outputs: dict, reference_outputs: dict) -> dict:
    return {"key": "recall@5", "score": score(_hits_from(outputs), reference_outputs["relevant_doc_ids"])["recall"]}


def mrr(outputs: dict, reference_outputs: dict) -> dict:
    return {"key": "mrr", "score": score(_hits_from(outputs), reference_outputs["relevant_doc_ids"])["mrr"]}


def retrieval_latency(outputs: dict) -> dict:
    return {"key": "retrieval_latency_ms", "score": outputs["latency_ms"]}


def citations_valid(outputs: dict) -> dict:
    """1 if the answer cites at least one passage and never cites a passage that wasn't supplied."""
    if "answer" not in outputs:
        return {"key": "citations_valid", "score": None}
    ok = bool(outputs["citations"]) and not outputs["invalid_citations"]
    refused = outputs["answer"].startswith("I can't find")
    return {"key": "citations_valid", "score": 1.0 if (ok or refused) else 0.0}


def langsmith_eval(pipelines: list[str], with_answers: bool) -> None:
    from langsmith import Client, evaluate

    client = Client()
    ensure_dataset(client)
    def make_target(pipeline: str):
        def target(inputs: dict) -> dict:
            with Timer() as t:
                hits = run_pipeline(pipeline, inputs["question"])
            out = {
                "retrieved": [{"chunk_id": h.id, "doc_id": h.doc_id, "doc_ids": h.metadata.get("doc_ids", "")} for h in hits],
                "latency_ms": t.ms,
            }
            if with_answers:
                out.update(answer_with_citations(inputs["question"], hits))
            return out

        return target

    for p in pipelines:
        evaluators = [precision_at_5, recall_at_5, mrr, retrieval_latency]
        if with_answers:
            evaluators.append(citations_valid)
        print(f"\n[langsmith] experiment: {p}")
        evaluate(
            make_target(p),
            data=DATASET_NAME,
            evaluators=evaluators,
            experiment_prefix=f"m2-{p}",
            metadata={"pipeline": p, "top_n": TOP_N, "with_answers": with_answers},
            max_concurrency=2,
        )
    print("\nOpen LangSmith → Datasets & Experiments → "
          f"'{DATASET_NAME}' and select the experiments to compare them side by side.")


# --------------------------------------------------------------------------
# Replay: explain where each failure happened
# --------------------------------------------------------------------------
@traceable(run_type="chain", name="replay_failure")
def diagnose(question: str, relevant: list[str], k: int = 50) -> None:
    rel = set(relevant)
    bm = get_bm25().search(question, k)
    se = semantic_search(question, k)
    fused = rrf_fuse({"bm25": bm, "semantic": se})[:k]
    rr = rerank(question, fused, top_n=TOP_N)

    def best_rank(hits: list[Hit], doc: str) -> str:
        r = next((i for i, h in enumerate(hits, start=1) if doc in hit_doc_ids(h)), None)
        return str(r) if r else "—"

    print(f"\nQ: {question}")
    print(f"   {'relevant doc':<16} {'BM25':>6} {'semantic':>9} {'RRF':>6} {'rerank':>7}   verdict")
    for d in sorted(rel):
        b, s, f, r = (best_rank(x, d) for x in (bm, se, fused, rr))
        if b == "—" and s == "—":
            verdict = "never retrieved: check chunking / ingestion / wording of the doc"
        elif f != "—" and r == "—":
            verdict = f"in stage-1 candidates (RRF rank {f}) but not in the final top-{TOP_N}"
        elif r != "—":
            verdict = f"reaches the final top-{TOP_N}"
        else:
            verdict = "retrieved by one leg only, lost in fusion"
        print(f"   {d:<16} {b:>6} {s:>9} {f:>6} {r:>7}   {verdict}")


def replay(path: Path, pipeline: str | None) -> None:
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        f = json.loads(line)
        if pipeline and f["pipeline"] != pipeline:
            continue
        if f["question"] in seen:
            continue
        seen.add(f["question"])
        print(f"\n[{f['id']}] failed in '{f['pipeline']}'  (trace {f.get('langsmith_trace_id')})")
        print(f"   retrieved: {f['retrieved']}")
        diagnose(f["question"], f["relevant_doc_ids"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pipelines", nargs="+", choices=list(PIPELINES), default=list(PIPELINES))
    ap.add_argument("--langsmith", action="store_true", help="upload dataset and run LangSmith experiments")
    ap.add_argument("--with-answers", action="store_true", help="also generate answers (costs more)")
    ap.add_argument("--replay", type=Path, help="failures.jsonl to replay and diagnose")
    ap.add_argument("--pipeline", help="with --replay: only failures from this pipeline")
    a = ap.parse_args()

    if a.replay:
        replay(a.replay, a.pipeline)
    elif a.langsmith:
        langsmith_eval(a.pipelines, a.with_answers)
    else:
        local_eval(a.pipelines)
