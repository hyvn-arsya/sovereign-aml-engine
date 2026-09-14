# Sovereign AML Engine

Automated, AI-driven **AML/KYC beneficial-ownership screening** for Australian financial institutions, built as a 4-agent compliance pipeline that complies with **AUSTRAC AML/CTF** obligations.

The system ingests an Australian trust deed / entity PDF, extracts the underlying ownership structure, deterministically screens all relevant parties against the **DFAT consolidated sanctions list** (and a PEP watchlist), and drafts a structured audit report for the compliance team.

---

## ✳ The Core Design Decision: Deterministic vs Generative

The single most important architectural choice in this project is **which agents use LLMs and which don't**. Compliance screening is not a place for improvisation: if an AUSTRAC examiner asks *"why was this entity flagged / not flagged?"*, the answer must be a traceable, deterministic, explainable algorithm — not a prompt response that can differ between calls.

So **Agent 3 (sanctions & PEP screening) is pure deterministic RapidFuzz code** — zero LLM — while **Agents 2 (document extraction) and 4 (report drafting) use LLMs** where human-grade comprehension and drafting genuinely require them.

| Agent | Method | Why |
|-------|--------|-----|
| **2 — Extraction** | LlamaParse + Gemini | Understanding hundreds of pages of legal text — genuinely needs LLM comprehension |
| **3 — Screening** | **Deterministic RapidFuzz** | A regulated decision: auditable, explainable, zero hallucination, near-zero cost at scale |
| **4 — Reporting** | Claude Sonnet | Human-facing narrative from a fixed, deterministic audit trail |

Full reasoning — including AUSTRAC Part 11 record-keeping, cost, and the rejected "LLM for everything" alternative — is in **[`docs/ADR-001-deterministic-vs-generative.md`](docs/ADR-001-deterministic-vs-generative.md)**.

**A concrete example of why this matters:** fuzzy matching alone misses common nickname/diminutive variants — a sanctioned *"Robert Smith"* recorded on a deed as *"Bob Smith"* scores only ~76% (below the 85% flag threshold) and would silently slip through. Because Agent 3 is deterministic and auditable, the fix is a curated alias table that expands *Bob→Robert, Bill→William, Dick→Richard* and re-scores, with every such match explicitly labelled `"alias expansion"` in the audit trail. This is the difference between "an AI that screens" and "an AI pipeline a compliance team can defend."

> **Honesty note:** this alias table is a deliberately small (~45-entry) English-language **seed list**, not a claim of coverage. It will not catch transliteration variants of non-English names — arguably a bigger real-world AML risk given the composition of DFAT's actual sanctions list — and in production it would be backed by a proper reference-data vendor. Like the mocked DFAT/PEP data in the pipeline, it's there to prove the mechanism, not to assert completeness.

---

## Architecture

A 4-agent orchestration pipeline with deterministic screening at its core and LLMs used only where human-grade document comprehension and drafting are required.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Agent 1   DATA GATHERING          S3 upload, ABN format+checksum    │
│  Agent 2   DOCUMENT EXTRACTION     LlamaParse + LLMProvider          │
│            (chunk & merge)         default Gemini, local Ollama opt  │
│  Agent 3   DETERMINISTIC SCREENING RapidFuzz vs DFAT sanctions + PEP │
│            (no LLM)                name normalization, redaction      │
│  Agent 4   REPORT DRAFTING         LLMProvider — default Claude      │
│            (memo drafting)         local Ollama option               │
└─────────────────────────────────────────────────────────────────────┘
              │                                   │
              ▼                                   ▼
         Audit trail                        PostgreSQL (SQLAlchemy)
         persisted to S3                    local SQLite / AWS RDS
