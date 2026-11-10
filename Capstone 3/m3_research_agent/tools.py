"""
tools.py - the agent's "hands".

The model can only THINK. To actually do anything it asks our code to run
a tool. This file has the four tools from the brief:

    1. web_search       - find pages about a query
    2. fetch_page       - download a web page
    3. extract_content  - turn messy HTML into clean, relevant text
    4. CitationTracker  - give every source a number [1], [2]... so the
                          final summary can cite them and we can check them

Each tool returns a plain string. That string becomes the "Observation"
the model reads on its next turn.
"""

import os
import re

import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (compatible; M3-Research-Agent/1.0; learning project)"


# ---------------------------------------------------------------------------
# 4. Citation tracker
# ---------------------------------------------------------------------------
class CitationTracker:
    """Keeps one numbered entry per unique URL."""

    def __init__(self):
        self.sources: dict[int, dict] = {}   # id -> {url, title, snippet, fetched}
        self._by_url: dict[str, int] = {}

    def add(self, url: str, title: str = "", snippet: str = "") -> int:
        url = url.strip()
        if url in self._by_url:
            sid = self._by_url[url]
            if title and not self.sources[sid]["title"]:
                self.sources[sid]["title"] = title
            if snippet and len(snippet) > len(self.sources[sid]["snippet"]):
                self.sources[sid]["snippet"] = snippet
            return sid
        sid = len(self.sources) + 1
        self.sources[sid] = {"url": url, "title": title or url, "snippet": snippet, "fetched": False}
        self._by_url[url] = sid
        return sid

    def id_for(self, url: str) -> int | None:
        return self._by_url.get(url.strip())

    def cited_ids(self, text: str) -> list[int]:
        """Find every [n] or [n, m] in a piece of text."""
        ids = []
        for group in re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", text):
            for n in group.split(","):
                n = int(n)
                if n not in ids:
                    ids.append(n)
        return ids

    def remove_invalid_citations(self, text: str) -> tuple[str, list[int]]:
        """Delete citations that point at sources we never saw (hallucinated numbers)."""
        bad = [n for n in self.cited_ids(text) if n not in self.sources]

        def fix(match):
            keep = [n.strip() for n in match.group(1).split(",") if int(n) in self.sources]
            return f"[{', '.join(keep)}]" if keep else ""

        cleaned = re.sub(r"\[(\d+(?:\s*,\s*\d+)*)\]", fix, text)
        return cleaned, bad

    def sources_markdown(self, only_ids: list[int] | None = None) -> str:
        ids = only_ids if only_ids is not None else list(self.sources)
        lines = []
        for sid in sorted(ids):
            s = self.sources.get(sid)
            if s:
                lines.append(f"[{sid}] {s['title']} — {s['url']}")
        return "\n".join(lines) if lines else "(no sources)"


# ---------------------------------------------------------------------------
# 1. Web search
# ---------------------------------------------------------------------------
def _search_tavily(query: str, max_results: int) -> list[dict]:
    from tavily import TavilyClient
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    data = client.search(query=query, max_results=max_results, search_depth="basic")
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""),
         "snippet": r.get("content", ""), "score": r.get("score")}
        for r in data.get("results", [])
    ]


def _search_duckduckgo(query: str, max_results: int) -> list[dict]:
    from ddgs import DDGS
    results = DDGS().text(query, max_results=max_results)
    return [
        {"title": r.get("title", ""), "url": r.get("href", ""),
         "snippet": r.get("body", ""), "score": None}
        for r in results
    ]


def web_search(query: str, tracker: CitationTracker, max_results: int = 5) -> str:
    """
    Search the web. Uses Tavily if TAVILY_API_KEY is set, otherwise DuckDuckGo (no key needed).
    Also checks whether the results look weak so the agent knows to try again.
    """
    query = (query or "").strip()
    if not query:
        return "ERROR: web_search needs a non-empty 'query'."

    engine = "tavily" if os.getenv("TAVILY_API_KEY") else "duckduckgo"
    try:
        results = _search_tavily(query, max_results) if engine == "tavily" else _search_duckduckgo(query, max_results)
    except Exception as e:
        return f"ERROR: search failed ({engine}): {e}. Try a simpler query."

    results = [r for r in results if r["url"]]
    if not results:
        return ("No results found. QUALITY WARNING: try a shorter query, different keywords, "
                "or the full name of the technique.")

    lines = [f"Search results for '{query}' (engine: {engine}):"]
    for r in results:
        sid = tracker.add(r["url"], r["title"], r["snippet"])
        snippet = re.sub(r"\s+", " ", r["snippet"])[:300]
        lines.append(f"[{sid}] {r['title']}\n    URL: {r['url']}\n    {snippet}")

    # --- self-correction signal: are these results any good? ---
    warning = _weak_results_warning(query, results)
    if warning:
        lines.append(warning)
    return "\n".join(lines)


