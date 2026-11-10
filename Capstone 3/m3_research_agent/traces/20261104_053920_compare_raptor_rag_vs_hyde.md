# Run trace: Compare Raptor RAG vs HyDE

## Run statistics

| Metric | Value |
|---|---|
| question | Compare Raptor RAG vs HyDE |
| model | openai/gpt-4o-mini |
| steps_used | 9 / 12 |
| tokens_used | 24046 / 80000 |
| seconds | 26 / 20 |
| stop_reason | agent decided goal was met (I have gathered and compared detailed information on Raptor RAG and HyDE, covering their methodologies, advantages, and limitations.) |
| notes_saved | 2 |
| sources_seen | 10 |
| sources_cited | 2 |
| context_trims | 0 |
| long_term_memory | upstash |

## Reasoning loop (Thought → Action → Observation)

**SYSTEM** _(t=0.1s)_

```
Recalled 2 past research item(s) from upstash: Compare Raptor RAG vs HyDE; Compare Raptor RAG vs HyDE
```

**Step 1 · THOUGHT** _(t=2.5s)_

```
I need to gather detailed information about both Raptor RAG and HyDE to compare their methodologies, advantages, and use cases. I will start by searching for specific details about Raptor RAG and then do the same for HyDE. This will help me understand their differences and similarities better.
```

**Step 1 · ACTION** _(t=2.5s)_

```
web_search {"query": "Raptor RAG retrieval technique details"}
```

**Step 1 · OBSERVATION** _(t=4.1s)_

```
Search results for 'Raptor RAG retrieval technique details' (engine: duckduckgo):
[1] RAPTOR RAG Explained: Building Hierarchical Retrieval for Smarter AI ...
    URL: https://machinelearningplus.com/gen-ai/raptor-rag-explained-building-hierarchical-retrieval-for-smarter-ai-answers/
    RAPTOR RAG Explained: Building Hierarchical Retrieval for Smarter AI Answers RAPTOR (Recursive Abstractive Processing for Tree-Organized Retrieval) is an advanced RAG technique that creates hierarchical tree structures from your documents, allowing you to retrieve information at different levels of 
[2] Raptor RAG explained: A full guide to hierarchical retrieval
    URL: https://www.meilisearch.com/blog/raptor-rag
    Raptor RAG explained: A full guide to hierarchical retrieval Learn what RAPTOR RAG is, how it differs from other RAG methods, and how to implement it in Python.
[3] GitHub - profintegra/raptor-rag: The official implementation of RAPTOR ...
    URL: https://github.com/profintegra/raptor-rag
    RAPTOR introduces a novel approach to retrieval-augmented language models by constructing a recursive tree structure from documents. This allows for more efficient and context-aware information retrieval across large texts, addressing common limitations in traditional language models. For detailed m
[4] RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval
    URL: https://arxiv.org/html/2401.18059v1
    At inference time, our RAPTOR model retrieves from this tree, integrat …[shortened in trace]
```

**Step 2 · THOUGHT** _(t=5.6s)_

```
I found several sources that explain Raptor RAG in detail. I will fetch the first two pages to gather comprehensive information about its structure, advantages, and how it operates. This will help me understand its retrieval mechanism better.
```

**Step 2 · ACTION** _(t=5.6s)_

```
fetch_page {"url": "https://machinelearningplus.com/gen-ai/raptor-rag-explained-building-hierarchical-retrieval-for-smarter-ai-answers/", "focus": "details about Raptor RAG"}
```

**Step 2 · OBSERVATION** _(t=5.9s)_

```
[1] RAPTOR RAG Explained: Building Hierarchical Retrieval for Smarter AI Answers - machinelearningplus
Very little readable text was found on this page (it may need JavaScript). QUALITY WARNING: try another source.
```

**Step 3 · THOUGHT** _(t=7.2s)_

```
The first page did not provide useful information due to a quality warning. I will now fetch the second source, which is likely to have more accessible content about Raptor RAG.
```

**Step 3 · ACTION** _(t=7.2s)_

```
fetch_page {"url": "https://www.meilisearch.com/blog/raptor-rag", "focus": "details about Raptor RAG"}
```

