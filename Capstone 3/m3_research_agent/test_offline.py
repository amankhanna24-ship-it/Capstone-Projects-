"""
test_offline.py - run the whole agent WITHOUT any API keys or internet.

How: we swap in a FakeLLM that replies with pre-written Thought/Action text,
and fake search/fetch tools that return canned results. Everything else -
the parser, the loop, the budgets, citations, memory - is the real code.

Run:  python test_offline.py
If you see "ALL TESTS PASSED" your setup and the loop logic are working.
"""

import os
import tempfile

import m3_react_agent as agent_mod
from memory import LongTermMemory, ShortTermMemory
from tools import CitationTracker, extract_content

# Make sure the test never touches real Redis
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)


class FakeLLM:
    provider, model = "fake", "scripted"

    def __init__(self, replies):
        self.replies = list(replies)

    def chat(self, system, messages, max_tokens=1000, stop=None, temperature=0.2):
        if "Summarizer" in system:
            return ("## Summary\nRAPTOR builds a tree of summaries [1]; HyDE writes a fake answer first [2].\n"
                    "## Key Findings\n- Made-up citation should be removed [99]"), 300
        return self.replies.pop(0), 500


def fake_search(query, tracker, max_results=5):
    a = tracker.add("https://arxiv.org/abs/2401.18059", "RAPTOR paper", "recursive tree summaries")
    b = tracker.add("https://arxiv.org/abs/2212.10496", "HyDE paper", "hypothetical document embeddings")
    return f"[{a}] RAPTOR paper\n[{b}] HyDE paper"


def fake_fetch(url, tracker, focus=""):
    sid = tracker.add(url)
    return f"[{sid}] page text about {focus}"


SCRIPT = [
    'Thought: Plan: learn RAPTOR, then HyDE, then compare.\nAction: web_search\nAction Input: {"query": "RAPTOR RAG"}',
    'Thought: I will repeat myself by mistake.\nAction: web_search\nAction Input: {"query": "raptor rag"}',
    'Thought: oops, bad JSON coming\nAction: save_note\nAction Input: {note: broken}',
    'Thought: Read the paper.\nAction: fetch_page\nAction Input: {"url": "https://arxiv.org/abs/2401.18059", "focus": "tree"}',
    'Thought: Save it.\nAction: save_note\nAction Input: {"note": "RAPTOR clusters and summarises chunks into a tree", "source_ids": [1, 42]}',
    'Thought: Save HyDE.\nAction: save_note\nAction Input: {"note": "HyDE embeds a hypothetical answer", "source_ids": [2]}',
    'Thought: Enough.\nAction: finish\nAction Input: {"reason": "both covered"}',
]


def run_tests():
    os.chdir(tempfile.mkdtemp())          # write traces/local memory into a throwaway folder
    agent_mod.web_search = fake_search
    agent_mod.fetch_page = fake_fetch

    # 1. full loop
    agent = agent_mod.ResearchAgent(llm=FakeLLM(SCRIPT), max_iterations=10, long_term=LongTermMemory())
    result = agent.run("Compare Raptor RAG vs HyDE")
    s = result["stats"]
    assert s["stop_reason"].startswith("agent decided"), s
    assert s["notes_saved"] == 2, s
    assert "[99]" not in result["summary"], "invalid citation should be removed"
    assert "## Sources" in result["summary"] and "arxiv.org/abs/2401.18059" in result["summary"]
    assert os.path.exists(result["trace_path"])
    print("✓ loop, self-correction, citations, trace file")

    # 2. long-term memory recall on the next run
    hits = LongTermMemory().recall("How does RAPTOR RAG work?")
    assert hits and "Raptor" in hits[0]["question"], hits
    print("✓ long-term memory recall")

    # 3. iteration budget
    looping = ['Thought: again\nAction: web_search\nAction Input: {"query": "q%d"}' % i for i in range(20)]
    r = agent_mod.ResearchAgent(llm=FakeLLM(looping), max_iterations=3, long_term=LongTermMemory()).run("budget test")
    assert r["stats"]["stop_reason"] == "max_iterations reached", r["stats"]
    print("✓ max-iterations budget")

    # 4. token budget
    r = agent_mod.ResearchAgent(llm=FakeLLM(looping), max_iterations=20, max_tokens=1000,
                                long_term=LongTermMemory()).run("token test")
    assert "token budget" in r["stats"]["stop_reason"], r["stats"]
    print("✓ max-tokens budget")

    # 5. short-term memory trimming
    stm = ShortTermMemory(max_context_tokens=300, keep_recent=2)
    stm.add("user", "task")
    for i in range(6):
        stm.add("assistant", "Thought: x")
        stm.add("user", "Observation: " + "long text " * 100)
    assert stm.trim_events > 0 and stm.messages[0]["content"] == "task"
    print("✓ short-term memory trimming")

    # 6. HTML extraction
    html = ("<html><head><title>T</title><script>bad()</script></head><body><nav>menu menu menu menu menu menu menu</nav>"
            "<article><p>HyDE generates a hypothetical document and embeds it for retrieval purposes.</p>"
            "<p>Unrelated paragraph about cooking pasta in salted water for ten minutes.</p></article></body></html>")
    title, text = extract_content(html, focus="hypothetical document embeddings", max_chars=90)
    assert title == "T" and "HyDE" in text and "bad()" not in text and "menu" not in text, text
    print("✓ content extraction")

    # 7. citation tracker de-duplicates URLs
    t = CitationTracker()
    assert t.add("https://a.com") == t.add("https://a.com") == 1
    print("✓ citation de-duplication")

    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    run_tests()
