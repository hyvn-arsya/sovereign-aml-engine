# Sovereign AML Engine — Portfolio Writeup

A 4-agent AI pipeline for **AML/KYC beneficial-ownership screening** of Australian trust structures, built for the compliance teams of financial institutions that must meet **AUSTRAC AML/CTF** obligations.

- **Code:** [`hyvn-arsya/sovereign-aml-engine`](https://github.com/hyvn-arsya/sovereign-aml-engine)
- **Stack:** Python · FastAPI · LangChain (LlamaParse, Gemini, Claude) · RapidFuzz · SQLAlchemy · AWS CDK · Docker
- **Tests:** 53 root tests (1 dev-only skipped) + 11 CDK unit tests, all green

---

## The one-line pitch

**"AI where it adds value, deterministic code where it can't be trusted to improvise"** — a compliance screening pipeline that treats a sanctioned-name match as a *regulated decision*, not a prompt response.

---

## What it does

An Australian financial institution needs to screen the beneficial owners of a trust structure before every transaction and periodically. The input is a trust deed — often a hundred-plus pages of dense legal text — naming a trustee, beneficiaries, and an appointor.

Sovereign AML takes that document and:

1. **Parses it** and extracts the current ownership structure (trustee, beneficiaries, appointor, risk indicators), correctly following *variation deeds* so removed beneficiaries drop out.
2. **Screens every party** against the DFAT Consolidated Sanctions list and a PEP watchlist.
3. **Produces an auditable compliance memo** summarising who was screened, what matched, and what a human reviewer must look at next.

---

## The core design decision (my strongest differentiator)

Most AI-agent portfolio projects use an LLM for **everything**. That's the wrong call for compliance — and the single most defensible decision in this project is *not* doing it.

**Why:**

- If an AUSTRAC examiner asks *"why was this entity flagged?"* the answer must be a **traceable, reproducible algorithm** — not "because Claude said so," which can differ between runs.
- Screening is a **high-volume, low-latency, near-zero-cost** operation: thousands of fuzzy matches in milliseconds via RapidFuzz. The same via LLM API calls would cost dollars and add minutes per screening.
- A deterministic screener **cannot hallucinate a sanctions match**; an LLM can, with catastrophic consequences in this domain.

So the pipeline is split deliberately:

| Agent | Task | Method | Why |
|-------|------|--------|-----|
| 1 | Data gathering / ABN validation | Boto3 + checksum | Pure I/O, no LLM needed |
| 2 | Document extraction | LlamaParse + Gemini | Reading comprehension genuinely requires an LLM |
| 3 | Sanctions & PEP **screening** | **Deterministic RapidFuzz** | A regulated decision — auditable, explainable, cheap |
| 4 | Report drafting | Claude | Narrative prose from a fixed, deterministic trail |

This reasoning, including the rejected "LLM for everything" alternative, is written up as a proper **Architecture Decision Record** ([`ADR-001-deterministic-vs-generative.md`](ADR-001-deterministic-vs-generative.md)) — the kind of artifact that signals you don't just ship code, you make and document engineering trade-offs.

---

## A concrete problem I found and fixed: the nickname gap

Fuzzy string matching has a real, quiet failure mode in sanctions screening: sanctioned *"Robert Smith"* recorded on a deed as *"Bob Smith"* scores only ~76% — **below the 85% flag threshold** — so a genuine match would be silently missed. Same for *William/Bill*, *Richard/Dick*, *Alexander/Alex*.

Because Agent 3 is deterministic, the fix is clean and testable: a curated given-name alias table that expands the diminutive and re-scores, with every alias-driven match explicitly labelled `"alias expansion"` in the audit trail. Two things I'm proud of here:

1. It **closes a real compliance gap**, not a cosmetic one.
2. It stayed **auditable** — the flag records *why* it fired, which is exactly what a compliance reviewer needs.

I wrote tests that confirm both the positive case (nicknames now caught) **and** the negative case (no false positives — e.g. "Bob Marley" never matches "Robert Smith").

---

## Engineering rigor

- **53 root tests** (pipeline unit + moto S3 + data-engineering/security regressions + API auth; one dev-only full-pipeline script is skipped because it needs a real PDF + live keys), all passing, plus 11 CDK tests that synth the real stack and assert on the resulting CloudFormation — no snapshot-mock churn. The strip of the pipeline everyone worries about is the storage layer, so two of the suites put it under real test:
  - `test_moto_s3.py` runs the **real boto3 S3 code paths** (`gather_asic_data` and the audit-trail persistence in `run_pipeline`) against an in-process S3 mock — no AWS credentials or bucket needed. The same `put_object(..., ServerSideEncryption="aws:kms")` calls the pipeline makes in production execute for real against moto: the raw-upload path, the three audit artifacts (`extraction_output.json` / `screening_result.json` / `compliance_memo.txt`), and the KMS-at-rest encryption flag are all asserted. The external registry hop and the LLM agents are mocked; the S3 layer itself is what's under test.
  - `test_priorities.py` runs the **real `run_pipeline`** against moto S3 **plus an in-memory SQLite database** (only the LLM agents mocked). It proves the deterministic `processing_key` skips a re-screening of the same document *under a fresh `run_id`* while a genuinely new document reprocesses; that `pipeline_runs` captures `chunk_count` / `entity_count` / `red_flag_count` / `duration_ms`; and that the entity model persists `entities`, `entity_aliases`, and `screening_matches` tagged `direct` vs `alias_expansion`.
- **Async job queue**: screening takes 20–40s, so a blocking HTTP request is a production smell. Added `POST /analyze/abn/async` (202 + job id) with `GET /jobs/{id}` polling; the worker is factored to run behind SQS/Fargate.
- **One-command demo**: `docker-compose up` brings up the FastAPI app + Postgres.
- **Production-hardened AWS CDK**: S3 raw + versioned audit buckets, VPC + flow logs, encrypted RDS with backup retention, ECS Fargate behind an ALB with health checks, env-aware dev/prod.
- **Honesty where it matters**: the sanctions list and the ~45-entry nickname table are *seed data* proving the mechanism — clearly labelled as such, not dressed up as production reference data. Docs stay in sync with the code (verified during development).

---

## Iteration: the `LLMProvider` seam (data sovereignty)

The project's name promises a bank can keep trust deeds on infrastructure it controls — but Agents 2 and 4 originally constructed a hard-coded cloud model inline, so *every* document's PII went to Google/Anthropic regardless. The name was aspirational.

Rather than promise this as a roadmap item, I built the minimal thing that makes it a **demonstrable claim**:

- A small **`LLMProvider` protocol** with two call shapes that map exactly onto the two generative agents — `extract_structured(prompt, schema)` (Agent 2) and `generate_text(prompt)` (Agent 4). The pipeline no longer names a vendor; it names a seam.
- **`CloudLLMProvider`** is the default and reproduces the prior Gemini/Claude behaviour bit-for-bit (a strict no-op — nothing about the default path changed).
- **`OllamaLLMProvider`** is a second, working implementation that talks to a local model via plain `requests` against Ollama's OpenAI-compatible API — no vendor SDK. A local 7B model is *worse* at legal-document extraction than Gemini 3.1 Pro, and that's the accepted, documented cost of self-hosting. The point isn't parity — it's *proof the architecture doesn't lock you into a foreign cloud*.
- Provider selection is an **admin-configured deployment decision** (`LLM_PROVIDER=cloud|ollama`), never a per-request user choice — consistent with ADR-001's argument that model choice in a compliance pipeline is governed.

### The compliance bug the refactor surfaced

Self-hosting introduced a trap I caught by checking Ollama's real API reference rather than trusting mocks: over-length input is **silently truncated** with no warning, and `num_ctx` can't be set through the OpenAI endpoint — it must be configured server-side. In a compliance pipeline that's a quiet data-loss gap: a chunk with beneficiaries A/B/C can be truncated to just C *while still returning a well-formed extraction*. So I added a **startup guard**: at construction the provider calls `/api/show` and compares the model's active context against the required minimum, logging a loud error — or refusing to start (`OLLAMA_REQUIRE_CONTEXT=true`) — when it's too small. And a reviewer caught that `/api/show` is **POST**, not GET (my mocked tests only patched whatever method the code called, so they couldn't catch the hard-coded wrong verb) — which, against a real server, would have silently no-oped the whole guard. Both are now fixed and verified with mocks patching the correct method.

