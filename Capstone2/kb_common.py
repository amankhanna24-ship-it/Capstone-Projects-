"""
kb_common.py — shared building blocks for the Module 2 capstone.

Every deliverable script imports from here, so each technique lives in one
place and can be tuned once:

    config ............ paths, model names, keys (read from .env)
    clients ........... OpenAI embeddings / chat model, ChromaDB, Cohere
    Hit ............... one retrieved chunk + the scores/ranks it picked up
    filters ........... builders for Chroma `where` clauses (dept, type, dates)
    BM25Index ......... keyword search over the same chunks that live in Chroma
    semantic_search ... vector search in Chroma
    rrf_fuse .......... Reciprocal Rank Fusion of any number of ranked lists
    rerank ............ cross-encoder second stage (Cohere / local / none)
    answer_with_citations ... grounded generation with [n] citations
    audit_log ......... append-only JSONL record of every answer

All retrieval and generation functions are decorated with @traceable so they
show up as nested steps in LangSmith when LANGSMITH_TRACING=true.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

from dotenv import load_dotenv
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

load_dotenv()

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
LOG_DIR = ROOT / "logs"
RESULTS_DIR = ROOT / "results"

CHROMA_DIR = Path(os.getenv("CHROMA_DIR", str(ROOT / "chroma_db")))
if not CHROMA_DIR.is_absolute():
    CHROMA_DIR = (ROOT / CHROMA_DIR).resolve()

COLLECTION = os.getenv("KB_COLLECTION", "kb_chunks")
RAPTOR_COLLECTION = os.getenv("RAPTOR_COLLECTION", "kb_raptor")

EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
RERANK_MODEL = os.getenv("COHERE_RERANK_MODEL", "rerank-v3.5")
RERANK_PROVIDER = os.getenv("RERANK_PROVIDER", "cohere").lower()

OFFLINE = os.getenv("OFFLINE_MODE", "0") == "1"

RRF_K = 60  # the standard RRF constant from Cormack et al. (2009)


def require_key(name: str) -> None:
    """Fail early with a readable message instead of a stack trace."""
    if OFFLINE:
        return
    if not os.getenv(name) or os.getenv(name, "").endswith("..."):
        sys.exit(f"[config] {name} is not set. Copy .env.example to .env and add it.")


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_embeddings():
    if OFFLINE:
        from langchain_core.embeddings import DeterministicFakeEmbedding

        return DeterministicFakeEmbedding(size=256)
    require_key("OPENAI_API_KEY")
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(model=EMBED_MODEL)


@lru_cache(maxsize=1)
def get_llm(temperature: float = 0.0):
    require_key("OPENAI_API_KEY")
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=CHAT_MODEL, temperature=temperature)


def llm_text(system: str, user: str, temperature: float = 0.0) -> str:
    """One-shot chat call that returns plain text. Traced automatically by LangChain."""
    if OFFLINE:
        return "OFFLINE MODE stub answer drawn from the context [1]."
    from langchain_core.messages import HumanMessage, SystemMessage

    msg = get_llm(temperature).invoke([SystemMessage(system), HumanMessage(user)])
    return msg.content if isinstance(msg.content, str) else str(msg.content)


@lru_cache(maxsize=2048)
def embed_query(text: str) -> tuple[float, ...]:
    """Cached so evaluation runs don't pay twice for the same question."""
    return tuple(get_embeddings().embed_query(text))


def embed_documents(texts: Sequence[str], batch_size: int = 96) -> list[list[float]]:
    out: list[list[float]] = []
    emb = get_embeddings()
    for i in range(0, len(texts), batch_size):
        out.extend(emb.embed_documents(list(texts[i : i + batch_size])))
    return out


@lru_cache(maxsize=1)
def get_chroma():
    import chromadb

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(CHROMA_DIR))


