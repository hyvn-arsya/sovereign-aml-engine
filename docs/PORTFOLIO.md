# Sovereign AML Engine — Portfolio Writeup

A 4-agent AI pipeline for **AML/KYC beneficial-ownership screening** of Australian trust structures, built for the compliance teams of financial institutions that must meet **AUSTRAC AML/CTF** obligations.

- **Code:** [`hyvn-arsya/sovereign-aml-engine`](https://github.com/hyvn-arsya/sovereign-aml-engine)
- **Stack:** Python · FastAPI · LangChain (LlamaParse, Gemini, Claude) · RapidFuzz · SQLAlchemy · AWS CDK · Docker
- **Tests:** 8 pipeline + 8 CDK unit tests, all green

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

- **16 unit tests** (8 pipeline + 8 CDK), all passing. The CDK tests synth the real stack and assert on the resulting CloudFormation — no snapshot-mock churn.
- **Async job queue**: screening takes 20–40s, so a blocking HTTP request is a production smell. Added `POST /analyze/abn/async` (202 + job id) with `GET /jobs/{id}` polling; the worker is factored to run behind SQS/Fargate.
- **One-command demo**: `docker-compose up` brings up the FastAPI app + Postgres.
- **Production-hardened AWS CDK**: S3 raw + versioned audit buckets, VPC + flow logs, encrypted RDS with backup retention, ECS Fargate behind an ALB with health checks, env-aware dev/prod.
- **Honesty where it matters**: the sanctions list and the ~45-entry nickname table are *seed data* proving the mechanism — clearly labelled as such, not dressed up as production reference data. Docs stay in sync with the code (verified during development).

---

## What I learned / would do next

- **Deterministic-vs-generative is a right answer worth defending** — interviewers responded well to an explicit, documented trade-off rather than a default "LLM everything".
- **True data sovereignty for Agents 2 & 4**: right now "Sovereign AML" sends trust-deed PII to Google and Anthropic's clouds — the name is aspirational, not yet true. The next real iteration is an `LLMProvider` abstraction that Agents 2 (extraction) and 4 (reporting) call through, with the current Gemini/Claude calls as the default implementation and a self-hosted option (vLLM or Ollama serving an open-weight model) as a second. Provider selection stays an **admin-configured deployment decision**, never a per-request user choice — consistent with ADR-001's argument that model choice in a compliance pipeline is a governed decision, not a preference. This is what actually lets a bank keep confidential trust deeds on infrastructure they control, which is the whole point of the project's name.
- **Production data source**: wire the real DFAT consolidated list and a commercial PEP provider, and back the alias table with a reference-data vendor (transliteration variants of non-English names are a bigger real-world risk than Anglo nicknames).
- **Truly async infra**: move the worker behind an SQS queue consumed by a separate Fargate task (the CDK stack is structured to accept it).
- **Observability**: add structured audit-logging to S3 for the 7-year AUSTRAC retention requirement.

---

## Why it's portfolio-worthy

It demonstrates the full arc of a real system, not a toy:

- a genuinely hard domain (compliance screening) with real constraints,
- a **documented engineering decision** that shows judgment,
- a **real bug found and fixed** with tests that prove it,
- a production-shaped deployment (containerised, async, cloud infra),
- and honest scoping that a technical interviewer can probe without finding smoke and mirrors.
