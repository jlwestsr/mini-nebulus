"""
Orchestrator REST API — FastAPI router for workflow job management.

Endpoints:
  POST   /orchestrator/jobs              Submit a job
  GET    /orchestrator/jobs              List recent jobs
  GET    /orchestrator/jobs/{id}         Get job status
  GET    /orchestrator/templates         List available templates
  DELETE /orchestrator/jobs/{id}         Cancel a job (if running)

Designed to be mounted on the existing Atom web server.
Also usable standalone: uvicorn nebulus_atom.orchestrator.api:app
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from nebulus_atom.utils.logger import setup_logger
from .engine import WorkflowEngine
from .loader import load_workflow, load_workflow_from_string, list_templates
from .models import JobStatus

logger = setup_logger(__name__)

# Engine singleton — injected at startup
_engine: Optional[WorkflowEngine] = None


def get_engine() -> WorkflowEngine:
    if _engine is None:
        raise RuntimeError("WorkflowEngine not initialized. Call init_engine() first.")
    return _engine


def init_engine(engine: WorkflowEngine) -> None:
    global _engine
    _engine = engine


router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])


# -------------------------------------------------------------------------
# Request/Response schemas
# -------------------------------------------------------------------------


class JobSubmitRequest(BaseModel):
    template: Optional[str] = None  # Built-in template name
    workflow_yaml: Optional[str] = None  # Inline YAML definition
    inputs: Dict[str, Any] = {}

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "template": "build-feature",
                    "inputs": {"goal": "Add JWT authentication to the FastAPI backend"},
                },
                {
                    "template": "fix-bug",
                    "inputs": {
                        "goal": "Login endpoint returns 500 when email contains special chars"
                    },
                },
            ]
        }


class StepResultResponse(BaseModel):
    status: str
    output: Optional[str]
    error: Optional[str]
    duration_seconds: Optional[float]
    model_used: Optional[str]


class JobResponse(BaseModel):
    id: str
    workflow: str
    status: str
    inputs: Dict[str, Any]
    steps: Dict[str, StepResultResponse]
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    error: Optional[str]


class TemplateInfo(BaseModel):
    name: str
    description: str
    steps: List[str]


# -------------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------------


@router.post("/jobs", response_model=JobResponse, status_code=202)
async def submit_job(request: JobSubmitRequest, background_tasks: BackgroundTasks):
    """Submit a workflow job for execution."""
    engine = get_engine()

    if not request.template and not request.workflow_yaml:
        raise HTTPException(400, "Provide either 'template' or 'workflow_yaml'")

    try:
        if request.workflow_yaml:
            workflow = load_workflow_from_string(request.workflow_yaml)
        else:
            workflow = load_workflow(request.template)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

    job = await engine.submit(workflow, inputs=request.inputs)
    return _job_to_response(job)


@router.get("/jobs", response_model=List[JobResponse])
def list_jobs(limit: int = 20):
    """List recent jobs."""
    engine = get_engine()
    jobs = engine.list_jobs(limit=limit)
    return [_job_to_response(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str):
    """Get job status and results."""
    engine = get_engine()
    job = engine.get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found")
    return _job_to_response(job)


@router.get("/templates", response_model=List[TemplateInfo])
def get_templates():
    """List available built-in workflow templates."""
    templates = []
    for name in list_templates():
        try:
            wf = load_workflow(name)
            templates.append(
                TemplateInfo(
                    name=name,
                    description=wf.description,
                    steps=[s.id for s in wf.steps],
                )
            )
        except Exception:
            pass
    return templates


@router.delete("/jobs/{job_id}", status_code=204)
def cancel_job(job_id: str):
    """Cancel a running job (best-effort)."""
    engine = get_engine()
    job = engine.get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found")
    if job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
        raise HTTPException(409, f"Job is already {job.status.value}")
    # Mark as cancelled — running tasks will complete current step then stop
    job.status = JobStatus.CANCELLED
    engine._persist_job(job)


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def _job_to_response(job) -> JobResponse:
    d = job.to_dict()
    return JobResponse(
        id=d["id"],
        workflow=d["workflow"],
        status=d["status"],
        inputs=d["inputs"],
        steps={
            sid: StepResultResponse(
                status=s["status"],
                output=s.get("output"),
                error=s.get("error"),
                duration_seconds=s.get("duration_seconds"),
                model_used=s.get("model_used"),
            )
            for sid, s in d["steps"].items()
        },
        created_at=d["created_at"],
        started_at=d.get("started_at"),
        completed_at=d.get("completed_at"),
        error=d.get("error"),
    )
