"""
Priority 1/2/4 integration tests.

Covers the data-engineering upgrade:

  * Priority 1  - deterministic processing key (content-based idempotency)
  * Priority 2  - pipeline_runs table records execution + runtime metrics
  * Priority 4  - entities / entity_aliases / screening_matches are persisted
                  from the previously in-memory screening decisions

These run the REAL `run_pipeline(...)` with moto (S3) + an in-memory SQLite
engine, with only the LLM agents mocked. The document fingerprint is computed
from the real uploaded bytes, so idempotency is exercised content-for-content.

Run with:
    .venv312\\Scripts\\python.exe -m pytest test_priorities.py -v
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models  # registers tables with database.Base.metadata
from database import Base
from aml_pipeline import (
    compute_processing_key,
    S3_BUCKET,
    AUDIT_BUCKET,
    AUDIT_LOG_PREFIX,
    PIPELINE_VERSION,
    EXTRACTION_MODEL,
    SCREENING_ALGORITHM_VERSION,
)

VALID_ABN = "51824753556"  # passes ABN checksum validation (no real lookup)
REGION = "ap-southeast-2"

# moto needs fake credentials for boto3 construction; nothing touches real AWS.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")


@pytest.fixture
def mock_s3():
    """moto S3 client with the raw + audit buckets created."""
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(
            Bucket=S3_BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        if AUDIT_BUCKET != S3_BUCKET:
            client.create_bucket(
                Bucket=AUDIT_BUCKET,
                CreateBucketConfiguration={"LocationConstraint": REGION},
            )
        yield client


@pytest.fixture
def db_session():
    """Fresh in-memory SQLite session for each test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


# ──────────────────────────────────────────────────────────────────────────────
# PRIORITY 1: compute_processing_key
# ──────────────────────────────────────────────────────────────────────────────
class TestComputeProcessingKey:
    def test_deterministic_for_same_inputs(self):
        a = compute_processing_key("51824753556", "aa" * 32)
        b = compute_processing_key("51824753556", "aa" * 32)
        assert a == b
        assert len(a) == 64

    def test_changes_with_document_content(self):
        a = compute_processing_key("51824753556", "aa" * 32)
        b = compute_processing_key("51824753556", "bb" * 32)
        assert a != b

    def test_changes_with_abn(self):
        a = compute_processing_key("51824753556", "aa" * 32)
        b = compute_processing_key("51824753557", "aa" * 32)
        assert a != b

    def test_changes_when_pipeline_version_bumps(self):
        a = compute_processing_key(
            "51824753556", "aa" * 32, pipeline_version="0.1.0"
        )
        b = compute_processing_key(
            "51824753556", "aa" * 32, pipeline_version="0.2.0"
        )
        assert a != b

    def test_changes_when_extraction_model_bumps(self):
        a = compute_processing_key(
            "51824753556", "aa" * 32, extraction_model="gemini-3.1-pro-preview"
        )
        b = compute_processing_key(
            "51824753556", "aa" * 32, extraction_model="gemini-4.0-pro"
        )
        assert a != b

    def test_changes_when_screening_algorithm_bumps(self):
        a = compute_processing_key(
            "51824753556", "aa" * 32, screening_algorithm_version="1"
        )
        b = compute_processing_key(
            "51824753556", "aa" * 32, screening_algorithm_version="2"
        )
        assert a != b


# ──────────────────────────────────────────────────────────────────────────────
# PRIORITY 1 + 2 + 4: end-to-end idempotency, run metrics, entity persistence
# ──────────────────────────────────────────────────────────────────────────────
def _extraction_json(beneficiaries=None):
    return json.dumps(
        {
            "trust_name": "Pemberton Family Test Trust",
            "trustee_company": "Pemberton Advisory Pty Ltd",
            "beneficiaries": beneficiaries or ["Bob Smith", "Alice Jones"],
            "is_high_risk": False,
        }
    )


_MEMO = "AML-COMPLIANCE-MEMO-<deterministic>"


