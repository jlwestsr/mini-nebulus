"""
Tests for the Nebulus Atom Orchestrator.

Tests cover:
- DAG model (Workflow, Step, Job)
- YAML loader + validation
- Model router
- Engine DAG execution (mocked LLM)
- Context propagation
- Failure handling
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nebulus_atom.orchestrator.engine import WorkflowEngine
from nebulus_atom.orchestrator.executor import StepExecutor
from nebulus_atom.orchestrator.loader import (
    list_templates,
    load_workflow,
    load_workflow_from_string,
)
from nebulus_atom.orchestrator.models import (
    Job,
    JobStatus,
    StepResult,
    StepStatus,
    Workflow,
    WorkflowStep,
)
from nebulus_atom.orchestrator.router import ModelRouter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_workflow() -> Workflow:
    return load_workflow_from_string("""
name: test-simple
steps:
  - id: step1
    agent: atom
    prompt: Do {{input}}
""")


@pytest.fixture
def dag_workflow() -> Workflow:
    return load_workflow_from_string("""
name: test-dag
steps:
  - id: plan
    agent: atom
    prompt: Plan for {{input}}
  - id: tests
    agent: atom
    depends_on: [plan]
    prompt: Tests based on {{plan}}
  - id: implement
    agent: atom
    depends_on: [plan, tests]
    prompt: Implement based on {{plan}} and {{tests}}
  - id: review
    agent: atom
    depends_on: [implement]
    prompt: Review {{implement}}
""")


def make_mock_openai(response: str = "mocked output") -> MagicMock:
    """Create a mock OpenAI service that returns a fixed response."""
    mock = MagicMock()
    mock.model = "test-model"

    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = response

    mock.client = MagicMock()
    mock.client.chat = MagicMock()
    mock.client.chat.completions = MagicMock()
    mock.client.chat.completions.create = AsyncMock(return_value=completion)

    return mock


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestWorkflowStep:
    def test_render_prompt_substitutes_variables(self):
        step = WorkflowStep(
            id="test",
            agent="atom",
            prompt_template="Build {{input}} using {{plan}}",
        )
        rendered = step.render_prompt({"input": "a REST API", "plan": "use FastAPI"})
        assert rendered == "Build a REST API using use FastAPI"

    def test_render_prompt_leaves_missing_vars(self):
        step = WorkflowStep(
            id="test",
            agent="atom",
            prompt_template="Hello {{name}}",
        )
        rendered = step.render_prompt({})
        assert "{{name}}" in rendered


class TestWorkflow:
    def test_get_ready_steps_no_deps(self, simple_workflow):
        ready = simple_workflow.get_ready_steps(set())
        assert len(ready) == 1
        assert ready[0].id == "step1"

    def test_get_ready_steps_dag_order(self, dag_workflow):
        # Round 1: only plan is ready (no deps)
        ready = dag_workflow.get_ready_steps(set())
        assert [s.id for s in ready] == ["plan"]

        # Round 2: after plan, tests is ready
        ready = dag_workflow.get_ready_steps({"plan"})
        assert [s.id for s in ready] == ["tests"]

        # Round 3: after plan + tests, implement is ready
        ready = dag_workflow.get_ready_steps({"plan", "tests"})
        assert [s.id for s in ready] == ["implement"]

        # Round 4: after implement, review is ready
        ready = dag_workflow.get_ready_steps({"plan", "tests", "implement"})
        assert [s.id for s in ready] == ["review"]

    def test_validate_catches_missing_dep(self):
        wf = Workflow(
            name="bad",
            steps=[
                WorkflowStep(
                    id="a",
                    agent="atom",
                    prompt_template="x",
                    depends_on=["nonexistent"],
                ),
            ],
        )
        errors = wf.validate()
        assert any("nonexistent" in e for e in errors)

    def test_validate_catches_cycle(self):
        wf = Workflow(
            name="cyclic",
            steps=[
                WorkflowStep(
                    id="a", agent="atom", prompt_template="x", depends_on=["b"]
                ),
                WorkflowStep(
                    id="b", agent="atom", prompt_template="y", depends_on=["a"]
                ),
            ],
        )
        errors = wf.validate()
        assert any("Cycle" in e for e in errors)

    def test_validate_passes_valid_dag(self, dag_workflow):
        errors = dag_workflow.validate()
        assert errors == []


class TestJob:
    def test_context_includes_inputs(self):
        job = Job(workflow_name="test", inputs={"goal": "build something"})
        ctx = job.get_context(job.inputs)
        assert ctx["goal"] == "build something"
        assert ctx["input"] == "build something"

    def test_context_propagates_step_outputs(self):
        job = Job(workflow_name="test", inputs={"goal": "test"})
        job.step_results["plan"] = StepResult(
            step_id="plan",
            status=StepStatus.COMPLETED,
            output="use FastAPI",
        )
        ctx = job.get_context(job.inputs)
        assert ctx["plan"] == "use FastAPI"
        assert ctx["plan.output"] == "use FastAPI"

    def test_context_excludes_incomplete_steps(self):
        job = Job(workflow_name="test", inputs={"goal": "test"})
        job.step_results["plan"] = StepResult(
            step_id="plan",
            status=StepStatus.RUNNING,
            output=None,
        )
        ctx = job.get_context(job.inputs)
        assert "plan" not in ctx

    def test_to_dict_serializes_correctly(self):
        job = Job(workflow_name="test", inputs={"goal": "x"}, id="fixed-id")
        d = job.to_dict()
        assert d["id"] == "fixed-id"
        assert d["workflow"] == "test"
        assert d["status"] == "pending"


# ---------------------------------------------------------------------------
# YAML loader tests
# ---------------------------------------------------------------------------


class TestLoader:
    def test_load_simple_workflow(self, simple_workflow):
        assert simple_workflow.name == "test-simple"
        assert len(simple_workflow.steps) == 1

    def test_load_raises_on_missing_name(self):
        with pytest.raises(ValueError, match="name"):
            load_workflow_from_string(
                "steps:\n  - id: x\n    agent: atom\n    prompt: y"
            )

    def test_load_raises_on_empty_steps(self):
        with pytest.raises(ValueError, match="step"):
            load_workflow_from_string("name: test\nsteps: []")

    def test_load_raises_on_cycle(self):
        with pytest.raises(ValueError, match="[Cc]ycle"):
            load_workflow_from_string("""