```

- **Agent 1** — Validates the ABN (format + checksum) and retrieves ASIC company data; accepts a pre-uploaded S3 PDF.
- **Agent 2** — Parses trust deeds with LlamaParse and extracts the ownership structure through the **`LLMProvider`** seam (Gemini by default). Oversized documents are chunked and truncated to fit the context window; each step has retry and error handling.
- **Agent 3** — The only mandated deterministic step. Normalizes entity names (`Acme Pty Ltd` → `acme`), fuzzy-matches all beneficiaries and the trustee company against the **DFAT sanctions list** (RapidFuzz, 85%+ threshold) and a PEP watchlist. PII is redacted in logs.
- **Agent 4** — Drafts a comprehensive AUSTRAC compliance memo with Claude Sonnet (via the same `LLMProvider` seam), citing the full audit trail.

The orchestrator (`run_pipeline`) coordinates the agents, assigns a deterministic reference number, persists an audit trail to S3 (7-year retention), and writes screening results to the database.

---

## Architecture: Current vs Production

The pipeline's *processing* agents are identical in both diagrams — the difference is the transport and worker topology of the envelope around them.

```
CURRENT IMPLEMENTATION (this repo)
┌──────────────┐   200/500   ┌────────────────────┐    runs in-process    ┌──────────────┐
│  FastAPI     │ ──────────► │  Background worker │ ────────────────────► │ run_pipeline │
│  api.py      │             │  (BackgroundTasks/ │                      │  (4 agents)  │
│              │             │   threading pool)  │                      └──────┬───────┘
└──────────────┘             └────────────────────┘                             │
         worker owns the scheduling: a request spawns a thread in the same      ▼
         process as the API. Fine for a single instance / demo; does not   PostgreSQL + S3
         survive crashes or scale beyond one process.
```

```
PRODUCTION EVOLUTION (deployment target)
┌──────────────┐  POST /analyze/abn/async   ┌──────────┐   pull   ┌──────────────────┐
│  FastAPI     │ ─────────────────────────► │   SQS     │ ──────► │  ECS/Fargate     │
│  (stateless) │ ◄───────────────────────── │ queue     │         │  worker (scale    │
│              │   job_id + status polling  └──────────┘          │   to N tasks)     │
└──────────────┘                                                  └────────┬─────────┘
                                                                           ▼
                                                                    PostgreSQL + S3
```

- **Current** — the FastAPI app runs the pipeline on a background task inside the API process. The `/analyze/abn/async` endpoint already returns a `job_id` immediately; the worker code is factored so it can be lifted onto SQS/Fargate as-is. Threads in a single process: fine for a load-tested single box, but a crash loses the in-flight job.
- **Production** — the API becomes a thin, stateless submission layer: it enqueues an SQS message and the consumer polls a durable queue. A **durable queue + idempotent processing key** is what makes this safe: if the ECS worker is killed mid-run, its retry is *deduplicated* (same processing key → SKIP) instead of producing a duplicate result. Persistence (PostgreSQL + S3) is unchanged — only the delivery semantics change.
- **Why not change it now?** The current in-process worker is behaviourally equivalent for one box, and the pipeline is already idempotent at the point the queue would retry it. SQS/Fargate adds durability and horizontal scale; it changes no processing logic.

---

## Data Engineering Design

The screening logic is deliberately simple; the parts that matter operationally are the data-engineering decisions around how a screening *run* is identified, measured, and stored.

- **Idempotency (content-addressed processing).** A run's identity is a deterministic `processing_key` — `sha256(document_hash | ABN | pipeline_version | extraction_model | screening_algorithm_version)`. Deleting all `run_id`-based logic: the same document + ABN + tool versions always resolves to the same key, so retries and duplicate submissions are recognised as replays and skipped, no matter what random `run_id` the caller issued. Bumping any version component (or uploading a revised deed) yields a genuinely new key and a legitimate re-process. This is *idempotent processing*, not exactly-once: a worker can still crash after an external side effect (e.g. the memo pushed downstream) and before recording completion — those are traceable through the audit trail rather than made impossible.

- **Incremental processing.** Each run is self-contained (`PIPELINE_VERSION`, `EXTRACTION_MODEL`, `SCREENING_ALGORITHM_VERSION` are frozen into the processing key), so a batch re-screen after a model or sanctions-list upgrade is a fresh `processing_key`, not a mutation of history. Old results stay readable for audit; new results are additive.

- **Entity resolution (promoted into the schema).** Nickname/diminutive alias expansion used to live only inside Agent 3's in-memory matching. It is now persisted: `entities` holds the canonical screened party, `entity_aliases` records the alias form that closed a match, and `screening_matches` records *how* the match happened (`direct` vs `alias_expansion`) for defensible audit.

- **Data quality.** The screening threshold and the seed alias table are intentionally small and *known to be incomplete* (see the honesty note in the design decision section). The schema is built to survive upgrade: references are keyed by `entity_id` (not the raw name string), so canonical-name corrections propagate, and `match_method` makes true-signal vs alias-signal matches distinguishable at query time.

- **Observability.** Every run lands in `pipeline_runs` with `started_at`, `completed_at`, `status`, `chunk_count`, `entity_count`, `red_flag_count`, and `duration_ms` — one row per attempt. Spot-check queries were tuned against this design, e.g. `SELECT AVG(duration_ms), AVG(entity_count), AVG(chunk_count), SUM(red_flag_count) FROM pipeline_runs WHERE status = 'completed'`. Skips (idempotent replays) and failed runs are represented so performance aggregates don't accidentally include wall-clock time for requests that did no work.

- **Auditability.** AUSTRAC Part 11 record-keeping is the driver: every decision is either deterministic (Agent 3, scripted in the audit trail) or regenerable (Agent 4 memo is reconstructed from the same audit trail). The S3 trail (`extraction_output.json`, `screening_result.json`, `compliance_memo.txt`) and the relational rows are written in the same transaction story, encrypted with KMS.

---

## Repository Layout

```
sovereign-aml-engine
├── api.py                    # FastAPI app (sync + async job endpoints)
├── aml_pipeline.py           # 4-agent pipeline orchestrator
├── llm_provider.py           # LLMProvider seam (cloud default + local Ollama)
├── models.py                 # SQLAlchemy ORM models (Trust/PipelineRun/Entity/etc.)
├── database.py               # DB engine/session (SQLite local, Postgres/RDS)
├── init_db.py                # Create database tables
├── test_aml_pipeline.py      # Unit tests for screening logic
├── test_priorities.py        # Idempotency + pipeline_runs + entity model (moto + in-memory SQLite)
├── test_moto_s3.py           # Moto-backed S3 integration tests (no AWS required)
├── Dockerfile                # Containerized FastAPI (uvicorn, port 8000)
├── docker-compose.yml        # App + PostgreSQL, one-command demo
├── sovereign-aml.yaml        # Raw CloudFormation IaC reference
├── requirements.txt          # Runtime dependencies
├── requirements-dev.txt      # Test / dev-only dependencies
├── .env.example              # Env var template (never commit real .env)
├── docs/                     # Architecture Decision Records (start with ADR-001)
└── infrastructure/           # ☁️ AWS CDK (Python) — production deployment
    ├── app.py                # CDK entry point, env-aware stack naming
    ├── cdk.json
    └── infrastructure/
        └── infrastructure_stack.py  # S3, VPC, RDS, ECS Fargate + ALB
