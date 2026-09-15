import hashlib
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv(override=True)

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Request
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.orm import Session

from aml_pipeline import run_pipeline, BLOCKED_PREFIX
from database import get_db, SessionLocal
from models import AnalysisJob, ApiKey, Tenant

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aml_api")


# ─────────────────────────────────────────
# SECURITY REVIEW — API key authentication
# ─────────────────────────────────────────
# Keys are stored as salted SHA-256 hashes; the plaintext is never persisted.
# Rotate by issuing a new key and deactivating the old one.
_API_KEY_SALT = os.environ.get("API_KEY_SALT", "sovereign-aml-dev-salt")


def _hash_api_key(key: str) -> str:
    return hashlib.sha256((key + _API_KEY_SALT).encode("utf-8")).hexdigest()


def seed_api_keys_from_env(db: Session) -> int:
    """
    Idempotently seeds tenants + API keys from SEED_API_KEYS="tenant:key[,tenant:key]".
    Only creates rows that do not already exist; never rotates existing keys.
    """
    raw = os.environ.get("SEED_API_KEYS", "")
    created = 0
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        tenant_name, sep, key = chunk.partition(":")
        if not sep or not tenant_name.strip() or not key.strip():
            log.warning(f"API key seeding: skipping malformed entry {chunk!r}")
            continue
        tenant_name = tenant_name.strip()
        key = key.strip()
        tenant = db.query(Tenant).filter(Tenant.name == tenant_name).first()
        if tenant is None:
            tenant = Tenant(name=tenant_name)
            db.add(tenant)
            db.flush()
        key_hash = _hash_api_key(key)
        existing = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
        if existing is None:
            db.add(ApiKey(
                tenant_id=tenant.id,
                key_hash=key_hash,
                key_prefix=key_hash[:8],
                is_active=True,
            ))
            created += 1
    db.commit()
    return created


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Seed API keys from environment at startup (best-effort)."""
    try:
        db = SessionLocal()
        try:
            n = seed_api_keys_from_env(db)
            if n:
                log.info(f"API key seeding: created {n} new key(s) from SEED_API_KEYS")
        finally:
            db.close()
    except Exception as exc:
        log.warning(f"API key seeding skipped ({exc}); log in via SEED_API_KEYS once the schema exists.")
    yield


app = FastAPI(
    title="Sovereign AML Engine API",
    description=(
        "Automated AI-driven AML/KYC screening pipeline for complex trust "
        "structures.  Supports both synchronous (blocking) and asynchronous "
        "(job-queue) modes."
    ),
    version="1.2.0",
    lifespan=lifespan,
)


def get_current_tenant(request: Request, db: Session = Depends(get_db)) -> Tenant:
    """
    SECURITY REVIEW — API-key authentication / tenant authorization.
    Every data-touching endpoint requires a valid X-Api-Key header; the key maps
    to exactly one tenant, and callers may only touch resources under that tenant.
    /health is deliberately unauthenticated (ALB liveness probe).
    """
    auth_header = request.headers.get("X-Api-Key")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Missing X-Api-Key header")
    key_hash = _hash_api_key(auth_header)
    key_row = (
        db.query(ApiKey)
        .filter(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
        .first()
    )
    if key_row is None:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    tenant = db.query(Tenant).filter(Tenant.id == key_row.tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=401, detail="API key tenant not found")
    return tenant


def assert_s3_key_owned(tenant: Tenant, s3_key: Optional[str]) -> None:
    """
    SECURITY REVIEW — tenants may only reference documents under their own S3
    prefix. Blocks the arbitrary-S3-key injection the review flagged: a caller
    can no longer point at another tenant's deed (or any other bucket key).
    """
    if s3_key and not s3_key.startswith(f"{tenant.name}/"):
        raise HTTPException(
            status_code=403,
            detail=f"pre_uploaded_s3_key must fall under your tenant prefix ('{tenant.name}/')",
        )


# ---------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------

class AnalyzeRequest(BaseModel):
    company_abn: str = Field(
        ...,
        description="The 11-digit ABN of the entity to analyze",
        example="51824753556",
    )
    pre_uploaded_s3_key: Optional[str] = Field(
        default=None,
        description=(
            "Optional: If the client already uploaded the PDF to S3 (Path A). "
            "Must be prefixed with your tenant name (e.g. 'acme-corp/...')."
        ),
        example="acme-corp/client_uploads/51824753556_trust_deed.pdf",
    )


class AnalyzeResponse(BaseModel):
    status: str
    abn: str
    compliance_memo: str


class AsyncAnalyzeResponse(BaseModel):
    job_id: str
    status: str
    message: str = "Job queued; poll GET /jobs/{job_id} for progress."


class JobStatusResponse(BaseModel):
    job_id: str
    abn: str
    status: str
    compliance_memo: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


# ---------------------------------------------------------
# Background worker (runs after the 202 response is sent)
# ---------------------------------------------------------

def _run_worker(job_id: str, abn: str, s3_key: str | None) -> None:
    """
    Execute the full 4-agent pipeline inside a background thread.
    The job status is updated in the database after completion or failure.

    AWS topology: in production this same function is invoked by an SQS-backed
    Fargate worker (the CDK stack can be extended with an SQS queue + ECS
    task definition referencing the same Docker image).
    """
    db = SessionLocal()
    try:
        job = db.query(AnalysisJob).filter(AnalysisJob.run_id == job_id).first()
        if job is None:
            log.error(f"Background worker: job {job_id} not found in DB")
            return
        job.status = "running"
        db.commit()

        memo = run_pipeline(
            company_abn=abn,
            pre_uploaded_s3_key=s3_key,
            max_retries=2,
            db=db,
        )
        job.compliance_memo = memo
        # SECURITY REVIEW: an incomplete screen is an explicit BLOCKED outcome,
        # not a normal completed memo.
        if memo.startswith(BLOCKED_PREFIX):
            job.status = "blocked"
        else:
            job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        log.info(f"Background worker: job {job_id} completed (status={job.status})")

    except Exception as exc:
        log.exception(f"Background worker: job {job_id} failed")
        db.rollback()
        try:
            job = db.query(AnalysisJob).filter(AnalysisJob.run_id == job_id).first()
            if job is not None:
                job.error = str(exc)
                job.status = "failed"
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            log.exception(f"Background worker: failed to update job {job_id} status")
    finally:
        db.close()


# ---------------------------------------------------------
# Endpoints
# ---------------------------------------------------------

@app.get("/health", tags=["System"])
def health_check():
    """ALB / Kubernetes liveness probe."""
    return {"status": "ok", "environment": os.environ.get("ENV", "development")}


@app.post(
    "/analyze/abn",
    response_model=AnalyzeResponse,
    tags=["Screening"],
    summary="Synchronous screening (20-40 s block)",
)
def analyze_entity(
    request: AnalyzeRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Triggers the 4-Agent pipeline and blocks until the compliance memo is ready."""
    log.info(f"API Request received for ABN: {request.company_abn} (tenant={tenant.name})")
    assert_s3_key_owned(tenant, request.pre_uploaded_s3_key)

    try:
        report_markdown = run_pipeline(
            company_abn=request.company_abn,
            pre_uploaded_s3_key=request.pre_uploaded_s3_key,
            max_retries=2,
            db=db,
        )
        # SECURITY REVIEW: surface the blocked/manual-review outcome explicitly.
        if report_markdown.startswith(BLOCKED_PREFIX):
            response_status = "blocked"
        else:
            response_status = "success"
        return AnalyzeResponse(
            status=response_status,
            abn=request.company_abn,
            compliance_memo=report_markdown,
        )
    except ValueError as e:
        log.warning(f"Validation Error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Pipeline Execution Failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error during pipeline execution.")


