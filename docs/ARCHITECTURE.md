# Architecture

## 1. Overview

The system converts dealer term sheets for EQD structured products
(FCN, BEN, Phoenix/autocallable notes with knock-out and knock-in features)
into structured, review-approved trade data destined for Murex.

Three design constraints shaped it:

1. **Sensitive data must not cross the office network.** Masking runs
   locally *before* any text reaches the LLM gateway; unmasking runs locally
   *after* the response returns. The token→value map is only ever persisted
   in the bank-side database.
2. **The system must improve with use.** Every manual correction by sales is
   converted into a durable *lesson* that is retrieved and injected into the
   extraction prompt of future, similar documents.
3. **Every automated decision must be explainable.** The critic uses
   deterministic EQD domain rules (not a second opaque LLM vote), and the
   full agent conversation is persisted and rendered in the GUI.

## 2. Component / flow diagram

```mermaid
flowchart TB
    subgraph Client["Sales front end (browser)"]
        UI[Upload / Blotter / Review ledger / Lessons]
    end

    subgraph App["FastAPI application (bank network)"]
        API[REST API]
        subgraph Graph["LangGraph agent pipeline"]
            ING[IngestionAgent<br/>pdfplumber / python-docx]
            MASK[MaskingAgent<br/>counterparty + PII → tokens]
            MEM[MemoryAgent<br/>retrieve top-k lessons]
            EXT[ExtractionAgent<br/>prompt = schema + lessons + critique]
            CRIT[CriticAgent<br/>EQD domain validation]
            FIN[FinalizerAgent<br/>unmask locally + persist]
        end
        MRX[Murex payload builder]
    end

    subgraph LLM["LLM boundary (TSP_LLM_PROVIDER)"]
        GW[gateway: bank Bedrock gateway URL<br/>bedrock: direct AWS boto3/SigV4<br/>mock: offline extractor]
    end

    subgraph DB["Database (SQLite dev / PostgreSQL+pgvector prod)"]
        D1[(documents)]
        D2[(extractions)]
        D3[(corrections)]
        D4[(lessons)]
        D5[(agent_runs)]
        D6[(publish_queue)]
    end

    UI -->|upload PDF/Word| API --> ING --> MASK --> MEM --> EXT
    EXT -->|masked text only| GW --> EXT
    EXT --> CRIT
    CRIT -->|critique, ≤ N loops| EXT
    CRIT -->|accepted| FIN
    FIN --> D2
    MEM <--> D4
    API <--> D1 & D2 & D3 & D5 & D6
    UI -->|edit fields| API -->|Correction + Lesson| D3 & D4
    UI -->|approve| API --> MRX --> D6
    D6 -.->|phase 2 connector| MUREX[(Murex<br/>MxML / REST)]
```

**The security boundary:** only the `masked_text` string crosses to the
gateway. `raw_text` and `mask_map` never appear in any prompt.

## 3. Sequence diagram — upload → review

```mermaid
sequenceDiagram
    actor S as Sales
    participant UI as GUI
    participant API as FastAPI
    participant G as LangGraph pipeline
    participant L as Bedrock gateway / MockLLM
    participant DB as Database

    S->>UI: drop term sheet (PDF/Word)
    UI->>API: POST /api/documents
    API->>DB: insert Document (UPLOADED)
    API-->>UI: document_id (processing)
    API->>G: run_pipeline(document_id)

    G->>G: IngestionAgent: parse text + tables
    G->>G: MaskingAgent: CPTY/PII → tokens, build mask_map
    G->>DB: MemoryAgent: load lessons, rank by similarity
    loop until critic accepts (≤ MAX_ITERATIONS)
        G->>L: ExtractionAgent: schema + lessons (+ critique) + MASKED text
        L-->>G: JSON fields
        G->>G: CriticAgent: EQD invariants (dates, KI<strike, KO>KI, …)
        alt issues found
            G->>G: write critique → back to ExtractionAgent
        end
    end
    G->>G: FinalizerAgent: restore tokens from local mask_map
    G->>DB: save Extraction + AgentRuns, Document → PENDING_REVIEW
    UI->>API: poll GET /api/documents/{id}
    API-->>UI: fields + provenance + agent conversation + masked preview
    UI-->>S: review ledger
```

## 4. Sequence diagram — feedback learning loop