```

---

## Getting Started (Local)

### 1. Set up the environment

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure keys

```bash
cp .env.example .env     # then fill in your LLM provider keys
```

Required: `LLAMACLOUD_API_KEY`, `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`.
Without a `DB_HOST`, the app falls back to a local SQLite file — no database setup needed to get started.

**LLM provider** (optional): the pipeline calls Gemini (extraction) and Claude (reporting) by default through the `LLMProvider` seam. To run extraction/reporting on a **self-hosted model** instead, set `LLM_PROVIDER=ollama` (plus `OLLAMA_BASE_URL` / `OLLAMA_MODEL`). If you use Ollama, you **must** size the model's context window to fit the pipeline's chunk size — set `OLLAMA_CONTEXT_LENGTH` on the server or bake `PARAMETER num_ctx <size>` into a custom Modelfile — otherwise over-length chunks are silently truncated (see `llm_provider.py`). The provider refuses to start with `OLLAMA_REQUIRE_CONTEXT=true` if the active context is too small.

### 3. Initialize the database

```bash
python init_db.py
```

### 4. Run the API

```bash
uvicorn api:app --reload
```

**Endpoints** (OpenAPI docs at `http://localhost:8000/docs`):

| Method | Path                  | Description                                                     |
|--------|-----------------------|-----------------------------------------------------------------|
| GET    | `/health`             | Liveness probe used by the ALB health check                    |
| POST   | `/analyze/abn`        | Run the full 4-agent pipeline, block for the compliance memo   |
| POST   | `/analyze/abn/async`  | Queue the pipeline (202 + `job_id`), return immediately        |
| GET    | `/jobs/{job_id}`      | Poll an async job's status and result                          |

```bash
curl -X POST http://localhost:8000/analyze/abn \
  -H "Content-Type: application/json" \
  -d '{"company_abn": "51824753556"}'

# Async (returns immediately, then poll the job):
JOB=$(curl -s -X POST http://localhost:8000/analyze/abn/async \
  -H "Content-Type: application/json" -d '{"company_abn":"51824753556"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['job_id'])")
curl -s http://localhost:8000/jobs/$JOB
```

