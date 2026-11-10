# Run trace: Compare Raptor RAG vs HyDE

## Run statistics

| Metric | Value |
|---|---|
| question | Compare Raptor RAG vs HyDE |
| model | openai/gpt-4o-mini |
| steps_used | 11 / 12 |
| tokens_used | 34872 / 80000 |
| seconds | 47 / 240 |
| stop_reason | agent decided goal was met (I have gathered sufficient information on Raptor RAG and HyDE, including their functionalities, advantages, and a comparative analysis.) |
| notes_saved | 3 |
| sources_seen | 15 |
| sources_cited | 3 |
| context_trims | 0 |
| long_term_memory | upstash |

## Reasoning loop (Thought → Action → Observation)

**SYSTEM** _(t=0.3s)_

```
No related past research in long-term memory (upstash).
```

**Step 1 · THOUGHT** _(t=3.8s)_

```
To compare Raptor RAG and HyDE, I need to gather information on both models, including their architecture, performance, use cases, and any notable features or differences. I will start by searching for detailed descriptions and comparisons of Raptor RAG and HyDE separately.
```

**Step 1 · ACTION** _(t=3.8s)_

```
web_search {"query": "Raptor RAG model overview"}
```

**Step 1 · OBSERVATION** _(t=6.7s)_

```
Search results for 'Raptor RAG model overview' (engine: duckduckgo):
[1] Raptor RAG explained: A full guide to hierarchical retrieval
    URL: https://www.meilisearch.com/blog/raptor-rag
    RAPTOR RAG changes how document chunks are organized for large-language-model processing. Instead of chunking documents into individual sections, RAPTOR RAG stores the chunks as a tree.
[2] RAG with RAPTOR - GitHub
    URL: https://github.com/FareedKhan-dev/rag-with-raptor
    Raptor with RAG (Created by Fareed Khan) This is the core idea behind RAPTOR (Recursive Abstractive Processing for Tree-Organized Retrieval), it keeps RAG simple at query time while delivering superior results by building a hierarchical index that mirrors human understanding from details to high-lev
[3] RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval
    URL: https://arxiv.org/html/2401.18059v1
    At inference time, our RAPTOR model retrieves from this tree, integrating information across lengthy documents at different levels of abstraction. Controlled experiments show that retrieval with recursive summaries offers significant improvements over traditional retrieval-augmented LMs on several t
[4] GitHub - profintegra/raptor-rag: The official implementation of RAPTOR ...
    URL: https://github.com/profintegra/raptor-rag
    RAPTOR introduces a novel approach to retrieval-augmented language models by constructing a recursive tree structure from documents. This allows for more efficient and cont …[shortened in trace]
```

**Step 2 · THOUGHT** _(t=9.5s)_

```
I found several sources that provide insights into the Raptor RAG model, including its architecture and functionality. I will fetch the most relevant pages to gather detailed information about Raptor RAG.
```

**Step 2 · ACTION** _(t=9.5s)_

```
fetch_page {"url": "https://www.meilisearch.com/blog/raptor-rag", "focus": "overview of Raptor RAG model"}
```

**Step 2 · OBSERVATION** _(t=11.1s)_

```
[1] Raptor RAG explained: A full guide to hierarchical retrieval | Meilisearch
URL: https://www.meilisearch.com/blog/raptor-rag
---
In 2024, researchers at Stanford published a new standard for chunking and organization called Recursive Abstractive Processing for Tree-Organized Retrieval (RAPTOR).
RAPTOR changes the way retrieval-augmented generation (RAG) works with chunked documents. Instead of creating chunks and storing them randomly, RAPTOR creates a hierarchical tree structure of chunks, categorizes them, and writes summaries for each group.
RAPTOR gives users more precise answers because hierarchical summaries contain high-level information that LLMs can search.
Here's how to effectively use RAPTOR in your RAG systems.
RAPTOR RAG changes how document chunks are organized for large-language-model processing. Instead of chunking documents into individual sections, RAPTOR RAG stores the chunks as a tree.
Imagine that you have several chunks for a dozen documents. RAPTOR RAG takes the chunks and organizes them by category.
Because chunked data is organized into a tree, using RAPTOR RAG also improves the accuracy of query answers.
The number of summaries in a RAPTOR RAG depends on the number of documents in your data silos.
How does RAPTOR differ from GraphRAG, CRAG, and other advanced RAG methods?
RAPTOR RAG primarily addresses latency and accuracy of large document chunks.
Both of these problems are better solved with the improved organization that RAPTOR RAG offers.
With …[shortened in trace]
```

