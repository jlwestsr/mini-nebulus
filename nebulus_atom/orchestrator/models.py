"""
Orchestrator data models.

Workflow      - YAML-parsed pipeline definition
WorkflowStep  - Single node in the DAG (agent + prompt template)
Job           - Live execution instance of a Workflow
StepResult    - Output from one executed step
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(Enum):
    PENDING = "pending"
    WAITING = "waiting"  # dependencies not yet satisfied
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkflowStep:
    """Single node in the workflow DAG."""

    id: str
    agent: str  # e.g. "atom", "moto", "cael"
    prompt_template: str  # may reference {{input}} and {{step_id.output}}
    depends_on: List[str] = field(default_factory=list)
    model_hint: Optional[str] = None  # override model routing
    timeout_seconds: int = 300

    def render_prompt(self, context: Dict[str, Any]) -> str:
        """Render prompt template with context variables."""
        rendered = self.prompt_template
        for key, value in context.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
        return rendered


@dataclass
class Workflow:
    """Parsed workflow definition."""

    name: str
    description: str = ""
    steps: List[WorkflowStep] = field(default_factory=list)
    version: str = "1.0"

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return next((s for s in self.steps if s.id == step_id), None)

    def get_ready_steps(self, completed_ids: set) -> List[WorkflowStep]:
        """Return steps whose dependencies are all satisfied."""
        return [
            s
            for s in self.steps
            if s.id not in completed_ids
            and all(dep in completed_ids for dep in s.depends_on)
        ]

    def validate(self) -> List[str]:
        """Validate DAG for cycles and missing dependencies. Returns list of errors."""
        errors = []
        step_ids = {s.id for s in self.steps}

        # Check missing dependency references
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    errors.append(f"Step '{step.id}' depends on unknown step '{dep}'")

        # Check for cycles using DFS
        visited = set()
        rec_stack = set()

        def has_cycle(step_id: str) -> bool:
            visited.add(step_id)
            rec_stack.add(step_id)
            step = self.get_step(step_id)
            if step:
                for dep in step.depends_on:
                    if dep not in visited:
                        if has_cycle(dep):
                            return True
                    elif dep in rec_stack:
                        return True
            rec_stack.discard(step_id)
            return False

        for step in self.steps:
            if step.id not in visited:
                if has_cycle(step.id):
                    errors.append("Cycle detected in workflow DAG")
                    break

        return errors


@dataclass
class StepResult:
    """Output from a single executed step."""

    step_id: str
    status: StepStatus = StepStatus.PENDING
    output: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    model_used: Optional[str] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


@dataclass
class Job:
    """Live execution instance of a workflow."""

    workflow_name: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: JobStatus = JobStatus.PENDING
    inputs: Dict[str, Any] = field(default_factory=dict)
    step_results: Dict[str, StepResult] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    def get_context(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Build template context from inputs + completed step outputs."""
        context = dict(inputs)
        context["input"] = context.get("goal", "")  # convenience alias
        for step_id, result in self.step_results.items():
            if result.status == StepStatus.COMPLETED and result.output:
                context[step_id] = result.output
                context[f"{step_id}.output"] = result.output
        return context

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workflow": self.workflow_name,
            "status": self.status.value,
            "inputs": self.inputs,
            "steps": {
                sid: {
                    "status": r.status.value,
                    "output": r.output,
                    "error": r.error,
                    "duration_seconds": r.duration_seconds,
                    "model_used": r.model_used,
                }
                for sid, r in self.step_results.items()
            },
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
            "error": self.error,
        }
