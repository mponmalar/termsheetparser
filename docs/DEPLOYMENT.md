# Deployment Guide

## 1. Local development (offline, MockLLM + SQLite)

```bash
git clone https://github.com/mponmalar/termsheetparser -b draft
cd termsheetparser
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

Open http://localhost:8000. No environment variables are required: with
`BEDROCK_GATEWAY_URL` unset, the deterministic MockLLM is used and the SQLite
database is created under `./data/`.

Run the test suite:

```bash
python -m pytest backend/tests -v
```

Regenerate / extend the sample term sheets:

```bash
python samples/generate_samples.py
```

## 2. Docker / docker-compose (with PostgreSQL + pgvector)

```bash
docker compose up --build
```

This starts the app on port 8000 and a `pgvector/pgvector:pg16` PostgreSQL.
Pass gateway credentials through the environment:

```bash
BEDROCK_GATEWAY_URL=https://llm-gw.bank.internal/bedrock/v1/messages \
BEDROCK_API_KEY=… docker compose up --build
```

## 3. Bank-network production deployment

### Topology

```
[Sales browsers] ──HTTPS──▶ [App: uvicorn/gunicorn behind the bank reverse proxy]
                                   │                         │
                                   ▼                         ▼
                        [PostgreSQL + pgvector]     [LLM gateway URL → Bedrock]
```

* Deploy the app **inside** the office network. Only the app's outbound call
  to `BEDROCK_GATEWAY_URL` crosses toward the gateway, and that call carries
  masked text only.
* Terminate TLS at the bank's standard reverse proxy; put the app behind the
  bank SSO (the API accepts an `edited_by` / `approved_by` identity — wire it
  to the SSO principal in the proxy or a small middleware).
* Run with a process manager, e.g.
  `gunicorn backend.app.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000`.

### Configuration reference

| Variable | Default | Purpose |
|---|---|---|
| `BEDROCK_GATEWAY_URL` | *(empty → MockLLM)* | Bank's Bedrock gateway endpoint (messages-API shape) |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-5-sonnet-20241022-v2:0` | Model routed by the gateway |
| `BEDROCK_API_KEY` | *(empty)* | Sent as `Authorization: Bearer …` |
| `BEDROCK_AUTH_HEADER` | `Authorization` | Change if the gateway expects e.g. `x-api-key` |
| `BEDROCK_TIMEOUT_SECONDS` | `120` | Gateway call timeout |
| `TSP_DATABASE_URL` | SQLite in `./data` | e.g. `postgresql+psycopg://user:pass@host:5432/termsheets` |
| `TSP_DATA_DIR` | `./data` | Upload storage + SQLite location |
| `TSP_MAX_CRITIC_ITERATIONS` | `3` | Extraction ⇄ critic loop budget |
| `TSP_LESSON_TOP_K` | `6` | Lessons injected per extraction |
| `TSP_LESSON_MIN_SIMILARITY` | `0.05` | Minimum cosine similarity for a lesson to be applied |

For PostgreSQL, also `pip install "psycopg[binary]"`.

### Upgrading lesson retrieval to pgvector

1. Add an `embedding vector(1024)` column to `lessons`.
2. On lesson creation, call the gateway's embedding model (e.g. Titan
   Embeddings) with the masked fingerprint.
3. Replace `services/similarity.rank_lessons` with a
   `SELECT … ORDER BY embedding <=> :query_embedding LIMIT :k` query.

Nothing else changes — the MemoryAgent interface is a single function.

### Murex connectivity (phase 2)

Approved trades land in `publish_queue` with a Murex-shaped payload
(`services/murex.py`). Implement a drainer that maps the payload to your MxML
import or Murex booking REST endpoint, then writes back `status=SENT/ACKED`
and `murex_trade_id`. The review/approval application needs no changes.

## 4. Operational notes

* **Backups:** the `lessons` table is the system's accumulated intelligence —
  include it in the standard database backup policy.
* **Monitoring:** `/health` for liveness; `/api/stats` exposes document
  counts, active lessons and a field-accuracy proxy suitable for dashboards.
* **Data retention:** uploads are stored under `TSP_DATA_DIR/uploads`;
  apply the bank's retention policy to that directory and to `documents.raw_text`.