**Step 3 · OBSERVATION** _(t=8.1s)_

```
[2] Raptor RAG explained: A full guide to hierarchical retrieval | Meilisearch
URL: https://www.meilisearch.com/blog/raptor-rag
---
In 2024, researchers at Stanford published a new standard for chunking and organization called Recursive Abstractive Processing for Tree-Organized Retrieval (RAPTOR).
RAPTOR changes the way retrieval-augmented generation (RAG) works with chunked documents. Instead of creating chunks and storing them randomly, RAPTOR creates a hierarchical tree structure of chunks, categorizes them, and writes summaries for each group.
RAPTOR gives users more precise answers because hierarchical summaries contain high-level information that LLMs can search.
More precise details are contained in each 'leaf' of the tree. To find answers, the LLM searches summaries and then drills down into the data contained in branches and leaves.
Here's how to effectively use RAPTOR in your RAG systems.
RAPTOR RAG changes how document chunks are organized for large-language-model processing. Instead of chunking documents into individual sections, RAPTOR RAG stores the chunks as a tree.
Imagine that you have several chunks for a dozen documents. RAPTOR RAG takes the chunks and organizes them by category.
Because chunked data is organized into a tree, using RAPTOR RAG also improves the accuracy of query answers.
The number of summaries in a RAPTOR RAG depends on the number of documents in your data silos.
How does RAPTOR differ from GraphRAG, CRAG, and other advanced RAG methods?
RA …[shortened in trace]
```

**Step 4 · THOUGHT** _(t=10.0s)_

```
I have gathered detailed information about Raptor RAG, including its structure, advantages, and limitations. Now, I will save a note summarizing these findings. After that, I will search for information on HyDE to compare it with Raptor RAG.
```

**Step 4 · ACTION** _(t=10.0s)_

```
save_note {"note": "Raptor RAG (Recursive Abstractive Processing for Tree-Organized Retrieval) organizes document chunks into a hierarchical tree structure, improving retrieval accuracy for complex queries across long documents. It generates summaries at different levels, allowing for precise answers. However, it requires constant updates for dynamic data and may be too complex for simple queries.", "source_ids": [2]}
```

**Step 4 · OBSERVATION** _(t=10.0s)_

```
Saved note #1 (sources [2]). Total notes: 1.
```

**Step 5 · THOUGHT** _(t=11.4s)_

```
Now that I have information about Raptor RAG, I will search for details about HyDE to understand its methodology, advantages, and how it compares to Raptor RAG.
```

**Step 5 · ACTION** _(t=11.4s)_

```
web_search {"query": "HyDE retrieval technique details"}
```

**Step 5 · OBSERVATION** _(t=14.4s)_

```
Search results for 'HyDE retrieval technique details' (engine: duckduckgo):
[6] HyDE for RAG Explained: How Hypothetical Document Embeddings ...
    URL: https://machinelearningplus.com/gen-ai/hypothetical-document-embedding-hyde-a-smarter-rag-method-to-search-documents/
    Hypothetical Document Embeddings (HyDE) is an advanced technique in information retrieval (IR) for RAG systems designed to improve search accuracy when little or relevant documents exist in the dataset yet.
[7] Advanced RAG Techniques 2026: Reranking, HyDE, Parent-Child ...
    URL: https://mljourney.com/advanced-rag-techniques-2026-reranking-hyde-parent-child-and-more/
    Sep 1, 2026 · Advanced RAG retrieval techniques beyond basic vector search. Covers cross-encoder reranking, HyDE, parent-child chunking, RAG Fusion, and when each improves retrieval quality.
[8] Introduction to Hypothetical Document Embeddings (HyDE)
    URL: https://www.geeksforgeeks.org/data-science/hypothetical-document-embeddings-hyde-hyde/
    Feb 10, 2026 · HyDE (Hypothetical Document Embedding) is an extension of traditional retrieval in Retrieval Augmented Generation (RAG) where the system generates a hypothetical document before retrieval. Instead of converting queries to embeddings directly, it expands the query with richer context t
[9] GitHub - texttron/hyde: HyDE: Precise Zero-Shot Dense ...
    URL: https://github.com/texttron/hyde
    HyDE: Precise Zero-Shot Dense Retrieval without Relevance Labels This is code repositor …[shortened in trace]
```