name: cyclic
steps:
  - id: a
    agent: atom
    prompt: x
    depends_on: [b]
  - id: b
    agent: atom
    prompt: y
    depends_on: [a]
""")

    def test_list_templates_returns_builtins(self):
        templates = list_templates()
        assert "build-feature" in templates
        assert "fix-bug" in templates
        assert "research-and-draft" in templates

    def test_builtin_templates_are_valid(self):
        for name in list_templates():
            wf = load_workflow(name)
            assert wf.validate() == []
            assert len(wf.steps) > 0


# ---------------------------------------------------------------------------
# Model router tests
# ---------------------------------------------------------------------------


class TestModelRouter:
    def setup_method(self):
        self.router = ModelRouter()

    def test_explicit_hint_overrides(self):
        model = self.router.route("anything", model_hint="large")
        assert "32b" in model or "70b" in model

    def test_explicit_tier_expands(self):
        model = self.router.route("anything", model_hint="small")
        assert "8b" in model or "7b" in model

    def test_implement_routes_to_large(self):
        model = self.router.route("implement the authentication module")
        assert "32b" in model or "70b" in model or "14b" in model  # large or medium

    def test_test_routes_to_code(self):
        model = self.router.route("write pytest tests for the login endpoint")
        assert "coder" in model or "code" in model

    def test_summarize_routes_to_small(self):
        model = self.router.route("summarize this list of items")
        assert "8b" in model or "7b" in model

    def test_default_is_medium(self):
        model = self.router.route("do some work")
        assert "14b" in model or "12b" in model


# ---------------------------------------------------------------------------
# Executor tests (mocked LLM)
# ---------------------------------------------------------------------------


class TestStepExecutor:
    @pytest.mark.asyncio
    async def test_execute_returns_output(self):
        mock_svc = make_mock_openai("plan result")
        executor = StepExecutor(mock_svc)
        step = WorkflowStep(id="plan", agent="atom", prompt_template="Plan {{input}}")
        result = await executor.execute(step, {"input": "build API"})

        assert result.status == StepStatus.COMPLETED
        assert result.output == "plan result"
        assert result.duration_seconds is not None

    @pytest.mark.asyncio
    async def test_execute_sets_model_used(self):
        mock_svc = make_mock_openai()
        executor = StepExecutor(mock_svc)
        step = WorkflowStep(id="x", agent="atom", prompt_template="hello")
        result = await executor.execute(step, {})

        assert result.model_used is not None

    @pytest.mark.asyncio
    async def test_execute_handles_llm_failure(self):
        mock_svc = MagicMock()
        mock_svc.model = "test-model"
        mock_svc.client = MagicMock()
        mock_svc.client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("LLM down")
        )

        executor = StepExecutor(mock_svc)
        step = WorkflowStep(id="x", agent="atom", prompt_template="hello")
        result = await executor.execute(step, {})

        assert result.status == StepStatus.FAILED
        assert "LLM down" in result.error

    @pytest.mark.asyncio
    async def test_execute_rejects_unknown_agent(self):
        mock_svc = make_mock_openai()
        executor = StepExecutor(mock_svc)
        step = WorkflowStep(id="x", agent="unknown_agent", prompt_template="hello")
        result = await executor.execute(step, {})

        assert result.status == StepStatus.FAILED
        assert "not yet supported" in result.error


# ---------------------------------------------------------------------------
# Engine tests (mocked LLM)
# ---------------------------------------------------------------------------


class TestWorkflowEngine:
    @pytest.mark.asyncio
    async def test_simple_job_completes(self):
        mock_svc = make_mock_openai("output")
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = WorkflowEngine(mock_svc, db_path=Path(tmpdir) / "test.db")
            wf = load_workflow_from_string("""
