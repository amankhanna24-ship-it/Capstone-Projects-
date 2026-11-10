# Capstone 2: Company Knowledge-Base Chatbot

**Module 2 · Learner role: RAG Engineer · About 8 hours**

This is a production-style RAG chatbot over a mixed company corpus (PDF policies, Word
contracts, Markdown runbooks, an HTML intranet page and CSV incident tickets). It uses:

- type-aware chunking
- ChromaDB
- hybrid BM25 + semantic retrieval fused with RRF
- Cohere cross-encoder reranking
- metadata and tenant filters
- Multi-Query and HyDE rewriting
- RAPTOR summary trees
- LangSmith tracing and evaluation

Every answer comes with citations and an audit record.

```
                ┌──────────── m2_chroma_ingestion.py ────────────┐
 data/raw/*  ─► │ load ─► chunk per doc type ─► metadata ─► embed │ ─► ChromaDB (kb_chunks)
 manifest.json  └─────────────────────────────────────────────────┘          │
                                                                              │
                ┌──────────────────── m2_hybrid_rag.py ─────────────────────┐ │
 question ────► │ (multi-query / HyDE) ─► BM25 top-50 ─┐                      │◄┘
                │                     ─► semantic top-50 ┴► RRF ─► Cohere     │
                │                         (same metadata filter on both)  rerank top-5
                │ ─► GPT answer with [n] citations ─► logs/answers.jsonl    │
                └────────────────────────────────────────────────────────────┘
                     every step traced in LangSmith ─► m2_eval_langsmith.py
```

## What's in the folder

| File | Purpose | Deliverable? |
|---|---|---|
| `m2_chroma_ingestion.py` | Loaders, chunking per type, metadata, incremental indexing | ✅ |
| `m2_hybrid_rag.py` | BM25 + semantic + RRF + rerank, Multi-Query, HyDE, chat with memory | ✅ |
| `m2_raptor_rag.py` | RAPTOR tree build, collapsed and top-down retrieval | ✅ |
| `m2_metadata_filtering.py` | Department/type/date/as-of filters, tenant-aware access, self-query | ✅ |
| `flowise/FLOWISE_BUILD_GUIDE.md` | Builds and exports `query_rerank_redismem.json` | ✅ (export) |
| `m2_eval_langsmith.py` | Precision, recall, MRR and latency per pipeline, LangSmith experiments, failure replay | ✅ (dashboard) |
| `kb_common.py` | Shared code: clients, BM25, RRF, rerank, citations, audit log | supporting |
| `scripts/make_sample_corpus.py` | Creates the sample PDFs, DOCX, MD, HTML and CSV | supporting |
| `data/manifest.json` | One entry per source with its metadata | supporting |
| `data/users.json` | Simulated SSO users for tenant filtering | supporting |
| `data/eval/golden.jsonl` | 16 labelled questions | supporting |
| `tests/test_core.py` | Offline unit tests (no API keys) | supporting |
| `.vscode/` | Interpreter, `.env` loading and one-click launch configs | supporting |

---

## Step 0: Before you start (15 min)

1. **VS Code** with the Python extension. When you open the folder, VS Code offers the
   recommended extensions from `.vscode/extensions.json`. Accept them.
2. **Python 3.12 or 3.13.** 3.14 should work, but if a package won't install, rebuild the
   venv with 3.12. On a Mac: `brew install python@3.12`.
3. **API keys**
   - OpenAI: platform.openai.com → API keys
   - Cohere: dashboard.cohere.com → API keys (the free trial key is enough for this project)
   - LangSmith: smith.langchain.com → Settings → API Keys
4. *(For Flowise only)* Node 24+ and Docker Desktop.

Rough cost: the sample corpus is about 67 chunks, so embedding it costs a fraction of a
cent. A full evaluation run with answers is a few cents. The whole capstone should come in
well under US$1.

## Step 1: Open the project and create the virtual environment (10 min)

