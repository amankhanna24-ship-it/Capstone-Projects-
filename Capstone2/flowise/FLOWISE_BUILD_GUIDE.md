# Flowise template: `query_rerank_redismem`

Multi-query rewriting, Cohere reranking and Redis-backed conversation memory, built on the
same ChromaDB collection (`kb_chunks`) that `m2_chroma_ingestion.py` creates.

You build it on the Flowise canvas, then export it as `flowise/query_rerank_redismem.json`.
That exported file is the deliverable.

> **Checked against the Flowise source (v3.1.x, October 2026).** There's one wiring catch.
> The **Cohere Rerank Retriever** only accepts a `VectorStoreRetriever` input. The
> **Multi Query** and **Reciprocal Rank Fusion** retrievers output a plain `BaseRetriever`,
> so the canvas won't let you drag a multi-query retriever into the reranker. Part C below
> shows the export-and-edit workaround. If it fails in your Flowise version, submit Part B
> and say that the full combination is in `m2_hybrid_rag.py --multi-query`.

---

## Part A: Services (one-off)

You need Node 24+ for Flowise 3.x (`node -v` to check) and Docker for Redis.

```bash
# 1. Redis for chat memory
docker run -d --name kb-redis -p 6379:6379 redis:7

# 2. Chroma in server mode, pointing at the folder your Python scripts wrote
#    (run from the project root with the venv active; stop any Python script that's using the DB first)
chroma run --path ./chroma_db --port 8000

# 3. Flowise (new terminal)
npm install -g flowise
npx flowise start          # opens on http://localhost:3000
```

Leave Chroma and Flowise running in their own VS Code terminals (Terminal → Split).

## Part B: Build the flow on the canvas

Flowise → **Chatflows** → **Add New**. Name it `query_rerank_redismem`.

Add the nodes below by clicking **+** and searching for each name.

| # | Node (search name) | Settings |
|---|---|---|
| 1 | **OpenAI Embeddings** | Credential: OpenAI API key · Model: `text-embedding-3-small` (must match ingestion, or you'll get a dimension error) |
| 2 | **Chroma** (Vector Stores) | Collection Name: `kb_chunks` · Chroma URL: `http://localhost:8000` · Top K: `20` · leave *Document* empty so it loads the existing collection |
| 3 | **ChatOpenAI** | Model: `gpt-4o-mini` · Temperature: `0` (for answers) |
| 4 | **ChatOpenAI** (second one) | Model: `gpt-4o-mini` · Temperature: `0.3` (for query rewriting) |
| 5 | **Reciprocal Rank Fusion Retriever** | Query Count: `4` · Top K: `20` · Constant: `60`. **Fill in both Top K and Constant.** The node reads Constant only when Top K is set, and leaving Constant empty gives `NaN`. |
| 6 | **Cohere Rerank Retriever** | Credential: Cohere API key · Model: `rerank-v3.5` · Top K: `5` (always set it) |
| 7 | **Redis-Backed Chat Memory** | Credential: Redis (`redis://localhost:6379`) · Session Timeouts: `3600` · Window Size: `10` · leave Session Id blank so Flowise uses the chat id |
| 8 | **Conversational Retrieval QA Chain** | Return Source Documents: **on** · paste the system message below |

**Connections**

```
OpenAI Embeddings ──► Chroma.Embeddings
Chroma (output: Chroma Retriever) ──► Reciprocal Rank Fusion Retriever.Vector Store Retriever
ChatOpenAI #2 ──► Reciprocal Rank Fusion Retriever.Language Model
Chroma (output: Chroma Retriever) ──► Cohere Rerank Retriever.Vector Store Retriever   (temporary, see Part C)
Cohere Rerank Retriever ──► Conversational Retrieval QA Chain.Vector Store Retriever
ChatOpenAI #1 ──► Conversational Retrieval QA Chain.Chat Model
Redis-Backed Chat Memory ──► Conversational Retrieval QA Chain.Memory
```

The Reciprocal Rank Fusion Retriever is Flowise's multi-query node: it asks the LLM for
*Query Count* rewrites, retrieves for each one and fuses the lists with RRF (the same
technique as `rrf_fuse()` in `kb_common.py`). At this point its output isn't connected
to anything.

**System message for node 8**

```
You are the internal knowledge-base assistant. Answer only from the provided context.
Cite the document ID (e.g. HR-POL-012, INC-4821) for every fact. If the context does not
contain the answer, say "I can't find that in the knowledge base."
```

Click **Save**. The flow already works as *Chroma top-20 → Cohere rerank top-5 → answer with
memory*. Test it in the chat bubble:

1. "What is the hotel cap in London?"
2. "And what was it before April 2026?" (memory should resolve "it")

## Part C: Put multi-query in front of the reranker (export-and-edit)

1. ⚙ (top right) → **Export Chatflow**. Save the file as `flowise/query_rerank_redismem.json` in this project.
2. Open it in VS Code. Press `Shift+Alt+F` (Windows) or `Shift+Option+F` (Mac) to format the JSON.
3. In `nodes`, find the RRF node (`"id": "RRFRetriever_0"`). Copy the `id` of its retriever output anchor, under
   `data.outputAnchors[0].options[0].id`. It looks like
   `RRFRetriever_0-output-retriever-RRFRetriever|BaseRetriever`.
4. In `edges`, find the edge with `"target": "cohereRerankRetriever_0"`. Change:
   - `"source"` → `"RRFRetriever_0"`
   - `"sourceHandle"` → the anchor id you copied
5. In `nodes` → `cohereRerankRetriever_0` → `data.inputs`, set
   `"baseRetriever": "{{RRFRetriever_0.data.instance}}"`.
6. Save. In Flowise: ⚙ → **Load Chatflow** → choose the edited file → **Save**.

At runtime both retriever nodes are LangChain `ContextualCompressionRetriever`s, which
accept any `BaseRetriever`. Only the canvas type check blocks the wiring. The resulting
pipeline is:

```
question ─► LLM writes 4 rewrites ─► Chroma top-20 each ─► RRF fusion ─► Cohere rerank top-5
        ─► Conversational Retrieval QA Chain (Redis memory) ─► answer + source documents
```

If the load fails or the edge disappears, use the Part B version and say so in your write-up.

## Part D: Tracing and API test

- ⚙ → **Configuration** → **Analyse Chatflow** → **LangSmith**: add your LangSmith credential and
  set the project to `m2-kb-chatbot`. Flowise runs now appear next to the Python traces.
- Call the flow from a terminal. The `sessionId` keeps memory per user:

```bash
curl -s http://localhost:3000/api/v1/prediction/<CHATFLOW_ID> \
  -H "Content-Type: application/json" \
  -d '{"question": "What uptime does Acme Cloud guarantee?", "overrideConfig": {"sessionId": "demo-user-1"}}'
```

- Check that memory is in Redis: `docker exec -it kb-redis redis-cli keys '*'`

Export the final version (⚙ → Export Chatflow) over `flowise/query_rerank_redismem.json` before you submit.
