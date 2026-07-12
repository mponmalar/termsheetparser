# Term Sheet Parser — self-learning multi-agent trade capture for EQD structured products

A multi-agent system that turns counterparty term sheets (FCN / BEN / Phoenix
autocallables with knock-out & knock-in features, received as PDF or Word from
dealers such as Citi, UBS, Standard Chartered, J.P. Morgan) into structured
trade data ready for booking in **Murex** — with a sales-facing review GUI and
a feedback loop where **every manual correction becomes a lesson the agents
apply on future documents**.

```
Upload (PDF/Word) ─▶ Ingestion ─▶ Masking ─▶ Memory ─▶ Extraction ◀─┐
                     agent        agent      agent      agent       │ critique
                                                          │         │
                                                          ▼         │
                                                        Critic ─────┘
                                                        agent
                                                          │ accepted
                                                          ▼
                              Sales review GUI ◀── Finalizer agent
                              edit / approve
                                   │
                        every edit = a Lesson ──▶ applied on next document
                                   │
                            approve ─▶ Murex publish queue
```

## Key properties

| Requirement | How it is met |
|---|---|
| Upload front end for sales | Web GUI at `/` — drag-and-drop PDF/Word, live blotter, review ledger |
| Mask sensitive data before the LLM | `MaskingAgent` runs **locally**: counterparty names, emails, phones, accounts, SWIFT/BIC, contact persons → `[CPTY_1]`-style tokens. The reversible map never leaves the box; values are restored locally after extraction |
| Bedrock LLM — gateway **or** direct | `TSP_LLM_PROVIDER` switches between the bank gateway URL (`gateway`), direct AWS Bedrock via boto3/SigV4 (`bedrock`), and an offline deterministic **MockLLM** (`mock`); `auto` picks sensibly. Config-only switch, no code change |
| Persist for self-learning | SQLite by default, PostgreSQL + pgvector recommended. Tables: documents, extractions, corrections, **lessons**, agent_runs, publish_queue |
| Visual presentation of extractions | Field ledger grouped by Identification / Dates / Economics / Underlyings / Barriers / Settlement, with per-field provenance chips (LLM / LESSON / EDITED) |
| Approve → save for Murex | Approval locks the extraction and queues a Murex-shaped payload (`publish_queue`) for the phase-2 connector |
| Manual edit in GUI | Inline editing on every field; underlyings editable as a table/JSON |
| Every edit is a lesson | Each edit persists a `Correction` **and** a `Lesson` (with a masked document fingerprint). The `MemoryAgent` retrieves the most similar lessons per new document and injects them into the extraction prompt |
| Agents talk to themselves | `ExtractionAgent ⇄ CriticAgent` loop: the critic validates EQD invariants (date ordering, KI < strike, KO > KI, sane coupon…) and sends written feedback back for re-extraction, up to `TSP_MAX_CRITIC_ITERATIONS`. The whole conversation is stored and rendered in the GUI |
| Appropriate framework | **LangGraph** state graph orchestrates the agents; FastAPI + SQLAlchemy backend; zero-build vanilla-JS front end (bank-network friendly, no CDNs) |

## Quick start (fully offline, mock LLM)

```bash
git clone -b draft https://github.com/mponmalar/termsheetparser.git
cd termsheetparser
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.app.main:app --port 8000
# open http://localhost:8000 and upload a file from samples/
```

Dependencies are installed inside `.venv/` and never touch your global Python.
Run `deactivate` to leave the environment; next time just `source .venv/bin/activate`.

Or with Docker (PostgreSQL included): `docker compose up --build`

## Connect a real LLM — two access models, one switch

**Bank gateway** (HTTP + API key):

```bash
export TSP_LLM_PROVIDER=gateway
export BEDROCK_GATEWAY_URL="https://llm-gateway.bank.internal/bedrock/v1/messages"
export BEDROCK_API_KEY="…"
```

**Direct AWS Bedrock** (boto3, SigV4 / IAM — Converse API):

```bash
export TSP_LLM_PROVIDER=bedrock
export BEDROCK_REGION=ap-southeast-1   # credentials via IAM role / AWS_PROFILE / env keys
```

Leave `TSP_LLM_PROVIDER=auto` and it selects gateway → direct → mock based on
what's configured. The gateway is expected to speak the Anthropic
messages-API shape; if yours wraps Bedrock `invoke-model`, adapt one function
(`_call_gateway` in `backend/app/services/llm_client.py`). Masked text only,
in every mode.

## Try the learning loop in 60 seconds

1. Upload `samples/FCN_Citi_WorstOf_3Stock_USD.pdf` — agents extract, critic
   reviews, status becomes *Pending review*.
2. Change `coupon_frequency` from `Monthly` to `Quarterly`, click **Save** —
   a lesson appears under *What the agents learned*.
3. Click **Re-run agents** — the extraction now returns `Quarterly` with a
   `LESSON` provenance chip: the agents learned from the correction.
4. Click **Approve → queue for Murex** to see the generated Murex payload.

## Sample term sheets

`samples/` contains four realistic **synthetic** term sheets (three PDFs, one
Word document) covering FCN worst-of, BEN, Phoenix autocall and a single-stock
FCN, in USD/SGD/HKD. Real dealer term sheets are confidential and cannot be
redistributed, so these reproduce the typical structure, vocabulary, and table
layouts with fictitious trade details — regenerate or extend them with
`python samples/generate_samples.py`.

## Tests

```bash
python -m pytest backend/tests -v
```

14 tests cover: masking (counterparty/PII removed, economics untouched,
round-trip restore), end-to-end extraction of all four samples, the agent
trace, **the learning loop** (edit → lesson → re-run applies it), approval →
Murex payload, and edit-locking after approval.

## Documentation

* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components, flow diagram, sequence diagrams, data model, learning design
* [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — local, Docker, bank-network deployment, configuration reference
* [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — step-by-step guide for the sales team

## Repository layout

```
backend/app/agents/      ingestion, masking, memory, extraction, critic, finalizer, LangGraph graph
backend/app/services/    llm_client (Bedrock gateway), mock_llm, similarity, murex payload builder
backend/app/api/         REST API
backend/app/static/      sales GUI (no build step)
backend/app/db/          SQLAlchemy models + session
backend/tests/           pytest suite
samples/                 synthetic term sheets + generator
docs/                    architecture / deployment / user guide
```
