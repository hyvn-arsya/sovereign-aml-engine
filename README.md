# Sovereign AML Engine

Automated, AI-driven **AML/KYC beneficial-ownership screening** for Australian financial institutions, built as a 4-agent compliance pipeline that complies with **AUSTRAC AML/CTF** obligations.

The system ingests an Australian trust deed / entity PDF, extracts the underlying ownership structure, deterministically screens all relevant parties against the **DFAT consolidated sanctions list** (and a PEP watchlist), and drafts a structured audit report for the compliance team.

---

## Architecture

A 4-agent orchestration pipeline with deterministic screening at its core and LLMs used only where human-grade document comprehension and drafting are required.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Agent 1   DATA GATHERING          S3 upload, ABN format+checksum    │
│  Agent 2   DOCUMENT EXTRACTION     LlamaParse + Gemini-1.5-Pro       │
│            (chunk & merge)         context-window guard, retries     │
│  Agent 3   DETERMINISTIC SCREENING RapidFuzz vs DFAT sanctions + PEP │
│            (no LLM)                name normalization, redaction      │
│  Agent 4   REPORT DRAFTING         Claude 3.5 Sonnet audit memo      │
└─────────────────────────────────────────────────────────────────────┘
              │                                   │
              ▼                                   ▼
         Audit trail                        PostgreSQL (SQLAlchemy)
         persisted to S3                    local SQLite / AWS RDS
```

- **Agent 1** — Validates the ABN (format + checksum) and retrieves ASIC company data; accepts a pre-uploaded S3 PDF.
- **Agent 2** — Parses trust deeds with LlamaParse and extracts the ownership structure with Gemini. Oversized documents are chunked and truncated to fit the context window; each step has retry and error handling.
- **Agent 3** — The only mandated deterministic step. Normalizes entity names (`Acme Pty Ltd` → `acme`), fuzzy-matches all beneficiaries and the trustee company against the **DFAT sanctions list** (RapidFuzz, 85%+ threshold) and a PEP watchlist. PII is redacted in logs.
- **Agent 4** — Drafts a comprehensive AUSTRAC compliance memo with Claude 3.5 Sonnet, citing the full audit trail.

The orchestrator (`run_pipeline`) coordinates the agents, assigns a deterministic reference number, persists an audit trail to S3 (7-year retention), and writes screening results to the database.

---

## Repository Layout

```
sovereign-aml-engine
├── api.py                    # FastAPI app (REST endpoints)
├── aml_pipeline.py           # 4-agent pipeline orchestrator
├── models.py                 # SQLAlchemy ORM models
├── database.py               # DB engine/session (SQLite local, Postgres/RDS)
├── init_db.py                # Create database tables
├── test_aml_pipeline.py      # Unit tests for screening logic
├── Dockerfile                # Containerized FastAPI (uvicorn, port 8000)
├── docker-compose.yml        # Local PostgreSQL for development
├── sovereign-aml.yaml        # Raw CloudFormation IaC reference
├── .env.example              # Env var template (never commit real .env)
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

### 3. Initialize the database

```bash
python init_db.py
```

### 4. Run the API

```bash
uvicorn api:app --reload
```

**Endpoints** (OpenAPI docs at `http://localhost:8000/docs`):

| Method | Path            | Description                                                     |
|--------|-----------------|-----------------------------------------------------------------|
| GET    | `/health`       | Liveness probe used by the ALB health check                    |
| POST   | `/analyze/abn`  | Run the full 4-agent pipeline for an ABN, return compliance memo |

```bash
curl -X POST http://localhost:8000/analyze/abn \
  -H "Content-Type: application/json" \
  -d '{"company_abn": "51824753556"}'
```

> The synchronous MVP keeps the connection open for the 20–40s pipeline runtime.

### 5. Run the tests

```bash
pip install -r requirements-dev.txt
python -m pytest                         # root pipeline tests
python -m pytest infrastructure/tests     # CDK infrastructure tests
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
- **Agents**: LangChain + LlamaParse, Google Gemini, Anthropic Claude
- **Screening**: RapidFuzz (deterministic, no LLM)
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