---

## Iteration: the data-engineering layer (idempotency, runs, entities)

A screening pipeline that works end-to-end in a demo is not yet a defensible data product. I tightened the layer underneath it along four axes that interviewers and reviewers tend to push on hardest:

- **Content-addressed idempotency (replacing run_id-based).** The old dedup keyed on a caller-supplied `run_id` — trivially defeated by retrying with a fresh UUID. The processing identity is now a deterministic `processing_key = sha256(document_hash | ABN | pipeline_version | extraction_model | screening_algorithm_version)`. Same document + same ABN + same tool versions ⇒ same key ⇒ replay, **whatever the caller's run_id**. New document, upgraded model, or bumped screening algorithm ⇒ genuinely new key ⇒ legitimate re-process. I was careful not to overclaim: this is *idempotent processing*, not exactly-once — a worker can still crash after an external side effect and before recording completion, and the way you catch that is the audit trail, not a queue fairy tale (see below).
- **`pipeline_runs` observability.** One row per run with `started_at`, `completed_at`, `status`, `chunk_count`, `entity_count`, `red_flag_count`, `duration_ms`. That turns a demo into something you can query: `SELECT AVG(duration_ms), AVG(chunk_count), AVG(entity_count), SUM(red_flag_count) FROM pipeline_runs WHERE status = 'completed'`. Skips and failures are represented distinctly so the aggregates measure real work.
- **Entity resolution promoted into the schema.** The nickname/alias expansion that used to live only inside Agent 3's in-memory matching is now persisted: `entities` (canonical screened party), `entity_aliases` (the alias form that closed a match), and `screening_matches` (with `match_method` = `direct` | `alias_expansion`). Audit trails don't help if they can't be re-examined structurally.
- **Explicit routing table for the envelope (Current vs Production).** The README now contrasts the in-process background worker (current, single-box truthful) with the SQS → ECS/Fargate worker (production target) and states plainly that only the *delivery* semantics change, not the processing logic — and why that matters (a durable queue without content-based dedup would still duplicate results).