def get_collection(name: str = COLLECTION):
    # embedding_function=None: we always pass our own OpenAI vectors, so Chroma
    # never silently embeds with its built-in default model.
    return get_chroma().get_or_create_collection(
        name=name,
        configuration={"hnsw": {"space": "cosine"}},
        embedding_function=None,
    )


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------
@dataclass
class Hit:
    id: str
    text: str
    metadata: dict[str, Any]
    score: float = 0.0
    ranks: dict[str, int] = field(default_factory=dict)  # e.g. {"bm25": 3, "semantic": 1}
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def doc_id(self) -> str:
        return str(self.metadata.get("doc_id", "?"))

    def label(self) -> str:
        m = self.metadata
        parts = [m.get("doc_id", "?"), m.get("title", "")]
        if m.get("page", -1) not in (-1, None):
            parts.append(f"p.{m['page']}")
        if m.get("section"):
            parts.append(str(m["section"])[:60])
        if m.get("effective_date_iso"):
            parts.append(f"effective {m['effective_date_iso']}")
        return " · ".join(str(p) for p in parts if p)

    def copy(self) -> "Hit":
        return Hit(self.id, self.text, dict(self.metadata), self.score, dict(self.ranks), dict(self.scores))


def hits_to_trace(outputs: Any) -> dict:
    """Render hits as LangChain-style documents so LangSmith shows them nicely."""
    hits = outputs if isinstance(outputs, list) else outputs.get("output", [])
    docs = []
    for h in hits if isinstance(hits, list) else []:
        if isinstance(h, Hit):
            docs.append(
                {
                    "type": "Document",
                    "page_content": h.text[:1500],
                    "metadata": {**h.metadata, "chunk_id": h.id, "score": h.score, "ranks": h.ranks},
                }
            )
    return {"documents": docs}


# --------------------------------------------------------------------------
# Metadata filters  (Chroma `where` syntax)
# --------------------------------------------------------------------------
def date_to_int(value: str | date | None) -> int | None:
    """'2026-04-01' -> 20260401. Chroma range operators ($gte/$lt) only work on numbers."""
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return int(value.strftime("%Y%m%d"))
    return int(datetime.strptime(str(value), "%Y-%m-%d").strftime("%Y%m%d"))


def build_where(
    department: str | list[str] | None = None,
    doc_type: str | list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    as_of: str | None = None,
    latest_only: bool = False,
    extra: dict | None = None,
) -> dict | None:
    """Compose a Chroma `where` clause. Returns None when there is nothing to filter on.

    date_from/date_to  -> documents whose effective date falls in the window
    as_of              -> the version that was *in force* on that day
                          (effective_date <= as_of < expiry_date)
    latest_only        -> only the current version of each document family
    """
    clauses: list[dict] = []

    def eq_or_in(key: str, val: str | list[str] | None) -> None:
        if not val:
            return
        if isinstance(val, (list, tuple, set)):
            vals = list(val)
            clauses.append({key: vals[0]} if len(vals) == 1 else {key: {"$in": vals}})
        else:
            clauses.append({key: val})

    eq_or_in("department", department)
    eq_or_in("doc_type", doc_type)
    if date_from:
        clauses.append({"effective_date": {"$gte": date_to_int(date_from)}})
    if date_to:
        clauses.append({"effective_date": {"$lte": date_to_int(date_to)}})
    if as_of:
        d = date_to_int(as_of)
        clauses.append({"effective_date": {"$lte": d}})
        clauses.append({"expiry_date": {"$gt": d}})
    if latest_only:
        clauses.append({"is_latest": True})
    if extra:
        clauses.append(extra)

    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def allowed_ids(where: dict | None, collection_name: str = COLLECTION) -> set[str] | None:
    """IDs that pass a filter — used so BM25 respects exactly the same filter as Chroma."""
    if where is None:
        return None
    return set(get_collection(collection_name).get(where=where, include=[])["ids"])


