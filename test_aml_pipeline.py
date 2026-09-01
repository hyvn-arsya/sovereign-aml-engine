import pytest
import json
from unittest.mock import patch, MagicMock

# Import the functions to test
from aml_pipeline import (
    _split_into_chunks,
    _normalize_company_name,
    _screen_entities,
    check_austrac_policy,
    load_dfat_sanctions,
    PEPApiError,
    FUZZY_MATCH_THRESHOLD,
    _is_meaningful_trustee,
    _reconcile_trustee,
)

def test_normalize_company_name():
    """Test suffix stripping and case normalization."""
    assert _normalize_company_name("Acme Pty Ltd") == "acme"
    assert _normalize_company_name("ACME PTY. LTD.") == "acme"
    assert _normalize_company_name("Acme Holdings") == "acme"
    assert _normalize_company_name("Acme Group") == "acme"
    assert _normalize_company_name("Acme Limited") == "acme"
    # No suffix
    assert _normalize_company_name("Jonathan Smith") == "jonathan smith"
    assert _normalize_company_name("") == ""
    assert _normalize_company_name(None) == ""

def test_fuzzy_match_boundaries():
    """Test that matches exactly at, below, and above 85% are handled correctly."""
    watchlist = [{"name": "John Doe", "type": "Sanctioned"}]
    
    # 1. Exact Match (100%)
    res = _screen_entities([{"name": "John Doe", "role": "Beneficiary"}], watchlist, "DFAT")
    assert len(res) == 1
    assert res[0]["match_confidence_score"] == 100

    # 2. Near Match (>85%) e.g. Johnny Doe
    res = _screen_entities([{"name": "Johnny Doe", "role": "Beneficiary"}], watchlist, "DFAT")
    assert len(res) == 1
    assert res[0]["match_confidence_score"] >= 85

    # 3. Definite Non-Match (<85%)
    res = _screen_entities([{"name": "Alexander Hamilton", "role": "Beneficiary"}], watchlist, "DFAT")
    assert len(res) == 0

def test_empty_beneficiaries_list():
    """Test handling of null or empty beneficiaries list (common LLM structured output edge case)."""
    dfat_db = [{"name": "Bad Guy", "type": "Sanctioned"}]
    
    # Null beneficiaries
    extracted = json.dumps({
        "trust_name": "Test Trust",
        "trustee_company": "Good Company",
        "beneficiaries": None,
        "is_high_risk": False
    })
    
    with patch("aml_pipeline.load_pep_list", return_value=[]):
        audit_trail = check_austrac_policy(extracted, dfat_db)
        # Should not crash, and should check 1 entity (the trustee)
        assert audit_trail["total_entities_checked"] == 1
        assert len(audit_trail["red_flags"]) == 0

def test_trustee_only_screening():
    """Test that trustee company is screened correctly."""
    dfat_db = [{"name": "Evil Corp", "type": "Sanctioned"}]
    
    extracted = json.dumps({
        "trust_name": "Test Trust",
        "trustee_company": "Evil Corp Pty Ltd",
        "beneficiaries": [],
        "is_high_risk": False
    })
    
    with patch("aml_pipeline.load_pep_list", return_value=[]):
        audit_trail = check_austrac_policy(extracted, dfat_db)
        assert audit_trail["total_entities_checked"] == 1
        assert len(audit_trail["red_flags"]) == 1
        assert audit_trail["red_flags"][0]["extracted_name"] == "Evil Corp Pty Ltd"
        assert audit_trail["red_flags"][0]["extracted_role"] == "Trustee"

def test_pep_api_failure_forces_incomplete_screening():
    """Test that a PEPApiError routes to incomplete screening."""
    dfat_db = [{"name": "Bad Guy", "type": "Sanctioned"}]
    
    extracted = json.dumps({
        "trust_name": "Test Trust",
        "trustee_company": "Good Company",
        "beneficiaries": ["Jane Doe"],
        "is_high_risk": False
    })
    
    with patch("aml_pipeline.load_pep_list", side_effect=PEPApiError("API Timeout")):
        audit_trail = check_austrac_policy(extracted, dfat_db)
        assert audit_trail["screening_incomplete"] is True
        # DFAT should still have been processed
        assert audit_trail["total_entities_checked"] == 2

def test_chunk_splitting():
    """Test the invariant properties of chunk splitting."""
    text = "A" * 50000
    chunks = _split_into_chunks(text, chunk_size=10000, overlap=1000)
    
    # Math: 
    # chunk 1: 0-10000
    # chunk 2: 9000-19000
    # chunk 3: 18000-28000
    # chunk 4: 27000-37000
    # chunk 5: 36000-46000
    # chunk 6: 45000-50000 (length 5000)
    assert len(chunks) == 6
    assert len(chunks[0]) == 10000
    assert len(chunks[-1]) == 5000
    # Reassembled, they should contain the same characters (though overlapping)
    assert all(c.startswith("A") for c in chunks)


