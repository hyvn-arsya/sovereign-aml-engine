"""
SECURITY REVIEW tests for the public API:

  * X-Api-Key authentication on every data-touching endpoint
    (POST /analyze/abn, POST /analyze/abn/async, GET /jobs/{id})
  * Tenant authorization — callers can only
      - supply an S3 key under their OWN tenant prefix
      - poll their OWN jobs (cross-tenant job ids 404)
  * Incomplete screening surfaces an explicit 'blocked' job status / response
  * The plaintext API key is never persisted (only a salted hash)

Set env before importing the API so database.py binds an isolated scratch
SQLite file and the startup key-seeder has something to load.
"""

import hashlib
import os
import uuid

from fastapi.testclient import TestClient
from unittest.mock import patch

import pytest

_TMP_DB = os.path.join(
    os.environ.get("TEMP", "."),
    "opencode",
    f"api_auth_{uuid.uuid4().hex}.db",
)
_SCRATCH_URI = f"sqlite:///{_TMP_DB.replace(os.sep, '/')}"

os.environ["DATABASE_URL"] = _SCRATCH_URI
os.environ["SEED_API_KEYS"] = "acme-corp:acme-secret-1,big-bank:big-secret-2"
os.environ["API_KEY_SALT"] = "test-salt"

import api as api_module  # noqa: E402
from aml_pipeline import BLOCKED_PREFIX  # noqa: E402
from database import Base, SessionLocal, engine  # noqa: E402
from models import AnalysisJob, ApiKey, Tenant  # noqa: E402

Base.metadata.create_all(engine)

VALID_ABN = "51824753556"
ACME_KEY = "acme-secret-1"
BANK_KEY = "big-secret-2"


@pytest.fixture(scope="module")
def client():
    with TestClient(api_module.app) as c:
        yield c


def _headers(api_key: str):
    return {"X-Api-Key": api_key}


# ──────────────────────────────────────────────────────────────────────────────
# AUTHENTICATION
# ──────────────────────────────────────────────────────────────────────────────

def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200


def test_async_endpoint_requires_api_key(client):
    r = client.post("/analyze/abn/async", json={"company_abn": VALID_ABN})
    assert r.status_code == 401
    r2 = client.post(
        "/analyze/abn/async",
        json={"company_abn": VALID_ABN},
        headers=_headers("wrong-key"),
    )
    assert r2.status_code == 401


def test_sync_endpoint_requires_api_key(client):
    r = client.post("/analyze/abn", json={"company_abn": VALID_ABN})
    assert r.status_code == 401


def test_job_poll_requires_api_key(client):
    r = client.get("/jobs/whatever")
    assert r.status_code == 401


def test_plaintext_api_key_never_persisted():
    """Only the salted SHA-256 hash is stored, never the raw key."""
    db = SessionLocal()
    try:
        row = db.query(ApiKey).first()
        assert row is not None
        assert ACME_KEY not in row.key_hash
        assert row.key_hash == hashlib.sha256(
            (ACME_KEY + "test-salt").encode("utf-8")
        ).hexdigest()
    finally:
        db.close()


# ──────────────────────────────────────────────────────────────────────────────
# TENANT AUTHORIZATION (S3 key ownership + job scoping)
# ──────────────────────────────────────────────────────────────────────────────

def test_cross_tenant_s3_key_forbidden(client):
    r = client.post(
        "/analyze/abn/async",
        json={
            "company_abn": VALID_ABN,
            "pre_uploaded_s3_key": "big-bank/uploads/doc.pdf",
        },
        headers=_headers(ACME_KEY),
    )
    assert r.status_code == 403


def test_s3_key_missing_tenant_prefix_forbidden(client):
    r = client.post(
        "/analyze/abn/async",
        json={
            "company_abn": VALID_ABN,
            "pre_uploaded_s3_key": "client_uploads/doc.pdf",
        },
        headers=_headers(ACME_KEY),
    )
    assert r.status_code == 403


def test_tenant_own_s3_key_accepted(client):
    with patch("api.run_pipeline", return_value="memo"):
        r = client.post(
            "/analyze/abn/async",
            json={
                "company_abn": VALID_ABN,
                "pre_uploaded_s3_key": "acme-corp/uploads/doc.pdf",
            },
            headers=_headers(ACME_KEY),
        )
    assert r.status_code == 202


def test_job_polling_is_tenant_scoped(client):
    db = SessionLocal()
    try:
        acme = db.query(Tenant).filter(Tenant.name == "acme-corp").one()
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        db.add(AnalysisJob(run_id=job_id, tenant_id=acme.id, abn=VALID_ABN, status="queued"))
        db.commit()
    finally:
        db.close()

    # Owner sees the job; another tenant gets 404 (no data leaked).
    assert client.get(f"/jobs/{job_id}", headers=_headers(ACME_KEY)).status_code == 200
    assert client.get(f"/jobs/{job_id}", headers=_headers(BANK_KEY)).status_code == 404


def test_seeded_tenants_from_env(client):
    db = SessionLocal()
    try:
        names = [t.name for t in db.query(Tenant).all()]
        assert "acme-corp" in names
        assert "big-bank" in names
    finally:
        db.close()


# ──────────────────────────────────────────────────────────────────────────────
# BLOCKED-OUTCOME PROPAGATION (incomplete screening)
# ──────────────────────────────────────────────────────────────────────────────

def test_sync_reports_blocked_status(client):
    with patch("api.run_pipeline", return_value=BLOCKED_PREFIX + "\nneeds a human"):
        r = client.post(
            "/analyze/abn",
            json={"company_abn": VALID_ABN},
            headers=_headers(ACME_KEY),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "blocked"
    assert body["compliance_memo"].startswith(BLOCKED_PREFIX)


def test_async_worker_marks_blocked_and_completed(client):
    # First job completes normally.
    with patch("api.run_pipeline", return_value="NORMAL MEMO"):
        r1 = client.post(
            "/analyze/abn/async",
            json={"company_abn": VALID_ABN},
            headers=_headers(ACME_KEY),
        )
    assert r1.status_code == 202
    job_ok_id = r1.json()["job_id"]
    resp = client.get(f"/jobs/{job_ok_id}", headers=_headers(ACME_KEY))
    assert resp.json()["status"] == "completed"

    # Second job is blocked (incomplete screening).
    with patch("api.run_pipeline", return_value=BLOCKED_PREFIX + "\nmanual review"):
        r2 = client.post(
            "/analyze/abn/async",
            json={"company_abn": VALID_ABN},
            headers=_headers(ACME_KEY),
        )
    assert r2.status_code == 202
    job_blocked_id = r2.json()["job_id"]
    resp = client.get(f"/jobs/{job_blocked_id}", headers=_headers(ACME_KEY))
    body = resp.json()
    assert body["status"] == "blocked"
    assert body["compliance_memo"].startswith(BLOCKED_PREFIX)