@app.post(
    "/analyze/abn/async",
    response_model=AsyncAnalyzeResponse,
    status_code=202,
    tags=["Screening"],
    summary="Async screening — returns immediately (poll /jobs/{job_id})",
)
def analyze_entity_async(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    tenant: Tenant = Depends(get_current_tenant),
):
    """
    Queues the 4-Agent pipeline as a background job and returns immediately
    with a ``job_id``.  Poll ``GET /jobs/{job_id}`` for progress and the
    final compliance memo.
    """
    log.info(f"Async job request for ABN: {request.company_abn} (tenant={tenant.name})")
    assert_s3_key_owned(tenant, request.pre_uploaded_s3_key)
    job_id = uuid.uuid4().hex

    db = SessionLocal()
    try:
        job = AnalysisJob(
            run_id=job_id,
            tenant_id=tenant.id,
            abn=request.company_abn,
            status="queued",
        )
        db.add(job)
        db.commit()
    finally:
        db.close()

    background_tasks.add_task(_run_worker, job_id, request.company_abn, request.pre_uploaded_s3_key)

    return AsyncAnalyzeResponse(job_id=job_id, status="queued")


@app.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    tags=["Screening"],
    summary="Poll an async job's status and result",
)
def get_job(
    job_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    # SECURITY REVIEW: a tenant may only poll its OWN jobs.
    job = (
        db.query(AnalysisJob)
        .filter(AnalysisJob.run_id == job_id, AnalysisJob.tenant_id == tenant.id)
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(
        job_id=job.run_id,
        abn=job.abn,
        status=job.status,
        compliance_memo=job.compliance_memo,
        error=job.error,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )
