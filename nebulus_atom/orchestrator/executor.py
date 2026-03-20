"""
Step executor — runs a single workflow step against an agent.

Currently supports the "atom" agent (local Atom LLM service).
Designed for future extension to "moto", "cael", etc.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Dict, Any, Optional

from nebulus_atom.utils.logger import setup_logger
from .models import WorkflowStep, StepResult, StepStatus
from .router import ModelRouter

logger = setup_logger(__name__)


class StepExecutor:
    """Executes a single workflow step against its designated agent."""

    def __init__(
        self,
        openai_service,
        model_router: Optional[ModelRouter] = None,
    ):
        self._openai = openai_service
        self._router = model_router or ModelRouter()

    async def execute(
        self,
        step: WorkflowStep,
        context: Dict[str, Any],
    ) -> StepResult:
        """
        Execute a step with rendered context.

        Args:
            step: The workflow step to execute
            context: Current job context (inputs + prior step outputs)

        Returns:
            StepResult with output or error
        """
        result = StepResult(
            step_id=step.id,
            status=StepStatus.RUNNING,
            started_at=datetime.utcnow(),
        )

        try:
            # Render the prompt
            prompt = step.render_prompt(context)

            # Route to model
            model = self._router.route(prompt, step.model_hint)
            result.model_used = model

            logger.info(
                f"Executing step '{step.id}' with agent={step.agent}, model={model}"
            )

            # Dispatch to agent
            output = await self._dispatch(
                step.agent, prompt, model, step.timeout_seconds
            )

            result.output = output
            result.status = StepStatus.COMPLETED
            result.completed_at = datetime.utcnow()

            logger.info(f"Step '{step.id}' completed in {result.duration_seconds:.1f}s")

        except asyncio.TimeoutError:
            result.status = StepStatus.FAILED
            result.error = f"Step timed out after {step.timeout_seconds}s"
            result.completed_at = datetime.utcnow()
            logger.error(f"Step '{step.id}' timed out")

        except Exception as e:
            result.status = StepStatus.FAILED
            result.error = str(e)
            result.completed_at = datetime.utcnow()
            logger.error(f"Step '{step.id}' failed: {e}")

        return result

    async def _dispatch(
        self,
        agent: str,
        prompt: str,
        model: str,
        timeout_seconds: int,
    ) -> str:
        """Dispatch prompt to agent and return response."""
        if agent == "atom":
            return await self._run_atom(prompt, model, timeout_seconds)
        else:
            # Future: route to remote agents via API
            raise NotImplementedError(
                f"Agent '{agent}' not yet supported. "
                f"Supported: atom. (moto, cael, hohenheim coming soon)"
            )

    async def _run_atom(self, prompt: str, model: str, timeout_seconds: int) -> str:
        """Run a prompt through the local Atom LLM service."""
        messages = [{"role": "user", "content": prompt}]

        # Temporarily override model
        original_model = getattr(self._openai, "model", None)
        try:
            if hasattr(self._openai, "model"):
                self._openai.model = model

            response_parts = []
            async with asyncio.timeout(timeout_seconds):
                completion = await self._openai.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=False,
                )
                response_parts.append(completion.choices[0].message.content or "")

            return "".join(response_parts).strip()

        finally:
            if original_model is not None and hasattr(self._openai, "model"):
                self._openai.model = original_model
