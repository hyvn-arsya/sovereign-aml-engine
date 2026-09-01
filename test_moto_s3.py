"""
Moto-backed S3 integration tests.

These tests exercise the REAL boto3 S3 code paths in ``aml_pipeline``
(``gather_asic_data`` and the audit-trail persistence inside ``run_pipeline``)
against an in-process S3 mock provided by ``moto``. No real AWS credentials or
bucket are required --- moto intercepts botocore's S3 requests at the transport
layer, so the same ``s3.put_object(...)`` calls the pipeline makes in production
run for real against the mock.

What is real vs. mocked here:
  * REAL: every ``boto3`` S3 call (put_object, head_object) executes against
    moto's in-process S3, including the ``ServerSideEncryption="aws:kms"`` flag
    that the pipeline sets on every PII-bearing write.
  * MOCKED: the external registry HTTP hop (``GOVERNMENT_API_KEY`` /
    business.gov.au ABR endpoint) and the LLM agents (Agent 2 extraction,
    Agent 4 reporting). Those are external network dependencies that are out of
    scope for an S3 integration test; ``unittest.mock.patch`` stands in for them.

This is the documented way to exercise the S3 + audit-trail layer locally,
per the conversation in the repo's docs. It intentionally avoids needing real
AWS credentials or a bucket.

Run with:
    .venv312\\Scripts\\python.exe -m pytest test_moto_s3.py -v
"""

import json
import os
import uuid
from unittest.mock import patch

import pytest

# moto needs *some* credentials for boto3 to construct a client, but the mock
# never talks to real AWS, so fake values are safe. Set these BEFORE importing
# aml_pipeline so its module-level `s3 = boto3.client("s3")` is well-formed.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")

import boto3
from moto import mock_aws

from aml_pipeline import (
    gather_asic_data,
    S3_BUCKET,
    AUDIT_BUCKET,
    S3_PREFIX,
    AUDIT_LOG_PREFIX,
)

VALID_ABN = "51824753556"  # passes ABN checksum validation (no real lookup)
REGION = "ap-southeast-2"


@pytest.fixture
def mock_s3():
    """Provide a moto-backed S3 client and a freshly created raw bucket."""
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


def _read_object(client, bucket, key) -> bytes:
    return client.get_object(Bucket=bucket, Key=key)["Body"].read()


def test_gather_asic_data_path_a_preuploaded_key(mock_s3):
    """Path A: a pre-uploaded S3 key short-circuits without touching the registry."""
    with patch("aml_pipeline.s3", mock_s3):
        key = "client_uploads/trust_deed.pdf"
        result = gather_asic_data(VALID_ABN, pre_uploaded_s3_key=key)
        assert result == key


def test_gather_asic_data_path_b_registry_fetch_uploads_to_s3(mock_s3):
    """Path B: registry PDF download is persisted to S3 with aws:kms encryption.

    The external business.gov.au hops (registry JSON + PDF download) are mocked;
    the S3 write itself is real, against moto.
    """
    s3_key_expected = f"{S3_PREFIX}/{VALID_ABN}_trust_deed.pdf"

    registry_payload = {
        "status": "Registered",
        "directors": [{"name": "Marcus Edward Pemberton", "role": "Director"}],
        "trust_deed_document_link": "https://registry.example/trust-deed.pdf",
    }
    import requests

    pdf_bytes = b"%PDF-1.4 fake trust deed content for upload test"

    with patch.dict(
        os.environ,
        {"GOVERNMENT_API_KEY": "fake-registry-key"},
        clear=False,
    ):
        with patch("aml_pipeline.s3", mock_s3):
            with patch.object(
                requests,
                "get",
                side_effect=[
                    # 1st call: registry JSON
                    _FakeResponse(registry_payload),
                    # 2nd call: PDF download
                    _FakeResponse(pdf_bytes),
                ],
            ) as mock_get:
                result = gather_asic_data(VALID_ABN)

    assert mock_get.call_count == 2
    assert result == s3_key_expected

    # The uploaded object is actually present in moto S3, with KMS encryption.
    head = mock_s3.head_object(Bucket=S3_BUCKET, Key=s3_key_expected)
    assert head["ServerSideEncryption"] == "aws:kms"
    assert _read_object(mock_s3, S3_BUCKET, s3_key_expected) == pdf_bytes


def test_run_pipeline_persists_audit_trail_to_s3(mock_s3):
    """run_pipeline writes extraction/screening/memo to the audit bucket.

    Agents 2 (extraction) and 4 (reporting) are mocked; everything else ---
    ABN validation, Agent 3 screening, and the S3 audit persistence --- runs for
    real. The three audit artifacts must appear in moto S3 under audit_logs/.
    """
    run_id = str(uuid.uuid4())
    extracted_json = json.dumps(
        {
            "trust_name": "Pemberton Family Test Trust",
            "trustee_company": "Pemberton Advisory Pty Ltd",
            "beneficiaries": ["Marcus Pemberton", "Sarah Pemberton"],
            "is_high_risk": False,
        }
    )
    memo_text = "AML-COMPLIANCE-MEMO-PLACEHOLDER"

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
                "aml_pipeline.extract_trust_deed", return_value=extracted_json
            ) as mock_extract, patch(
                "aml_pipeline.generate_audit_report", return_value=memo_text
            ) as mock_report:
                from aml_pipeline import run_pipeline

                memo = run_pipeline(
                    VALID_ABN,
                    pre_uploaded_s3_key="client_uploads/trust_deed.pdf",
                    db=None,
                    run_id=run_id,
                )

    assert memo == memo_text
    mock_extract.assert_called_once()
    mock_report.assert_called_once()

    prefix = f"{AUDIT_LOG_PREFIX}/{run_id}"
    assert _read_object(mock_s3, AUDIT_BUCKET, f"{prefix}/extraction_output.json") == encoded(
        extracted_json
    )
    assert _read_object(mock_s3, AUDIT_BUCKET, f"{prefix}/compliance_memo.txt") == encoded(
        memo_text
    )

    screening = json.loads(
        _read_object(mock_s3, AUDIT_BUCKET, f"{prefix}/screening_result.json")
    )
    assert screening["reference_number"] == f"AML-{VALID_ABN}-{run_id[:8]}"
    assert screening["run_id"] == run_id

    # Every PII-bearing audit artifact must carry KMS encryption at rest.
    for key in (
        f"{prefix}/extraction_output.json",
        f"{prefix}/screening_result.json",
        f"{prefix}/compliance_memo.txt",
    ):
        head = mock_s3.head_object(Bucket=AUDIT_BUCKET, Key=key)
        assert head["ServerSideEncryption"] == "aws:kms", key


def encoded(text: str) -> bytes:
    return text.encode("utf-8")


class _FakeResponse:
    """Minimal stand-in for requests.get() that satisfies json()/content/raise_for_status."""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    @property
    def content(self):
        return self._payload

    def raise_for_status(self):
        return None
