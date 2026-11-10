"""
llm.py - a tiny wrapper so the agent can talk to OpenAI OR Claude.

Why this file exists:
    The ReAct loop should not care which company's model it uses.
    It just calls `llm.chat(...)` and gets back (text, tokens_used).
    This is the same "one interface, many SDKs" idea from Module 1.

We use the raw SDKs here on purpose (no LangChain) because the assignment
asks for a ReAct agent "from scratch, no high-level abstractions".
"""

import os


class LLM:
    def __init__(self, provider: str | None = None, model: str | None = None):
        self.provider = (provider or os.getenv("LLM_PROVIDER", "openai")).lower()

        if self.provider == "openai":
            from openai import OpenAI
            self.client = OpenAI(timeout=60)  # reads OPENAI_API_KEY from the environment
            self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        elif self.provider in ("anthropic", "claude"):
            import anthropic
            self.provider = "anthropic"
            self.client = anthropic.Anthropic(timeout=60)  # reads ANTHROPIC_API_KEY
            self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
        else:
            raise ValueError(f"Unknown LLM_PROVIDER '{self.provider}'. Use 'openai' or 'anthropic'.")

    def chat(self, system: str, messages: list[dict], max_tokens: int = 1000,
             stop: list[str] | None = None, temperature: float = 0.2) -> tuple[str, int]:
        """
        Send a conversation to the model.

        system   - the instructions (who the model is, what format to use)
        messages - [{"role": "user"|"assistant", "content": "..."}]
        stop     - text that makes the model stop writing. We stop at
                   "Observation:" so the MODEL never invents tool results;
                   only OUR code is allowed to write observations.

        Returns (reply_text, total_tokens_used_by_this_call)
        """
        if self.provider == "openai":
            kwargs = dict(
                model=self.model,
                messages=[{"role": "system", "content": system}] + messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if stop:
                kwargs["stop"] = stop
            try:
                resp = self.client.chat.completions.create(**kwargs)
            except Exception as e:
                # Some newer models reject 'stop'/'temperature'/'max_tokens'. Retry with the basics.
                if any(word in str(e) for word in ("stop", "temperature", "max_tokens")):
                    kwargs.pop("stop", None)
                    kwargs.pop("temperature", None)
                    kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                    resp = self.client.chat.completions.create(**kwargs)
                else:
                    raise
            text = resp.choices[0].message.content or ""
            used = resp.usage.total_tokens if resp.usage else 0

        else:  # anthropic
            kwargs = dict(
                model=self.model,
                system=system,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if stop:
                kwargs["stop_sequences"] = stop
            resp = self.client.messages.create(**kwargs)
            text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
            used = resp.usage.input_tokens + resp.usage.output_tokens

        # Belt and braces: if the model ignored the stop word, cut it off ourselves.
        if stop:
            for s in stop:
                if s in text:
                    text = text.split(s)[0]
        return text.strip(), used
