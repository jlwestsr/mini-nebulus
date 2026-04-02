"""Mission brief generator — creates MISSION_BRIEF.md for worker execution.

Generates structured markdown briefs that communicate task objectives,
constraints, and verification criteria to autonomous workers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nebulus_swarm.overlord.dispatcher import DispatchContext

logger = logging.getLogger(__name__)

BRIEF_FILENAME = "MISSION_BRIEF.md"

_BRIEF_TEMPLATE = """\
## Return Block (MANDATORY)
End your output with exactly this block, filling in the fields:

---NEBULUS-RETURN---
STATUS: complete|needs_review|needs_fix|blocked|error
SUMMARY: Brief description of what was accomplished
FILES_CREATED: file1.py, file2.py
FILES_MODIFIED: file3.py
TESTS_PASSED: 12/12
TESTS_FAILED: 0
BLOCKERS: None
NEXT_ACTION: merge|review|fix|escalate
---END-NEBULUS-RETURN---

# MISSION BRIEF — {title}

## Objective
{objective}

## Task Metadata
- **Task ID**: {task_id}
- **Project**: {project}
- **Priority**: {priority}
- **Complexity**: {complexity}

## Project Context
- **Repository**: {remote}
- **Role**: {role}
- **Dependencies**: {dependencies}

## Constraints
- Do NOT merge any branch into `develop` or `main`
- Do NOT run `git push` to any remote
- Work ONLY within this worktree: {worktree_path}
- Run all tests before marking complete
- Do NOT modify files outside the project scope

## Verification
- [ ] All existing tests pass: `pytest tests/ -v`
- [ ] New code has test coverage
- [ ] No lint errors: `ruff check .`
- [ ] Changes are committed to a feature branch
"""

_PM_ROLE_SECTION = """\

## Role: Project Manager
Prioritize: sequencing, dependency analysis, risk assessment, business alignment.
Deprioritize: code generation, implementation details, file-level changes.
"""


def generate_mission_brief(ctx: DispatchContext) -> Path:
    """Generate and write MISSION_BRIEF.md to the worktree root.

    Args:
        ctx: Dispatch context containing task, project config, and worktree path.

    Returns:
        Path to the written MISSION_BRIEF.md file.

    Raises:
        ValueError: If worktree_path is not set on the context.
    """
    if not ctx.worktree_path:
        raise ValueError("worktree_path must be set before generating a brief")

    task = ctx.task
    pc = ctx.project_config

    content = _BRIEF_TEMPLATE.format(
        title=task.title,
        objective=task.description or task.title,
        task_id=task.id[:8],
        project=task.project,
        priority=task.priority,
        complexity=task.complexity,
        remote=pc.remote,
        role=pc.role,
        dependencies=", ".join(pc.depends_on) if pc.depends_on else "none",
        worktree_path=ctx.worktree_path,
    )

    # Append PM role section when role is "pm"
    role = getattr(ctx, "role", None)
    if role == "pm":
        content += _PM_ROLE_SECTION

    # Append focus context if provided
    # Append fix context if provided
    fix_context = getattr(ctx, "fix_context", None)
    if fix_context:
        content += f"\n## FIX ATTEMPT {fix_context.attempt}\n"
        content += f"**Previous Review Feedback:** {fix_context.review_feedback}\n"
        content += (
            f"**Previous Output Snippet:** {fix_context.previous_output[:1000]}...\n"
        )

    focus_context = getattr(ctx, "focus_context", None)
    if focus_context:
        content += f"\n## Ecosystem Context\n{focus_context}\n"

    brief_path = ctx.worktree_path / BRIEF_FILENAME
    brief_path.write_text(content)
    logger.info("Wrote mission brief: %s", brief_path)
    return brief_path


def build_worker_prompt(brief_path: Path) -> str:
    """Read the brief and wrap it as a worker prompt.

    Args:
        brief_path: Path to the MISSION_BRIEF.md file.

    Returns:
        Prompt string for the worker.
    """
    return (
        f"Read MISSION_BRIEF.md in this directory and execute the task "
        f"described within. The brief is located at: {brief_path}\n\n"
        f"{brief_path.read_text()}"
    )


def build_review_prompt(brief_path: Path, exec_output: str) -> str:
    """Build a review prompt from brief + execution output.

    Args:
        brief_path: Path to the MISSION_BRIEF.md file.
        exec_output: Output from the execution worker.

    Returns:
        Review prompt string for the reviewer worker.
    """
    brief_content = brief_path.read_text()
    return (
        f"Review the following work against the mission brief.\n\n"
        f"## Mission Brief\n{brief_content}\n\n"
        f"## Execution Output\n{exec_output}\n\n"
        f"## Review Instructions\n"
        f"1. Verify the objective was met\n"
        f"2. Check that all constraints were respected\n"
        f"3. Confirm verification criteria are satisfied\n"
        f"4. Report any issues found\n"
    )
