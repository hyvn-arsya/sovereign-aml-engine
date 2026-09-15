# Releases

## v0.3.0-alpha

**Follow-up security review — 6 findings (2 Critical, 3 High, 1 Low) on the *deployed* system, with regression tests, CDK assertions, and a verified migration chain.**

### What shipped

- **Tenant data isolation (Critical)** — idempotency no longer leaks across tenants: `processing_key = sha256(... | tenant)` diverges byte-identical deeds per tenant, and the persisted audit trail carries `trusts.tenant_id`. Tenant identity is threaded end-to-end from API key → `run_pipeline(tenant_id, tenant_name)` → claim → trust record.
- **Operator-provisioned secrets, deploy-fail-closed (Critical)** — the CDK prod stack **refuses to synthesize** without `-c llm_credentials_arn` and `-c app_secrets_arn` (or `LLM_CREDENTIALS_ARN` / `APP_SECRETS_ARN`). The generated `LlmCredentials` placeholder secret is gone. App config (`API_KEY_SALT`, `SEED_API_KEYS`, `DFAT_SOURCE_URL`, `PEP_API_KEY`) is injected from an operator secret; `SCREENING_MODE` is pinned `production`/`demo` per env.
- **Migrations as a one-off run-task (High)** — the serving container never runs migrations at startup. A dedicated Fargate task (`alembic upgrade head`) shares the image + DB secret and has its own security group, log group, and CDK outputs (`MigrationTaskDefinitionFamily`, `MigrationTaskSecurityGroupId`); README documents the `aws ecs run-task` invocation. New migration `57cdbc23dd16 add tenant scoping to trusts` verified `upgrade head` → `downgrade` against a fresh DB.
- **Failed-run retry (High)** — a terminal `failed` claim is released so the document can be re-claimed and re-processed; the failed attempt stays as audit history (claim cleared). Active/completed/blocked claims still block.
- **DFAT unavailable → blocked, not failed (High)** — `load_dfat_sanctions` errors resolve to the deterministic `BLOCKED — MANUAL REVIEW REQUIRED` outcome with a `screening_incomplete`/`dfat_unavailable_reason` audit trail, mirroring the existing PEP fail-closed path.
- **Production salt enforcement (Low)** — outside development, startup refuses if `API_KEY_SALT` is missing or still the checked-in dev default.
- **Order-independent test DB isolation** — new root `conftest.py` pins `DATABASE_URL` before any module import, fixing a collection-order-sensitive bug where `database` could bind to a stale dev file.

### Test suite (53 root + 11 CDK, all green; 1 dev-only root test skipped)

- `test_priorities.py` +5 (tenant-scoped processing keys; failed-run re-claim lifecycle; DFAT-unavailable blocked outcome with tenant-scoped trust)
- `test_api_auth.py` +2 (sync endpoint passes tenant identity to the pipeline; production runtime requires a real salt)
- CDK +3 (prod synthesis throws without operator ARNs; prod task gets `SCREENING_MODE=production` + app-config secrets; the only command override in the stack is the alembic migration task)

---

## v0.2.0-alpha

**Security review — 7 findings triaged and fixed in one pass, with regression tests and CDK assertions.**

### What shipped

- **Tenant-scoped API keys** — every `/analyze/*` and `/jobs/*` endpoint requires `X-Api-Key`; keys are stored as salted SHA-256 hashes, seeded via `SEED_API_KEYS="tenant:key,..."`, and enforce tenant borders on S3 prefixes (403) and job polling (404). `/health` stays public for the ALB probe.
- **Fail-closed screening sources** — `SCREENING_MODE=production` refuses to screen without `DFAT_SOURCE_URL` (real DFAT consolidated list) and `PEP_API_KEY`; no silent fallback to demo seeds. Demo mode remains, loudly.
- **Blocked outcome** — incomplete extraction (missing doc, chunk failures) resolves to `status=blocked` with `OUTCOME: BLOCKED — MANUAL REVIEW REQUIRED`, propagated through sync and async API paths. Screening never reports success it doesn't have.
- **Concurrency-safe idempotency** — `PipelineRun.processing_key` is UNIQUE; the claim is a `CREATE` whose `IntegrityError` resolves to a skip, so duplicate concurrent submissions converge on one run.
- **IaC hardening** — Fargate→RDS security-group rule added; LLM provider keys moved to a Secrets Manager secret injected as ECS task secrets (operator fills placeholder before deploy); audit bucket now has S3-managed encryption + **Object Lock 7-year compliance retention**.
- **Alembic migrations** — schema is versioned (`alembic upgrade head`); initial baseline migration verified against a fresh database.

### Test suite (48 root + 8 CDK, all green)