def _run_once(client, session, abn, doc_bytes, s3_key):
    """Execute run_pipeline once against moto + in-memory sqlite."""
    from aml_pipeline import run_pipeline

    def fake_extract(s3_key_arg, stats=None):
        stats["chunk_count"] = 2
        return _extraction_json()

    with patch.dict(
        os.environ,
        {
            "LLAMACLOUD_API_KEY": "fake",
            "GOOGLE_API_KEY": "fake",
            "ANTHROPIC_API_KEY": "fake",
        },
        clear=False,
    ):
        client.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=doc_bytes)
        with patch("aml_pipeline.s3", client):
            with patch("aml_pipeline.extract_trust_deed", side_effect=fake_extract):
                with patch("aml_pipeline.generate_audit_report", return_value=_MEMO):
                    with patch(
                        "aml_pipeline.load_pep_list",
                        return_value=[
                            {"name": "Robert Smith", "type": "PEP - Test Entry"}
                        ],
                    ):
                        return run_pipeline(abn, pre_uploaded_s3_key=s3_key, db=session)


def test_run_pipeline_persists_pipeline_run_metrics(mock_s3, db_session):
    """Priority 2: a completed run lands in pipeline_runs with runtime metrics."""
    doc_bytes = b"%PDF-1.4 pemberton family deed v1"
    s3_key = "client_uploads/trust_deed.pdf"

    memo = _run_once(mock_s3, db_session, VALID_ABN, doc_bytes, s3_key)
    assert memo == _MEMO

    from models import PipelineRun, Trust

    run = db_session.query(PipelineRun).one()
    assert run.status == "completed"
    assert run.abn == VALID_ABN
    assert run.chunk_count == 2
    assert run.entity_count == 3  # 2 beneficiaries + 1 trustee
    assert run.red_flag_count == 1  # Bob Smith -> PEP Robert Smith (alias)
    assert run.duration_ms is not None and run.duration_ms >= 0
    assert run.started_at is not None
    assert run.completed_at is not None

    trust = db_session.query(Trust).one()
    # The Trust row carries the deterministic processing key.
    doc_hash = hashlib.sha256(doc_bytes).hexdigest()
    assert trust.processing_key == compute_processing_key(VALID_ABN, doc_hash)
    assert run.processing_key == trust.processing_key


def test_processing_key_skips_content_replay(mock_s3, db_session):
    """Priority 1: re-screening the SAME document under a NEW run_id is skipped."""
    doc_bytes = b"%PDF-1.4 same deed bytes, brand new run_id"
    s3_key = "client_uploads/trust_deed.pdf"

    first = _run_once(mock_s3, db_session, VALID_ABN, doc_bytes, s3_key)
    assert first == _MEMO

    from models import PipelineRun, Trust

    before_trust_count = db_session.query(Trust).count()
    before_run_count = db_session.query(PipelineRun).count()

    import uuid
    # Same document + same ABN + same versions, but a NOT-null run_id would
    # normally defeat run_id-based idempotency. Content-based key still skips.
    with patch.dict(
        os.environ,
        {
            "LLAMACLOUD_API_KEY": "fake",
            "GOOGLE_API_KEY": "fake",
            "ANTHROPIC_API_KEY": "fake",
        },
        clear=False,
    ):
        with patch("aml_pipeline.s3", mock_s3):
            with patch(
                "aml_pipeline.extract_trust_deed",
                side_effect=lambda k, stats=None: stats.update(chunk_count=2)
                or _extraction_json(),
            ):
                with patch(
                    "aml_pipeline.generate_audit_report", return_value=_MEMO
                ):
                    with patch("aml_pipeline.load_pep_list", return_value=[]):
                        from aml_pipeline import run_pipeline

                        second = run_pipeline(
                            VALID_ABN,
                            pre_uploaded_s3_key=s3_key,
                            db=db_session,
                            run_id=str(uuid.uuid4()),
                        )

    assert str(second).startswith("SKIPPED: Already processed under reference")
    # No duplicate Trust row and no extra completed run was recorded.
    assert db_session.query(Trust).count() == before_trust_count
    assert db_session.query(PipelineRun).count() == before_run_count