# --------------------------------------------------------------------------
# BM25 keyword search
# --------------------------------------------------------------------------
_STOP = set(
    "a an the and or of to in on for is are was were be by with at as it this that from what which who "
    "how when where do does did can i we you our your my me us there their than then if not no".split()
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[-_/.][A-Za-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    """Lower-case word tokens that keep IDs intact.

    'INC-4821' becomes ['inc-4821', 'inc', '4821'] so a search for the full ID,
    or just the number, still hits. This is exactly where BM25 beats embeddings.
    """
    out: list[str] = []
    for tok in _TOKEN_RE.findall(text.lower()):
        if tok in _STOP:
            continue
        out.append(tok)
        if any(c in tok for c in "-_/."):
            out.extend(p for p in re.split(r"[-_/.]", tok) if p and p not in _STOP)
    return out


class BM25Index:
    """BM25 over every chunk stored in a Chroma collection.

    Chroma is the single source of truth: the index is rebuilt from it, so the
    keyword and vector sides can never drift apart.
    """

    def __init__(self, collection_name: str = COLLECTION):
        from rank_bm25 import BM25Okapi

        data = get_collection(collection_name).get(include=["documents", "metadatas"])
        self.ids: list[str] = data["ids"]
        self.docs: list[str] = data["documents"] or []
        self.metas: list[dict] = data["metadatas"] or []
        if not self.ids:
            sys.exit(f"[bm25] Collection '{collection_name}' is empty. Run m2_chroma_ingestion.py first.")
        self._bm25 = BM25Okapi([tokenize(d) for d in self.docs])

    @traceable(run_type="retriever", name="bm25_search", process_outputs=hits_to_trace)
    def search(self, query: str, k: int = 50, allowed: set[str] | None = None, label: str = "bm25") -> list[Hit]:
        scores = self._bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        hits: list[Hit] = []
        for i in order:
            if scores[i] <= 0:
                break
            if allowed is not None and self.ids[i] not in allowed:
                continue
            h = Hit(self.ids[i], self.docs[i], self.metas[i], float(scores[i]))
            h.ranks[label] = len(hits) + 1
            h.scores[label] = float(scores[i])
            hits.append(h)
            if len(hits) >= k:
                break
        return hits


@lru_cache(maxsize=4)
def get_bm25(collection_name: str = COLLECTION) -> BM25Index:
    return BM25Index(collection_name)


# --------------------------------------------------------------------------
# Semantic search
# --------------------------------------------------------------------------
@traceable(run_type="retriever", name="semantic_search", process_outputs=hits_to_trace)
def semantic_search(
    query: str,
    k: int = 50,
    where: dict | None = None,
    collection_name: str = COLLECTION,
    embed_text: str | None = None,
    label: str = "semantic",
) -> list[Hit]:
    """Bi-encoder retrieval. `embed_text` lets HyDE embed a hypothetical answer instead of the question."""
    col = get_collection(collection_name)
    res = col.query(
        query_embeddings=[list(embed_query(embed_text or query))],
        n_results=max(1, min(k, col.count())),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    hits = []
    for rank, (cid, doc, meta, dist) in enumerate(
        zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]), start=1
    ):
        sim = 1.0 - float(dist)  # cosine distance -> similarity
        h = Hit(cid, doc, meta, sim)
        h.ranks[label] = rank
        h.scores[label] = sim
        hits.append(h)
    return hits


# --------------------------------------------------------------------------
# Reciprocal Rank Fusion
# --------------------------------------------------------------------------
def rrf_fuse(ranked_lists: dict[str, list[Hit]], k: int = RRF_K, weights: dict[str, float] | None = None) -> list[Hit]:
    """score(d) = Σ_lists  w_list / (k + rank_list(d))

    Uses ranks only, never raw scores, which is why BM25 scores (0–30ish) and
    cosine similarities (0–1) can be combined without any normalisation.
    """
    fused: dict[str, Hit] = {}
    for name, hits in ranked_lists.items():
        w = (weights or {}).get(name, 1.0)
        for rank, h in enumerate(hits, start=1):
            if h.id not in fused:
                fused[h.id] = h.copy()
                fused[h.id].score = 0.0
            f = fused[h.id]
            f.score += w / (k + rank)
            f.ranks[name] = rank
            f.scores.update(h.scores)
    out = sorted(fused.values(), key=lambda h: h.score, reverse=True)
    for i, h in enumerate(out, start=1):
        h.ranks["rrf"] = i
        h.scores["rrf"] = h.score
    return out


# --------------------------------------------------------------------------
# Cross-encoder reranking
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _local_cross_encoder():
    from sentence_transformers import CrossEncoder  # optional dependency

    return CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")


@traceable(run_type="retriever", name="cross_encoder_rerank", process_outputs=hits_to_trace)
def rerank(query: str, hits: list[Hit], top_n: int = 5, provider: str | None = None) -> list[Hit]:
    """Stage 2: score each (query, chunk) pair jointly and keep the best `top_n`."""
    provider = (provider or RERANK_PROVIDER).lower()
    if not hits:
        return []
    if OFFLINE or provider == "none":
        return [h.copy() for h in hits[:top_n]]

    if provider == "cohere":
        if not os.getenv("COHERE_API_KEY") or os.getenv("COHERE_API_KEY", "").endswith("..."):
            print("[rerank] COHERE_API_KEY missing -> skipping rerank (set RERANK_PROVIDER=none to silence)")
            return [h.copy() for h in hits[:top_n]]
        import cohere

        co = cohere.ClientV2(api_key=os.environ["COHERE_API_KEY"])
        res = co.rerank(model=RERANK_MODEL, query=query, documents=[h.text for h in hits], top_n=top_n)
        pairs = [(r.index, float(r.relevance_score)) for r in res.results]
    elif provider == "local":
        scores = _local_cross_encoder().predict([(query, h.text) for h in hits])
        pairs = sorted(enumerate(map(float, scores)), key=lambda p: p[1], reverse=True)[:top_n]
    else:
        raise ValueError(f"Unknown RERANK_PROVIDER '{provider}' (use cohere | local | none)")

    out = []
    for new_rank, (idx, score) in enumerate(pairs, start=1):
        h = hits[idx].copy()
        h.score = score
        h.ranks["rerank"] = new_rank
        h.scores["rerank"] = score
        out.append(h)
    return out


# --------------------------------------------------------------------------
# Grounded answer with citations
# --------------------------------------------------------------------------
ANSWER_SYSTEM = """You are the internal knowledge-base assistant for the company.

Rules:
1. Answer ONLY from the numbered context passages. Do not use outside knowledge.
2. Put a citation like [1] or [2][4] after every sentence that states a fact.
3. Quote exact IDs, amounts, dates and limits as written in the context.
4. If two passages disagree (e.g. an old and a new version of a policy), say so and
   prefer the one with the later effective date, citing both.
5. If the context does not contain the answer, reply exactly:
   "I can't find that in the knowledge base." and nothing else.
Keep answers short and factual."""


def format_context(hits: list[Hit]) -> str:
    blocks = []
    for i, h in enumerate(hits, start=1):
        blocks.append(f"[{i}] ({h.label()})\n{h.text}")
    return "\n\n".join(blocks)


@traceable(run_type="chain", name="answer_with_citations")
def answer_with_citations(question: str, hits: list[Hit]) -> dict:
    if not hits:
        return {"answer": "I can't find that in the knowledge base.", "citations": [], "invalid_citations": []}

    user = f"Context:\n{format_context(hits)}\n\nQuestion: {question}"
    answer = llm_text(ANSWER_SYSTEM, user)

    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)})
    valid = [n for n in cited if 1 <= n <= len(hits)]
    invalid = [n for n in cited if n not in valid]
    citations = [
        {
            "n": n,
            "chunk_id": hits[n - 1].id,
            "doc_id": hits[n - 1].doc_id,
            "title": hits[n - 1].metadata.get("title"),
            "source": hits[n - 1].metadata.get("source"),
            "page": hits[n - 1].metadata.get("page"),
            "section": hits[n - 1].metadata.get("section"),
        }
        for n in valid
    ]
    return {"answer": answer, "citations": citations, "invalid_citations": invalid}


