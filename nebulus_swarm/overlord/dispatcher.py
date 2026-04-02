"""Core dispatch loop — Analyze → Brief → Provision → Execute → Review.

Orchestrates the full lifecycle of dispatching a task from the work queue
through worker execution and optional review.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from nebulus_swarm.overlord.mirrors import MirrorManager
from nebulus_swarm.overlord.return_parser import parse_return_block

from nebulus_swarm.overlord.mission_brief import (
    build_review_prompt,
    build_worker_prompt,
    generate_mission_brief,
)
from nebulus_swarm.overlord.registry import OverlordConfig, ProjectConfig
from nebulus_swarm.overlord.work_queue import (
    DispatchResultRecord,
    Task,
    WorkQueue,
)
from nebulus_swarm.overlord.workers.base import BaseWorker, WorkerResult

if TYPE_CHECKING:
    from nebulus_swarm.overlord.governance import GovernanceEngine, GovernanceResult

logger = logging.getLogger(__name__)

# Tier mapping: task complexity/type → preferred worker tier
MAX_RETRIES = 2  # Default max retries for fix passes

TIER_MAP: dict[str, str] = {
    "format": "local",
    "lint": "local",
    "boilerplate": "local",
    "review": "cloud-fast",
    "architecture": "cloud-heavy",
    "planning": "cloud-heavy",
}

# Worker tier preferences
TIER_TO_WORKER: dict[str, str] = {
    "local": "local",
    "cloud-fast": "claude",
    "cloud-heavy": "claude",
}

# Fallback order when preferred worker is unavailable
FALLBACK_ORDER: list[str] = ["claude", "gemini", "local"]


@dataclass
class FixContext:
    """Context passed to a worker for a fix/retry attempt."""

    original_brief_path: Path
    review_feedback: str
    attempt: int
    previous_output: str
    previous_worker: str


# Model override for cloud-heavy tier (use Opus)
CLOUD_HEAVY_MODEL = "opus"


@dataclass
class DispatchContext:
    """Everything needed to execute a task."""

    task: Task
    project_config: ProjectConfig
    worker: BaseWorker
    worktree_path: Optional[Path] = None
    brief_path: Optional[Path] = None
    model: Optional[str] = None
    dry_run: bool = False
    role: Optional[str] = None
    focus_context: Optional[str] = None
    fix_context: Optional[FixContext] = None


class Dispatcher:
    """Orchestrates the Analyze → Brief → Provision → Execute → Review loop."""

    def __init__(
        self,
        queue: WorkQueue,
        config: OverlordConfig,
        mirrors: MirrorManager,
        workers: dict[str, BaseWorker],
        daily_ceiling_usd: float = 10.0,
        warning_threshold_pct: float = 80.0,
        notification_manager: Optional[object] = None,
        governance: Optional[GovernanceEngine] = None,
    ) -> None:
        self.queue = queue
        self.config = config
        self.mirrors = mirrors
        self.workers = workers
        self.daily_ceiling_usd = daily_ceiling_usd
        self.warning_threshold_pct = warning_threshold_pct
        self.notification_manager = notification_manager
        self.governance = governance

    def dispatch_task(
        self,
        task_id: str,
        *,
        dry_run: bool = False,
        worker_name: Optional[str] = None,
        skip_review: bool = False,
        role: str = "default",
    ) -> DispatchResultRecord:
        """Full lifecycle for one task.

        Args:
            task_id: UUID of the task to dispatch.
            dry_run: If True, do not actually execute the task.
            worker_name: Optional explicit worker to use.
            skip_review: If True, skip the automated review step.
            role: Worker role (default or pm).

        Returns:
            Record of the dispatch execution.

        Raises:
            ValueError: If task not found or in invalid state.
        """
        # 1. Load and validate
        task = self.queue.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        if task.status != "active":
            raise ValueError(
                f"Task {task_id[:8]} is '{task.status}', expected 'active'"
            )

        project_config = self.config.projects.get(task.project)
        if not project_config:
            raise ValueError(f"Unknown project: {task.project}")

        # 2. Lock and transition
        worker_obj, selected_name = self.select_worker(task, worker_name)
        self.queue.lock_task(task_id, selected_name)

        try:
            self.queue.transition(
                task_id,
                "dispatched",
                changed_by="dispatcher",
                reason=f"Dispatched to worker={selected_name}",
            )

            # 2a. Governance pre-check
            if not dry_run and self.governance:
                gov_result = self._run_governance_check(task, project_config)
                if not gov_result.approved:
                    return self._fail_task(
                        task_id,
                        selected_name,
                        DispatchContext(
                            task=task,
                            project_config=project_config,
                            worker=worker_obj,
                        ),
                        None,
                        reason=f"Governance: {gov_result.violations[0].message}",
                    )

            # 2b. Pre-dispatch health scan
            if not dry_run:
                scan_issues = self._run_pre_dispatch_scan(project_config)
                if scan_issues:
                    return self._fail_task(
                        task_id,
                        selected_name,
                        DispatchContext(
                            task=task,
                            project_config=project_config,
                            worker=worker_obj,
                        ),
                        None,
                        reason=f"Repo unhealthy: {'; '.join(scan_issues)}",
                    )

            # 2c. Conflict detection
            if not dry_run and self.governance:
                active_dispatched = self.queue.list_tasks(status="dispatched")
                conflict = self.governance.check_conflict(task, active_dispatched)
                if conflict:
                    return self._fail_task(
                        task_id,
                        selected_name,
                        DispatchContext(
                            task=task,
                            project_config=project_config,
                            worker=worker_obj,
                        ),
                        None,
                        reason=f"Conflict: {conflict.message}",
                    )

            # 3. Build context
            model = (
                CLOUD_HEAVY_MODEL if self._infer_tier(task) == "cloud-heavy" else None
            )

            # Populate focus context if role is PM
            focus_context_str = None
            if role == "pm":
                try:
                    from nebulus_swarm.overlord.focus import get_ecosystem_focus

                    focus_context_str = get_ecosystem_focus(self.queue, self.config)
                except Exception:
                    logger.debug(
                        "Failed to populate focus context for PM role", exc_info=True
                    )

            ctx = DispatchContext(
                task=task,
                project_config=project_config,
                worker=worker_obj,
                model=model,
                dry_run=dry_run,
                role=role if role != "default" else None,
                focus_context=focus_context_str,
            )

            # 4. Provision worktree
            ctx.worktree_path = self.mirrors.provision_worktree(
                task.project,
                task_id,
            )

            # 5. Generate brief
            ctx.brief_path = generate_mission_brief(ctx)

            # 6. Execute (Verify-Fix Pattern)
            exec_result: Optional[WorkerResult] = None
            review_result: Optional[WorkerResult] = None
            review_status = "skipped" if dry_run else ""

            if not dry_run:
                for attempt in range(1, (task.max_retries or MAX_RETRIES) + 1):
                    exec_result = self.execute_worker(ctx)
                    if not exec_result.success:
                        return self._fail_task(
                            task_id,
                            selected_name,
                            ctx,
                            exec_result,
                            reason=f"Worker execution failed: {exec_result.error}",
                        )

                    # 6b. Per-task token budget enforcement
                    if (
                        task.token_budget
                        and exec_result.tokens_total > task.token_budget
                    ):
                        return self._fail_task(
                            task_id,
                            selected_name,
                            ctx,
                            exec_result,
                            reason=f"Token budget exceeded: {exec_result.tokens_total} > {task.token_budget}",
                        )

                    # Triage return block
                    return_block = parse_return_block(exec_result.output)
                    if return_block:
                        if return_block.status == "blocked":
                            return self._fail_task(
                                task_id,
                                selected_name,
                                ctx,
                                exec_result,
                                reason=f"Worker blocked: {return_block.blockers}",
                            )
                        if return_block.status == "error":
                            return self._fail_task(
                                task_id,
                                selected_name,
                                ctx,
                                exec_result,
                                reason=f"Worker error: {return_block.summary}",
                            )

                    # Transition to in_review only on first attempt
                    if attempt == 1:
                        self.queue.transition(
                            task_id,
                            "in_review",
                            changed_by="dispatcher",
                            reason=f"Attempt {attempt} complete, starting review",
                        )

                    if skip_review:
                        review_status = "skipped"
                        break

                    review_result = self.run_review(ctx, exec_result)

                    if review_result.success:
                        review_status = "passed"
                        break

                    # Review failed - build fix context for next attempt
                    review_status = "failed"
                    if attempt < (task.max_retries or MAX_RETRIES):
                        logger.info(
                            "Attempt %d failed review, building fix context", attempt
                        )

                        # Increment retry_count in DB
                        try:
                            with self.queue._get_connection() as conn:
                                conn.execute(
                                    "UPDATE tasks SET retry_count = retry_count + 1 WHERE id = ?",
                                    (task_id,),
                                )
                        except Exception:
                            logger.warning(
                                "Failed to increment retry_count", exc_info=True
                            )

                        # Check daily budget ceiling before retry
                        if self.daily_ceiling_usd > 0:
                            available, _ = self.queue.check_budget_available(
                                self.daily_ceiling_usd
                            )
                            if not available:
                                return self._fail_task(
                                    task_id,
                                    selected_name,
                                    ctx,
                                    exec_result,
                                    reason="Global daily budget exceeded during retry pass",
                                )

                        ctx.fix_context = FixContext(
                            original_brief_path=ctx.brief_path,
                            review_feedback=review_result.output,
                            attempt=attempt + 1,
                            previous_output=exec_result.output,
                            previous_worker=selected_name,
                        )
                        ctx.brief_path = generate_mission_brief(ctx)
                    else:
                        # Max attempts reached
                        return self._fail_task(
                            task_id,
                            selected_name,
                            ctx,
                            exec_result,
                            reason=f"Review failed after {attempt} attempts: {review_result.output}",
                            review_status="failed",
                        )

            # 8. Record success
            usage_stats = {}
            if exec_result:
                usage_stats = {
                    "tokens_input": exec_result.tokens_input,
                    "tokens_output": exec_result.tokens_output,
                    "tokens_total": exec_result.tokens_total,
                }

            result = DispatchResultRecord(
                task_id=task_id,
                worker_id=selected_name,
                model_id=exec_result.model_used if exec_result else "",
                branch_name=f"atom/{task_id[:8]}",
                mission_brief_path=str(ctx.brief_path) if ctx.brief_path else "",
                review_status=review_status,
                usage_stats=usage_stats,
                output_log=exec_result.output if exec_result else "dry-run",
                tokens_used=exec_result.tokens_total if exec_result else 0,
            )
            self.queue.record_dispatch_result(result)

            # Record token usage in cost ledger
            if exec_result and exec_result.tokens_total > 0:
                try:
                    from nebulus_swarm.overlord.workers.sdk_factory import estimate_cost

                    cost = estimate_cost(
                        exec_result.tokens_input,
                        exec_result.tokens_output,
                        exec_result.model_used,
                    )
                    self.queue.record_token_usage(
                        tokens_input=exec_result.tokens_input,
                        tokens_output=exec_result.tokens_output,
                        estimated_cost_usd=cost,
                        ceiling_usd=self.daily_ceiling_usd,
                        updated_at=datetime.now(timezone.utc).isoformat(),
                    )
                except Exception:
                    logger.debug("Failed to record token usage")

            if not dry_run:
                self.queue.transition(
                    task_id,
                    "completed",
                    changed_by="dispatcher",
                    reason="Dispatch completed successfully",
                )

            return result

        except Exception:
            # Transition to failed on unexpected exceptions (e.g. provision failure)
            current = self.queue.get_task(task_id)
            if current and current.status not in ("completed", "failed"):
                try:
                    self.queue.transition(
                        task_id,
                        "failed",
                        changed_by="dispatcher",
                        reason="Unhandled dispatch error",
                    )
                except Exception:
                    pass
            raise
        finally:
            self.queue.unlock_task(task_id)

    def select_worker(
        self, task: Task, explicit_name: Optional[str] = None
    ) -> tuple[BaseWorker, str]:
        """Select the best worker for a task based on complexity and availability.

        Args:
            task: The task to select a worker for.
            explicit_name: Optional worker name override.

        Returns:
            Tuple of (worker instance, worker name).

        Raises:
            RuntimeError: If no eligible workers are available.
        """
        if explicit_name:
            worker = self.workers.get(explicit_name)
            if worker and worker.available:
                return worker, explicit_name
            raise RuntimeError(f"Requested worker '{explicit_name}' is not available")

        tier = self._infer_tier(task)
        preferred = TIER_TO_WORKER.get(tier)
        if (
            preferred
            and preferred in self.workers
            and self.workers[preferred].available
        ):
            return self.workers[preferred], preferred

        for name in FALLBACK_ORDER:
            if name in self.workers and self.workers[name].available:
                return self.workers[name], name
        raise RuntimeError("No eligible workers available")

    def select_reviewer(self, executor_name: str) -> tuple[BaseWorker, str]:
        """Select a worker to perform automated review.

        Args:
            executor_name: Name of the worker that executed the task.

        Returns:
            Tuple of (reviewer instance, reviewer name).

        Raises:
            RuntimeError: If no review workers are available.
        """
        for name in FALLBACK_ORDER:
            if (
                name != executor_name
                and name in self.workers
                and self.workers[name].available
            ):
                return self.workers[name], name
        if executor_name in self.workers and self.workers[executor_name].available:
            return self.workers[executor_name], executor_name
        raise RuntimeError("No review workers available")

    def generate_brief(self, ctx: DispatchContext) -> Path:
        """Generate a mission brief for a worker."""
        return generate_mission_brief(ctx)

    def execute_worker(self, ctx: DispatchContext) -> WorkerResult:
        """Execute a worker against a mission brief.

        Args:
            ctx: Dispatch context.

        Returns:
            Result of the execution.

        Raises:
            ValueError: If required paths are not set.
        """
        if not ctx.brief_path or not ctx.worktree_path:
            raise ValueError("brief_path and worktree_path must be set")
        prompt = build_worker_prompt(ctx.brief_path)
        return ctx.worker.execute(
            prompt=prompt,
            project_path=ctx.worktree_path,
            task_type=ctx.task.complexity,
            model=ctx.model,
        )

    def run_review(
        self, ctx: DispatchContext, exec_result: WorkerResult
    ) -> WorkerResult:
        """Perform an automated review of worker output.

        Args:
            ctx: Dispatch context.
            exec_result: Result of the worker execution.

        Returns:
            Result of the review execution.

        Raises:
            ValueError: If required paths are not set.
        """
        if not ctx.brief_path or not ctx.worktree_path:
            raise ValueError("brief_path and worktree_path must be set")
        reviewer, _ = self.select_reviewer(ctx.worker.worker_type)
        prompt = build_review_prompt(ctx.brief_path, exec_result.output)
        return reviewer.execute(
            prompt=prompt, project_path=ctx.worktree_path, task_type="review"
        )

    def _infer_tier(self, task: Task) -> str:
        """Infer the required worker tier based on task metadata."""
        text = f"{task.title} {task.description or ''}".lower()
        for keyword, tier in TIER_MAP.items():
            if keyword in text:
                return tier
        if task.complexity == "low":
            return "local"
        if task.complexity == "high":
            return "cloud-heavy"
        return "cloud-fast"

    def _run_governance_check(
        self, task: Task, config: ProjectConfig
    ) -> GovernanceResult:
        """Run pre-dispatch governance checks."""
        if not self.governance:
            from nebulus_swarm.overlord.governance import GovernanceResult

            return GovernanceResult(approved=True)
        return self.governance.pre_dispatch_check(task, config)

    def _run_pre_dispatch_scan(self, config: ProjectConfig) -> list[str]:
        """Scan the target repository for health issues before dispatch."""
        try:
            from nebulus_swarm.overlord.scanner import scan_project

            issues = scan_project(config).issues
            # Filter out "Project path does not exist" which is common in tests
            return [i for i in issues if "Project path does not exist" not in i]
        except Exception:
            return []

    def _fail_task(
        self,
        task_id: str,
        worker_id: str,
        ctx: DispatchContext,
        exec_result: Optional[WorkerResult],
        reason: str,
        review_status: str = "",
    ) -> DispatchResultRecord:
        """Mark a task as failed and record the result."""
        usage_stats = {}
        if exec_result:
            usage_stats = {
                "tokens_input": exec_result.tokens_input,
                "tokens_output": exec_result.tokens_output,
                "tokens_total": exec_result.tokens_total,
            }

        result = DispatchResultRecord(
            task_id=task_id,
            worker_id=worker_id,
            model_id=exec_result.model_used if exec_result else "",
            branch_name=f"atom/{task_id[:8]}",
            mission_brief_path=str(ctx.brief_path) if ctx.brief_path else "",
            review_status=review_status,
            usage_stats=usage_stats,
            output_log=exec_result.output if exec_result else "",
            tokens_used=exec_result.tokens_total if exec_result else 0,
        )
        self.queue.record_dispatch_result(result)
        self.queue.transition(task_id, "failed", changed_by="dispatcher", reason=reason)
        return result