> The synchronous endpoint keeps the connection open for the 20–40s pipeline runtime. For production, use the async endpoint — the background worker is factored to run behind an SQS/Fargate consumer.

### 5. Run the tests

```bash
pip install -r requirements-dev.txt
python -m pytest                         # root pipeline + moto S3 integration tests
python -m pytest infrastructure/tests     # CDK infrastructure tests
```

The root suite includes `test_moto_s3.py`, which exercises the **real boto3 S3 code paths** in `aml_pipeline` — `gather_asic_data` (registry → upload) and the audit-trail persistence inside `run_pipeline` (`extraction_output.json`, `screening_result.json`, `compliance_memo.txt`, each encrypted with `aws:kms`) — against an **in-process S3 mock** (`moto`). No AWS credentials or bucket are needed: moto intercepts botocore's S3 requests at the transport layer, so the same `put_object` calls the pipeline makes in production run for real. The external registry HTTP and the LLM agents are mocked; the S3 layer itself is the thing under test.

`test_priorities.py` goes one step further for the data-engineering layer: it runs the **real `run_pipeline`** against moto S3 **plus an in-memory SQLite DB** (with only the LLM agents mocked), asserting that (a) the deterministic `processing_key` skips a content replay under a fresh `run_id`, (b) a new document reprocesses normally, and (c) `pipeline_runs`, `entities`, `entity_aliases`, and `screening_matches` rows land with correct runtime metrics and `match_method` tags.

To verify the S3 layer locally, run the moto-backed tests alone:

```bash
python -m pytest test_moto_s3.py -v
```

---

## Deployment

Two infrastructure options are included:

### AWS CDK (recommended, `infrastructure/`)

Python AWS CDK app that provisions a complete, production-hardened stack:

- **S3** — raw-document bucket + append-only audit bucket (versioned)
- **VPC** with CloudWatch flow logs
- **RDS PostgreSQL** — encrypted, 7-day backup retention
- **ECS Fargate** behind an **Application Load Balancer** with health checks on `/health`
- Optional **HTTPS** via ACM certificate + HTTP redirect (provide `certificate_arn`)
- Deployment circuit breaker, `min_healthy_percent`, cost-allocation tags, `CfnOutputs`
- `env` (dev/prod) parameterization via CDK context

```bash
cd infrastructure
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cdk synth                              # '-c env=prod' for prod profile
cdk deploy SovereignAml-dev            # or SovereignAml-prod
```

### Raw CloudFormation (`sovereign-aml.yaml`)

A standalone template (VPC, RDS, ECS Fargate, S3) provided as a reference alternative to CDK.

---

## Tech Stack

- **API**: FastAPI, Uvicorn, Pydantic
- **Agents**: LangChain + LlamaParse, via an **`LLMProvider` seam** — Google Gemini (extraction) and Anthropic Claude (reporting) by default, with a **self-hosted Ollama** option (`LLM_PROVIDER=ollama`)
- **Screening**: RapidFuzz (deterministic, no LLM), curated given-name alias table
- **Job queue**: In-process async jobs (`POST /analyze/abn/async`) + `GET /jobs/{id}` polling; worker ready to run on SQS/Fargate
- **Storage**: SQLAlchemy (SQLite local / PostgreSQL), Amazon S3 (+ KMS encryption)
- **Cloud**: AWS CDK (Python) — S3, VPC, RDS, ECS Fargate, ALB, CloudWatch
- **Containerization**: Docker, docker-compose

---

## Security & Compliance Notes

- `validate_env()` enforces required secrets before the pipeline runs.
- All S3 writes use **server-side KMS encryption** (`aws:kms`).
- Audit trail and memo persisted to S3 with **7-year retention** for AUSTRAC record-keeping.
- Deterministic **reference number** for each run.
- PII redacted (`redact()`) in logs; structured JSON logging.
- `.env` is gitignored — only the placeholder `.env.example` is committed.

---

## Disclaimer

This project is a demonstration/portfolio implementation of automated AML screening concepts. It is **not** certified AUSTRAC AML/CTF program software and should not be used as the sole basis for regulatory compliance decisions. Production deployment requires review by qualified compliance and security professionals.
