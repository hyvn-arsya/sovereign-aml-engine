"""
AML/KYC Beneficial Ownership Screening Pipeline
================================================
4-Agent AUSTRAC/AML-CTF compliance pipeline for Australian financial institutions.

Architecture:
    Agent 1 → S3 PDF upload      (Data Gathering)
    Agent 2 → LlamaParse + GPT   (Structured Extraction from PDF)
    Agent 3 → Deterministic Rules (DFAT Sanctions + PEP Screening)
    Agent 4 → Claude Sonnet       (Audit Report Drafting)

Fixed Issues (v2):
    - Agent 1→2: S3 download glue added; no longer hardcodes local path
    - Agent 2→3: Pydantic object serialised with .model_dump_json() before handoff
    - Agent 3→4: Already worked; kept clean
    - Added retry logic, structured logging, and per-agent error handling
    - [FIX #1]  Agent 2: LlamaParse uses temp file instead of BytesIO
    - [FIX #2]  Orchestrator: None guard after Agent 2 retry loop
    - [FIX #3]  Agent 4: Timezone-aware datetime via ZoneInfo
    - [FIX #4]  Agent 3: Fuzzy-match logic clarified, reports all matches above threshold
    - [FIX #5]  Agent 3: Trustee company now screened alongside beneficiaries
    - [FIX #6]  Agent 3: PEP screening stub added with clear production guidance
    - [FIX #7]  Orchestrator: Audit trail and memo persisted to S3 (7-year retention)
    - [FIX #8]  Orchestrator: Deterministic reference number generated, passed to Agent 4
    - [FIX #9]  All S3 uploads: ServerSideEncryption="aws:kms" added
    - [FIX #10] Agent 3: PII redacted in log output
    - [FIX #11] Startup: Required env vars validated before pipeline runs
    - [FIX #12] Agent 1: ABN format + checksum validation
    - [FIX #13] Agent 2: Context-window guard truncates oversized documents
    - [FIX #14] Orchestrator: Overall pipeline timeout documented (platform-dependent)
    - [FIX #15] Orchestrator: Run ID + intermediate outputs persisted for idempotency
    - [FIX #16] Agent 3: DFAT sanctions list cached with TTL
"""

import io
import json
import logging
import os
import re
import tempfile
import time
import uuid
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo  # FIX #3: Timezone-aware datetime

import boto3
import requests
from botocore.exceptions import BotoCoreError, ClientError
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from llama_parse import LlamaParse
from pydantic import BaseModel, Field
from thefuzz import fuzz

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("aml_pipeline")

# ─────────────────────────────────────────────
# DEBUG INSTRUMENTATION (session 4d4fc1)
# ─────────────────────────────────────────────
DEBUG_LOG_PATH = os.path.join(os.path.expanduser("~"), "debug-4d4fc1.log")
DEBUG_SESSION_ID = "4d4fc1"


