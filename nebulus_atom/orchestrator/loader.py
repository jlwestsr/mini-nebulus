"""
Workflow loader — parses YAML workflow definitions into Workflow objects.

YAML Format:
------------
name: build-feature
description: Build a feature from a goal statement
version: "1.0"

steps:
  - id: plan
    agent: atom
    prompt: |
      Create a detailed implementation plan for: {{input}}
      Include: architecture decisions, file list, key interfaces.

  - id: tests
    agent: atom
    depends_on: [plan]
    prompt: |
      Write failing pytest tests based on this plan:
      {{plan}}

  - id: implement
    agent: atom
    depends_on: [tests]
    model_hint: "large"
    prompt: |
      Implement code to pass these tests:
      {{tests}}

  - id: review
    agent: atom
    depends_on: [implement]
    prompt: |
      Review this implementation for quality and correctness:
      {{implement}}
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import yaml

from .models import Workflow, WorkflowStep


TEMPLATES_DIR = Path(__file__).parent / "templates"


def load_workflow(source: Union[str, Path]) -> Workflow:
    """
    Load a workflow from a YAML file or name.

    Args:
        source: Path to YAML file, or template name (without .yml)

    Returns:
        Parsed Workflow object

    Raises:
        FileNotFoundError: If source not found
        ValueError: If YAML is invalid or workflow fails validation
    """
    path = _resolve_path(source)

    with open(path) as f:
        data = yaml.safe_load(f)

    return _parse_workflow(data)


def load_workflow_from_string(yaml_content: str) -> Workflow:
    """Load a workflow from a YAML string."""
    data = yaml.safe_load(yaml_content)
    return _parse_workflow(data)


def list_templates() -> list[str]:
    """Return names of available built-in workflow templates."""
    if not TEMPLATES_DIR.exists():
        return []
    return [p.stem for p in TEMPLATES_DIR.glob("*.yml")]


def _resolve_path(source: Union[str, Path]) -> Path:
    path = Path(source)

    # Direct path
    if path.exists():
        return path

    # Template by name
    template_path = TEMPLATES_DIR / f"{source}.yml"
    if template_path.exists():
        return template_path

    raise FileNotFoundError(
        f"Workflow not found: '{source}'. Available templates: {list_templates()}"
    )


def _parse_workflow(data: dict) -> Workflow:
    if not isinstance(data, dict):
        raise ValueError("Workflow YAML must be a mapping")

    if "name" not in data:
        raise ValueError("Workflow must have a 'name' field")

    if "steps" not in data or not data["steps"]:
        raise ValueError("Workflow must have at least one step")

    steps = []
    for raw_step in data["steps"]:
        step = WorkflowStep(
            id=str(raw_step["id"]),
            agent=raw_step.get("agent", "atom"),
            prompt_template=raw_step.get("prompt", raw_step.get("prompt_template", "")),
            depends_on=[str(d) for d in raw_step.get("depends_on", [])],
            model_hint=raw_step.get("model_hint"),
            timeout_seconds=int(raw_step.get("timeout_seconds", 300)),
        )
        steps.append(step)

    workflow = Workflow(
        name=data["name"],
        description=data.get("description", ""),
        steps=steps,
        version=str(data.get("version", "1.0")),
    )

    errors = workflow.validate()
    if errors:
        raise ValueError(f"Invalid workflow: {'; '.join(errors)}")

    return workflow