name: simple
steps:
  - id: only
    agent: atom
    prompt: Do {{input}}
""")
            job = await engine.submit_and_wait(wf, inputs={"goal": "test"})

        assert job.status == JobStatus.COMPLETED
        assert job.step_results["only"].status == StepStatus.COMPLETED
        assert job.step_results["only"].output == "output"

    @pytest.mark.asyncio
    async def test_dag_executes_in_order(self):
        call_order = []

        async def fake_create(model, messages, stream):
            step_content = messages[0]["content"]
            # Extract which step this is from the prompt
            if (
                "plan" in step_content.lower()
                and "implement" not in step_content.lower()
            ):
                call_order.append("plan")
                return MagicMock(
                    choices=[MagicMock(message=MagicMock(content="plan result"))]
                )
            elif "test" in step_content.lower():
                call_order.append("tests")
                return MagicMock(
                    choices=[MagicMock(message=MagicMock(content="test result"))]
                )
            else:
                call_order.append("other")
                return MagicMock(
                    choices=[MagicMock(message=MagicMock(content="other result"))]
                )

        mock_svc = MagicMock()
        mock_svc.model = "test"
        mock_svc.client = MagicMock()
        mock_svc.client.chat.completions.create = AsyncMock(side_effect=fake_create)

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = WorkflowEngine(mock_svc, db_path=Path(tmpdir) / "test.db")
            wf = load_workflow_from_string("""
name: ordered
steps:
  - id: plan
    agent: atom
    prompt: Plan {{input}}
  - id: tests
    agent: atom
    depends_on: [plan]
    prompt: Write tests based on {{plan}}
""")
            job = await engine.submit_and_wait(wf, inputs={"goal": "test"})

        assert job.status == JobStatus.COMPLETED
        # plan must complete before tests
        assert call_order[0] == "plan"

    @pytest.mark.asyncio
    async def test_failed_step_marks_remaining_skipped(self):
        mock_svc = MagicMock()
        mock_svc.model = "test"
        mock_svc.client = MagicMock()
        mock_svc.client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("LLM error")
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = WorkflowEngine(mock_svc, db_path=Path(tmpdir) / "test.db")
            wf = load_workflow_from_string("""
name: failing
steps:
  - id: step1
    agent: atom
    prompt: First
  - id: step2
    agent: atom
    depends_on: [step1]
    prompt: Second
""")
            job = await engine.submit_and_wait(wf, inputs={"goal": "test"})

        assert job.status == JobStatus.FAILED
        assert job.step_results["step1"].status == StepStatus.FAILED
        assert job.step_results["step2"].status == StepStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_context_propagates_between_steps(self):
        outputs = {}

        async def capture_create(model, messages, stream):
            prompt = messages[0]["content"]
            outputs[prompt] = True
            # Return different output per step based on prompt content
            if "Plan" in prompt:
                return MagicMock(
                    choices=[MagicMock(message=MagicMock(content="FastAPI plan"))]
                )
            else:
                return MagicMock(
                    choices=[MagicMock(message=MagicMock(content="tests done"))]
                )

        mock_svc = MagicMock()
        mock_svc.model = "test"
        mock_svc.client = MagicMock()
        mock_svc.client.chat.completions.create = AsyncMock(side_effect=capture_create)

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = WorkflowEngine(mock_svc, db_path=Path(tmpdir) / "test.db")
            wf = load_workflow_from_string("""
name: context-test
steps:
  - id: plan
    agent: atom
    prompt: Plan {{input}}
  - id: tests
    agent: atom
    depends_on: [plan]
    prompt: Tests using {{plan}}
""")
            job = await engine.submit_and_wait(wf, inputs={"goal": "build API"})

        assert job.status == JobStatus.COMPLETED
        # The tests step prompt should have contained the plan output
        tests_prompt = [p for p in outputs.keys() if "FastAPI plan" in p]
        assert len(tests_prompt) == 1, (
            "Context propagation: plan output should appear in tests prompt"
        )

    @pytest.mark.asyncio
    async def test_job_persists_to_db(self):
        mock_svc = make_mock_openai("result")
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            engine = WorkflowEngine(mock_svc, db_path=db_path)
            wf = load_workflow_from_string("""
name: persist-test
steps:
  - id: s1
    agent: atom
    prompt: Test
""")
            job = await engine.submit_and_wait(wf, inputs={})
            job_id = job.id

            # Create a new engine pointing at same DB
            engine2 = WorkflowEngine(mock_svc, db_path=db_path)
            loaded = engine2.get_job(job_id)

        assert loaded is not None
        assert loaded.id == job_id
        assert loaded.status == JobStatus.COMPLETED
