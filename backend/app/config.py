"""Central configuration. Everything is overridable via environment variables
so the same build runs on a laptop (mock LLM + SQLite) and inside the bank
network (Bedrock gateway + PostgreSQL/pgvector).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("TSP_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# --- Database -------------------------------------------------------------
# Default: SQLite (zero-setup demo). Production: point at PostgreSQL with
# pgvector, e.g. postgresql+psycopg://user:pass@host:5432/termsheets
DATABASE_URL = os.getenv("TSP_DATABASE_URL", f"sqlite:///{DATA_DIR / 'termsheets.db'}")

# --- LLM provider ------------------------------------------------------------
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
BEDROCK_GATEWAY_URL = os.getenv("BEDROCK_GATEWAY_URL", "")           # e.g. https://llm-gw.bank.internal/bedrock/v1/messages
BEDROCK_API_KEY = os.getenv("BEDROCK_API_KEY", "")                   # forwarded as Authorization: Bearer <key>
BEDROCK_AUTH_HEADER = os.getenv("BEDROCK_AUTH_HEADER", "Authorization")

# Provider: bedrock (direct AWS API). Credentials come from the standard AWS
# chain: env vars (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY), AWS_PROFILE,
# ~/.aws/*, or an instance/ECS role — never hard-code them here.
BEDROCK_REGION = os.getenv("BEDROCK_REGION", os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "")))
BEDROCK_ENDPOINT_URL = os.getenv("BEDROCK_ENDPOINT_URL", "")         # optional VPC endpoint, e.g. https://vpce-….bedrock-runtime.ap-southeast-1.vpce.amazonaws.com

# --- Agent loop ------------------------------------------------------------
MAX_CRITIC_ITERATIONS = int(os.getenv("TSP_MAX_CRITIC_ITERATIONS", "3"))
LESSON_TOP_K = int(os.getenv("TSP_LESSON_TOP_K", "6"))               # lessons injected per extraction
LESSON_MIN_SIMILARITY = float(os.getenv("TSP_LESSON_MIN_SIMILARITY", "0.05"))

# --- Masking ---------------------------------------------------------------
# Counterparties the masking agent recognises out of the box; the list grows
# automatically as sales approve documents with new counterparties.
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
