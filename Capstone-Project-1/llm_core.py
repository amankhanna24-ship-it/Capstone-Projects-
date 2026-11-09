"""
llm_core.py — the provider-agnostic layer for the Multi-SDK LLM Playground.

The central idea: OpenAI, Gemini and Claude each have their own SDK, with
different method names, message formats and response objects. This module
puts a small adapter in front of each one so that the rest of the project
only ever sees:

    provider.generate(...)            -> LLMResponse
    provider.generate_structured(...) -> (pydantic object, LLMResponse)
    provider.run_tools(...)           -> LLMResponse  (function-calling loop)

Every call, whichever provider served it, is timed, costed and logged to
logs/telemetry.jsonl.

Run with --mock (or MOCK_LLM=1) to use three offline fake providers. That
lets you test the plumbing without API keys or spending money. Mock output
is NOT real model output and must never go in your comparison report.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

LOG_DIR = ROOT / "logs"
TELEMETRY_FILE = LOG_DIR / "telemetry.jsonl"

# A conversation is a list of {"role": "user" | "assistant", "content": str}.
Message = dict[str, str]


# ===========================================================================
# 1. The common answer shape
# ===========================================================================
@dataclass
class LLMResponse:
    provider: str
    model: str
    text: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    cost_usd: float | None          # None when the model has no entry in pricing.json
    tool_trace: list[dict] = field(default_factory=list)  # filled by run_tools()
    raw: Any = field(default=None, repr=False)

    def summary(self) -> str:
        cost = f"${self.cost_usd:.6f}" if self.cost_usd is not None else "cost n/a"
        return (f"[{self.provider} | {self.model}] in={self.input_tokens} "
                f"out={self.output_tokens} tok | {self.latency_s:.2f}s | {cost}")


# ===========================================================================
# 2. Cost telemetry
# ===========================================================================
PRICING_FILE = ROOT / "pricing.json"


def load_pricing() -> dict[str, tuple[float, float]]:
    """Read USD-per-million-token prices from pricing.json.
    Prices change often, so they live in a file you edit, not in the code."""
    if not PRICING_FILE.exists():
        return {}
    data = json.loads(PRICING_FILE.read_text())
    out = {}
    for model, p in data.get("models", {}).items():
        if model.startswith("_"):            # skip the example/comment entries
            continue
        out[model] = (float(p["input_per_million"]), float(p["output_per_million"]))
    return out


PRICING = load_pricing()


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    if model not in PRICING:
        return None
    in_price, out_price = PRICING[model]
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000


def log_telemetry(resp: LLMResponse, kind: str, error: str | None = None) -> None:
    """One JSON line per call: when, who, what kind of call, tokens, time, cost."""
    LOG_DIR.mkdir(exist_ok=True)
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "provider": resp.provider,
        "model": resp.model,
        "input_tokens": resp.input_tokens,
        "output_tokens": resp.output_tokens,
        "latency_s": round(resp.latency_s, 3),
        "cost_usd": resp.cost_usd,
        "error": error,
    }
    with TELEMETRY_FILE.open("a") as f:
        f.write(json.dumps(row) + "\n")


# ===========================================================================
# 3. JSON Schema helper
#    OpenAI's strict mode (and Claude's structured outputs) need every object
#    to list all its properties as required and set additionalProperties
#    to false. Pydantic doesn't do that by default, so we tighten the schema.
# ===========================================================================
def strict_schema(model_cls: type[BaseModel]) -> dict:
    schema = model_cls.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any, is_properties: bool = False) -> Any:
        if isinstance(node, dict):
            if "$ref" in node and not is_properties:   # inline nested models
                return resolve(defs[node["$ref"].split("/")[-1]])
            if is_properties:                          # keys here are field names
                return {k: resolve(v) for k, v in node.items()}
            # drop schema keywords the strict modes dislike ("title" the keyword,
            # not a field called title, which lives under "properties")
            node = {k: resolve(v, is_properties=(k == "properties"))
                    for k, v in node.items() if k not in ("title", "default")}
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"].keys())
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [resolve(x) for x in node]
        return node

    return resolve(schema)


# ===========================================================================
# 4. Tool definition (for function calling)
# ===========================================================================
@dataclass
class Tool:
    name: str
    description: str
    parameters: dict                 # JSON Schema for the arguments
    function: Callable[..., Any]     # the real Python function to run

    def call(self, args: dict) -> Any:
        return self.function(**args)


# ===========================================================================
# 5. The abstraction every provider follows
# ===========================================================================
class LLMProvider(ABC):
    name = "base"

    def __init__(self, model: str):
        self.model = model

    # ---- public methods: timing, costing and logging live here, once ----
    def generate(self, prompt: str | list[Message], system: str | None = None,
                 temperature: float | None = None, max_tokens: int = 1500,
                 json_schema: dict | None = None) -> LLMResponse:
        messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else prompt
        start = time.perf_counter()
        text, in_tok, out_tok, raw = self._call(messages, system, temperature,
                                                max_tokens, json_schema)
        resp = self._package(text, in_tok, out_tok, time.perf_counter() - start, raw)
        log_telemetry(resp, "structured" if json_schema else "text")
        return resp

    def generate_structured(self, prompt: str, model_cls: type[BaseModel],
                            system: str | None = None, retries: int = 1,
                            max_tokens: int = 1500):
        """Ask for JSON matching a Pydantic model, then validate it.
        On a validation failure we retry once, feeding the error back."""
        schema = strict_schema(model_cls)
        messages: list[Message] = [{"role": "user", "content": prompt}]
        last_error = None
        for attempt in range(retries + 1):
            resp = self.generate(messages, system=system, json_schema=schema,
                                 max_tokens=max_tokens)
            try:
                return model_cls.model_validate_json(_strip_fences(resp.text)), resp
            except ValidationError as e:
                last_error = e
                messages = messages + [
                    {"role": "assistant", "content": resp.text},
                    {"role": "user", "content": "That JSON failed validation:\n"
                     f"{e}\nReturn corrected JSON only."},
                ]
        raise last_error  # type: ignore[misc]

    def run_tools(self, prompt: str, tools: list[Tool], system: str | None = None,
                  max_steps: int = 5, max_tokens: int = 1500) -> LLMResponse:
        """The function-calling loop: model asks for a tool -> we run it ->
        we send the result back -> repeat until the model answers in text."""
        start = time.perf_counter()
        text, in_tok, out_tok, trace, raw = self._tool_loop(
            prompt, tools, system, max_steps, max_tokens)
        resp = self._package(text, in_tok, out_tok, time.perf_counter() - start, raw)
        resp.tool_trace = trace
        log_telemetry(resp, "tools")
        return resp

    def _package(self, text, in_tok, out_tok, latency, raw) -> LLMResponse:
        return LLMResponse(self.name, self.model, text or "", in_tok, out_tok,
                           latency, estimate_cost(self.model, in_tok, out_tok), raw=raw)

    # ---- each provider implements these two ----
    @abstractmethod
    def _call(self, messages, system, temperature, max_tokens, json_schema):
        """Return (text, input_tokens, output_tokens, raw_response)."""

    @abstractmethod
    def _tool_loop(self, prompt, tools, system, max_steps, max_tokens):
        """Return (final_text, input_tokens, output_tokens, trace, raw_last_response)."""


def _strip_fences(text: str) -> str:
    """Remove ```json fences if a model wraps its JSON in them."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t.strip()


def _dispatch(tools: list[Tool], name: str, args: dict, trace: list[dict]) -> Any:
    """Find the tool by name, run it, record what happened."""
    tool = next((t for t in tools if t.name == name), None)
    try:
        result = tool.call(args) if tool else {"error": f"unknown tool {name}"}
    except Exception as e:                       # a tool error goes back to the model
        result = {"error": str(e)}
    trace.append({"tool": name, "args": args, "result": result})
    return result


# ===========================================================================
# 6. OpenAI — Responses API
# ===========================================================================
class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str | None = None):
        from openai import OpenAI
        super().__init__(model or os.environ["OPENAI_MODEL"])
        self.client = OpenAI()

    def _call(self, messages, system, temperature, max_tokens, json_schema):
        kwargs: dict[str, Any] = {"model": self.model, "input": messages,
                                  "max_output_tokens": max_tokens}
        if system:
            kwargs["instructions"] = system
        if temperature is not None:      # some reasoning models reject it
            kwargs["temperature"] = temperature
        if json_schema:
            kwargs["text"] = {"format": {"type": "json_schema", "name": "output",
                                         "schema": json_schema, "strict": True}}
        r = self.client.responses.create(**kwargs)
        return r.output_text, r.usage.input_tokens, r.usage.output_tokens, r

    def _tool_loop(self, prompt, tools, system, max_steps, max_tokens):
        specs = [{"type": "function", "name": t.name, "description": t.description,
                  "parameters": t.parameters, "strict": True} for t in tools]
        items: list[Any] = [{"role": "user", "content": prompt}]
        trace: list[dict] = []
        tin = tout = 0
        for _ in range(max_steps):
            kwargs: dict[str, Any] = {"model": self.model, "input": items,
                                      "tools": specs, "max_output_tokens": max_tokens}
            if system:
                kwargs["instructions"] = system
            r = self.client.responses.create(**kwargs)
            tin += r.usage.input_tokens
            tout += r.usage.output_tokens
            calls = [o for o in r.output if o.type == "function_call"]
            if not calls:
                return r.output_text, tin, tout, trace, r
            items += r.output                       # keep the model's own turn
            for c in calls:
                result = _dispatch(tools, c.name, json.loads(c.arguments), trace)
                items.append({"type": "function_call_output", "call_id": c.call_id,
                              "output": json.dumps(result)})
        return "[stopped: too many tool steps]", tin, tout, trace, None


# ===========================================================================
# 7. Google Gemini — google-genai SDK
# ===========================================================================
class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, model: str | None = None):
        from google import genai
        super().__init__(model or os.environ["GEMINI_MODEL"])
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    @staticmethod
    def _tokens(r) -> tuple[int, int]:
        u = r.usage_metadata
        # "thinking" tokens are billed as output, so count them in
        out = (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
        return u.prompt_token_count or 0, out

    def _call(self, messages, system, temperature, max_tokens, json_schema):
        from google.genai import types
        # Gemini calls the assistant role "model"
        contents = [types.Content(role="model" if m["role"] == "assistant" else "user",
                                  parts=[types.Part(text=m["content"])]) for m in messages]
        cfg: dict[str, Any] = {"max_output_tokens": max_tokens}
        if system:
            cfg["system_instruction"] = system
        if temperature is not None:
            cfg["temperature"] = temperature
        if json_schema:
            cfg["response_mime_type"] = "application/json"
            cfg["response_json_schema"] = json_schema
        r = self.client.models.generate_content(
            model=self.model, contents=contents, config=types.GenerateContentConfig(**cfg))
        tin, tout = self._tokens(r)
        return r.text or "", tin, tout, r

    def _tool_loop(self, prompt, tools, system, max_steps, max_tokens):
        from google.genai import types
        decl = [types.FunctionDeclaration(name=t.name, description=t.description,
                                          parameters_json_schema=t.parameters) for t in tools]
        cfg = types.GenerateContentConfig(
            tools=[types.Tool(function_declarations=decl)],
            # switch off the SDK's auto-execution so the loop is visible here
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            system_instruction=system, max_output_tokens=max_tokens)
        contents: list[Any] = [types.Content(role="user", parts=[types.Part(text=prompt)])]
        trace: list[dict] = []
        tin = tout = 0
        for _ in range(max_steps):
            r = self.client.models.generate_content(model=self.model, contents=contents, config=cfg)
            a, b = self._tokens(r)
            tin, tout = tin + a, tout + b
            if not r.function_calls:
                return r.text or "", tin, tout, trace, r
            contents.append(r.candidates[0].content)
            parts = [types.Part.from_function_response(
                        name=fc.name,
                        response={"result": _dispatch(tools, fc.name, dict(fc.args or {}), trace)})
                     for fc in r.function_calls]
            contents.append(types.Content(role="user", parts=parts))
        return "[stopped: too many tool steps]", tin, tout, trace, None


# ===========================================================================
# 8. Anthropic Claude — Messages API
# ===========================================================================
class ClaudeProvider(LLMProvider):
    name = "claude"

    def __init__(self, model: str | None = None):
        from anthropic import Anthropic
        super().__init__(model or os.environ["ANTHROPIC_MODEL"])
        self.client = Anthropic()

    def _call(self, messages, system, temperature, max_tokens, json_schema):
        # Note: temperature is not a parameter in the current Claude Messages
        # SDK, so it is ignored for this provider. A real provider difference.
        kwargs: dict[str, Any] = {"model": self.model, "max_tokens": max_tokens,
                                  "messages": messages}
        if system:
            kwargs["system"] = system
        if json_schema:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": json_schema}}
        r = self.client.messages.create(**kwargs)
        text = "".join(b.text for b in r.content if b.type == "text")
        return text, r.usage.input_tokens, r.usage.output_tokens, r

    def _tool_loop(self, prompt, tools, system, max_steps, max_tokens):
        specs = [{"name": t.name, "description": t.description,
                  "input_schema": t.parameters} for t in tools]
        messages: list[dict] = [{"role": "user", "content": prompt}]
        trace: list[dict] = []
        tin = tout = 0
        for _ in range(max_steps):
            kwargs: dict[str, Any] = {"model": self.model, "max_tokens": max_tokens,
                                      "messages": messages, "tools": specs}
            if system:
                kwargs["system"] = system
            r = self.client.messages.create(**kwargs)
            tin += r.usage.input_tokens
            tout += r.usage.output_tokens
            if r.stop_reason != "tool_use":
                return "".join(b.text for b in r.content if b.type == "text"), tin, tout, trace, r
            messages.append({"role": "assistant", "content": r.content})
            results = [{"type": "tool_result", "tool_use_id": b.id,
                        "content": json.dumps(_dispatch(tools, b.name, b.input, trace))}
                       for b in r.content if b.type == "tool_use"]
            messages.append({"role": "user", "content": results})
        return "[stopped: too many tool steps]", tin, tout, trace, None


# ===========================================================================
# 9. Mock provider — offline testing only
# ===========================================================================
class MockProvider(LLMProvider):
    """Fake provider for testing the plumbing with no keys and no cost.
    It returns placeholder text, schema-shaped dummy JSON, and calls the
    first tool once. Its output is meaningless by design."""

    def __init__(self, name: str, latency: float):
        super().__init__(f"{name}-model")
        self.name = name
        self.latency = latency

    def _fake(self, words: int) -> str:
        time.sleep(self.latency * random.uniform(0.8, 1.2))
        return " ".join(["(mock)"] * words)

    def _call(self, messages, system, temperature, max_tokens, json_schema):
        n_in = sum(len(m["content"].split()) for m in messages) * 4 // 3
        if json_schema:
            self._fake(0)
            return json.dumps(_dummy(json_schema)), n_in, 40, None
        return self._fake(12) + "\nANSWER: (mock)", n_in, 16, None

    def _tool_loop(self, prompt, tools, system, max_steps, max_tokens):
        trace: list[dict] = []
        if tools:
            _dispatch(tools, tools[0].name, _dummy(tools[0].parameters), trace)
        return self._fake(10), len(prompt.split()) * 2, 30, trace, None


def _dummy(schema: dict) -> Any:
    t = schema.get("type")
    if "enum" in schema:
        return schema["enum"][0]
    if t == "object":
        return {k: _dummy(v) for k, v in schema.get("properties", {}).items()}
    if t == "array":
        return [_dummy(schema.get("items", {"type": "string"}))]
    if isinstance(t, list):
        return _dummy({**schema, "type": [x for x in t if x != "null"][0]})
    if "anyOf" in schema:
        return _dummy(schema["anyOf"][0])
    return {"integer": 1, "number": 1.0, "boolean": False}.get(t, "mock")


# ===========================================================================
# 10. Registry
# ===========================================================================
def mock_mode() -> bool:
    return "--mock" in sys.argv or os.getenv("MOCK_LLM") == "1"


def available_providers(only: list[str] | None = None) -> list[LLMProvider]:
    """Build every provider that has a key and model set in .env.
    Missing ones are skipped with a note, so you can run with just one."""
    if mock_mode():
        print("*** MOCK MODE: offline fake providers, output is not real ***\n")
        ps: list[LLMProvider] = [MockProvider("mock-openai", 0.05),
                                 MockProvider("mock-gemini", 0.03),
                                 MockProvider("mock-claude", 0.04)]
    else:
        candidates = [("openai", "OPENAI_API_KEY", "OPENAI_MODEL", OpenAIProvider),
                      ("gemini", "GEMINI_API_KEY", "GEMINI_MODEL", GeminiProvider),
                      ("claude", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", ClaudeProvider)]
        ps = []
        for name, key, model, cls in candidates:
            if os.getenv(key) and os.getenv(model):
                try:
                    ps.append(cls())
                except Exception as e:
                    print(f"  ! {name}: could not start ({e})")
            else:
                print(f"  - {name}: skipped ({key} or {model} not set in .env)")
    if only:
        ps = [p for p in ps if any(o in p.name for o in only)]
    if not ps:
        raise SystemExit("No providers available. Fill in .env, or run with --mock to test offline.")
    return ps


def safe(fn: Callable, *args, **kwargs) -> tuple[Any, str | None]:
    """Run a provider call; return (result, None) or (None, error message).
    Keeps one failing provider from stopping a side-by-side comparison."""
    try:
        return fn(*args, **kwargs), None
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:300]}"