**Step 3 · THOUGHT** _(t=13.3s)_

```
I have gathered a detailed overview of the Raptor RAG model, including its hierarchical structure, chunking methods, and advantages. Now, I will search for information on the HyDE model to compare it with Raptor RAG.
```

**Step 3 · ACTION** _(t=13.3s)_

```
web_search {"query": "HyDE model overview"}
```

**Step 3 · OBSERVATION** _(t=16.8s)_

```
Search results for 'HyDE model overview' (engine: duckduckgo):
[6] Introduction to Hypothetical Document Embeddings (HyDE)
    URL: https://www.geeksforgeeks.org/data-science/hypothetical-document-embeddings-hyde-hyde/
    Feb 10, 2026 · HyDE (Hypothetical Document Embedding) is an extension of traditional retrieval in Retrieval Augmented Generation (RAG) where the system generates a hypothetical document before retrieval. Instead of converting queries to embeddings directly, it expands the query with richer context t
[7] HyDE for RAG Explained: How Hypothetical Document Embeddings ...
    URL: https://machinelearningplus.com/gen-ai/hypothetical-document-embedding-hyde-a-smarter-rag-method-to-search-documents/
    Learn how HyDE (Hypothetical Document Embeddings) improves RAG systems by creating richer query embeddings for smarter, more accurate AI-driven retrievals.
[8] What Is HyDE? How to Improve RAG with Hypothetical Documents
    URL: https://www.freecodecamp.org/news/what-is-hyde-how-to-improve-rag-with-hypothetical-documents/
    Jul 22, 2026 · Summary HyDE is a small idea with a large effect. You're not changing your index, embedding model, or generator. You're changing one line: what gets embedded when a query arrives. That single change reshapes the geometry of the search from question against answer to answer against ans
[9] HyDE - Overview of Hypothetical Document Embeddings - LinkedIn
    URL: https://www.linkedin.com/pulse/hyde-overview-hypothetical-document-emb …[shortened in trace]
```

**Step 4 · THOUGHT** _(t=18.7s)_

```
I found several sources that explain the HyDE model, including its approach to generating hypothetical documents for improved retrieval. I will fetch the most relevant pages to gather detailed information about HyDE.
```

**Step 4 · ACTION** _(t=18.7s)_

```
fetch_page {"url": "https://machinelearningplus.com/gen-ai/hypothetical-document-embedding-hyde-a-smarter-rag-method-to-search-documents/", "focus": "overview of HyDE model"}
```

**Step 4 · OBSERVATION** _(t=19.3s)_

```
[7] HyDE for RAG Explained: How Hypothetical Document Embeddings Boost Retrieval Accuracy
Very little readable text was found on this page (it may need JavaScript). QUALITY WARNING: try another source.
```

**Step 5 · THOUGHT** _(t=21.1s)_

```
The page I attempted to fetch for HyDE did not provide usable information due to a quality warning. I will try another source to gather details about the HyDE model.
```

**Step 5 · ACTION** _(t=21.1s)_

```
fetch_page {"url": "https://www.freecodecamp.org/news/what-is-hyde-how-to-improve-rag-with-hypothetical-documents/", "focus": "overview of HyDE model"}
```

**Step 5 · OBSERVATION** _(t=22.2s)_