def _weak_results_warning(query: str, results: list[dict]) -> str:
    """Simple heuristics. No AI needed - just rules of thumb."""
    reasons = []
    if len(results) < 2:
        reasons.append("fewer than 2 results")

    scores = [r["score"] for r in results if r["score"] is not None]
    if scores and max(scores) < 0.3:
        reasons.append("low relevance scores")

    # Do the snippets even mention the important words from the query?
    keywords = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", query)]
    if keywords:
        text = " ".join((r["title"] + " " + r["snippet"]).lower() for r in results)
        hits = sum(1 for k in keywords if k in text)
        if hits / len(keywords) < 0.5:
            reasons.append("snippets don't mention most of the query keywords")

    if reasons:
        return ("QUALITY WARNING: results look weak (" + "; ".join(reasons) +
                "). Consider rephrasing the query or searching for each concept separately.")
    return ""


# ---------------------------------------------------------------------------
# 2. Page fetch   +   3. Content extraction
# ---------------------------------------------------------------------------
def fetch_html(url: str, timeout: int = 15) -> tuple[str, str]:
    """Download a page. Returns (html, error_message). One of them is empty."""
    # arXiv PDFs are common for research questions; the /abs/ page is readable HTML.
    url = re.sub(r"arxiv\.org/pdf/([\w.]+?)(v\d+)?(\.pdf)?$", r"arxiv.org/abs/\1", url)
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        return "", f"could not download ({e})"
    ctype = resp.headers.get("Content-Type", "")
    if "html" not in ctype and "text" not in ctype:
        return "", f"not a web page (Content-Type: {ctype}). Try a different URL."
    return resp.text, ""


def extract_content(html: str, focus: str = "", max_chars: int = 3500) -> tuple[str, str]:
    """
    Clean HTML -> readable text, then keep the paragraphs most related to `focus`.
    Returns (title, text).
    """
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""

    # Throw away the parts of a page that are never the actual content.
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg"]):
        tag.decompose()

    main = soup.find("article") or soup.find("main") or soup.body or soup
    blocks = [b.get_text(" ", strip=True) for b in main.find_all(["h1", "h2", "h3", "p", "li", "blockquote"])]
    blocks = [re.sub(r"\s+", " ", b) for b in blocks if len(b) > 40]
    if not blocks:  # some pages don't use <p> tags
        blocks = [re.sub(r"\s+", " ", main.get_text(" ", strip=True))]

    if focus:
        blocks = _most_relevant(blocks, focus, max_chars)

    text = "\n".join(blocks)
    if len(text) > max_chars:
        text = text[:max_chars] + " …[truncated]"
    return title, text


def _most_relevant(blocks: list[str], focus: str, max_chars: int) -> list[str]:
    """Score each paragraph by how many focus words it contains; keep the best, in original order."""
    words = set(w.lower() for w in re.findall(r"[A-Za-z]{3,}", focus))
    if not words:
        return blocks
    scored = [(sum(1 for w in words if w in b.lower()), i, b) for i, b in enumerate(blocks)]
    scored.sort(key=lambda x: (-x[0], x[1]))
    chosen, total = [], 0
    for score, i, b in scored:
        if total + len(b) > max_chars and chosen:
            break
        chosen.append((i, b))
        total += len(b)
    return [b for i, b in sorted(chosen)]


def fetch_page(url: str, tracker: CitationTracker, focus: str = "") -> str:
    """The tool the agent actually calls: fetch + extract + register the citation."""
    url = (url or "").strip()
    if not url.startswith("http"):
        return "ERROR: fetch_page needs a full 'url' starting with http(s)://"
    html, error = fetch_html(url)
    if error:
        return f"ERROR fetching {url}: {error}"
    title, text = extract_content(html, focus=focus)
    sid = tracker.add(url, title, text[:500])
    tracker.sources[sid]["fetched"] = True
    if len(text) < 200:
        return (f"[{sid}] {title}\nVery little readable text was found on this page "
                f"(it may need JavaScript). QUALITY WARNING: try another source.")
    return f"[{sid}] {title}\nURL: {url}\n---\n{text}"
