"""
config.py - one place for all settings.

Settings come from a file called `.env` (copy `.env.example` to `.env` and fill
it in). Keeping secrets such as API keys in `.env` means they never get typed
into the code - and `.gitignore` stops `.env` being uploaded to GitHub.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Where the agents find the MCP server
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")

# Which LLM to use. CrewAI uses the "provider/model" format (via LiteLLM).
# Examples: "gemini/gemini-2.5-flash", "openai/gpt-4o-mini"
CREWAI_MODEL = os.getenv("CREWAI_MODEL", "gemini/gemini-2.5-flash")

# Google ADK uses the plain Gemini model name.
ADK_MODEL = os.getenv("ADK_MODEL", "gemini-2.5-flash")

# How many times the Critique -> Refine loop may run before we stop.
MAX_REFINE_ROUNDS = int(os.getenv("MAX_REFINE_ROUNDS", "2"))

OUTPUT_DIR = PROJECT_ROOT / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)