```
[8] What Is HyDE? How to Improve RAG with Hypothetical Documents
URL: https://www.freecodecamp.org/news/what-is-hyde-how-to-improve-rag-with-hypothetical-documents/
---
Retrieval-Augmented Generation, commonly known as RAG, has become one of the most widely used approaches for building applications with large language models.
Instead of asking an LLM to answer entirely from its training data, a RAG system retrieves relevant information from an external knowledge base and provides that information to the model as context.
This is the problem that Hypothetical Document Embeddings, or HyDE, was designed to solve.
Why Hallucination Doesn't Automatically Break HyDE
Why Hallucination Doesn't Automatically Break HyDE
An Anthropic API key if you want to run the HyDE code sample (available at console.anthropic.com )
An Anthropic API key if you want to run the HyDE code sample (available at console.anthropic.com )
HyDE stands for Hypothetical Document Embeddings. The technique is simple. At query time, you prompt an LLM to generate a hypothetical document that would answer the user's question, embed that document instead of the query, and use its vector to search your index. That's the whole idea. Everything else is engineering.
The original HyDE approach used a language model to generate hypothetical documents and an unsupervised dense retriever to map those documents into an embedding space. The embedding acts as a search instruction for retrieving real documents from the corpus.
Whe …[shortened in trace]
```

**Step 6 · THOUGHT** _(t=24.9s)_

```
I have gathered a comprehensive overview of the HyDE model, including its mechanism of generating hypothetical documents to improve retrieval accuracy. Now, I will save the findings for both Raptor RAG and HyDE, and then I will look for comparative analyses or summaries that highlight the differences and similarities between the two models.
```

**Step 6 · ACTION** _(t=24.9s)_

```
save_note {"note": "Raptor RAG organizes document chunks into a hierarchical tree structure, improving retrieval accuracy by allowing LLMs to search high-level summaries. It uses a soft clustering algorithm and is best for complex queries across long documents. Limitations include the need for constant updates and potential document ingestion errors.", "source_ids": [1]}
```

**Step 6 · OBSERVATION** _(t=24.9s)_

```
Saved note #1 (sources [1]). Total notes: 1.
```

**Step 7 · THOUGHT** _(t=27.4s)_

```
I will now save the findings about the HyDE model to complete my notes on both models. After that, I will search for comparative analyses or summaries that highlight the differences and similarities between Raptor RAG and HyDE.
```

**Step 7 · ACTION** _(t=27.4s)_

```
save_note {"note": "HyDE (Hypothetical Document Embeddings) generates a hypothetical document at query time to improve retrieval accuracy. This document is embedded instead of the original query, allowing for a more effective comparison between answers. HyDE reshapes the search geometry, enhancing retrieval quality without changing the underlying index or embedding model.", "source_ids": [8]}
```

**Step 7 · OBSERVATION** _(t=27.4s)_

```
Saved note #2 (sources [8]). Total notes: 2.
```

**Step 8 · THOUGHT** _(t=29.3s)_

```
I have now saved notes on both Raptor RAG and HyDE. Next, I will search for comparative analyses or summaries that discuss the differences and similarities between these two models to complete the research question.
```

**Step 8 · ACTION** _(t=29.3s)_

```
web_search {"query": "Raptor RAG vs HyDE comparison"}
```

**Step 8 · OBSERVATION** _(t=32.8s)_

```
Search results for 'Raptor RAG vs HyDE comparison' (engine: duckduckgo):
[11] RAPTOR, HyDE and RAG Fusion Explained: Three Advanced ...
    URL: https://mljourney.com/raptor-hyde-and-rag-fusion-explained-three-advanced-retrieval-techniques/
    Sep 2, 2026 · RAPTOR, HyDE, and RAG Fusion are three advanced retrieval techniques that each address a different fundamental limitation of standard vector RAG. This guide gives each the depth it deserves: the core idea, why it works, when to use it, and a working implementation you can drop into an 
[12] HyDE vs RAG: Comparing Retrieval Approaches for LLMs
    URL: https://securetom.com/blog/hyde-vs-rag-retrieval-augmented-generation
    Feb 18, 2026 · HyDE vs traditional RAG: when to use each, implementation trade-offs, and how hybrid retrieval strategies improve LLM accuracy in production.
[13] GraphRAG vs RAPTOR: Architecture Comparison Guide
    URL: https://inferensys.com/differences/context-engineering-and-retrieval-ranking-platforms/graphrag-vs-vector-rag-architectures/graphrag-vs-raptor-recursive-abstractive-processing
    A technical comparison of Microsoft's GraphRAG entity-centric knowledge graph approach and RAPTOR's hierarchical summarization tree, focusing on which architecture better preserves global context for thematic questions versus specific entity lookups.
[14] Advanced RAG Techniques 2026: Reranking, HyDE, Parent-Child ...
    URL: https://mljourney.com/advanced-rag-techniques-2026-reranking-hyde-parent-child-and- …[shortened in trace]
```

