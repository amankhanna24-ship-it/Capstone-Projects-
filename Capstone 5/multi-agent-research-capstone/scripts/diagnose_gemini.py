"""
diagnose_gemini.py - find out WHY the agents seem stuck. No MCP server needed.

It runs three small checks against Gemini, each with a 60-second time limit,
and prints how long each took and any error IN FULL (nothing is hidden):

  1. Which "flash" models can your key use?
  2. A plain question         ("Reply with one word")
  3. A question with a tool   (this is what the agents do)

Run:
    python scripts/diagnose_gemini.py
    python scripts/diagnose_gemini.py gemini-3.8-flash      # test a specific model
"""

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MODEL = sys.argv[1] if len(sys.argv) > 1 else os.getenv("ADK_MODEL", "gemini-3.8-flash")
KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

if not KEY or "paste" in KEY:
    sys.exit("No API key found. Put your key in .env as GOOGLE_API_KEY=... and GEMINI_API_KEY=...")

# timeout is in milliseconds; attempts=1 means "don't silently retry - show me the error"
client = genai.Client(
    api_key=KEY,
    http_options=types.HttpOptions(timeout=60_000,
                                   retry_options=types.HttpRetryOptions(attempts=1)),
)


def check(title, fn):
    print(f"\n--- {title} ---")
    start = time.time()
    try:
        result = fn()
        print(f"OK in {time.time() - start:.1f}s")
        return result
    except Exception as err:
        print(f"FAILED after {time.time() - start:.1f}s")
        print(f"{type(err).__name__}: {err}")
        return None


print(f"Testing model: {MODEL}")

models = check("1. Models available to your key", lambda: [
    m.name.replace("models/", "") for m in client.models.list() if "flash" in m.name])
if models:
    for name in models:
        print("   ", name)

reply = check("2. Plain question", lambda: client.models.generate_content(
    model=MODEL, contents="Reply with one word: hello").text)
if reply:
    print("   Gemini said:", reply.strip())

weather_tool = types.Tool(function_declarations=[types.FunctionDeclaration(
    name="get_price",
    description="Get the latest share price for a ticker.",
    parameters=types.Schema(type="OBJECT",
                            properties={"ticker": types.Schema(type="STRING")},
                            required=["ticker"]),
)])

response = check("3. Question that should trigger a tool call", lambda: client.models.generate_content(
    model=MODEL,
    contents="What is NVDA's share price? Use the tool.",
    config=types.GenerateContentConfig(tools=[weather_tool],
                                       automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)),
))
if response is not None:
    calls = response.function_calls or []
    print("   Tool calls requested:", [(c.name, dict(c.args or {})) for c in calls] or "none")

print("\nWhat this means:")
print("  - 429 / RESOURCE_EXHAUSTED  -> free-tier limit hit. Wait, or pick a model with a higher limit.")
print("  - 404 / NOT_FOUND           -> model name not available; pick one from list 1 and put it in .env.")
print("  - Timed out (60s)           -> model too slow / network issue; try another model from list 1.")
print("  - All three OK              -> Gemini is fine; the problem is elsewhere. Share the demo's output.")
