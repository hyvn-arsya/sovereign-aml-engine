"""
Local Pipeline Test v2 -- Bypasses S3, reads PDF from disk.
Uses pymupdf4llm for local PDF parsing (no LlamaParse API needed).
Tests Agent 2 (extraction) -> Agent 3 (Screening) -> Agent 4 (Report)

> NOTE: This is a DEVELOPMENT-ONLY script and is NOT the canonical
> extraction path. The production path is the chunk-and-merge pipeline in
> ``aml_pipeline.extract_trust_deed`` (LlamaParse + Gemini), which guarantees
> every page of a large trust deed is processed (see the rationale in
> ``aml_pipeline.py``). This script uses a single-pass prompt with a local
> parser mainly to exercise Agents 3 and 4 offline.

Usage:
    1. Set your API keys:
        $env:OPENAI_API_KEY = "your-key"
        $env:ANTHROPIC_API_KEY = "your-key"

    2. Run with a local PDF:
        python test_local.py "C:\\path\\to\\trust_deed.pdf"

    3. Or run with just Agent 3+4 (no API keys needed) using mock extraction:
        python test_local.py --mock-only

Dev dependency (not in requirements.txt): pip install pymupdf4llm
"""

import json
import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("test_local")


def test_agents_3_and_4_mock():
    """Test Agent 3 + 4 with hardcoded extraction data. No API keys needed."""
    from aml_pipeline import (
        check_austrac_policy,
        load_dfat_sanctions,
        generate_audit_report,
    )
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import uuid

    AEST = ZoneInfo("Australia/Sydney")

    # Simulate Agent 2 output -- a trust with one sanctioned beneficiary
    mock_extraction = json.dumps({
        "trust_name": "Smith Family Trust",
        "trustee_company": "Smith Holdings Pty Ltd",
        "beneficiaries": ["Jonathan Smith", "Jane Doe", "Alice Johnson"],
        "is_high_risk": False,
    })

    log.info("=" * 60)
    log.info("TEST 1: Agent 3 -- Screening (should flag Jonathan Smith)")
    log.info("=" * 60)

    dfat_db = load_dfat_sanctions()
    audit_trail = check_austrac_policy(mock_extraction, dfat_db)

    # Inject reference number (normally done by orchestrator)
    run_id = str(uuid.uuid4())
    ref_timestamp = datetime.now(tz=AEST).strftime("%Y%m%d%H%M%S")
    audit_trail["reference_number"] = f"AML-TEST-{ref_timestamp}-{run_id[:8]}"
    audit_trail["run_id"] = run_id

    print("\n--- Agent 3 Output ---")
    print(json.dumps(audit_trail, indent=2))

    if not audit_trail["red_flags"]:
        log.warning("No red flags found -- expected at least 1 for 'Jonathan Smith'")
    else:
        log.info(f"Found {len(audit_trail['red_flags'])} red flag(s)")

    # Only test Agent 4 if Anthropic key is available
    if os.environ.get("ANTHROPIC_API_KEY"):
        log.info("=" * 60)
        log.info("TEST 2: Agent 4 -- Report Generation (Claude)")
        log.info("=" * 60)

        memo = generate_audit_report(audit_trail)
        print("\n--- Agent 4 Output ---")
        print(memo)
    else:
        log.info("Skipping Agent 4 (ANTHROPIC_API_KEY not set)")

    return audit_trail


def test_full_pipeline_local(pdf_path: str):
    """Test Agents 2->3->4 with a real PDF file from disk."""
    import pymupdf4llm

    # Verify API keys
    missing = []
    # Test script checks GOOGLE_API_KEY later, but we can do a quick check here too
    if not os.environ.get("GOOGLE_API_KEY"):
        missing.append("GOOGLE_API_KEY")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nWARNING: ANTHROPIC_API_KEY not set. Agent 4 will be skipped.")

    if not os.path.exists(pdf_path):
        print(f"\nERROR: File not found: {pdf_path}")
        sys.exit(1)

    # Import pipeline components
    from aml_pipeline import (
        TrustDeedExtraction,
        check_austrac_policy,
        load_dfat_sanctions,
        generate_audit_report,
    )
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import uuid

    AEST = ZoneInfo("Australia/Sydney")

    # -- Agent 2: Parse PDF locally with pymupdf4llm (no API needed) ----
    log.info("=" * 60)
    log.info(f"AGENT 2: Parsing PDF -- {pdf_path}")
    log.info("=" * 60)

    markdown_text = pymupdf4llm.to_markdown(pdf_path)
    log.info(f"Parsed {len(markdown_text)} characters of markdown")

    # Save raw markdown for inspection
    md_output = pdf_path.rsplit(".", 1)[0] + "_parsed.md"
    with open(md_output, "w", encoding="utf-8") as f:
        f.write(markdown_text)
    log.info(f"Raw markdown saved to: {md_output}")

    # Show first 500 chars as a sanity check
    print("\n--- Parsed Markdown (first 500 chars) ---")
    print(markdown_text[:500])
    print("...")

    from langchain_google_genai import ChatGoogleGenerativeAI
    
    missing = []
    for key in ["GOOGLE_API_KEY"]:
        if not os.environ.get(key):
            missing.append(key)
    if missing:
        print(f"\nERROR: Missing API keys: {', '.join(missing)}")
        print("\nSet them in PowerShell before running:")
        for key in missing:
            print(f'    $env:{key} = "your-key-here"')
        sys.exit(1)

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
    log.info("Agent 2: Extracting entities in a single pass using Gemini 1.5 Pro...")
    result = structured_llm.invoke(prompt)
    
    extracted_json = result.model_dump_json(indent=2)

    # Save extraction output
    json_output = pdf_path.rsplit(".", 1)[0] + "_extraction.json"
    with open(json_output, "w", encoding="utf-8") as f:
        f.write(extracted_json)
    log.info(f"Extraction saved to: {json_output}")

    print("\n--- Agent 2 Extraction ---")
    print(extracted_json)

    # -- Agent 3: Screen -----------------------------------------------
    log.info("=" * 60)
    log.info("AGENT 3: Screening")
    log.info("=" * 60)

    dfat_db = load_dfat_sanctions()
    audit_trail = check_austrac_policy(extracted_json, dfat_db)

    run_id = str(uuid.uuid4())
    ref_timestamp = datetime.now(tz=AEST).strftime("%Y%m%d%H%M%S")
    audit_trail["reference_number"] = f"AML-LOCAL-{ref_timestamp}-{run_id[:8]}"
    audit_trail["run_id"] = run_id

    print("\n--- Agent 3 Screening Result ---")
    print(json.dumps(audit_trail, indent=2))

    # -- Agent 4: Report -----------------------------------------------
    if os.environ.get("ANTHROPIC_API_KEY"):
        log.info("=" * 60)
        log.info("AGENT 4: Report Generation")
        log.info("=" * 60)

        memo = generate_audit_report(audit_trail)

        # Save report
        report_output = pdf_path.rsplit(".", 1)[0] + "_report.txt"
        with open(report_output, "w", encoding="utf-8") as f:
            f.write(memo)
        log.info(f"Report saved to: {report_output}")

        print("\n--- Agent 4 Compliance Report ---")
        print(memo)
    else:
        log.info("Skipping Agent 4 (ANTHROPIC_API_KEY not set)")

    log.info("LOCAL TEST COMPLETE")


if __name__ == "__main__":
    if len(sys.argv) < 2 or "--mock-only" in sys.argv:
        test_agents_3_and_4_mock()
    else:
        test_full_pipeline_local(sys.argv[1])
