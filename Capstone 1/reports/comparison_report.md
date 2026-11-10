# Multi-SDK LLM Comparison Report

Generated 31 October 2026, 16:08 · 5 prompts × 3 providers × 1 run(s) = 15 calls

## 1. Set-up

| Provider | Model | SDK path |
|---|---|---|
| openai | `gpt-5.6-luna` | OpenAI Responses API |
| gemini | `<model ID from Google AI Studio>` | google-genai `generate_content` |
| claude | `claude-haiku-5-5` | Anthropic Messages API |

Text prompts were sent with temperature 0 where the provider supports it. Latency is wall-clock time for the full API call from this machine. Cost is calculated from returned token counts and the per-million-token prices in `pricing.json`; it shows n/a where no price was entered.

## 2. Test prompts

| # | Prompt | Module 1 concept | How it is scored |
|---|---|---|---|
| 1 | `cot-arithmetic` | Chain-of-Thought | Final number must equal 82,500 |
| 2 | `zero-shot-logic` | Zero-shot reasoning | Final answer must be Asha |
| 3 | `few-shot-classify` | Few-shot prompting | Label must be billing |
| 4 | `json-extraction` | Structured output (JSON Schema + Pydantic) | Valid against schema, then 9 fields checked; score = share correct |
| 5 | `long-context` | Context handling (~6,012 words) | Answer must contain BLUE HERON |

## 3. Overall results

| Rank | Provider | Accuracy | Avg latency | Avg cost / call | Total cost | Tokens in / out | Errors | Composite |
|---|---|---|---|---|---|---|---|---|
| 1 | claude | 100% | 2.24s | n/a | n/a | 14,595 / 656 | 0/5 | 1.00 |
| 2 | openai | 20% | 3.46s | n/a | n/a | 307 / 65 | 4/5 | 0.13 |
| 3 | gemini | 0% | n/a | n/a | n/a | 0 / 0 | 5/5 | 0.00 |

Composite = 50% accuracy + 25% cost + 25% latency, each scaled 0–1 across providers (1 = best). If no prices are set, cost is left out and the weights re-normalise.

## 4. Results by prompt

### cot-arithmetic — Chain-of-Thought

| Provider | Accuracy | Avg latency | Avg cost | Tokens in / out (avg) | Note (last run) |
|---|---|---|---|---|---|
| openai | 0% | — | n/a | — | BadRequestError: Error code: 400 - Unsupported parameter: 'temperature' is not supported w |
| gemini | 0% | — | n/a | — | ClientError: 400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': 'API key not valid.  |
| claude | 100% | 2.14s | n/a | 160 / 301 | answered '82500', expected 82500 |

### zero-shot-logic — Zero-shot reasoning

| Provider | Accuracy | Avg latency | Avg cost | Tokens in / out (avg) | Note (last run) |
|---|---|---|---|---|---|
| openai | 0% | — | n/a | — | BadRequestError: Error code: 400 - Unsupported parameter: 'temperature' is not supported w |
| gemini | 0% | — | n/a | — | ClientError: 400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': 'API key not valid.  |
| claude | 100% | 1.24s | n/a | 131 / 148 | answered 'asha', expected 'asha' |

### few-shot-classify — Few-shot prompting

| Provider | Accuracy | Avg latency | Avg cost | Tokens in / out (avg) | Note (last run) |
|---|---|---|---|---|---|
| openai | 0% | — | n/a | — | BadRequestError: Error code: 400 - Unsupported parameter: 'temperature' is not supported w |
| gemini | 0% | — | n/a | — | ClientError: 400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': 'API key not valid.  |
| claude | 100% | 0.95s | n/a | 298 / 10 | answered 'billing', expected 'billing' |

### json-extraction — Structured output (JSON Schema + Pydantic)

| Provider | Accuracy | Avg latency | Avg cost | Tokens in / out (avg) | Note (last run) |
|---|---|---|---|---|---|
| openai | 100% | 3.46s | n/a | 307 / 65 | all fields correct |
| gemini | 0% | — | n/a | — | ClientError: 400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': 'API key not valid.  |
| claude | 100% | 4.85s | n/a | 838 / 108 | all fields correct |

### long-context — Context handling (~6,012 words)

| Provider | Accuracy | Avg latency | Avg cost | Tokens in / out (avg) | Note (last run) |
|---|---|---|---|---|---|
| openai | 0% | — | n/a | — | BadRequestError: Error code: 400 - Unsupported parameter: 'temperature' is not supported w |
| gemini | 0% | — | n/a | — | ClientError: 400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': 'API key not valid.  |
| claude | 100% | 2.04s | n/a | 13,168 / 89 | answered 'BLUE HERON' |

## 5. Observations from the data

- **Most accurate:** claude (100% across the five prompts).
- **Fastest on average:** claude (2.24s), against openai at 3.46s.
- **Cost:** not compared, as no prices were entered in `pricing.json`.
- **Tokenisers differ:** the same long-context document counted as 13,168 input tokens for claude. The same text can therefore cost different amounts before any answer is written.
- **Misses:** openai on `cot-arithmetic`; openai on `zero-shot-logic`; openai on `few-shot-classify`; openai on `long-context`; gemini on `cot-arithmetic`; gemini on `zero-shot-logic`; gemini on `few-shot-classify`; gemini on `json-extraction`; gemini on `long-context`.
- **Errors:** openai (4), gemini (5). See `results.csv` for the messages.

## 6. Interpretation and recommendation

_Write this section yourself from the tables above. Suggested points: which provider you would choose for which job (reasoning, extraction, long documents, high volume), where the accuracy differences actually mattered, how stable latency was across runs, and what the abstraction layer made easy or hard._

## 7. Limitations

- Five prompts and 1 run(s) per prompt is a small sample; one wrong answer moves accuracy by 20 points.
- Latency depends on network, region and provider load at the time of the run.
- Results apply to the specific model versions listed in section 1, not to each provider's whole range.
- Some checks are strict on format (for example, the final `ANSWER:` line), so a correct answer in the wrong format scores zero. That is deliberate: format reliability is part of what is being compared.

Raw data: `reports/results.csv` and `reports/responses.jsonl`.