---

## Iteration: the security review (auth, fail-closed sources, blocked outcomes)

A reviewer triaged the codebase and CDK into 7 findings, covering "the app has no auth", "demo DFAT/PEP seeds ship silently", "incomplete extraction reports success", "concurrent idempotency races", and IaC gaps (no Fargate→RDS network rule, no LLM-credential secret, audit bucket lacking Object Lock). All 7 are implemented with regression tests *and* CDK assertions rather than prose promises:

- **Tenant-scoped API keys (the "no auth" review).** Every data endpoint now requires `X-Api-Key`; only `/health` stays public for the ALB probe. Keys map to a tenant, are stored as **salted SHA-256 hashes** (never plaintext), seed via `SEED_API_KEYS="tenant:key,..."`, and enforce borders on both axes — the tenant prefix owns uploaded S3 keys (cross-tenant S3 keys → 403) and job polling is tenant-scoped (cross-tenant job IDs → 404, not data leaks). 12 dedicated API tests cover 401/403/404 paths and blocked-status propagation.
- **Fail-closed screening sources.** `SCREENING_MODE=production` refuses to screen unless `DFAT_SOURCE_URL` and `PEP_API_KEY` are configured — `load_dfat_sanctions`/`load_pep_list` raise instead of silently screening against demo seeds. Demo mode stays for development but is loud. Tests prove production refuses the mocks and demo defaults to them.
- **Blocked outcome, not a false success.** The old code promised a "successful" screening even when a damaged document skipped chunks or PEP never loaded. Extraction now records per-chunk failures, and any incomplete screening resolves to a deterministic, LLM-independent outcome — job status `blocked`, memo `OUTCOME: BLOCKED — MANUAL REVIEW REQUIRED` — passed through the API as `status=blocked` on both sync and async paths. The screening decision is never laundered through the memo writer.
- **Concurrency-safe idempotency.** The deterministic `processing_key` was previously enforced only by a `SELECT ... THEN SELECT` — two concurrent submissions could both pass the check and double-process. The column is now UNIQUE and the claim is a plain INSERT whose `IntegrityError` resolves to "this reference is already being/has been processed", so N concurrent duplicates converge on one run.
- **IaC hardening (CDK assertions prove it).** An explicit security-group rule connects Fargate → RDS (previously the ALB was defined but the database was unreachable); LLM provider keys move to a Secrets Manager secret injected as ECS task secrets (placeholder value for the operator, never baked into the image); the audit bucket gets **Object Lock with a 7-year compliance-mode retention** plus S3-managed encryption — audit objects are immutable for their full AUSTRAC Part 11 retention window, and no policy (operator or API) can shorten it.

---

## Iteration: follow-up security review (tenant data isolation & production deploy)

The first review's fixes were committed, then a second reviewer pass scored the *deployed* system, not just the demo. Six findings — two Critical, three High, one Low — all now implemented with tests:

