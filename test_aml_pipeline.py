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
    FUZZY_MATCH_THRESHOLD
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
