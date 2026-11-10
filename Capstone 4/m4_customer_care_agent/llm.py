"""
llm.py - OpenAI function calling, wrapped in a tiny class.

The agent only needs one method: complete(messages, tools) -> LLMReply.
That makes it easy to swap in a FakeLLM for testing (see test_offline.py).
"""

import os
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str          # a JSON string, exactly as the model wrote it


@dataclass
class LLMReply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens: int = 0


class OpenAIChat:
    def __init__(self, model: str | None = None):
        from openai import OpenAI
        self.client = OpenAI(timeout=60)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.strict = os.getenv("STRICT_TOOLS", "true").lower() == "true"
        self.use_temperature = True

    def complete(self, messages: list[dict], tools: list) -> LLMReply:
        kwargs = dict(model=self.model, messages=messages,
                      tools=[t.openai_spec(strict=self.strict) for t in tools],
                      parallel_tool_calls=True)      # let the model ask for several tools at once
        if self.use_temperature:
            kwargs["temperature"] = 0.1
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except Exception as e:
            msg = str(e).lower()
            if "temperature" in msg:
                self.use_temperature = False
            elif self.strict and ("schema" in msg or "strict" in msg):
                print("⚠️  Model rejected strict schemas - retrying with strict=False "
                      "(our Pydantic validators still enforce every argument).")
                self.strict = False
            else:
                raise
            return self.complete(messages, tools)

        m = resp.choices[0].message
        calls = [ToolCall(tc.id, tc.function.name, tc.function.arguments) for tc in (m.tool_calls or [])]
        return LLMReply(m.content or "", calls, resp.usage.total_tokens if resp.usage else 0)