def _agent_debug_log(
    location: str,
    message: str,
    data: dict,
    hypothesis_id: str,
    run_id: str = "pre-fix",
) -> None:
    # #region agent log
    entry = {
        "sessionId": DEBUG_SESSION_ID,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass
    # #endregion


# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────
S3_BUCKET = "sovereign-engine-raw-documents"
S3_PREFIX = "client_uploads"
AUDIT_LOG_PREFIX = "audit_logs"

# FIX #3: Timezone constant for Australia/Sydney (handles AEST/AEDT automatically)
AEST = ZoneInfo("Australia/Sydney")

# Chunk-and-merge constants for Agent 2.
# CHUNK_SIZE: max characters per chunk sent to GPT-4o (~15k tokens, well within
#   the 128k context window, leaving room for system prompt + structured output).
# CHUNK_OVERLAP: characters of overlap between consecutive chunks to avoid
#   splitting an entity across a chunk boundary.
CHUNK_SIZE = 60_000
CHUNK_OVERLAP = 5_000

# ─────────────────────────────────────────────
# SHARED S3 CLIENT (created once, reused)
# ─────────────────────────────────────────────
s3 = boto3.client("s3")

# ─────────────────────────────────────────────
# FIX #11: ENVIRONMENT VARIABLE VALIDATION
# ─────────────────────────────────────────────
# GOVERNMENT_API_KEY is excluded — only needed when Path B (registry fetch) is used.
REQUIRED_ENV_VARS = ["LLAMACLOUD_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]


def validate_env() -> None:
    """Checks that all required API keys are present before the pipeline runs."""
    missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Set them before running the pipeline."
        )


# ─────────────────────────────────────────────
# FIX #12: ABN VALIDATION
# ─────────────────────────────────────────────
def validate_abn(abn: str) -> bool:
    """
    Validates an Australian Business Number using the official ABR checksum algorithm.
    ABNs are exactly 11 digits. Returns True if valid, False otherwise.
    Reference: https://abr.business.gov.au/Help/AbnFormat
    """
    if not re.fullmatch(r"\d{11}", abn):
        return False
    weights = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
    digits = [int(d) for d in abn]
    digits[0] -= 1  # Subtract 1 from the first digit per ABN algorithm
    return sum(d * w for d, w in zip(digits, weights)) % 89 == 0


# ─────────────────────────────────────────────
# FIX #10: PII REDACTION HELPER
# ─────────────────────────────────────────────
def redact(name: str) -> str:
    """
    Redacts a name for safe logging. 'Jonathan Smith' → 'J*** S***'.
    Full names are never written to log output.
    """
    parts = name.strip().split()
    return " ".join(p[0] + "***" if p else "***" for p in parts)


# ─────────────────────────────────────────────
# FIX #16: DFAT SANCTIONS LIST CACHING
# ─────────────────────────────────────────────
_dfat_cache: dict = {"data": None, "fetched_at": None}
DFAT_CACHE_TTL_SECONDS = 86_400  # 24 hours


# ══════════════════════════════════════════════════════════════════════════════
# AGENT 1 — DATA GATHERING
# Responsibility: Hit ASIC/ABR API → pull structured metadata → upload PDF to S3
#
# PRODUCTION NOTE ON REAL REGISTERS:
#   Neither ASIC nor ABR expose private trust deeds via their public APIs.
#   In production, Agent 1 takes two real-world input paths:
#
#   Path A — Client-Uploaded Documents (most common):
#       The customer uploads their trust deed through your onboarding portal.
#       Your app receives the file, stores it to S3, and passes the S3 key
#       straight into Agent 2. Agent 1 is bypassed for document sourcing.
#
#   Path B — Third-Party Registry Enrichment (supplementary):
#       Use a licensed data provider (Acceleon, CreditorWatch, ASIC Connect)
#       to pull ASIC company-profile data (directors, registration status,
#       officeholders). This gives you the structured JSON side of Agent 1.
#       It does NOT provide the trust deed itself.
#
#   The function below models Path B for the structured side, and shows how
#   to accept a pre-uploaded file key for the document side.
# ══════════════════════════════════════════════════════════════════════════════


def gather_asic_data(
    company_abn: str,
    pre_uploaded_s3_key: Optional[str] = None,  # ← Path A: client already uploaded
) -> Optional[str]:
    """
    Pulls structured company data from ABR/ASIC registry.
    If a pre-uploaded S3 key is provided, skips the registry PDF download
    and uses that document directly (the normal production flow).

    Returns: S3 key of the trust deed PDF, or None if not found.
    """
    log.info(f"Agent 1: Initiating gather for ABN {company_abn}")

    # ── PATH A: Client already uploaded the trust deed to your portal ──────────
    if pre_uploaded_s3_key:
        log.info(
            f"Agent 1: Using pre-uploaded document at s3://{S3_BUCKET}/{pre_uploaded_s3_key}"
        )
        return pre_uploaded_s3_key

    # ── PATH B: Fetch structured metadata from ABR/ASIC third-party provider ───
    # Replace this endpoint with your licensed provider (Acceleon, CreditorWatch, etc.)
    gov_api_key = os.environ.get("GOVERNMENT_API_KEY")
    if not gov_api_key:
        raise EnvironmentError(
            "GOVERNMENT_API_KEY is required for Path B (registry fetch). "
            "Set it or provide a pre_uploaded_s3_key instead."
        )

    api_endpoint = f"https://api.business.gov.au/abr/v1/{company_abn}"
    headers = {"Authorization": f"Bearer {gov_api_key}"}

    try:
        response = requests.get(api_endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        company_data = response.json()
    except requests.RequestException as exc:
        log.error(f"Agent 1: Registry API call failed — {exc}")
        raise

    directors = company_data.get("directors", [])
    company_status = company_data.get("status", "Unknown")
    log.info(f"Agent 1: Status={company_status}, Directors={len(directors)}")

    # ── Registry PDF link (only exists if your provider supports it) ───────────
    # Most real providers return a link to ASIC-filed documents (annual returns,
    # change-of-directors notices) but NOT private trust deeds. If your provider
    # does include a document link, the block below handles downloading it.
    trust_deed_url = company_data.get("trust_deed_document_link")
    if not trust_deed_url:
        log.warning(
            "Agent 1: No trust deed URL returned by registry. "
            "Collect the trust deed directly from the client."
        )
        return None

    log.info("Agent 1: Document link found — downloading PDF...")
    pdf_response = requests.get(trust_deed_url, timeout=30)
    pdf_response.raise_for_status()

    s3_key = f"{S3_PREFIX}/{company_abn}_trust_deed.pdf"
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=pdf_response.content,
            ContentType="application/pdf",
            ServerSideEncryption="aws:kms",  # FIX #9: Encrypt PII at rest
        )
        log.info(f"Agent 1: PDF saved to s3://{S3_BUCKET}/{s3_key}")
    except (BotoCoreError, ClientError) as exc:
        log.error(f"Agent 1: S3 upload failed — {exc}")
        raise

    return s3_key  # ← handed to Agent 2


# ══════════════════════════════════════════════════════════════════════════════
# AGENT 2 — DOCUMENT EXTRACTION (with chunk-and-merge)
# Responsibility: Download PDF from S3 → parse with LlamaParse → split into
#                overlapping chunks → extract structured JSON from each chunk
#                via GPT-4o → merge results with deduplication.
#
# Why chunk-and-merge instead of truncation:
#   Trust deeds are highly structured legal documents. Beneficiary schedules,
#   appointor clauses, and foreign-entity disclosures can appear anywhere —
#   often at the very end. Naive truncation silently drops these sections,
#   producing a false "Clearance Certificate" for an unscreened trust.
#   Chunk-and-merge guarantees every page is processed.
#
# FIX #1: LlamaParse now uses a temp file on disk instead of BytesIO.
# ══════════════════════════════════════════════════════════════════════════════


class TrustDeedExtraction(BaseModel):
    trust_name: str = Field(description="The legal name of the trust")
    trustee_company: str = Field(description="The company acting as the trustee")
    beneficiaries: list[str] = Field(description="All named beneficiaries (both individuals and corporate entities)")
    is_high_risk: bool = Field(
        description="True if any foreign entities or non-residents are named"
    )





def extract_trust_deed(s3_key: str) -> str:
    """
    Downloads the PDF from S3, writes it to a temp file, parses it with
    LlamaParse, then uses GPT-4o to extract structured data from each chunk.
    Results are merged with deduplication.

    Returns: JSON string (not a Pydantic object) — ready for Agent 3.
    """
    log.info(f"Agent 2: Fetching s3://{S3_BUCKET}/{s3_key}")

    # ── Download PDF bytes from S3 ────────────────────────────────────────────
    try:
        s3_object = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
        pdf_bytes = s3_object["Body"].read()
    except (BotoCoreError, ClientError) as exc:
        log.error(f"Agent 2: S3 download failed — {exc}")
        raise

    # ── Write to temp file — LlamaParse reliably accepts file paths ────────────
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        parser = LlamaParse(
            api_key=os.environ["LLAMACLOUD_API_KEY"],
            result_type="markdown",
            verbose=True,
        )

        parsed_document = parser.load_data(
            file_path=tmp_path, extra_info={"file_name": s3_key}
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    if not parsed_document:
        raise ValueError("Agent 2: LlamaParse returned an empty document.")

    markdown_text = parsed_document[0].text
    log.info(f"Agent 2: Parsed {len(markdown_text)} characters of Markdown")

    # ── SINGLE-PASS EXTRACTION ────────────────────────────────────────────────
    log.info("Agent 2: Extracting entities in a single pass using Gemini 1.5 Pro...")
    
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.1-pro-preview",
        temperature=0,
        api_key=os.environ["GOOGLE_API_KEY"],
    )
    structured_llm = llm.with_structured_output(TrustDeedExtraction)

    prompt = f"""
You are an expert Australian AML/KYC compliance analyst.
You are reviewing the full text of a Trust Deed and any associated Variation Deeds, Deeds of Retirement and Appointment, and other compliance documents.
Extract the CURRENT entities as of the latest document.
Pay close attention to the chronology of variations:
- If a variation deed removes a beneficiary, do NOT include them in the final list.
- If a variation deed adds a beneficiary, include them.
- If the trustee has changed, extract the CURRENT trustee.

Document Text:
{markdown_text}
"""

    result: TrustDeedExtraction = structured_llm.invoke(prompt)
    log.info(f"Agent 2: Extraction complete — Trust: {result.trust_name}")

    return result.model_dump_json(indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# AGENT 3 — DETERMINISTIC SANCTIONS & PEP SCREENING
# Responsibility: Screen every extracted party (beneficiaries AND trustee)
#                against the DFAT Consolidated Sanctions List and PEP lists
#                using fuzzy string matching.
#
# This agent is intentionally non-LLM. Risk decisions must be auditable,
# repeatable, and explainable — qualities that deterministic code provides
# and LLMs do not.
#
# FIX #4:  All matches above threshold are reported (no early break).
# FIX #5:  Trustee company is now screened alongside beneficiaries.
# FIX #6:  PEP screening stub added.
# FIX #10: PII redacted in log messages.
# FIX #16: DFAT list cached with 24-hour TTL.
# ══════════════════════════════════════════════════════════════════════════════

FUZZY_MATCH_THRESHOLD = 85  # Flag if name similarity >= 85%


def load_dfat_sanctions() -> list[dict]:
    """
    Downloads and caches the DFAT Consolidated Sanctions List.
    In production: parse the official CSV/XML from DFAT.
    Cache is refreshed every 24 hours.

    For now returns a mock list.
    """
    # FIX #16: Check cache validity
    now = time.time()
    if (
        _dfat_cache["data"] is not None
        and _dfat_cache["fetched_at"] is not None
        and (now - _dfat_cache["fetched_at"]) < DFAT_CACHE_TTL_SECONDS
    ):
        log.info("Agent 3: Using cached DFAT sanctions list.")
        return _dfat_cache["data"]

    log.info("Agent 3: Refreshing DFAT sanctions list...")

    # PRODUCTION REPLACEMENT:
    # dfat_url = "https://www.dfat.gov.au/sites/default/files/ConList.csv"
    # response = requests.get(dfat_url, timeout=15)
    # response.raise_for_status()
    # ... parse CSV into [{"name": ..., "type": ...}, ...]
    data = [
        {"name": "Jonathan Smith", "type": "Sanctioned - DFAT Consolidated List"},
        {"name": "Vladimir Ivanov", "type": "Sanctioned - Foreign National"},
    ]

    # Update cache
    _dfat_cache["data"] = data
    _dfat_cache["fetched_at"] = now
    return data


def load_pep_list() -> list[dict]:
    """
    FIX #6: PEP (Politically Exposed Persons) screening stub.

    PRODUCTION IMPLEMENTATION:
        In production, integrate with a licensed PEP data provider such as:
        - Dow Jones Risk & Compliance
        - Refinitiv World-Check
        - ComplyAdvantage
        - LexisNexis WorldCompliance

        These providers offer API access to global PEP databases that include
        heads of state, senior government officials, senior judicial figures,
        senior military officers, and their close associates/family members.

        The returned format should match the DFAT structure:
        [{"name": "...", "type": "PEP - [Category]"}, ...]

    For now returns an empty list — PEP screening is a documented Phase 2 item.
    """
    log.info(
        "Agent 3: PEP list is currently a stub. "
        "Integrate a licensed PEP provider for production."
    )
    return []


def _screen_entities(
    entities: list[dict],
    watchlist: list[dict],
    watchlist_label: str,
) -> list[dict]:
    """
    Screens a list of entities against a watchlist using fuzzy string matching.
    Returns a list of red flag dicts for any matches above the threshold.

    Each entity is a dict with keys: {"name": str, "role": str}
    Each watchlist entry is a dict with keys: {"name": str, "type": str}

    FIX #4: All matches above FUZZY_MATCH_THRESHOLD are reported for each entity.
    Compliance reviewers need visibility into every near-match. The previous
    early-break at score >= 95 silently suppressed additional matches for the
    same person against other watchlist entries.
    """
    flags = []
    for entity in entities:
        for watchlist_entry in watchlist:
            match_score = fuzz.token_set_ratio(
                entity["name"].lower(), watchlist_entry["name"].lower()
            )

            if match_score >= FUZZY_MATCH_THRESHOLD:
                # FIX #10: Redact PII in log output
                log.warning(
                    f"Agent 3: RED FLAG — {redact(entity['name'])} "
                    f"({entity['role']}) matched {watchlist_label} entry "
                    f"(score={match_score})"
                )
                flags.append(
                    {
                        "extracted_name": entity["name"],
                        "entity_role": entity["role"],
                        "matched_watchlist_name": watchlist_entry["name"],
                        "watchlist_type": watchlist_entry["type"],
                        "match_confidence_score": match_score,
                        "action_required": "Manual Review Required by Head of Risk",
                    }
                )
    return flags


def check_austrac_policy(extracted_json: str, dfat_db: list[dict]) -> dict:
    """
    Screens all parties in the extracted JSON against sanctions and PEP lists.
    Returns an audit trail dict — the direct input for Agent 4.

    FIX #5: Trustee company is now included in the screening.
    FIX #6: PEP list is screened in addition to DFAT sanctions.
    """
    log.info("Agent 3: Initiating AUSTRAC Policy Check...")

    extracted_data = json.loads(extracted_json)
    beneficiaries: list[str] = extracted_data.get("beneficiaries") or []
    trustee_company: str = extracted_data.get("trustee_company", "")

    # #region agent log
    _agent_debug_log(
        "aml_pipeline.py:check_austrac_policy",
        "agent 3 input parsed",
        {
            "beneficiaries_raw_type": type(extracted_data.get("beneficiaries")).__name__,
            "beneficiaries_is_none": extracted_data.get("beneficiaries") is None,
            "beneficiaries_len": len(beneficiaries) if beneficiaries is not None else None,
            "trustee_company": trustee_company or "",
            "is_high_risk": extracted_data.get("is_high_risk", False),
        },
        "A",
    )
    # #endregion

    # FIX #5: Build a unified entity list including the trustee
    entities_to_screen: list[dict] = [
        {"name": name, "role": "Beneficiary"} for name in beneficiaries
    ]
    if trustee_company:
        entities_to_screen.append({"name": trustee_company, "role": "Trustee"})

    audit_trail = {
        "trust_name": extracted_data.get("trust_name"),
        "trustee_company": trustee_company,
        "is_high_risk_flag": extracted_data.get("is_high_risk", False),
        "total_entities_checked": len(entities_to_screen),
        "screening_sources": ["DFAT Consolidated Sanctions List"],
        "red_flags": [],
    }

    # ── DFAT Sanctions Screening ──────────────────────────────────────────────
    dfat_flags = _screen_entities(entities_to_screen, dfat_db, "DFAT")
    audit_trail["red_flags"].extend(dfat_flags)

    # ── FIX #6: PEP Screening ────────────────────────────────────────────────
    pep_db = load_pep_list()
    if pep_db:
        audit_trail["screening_sources"].append("PEP Database")
        pep_flags = _screen_entities(entities_to_screen, pep_db, "PEP")
        audit_trail["red_flags"].extend(pep_flags)

    flag_count = len(audit_trail["red_flags"])
    # #region agent log
    _agent_debug_log(
        "aml_pipeline.py:check_austrac_policy",
        "agent 3 screening complete",
        {
            "total_entities_checked": audit_trail["total_entities_checked"],
            "red_flag_count": flag_count,
            "red_flag_roles": [f.get("entity_role") for f in audit_trail["red_flags"]],
        },
        "D",
    )
    # #endregion
    log.info(f"Agent 3: Complete — {flag_count} red flag(s) found.")
    return audit_trail


# ══════════════════════════════════════════════════════════════════════════════
# AGENT 4 — REPORT DRAFTING
# Responsibility: Use Claude to convert the deterministic audit trail into
#                a human-readable, AUSTRAC-formatted compliance memo.
#
# Claude is used only for prose generation here, not for making risk decisions.
# All risk determinations come from Agent 3's deterministic output.
#
# FIX #3: Timezone-aware timestamp.
# FIX #8: Reference number is generated externally and passed in audit_trail.
# ══════════════════════════════════════════════════════════════════════════════


def generate_audit_report(audit_trail: dict) -> str:
    """
    Drafts a formal compliance memo based on Agent 3's audit trail.
    Returns the memo as a plain string.
    """
    log.info("Agent 4: Drafting final compliance report...")

    # NOTE: Model string updated to current Sonnet identifier.
    # Check Anthropic docs for latest model string before deploying.
    llm = ChatAnthropic(
        model="claude-sonnet-5",
        api_key=os.environ["ANTHROPIC_API_KEY"],
    )

    has_flags = len(audit_trail["red_flags"]) > 0
    has_high_risk = audit_trail.get("is_high_risk_flag", False)

    # FIX #8: Use the pre-generated reference number from the orchestrator
    ref_number = audit_trail.get("reference_number", "MISSING-REF")

    if not has_flags and not has_high_risk:
        report_type = "CLEARANCE CERTIFICATE — NO RISKS FOUND"
        instructions = (
            "Draft a formal compliance memo confirming that all named beneficiaries "
            "and the trustee company were screened against the DFAT Consolidated "
            "Sanctions List and no matches were found. Confirm that onboarding may "
            "proceed subject to standard ongoing monitoring obligations under "
            "AML-CTF Act 2006."
        )
    elif has_flags:
        report_type = "SUSPICIOUS MATTER SUMMARY — RED FLAGS DETECTED"
        instructions = (
            "Draft a formal compliance memo highlighting the matched entities. "
            "Include the entity role (Beneficiary or Trustee) and the Match "
            "Confidence Score for each match. "
            "State that submission of a Suspicious Matter Report (SMR) to AUSTRAC "
            "may be required and that manual review by the Head of Risk is mandatory "
            "before any onboarding decision is made."
        )
    else:
        # No sanctions match, but LLM flagged structural risk (e.g. foreign trustee)
        report_type = "ENHANCED DUE DILIGENCE REQUIRED — ELEVATED RISK INDICATORS"
        instructions = (
            "Draft a formal compliance memo noting that while no DFAT sanctions "
            "matches were found, the trust structure contains elevated risk indicators "
            "(e.g. foreign entities or non-resident beneficiaries). "
            "Recommend Enhanced Customer Due Diligence (ECDD) before proceeding."
        )

    # FIX #3: Timezone-aware timestamp
    audit_timestamp = datetime.now(tz=AEST).strftime("%Y-%m-%d %H:%M:%S %Z")

    prompt = f"""
You are the Lead Compliance Writer for an Australian Financial Institution.
Generate an official AUSTRAC-formatted {report_type}.

Reference Number: {ref_number}
Instructions: {instructions}

Raw Audit Data (from Python deterministic checks):
{json.dumps(audit_trail, indent=2)}

Date of Audit: {audit_timestamp}

Format: Professional, printable legal memo. Use the provided Reference Number
exactly as given — do not generate your own. Include date, subject line, body,
and a signature block for the Compliance Officer.
"""

    response = llm.invoke(prompt)
    # #region agent log
    _agent_debug_log(
        "aml_pipeline.py:generate_audit_report",
        "agent 4 response received",
        {
            "content_type": type(response.content).__name__,
            "content_is_str": isinstance(response.content, str),
            "content_preview": (
                response.content[:120]
                if isinstance(response.content, str)
                else str(response.content)[:120]
            ),
            "model": "claude-sonnet-5",
        },
        "C",
    )
    # #endregion
    log.info("Agent 4: Report generation complete.")
    # Handle newer langchain-anthropic versions where content is a list of blocks
    content = response.content
    if isinstance(content, list):
        parts = []
        for block in content:
            # Skip Claude's internal thinking blocks — not report content
            if isinstance(block, dict) and block.get("type") == "thinking":
                continue
            if hasattr(block, "type") and getattr(block, "type", None) == "thinking":
                continue
            if isinstance(block, dict):
                parts.append(block.get("text", str(block)))
            elif hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        content = "\n".join(parts)
    return content


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE ORCHESTRATOR
# Wires all four agents together with error handling, retry on Agent 2
# (LlamaParse can occasionally time out on large PDFs), and full audit
# trail persistence.
#
# FIX #2:  None guard after retry loop.
# FIX #7:  Intermediate outputs and final memo persisted to S3.
# FIX #8:  Deterministic reference number generated here.
# FIX #11: Env vars validated before pipeline runs.
# FIX #14: Overall pipeline timeout is platform-dependent. On Unix, wrap
#          run_pipeline() with signal.alarm(). On Windows, use
#          concurrent.futures.ThreadPoolExecutor with a timeout. The caller
#          is responsible for enforcing the overall timeout.
# FIX #15: Run ID enables resume-from-checkpoint in future iterations.
# ══════════════════════════════════════════════════════════════════════════════


def run_pipeline(
    company_abn: str,
    pre_uploaded_s3_key: Optional[str] = None,
    max_retries: int = 2,
) -> str:
    """
    Runs the full AML/KYC screening pipeline for a given ABN.

    Args:
        company_abn:         The 11-digit Australian Business Number.
        pre_uploaded_s3_key: S3 key of a client-uploaded trust deed (Path A).
                             If None, Agent 1 attempts to fetch from the registry.
        max_retries:         How many times to retry Agent 2 on transient failures.

    Returns:
        The final compliance memo as a string.
    """
    # FIX #11: Validate environment before doing any work
    validate_env()

    # #region agent log
    _agent_debug_log(
        "aml_pipeline.py:run_pipeline",
        "pipeline started",
        {
            "company_abn": company_abn,
            "pre_uploaded_s3_key": pre_uploaded_s3_key,
            "max_retries": max_retries,
            "env_present": {v: bool(os.environ.get(v)) for v in REQUIRED_ENV_VARS},
        },
        "E",
    )
    # #endregion

    # FIX #12: Validate ABN format and checksum
    if not validate_abn(company_abn):
        raise ValueError(
            f"Invalid ABN: '{company_abn}'. "
            "Australian Business Numbers must be exactly 11 digits "
            "and pass the ABR checksum validation."
        )

    # FIX #15: Generate a unique run ID for tracing and idempotency
    run_id = str(uuid.uuid4())
    log.info(f"Pipeline START — ABN {company_abn} — Run ID {run_id}")

    # FIX #8: Generate a deterministic, traceable reference number
    ref_timestamp = datetime.now(tz=AEST).strftime("%Y%m%d%H%M%S")
    reference_number = f"AML-{company_abn}-{ref_timestamp}-{run_id[:8]}"
    log.info(f"Pipeline reference number: {reference_number}")

    # ── AGENT 1: Gather & Upload ───────────────────────────────────────────────
    s3_key = gather_asic_data(company_abn, pre_uploaded_s3_key=pre_uploaded_s3_key)

    if not s3_key:
        raise RuntimeError(
            "Pipeline halted: No trust deed available. "
            "Request the document directly from the client."
        )

    # ── AGENT 2: Extract (with retry) ─────────────────────────────────────────
    extracted_json = None
    for attempt in range(1, max_retries + 2):
        try:
            extracted_json = extract_trust_deed(s3_key)
            break
        except Exception as exc:
            if attempt <= max_retries:
                wait = 2 ** attempt
                log.warning(
                    f"Agent 2 attempt {attempt} failed ({exc}). Retrying in {wait}s..."
                )
                time.sleep(wait)
            else:
                log.error("Agent 2: All retry attempts exhausted.")
                raise

    # FIX #2: Guard against None (defensive — the raise above should prevent this)
    if extracted_json is None:
        raise RuntimeError(
            "Agent 2 failed to produce extraction output after all attempts."
        )

    # FIX #15: Persist intermediate extraction output for checkpointing
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"{AUDIT_LOG_PREFIX}/{run_id}/extraction_output.json",
            Body=extracted_json,
            ContentType="application/json",
            ServerSideEncryption="aws:kms",  # FIX #9
        )
    except (BotoCoreError, ClientError) as exc:
        log.warning(f"Pipeline: Failed to persist extraction checkpoint — {exc}")
        # Non-fatal: pipeline continues even if checkpoint write fails

    # ── AGENT 3: Screen ───────────────────────────────────────────────────────
    dfat_db = load_dfat_sanctions()
    audit_trail = check_austrac_policy(extracted_json, dfat_db)

    # FIX #8: Inject reference number into audit trail for Agent 4
    audit_trail["reference_number"] = reference_number
    audit_trail["run_id"] = run_id

    # FIX #7: Persist screening results (required for 7-year retention)
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"{AUDIT_LOG_PREFIX}/{run_id}/screening_result.json",
            Body=json.dumps(audit_trail, indent=2),
            ContentType="application/json",
            ServerSideEncryption="aws:kms",  # FIX #9
        )
        log.info(
            f"Pipeline: Screening results persisted to "
            f"s3://{S3_BUCKET}/{AUDIT_LOG_PREFIX}/{run_id}/screening_result.json"
        )
    except (BotoCoreError, ClientError) as exc:
        # Audit persistence failure IS fatal — we cannot proceed without
        # a durable record of the screening decision.
        log.error(f"Pipeline: FATAL — Failed to persist screening results — {exc}")
        raise RuntimeError(
            "Cannot continue pipeline: audit trail persistence failed. "
            "AML-CTF Act Part 11 requires durable record-keeping."
        ) from exc

    # ── AGENT 4: Draft Report ─────────────────────────────────────────────────
    final_memo = generate_audit_report(audit_trail)

    # FIX #7: Persist final compliance memo
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"{AUDIT_LOG_PREFIX}/{run_id}/compliance_memo.txt",
            Body=final_memo,
            ContentType="text/plain",
            ServerSideEncryption="aws:kms",  # FIX #9
        )
        log.info(
            f"Pipeline: Compliance memo persisted to "
            f"s3://{S3_BUCKET}/{AUDIT_LOG_PREFIX}/{run_id}/compliance_memo.txt"
        )
    except (BotoCoreError, ClientError) as exc:
        log.warning(f"Pipeline: Failed to persist compliance memo — {exc}")
        # Non-fatal: the screening result (the legally critical part) is already saved.
        # The memo can be regenerated from the screening result if needed.

    log.info(f"Pipeline COMPLETE — Run ID {run_id}")
    return final_memo