```mermaid
sequenceDiagram
    actor S as Sales
    participant UI as GUI
    participant API as FastAPI
    participant DB as Database
    participant MEM as MemoryAgent
    participant EXT as ExtractionAgent

    S->>UI: edit field (e.g. coupon_frequency → Quarterly)
    UI->>API: PATCH /api/extractions/{id}/fields
    API->>DB: insert Correction (audit)
    API->>DB: insert Lesson (field, wrong→right, masked fingerprint)
    API-->>UI: updated fields, chip = EDITED

    Note over S,DB: …later, a similar term sheet arrives (or re-run)…

    API->>MEM: pipeline start
    MEM->>DB: load non-superseded lessons
    MEM->>MEM: TF-IDF cosine vs new masked document
    MEM->>EXT: top-k lessons as <LESSONS> prompt block
    EXT->>EXT: extraction honours the lesson
    EXT-->>UI: field returns corrected value, chip = LESSON
```

## 5. Sequence diagram — approval → Murex

```mermaid
sequenceDiagram
    actor S as Sales
    participant API as FastAPI
    participant DB as Database
    participant MX as Murex (phase 2)

    S->>API: POST /api/extractions/{id}/approve
    API->>DB: Extraction.approved = true (edits locked)
    API->>DB: insert PublishRecord (Murex-shaped payload, QUEUED)
    API-->>S: payload preview
    MX-->>DB: connector drains queue (MxML / REST), writes SENT/ACKED + murex_trade_id
```

## 6. The agents

| Agent | Responsibility | Key detail |
|---|---|---|
| **IngestionAgent** | PDF/Word → text | pdfplumber page text **and** table rows (`a \| b \| c`), python-docx paragraphs + tables |
| **MaskingAgent** | Remove sensitive data pre-LLM | Ordered passes: emails → SWIFT/BIC → accounts → phones → counterparty legal names (word-bounded, longest-first, entity-suffix aware) → contact-line person names. Same entity ⇒ same token. Economics (tickers, barriers, dates) deliberately untouched |
| **MemoryAgent** | Self-learning retrieval | Ranks all active lessons against the masked document (TF-IDF cosine; pgvector embeddings in production) and formats the top-k as a `<LESSONS>` prompt block. Also records new lessons from corrections |
| **ExtractionAgent** | LLM extraction | Prompt = system rules + field schema (from `schemas.py`, descriptions are the contract) + lessons + optional critic feedback + masked text. Parses robust JSON |
| **CriticAgent** | Self-review | Deterministic EQD invariants: required fields, `trade ≤ fixing ≤ issue ≤ final ≤ maturity`, `KI < 100`, `KI ≤ strike`, `KO > KI`, coupon ∈ (0, 60] % p.a., ISO currency, underlyings named, autocall⇒KO. On failure writes a critique and loops back (≤ `TSP_MAX_CRITIC_ITERATIONS`) |
| **FinalizerAgent** | Unmask + persist | Restores `[CPTY_n]`-style tokens in counterparty/issuer/calculation-agent fields using the **local** mask map, saves the extraction with per-field provenance, flips the document to `PENDING_REVIEW` |

The Extraction ⇄ Critic loop is the "agents talking to themselves"
conversation; every turn is persisted as an `AgentRun` and shown in the GUI
timeline.

## 7. Data model

```
documents      1 ──▶ * extractions ──▶ * corrections
documents      1 ──▶ * agent_runs
extractions    1 ──▶ * publish_queue
lessons        (independent; linked to context via masked fingerprint,
                referenced by extractions.lessons_used)
```

Why this database design for self-learning:

* **Lessons are first-class rows**, not prompt hacks — auditable, countable
  (`times_applied`), reversible (`superseded` flag instead of deletion).
* **The fingerprint is the masked text**, so similarity search never touches
  sensitive values and lessons transfer across counterparties that use the
  same template dialect.
* **Per-field provenance** (`field_meta`) lets the GUI show *why* a value is
  what it is (LLM / LESSON / EDITED) — trust is a feature.
* Production: PostgreSQL + **pgvector**; swap `services/similarity.py`
  for an embedding + `ORDER BY embedding <=> query` and everything else is
  unchanged.

## 8. Framework choices

* **LangGraph** — explicit state graph with a conditional critic loop;
  the pipeline is testable node-by-node and the state is a plain dict.
* **FastAPI + SQLAlchemy** — typed API, background pipeline execution,
  SQLite→PostgreSQL portability.
* **Provider-switchable LLM client** — `TSP_LLM_PROVIDER` selects bank
  gateway (HTTP+key), direct AWS Bedrock (boto3 Converse API, SigV4/IAM
  credential chain, optional VPC endpoint), or the deterministic MockLLM —
  behind one `complete(prompt)` interface. The whole system (including the
  learning loop) runs and is CI-tested offline; flipping providers is an
  environment variable, not a code change, and explicit misconfiguration
  fails loudly instead of silently degrading to mock.
* **Zero-build front end** — no npm, no CDN fonts/scripts; deploys inside a
  locked-down bank network as static files served by the API.
