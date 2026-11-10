"""
m2_raptor_rag.py — RAPTOR: Recursive Abstractive Processing for Tree-Organised Retrieval.

    python m2_raptor_rag.py build                 # build the summary tree (cached in Chroma)
    python m2_raptor_rag.py build --rebuild       # throw it away and rebuild
    python m2_raptor_rag.py show-tree             # print the levels and node titles
    python m2_raptor_rag.py ask "What changed in the expense policy between versions?"
    python m2_raptor_rag.py ask "Summarise our database incidents" --strategy traverse

Why: chunk-level RAG answers "what is the hotel cap?" well but struggles with questions
that need the whole corpus ("what are the main themes across our IT incidents?"),
because no single chunk contains the answer. RAPTOR adds higher-level nodes:

    level 0   the original chunks (leaves)
    level 1   LLM summaries of clusters of similar chunks
    level 2   summaries of clusters of level-1 summaries … up to a root

Build:  embed -> reduce (PCA) -> soft-cluster (Gaussian Mixture, k chosen by BIC)
        -> summarise each cluster -> embed summaries -> repeat on the new level.
        (The paper uses UMAP for reduction; PCA keeps dependencies light. Swap in
        umap-learn if you want to follow it exactly.)

Query:  collapsed  — search all levels at once and take the best nodes (paper's default)
        traverse   — start at the top, pick the best nodes, descend into their children
"""

from __future__ import annotations

import argparse
from collections import Counter

import numpy as np
from langsmith import traceable
from sklearn.decomposition import PCA
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import normalize

from kb_common import (
    COLLECTION,
    OFFLINE,
    RAPTOR_COLLECTION,
    Hit,
    Timer,
    answer_with_citations,
    audit_log,
    current_trace_id,
    embed_documents,
    embed_query,
    get_chroma,
    get_collection,
    hits_summary,
    hits_to_trace,
    llm_text,
    print_answer,
    print_hits,
    rerank,
    semantic_search,
)

MAX_CLUSTER_CHARS = 12_000  # ~3k tokens of input per summary call
SUMMARY_SYSTEM = """You summarise passages from internal company documents (policies,
contracts, runbooks, incident tickets) for a retrieval index.
- Start with a one-line title on its own line.
- Then write 120-200 words covering the shared theme and the most important facts.
- Preserve exact IDs (INC-4821, FIN-POL-004, RB-DB-003), amounts, limits, dates and version
  numbers. If passages come from different versions of the same document, state what changed.
- No preamble, no bullet lists."""