**Step 9 · THOUGHT** _(t=35.9s)_

```
I found a relevant source that discusses Raptor RAG and HyDE together, which should provide a comparative analysis of the two models. I will fetch this page to gather insights on their differences and similarities.
```

**Step 9 · ACTION** _(t=35.9s)_

```
fetch_page {"url": "https://mljourney.com/raptor-hyde-and-rag-fusion-explained-three-advanced-retrieval-techniques/", "focus": "comparison of Raptor RAG and HyDE"}
```

**Step 9 · OBSERVATION** _(t=38.1s)_

```
[11] RAPTOR, HyDE and RAG Fusion Explained: Three Advanced Retrieval Techniques
URL: https://mljourney.com/raptor-hyde-and-rag-fusion-explained-three-advanced-retrieval-techniques/
---
RAPTOR, HyDE, and RAG Fusion are three advanced retrieval techniques that each address a different fundamental limitation of standard vector RAG. This guide gives each the depth it deserves: the core idea, why it works, when to use it, and a working implementation you can drop into an existing pipeline.
Standard RAG retrieves at the chunk level: individual passages. RAPTOR (Recursive Abstractive Processing for Tree-Organized Retrieval) builds a tree of summaries — clusters of chunks are summarised by an LLM, those summaries are clustered and summarised again, repeating until the entire corpus is represented by a small number of high-level summaries. At query time, RAPTOR retrieves from all levels of the tree simultaneously. A specific factual question finds its answer in a leaf chunk. A broad thematic question (“what are the main arguments in this corpus?”) finds relevant material in the high-level summary nodes that capture themes across many documents.
Figure 1 — RAPTOR, HyDE, and RAG Fusion: When Each Technique Helps
These three techniques — RAPTOR, HyDE, and RAG Fusion — are not mutually exclusive. A production RAG system might use RAPTOR for the index (leaf chunks plus summary nodes), RAG Fusion at query time (multiple query variants), and reranking to select the final context (the previou …[shortened in trace]
```

**Step 10 · THOUGHT** _(t=40.6s)_

```
I have obtained a comparative overview of Raptor RAG and HyDE, highlighting their unique approaches and how they can be integrated into retrieval systems. I will save this finding to my notes. After that, I will check if I need any additional information or if I can conclude my research.
```

**Step 10 · ACTION** _(t=40.6s)_

```
save_note {"note": "Raptor RAG builds a hierarchical tree of summaries from document chunks, allowing retrieval from multiple levels simultaneously, which is beneficial for both specific and broad queries. HyDE generates a hypothetical document at query time to improve embedding and retrieval accuracy. Both techniques can be used together in a retrieval system to enhance performance, addressing different limitations of standard RAG.", "source_ids": [11]}
```

**Step 10 · OBSERVATION** _(t=40.6s)_

```
Saved note #3 (sources [11]). Total notes: 3.
```

**Step 11 · THOUGHT** _(t=44.0s)_

```
I have successfully saved notes on Raptor RAG, HyDE, and their comparison. The notes cover their architectures, functionalities, and how they can be integrated into retrieval systems. I now have enough information to answer the research question comprehensively. I will proceed to finish the research.
```

**Step 11 · ACTION** _(t=44.0s)_