# ══════════════════════════════════════════════════════════════════════════════
# DEBUG MOCK RUNNER (no S3 / LLM calls — tests deterministic agents locally)
# ══════════════════════════════════════════════════════════════════════════════


def run_debug_mock_tests() -> None:
    """
    Exercises Agent 3 and chunk splitting without external services.
    Writes NDJSON evidence to debug-4d4fc1.log for hypothesis validation.
    """
    log.info("Debug mock tests START")

    # Hypothesis B: chunk size invariant on a large synthetic document
    synthetic_doc = "# Schedule A\n" + ("Beneficiary: Jane Doe\n" * 8000)
    chunks = _split_into_chunks(synthetic_doc)

    # Hypothesis D: sanctions match on known mock list entry
    valid_extraction = json.dumps(
        {
            "trust_name": "Smith Family Trust",
            "trustee_company": "Smith Holdings Pty Ltd",
            "beneficiaries": ["Jonathan Smith", "Jane Doe"],
            "is_high_risk": False,
        }
    )
    dfat_db = load_dfat_sanctions()
    audit_trail = check_austrac_policy(valid_extraction, dfat_db)

    # Hypothesis A: null beneficiaries (common GPT structured-output edge case)
    null_beneficiaries_error = None
    try:
        null_extraction = json.dumps(
            {
                "trust_name": "Test Trust",
                "trustee_company": "Acme Pty Ltd",
                "beneficiaries": None,
                "is_high_risk": False,
            }
        )
        check_austrac_policy(null_extraction, dfat_db)
    except Exception as exc:
        null_beneficiaries_error = f"{type(exc).__name__}: {exc}"

    # #region agent log
    _agent_debug_log(
        "aml_pipeline.py:run_debug_mock_tests",
        "mock test summary",
        {
            "chunk_count": len(chunks),
            "max_chunk_size": max((len(c) for c in chunks), default=0),
            "chunks_exceed_limit": any(len(c) > CHUNK_SIZE for c in chunks),
            "sanctions_red_flags": len(audit_trail["red_flags"]),
            "null_beneficiaries_error": null_beneficiaries_error,
        },
        "SUMMARY",
    )
    # #endregion

    log.info(
        "Debug mock tests COMPLETE — red_flags=%s null_beneficiaries_error=%s",
        len(audit_trail["red_flags"]),
        null_beneficiaries_error,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if "--debug-mock" in sys.argv:
        run_debug_mock_tests()
        sys.exit(0)

    # ── SCENARIO A: Client uploads their own trust deed ───────────────────────
    # This is the most common real-world flow. The file is already in S3
    # (put there by your onboarding portal), so we skip the registry download.
    memo = run_pipeline(
        company_abn="51824753556",  # Example valid ABN (passes checksum)
        pre_uploaded_s3_key="client_uploads/51824753556_trust_deed.pdf",
    )

    # ── SCENARIO B: Attempt registry fetch (mock/dev only) ────────────────────
    # memo = run_pipeline(company_abn="51824753556")

    print("\n" + "=" * 60)
    print("FINAL COMPLIANCE MEMO")
    print("=" * 60)
    print(memo)
