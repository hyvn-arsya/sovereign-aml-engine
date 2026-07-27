import logging
import os
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional

# Import the core logic from our pipeline
from aml_pipeline import run_pipeline

# Configure basic logging for the API layer
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aml_api")

# Initialize the FastAPI app
app = FastAPI(
    title="Sovereign AML Engine API",
    description="Automated AI-driven AML/KYC screening pipeline for complex trust structures.",
    version="1.0.0"
)

# ---------------------------------------------------------
# Pydantic Schemas for API Requests & Responses
# ---------------------------------------------------------

class AnalyzeRequest(BaseModel):
    company_abn: str = Field(
        ..., 
        description="The 11-digit ABN of the entity to analyze", 
        example="51824753556"
    )
    pre_uploaded_s3_key: Optional[str] = Field(
        default=None,
        description="Optional: If the client already uploaded the PDF to S3 (Path A)",
        example="client_uploads/51824753556_trust_deed.pdf"
    )

class AnalyzeResponse(BaseModel):
    status: str
    abn: str
    compliance_memo: str

# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------

@app.get("/health", tags=["System"])
def health_check():
    """
    Simple health check endpoint used by AWS Application Load Balancers
    to verify the Docker container is running.
    """
    return {"status": "ok", "environment": os.environ.get("ENV", "development")}

@app.post("/analyze/abn", response_model=AnalyzeResponse, tags=["Screening"])
def analyze_entity(request: AnalyzeRequest):
    """
    Synchronous MVP (Option A): Triggers the 4-Agent pipeline and blocks
    until the final compliance memo is generated.
    """
    log.info(f"API Request received for ABN: {request.company_abn}")
    
    try:
        # We call the exact same pipeline function you tested locally!
        # This takes 20-40 seconds, so the HTTP connection remains open.
        report_markdown = run_pipeline(
            company_abn=request.company_abn,
            pre_uploaded_s3_key=request.pre_uploaded_s3_key,
            max_retries=2
        )
        
        return AnalyzeResponse(
            status="success",
            abn=request.company_abn,
            compliance_memo=report_markdown
        )
        
    except ValueError as e:
        # e.g., Invalid ABN Checksum
        log.warning(f"Validation Error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
        
    except Exception as e:
        # Catch-all for API timeouts, S3 failures, etc.
        log.error(f"Pipeline Execution Failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error during pipeline execution.")