```
finish {"reason": "I have gathered sufficient information on Raptor RAG and HyDE, including their functionalities, advantages, and a comparative analysis."}
```

**SYSTEM** _(t=44.0s)_

```
Loop stopped after 11 step(s): agent decided goal was met (I have gathered sufficient information on Raptor RAG and HyDE, including their functionalities, advantages, and a comparative analysis.)
```

**FINAL** _(t=46.9s)_

```
# Compare Raptor RAG vs HyDE

## Summary
Raptor RAG and HyDE are two advanced retrieval techniques that enhance the accuracy of document retrieval systems. Raptor RAG organizes document chunks into a hierarchical tree structure, which allows for improved retrieval accuracy by enabling searches at multiple levels, making it particularly effective for complex queries across long documents. In contrast, HyDE generates a hypothetical document at query time, reshaping the search geometry to improve retrieval accuracy without altering the underlying index. Both methods can be integrated to leverage their strengths and address the limitations of standard retrieval-augmented generation (RAG) systems.

## Key Findings
- Raptor RAG uses a hierarchical tree structure for document chunks, enhancing retrieval accuracy and allowing simultaneous searches at multiple levels [1, 11].
- HyDE generates a hypothetical document at query time, improving embedding and retrieval accuracy by reshaping the search geometry [8, 11].
- Both Raptor RAG and HyDE can be combined in a retrieval system to enhance overall performance [11].

## Limitations
- Raptor RAG requires constant updates and may experience document ingestion errors [1].
- The specific performance metrics or comparative effectiveness of Raptor RAG and HyDE in various scenarios were not confirmed.

## Sources
[1] Raptor RAG explained: A full guide to hierarchical retrieval — https://www.meilisearch.com/blog/raptor-rag  
[8] What Is HyDE? How to Improve RAG with Hypothetical Documents — https://www.freecodecamp.org/news/what-is-hyde-how-to-improve-rag-with-hypothetical-documents/  
[11] RAPTOR, HyDE and RAG Fusion Explained: Three Advanced ... — https://mljourney.com/raptor-hyde-and-rag-fusion-explained-three-advanced-retrieval-techniques/  
```

**SYSTEM** _(t=47.0s)_

```
Saved to long-term memory (upstash) with id 7df85a84
```

## Final output

# Compare Raptor RAG vs HyDE

## Summary
Raptor RAG and HyDE are two advanced retrieval techniques that enhance the accuracy of document retrieval systems. Raptor RAG organizes document chunks into a hierarchical tree structure, which allows for improved retrieval accuracy by enabling searches at multiple levels, making it particularly effective for complex queries across long documents. In contrast, HyDE generates a hypothetical document at query time, reshaping the search geometry to improve retrieval accuracy without altering the underlying index. Both methods can be integrated to leverage their strengths and address the limitations of standard retrieval-augmented generation (RAG) systems.

## Key Findings
- Raptor RAG uses a hierarchical tree structure for document chunks, enhancing retrieval accuracy and allowing simultaneous searches at multiple levels [1, 11].
- HyDE generates a hypothetical document at query time, improving embedding and retrieval accuracy by reshaping the search geometry [8, 11].
- Both Raptor RAG and HyDE can be combined in a retrieval system to enhance overall performance [11].

## Limitations
- Raptor RAG requires constant updates and may experience document ingestion errors [1].
- The specific performance metrics or comparative effectiveness of Raptor RAG and HyDE in various scenarios were not confirmed.

## Sources
[1] Raptor RAG explained: A full guide to hierarchical retrieval — https://www.meilisearch.com/blog/raptor-rag  
[8] What Is HyDE? How to Improve RAG with Hypothetical Documents — https://www.freecodecamp.org/news/what-is-hyde-how-to-improve-rag-with-hypothetical-documents/  
[11] RAPTOR, HyDE and RAG Fusion Explained: Three Advanced ... — https://mljourney.com/raptor-hyde-and-rag-fusion-explained-three-advanced-retrieval-techniques/  