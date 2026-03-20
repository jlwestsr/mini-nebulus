"""
Nebulus Atom Orchestrator
=========================
Native workflow engine for DAG-based task execution with async parallelism,
context propagation, and model routing.

Usage:
    from nebulus_atom.orchestrator import WorkflowEngine
    from nebulus_atom.orchestrator.loader import load_workflow

    engine = WorkflowEngine(config)
    workflow = load_workflow("build-feature.yml")
    job = await engine.submit(workflow, inputs={"goal": "build a REST API"})
"""

from .engine import WorkflowEngine
from .models import Workflow, WorkflowStep, Job, JobStatus, StepResult

__all__ = [
    "WorkflowEngine",
    "Workflow",
    "WorkflowStep",
    "Job",
    "JobStatus",
    "StepResult",
]