**Step 6 · THOUGHT** _(t=16.0s)_

```
I found several sources that discuss HyDE and its methodology. I will fetch the first two pages to gather comprehensive information about HyDE's approach, advantages, and how it operates.
```

**Step 6 · ACTION** _(t=16.0s)_

```
fetch_page {"url": "https://machinelearningplus.com/gen-ai/hypothetical-document-embedding-hyde-a-smarter-rag-method-to-search-documents/", "focus": "details about HyDE"}
```

**Step 6 · OBSERVATION** _(t=16.3s)_

```
[6] HyDE for RAG Explained: How Hypothetical Document Embeddings Boost Retrieval Accuracy
Very little readable text was found on this page (it may need JavaScript). QUALITY WARNING: try another source.
```

**Step 7 · THOUGHT** _(t=17.8s)_

```
The first page did not provide useful information due to a quality warning. I will now fetch the second source, which may have more accessible content about HyDE.
```

**Step 7 · ACTION** _(t=17.8s)_

```
fetch_page {"url": "https://www.geeksforgeeks.org/data-science/hypothetical-document-embeddings-hyde-hyde/", "focus": "details about HyDE"}
```

**Step 7 · OBSERVATION** _(t=17.9s)_

```
[8] Introduction  to Hypothetical Document Embeddings (HyDE) - GeeksforGeeks
URL: https://www.geeksforgeeks.org/data-science/hypothetical-document-embeddings-hyde-hyde/
---
Python Libraries for AI, ML, DL and Data Science
Difference between Structured, Semi-structured and Unstructured data
EDA - Exploratory Data Analysis in Python
Probability Distributions in Data Science
ANOVA for Data Science and Data Analytics
Feature Selection Techniques in Machine Learning
Feature Engineering - Scaling, Normalization and Standardization
Data Science Interview Questions and Answers
Introduction to Hypothetical Document Embeddings (HyDE)
HyDE (Hypothetical Document Embedding) is an extension of traditional retrieval in Retrieval Augmented Generation (RAG) where the system generates a hypothetical document before retrieval. Instead of converting queries to embeddings directly, it expands the query with richer context to improve semantic understanding and retrieval accuracy.
Generates a hypothetical document to enrich the query context
Improves understanding of short or ambiguous queries
Focuses on semantic meaning rather than keywords
Helps produce more accurate responses in RAG pipelines
This approach helps overcome the limitations of short or ambiguous queries by adding richer semantic context, leading to more accurate retrieval results.
Traditional semantic retrieval systems typically convert the user’s query directly into an embedding and search for similar documents. While this approac …[shortened in trace]
```

**Step 8 · THOUGHT** _(t=19.6s)_

```
I have gathered detailed information about HyDE, including its methodology, advantages, and how it addresses limitations in traditional retrieval systems. I will save a note summarizing these findings. After that, I will compare the two techniques based on the information I have collected.
```

**Step 8 · ACTION** _(t=19.6s)_

```
save_note {"note": "HyDE (Hypothetical Document Embedding) enhances traditional retrieval in RAG by generating a hypothetical document based on the user's query, enriching the context for better semantic understanding. This approach addresses issues with short or ambiguous queries, improving retrieval accuracy by focusing on semantic meaning rather than keywords.", "source_ids": [8]}
```

**Step 8 · OBSERVATION** _(t=19.6s)_

```
Saved note #2 (sources [8]). Total notes: 2.
```

**Step 9 · THOUGHT** _(t=22.6s)_

