"""Central configuration — all settings live in .env at the project root.

python-dotenv loads .env automatically at import time so every setting is
available as a plain os.getenv() call, exactly as before. Running with real
environment variables (CI, Docker, systemd) always takes priority over .env.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels above this file).
# override=False means real env vars always win over .env values.
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_ENV_FILE, override=False)

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("TSP_DATA_DIR") or BASE_DIR / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# --- Server ---------------------------------------------------------------
TSP_HOST = os.getenv("TSP_HOST", "127.0.0.1")
TSP_PORT = int(os.getenv("TSP_PORT", "8000"))
TSP_RELOAD = os.getenv("TSP_RELOAD", "true").lower() in ("1", "true", "yes")
TSP_LOG_LEVEL = os.getenv("TSP_LOG_LEVEL", "info")

# --- Database -------------------------------------------------------------
# Default: SQLite (zero-setup). Production: PostgreSQL + pgvector.
DATABASE_URL = os.getenv("TSP_DATABASE_URL") or f"sqlite:///{DATA_DIR / 'termsheets.db'}"

# --- LLM provider ---------------------------------------------------------
# TSP_LLM_PROVIDER selects how the ExtractionAgent reaches the model:
#   gateway  -> POST masked text to the bank's internal Bedrock gateway URL
#   bedrock  -> call AWS Bedrock directly via boto3 (SigV4 / IAM credentials)
#   mock     -> deterministic offline extractor (dev / CI)
#   auto     -> gateway if BEDROCK_GATEWAY_URL is set, else bedrock if an AWS
#               region is configured, else mock
LLM_PROVIDER = os.getenv("TSP_LLM_PROVIDER", "auto").strip().lower()

# Shared across providers
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
BEDROCK_TIMEOUT_SECONDS = int(os.getenv("BEDROCK_TIMEOUT_SECONDS", "120"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4000"))

# Provider: gateway (bank-hosted HTTP endpoint, messages-API shape)
BEDROCK_GATEWAY_URL = os.getenv("BEDROCK_GATEWAY_URL", "")
BEDROCK_API_KEY = os.getenv("BEDROCK_API_KEY", "")
BEDROCK_AUTH_HEADER = os.getenv("BEDROCK_AUTH_HEADER", "Authorization")

# Provider: bedrock (direct AWS). Credentials from the standard AWS chain
# (AWS_ACCESS_KEY_ID/SECRET, AWS_PROFILE, ~/.aws/*, instance/ECS role).
BEDROCK_REGION = os.getenv("BEDROCK_REGION") or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "")
BEDROCK_ENDPOINT_URL = os.getenv("BEDROCK_ENDPOINT_URL", "")

# --- Agent loop -----------------------------------------------------------
MAX_CRITIC_ITERATIONS = int(os.getenv("TSP_MAX_CRITIC_ITERATIONS", "3"))
LESSON_TOP_K = int(os.getenv("TSP_LESSON_TOP_K", "6"))
LESSON_MIN_SIMILARITY = float(os.getenv("TSP_LESSON_MIN_SIMILARITY", "0.05"))

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