- **Tenant isolation stops at the API node, not the pipeline (Critical).** API auth scoped requests, but the *idempotency key and audit data* didn't know who was asking: two tenants submitting the byte-same deed would collide on the same `processing_key`, so tenant B could be "skipped" off tenant A's run and inherit its reference. Processing keys now include the tenant (`sha256(... | tenant)`), and the persisted audit trail carries `trusts.tenant_id` — byte-identical deeds from different tenants can never collide, and a tenant's audit history is its own. Regression tests prove key divergence across tenants and that `run_pipeline(..., tenant_id=..., tenant_name=...)` threads identity end to end.
- **Production CDK had placeholder/"replace" secrets and no migration step (Critical).** The deployed task shipped with a generated secret the operator was meant to edit, and the DB deployed *empty* because the container runs `uvicorn` directly with no migrate step. Production now **refuses to synthesize** without operator-provided Secrets Manager ARNs (`-c llm_credentials_arn` + `-c app_secrets_arn` — or env equivalents), app config (salt, seed keys, DFAT URL, PEP key) is injected from an operator secret, `SCREENING_MODE` is pinned per-env, and migrations run as a **separate Fargate run-task** (`alembic upgrade head`) with its own security group, log group, and run instructions — never at app startup. CDK tests assert the stack throws without ARNs, that the prod container env is `SCREENING_MODE=production`, and that the only command override in the whole stack is the alembic one-off.
- **Failed runs permanently swallowed their idempotency claim (High).** A transient worker failure left `status='failed'` holding the UNIQUE processing key forever — the document could never be retried. `_claim_processing_key` now treats a *terminal failed* claim as releasable: the old row is preserved as audit history with its claim cleared, and a fresh attempt can re-claim and re-process. Active/completed/blocked claims still genuinely block. Tested with a three-phase claim→fail→re-claim sequence.
- **DFAT outage was reported as failure, not incomplete screening (High).** An unavailable PEP source was already fail-closed into `blocked`; an unavailable DFAT list escaped into a run failure. Both are now symmetric: `load_dfat_sanctions` failures resolve to the same deterministic `BLOCKED — MANUAL REVIEW REQUIRED` outcome with an audit trail flag (`screening_incomplete`, `dfat_unavailable_reason`) instead of an unhandled error.
- **Production API-key salt (Low).** Outside development the API refuses to start with a missing or unchanged dev-default `API_KEY_SALT` — no "change-me" salt can silently reach production.
- **A test-isolation bug this round surfaced (worth flagging in interviews).** When I ran the suites in a different order, 3 API tests broke with `no column named tenant_id`. Root cause: `DATABASE_URL` is read once at `database` module import, and `test_api_auth` set it *after* another module (collection order-dependent) had already imported `database` → it bound to a stale dev file. Fixed properly with a repo-root `conftest.py` that pins the DB env before any test module is imported, so the app's DB binding is order-independent. The lesson: env-at-import apps need the env pinned at *session* scope, not in one test file.

---

## What I learned / would do next

- **Deterministic-vs-generative is a right answer worth defending** — interviewers responded well to an explicit, documented trade-off rather than a default "LLM everything".
- **Data sovereignty for Agents 2 & 4 — now built, not a promise.** "Sovereign AML" no longer has to send trust-deed PII to a foreign cloud by construction: the `LLMProvider` seam (see the iteration below) lets a bank run extraction and reporting on infrastructure it controls, while staying on Gemini/Claude by default. The self-hosted option is a working seam, not a roadmap claim.
- **Production data source**: `SCREENING_MODE=production` already refuses to screen without `DFAT_SOURCE_URL` and `PEP_API_KEY`, so wiring the real DFAT consolidated list and a commercial PEP provider is now a config change plus data-contract work — and the alias table should move to a reference-data vendor (transliteration variants of non-English names are a bigger real-world risk than Anglo nicknames).
- **Truly async infra**: move the worker behind an SQS queue consumed by a separate Fargate task (the CDK stack is structured to accept it).
- **Observability — now built, not a roadmap item.** Every run lands in `pipeline_runs` (`started_at`, `completed_at`, `status`, `chunk_count`, `entity_count`, `red_flag_count`, `duration_ms`), feeding the kind of spot-check query a reviewer actually writes: `SELECT AVG(duration_ms), AVG(entity_count), AVG(chunk_count), SUM(red_flag_count) FROM pipeline_runs WHERE status = 'completed'`.
- **Idempotency claims stay honest.** The processing key buys idempotent replays, not exactly-once — and *that* claim (a worker can still crash after pushing a memo downstream and before recording completion) is documented in the README rather than papered over. What *is* now DB-enforced: the claim itself. `processing_key` is UNIQUE and the claim is a `CREATE` whose `IntegrityError` resolves to a skip, so concurrent duplicates can't double-process in the gap between check and insert. A *failed* claim is releasable for retry; active/completed/blocked claims still block.
- **Deployed ≠ demo.** The strongest second-pass theme was that "it works in a demo" doesn't survive deployment — placeholder credentials, an empty auto-migrating database, and unsalted dev defaults all shipped as quiet footguns. The CDK now fails closed where an operator action is genuinely required, and the migration is an explicit one-off task rather than a best-effort side effect.

---

## Why it's portfolio-worthy

It demonstrates the full arc of a real system, not a toy:

- a genuinely hard domain (compliance screening) with real constraints,
- a **documented engineering decision** that shows judgment,
- a **real bug found and fixed** with tests that prove it,
- a production-shaped deployment (containerised, async, cloud infra),
- and honest scoping that a technical interviewer can probe without finding smoke and mirrors.