- 18 `test_priorities.py` (original data-engineering + 7 new security regressions: blocked outcomes, chunk-failure stats, concurrency claim, production fails closed, demo defaults)
- 12 `test_api_auth.py` (auth 401s, cross-tenant S3 403, tenant-scoped polling 404, blocked/completed job status, plaintext-never-persisted)
- 14 pipeline unit + 3 moto S3 (unchanged) + 1 local mock (now green with `tzdata` installed)
- 8 CDK unit tests asserting the new Object Lock retention, encryption, LLM secret, and Fargate→RDS rule

---

## v0.1.0-alpha

**Core pipeline (4-agent extraction/screening/reporting) tested, live-verified, and passing.**

### What shipped

- **4-agent AML/KYC pipeline** for Australian trust-deed compliance: ABN validation + data gathering (Agent 1), structured entity extraction via LlamaParse + chunk-and-merge Gemini (Agent 2), deterministic DFAT sanctions + PEP screening (Agent 3), and compliance memo drafting via Claude (Agent 4).
- **`LLMProvider` seam**: Agents 2 and 4 no longer hard-code a cloud vendor. A `LLMProvider` protocol with two call shapes (`extract_structured`, `generate_text`) routes through `CloudLLMProvider` (Gemini/Claude, default) or `OllamaLLMProvider` (self-hosted). Provider selection is an admin-configured deployment decision, never per-request — consistent with ADR-001.
- **Ollama context-window guard**: a startup check via `POST /api/show` verifies the active context is large enough for the pipeline's chunk size. With `OLLAMA_REQUIRE_CONTEXT=true`, the provider refuses to start on an undersized model rather than silently truncating input.
- **Async job queue**: `POST /analyze/abn/async` (202 + job ID) with `GET /jobs/{id}` polling, ready to run behind SQS/Fargate.
- **Production-hardened AWS CDK** (in `infrastructure/`): S3 raw + versioned audit buckets, VPC + flow logs, encrypted RDS with backup retention, ECS Fargate behind an ALB with health checks, env-aware dev/prod.

### Live verification

The canonical production path — real LlamaParse (164k chars parsed from a 100-page trust-deed bundle) → chunk-and-merge Gemini extraction (3 chunks) → deterministic screening → real Claude compliance memo — was run end-to-end with real API keys against the project's own `test_pemberton_trust_bundle.pdf`. Every agent made a real service call. Results:

- 9 beneficiaries extracted correctly (including foreign corporate entities from variation deeds)
- 2 red-flag matches flagged (demo PEP seed-data — not a production feed; see "Known gaps")
- Full AUSTRAC-format compliance memo generated

### Named fixes

- **Trustee chunk-merge bug (`_reconcile_trustee`)**: the chunk-and-merge reconciliation used a "last chunk wins" rule for `trustee_company`, so a later chunk returning a low-information placeholder (`"Not specified"`) would silently overwrite a concrete name (`"Pemberton Advisory Pty Ltd"`) extracted from an earlier chunk. Fixed with a new `_reconcile_trustee` helper: placeholders are now detected and skipped, and the first (or latest concrete) value is retained. Re-verified against the real document — `trustee_company` now correctly returns `"Pemberton Advisory Pty Ltd"`.
- **Ollama `/api/show` POST-vs-GET**: the context-length startup guard was calling the endpoint with `requests.get` — a real server would silently 404 the guard. Fixed to `requests.post`.

### Test suite (17 tests, all green)

- **14 pipeline unit tests** covering screening logic, nickname alias expansion, chunk splitting, ABN validation, the trustee chunk-merge reconciliation, and the Ollama provider factory
- **3 moto S3 integration tests** exercising real boto3 S3 code paths (`gather_asic_data` Path A/B, `run_pipeline` audit-trail persistence with `aws:kms` encryption) against an in-process mock — no AWS credentials or bucket needed

### Known gaps

- **Sanctions/PEP data are seed/demo values**, not production feeds. The DFAT consolidated list and the PEP watchlist contain synthetic entries for testing purposes only. See `README.md`.
- **`trustee_company` chronology in per-chunk prompts**: the extraction prompt gives Gemini explicit chronology instructions for beneficiary additions/removals, but not yet for trustee changes within a single chunk. This was not surfaced by the live run (the retirement deed and original deed happened to land in separate chunks), but is a known edge case.
- **Ollama quality trade-off**: a self-hosted 7B model is demonstrably worse at legal-document extraction than Gemini 3.1 Pro. The `LLMProvider` seam proves the architecture doesn't lock you into a foreign cloud; parity is a separate, documented trade-off.
- **LLaMA Parse deprecation**: the `llama-parse` package is deprecated (maintained until May 1, 2026). Migration to `llama-cloud>=1.0` is planned.
- **`trustee_company` reconciliation** handles cross-chunk disagreements correctly after the fix above, but a single chunk spanning both an original and retirement deed (with different trustees) still depends on the LLM's per-chunk extraction — no per-chunk chronology guidance for trustee changes yet.