# --------------------------------------------------------------------------
# Clustering
# --------------------------------------------------------------------------
def soft_cluster(X: np.ndarray, max_clusters: int = 8, threshold: float = 0.15, seed: int = 42,
                 target_size: int = 12) -> list[list[int]]:
    """Gaussian-Mixture soft clustering, k chosen by BIC. A node may join several clusters.

    k is searched between ceil(n / target_size) and max_clusters, so one summary never has
    to squeeze in more than roughly `target_size` chunks.
    """
    n = len(X)
    if n <= 3:
        return [list(range(n))]
    dim = max(2, min(10, n - 2))
    Xr = PCA(n_components=dim, random_state=seed).fit_transform(normalize(X))

    max_k = max(1, min(max_clusters, n // 2))
    min_k = min(max_k, max(1, -(-n // target_size)))
    best_k, best_bic = min_k, np.inf
    for k in range(min_k, max_k + 1):
        gm = GaussianMixture(n_components=k, covariance_type="diag", random_state=seed).fit(Xr)
        bic = gm.bic(Xr)
        if bic < best_bic:
            best_k, best_bic = k, bic
    gm = GaussianMixture(n_components=best_k, covariance_type="diag", random_state=seed).fit(Xr)
    probs = gm.predict_proba(Xr)

    clusters: list[set[int]] = [set() for _ in range(best_k)]
    for i in range(n):
        clusters[int(probs[i].argmax())].add(i)  # every node in its best cluster
        for c in np.where(probs[i] > threshold)[0]:
            clusters[int(c)].add(i)  # plus any other cluster it plausibly belongs to
    return [sorted(c) for c in clusters if c]


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
LEAF_KEYS = ("doc_id", "title", "department", "doc_type", "source", "page", "section",
             "effective_date", "effective_date_iso", "is_latest", "visibility")


def _common(values: list[str]) -> str:
    vals = set(values)
    return vals.pop() if len(vals) == 1 else "mixed"


@traceable(run_type="chain", name="raptor_summarise_cluster")
def summarise(texts: list[str]) -> str:
    joined, used = "", 0
    for t in texts:
        if used + len(t) > MAX_CLUSTER_CHARS:
            break
        joined += f"---\n{t}\n"
        used += len(t)
    if OFFLINE:
        return "Offline summary\n" + joined[:600]
    return llm_text(SUMMARY_SYSTEM, joined)


@traceable(run_type="chain", name="raptor_build_tree")
def build_tree(rebuild: bool = False, max_levels: int = 3, where: dict | None = None) -> None:
    chroma = get_chroma()
    if rebuild:
        try:
            chroma.delete_collection(RAPTOR_COLLECTION)
        except Exception:
            pass
    tree = get_collection(RAPTOR_COLLECTION)
    if tree.count() and not rebuild:
        print(f"[raptor] tree already exists ({tree.count()} nodes). Use --rebuild to recreate.")
        return

    data = get_collection(COLLECTION).get(where=where, include=["documents", "metadatas", "embeddings"])
    if not data["ids"]:
        raise SystemExit("[raptor] no leaf chunks found — run m2_chroma_ingestion.py first")

    # ---- level 0: copy leaves (re-use their vectors, no new embedding cost)
    nodes = []
    for cid, text, meta, emb in zip(data["ids"], data["documents"], data["metadatas"], data["embeddings"]):
        m = {k: meta[k] for k in LEAF_KEYS if k in meta}
        m.update({"level": 0, "node_type": "leaf", "doc_ids": meta["doc_id"], "children": ""})
        nodes.append({"id": f"L0::{cid}", "text": text, "emb": np.asarray(emb, dtype=float), "meta": m})
    _store(tree, nodes)
    print(f"[raptor] level 0: {len(nodes)} leaves")

    # ---- levels 1..n: cluster, summarise, embed
    current = nodes
    for level in range(1, max_levels + 1):
        if len(current) <= 1:
            break
        clusters = soft_cluster(np.vstack([n["emb"] for n in current]))
        if len(current) <= 3:
            clusters = [list(range(len(current)))]  # collapse into a single root

        new_nodes = []
        for c_idx, members in enumerate(clusters):
            group = [current[i] for i in members]
            text = summarise([g["text"] for g in group])
            doc_ids = sorted({d for g in group for d in g["meta"]["doc_ids"].split(",") if d})
            title_line = text.strip().splitlines()[0][:120] if text.strip() else f"Cluster {c_idx}"
            new_nodes.append(
                {
                    "id": f"L{level}::{c_idx:03d}",
                    "text": text,
                    "meta": {
                        "level": level,
                        "node_type": "summary",
                        "doc_id": f"RAPTOR-L{level}-{c_idx:02d}",
                        "title": f"Summary: {title_line}",
                        "doc_ids": ",".join(doc_ids),
                        "children": ",".join(g["id"] for g in group),
                        "department": _common([g["meta"].get("department", "") for g in group]),
                        "doc_type": _common([g["meta"].get("doc_type", "") for g in group]),
                        "cluster_size": len(group),
                    },
                }
            )
        vectors = embed_documents([n["text"] for n in new_nodes])
        for n, v in zip(new_nodes, vectors):
            n["emb"] = np.asarray(v, dtype=float)
        _store(tree, new_nodes)
        print(f"[raptor] level {level}: {len(new_nodes)} summaries from {len(current)} nodes "
              f"(sizes {[len(c) for c in clusters]})")
        if len(new_nodes) == 1 or len(new_nodes) >= len(current):
            break
        current = new_nodes
    print(f"[raptor] tree stored in collection '{RAPTOR_COLLECTION}' ({tree.count()} nodes)")


def _store(col, nodes: list[dict]) -> None:
    for i in range(0, len(nodes), 200):
        batch = nodes[i : i + 200]
        col.upsert(
            ids=[n["id"] for n in batch],
            documents=[n["text"] for n in batch],
            embeddings=[n["emb"].tolist() for n in batch],
            metadatas=[n["meta"] for n in batch],
        )


# --------------------------------------------------------------------------
# Query
# --------------------------------------------------------------------------
@traceable(run_type="retriever", name="raptor_collapsed", process_outputs=hits_to_trace)
def retrieve_collapsed(question: str, top_k: int = 8, where: dict | None = None) -> list[Hit]:
    """Treat every node (leaf or summary) as one flat pool and take the most similar."""
    return semantic_search(question, k=top_k, where=where, collection_name=RAPTOR_COLLECTION, label="raptor")


@traceable(run_type="retriever", name="raptor_traverse", process_outputs=hits_to_trace)
def retrieve_traverse(question: str, beam: int = 3) -> list[Hit]:
    """Top-down: best nodes at the top level, then the best of their children, down to leaves."""
    tree = get_collection(RAPTOR_COLLECTION)
    q = np.asarray(embed_query(question))
    top_level = max(m["level"] for m in tree.get(include=["metadatas"])["metadatas"])

    selected: list[Hit] = []
    frontier = tree.get(where={"level": top_level}, include=["documents", "metadatas", "embeddings"])
    for _ in range(top_level + 1):
        if not frontier["ids"]:
            break
        embs = np.asarray(frontier["embeddings"], dtype=float)
        sims = embs @ q / (np.linalg.norm(embs, axis=1) * np.linalg.norm(q) + 1e-9)
        best = np.argsort(-sims)[:beam]
        children: list[str] = []
        for rank, i in enumerate(best, start=1):
            meta = frontier["metadatas"][i]
            h = Hit(frontier["ids"][i], frontier["documents"][i], meta, float(sims[i]))
            h.ranks[f"L{meta['level']}"] = rank
            selected.append(h)
            children += [c for c in meta.get("children", "").split(",") if c]
        if not children:
            break
        frontier = tree.get(ids=list(dict.fromkeys(children)), include=["documents", "metadatas", "embeddings"])
    # most specific first: leaves carry the exact facts, summaries the overview
    return sorted(selected, key=lambda h: (h.metadata.get("level", 0), -h.score))


@traceable(run_type="chain", name="raptor_ask")
def ask(question: str, strategy: str = "collapsed", top_k: int = 8, use_rerank: bool = False) -> dict:
    with Timer() as t:
        hits = retrieve_collapsed(question, top_k) if strategy == "collapsed" else retrieve_traverse(question)
        if use_rerank:
            hits = rerank(question, hits, top_n=min(6, len(hits)))
    result = answer_with_citations(question, hits)
    result.update({"hits": hits, "retrieval_ms": round(t.ms)})
    audit_log({"question": question, "pipeline": f"raptor-{strategy}", "retrieved": hits_summary(hits),
               "answer": result["answer"], "citations": result["citations"],
               "langsmith_trace_id": current_trace_id()})
    return result


def show_tree() -> None:
    tree = get_collection(RAPTOR_COLLECTION)
    data = tree.get(include=["metadatas"])
    if not data["ids"]:
        raise SystemExit("No tree yet — run: python m2_raptor_rag.py build")
    levels = Counter(m["level"] for m in data["metadatas"])
    for lvl in sorted(levels):
        print(f"\nLevel {lvl}: {levels[lvl]} nodes")
        if lvl == 0:
            continue
        for cid, m in sorted(zip(data["ids"], data["metadatas"]), key=lambda p: p[0]):
            if m["level"] == lvl:
                print(f"  {cid:<10} [{m.get('cluster_size')} children] {m['title'][:70]}  <- {m['doc_ids'][:60]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--rebuild", action="store_true")
    b.add_argument("--max-levels", type=int, default=3)
    b.add_argument("--department", help="build a tree for one department only")
    sub.add_parser("show-tree")
    q = sub.add_parser("ask")
    q.add_argument("question")
    q.add_argument("--strategy", choices=["collapsed", "traverse"], default="collapsed")
    q.add_argument("--top-k", type=int, default=8)
    q.add_argument("--rerank", action="store_true")
    a = ap.parse_args()

    if a.cmd == "build":
        build_tree(rebuild=a.rebuild, max_levels=a.max_levels,
                   where={"department": a.department} if a.department else None)
    elif a.cmd == "show-tree":
        show_tree()
    else:
        res = ask(a.question, a.strategy, a.top_k, a.rerank)
        print_hits(res["hits"], f"RAPTOR context ({a.strategy})")
        print_answer(res)