1. Unzip the project and choose **File → Open Folder…** → `kb-chatbot`.
2. Open a terminal: **Terminal → New Terminal** (Ctrl+`).

**macOS / Linux**
```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**Windows (PowerShell)**
```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```
On Windows, also change `python.defaultInterpreterPath` in `.vscode/settings.json` to
`${workspaceFolder}\\.venv\\Scripts\\python.exe`.

3. Press `Cmd/Ctrl+Shift+P` → **Python: Select Interpreter** → choose `.venv`.

## Step 2: Configure keys (5 min)

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

Open `.env` and fill in `OPENAI_API_KEY`, `COHERE_API_KEY` and `LANGSMITH_API_KEY`. Leave
`LANGSMITH_TRACING=true`. Every script loads `.env` itself, and the VS Code launch
configs load it too.

## Step 3: Smoke-test without spending anything (5 min)

```bash
pytest -q                                     # 6 offline tests: tokeniser, RRF, filters, metrics, clustering
OFFLINE_MODE=1 python m2_chroma_ingestion.py --dry-run
```

`OFFLINE_MODE=1` swaps in fake embeddings and a stub LLM, so you can check the plumbing.
The answers are meaningless. Keep it at `0` for real work. (PowerShell:
`$env:OFFLINE_MODE=1; python ...`, then `Remove-Item Env:OFFLINE_MODE`.)

If you ran anything in offline mode against the real index, run
`python m2_chroma_ingestion.py --rebuild` afterwards. Fake vectors and OpenAI vectors
must never share a collection.

## Step 4: Create the corpus (5 min)

```bash
python scripts/make_sample_corpus.py
```

This writes nine fictional sources into `data/raw/`. The corpus is designed to expose each
failure mode the module covers:

| Trap | Example | What fixes it |
|---|---|---|
| Exact IDs | "What happened in INC-4821?" | BM25 |
| Paraphrase | "Can I work from abroad?" when the policy says "working from another country" | Embeddings |
| Two versions of one policy | Hotel cap GBP 150 (2024) vs GBP 180 (2026) | `is_latest` / `as_of` filters |
| Mixed departments | "notice period" appears in contracts and policies | Department filter |
| Corpus-wide questions | "What changed between the versions?" | RAPTOR |

**Using your own documents:** drop them into `data/raw/…` and add one entry each to
`data/manifest.json` with `doc_id`, `title`, `department`, `doc_type`, `visibility` and
`effective_date`. To ingest a live web page, use `"url"` instead of `"path"`.

## Step 5: Ingestion — `m2_chroma_ingestion.py` (60 min)

**5a. Dry run (free).** Chunk the corpus and inspect the result before paying for embeddings:

```bash
python m2_chroma_ingestion.py --dry-run
```

Open `data/processed/chunks.jsonl` in VS Code and read a dozen chunks. Each one starts with a
contextual header, for example `Travel and Expenses Policy v2.0 (FIN-POL-004-v2) — 3. Hotels`.

| doc_type | Format | Strategy | Size / overlap (chars) | Why |
|---|---|---|---|---|
| policy | PDF | Detect numbered headings, then recursive split; page number kept | 900 / 150 | Policies are organised by section, and citations need page numbers |
| contract | DOCX | One clause per chunk (Word heading styles) | 1500 / 200 | Never cut a legal clause in half |
| runbook | Markdown | Split on `#`/`##`/`###`, then recursive | 1200 / 150 | Each procedure step stays together |
| faq / web | HTML | Strip nav and footer, group by h1–h3 | 800 / 100 | Q&A pages are short and self-contained |
| ticket | CSV | One row per chunk, never split | n/a | A ticket is one fact |

Tune these in the `CHUNKING` dict and `split_sections()`.

**5b. Real run**

```bash
python m2_chroma_ingestion.py --rebuild
python m2_chroma_ingestion.py              # run again: every document reports "unchanged"
```

Production features to point out in your submission:

- **Deterministic chunk IDs** (`doc_id::index::hash`) make re-runs idempotent.
- **Incremental indexing.** A document is re-embedded only if its content or metadata hash
  changed, and its stale chunks are deleted first.
- **Version metadata.** `doc_family`, `effective_date`, `expiry_date` and `is_latest` are
  computed across versions. Dates are stored as integers (`20260401`) because Chroma's
  `$gte`/`$lt` only work on numbers.
- **`--prune`** removes documents that were taken out of the manifest.

## Step 6: Hybrid retrieval — `m2_hybrid_rag.py` (90 min)

**6a. See what each stage contributes**

```bash
python m2_hybrid_rag.py "What happened in INC-4821 and how was it fixed?" --compare
python m2_hybrid_rag.py "Can I work from abroad for a few weeks?" --compare
```

The output shows semantic-only, BM25-only, hybrid (RRF), hybrid + rerank and hybrid +
multi-query + rerank, with each chunk's rank in every list. Expect BM25 to win the ID
question and embeddings to win the paraphrase. Hybrid should get both.

**6b. Ask with citations**

```bash
python m2_hybrid_rag.py "How much can I spend on a hotel night in London?" --show-context
python m2_hybrid_rag.py "How much can I spend on a hotel night in London?" --latest-only
```

Without `--latest-only`, the model sees both policy versions and should flag the conflict
(rule 4 in the system prompt). With the flag, it gets only the current rule.

**6c. Chat with memory**

```bash
python m2_hybrid_rag.py
```

Try "What's the uptime commitment from Acme Cloud?" followed by "and what if they miss it?".
The follow-up is rewritten into a standalone question before retrieval. Use `/sources` to see
the passages behind the last answer, `/mq on` for multi-query, `/hyde on` for HyDE and
`/mode bm25` to switch retriever.

How it works (read `retrieve()`):

- **Stage 1 (recall).** BM25 top-50 and Chroma top-50, both under the same `where` filter,
  are fused with `rrf_fuse()`: `score = Σ 1/(60 + rank)`. RRF uses ranks only, so BM25
  scores and cosine similarities never need normalising. Use `RetrievalConfig.rrf_weights`
  to favour one leg.
- **Stage 2 (precision).** Cohere `rerank-v3.5` reads each (question, chunk) pair together
  and keeps the top 5. Set `RERANK_PROVIDER=local` (after
  `pip install -r requirements-local-rerank.txt`) to use the open-source
  `ms-marco-MiniLM-L-6-v2` cross-encoder instead.
- **Multi-Query** rewrites the question three ways. Each rewrite runs through both legs,
  and all the lists are fused together.
- **HyDE** embeds a hypothetical answer for the semantic leg only. BM25 keeps the raw
  question so exact IDs still match.
- **Citations.** Passages are numbered `[1]…[5]` and the model must cite them. Citation
  numbers are checked afterwards, and invalid ones are reported.
- **Audit trail.** Every answer appends a line to `logs/answers.jsonl` with the question,
  filter, chunk IDs, scores, answer, citations and LangSmith trace ID.

## Step 7: Metadata filtering — `m2_metadata_filtering.py` (45 min)

```bash
python m2_metadata_filtering.py --demo
```

The demo runs six scenarios:

1. The hotel-cap question with no filter, then `latest_only`, then `as_of 2025-06-01`
   (time travel to the rule that applied then).
2. "notice to terminate" with and without `department=Legal`.
3. "VPN error 809" with `doc_type=runbook` vs `doc_type=ticket`.
4. A date window: tickets opened in H1 2026.
5. **Tenant-aware access.** `arjun` (IT) can't see Legal contracts, so he gets "I can't
   find that…". `meera` (Legal) gets the answer. The tenant clause is always ANDed on, so
   a user can't widen their own access.
6. **Self-query.** The LLM extracts `{doc_type, date_from, date_to}` from
   "P1 or P2 database incidents from the first half of 2026", validated against a Pydantic
   schema.

To run individual filters:

```bash
python m2_metadata_filtering.py "hotel cap London" --as-of 2025-06-01
python m2_metadata_filtering.py "Acme uptime" --user arjun
python m2_metadata_filtering.py "P1 database incidents in 2026" --self-query
```

## Step 8: RAPTOR — `m2_raptor_rag.py` (60 min)

```bash
python m2_raptor_rag.py build --rebuild
python m2_raptor_rag.py show-tree
python m2_raptor_rag.py ask "What changed between the two versions of the travel and expenses policy?"
python m2_raptor_rag.py ask "Summarise our database incidents and how quickly we recovered" --strategy traverse
```

The build reuses the leaf vectors already in Chroma, so it costs nothing extra to embed
them. It then:

1. reduces them with PCA
2. soft-clusters them with a Gaussian Mixture, choosing k by BIC (a chunk can join more
   than one cluster)
3. summarises each cluster with the LLM, keeping IDs, numbers and version differences
4. embeds the summaries and repeats on the new level

The tree goes into a separate collection, `kb_raptor`. Compare
`python m2_hybrid_rag.py "<same question>"` against RAPTOR on summary questions: chunk-level
RAG tends to return fragments, while RAPTOR returns the overview.

## Step 9: Evaluation and the LangSmith dashboard — `m2_eval_langsmith.py` (60 min)

**9a. Local scorecard**

```bash
python m2_eval_langsmith.py
```

This runs all 16 golden questions through seven pipelines (semantic, bm25, hybrid_rrf,
hybrid_rrf_rerank, multiquery_rerank, hyde_rerank, raptor_collapsed). It prints
precision@5, recall@5, MRR and p50/p95 latency, then recall broken down by question kind
(exact-id / paraphrase / versioned / mixed / summary). Results go to `results/`.

**9b. LangSmith experiments**

```bash
python m2_eval_langsmith.py --langsmith --with-answers
```

This creates the dataset `m2-kb-chatbot-golden` and one experiment per pipeline. Each
experiment has these feedback keys:

- `precision@5`
- `recall@5`
- `mrr`
- `retrieval_latency_ms`
- `citations_valid`

**9c. Build the dashboard view** (LangSmith menu names occasionally move; look for the
equivalents):

1. **Datasets & Experiments** → `m2-kb-chatbot-golden` → select all experiments →
   **Compare**. This side-by-side table of precision, recall, MRR and latency per pipeline
   is your precision/recall dashboard. Screenshot it.
2. **Tracing project** `m2-kb-chatbot` → **Monitor / Dashboard** tab. Latency P50/P99,
   token usage and error rate are charted automatically. Every run carries the metadata
   key `pipeline`, so you can filter or group by it.
3. Optional: **Dashboards → New dashboard**. Add charts for latency and feedback scores,
   grouped by the `pipeline` metadata.

Open any trace and you'll see the nested steps: `kb_chat_turn` → `condense_question` →
`retrieve` → `bm25_search` / `semantic_search` → `cross_encoder_rerank` →
`answer_with_citations` → `ChatOpenAI`. Each retriever step shows its documents with
ranks and scores.

**9d. Replay failures**

```bash
python m2_eval_langsmith.py --replay results/failures.jsonl --pipeline hybrid_rrf_rerank
```

For each failed question, this shows where every relevant document ranked in BM25,
semantic, RRF and rerank, with a verdict:

- *never retrieved* means the problem is chunking or ingestion
- *in candidates but not top-5* means the problem is fusion or reranking

Each failure also stores its LangSmith trace ID. In LangSmith you can open that trace and
use **Add to dataset** to turn it into a regression test.

## Step 10: Flowise template (60 min)

Follow `flowise/FLOWISE_BUILD_GUIDE.md`. You'll run Chroma in server mode on the same
`chroma_db/` folder, start Redis in Docker, build the flow and export
`flowise/query_rerank_redismem.json`. The guide explains one canvas limitation (the Cohere
reranker won't accept a multi-query retriever as input) and the export-and-edit
workaround.

## Step 11: Submission checklist

- [ ] `m2_chroma_ingestion.py` output: chunk table plus a second run showing "unchanged"
- [ ] `m2_hybrid_rag.py --compare` output for one exact-ID and one paraphrase question
- [ ] `m2_raptor_rag.py show-tree` and one summary answer
- [ ] `m2_metadata_filtering.py --demo` output (versioning and tenant scenarios especially)
- [ ] `flowise/query_rerank_redismem.json` plus a screenshot of a two-turn chat
- [ ] LangSmith screenshots: experiment comparison (precision/recall/MRR/latency) and one expanded trace
- [ ] `results/summary_*.json` plus a short paragraph: which pipeline wins on which question kind, and why
- [ ] A sample of `logs/answers.jsonl` as the audit trail

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Collection 'kb_chunks' is empty` | Run `python m2_chroma_ingestion.py --rebuild` |
| `[config] OPENAI_API_KEY is not set` | Check `.env` is in the project root and has no quotes or spaces round `=` |
| Dimension mismatch from Chroma | You changed the embedding model. Rebuild the index (and the RAPTOR tree) |
| `[rerank] COHERE_API_KEY missing` | Add the key, or set `RERANK_PROVIDER=none` / `local` |
| HTTP 429 from Cohere | The trial key is rate-limited. Run fewer pipelines: `--pipelines hybrid_rrf hybrid_rrf_rerank` |
| No traces in LangSmith | `LANGSMITH_TRACING=true`. EU accounts need `LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com` |
| Flowise can't see the collection | Chroma must be running (`chroma run --path ./chroma_db --port 8000`) and nothing else should be writing to the folder |
| RAPTOR tree looks stale | `python m2_raptor_rag.py build --rebuild` after every re-ingestion |
