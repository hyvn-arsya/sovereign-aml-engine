# ADR-001: Deterministic vs Generative Agent Selection

## Status

Accepted — 2026-08-31

## Context

Sovereign AML is a 4-agent compliance pipeline for Australian financial institutions. Each agent's task has different requirements around **auditability**, **explainability**, **cost**, **latency**, and **regulatory defensibility** under AUSTRAC's AML/CTF Act (Part 11 — record-keeping obligations).

The question: which agents should use large language models (generative), and which should use purely deterministic code?

## Decision

**Agent 3 (Sanctions & PEP Screening) is implemented as deterministic RapidFuzz-based code with zero LLM involvement.** Agents 2 (Document Extraction) and 4 (Compliance Report Drafting) use LLMs.

### Agent-by-agent rationale

| Agent | Method | Rationale |
|-------|--------|-----------|
| **1 — Data Gathering** | Boto3 / ABN validation | Pure I/O and checksum validation. No LLM needed. |
| **2 — Document Extraction** | LlamaParse + Gemini 3.1 Pro | Trust deeds are hundreds of pages of unstructured legal text. Extracting entities, trustee companies, and variation chronology requires genuine reading comprehension that no rule-based system can replicate. LLMs are the right tool here because the task is *understanding*, not *deciding*. |
| **3 — Sanctions & PEP Screening** | RapidFuzz + DFAT sanctions list | This is a **regulated decision** — screening an entity against a government sanctions list is deterministic by design. The answer is either "match found above 85% threshold" or "no match." Using an LLM here would introduce non-determinism into a step that AUSTRAC requires you to explain in audit reviews. If an examiner asks "why was this entity flagged/not flagged," the answer must be a traceable, auditable algorithm — not a prompt response. |
| **4 — Report Drafting** | Claude Sonnet | The compliance memo is a human-facing narrative document for an internal review team. It synthesises the structured audit trail (generated deterministically by Agent 3) into a readable report. This is a drafting/summarisation task where LLMs excel and where non-determinism in prose quality is acceptable — the underlying screening facts are fixed. |

## Consequences

### What we gain

- **Auditability**: Agent 3's output is fully explainable. Every fuzzy-match score, every threshold comparison, and every entity name normalisation is logged and reproducible. An AUSTRAC reviewer can trace the exact algorithmic path that led to a red flag.
- **Cost control**: Screening hundreds of entities against thousands of sanctions records is a high-volume, low-latency task. RapidFuzz processes thousands of fuzzy matches in milliseconds at zero marginal cost. The same operation via LLM API calls would cost dollars per screening and add minutes of latency.
- **Regulatory defensibility**: AUSTRAC AML/CTF Rule 57.1 requires that reporting entities "take reasonable steps" to screen customers. A deterministic, testable algorithm with documented thresholds is a stronger demonstration of "reasonable steps" than a prompt-response from a model that may vary between calls.
- **Reliability**: Agent 3 never hallucinates a sanctions match. It either finds one above the threshold or it doesn't. This eliminates the class of LLM errors — false positives from pattern-matching, false negatives from misunderstanding entity name formats — that would be catastrophic in a compliance context.

> **Note on scope:** the nickname/diminutive alias table used to widen matching is a deliberately small (~45-entry) English-language **seed list**, not a claim of coverage. It won't catch transliteration variants of non-English names — a bigger real-world risk given DFAT's actual sanctions composition — and production would back it with a reference-data vendor.

### What we accept

- **Agent 2 and 4 hallucination risk**: LLMs can produce incorrect extractions (Agent 2) or fabricate details in reports (Agent 4). We mitigate this by:
  - Agent 2: Structured output (Pydantic schema), chunk-and-merge with reconciliation, and deterministic Agent 3 as a downstream validation layer.
  - Agent 4: The compliance memo is a *draft* for human review, not a final determination. The underlying facts in the audit trail are deterministic.
- **LLM cost and latency**: Agents 2 and 4 make API calls. We accept this because they process one trust deed per screening run (not thousands of entities per run like Agent 3), and the latency is bounded by the document volume.
- **Model dependency**: Both Gemini and Anthropic are external services with their own SLAs. The pipeline is designed to fail gracefully (retry, timeout, user-visible error) rather than silently degrade.

## Alternatives considered

### "Use an LLM for Agent 3 too"

This was considered and rejected. While an LLM could theoretically perform fuzzy matching, it would:
1. Be non-deterministic — the same input could produce different outputs across calls.
2. Be untestable — there is no clean way to write `assert match_score == 0.87` against an LLM response.
3. Violate the spirit of AUSTRAC's record-keeping obligations — you cannot explain "why" an LLM flagged an entity.
4. Cost 100-1000x more per screening at scale.

### "Use deterministic code for everything"

This would eliminate the ability to parse trust deeds (Agent 2) — there is no rule-based system that can reliably extract beneficiary schedules from arbitrary legal PDFs with variation chronology. And it would produce poor-quality compliance memos (Agent 4) — turning a structured audit trail into readable prose is a core LLM strength.

## References

- [AUSTRAC AML/CTF Rules — Chapter 11 (Record-keeping)](https://www.legislation.gov.au/F2014L00558/latest/text)
- [ASAP 3: Agile Screening of Australian PEPs](https://www.austrac.gov.au/businesses-and-organisations/compliance-and-reporting/aml-ctf-program/austrac-strengthened-aml-ctf-regime/asap3)
- LangChain RapidFuzz documentation: deterministic tool-use vs. generative tool-use patterns