```
I now have notes on both Raptor RAG and HyDE, detailing their methodologies and advantages. I will compare the two techniques based on their retrieval mechanisms, strengths, and weaknesses to provide a comprehensive comparison.

1. **Raptor RAG**:
   - Organizes document chunks into a hierarchical tree structure.
   - Improves retrieval accuracy for complex queries across long documents.
   - Generates summaries at different levels, allowing for precise answers.
   - Requires constant updates for dynamic data and may be too complex for simple queries.

2. **HyDE**:
   - Generates a hypothetical document based on the user's query to enrich context.
   - Improves understanding of short or ambiguous queries by focusing on semantic meaning.
   - Addresses limitations of traditional retrieval systems by capturing deeper semantic meaning.
   - Enhances retrieval accuracy by converting the enriched query into an embedding for better matching.

Both techniques aim to improve retrieval accuracy but approach the problem differently. Raptor RAG focuses on organizing existing information hierarchically, while HyDE enhances the query itself to improve retrieval outcomes.

I will now finalize my research as I have sufficient notes to answer the comparison question.
```

**Step 9 · ACTION** _(t=22.6s)_

```
finish {"reason": "I have gathered and compared detailed information on Raptor RAG and HyDE, covering their methodologies, advantages, and limitations."}
```

**SYSTEM** _(t=22.6s)_

```
Loop stopped after 9 step(s): agent decided goal was met (I have gathered and compared detailed information on Raptor RAG and HyDE, covering their methodologies, advantages, and limitations.)
```

**FINAL** _(t=26.1s)_

```
# Compare Raptor RAG vs HyDE

## Summary
Raptor RAG and HyDE are two advanced retrieval techniques that enhance the accuracy of information retrieval. Raptor RAG organizes document chunks into a hierarchical tree structure, which improves retrieval for complex queries but may be overly complex for simpler ones and requires constant updates for dynamic data [2]. In contrast, HyDE generates a hypothetical document based on user queries, focusing on semantic meaning to improve retrieval accuracy, particularly for short or ambiguous queries [8].

## Key Findings
- Raptor RAG improves retrieval accuracy for complex queries through a hierarchical tree structure and generates summaries at different levels [2].
- Raptor RAG may be too complex for simple queries and requires constant updates for dynamic data [2].
- HyDE enhances traditional retrieval by generating a hypothetical document that enriches context and focuses on semantic understanding [8].
- HyDE addresses issues with short or ambiguous queries, improving retrieval accuracy by emphasizing semantic meaning over keywords [8].

## Limitations
- The effectiveness of Raptor RAG for simple queries is uncertain due to its complexity [2].
- The performance of HyDE in scenarios with highly structured documents has not been confirmed [8].

## Sources
[2] Raptor RAG explained: A full guide to hierarchical retrieval — https://www.meilisearch.com/blog/raptor-rag  
[8] Introduction to Hypothetical Document Embeddings (HyDE) — https://www.geeksforgeeks.org/data-science/hypothetical-document-embeddings-hyde-hyde/  
```

**SYSTEM** _(t=26.3s)_

```
Saved to long-term memory (upstash) with id 3392271c
```

## Final output

# Compare Raptor RAG vs HyDE

## Summary
Raptor RAG and HyDE are two advanced retrieval techniques that enhance the accuracy of information retrieval. Raptor RAG organizes document chunks into a hierarchical tree structure, which improves retrieval for complex queries but may be overly complex for simpler ones and requires constant updates for dynamic data [2]. In contrast, HyDE generates a hypothetical document based on user queries, focusing on semantic meaning to improve retrieval accuracy, particularly for short or ambiguous queries [8].

## Key Findings
- Raptor RAG improves retrieval accuracy for complex queries through a hierarchical tree structure and generates summaries at different levels [2].
- Raptor RAG may be too complex for simple queries and requires constant updates for dynamic data [2].
- HyDE enhances traditional retrieval by generating a hypothetical document that enriches context and focuses on semantic understanding [8].
- HyDE addresses issues with short or ambiguous queries, improving retrieval accuracy by emphasizing semantic meaning over keywords [8].

## Limitations
- The effectiveness of Raptor RAG for simple queries is uncertain due to its complexity [2].
- The performance of HyDE in scenarios with highly structured documents has not been confirmed [8].

## Sources
[2] Raptor RAG explained: A full guide to hierarchical retrieval — https://www.meilisearch.com/blog/raptor-rag  
[8] Introduction to Hypothetical Document Embeddings (HyDE) — https://www.geeksforgeeks.org/data-science/hypothetical-document-embeddings-hyde-hyde/  