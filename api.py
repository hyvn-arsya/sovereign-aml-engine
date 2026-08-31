import logging
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv(override=True)

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.orm import Session

from aml_pipeline import run_pipeline
from database import get_db, SessionLocal
from models import AnalysisJob

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aml_api")

app = FastAPI(
    title="Sovereign AML Engine API",
    description=(
        "Automated AI-driven AML/KYC screening pipeline for complex trust "
        "structures.  Supports both synchronous (blocking) and asynchronous "
        "(job-queue) modes."
    ),
    version="1.1.0",
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
        description="Optional: If the client already uploaded the PDF to S3 (Path A)",
        example="client_uploads/51824753556_trust_deed.pdf",
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
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        log.info(f"Background worker: job {job_id} completed")

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
def analyze_entity(request: AnalyzeRequest, db: Session = Depends(get_db)):
    """Triggers the 4-Agent pipeline and blocks until the compliance memo is ready."""
    log.info(f"API Request received for ABN: {request.company_abn}")

    try:
        report_markdown = run_pipeline(
            company_abn=request.company_abn,
            pre_uploaded_s3_key=request.pre_uploaded_s3_key,
            max_retries=2,
            db=db,
        )
        return AnalyzeResponse(
            status="success",
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
):
    """
    Queues the 4-Agent pipeline as a background job and returns immediately
    with a ``job_id``.  Poll ``GET /jobs/{job_id}`` for progress and the
    final compliance memo.
    """
    log.info(f"Async job request for ABN: {request.company_abn}")
    job_id = uuid.uuid4().hex

    db = SessionLocal()
    try:
        job = AnalysisJob(run_id=job_id, abn=request.company_abn, status="queued")
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
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(AnalysisJob).filter(AnalysisJob.run_id == job_id).first()
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