def test_different_document_is_not_skipped(mock_s3, db_session):
    """Priority 1: a NEW document (different bytes) reprocesses normally."""
    from models import Trust

    first = _run_once(
        mock_s3, db_session, VALID_ABN, b"%PDF-1.4 deeds v1", "client_uploads/a.pdf"
    )
    assert first == _MEMO
    assert db_session.query(Trust).count() == 1

    second = _run_once(
        mock_s3, db_session, VALID_ABN, b"%PDF-1.4 deeds v2", "client_uploads/a.pdf"
    )
    assert second == _MEMO
    assert db_session.query(Trust).count() == 2  # different content → new result


def test_entity_model_persists_aliases_and_match_method(mock_s3, db_session):
    """Priority 4: Bob Smith -> PEP Robert Smith is persisted as alias_expansion."""
    doc_bytes = b"%PDF-1.4 alias deed"
    s3_key = "client_uploads/alias.pdf"

    _run_once(mock_s3, db_session, VALID_ABN, doc_bytes, s3_key)

    from models import Entity, EntityAlias, ScreeningMatch

    bob = db_session.query(Entity).filter_by(canonical_name="Bob Smith").one()
    assert bob.entity_type == "Beneficiary"

    matches = (
        db_session.query(ScreeningMatch)
        .filter_by(entity_id=bob.id)
        .all()
    )
    assert len(matches) == 1
    assert matches[0].watchlist_name == "Robert Smith"
    assert matches[0].match_method == "alias_expansion"

    # The alias form that closed the match is persisted on the entity.
    aliases = db_session.query(EntityAlias).filter_by(entity_id=bob.id).all()
    assert len(aliases) == 1
    assert aliases[0].alias_type == "given_name_variant"

    # Trustee is also a persisted entity, with no screening match.
    trustee = (
        db_session.query(Entity)
        .filter_by(canonical_name="Pemberton Advisory Pty Ltd")
        .one()
    )
    assert trustee.entity_type == "Trustee"
    assert db_session.query(ScreeningMatch).filter_by(entity_id=trustee.id).count() == 0


def test_direct_match_recorded_as_direct_method(mock_s3, db_session):
    """Priority 4: exact-name matches are tagged match_method='direct'."""
    doc_bytes = b"%PDF-1.4 direct-hit deed"
    s3_key = "client_uploads/direct.pdf"

    from aml_pipeline import run_pipeline

    def fake_extract(s3_key_arg, stats=None):
        stats["chunk_count"] = 1
        return json.dumps(
            {
                "trust_name": "Hit Test Trust",
                "trustee_company": "Pemberton Advisory Pty Ltd",
                "beneficiaries": ["Jonathan Smith", "Oliver Jones"],
                "is_high_risk": False,
            }
        )

    with patch.dict(
        os.environ,
        {
            "LLAMACLOUD_API_KEY": "fake",
            "GOOGLE_API_KEY": "fake",
            "ANTHROPIC_API_KEY": "fake",
        },
        clear=False,
    ):
        mock_s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=doc_bytes)
        with patch("aml_pipeline.s3", mock_s3):
            with patch("aml_pipeline.extract_trust_deed", side_effect=fake_extract):
                with patch("aml_pipeline.generate_audit_report", return_value=_MEMO):
                    # DFAT seed list contains "Jonathan Smith" → direct match
                    with patch("aml_pipeline.load_pep_list", return_value=[]):
                        run_pipeline(
                            VALID_ABN, pre_uploaded_s3_key=s3_key, db=db_session
                        )

    from models import Entity, ScreeningMatch

    jonathan = (
        db_session.query(Entity).filter_by(canonical_name="Jonathan Smith").one()
    )
    matches = (
        db_session.query(ScreeningMatch)
        .filter_by(entity_id=jonathan.id)
        .all()
    )
    assert len(matches) == 1
    assert matches[0].match_method == "direct"
    assert matches[0].watchlist_name == "Jonathan Smith"


# ──────────────────────────────────────────────────────────────────────────────
# SECURITY REVIEW REGRESSIONS
#  * incomplete screening → explicit BLOCKED outcome (not a normal memo)
#  * blocked memo is deterministic (LLM-independent)
#  * concurrency-safe claim on the processing key
#  * production screening mode fails closed on mock DFAT / PEP sources
# ──────────────────────────────────────────────────────────────────────────────

def _generic_extract(s3_key_arg, stats=None):
    stats["chunk_count"] = 2
    return _extraction_json()


def test_incomplete_pep_screening_returns_blocked_outcome(mock_s3, db_session):
    """
    SECURITY (High): a failed PEP lookup must yield an explicit blocked outcome
    with pipeline_runs.status='blocked' — never a normal compliance memo.
    """
    from aml_pipeline import run_pipeline, PEPApiError, BLOCKED_PREFIX

    doc_bytes = b"%PDF-1.4 deed when the PEP API is down"
    s3_key = "client_uploads/pep_down.pdf"

    with patch.dict(
        os.environ,
        {
            "LLAMACLOUD_API_KEY": "fake",
            "GOOGLE_API_KEY": "fake",
            "ANTHROPIC_API_KEY": "fake",
        },
        clear=False,
    ):
        mock_s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=doc_bytes)
        with patch("aml_pipeline.s3", mock_s3):
            with patch("aml_pipeline.extract_trust_deed", side_effect=_generic_extract):
                with patch("aml_pipeline.load_pep_list", side_effect=PEPApiError("PEP down")):
                    with patch("aml_pipeline.generate_audit_report") as mock_report:
                        memo = run_pipeline(
                            VALID_ABN, pre_uploaded_s3_key=s3_key, db=db_session
                        )

    assert memo.startswith(BLOCKED_PREFIX)
    # The safety memo must not depend on LLM availability.
    mock_report.assert_not_called()

    from models import PipelineRun

    run = db_session.query(PipelineRun).one()
    assert run.status == "blocked"
    assert run.completed_at is not None


def test_extraction_chunk_failure_blocks_outcome(mock_s3, db_session):
    """
    SECURITY (High): a dropped extraction chunk is a data-availability gap and
    must block, not silently produce a normal memo.
    """
    from aml_pipeline import run_pipeline, BLOCKED_PREFIX

    doc_bytes = b"%PDF-1.4 deed with a chunk that will fail"
    s3_key = "client_uploads/chunk_fail.pdf"

    def flaky_extract(s3_key_arg, stats=None):
        stats["chunk_count"] = 3
        stats["failed_chunks"] = 1
        stats["failed_chunk_indexes"] = [2]
        return _extraction_json()

    with patch.dict(
        os.environ,
        {
            "LLAMACLOUD_API_KEY": "fake",
            "GOOGLE_API_KEY": "fake",
            "ANTHROPIC_API_KEY": "fake",
        },
        clear=False,
    ):
        mock_s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=doc_bytes)
        with patch("aml_pipeline.s3", mock_s3):
            with patch("aml_pipeline.extract_trust_deed", side_effect=flaky_extract):
                with patch("aml_pipeline.load_pep_list", return_value=[]):
                    with patch("aml_pipeline.generate_audit_report") as mock_report:
                        memo = run_pipeline(
                            VALID_ABN, pre_uploaded_s3_key=s3_key, db=db_session
                        )

    assert memo.startswith(BLOCKED_PREFIX)
    assert "chunk" in memo
    mock_report.assert_not_called()

    from models import PipelineRun

    run = db_session.query(PipelineRun).one()
    assert run.status == "blocked"