def test_nickname_matching_catches_previously_missed_sanctioned_entities():
    """A sanctioned full name recorded under a common nickname must still flag.

    Raw fuzzy token matching scores these below the 85% threshold
    (e.g. Robert/Bob ~= 76, William/Bill ~= 78), so the deterministic alias
    table in Agent 3 must expand the diminutive and re-score.
    """
    watchlist = [
        {"name": "Robert Smith", "type": "Sanctioned"},
        {"name": "William Jones", "type": "Sanctioned"},
        {"name": "Richard Nixon", "type": "Sanctioned"},
        {"name": "Alexander Hamilton", "type": "Sanctioned"},
    ]
    beneficiaries = [
        {"name": "Bob Smith", "role": "Beneficiary"},
        {"name": "Bill Jones", "role": "Beneficiary"},
        {"name": "Dick Nixon", "role": "Beneficiary"},
        {"name": "Alex Hamilton", "role": "Beneficiary"},
    ]
    flags = _screen_entities(beneficiaries, watchlist, "DFAT")
    assert len(flags) == 4
    matched = {f["extracted_name"] for f in flags}
    assert matched == {"Bob Smith", "Bill Jones", "Dick Nixon", "Alex Hamilton"}
    # Every nickname-driven match is explicitly labelled as alias expansion
    assert all(f.get("match_reason") == "DFAT alias expansion" for f in flags)


def test_nickname_matching_avoids_false_positives():
    """Alias expansion must not create matches for genuinely different people."""
    watchlist = [{"name": "Robert Smith", "type": "Sanctioned"}]

    # Different surname, coincidental first-name nickname -> no match
    res = _screen_entities(
        [{"name": "Bob Marley", "role": "Beneficiary"}], watchlist, "DFAT"
    )
    assert len(res) == 0

    # Same surname but completely different first name -> no match
    res = _screen_entities(
        [{"name": "Alice Smith", "role": "Beneficiary"}], watchlist, "DFAT"
    )
    assert len(res) == 0


# ─────────────────────────────────────────────────────────────────────────────
# trustee_company chunk reconciliation (Agent 2 merge rule)
# ─────────────────────────────────────────────────────────────────────────────

def test_is_meaningful_trustee():
    """Real names are meaningful; empty and low-information values are not."""
    assert _is_meaningful_trustee("Pemberton Advisory Pty Ltd") is True
    assert _is_meaningful_trustee(" ACME Holdings Ltd ") is True
    assert _is_meaningful_trustee("") is False
    assert _is_meaningful_trustee(None) is False
    # Placeholders that add no information must be rejected.
    for placeholder in (
        "Not specified", "unspecified", "Unknown", "Unknown Trustee",
        "N/A", "none", "null", "not mentioned", "not stated",
        "not found", "not provided", "  NA  ",
    ):
        assert _is_meaningful_trustee(placeholder) is False, placeholder


def test_reconcile_trustee_placeholder_never_overwrites_concrete():
    """A later 'Not specified' chunk must NOT erase a concrete trustee name."""
    concrete = "Pemberton Advisory Pty Ltd"
    new_value, discrepancy, skipped = _reconcile_trustee(concrete, "Not specified")
    assert new_value == concrete
    assert skipped is True
    assert discrepancy is False


def test_reconcile_trustee_first_concrete_value_is_set():
    """The first concrete trustee value is adopted (no discrepancy logged)."""
    new_value, discrepancy, skipped = _reconcile_trustee(None, "Pemberton Advisory Pty Ltd")
    assert new_value == "Pemberton Advisory Pty Ltd"
    assert discrepancy is False
    assert skipped is False


def test_reconcile_trustee_same_concrete_value_is_kept():
    """Repeating the same concrete value across chunks is a no-op."""
    new_value, discrepancy, skipped = _reconcile_trustee(
        "Pemberton Advisory Pty Ltd", "Pemberton Advisory Pty Ltd"
    )
    assert new_value == "Pemberton Advisory Pty Ltd"
    assert discrepancy is False
    assert skipped is False


def test_reconcile_trustee_different_concrete_value_overwrites():
    """A genuinely different concrete value replaces the old one (flagged)."""
    new_value, discrepancy, skipped = _reconcile_trustee(
        "Pemberton Holdings Pty Ltd", "Pemberton Advisory Pty Ltd"
    )
    assert new_value == "Pemberton Advisory Pty Ltd"
    assert discrepancy is True
    assert skipped is False


def test_reconcile_trustee_placeholder_alone_stays_unknown():
    """If only placeholders arrive, no concrete trustee is ever adopted."""
    new_value, discrepancy, skipped = _reconcile_trustee(None, "Not specified")
    assert new_value is None
    assert skipped is True
    assert discrepancy is False
