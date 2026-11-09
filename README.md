# Multi-SDK LLM Playground — Module 1 Capstone

A provider-agnostic Python layer over the **OpenAI**, **Google Gemini** and **Anthropic Claude** SDKs. The same prompt goes to all three; responses, tokens, latency and cost are compared side by side across zero-shot, few-shot and Chain-of-Thought prompting, structured JSON output and function calling.

## Why this exists

Teams that build on one LLM provider from day one rarely find out how the others differ on reasoning, structured-output reliability, latency, cost and context handling. When pricing changes or a better model appears, they face a rewrite. This project puts one thin interface in front of all three providers, so switching or comparing is a configuration change, not a code change.

## Project layout

| File | What it does |
|---|---|
| `llm_core.py` | The abstraction layer: `LLMProvider` base class, one adapter per SDK, the common `LLMResponse`, cost and token telemetry, JSON Schema helper, tool-calling loop, offline mock providers |
| `prompting.py` | Prompt-strategy switcher (zero-shot / few-shot / CoT) and answer extraction |
| **`m1_openai_chatbot_demo.py`** | Deliverable 1 — interactive multi-SDK chatbot; each message goes to every provider and the answers are compared side by side |
| **`m1_cot_reasoning_demo.py`** | Deliverable 2 — Chain-of-Thought agent; six reasoning problems × strategies × providers, auto-scored |
| **`m1_structured_function_demo.py`** | Deliverable 3 — JSON Schema enforcement with Pydantic validation (Part A) and one tool with its dispatch loop (Part B) |
| **`m1_comparison_report.py`** | Deliverable 4 — runs 5 prompts × 3 providers and writes `reports/comparison_report.md` |
| `tests/test_sdk_wiring.py` | Offline test of all three real adapters against fake HTTP servers |
| `pricing.json` | Per-model prices (USD per million tokens) that drive the cost figures |
| `.env.example` | Template for API keys and model IDs |

## Design

```
            your code (chatbot, CoT demo, structured demo, report)
                                  │
                 generate() · generate_structured() · run_tools()
                                  │
                      LLMProvider  (timing, costing, logging, validation)
              ┌───────────────────┼───────────────────┐
        OpenAIProvider      GeminiProvider      ClaudeProvider
       Responses API       generate_content     Messages API
```

**One answer shape.** Every call returns an `LLMResponse` with text, input tokens, output tokens, latency and cost, whichever provider served it. All comparison and reporting code is written once, against that shape.

**Template method.** The base class owns timing, cost calculation, telemetry logging, Pydantic validation and retry. Each adapter implements only two methods: `_call()` (one request) and `_tool_loop()` (the function-calling loop). Adding a fourth provider means writing those two methods and nothing else.

**Native features, not lowest common denominator.** Each adapter uses its provider's own mechanism rather than asking for JSON in the prompt and hoping:

| Concept | OpenAI | Gemini | Claude |
|---|---|---|---|
| System prompt | `instructions` | `system_instruction` | `system` |
| Assistant role name | `assistant` | `model` | `assistant` |
| Structured output | `text.format` json_schema, `strict: true` | `response_mime_type` + `response_json_schema` | `output_config.format` json_schema |
| Tool definition | `tools[{type: function, parameters}]` | `FunctionDeclaration(parameters_json_schema)` | `tools[{input_schema}]` |
| Tool request signal | output item `type == "function_call"` | `response.function_calls` | `stop_reason == "tool_use"` |
| Tool result returned as | `function_call_output` item | `Part.from_function_response` | `tool_result` content block |
| Token usage | `usage.input_tokens / output_tokens` | `usage_metadata.prompt_token_count / candidates_token_count + thoughts_token_count` | `usage.input_tokens / output_tokens` |
| Temperature | supported (some reasoning models reject it, so it is sent only when asked) | supported | not exposed in the current Messages SDK, so ignored |

That table is itself one of the findings: the same idea has a different name, shape and failure mode in each SDK, and those are exactly the differences that make single-provider code brittle.

**Strict schemas.** Pydantic's generated schema is tightened by `strict_schema()` (every property required, `additionalProperties: false`, nested refs inlined) so one schema satisfies all three providers' strict modes. Optional fields become `anyOf [type, null]`.

**Validation and retry.** Structured replies are validated with Pydantic. On failure the validation error is sent back to the model once for a corrected answer.

**Telemetry.** Every call appends a line to `logs/telemetry.jsonl`: timestamp, call type, provider, model, input and output tokens, latency, cost and any error.

**Failure isolation.** Calls in the comparisons go through `safe()`, so one provider's outage or rate-limit is recorded as an error rather than stopping the run.

## Setup

Python 3.11 or later.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then add keys and model IDs
```

Add prices for your chosen models to `pricing.json` from each provider's pricing page; without them cost shows as n/a.

Check everything works before spending anything:

```bash
python tests/test_sdk_wiring.py                 # real adapters, fake servers
python m1_comparison_report.py --mock           # full pipeline, fake providers
```

## Running the deliverables

```bash
# 1. Multi-SDK chatbot
python m1_openai_chatbot_demo.py
python m1_openai_chatbot_demo.py --once "Explain context windows in two sentences."
#    in-chat: /mode few-shot   /mode cot   /stats   /reset   /quit

# 2. Chain-of-Thought reasoning
python m1_cot_reasoning_demo.py --strategies zero-shot,few-shot,cot --show-reasoning

# 3. Structured output and function calling
python m1_structured_function_demo.py

# 4. Comparison report (3 runs recommended so latency and cost are averaged)
python m1_comparison_report.py --runs 3
```

Every script accepts `--providers openai,claude` to run a subset and `--mock` to run offline.

## The comparison report

`m1_comparison_report.py` runs five prompts, each tied to a Module 1 concept and each with an automatic checker:

| Prompt | Concept | Scored on |
|---|---|---|
| `cot-arithmetic` | Chain-of-Thought | final number = 82,500 |
| `zero-shot-logic` | zero-shot reasoning | answer = Asha |
| `few-shot-classify` | few-shot prompting | label = billing |
| `json-extraction` | structured output | schema-valid, then 9 fields checked (partial credit) |
| `long-context` | context handling | finds one fact hidden in ~6,000 words |

It writes `reports/comparison_report.md` (tables, a weighted ranking and data-driven observations), `reports/results.csv` and `reports/responses.jsonl`. The composite score weights accuracy 50%, cost 25% and latency 25%; change `WEIGHTS` in the script if needed. Section 6 of the generated report, interpretation and recommendation, is left for you to write from your own results.

## Limitations

- Five prompts is a small sample; run with `--runs 3` or more and treat differences of one answer with caution.
- Latency reflects network, region and provider load at the time of the run.
- Results hold for the specific model IDs used, not for each provider's whole range.
- Currency rates in the tool demo are fixed demo values, not live rates.
