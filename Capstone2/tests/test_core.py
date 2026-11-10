"""Offline unit tests — no API keys needed.   Run:  pytest -q"""

import os
import sys
from pathlib import Path

os.environ.setdefault("OFFLINE_MODE", "1")
os.environ.setdefault("LANGSMITH_TRACING", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from kb_common import Hit, build_where, date_to_int, rrf_fuse, tokenize  # noqa: E402
from m2_eval_langsmith import score  # noqa: E402
from m2_raptor_rag import soft_cluster  # noqa: E402


def _h(i, doc="D"):
    return Hit(id=i, text=i, metadata={"doc_id": doc})


def test_tokenize_keeps_ids_and_parts():
    toks = tokenize("What happened in INC-4821?")
    assert "inc-4821" in toks and "4821" in toks
    assert "what" not in toks  # stop-word removed


def test_rrf_rewards_agreement():
    a = [_h("x"), _h("y"), _h("z")]
    b = [_h("y"), _h("x"), _h("w")]
    fused = rrf_fuse({"bm25": a, "semantic": b})
    assert {fused[0].id, fused[1].id} == {"x", "y"}  # in both lists -> top
    assert fused[0].score == fused[1].score  # 1/61 + 1/62 for both
    assert fused[-1].ranks.get("semantic") == 3 and "bm25" not in fused[-1].ranks


def test_rrf_weights():
    fused = rrf_fuse({"bm25": [_h("x")], "semantic": [_h("y")]}, weights={"semantic": 2.0})
    assert fused[0].id == "y"


def test_build_where_shapes():
    assert build_where() is None
    assert build_where(department="HR") == {"department": "HR"}
    w = build_where(department=["HR", "IT"], as_of="2025-06-01")
    assert w["$and"][0] == {"department": {"$in": ["HR", "IT"]}}
    assert {"expiry_date": {"$gt": 20250601}} in w["$and"]
    assert date_to_int("2026-04-01") == 20260401


def test_score_metrics():
    hits = [_h("1", "A"), _h("2", "B"), _h("3", "A")]
    m = score(hits, ["A", "C"], k=3)
    assert abs(m["precision"] - 2 / 3) < 1e-9
    assert m["recall"] == 0.5
    assert m["mrr"] == 1.0


def test_soft_cluster_separates_obvious_groups():
    rng = np.random.default_rng(0)
    X = np.vstack([rng.normal(0, 0.05, (15, 20)) + 1, rng.normal(0, 0.05, (15, 20)) - 1])
    clusters = soft_cluster(X, target_size=20)
    covered = set().union(*map(set, clusters))
    assert covered == set(range(30))
    assert len(clusters) >= 2
