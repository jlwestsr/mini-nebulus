"""
WorkflowEngine — core DAG execution engine.

Responsibilities:
  - Accept workflow + inputs → return Job
  - Execute steps in topological order, parallelizing where possible
  - Propagate outputs as context for downstream steps
  - Persist job state to SQLite
  - Provide job status polling
"""

from __future__ import annotations

import asyncio
import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from nebulus_atom.utils.logger import setup_logger
from .models import Workflow, Job, JobStatus, StepResult, StepStatus
from .executor import StepExecutor
from .router import ModelRouter

logger = setup_logger(__name__)

DEFAULT_DB_PATH = Path.home() / ".nebulus_atom" / "orchestrator.db"


class WorkflowEngine:
    """
    Async workflow execution engine.

    Usage:
        engine = WorkflowEngine(openai_service)
        job = await engine.submit(workflow, inputs={"goal": "build a REST API"})
        status = engine.get_job(job.id)
    """

    def __init__(
        self,
        openai_service,
        db_path: Optional[Path] = None,
        model_router: Optional[ModelRouter] = None,
    ):
        self._openai = openai_service
        self._db_path = db_path or DEFAULT_DB_PATH
        self._router = model_router or ModelRouter()
        self._executor = StepExecutor(openai_service, self._router)
        self._jobs: Dict[str, Job] = {}
        self._ensure_db()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def submit(
        self,
        workflow: Workflow,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> Job:
        """
        Submit a workflow for execution.

        Args:
            workflow: Parsed workflow definition
            inputs: Initial context variables (e.g. {"goal": "..."})

        Returns:
            Job instance (execution starts immediately)
        """
        job = Job(
            workflow_name=workflow.name,
            inputs=inputs or {},
        )
        self._jobs[job.id] = job
        self._persist_job(job)

        logger.info(f"Submitted job {job.id} for workflow '{workflow.name}'")

        # Run async without blocking caller
        asyncio.create_task(self._execute(workflow, job))

        return job

    async def submit_and_wait(
        self,
        workflow: Workflow,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> Job:
        """Submit and block until the job completes."""
        job = Job(
            workflow_name=workflow.name,
            inputs=inputs or {},
        )
        self._jobs[job.id] = job
        self._persist_job(job)
        await self._execute(workflow, job)
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID (from memory or DB)."""
        if job_id in self._jobs:
            return self._jobs[job_id]
        return self._load_job(job_id)

    def list_jobs(self, limit: int = 20) -> List[Job]:
        """List recent jobs from DB."""
        return self._load_recent_jobs(limit)

    # -------------------------------------------------------------------------
    # Execution
    # -------------------------------------------------------------------------

    async def _execute(self, workflow: Workflow, job: Job) -> None:
        """Execute a workflow DAG, parallelizing independent steps."""
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        self._persist_job(job)

        completed_ids: set = set()
        failed = False

        try:
            while True:
                # Find steps ready to run (deps satisfied, not yet run)
                ready = workflow.get_ready_steps(completed_ids)
                remaining = [s for s in workflow.steps if s.id not in completed_ids]

                if not remaining:
                    # All steps complete
                    break

                if not ready and remaining:
                    # Deadlock — shouldn't happen if validation passed
                    job.error = "Workflow deadlock: no ready steps but work remains"
                    failed = True
                    break

                if not ready:
                    break

                # Run all ready steps in parallel
                context = job.get_context(job.inputs)
                logger.info(
                    f"Job {job.id}: running {len(ready)} step(s) in parallel: "
                    f"{[s.id for s in ready]}"
                )

                tasks = [self._executor.execute(step, context) for step in ready]
                results: List[StepResult] = await asyncio.gather(
                    *tasks, return_exceptions=True
                )

                for step, result in zip(ready, results):
                    if isinstance(result, Exception):
                        result = StepResult(
                            step_id=step.id,
                            status=StepStatus.FAILED,
                            error=str(result),
                            started_at=datetime.utcnow(),
                            completed_at=datetime.utcnow(),
                        )

                    job.step_results[step.id] = result
                    completed_ids.add(step.id)
                    self._persist_job(job)

                    if result.status == StepStatus.FAILED:
                        logger.error(
                            f"Job {job.id}: step '{step.id}' failed: {result.error}"
                        )
                        failed = True

                if failed:
                    # Mark remaining steps as skipped
                    for step in workflow.steps:
                        if step.id not in job.step_results:
                            job.step_results[step.id] = StepResult(
                                step_id=step.id,
                                status=StepStatus.SKIPPED,
                            )
                    break

            job.status = JobStatus.FAILED if failed else JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()

            logger.info(
                f"Job {job.id} {job.status.value} "
                f"in {(job.completed_at - job.started_at).total_seconds():.1f}s"
            )

        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.utcnow()
            logger.error(f"Job {job.id} crashed: {e}")

        finally:
            self._persist_job(job)

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    def _ensure_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    workflow_name TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    @contextmanager
    def _get_db(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _persist_job(self, job: Job) -> None:
        now = datetime.utcnow().isoformat()
        with self._get_db() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, workflow_name, data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
                """,
                (job.id, job.workflow_name, json.dumps(job.to_dict()), now, now),
            )

    def _load_job(self, job_id: str) -> Optional[Job]:
        with self._get_db() as conn:
            row = conn.execute(
                "SELECT data FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if not row:
            return None
        return self._job_from_dict(json.loads(row["data"]))

    def _load_recent_jobs(self, limit: int) -> List[Job]:
        with self._get_db() as conn:
            rows = conn.execute(
                "SELECT data FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._job_from_dict(json.loads(r["data"])) for r in rows]

    def _job_from_dict(self, data: dict) -> Job:
        """Reconstruct Job from serialized dict."""
        from .models import StepResult, StepStatus

        job = Job(
            workflow_name=data["workflow"],
            id=data["id"],
            status=JobStatus(data["status"]),
            inputs=data.get("inputs", {}),
        )
        if data.get("created_at"):
            job.created_at = datetime.fromisoformat(data["created_at"])
        if data.get("started_at"):
            job.started_at = datetime.fromisoformat(data["started_at"])
        if data.get("completed_at"):
            job.completed_at = datetime.fromisoformat(data["completed_at"])
        job.error = data.get("error")

        for step_id, step_data in data.get("steps", {}).items():
            job.step_results[step_id] = StepResult(
                step_id=step_id,
                status=StepStatus(step_data["status"]),
                output=step_data.get("output"),
                error=step_data.get("error"),
                model_used=step_data.get("model_used"),
            )

        return job
