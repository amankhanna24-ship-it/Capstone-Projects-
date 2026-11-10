"""
bonus_langgraph_agent.py - the SAME research agent, built with LangGraph.

Why include this?  So you can compare:
    m3_react_agent.py       ~300 lines, every step visible (from scratch)
    this file               ~70 lines, LangGraph runs the loop for you

Same tools, same citation tracker. LangGraph's prebuilt ReAct agent uses the
model's native "tool calling" instead of our text Thought/Action format.

Run:  python bonus_langgraph_agent.py "Compare Raptor RAG vs HyDE"
"""

import os
import sys

from dotenv import load_dotenv
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from tools import CitationTracker, fetch_page as _fetch_page, web_search as _web_search

load_dotenv()
tracker = CitationTracker()


@tool
def web_search(query: str) -> str:
    """Search the web. Results are numbered [n] so you can cite them."""
    return _web_search(query, tracker)


@tool
def fetch_page(url: str, focus: str = "") -> str:
    """Read a web page. 'focus' says what you are looking for so only relevant text is returned."""
    return _fetch_page(url, tracker, focus=focus)


def get_model():
    if os.getenv("LLM_PROVIDER", "openai").lower() == "anthropic":
        from langchain_anthropic import ChatAnthropic   # pip install langchain-anthropic
        return ChatAnthropic(model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5"), temperature=0.2)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0.2)


PROMPT = ("You are a research agent. Search, read at least 2 pages, then write a markdown summary "
          "with inline citations like [1] using the numbers shown in tool results. "
          "Do not write a sources list; it is added automatically.")


def main():
    question = sys.argv[1] if len(sys.argv) > 1 else "Compare Raptor RAG vs HyDE"
    agent = create_react_agent(get_model(), tools=[web_search, fetch_page], prompt=PROMPT)

    # recursion_limit is LangGraph's version of our max_iterations budget
    result = agent.invoke({"messages": [("user", question)]}, config={"recursion_limit": 20})

    for msg in result["messages"]:           # print the trace
        kind = type(msg).__name__
        calls = getattr(msg, "tool_calls", None)
        print(f"--- {kind} ---\n{calls if calls else str(msg.content)[:600]}\n")

    answer = result["messages"][-1].content
    cited = tracker.cited_ids(answer)
    print("\n=== FINAL ===\n" + answer + "\n\n## Sources\n" + tracker.sources_markdown(cited))


if __name__ == "__main__":
    main()