def print_answer(result: dict) -> None:
    print("\n" + "=" * 78)
    print(result["answer"])
    if result.get("citations"):
        print("\nSources:")
        for c in result["citations"]:
            loc = f"p.{c['page']}" if c.get("page") not in (None, -1) else (c.get("section") or "")
            print(f"  [{c['n']}] {c['doc_id']} — {c['title']} {loc}  ({c['source']})")
    if result.get("invalid_citations"):
        print(f"\n  ⚠ answer cited passages that were not supplied: {result['invalid_citations']}")
    print("=" * 78)


def print_hits(hits: list[Hit], title: str = "Retrieved") -> None:
    print(f"\n--- {title} ({len(hits)}) ---")
    for i, h in enumerate(hits, start=1):
        ranks = " ".join(f"{k}={v}" for k, v in h.ranks.items())
        print(f"{i:>2}. {h.score:8.4f}  {h.label()[:70]:<70}  [{ranks}]")


# --------------------------------------------------------------------------
# Audit trail
# --------------------------------------------------------------------------
def current_trace_id() -> str | None:
    rt = get_current_run_tree()
    return str(rt.trace_id) if rt is not None else None


def audit_log(record: dict) -> None:
    """Append one JSON line per answer: question, filters, chunk IDs, answer, trace ID."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now(timezone.utc).isoformat(), **record}
    with open(LOG_DIR / "answers.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class Timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = (time.perf_counter() - self.t0) * 1000


def hits_summary(hits: Iterable[Hit]) -> list[dict]:
    return [{"chunk_id": h.id, "doc_id": h.doc_id, "score": round(h.score, 5), "ranks": h.ranks} for h in hits]
