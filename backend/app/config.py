"""Central configuration — all settings live in .env at the project root.

python-dotenv loads .env automatically at import time so every setting is
available as a plain os.getenv() call. Running with real environment variables
(CI, Docker, systemd) always takes priority over .env values.
"""
import os
import re
from pathlib import Path

from dotenv import load_dotenv

# backend/app/config.py → parents[0]=app, [1]=backend, [2]=termsheetparser/
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_FILE, override=False)


def _env(key: str, default: str = "") -> str:
    """Read an env var and strip any trailing inline comment (# ...)."""
    raw = os.getenv(key, default)
    # strip inline comments: "value  # comment" → "value"
    raw = re.sub(r"\s+#.*$", "", raw).strip()
    return raw


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(_env("TSP_DATA_DIR") or BASE_DIR / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# --- Server ---------------------------------------------------------------
TSP_HOST      = _env("TSP_HOST",      "127.0.0.1")
TSP_PORT      = int(_env("TSP_PORT", "8000") or "8000")
TSP_RELOAD    = _env("TSP_RELOAD",    "true").lower() in ("1", "true", "yes")
TSP_LOG_LEVEL = _env("TSP_LOG_LEVEL", "info")

# --- Database -------------------------------------------------------------
_raw_db_url = _env("TSP_DATABASE_URL").strip()
# Accept only values that look like a DB URL (contain "://"); anything else
# (blank, comment fragment, placeholder text) falls back to SQLite.
DATABASE_URL = (_raw_db_url
                if "://" in _raw_db_url
                else f"sqlite:///{DATA_DIR / 'termsheets.db'}")

# --- LLM provider ---------------------------------------------------------
LLM_PROVIDER           = _env("TSP_LLM_PROVIDER", "auto").lower()
BEDROCK_MODEL_ID       = _env("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
BEDROCK_TIMEOUT_SECONDS = int(_env("BEDROCK_TIMEOUT_SECONDS", "120") or "120")
LLM_MAX_TOKENS         = int(_env("LLM_MAX_TOKENS", "4000") or "4000")

BEDROCK_GATEWAY_URL  = _env("BEDROCK_GATEWAY_URL")
BEDROCK_API_KEY      = _env("BEDROCK_API_KEY")
BEDROCK_AUTH_HEADER  = _env("BEDROCK_AUTH_HEADER", "Authorization")

BEDROCK_REGION       = (_env("BEDROCK_REGION")
                        or _env("AWS_REGION")
                        or _env("AWS_DEFAULT_REGION"))
BEDROCK_ENDPOINT_URL = _env("BEDROCK_ENDPOINT_URL")

# --- Agent loop -----------------------------------------------------------
MAX_CRITIC_ITERATIONS = int(_env("TSP_MAX_CRITIC_ITERATIONS", "3") or "3")
LESSON_TOP_K          = int(_env("TSP_LESSON_TOP_K", "6") or "6")
LESSON_MIN_SIMILARITY = float(_env("TSP_LESSON_MIN_SIMILARITY", "0.05") or "0.05")

# --- Masking --------------------------------------------------------------
KNOWN_COUNTERPARTIES = [
    "Citigroup", "Citibank", "Citi",
    "UBS AG", "UBS",
    "Standard Chartered Bank", "Standard Chartered", "StanChart",
    "JPMorgan Chase", "J.P. Morgan", "JP Morgan", "JPMorgan",
    "Goldman Sachs", "Morgan Stanley", "BNP Paribas", "Societe Generale",
    "Barclays", "HSBC", "Credit Agricole", "Nomura", "Deutsche Bank",
    "DBS Bank", "OCBC", "United Overseas Bank", "UOB",
]

APP_VERSION = "1.0.0"
