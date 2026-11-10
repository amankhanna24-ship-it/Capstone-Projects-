"""
memory.py - the agent's memory, in three layers.

    ShortTermMemory  - the conversation the model sees on each turn.
                       It grows every loop, so we trim old tool outputs
                       to stay inside the context window.

    WorkingMemory    - the "notebook": findings the agent chose to save
                       with save_note, each linked to source numbers.
                       The summariser writes the final answer from this.

    LongTermMemory   - Upstash Redis. Survives after the program ends,
                       so next week the agent can say "I researched
                       something similar before - here's what I found".
"""

import json
import os
import re
import time
import uuid


def approx_tokens(text: str) -> int:
    """Rough rule: 1 token ≈ 4 characters of English. Good enough for budgeting."""
    return len(text) // 4 + 1


# ---------------------------------------------------------------------------
# Short-term memory: a managed conversation buffer
# ---------------------------------------------------------------------------
class ShortTermMemory:
    def __init__(self, max_context_tokens: int = 6000, keep_recent: int = 4):
        self.max_context_tokens = max_context_tokens
        self.keep_recent = keep_recent      # always keep the last N messages in full
        self.messages: list[dict] = []
        self.trim_events = 0

    def add(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        self._trim()

    def total_tokens(self) -> int:
        return sum(approx_tokens(m["content"]) for m in self.messages)

    def _trim(self):
        """
        If the buffer is too big, shrink the OLDEST observations first.
        We never touch message 0 (the original task) or the most recent messages.
        """
        i = 1
        while self.total_tokens() > self.max_context_tokens and i < len(self.messages) - self.keep_recent:
            msg = self.messages[i]
            if msg["role"] == "user" and msg["content"].startswith("Observation:") \
                    and not msg["content"].startswith("Observation: [trimmed"):
                preview = re.sub(r"\s+", " ", msg["content"][len("Observation:"):]).strip()[:150]
                msg["content"] = (f"Observation: [trimmed to save context - you already read this. "
                                  f"Started with: {preview}] "
                                  f"Anything important should already be in your saved notes.")
                self.trim_events += 1
            i += 1


# ---------------------------------------------------------------------------
# Working memory: the agent's notebook of findings
# ---------------------------------------------------------------------------
class WorkingMemory:
    def __init__(self):
        self.notes: list[dict] = []

    def save(self, note: str, source_ids: list[int]) -> str:
        note = (note or "").strip()
        if not note:
            return "ERROR: save_note needs a non-empty 'note'."
        self.notes.append({"note": note, "source_ids": source_ids})
        return f"Saved note #{len(self.notes)} (sources {source_ids}). Total notes: {len(self.notes)}."

    def as_text(self) -> str:
        if not self.notes:
            return "(no notes saved yet)"
        return "\n".join(f"- {n['note']} " + "".join(f"[{s}]" for s in n["source_ids"]) for n in self.notes)


# ---------------------------------------------------------------------------
# Long-term memory: Upstash Redis (with a local-file fallback for practice)
# ---------------------------------------------------------------------------
class LongTermMemory:
    """
    Stores every finished research task in ONE Redis hash:
        key   = "m3:research"
        field = a short random id
        value = JSON {question, summary, sources, timestamp}
    """

    KEY = "m3:research"

    def __init__(self):
        url = os.getenv("UPSTASH_REDIS_REST_URL")
        token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
        self.backend = "upstash"
        self.redis = None
        self.local_path = "local_memory.json"
        if url and token:
            from upstash_redis import Redis
            self.redis = Redis(url=url, token=token)
        else:
            self.backend = "local-file"
            print("⚠️  UPSTASH_REDIS_REST_URL/TOKEN not set - using local_memory.json instead. "
                  "Set them in .env for the real submission.")

    # --- low-level read/write -------------------------------------------------
    def _all(self) -> dict[str, dict]:
        if self.redis:
            raw = self.redis.hgetall(self.KEY) or {}
        else:
            raw = json.load(open(self.local_path)) if os.path.exists(self.local_path) else {}
        out = {}
        for k, v in raw.items():
            try:
                out[k] = json.loads(v) if isinstance(v, str) else v
            except json.JSONDecodeError:
                pass
        return out

    def _put(self, item_id: str, item: dict):
        value = json.dumps(item)
        if self.redis:
            self.redis.hset(self.KEY, item_id, value)
        else:
            data = json.load(open(self.local_path)) if os.path.exists(self.local_path) else {}
            data[item_id] = value
            json.dump(data, open(self.local_path, "w"), indent=2)

    # --- what the agent uses ----------------------------------------------------
    def save_research(self, question: str, summary: str, sources: list[str]) -> str:
        item_id = uuid.uuid4().hex[:8]
        self._put(item_id, {
            "question": question,
            "summary": summary[:3000],      # keep memory compact
            "sources": sources[:15],
            "timestamp": time.strftime("%Y-%m-%d %H:%M"),
        })
        return item_id

    def recall(self, question: str, k: int = 2, min_overlap: float = 0.25) -> list[dict]:
        """
        Find past research on a similar topic using simple keyword overlap.
        (A later improvement would be embeddings - but this keeps it easy to understand.)
        """
        q_words = _keywords(question)
        if not q_words:
            return []
        scored = []
        for item in self._all().values():
            overlap = len(q_words & _keywords(item.get("question", ""))) / len(q_words)
            if overlap >= min_overlap:
                scored.append((overlap, item))
        scored.sort(key=lambda x: -x[0])
        return [item for _, item in scored[:k]]

    def list_topics(self) -> list[dict]:
        items = list(self._all().values())
        return sorted(items, key=lambda x: x.get("timestamp", ""), reverse=True)


STOPWORDS = {"the", "and", "for", "with", "what", "how", "does", "are", "between", "compare",
             "versus", "about", "from", "this", "that", "which", "into", "their", "vs"}


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", text.lower()) if w not in STOPWORDS}
