"""Offline wiring test: runs the real OpenAI, Gemini and Claude provider classes
against fake HTTP servers. Checks text, structured output and the tool loop
all serialise and parse correctly. Needs no API keys and costs nothing.

Run:  python tests/test_sdk_wiring.py

"""
import json, os, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
os.environ.update(OPENAI_API_KEY="x", GEMINI_API_KEY="x", ANTHROPIC_API_KEY="x")
import httpx
from llm_core import OpenAIProvider, GeminiProvider, ClaudeProvider
from m1_structured_function_demo import JobPosting, CURRENCY_TOOL

JOB = {"title": "Senior Data Engineer", "company": "Brightwave Analytics", "location": "Manchester",
       "remote_policy": "hybrid", "salary_min": 70000, "salary_max": 85000, "currency": "GBP",
       "years_experience": 5, "skills": ["Python", "SQL", "Airflow", "Snowflake"]}
ARGS = {"amount": 2800000, "from_currency": "INR", "to_currency": "GBP"}

def transport(queue, seen, mod=httpx):
    def handler(req):
        seen.append((req.url.path, json.loads(req.content or b"{}")))
        return mod.Response(200, json=queue.pop(0))
    return mod.MockTransport(handler)

# ---------- OpenAI ----------
def oa_msg(text):
    return {"id": "resp_1", "object": "response", "created_at": 0, "model": "m", "status": "completed",
            "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
            "output": [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}
oa_tool = oa_msg("")
oa_tool["output"] = [{"type": "function_call", "id": "fc_1", "call_id": "call_1",
                      "name": "convert_currency", "arguments": json.dumps(ARGS), "status": "completed"}]

# ---------- Anthropic ----------
def an_msg(content, stop="end_turn"):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "m", "content": content,
            "stop_reason": stop, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 5}}

# ---------- Gemini ----------
def ge_msg(parts):
    return {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "thoughtsTokenCount": 3,
                              "totalTokenCount": 18}}

def check(provider, queue, label):
    seen = []
    import httpx2
    t = transport(queue, seen, httpx2 if isinstance(provider, ClaudeProvider) else httpx)
    if isinstance(provider, OpenAIProvider):
        from openai import OpenAI; provider.client = OpenAI(api_key="x", http_client=httpx.Client(transport=t))
    elif isinstance(provider, ClaudeProvider):
        from anthropic import Anthropic; provider.client = Anthropic(api_key="x", http_client=httpx2.Client(transport=t))
    else:
        from google import genai; from google.genai import types
        provider.client = genai.Client(api_key="x", http_options=types.HttpOptions(httpx_client=httpx.Client(transport=t)))
    return seen

for P, mk_text, mk_json, tool_seq in [
    (OpenAIProvider, lambda: oa_msg("ok\nANSWER: 5"), lambda: oa_msg(json.dumps(JOB)),
     lambda: [oa_tool, oa_msg("It fits.")]),
    (ClaudeProvider, lambda: an_msg([{"type": "text", "text": "ok\nANSWER: 5"}]),
     lambda: an_msg([{"type": "text", "text": json.dumps(JOB)}]),
     lambda: [an_msg([{"type": "tool_use", "id": "tu_1", "name": "convert_currency", "input": ARGS}], "tool_use"),
              an_msg([{"type": "text", "text": "It fits."}])]),
    (GeminiProvider, lambda: ge_msg([{"text": "ok\nANSWER: 5"}]), lambda: ge_msg([{"text": json.dumps(JOB)}]),
     lambda: [ge_msg([{"functionCall": {"name": "convert_currency", "args": ARGS}}]), ge_msg([{"text": "It fits."}])]),
]:
    p = P(model="test-model")
    seen = check(p, [mk_text()], "text")
    r = p.generate([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
                    {"role": "user", "content": "q"}], system="sys", temperature=0)
    print(p.name, "TEXT ok:", r.text.splitlines()[-1], r.input_tokens, r.output_tokens)
    seen = check(p, [mk_json()], "json")
    job, r = p.generate_structured("extract", JobPosting, system="s")
    body = seen[0][1]
    fmt = body.get("text") or body.get("output_config") or body.get("generationConfig", {})
    print(p.name, "JSON ok:", job.title, "| schema keys sent:", list(fmt)[:4])
    seen = check(p, tool_seq(), "tools")
    r = p.run_tools("convert please", [CURRENCY_TOOL], system="s")
    print(p.name, "TOOLS ok:", r.tool_trace[0]["result"]["converted"], "->", r.text, "| calls:", len(seen),
          "| tokens", r.input_tokens, r.output_tokens)
print("ALL WIRE TESTS PASSED")