def test_extraction_stats_record_failed_chunks():
    """
    SECURITY (High): a chunk that fails to extract is surfaced in stats
    (failed_chunks / failed_chunk_indexes) instead of being silently dropped.
    """
    import io
    from types import SimpleNamespace
    from unittest.mock import Mock

    from aml_pipeline import extract_trust_deed, TrustDeedExtraction

    doc_bytes = b"%PDF-1.4 a deed with two llm chunks"

    class FakeLlamaParse:
        def __init__(self, **kwargs):
            pass

        def load_data(self, file_path, extra_info):
            return [
                SimpleNamespace(text="A" * 30000),
                SimpleNamespace(text="B" * 30000),
            ]

    provider = Mock()
    provider.name = "fake-provider"
    provider.extract_structured.side_effect = [
        RuntimeError("LLM down for chunk 1"),
        TrustDeedExtraction(
            trust_name="Test Trust",
            trustee_company="Test Trustee Pty Ltd",
            beneficiaries=["Beneficiary One"],
            is_high_risk=False,
        ),
    ]

    stats = {}
    with patch.dict(os.environ, {"LLAMACLOUD_API_KEY": "fake"}, clear=False):
        with patch("aml_pipeline.LlamaParse", FakeLlamaParse):
            with patch("aml_pipeline._provider", return_value=provider):
                with patch(
                    "aml_pipeline.s3.get_object",
                    return_value={"Body": io.BytesIO(doc_bytes)},
                ):
                    extract_trust_deed("client_uploads/failed_chunks.pdf", stats=stats)

    assert stats["chunk_count"] == 2
    assert stats["failed_chunks"] == 1
    assert stats["failed_chunk_indexes"] == [1]


def test_claim_processing_key_prevents_duplicate_work(db_session):
    """
    SECURITY (Medium): the unique processing_key on pipeline_runs is a
    concurrency-safe claim. A second worker racing on the same key is skipped
    instead of duplicating expensive Agent 2/3 work.
    """
    import uuid

    from aml_pipeline import _claim_processing_key, compute_processing_key
    from models import PipelineRun, Trust

    doc_bytes = b"%PDF-1.4 concurrent deed"
    pkey = compute_processing_key(VALID_ABN, hashlib.sha256(doc_bytes).hexdigest())

    # Worker A claims the key.
    run_a = str(uuid.uuid4())
    claimed, skip = _claim_processing_key(
        db_session, run_a, pkey, VALID_ABN, datetime.now(timezone.utc)
    )
    assert claimed is not None
    assert skip is None

    # Worker B races with an identical claim while A is still running.
    run_b = str(uuid.uuid4())
    claimed_b, skip_b = _claim_processing_key(
        db_session, run_b, pkey, VALID_ABN, datetime.now(timezone.utc)
    )
    assert claimed_b is None
    assert "in progress" in skip_b
    assert "SKIPPED" in skip_b

    # A now completes and records the Trust row.
    db_session.add(Trust(
        run_id=run_a,
        processing_key=pkey,
        reference_number=f"AML-{VALID_ABN}-{run_a[:8]}",
        abn=VALID_ABN,
    ))
    db_session.commit()

    # A retry after completion reports the official reference number.
    _, skip_c = _claim_processing_key(
        db_session, str(uuid.uuid4()), pkey, VALID_ABN, datetime.now(timezone.utc)
    )
    assert f"reference AML-{VALID_ABN}" in skip_c

    # Only worker A's claim row survived; neither loser added a row.
    assert db_session.query(PipelineRun).count() == 1
    assert db_session.query(Trust).count() == 1


def test_production_mode_refuses_mock_dfat():
    """SECURITY (High): production mode fails closed without a real DFAT source."""
    from aml_pipeline import load_dfat_sanctions, PEPApiError, _dfat_cache

    _dfat_cache["data"] = None
    _dfat_cache["fetched_at"] = None
    with patch.dict(
        os.environ,
        {"SCREENING_MODE": "production", "DFAT_SOURCE_URL": ""},
        clear=False,
    ):
        with pytest.raises(PEPApiError):
            load_dfat_sanctions()
    _dfat_cache["data"] = None
    _dfat_cache["fetched_at"] = None


def test_production_mode_refuses_mock_pep():
    """SECURITY (High): production mode fails closed without a PEP provider."""
    from aml_pipeline import load_pep_list, PEPApiError

    with patch.dict(
        os.environ,
        {"SCREENING_MODE": "production", "PEP_API_KEY": ""},
        clear=False,
    ):
        with pytest.raises(PEPApiError):
            load_pep_list()


def test_demo_mode_returns_mocks_by_default():
    """Demo (default) mode still returns the bundled mock data with a warning."""
    from aml_pipeline import load_pep_list

    with patch.dict(os.environ, {"PEP_API_KEY": ""}, clear=False):
        peps = load_pep_list()
    assert any(p["type"].startswith("PEP") for p in peps)