# V2 Phase 2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add supervisor evaluation, worker scope enforcement, and enhancement proposals to the Overlord/Minion system.

**Architecture:** Extend the existing Overlord with three new modules (evaluator, scope, proposals) and modify the Minion's ToolExecutor to enforce file-level write scope. All modules are tested independently with mocked dependencies.

**Tech Stack:** Python 3.12, SQLite, dataclasses, pytest, existing reviewer module (CheckRunner, LLMReviewer)

---

### Task 1: Evaluator Data Models

**Files:**
- Create: `nebulus_swarm/overlord/evaluator.py`
- Create: `tests/test_evaluator.py`

**Step 1: Write failing tests for data models**

```python
# tests/test_evaluator.py
"""Tests for the supervisor evaluation layer."""

from nebulus_swarm.overlord.evaluator import (
    CheckScore,
    EvaluationResult,
    RevisionRequest,
)


class TestCheckScore:
    def test_pass_value(self):
        assert CheckScore.PASS.value == "pass"

    def test_fail_value(self):
        assert CheckScore.FAIL.value == "fail"

    def test_needs_revision_value(self):
        assert CheckScore.NEEDS_REVISION.value == "needs_revision"


class TestEvaluationResult:
    def test_overall_pass_when_all_pass(self):
        result = EvaluationResult(
            pr_number=1,
            repo="owner/repo",
            test_score=CheckScore.PASS,
            lint_score=CheckScore.PASS,
            review_score=CheckScore.PASS,
        )
        assert result.overall == CheckScore.PASS

    def test_overall_needs_revision_when_any_needs_revision(self):
        result = EvaluationResult(
            pr_number=1,
            repo="owner/repo",
            test_score=CheckScore.PASS,
            lint_score=CheckScore.NEEDS_REVISION,
            review_score=CheckScore.PASS,
        )
        assert result.overall == CheckScore.NEEDS_REVISION

    def test_overall_fail_when_any_fail(self):
        result = EvaluationResult(
            pr_number=1,
            repo="owner/repo",
            test_score=CheckScore.FAIL,
            lint_score=CheckScore.PASS,
            review_score=CheckScore.NEEDS_REVISION,
        )
        assert result.overall == CheckScore.FAIL

    def test_fail_beats_needs_revision(self):
        result = EvaluationResult(
            pr_number=1,
            repo="owner/repo",
            test_score=CheckScore.NEEDS_REVISION,
            lint_score=CheckScore.FAIL,
            review_score=CheckScore.NEEDS_REVISION,
        )
        assert result.overall == CheckScore.FAIL

    def test_default_revision_number_is_zero(self):
        result = EvaluationResult(
            pr_number=1,
            repo="owner/repo",
            test_score=CheckScore.PASS,
            lint_score=CheckScore.PASS,
            review_score=CheckScore.PASS,
        )
        assert result.revision_number == 0

    def test_feedback_aggregation(self):
        result = EvaluationResult(
            pr_number=1,
            repo="owner/repo",
            test_score=CheckScore.FAIL,
            lint_score=CheckScore.PASS,
            review_score=CheckScore.PASS,
            test_feedback="3 tests failed",
            lint_feedback="",
            review_feedback="",
        )
        combined = result.combined_feedback
        assert "3 tests failed" in combined


class TestRevisionRequest:
    def test_has_required_fields(self):
        req = RevisionRequest(
            repo="owner/repo",
            pr_number=42,
            issue_number=10,
            branch="minion/issue-10",
            feedback="Tests failed: test_foo, test_bar",
            revision_number=1,
        )
        assert req.repo == "owner/repo"
        assert req.revision_number == 1
```

**Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_evaluator.py -q`
Expected: ImportError — `evaluator` module doesn't exist yet.

**Step 3: Implement data models**

```python
# nebulus_swarm/overlord/evaluator.py
"""Supervisor evaluation layer for Minion output."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

MAX_REVISIONS = 2


class CheckScore(Enum):
    """Score for a single evaluation check."""

    PASS = "pass"
    FAIL = "fail"
    NEEDS_REVISION = "needs_revision"


@dataclass
class EvaluationResult:
    """Result of evaluating a Minion's work."""

    pr_number: int
    repo: str
    test_score: CheckScore
    lint_score: CheckScore
    review_score: CheckScore
    revision_number: int = 0
    test_feedback: str = ""
    lint_feedback: str = ""
    review_feedback: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def overall(self) -> CheckScore:
        """Compute overall score from individual checks."""
        scores = [self.test_score, self.lint_score, self.review_score]
        if any(s == CheckScore.FAIL for s in scores):
            return CheckScore.FAIL
        if any(s == CheckScore.NEEDS_REVISION for s in scores):
            return CheckScore.NEEDS_REVISION
        return CheckScore.PASS

    @property
    def combined_feedback(self) -> str:
        """Combine all feedback into a single string."""
        parts = []
        if self.test_feedback:
            parts.append(f"Tests: {self.test_feedback}")
        if self.lint_feedback:
            parts.append(f"Lint: {self.lint_feedback}")
        if self.review_feedback:
            parts.append(f"Review: {self.review_feedback}")
        return "\n".join(parts)


@dataclass
class RevisionRequest:
    """Request for a Minion to revise its work."""

    repo: str
    pr_number: int
    issue_number: int
    branch: str
    feedback: str
    revision_number: int
```

**Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_evaluator.py -q`
Expected: All pass.

**Step 5: Commit**

```bash
git add nebulus_swarm/overlord/evaluator.py tests/test_evaluator.py
git commit -m "feat: add evaluator data models (CheckScore, EvaluationResult, RevisionRequest)"
```

---

### Task 2: Evaluator Core Logic

**Files:**
- Modify: `nebulus_swarm/overlord/evaluator.py`
- Modify: `tests/test_evaluator.py`

**Step 1: Write failing tests for Evaluator class**

Add to `tests/test_evaluator.py`:

```python
from unittest.mock import MagicMock, patch

from nebulus_swarm.overlord.evaluator import (
    CheckScore,
    Evaluator,
    EvaluationResult,
    MAX_REVISIONS,
)
from nebulus_swarm.reviewer.checks import CheckResult, ChecksReport, CheckStatus
from nebulus_swarm.reviewer.pr_reviewer import ReviewDecision, ReviewResult


class TestEvaluator:
    def _make_evaluator(self):
        return Evaluator(
            llm_base_url="http://localhost:5000/v1",
            llm_model="test-model",
            github_token="ghp_test",
        )

    def test_all_pass(self):
        ev = self._make_evaluator()
        checks = ChecksReport(results=[
            CheckResult(name="pytest", status=CheckStatus.PASSED, message="10 passed"),
            CheckResult(name="ruff", status=CheckStatus.PASSED, message="clean"),
        ])
        review = ReviewResult(
            decision=ReviewDecision.APPROVE,
            summary="Looks good",
            confidence=0.9,
        )
        result = ev._score(checks, review, repo="o/r", pr_number=1)
        assert result.overall == CheckScore.PASS

    def test_test_failure_means_needs_revision(self):
        ev = self._make_evaluator()
        checks = ChecksReport(results=[
            CheckResult(name="pytest", status=CheckStatus.FAILED, message="2 failed"),
            CheckResult(name="ruff", status=CheckStatus.PASSED, message="clean"),
        ])
        review = ReviewResult(
            decision=ReviewDecision.APPROVE,
            summary="Looks good",
            confidence=0.9,
        )
        result = ev._score(checks, review, repo="o/r", pr_number=1)
        assert result.test_score == CheckScore.NEEDS_REVISION
        assert "2 failed" in result.test_feedback

    def test_request_changes_means_needs_revision(self):
        ev = self._make_evaluator()
        checks = ChecksReport(results=[
            CheckResult(name="pytest", status=CheckStatus.PASSED, message="ok"),
        ])
        review = ReviewResult(
            decision=ReviewDecision.REQUEST_CHANGES,
            summary="Has bugs",
            confidence=0.8,
            issues=["Off by one error"],
        )
        result = ev._score(checks, review, repo="o/r", pr_number=1)
        assert result.review_score == CheckScore.NEEDS_REVISION

    def test_low_confidence_review_means_pass(self):
        ev = self._make_evaluator()
        checks = ChecksReport(results=[])
        review = ReviewResult(
            decision=ReviewDecision.COMMENT,
            summary="Minor suggestions",
            confidence=0.6,
        )
        result = ev._score(checks, review, repo="o/r", pr_number=1)
        assert result.review_score == CheckScore.PASS

    def test_can_revise_under_max(self):
        ev = self._make_evaluator()
        assert ev.can_revise(revision_number=0) is True
        assert ev.can_revise(revision_number=1) is True

    def test_cannot_revise_at_max(self):
        ev = self._make_evaluator()
        assert ev.can_revise(revision_number=MAX_REVISIONS) is False
```

**Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_evaluator.py::TestEvaluator -q`
Expected: ImportError — `Evaluator` class not defined yet.

**Step 3: Implement Evaluator class**

Add to `nebulus_swarm/overlord/evaluator.py`:

```python
from nebulus_swarm.reviewer.checks import CheckRunner, ChecksReport, CheckStatus
from nebulus_swarm.reviewer.llm_review import LLMReviewer
from nebulus_swarm.reviewer.pr_reviewer import PRReviewer, ReviewDecision, ReviewResult


class Evaluator:
    """Evaluates Minion output after task completion."""

    def __init__(
        self,
        llm_base_url: str,
        llm_model: str,
        github_token: str,
        llm_api_key: str = "not-needed",
        llm_timeout: int = 120,
    ):
        self.llm_base_url = llm_base_url
        self.llm_model = llm_model
        self.github_token = github_token
        self.llm_api_key = llm_api_key
        self.llm_timeout = llm_timeout
        self._llm_reviewer: Optional[LLMReviewer] = None
        self._pr_reviewer: Optional[PRReviewer] = None

    @property
    def llm_reviewer(self) -> LLMReviewer:
        if self._llm_reviewer is None:
            self._llm_reviewer = LLMReviewer(
                base_url=self.llm_base_url,
                model=self.llm_model,
                api_key=self.llm_api_key,
                timeout=self.llm_timeout,
            )
        return self._llm_reviewer

    @property
    def pr_reviewer(self) -> PRReviewer:
        if self._pr_reviewer is None:
            self._pr_reviewer = PRReviewer(self.github_token)
        return self._pr_reviewer

    def can_revise(self, revision_number: int) -> bool:
        """Check if another revision is allowed."""
        return revision_number < MAX_REVISIONS

    def _score(
        self,
        checks: ChecksReport,
        review: ReviewResult,
        repo: str,
        pr_number: int,
        revision_number: int = 0,
    ) -> EvaluationResult:
        """Score check results and LLM review into an EvaluationResult."""
        # Tests: any pytest failure -> NEEDS_REVISION
        test_score = CheckScore.PASS
        test_feedback = ""
        for r in checks.results:
            if r.name.lower() in ("pytest", "tests") and r.status == CheckStatus.FAILED:
                test_score = CheckScore.NEEDS_REVISION
                test_feedback = r.message
                break

        # Lint: any lint failure -> NEEDS_REVISION
        lint_score = CheckScore.PASS
        lint_feedback = ""
        for r in checks.results:
            if r.name.lower() in ("ruff", "lint", "flake8") and r.status == CheckStatus.FAILED:
                lint_score = CheckScore.NEEDS_REVISION
                lint_feedback = r.message
                break

        # Review: REQUEST_CHANGES -> NEEDS_REVISION, APPROVE/COMMENT -> PASS
        review_score = CheckScore.PASS
        review_feedback = ""
        if review.decision == ReviewDecision.REQUEST_CHANGES:
            review_score = CheckScore.NEEDS_REVISION
            review_feedback = review.summary
            if review.issues:
                review_feedback += "\n" + "\n".join(f"- {i}" for i in review.issues)

        return EvaluationResult(
            pr_number=pr_number,
            repo=repo,
            test_score=test_score,
            lint_score=lint_score,
            review_score=review_score,
            revision_number=revision_number,
            test_feedback=test_feedback,
            lint_feedback=lint_feedback,
            review_feedback=review_feedback,
        )

    def evaluate(
        self,
        repo: str,
        pr_number: int,
        repo_path: Optional[str] = None,
        revision_number: int = 0,
    ) -> EvaluationResult:
        """Run full evaluation on a PR.

        Args:
            repo: Repository in owner/name format.
            pr_number: Pull request number.
            repo_path: Local path for running checks (optional).
            revision_number: Current revision attempt number.

        Returns:
            EvaluationResult with scores and feedback.
        """
        logger.info(f"Evaluating {repo}#{pr_number} (revision {revision_number})")

        # Run local checks
        checks = ChecksReport()
        if repo_path:
            runner = CheckRunner(repo_path)
            pr_details = self.pr_reviewer.get_pr_details(repo, pr_number)
            changed_files = [f.filename for f in pr_details.files]
            checks = runner.run_all_checks(changed_files)

        # Run LLM review
        pr_details = self.pr_reviewer.get_pr_details(repo, pr_number)
        review = self.llm_reviewer.review_pr(pr_details)

        return self._score(
            checks, review,
            repo=repo,
            pr_number=pr_number,
            revision_number=revision_number,
        )

    def close(self) -> None:
        """Clean up resources."""
        if self._pr_reviewer:
            self._pr_reviewer.close()
```

**Step 4: Run tests**

Run: `venv/bin/python -m pytest tests/test_evaluator.py -q`
Expected: All pass.

**Step 5: Commit**

```bash
git add nebulus_swarm/overlord/evaluator.py tests/test_evaluator.py
git commit -m "feat: add Evaluator class with scoring and revision logic"
```

---

### Task 3: Scope Enforcement — Data Model

**Files:**
- Create: `nebulus_swarm/overlord/scope.py`
- Create: `tests/test_scope.py`

**Step 1: Write failing tests**

```python
# tests/test_scope.py
"""Tests for worker scope enforcement."""

from nebulus_swarm.overlord.scope import ScopeConfig, ScopeMode


class TestScopeMode:
    def test_unrestricted_value(self):
        assert ScopeMode.UNRESTRICTED.value == "unrestricted"

    def test_directory_value(self):
        assert ScopeMode.DIRECTORY.value == "directory"

    def test_explicit_value(self):
        assert ScopeMode.EXPLICIT.value == "explicit"


class TestScopeConfig:
    def test_unrestricted_allows_all(self):
        scope = ScopeConfig.unrestricted()
        assert scope.is_write_allowed("any/path/file.py")
        assert scope.is_write_allowed("deeply/nested/dir/file.txt")

    def test_directory_allows_matching_paths(self):
        scope = ScopeConfig(
            mode=ScopeMode.DIRECTORY,
            allowed_patterns=["src/components/**", "tests/components/**"],
        )
        assert scope.is_write_allowed("src/components/Button.tsx")
        assert scope.is_write_allowed("src/components/deep/nested/File.tsx")
        assert scope.is_write_allowed("tests/components/test_button.py")

    def test_directory_blocks_non_matching_paths(self):
        scope = ScopeConfig(
            mode=ScopeMode.DIRECTORY,
            allowed_patterns=["src/components/**"],
        )
        assert not scope.is_write_allowed("src/utils/helper.py")
        assert not scope.is_write_allowed("README.md")
        assert not scope.is_write_allowed("package.json")

    def test_explicit_allows_exact_files(self):
        scope = ScopeConfig(
            mode=ScopeMode.EXPLICIT,
            allowed_patterns=["src/app.py", "tests/test_app.py"],
        )
        assert scope.is_write_allowed("src/app.py")
        assert scope.is_write_allowed("tests/test_app.py")
        assert not scope.is_write_allowed("src/other.py")

    def test_from_json_string(self):
        scope = ScopeConfig.from_json('["src/**", "tests/**"]')
        assert scope.mode == ScopeMode.DIRECTORY
        assert scope.is_write_allowed("src/foo.py")

    def test_from_json_empty_means_unrestricted(self):
        scope = ScopeConfig.from_json("")
        assert scope.mode == ScopeMode.UNRESTRICTED

    def test_from_json_invalid_means_unrestricted(self):
        scope = ScopeConfig.from_json("not valid json")
        assert scope.mode == ScopeMode.UNRESTRICTED

    def test_to_json(self):
        scope = ScopeConfig(
            mode=ScopeMode.DIRECTORY,
            allowed_patterns=["src/**"],
        )
        json_str = scope.to_json()
        assert "src/**" in json_str

    def test_violation_message(self):
        scope = ScopeConfig(
            mode=ScopeMode.DIRECTORY,
            allowed_patterns=["src/**"],
        )
        msg = scope.violation_message("README.md")
        assert "README.md" in msg
        assert "src/**" in msg
```

**Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_scope.py -q`
Expected: ImportError.

**Step 3: Implement ScopeConfig**

```python
# nebulus_swarm/overlord/scope.py
"""Worker scope enforcement for Minion file access."""

import fnmatch
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List

logger = logging.getLogger(__name__)


class ScopeMode(Enum):
    """Scope enforcement mode."""

    UNRESTRICTED = "unrestricted"
    DIRECTORY = "directory"
    EXPLICIT = "explicit"


@dataclass
class ScopeConfig:
    """Configuration for Minion write scope."""

    mode: ScopeMode = ScopeMode.UNRESTRICTED
    allowed_patterns: List[str] = field(default_factory=list)

    @classmethod
    def unrestricted(cls) -> "ScopeConfig":
        """Create an unrestricted scope."""
        return cls(mode=ScopeMode.UNRESTRICTED)

    @classmethod
    def from_json(cls, json_str: str) -> "ScopeConfig":
        """Parse scope from JSON string (MINION_SCOPE env var).

        Args:
            json_str: JSON array of allowed path patterns.

        Returns:
            ScopeConfig. Unrestricted if empty or invalid.
        """
        if not json_str or not json_str.strip():
            return cls.unrestricted()
        try:
            patterns = json.loads(json_str)
            if not isinstance(patterns, list) or not patterns:
                return cls.unrestricted()
            return cls(mode=ScopeMode.DIRECTORY, allowed_patterns=patterns)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Invalid MINION_SCOPE JSON, using unrestricted: {json_str[:100]}")
            return cls.unrestricted()

    def to_json(self) -> str:
        """Serialize allowed patterns to JSON."""
        return json.dumps(self.allowed_patterns)

    def is_write_allowed(self, path: str) -> bool:
        """Check if writing to a path is allowed.

        Args:
            path: Relative file path to check.

        Returns:
            True if write is allowed.
        """
        if self.mode == ScopeMode.UNRESTRICTED:
            return True

        for pattern in self.allowed_patterns:
            if self.mode == ScopeMode.EXPLICIT:
                if path == pattern:
                    return True
            else:  # DIRECTORY
                if fnmatch.fnmatch(path, pattern):
                    return True
        return False

    def violation_message(self, path: str) -> str:
        """Generate a human-readable violation message.

        Args:
            path: The path that was blocked.

        Returns:
            Error message explaining the restriction.
        """
        allowed = ", ".join(self.allowed_patterns)
        return (
            f"Write to '{path}' is outside your assigned scope. "
            f"Allowed paths: [{allowed}]. "
            f"If you need to modify this file, use task_blocked to request expanded scope."
        )
```

**Step 4: Run tests**

Run: `venv/bin/python -m pytest tests/test_scope.py -q`
Expected: All pass.

**Step 5: Commit**

```bash
git add nebulus_swarm/overlord/scope.py tests/test_scope.py
git commit -m "feat: add ScopeConfig for worker file-level write enforcement"
```

---

### Task 4: Scope Enforcement — ToolExecutor Integration

**Files:**
- Modify: `nebulus_swarm/minion/agent/tool_executor.py:25-43` (constructor)
- Modify: `nebulus_swarm/minion/agent/tool_executor.py:180-207` (write_file)
- Create: `tests/test_scope_executor.py`

**Step 1: Write failing tests**

```python
# tests/test_scope_executor.py
"""Tests for scope enforcement in ToolExecutor."""

from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("openai")

from nebulus_swarm.minion.agent.tool_executor import ToolExecutor
from nebulus_swarm.overlord.scope import ScopeConfig, ScopeMode


class TestScopedToolExecutor:
    def test_unrestricted_allows_write(self, tmp_path):
        executor = ToolExecutor(workspace=tmp_path)
        result = executor.execute("write_file", {"path": "foo.py", "content": "x = 1"})
        assert result.success

    def test_scoped_allows_write_in_scope(self, tmp_path):
        scope = ScopeConfig(mode=ScopeMode.DIRECTORY, allowed_patterns=["src/**"])
        executor = ToolExecutor(workspace=tmp_path, scope=scope)
        (tmp_path / "src").mkdir()
        result = executor.execute("write_file", {"path": "src/app.py", "content": "x = 1"})
        assert result.success

    def test_scoped_blocks_write_outside_scope(self, tmp_path):
        scope = ScopeConfig(mode=ScopeMode.DIRECTORY, allowed_patterns=["src/**"])
        executor = ToolExecutor(workspace=tmp_path, scope=scope)
        result = executor.execute("write_file", {"path": "README.md", "content": "hi"})
        assert not result.success
        assert "outside your assigned scope" in result.error

    def test_scoped_blocks_edit_outside_scope(self, tmp_path):
        scope = ScopeConfig(mode=ScopeMode.DIRECTORY, allowed_patterns=["src/**"])
        executor = ToolExecutor(workspace=tmp_path, scope=scope)
        # Create a file outside scope
        (tmp_path / "README.md").write_text("original")
        result = executor.execute("edit_file", {
            "path": "README.md",
            "old_text": "original",
            "new_text": "modified",
        })
        assert not result.success
        assert "outside your assigned scope" in result.error

    def test_scoped_allows_read_outside_scope(self, tmp_path):
        scope = ScopeConfig(mode=ScopeMode.DIRECTORY, allowed_patterns=["src/**"])
        executor = ToolExecutor(workspace=tmp_path, scope=scope)
        (tmp_path / "README.md").write_text("hello")
        result = executor.execute("read_file", {"path": "README.md"})
        assert result.success
        assert "hello" in result.output

    def test_default_scope_is_unrestricted(self, tmp_path):
        executor = ToolExecutor(workspace=tmp_path)
        result = executor.execute("write_file", {"path": "anywhere.py", "content": "x"})
        assert result.success
```

**Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_scope_executor.py -q`
Expected: TypeError — ToolExecutor doesn't accept `scope` parameter yet.

**Step 3: Modify ToolExecutor**

In `nebulus_swarm/minion/agent/tool_executor.py`:

1. Add import at top: `from nebulus_swarm.overlord.scope import ScopeConfig`
2. Add `scope` parameter to `__init__`:
   ```python
   def __init__(
       self,
       workspace: Path,
       skill_loader=None,
       skill_getter=None,
       scope: Optional[ScopeConfig] = None,
   ):
       self.workspace = workspace.resolve()
       self.scope = scope or ScopeConfig.unrestricted()
       # ... rest unchanged
   ```
3. Add scope check method:
   ```python
   def _check_write_scope(self, path: str) -> Optional[str]:
       """Check if a write to path is allowed by scope. Returns error or None."""
       if self.scope.is_write_allowed(path):
           return None
       return self.scope.violation_message(path)
   ```
4. Add scope check to `_write_file` (before `resolved.write_text`):
   ```python
   scope_error = self._check_write_scope(path)
   if scope_error:
       return ToolResult(tool_call_id="", name="write_file", success=False, output="", error=scope_error)
   ```
5. Add same check to `_edit_file` (before the edit logic).

**Step 4: Run tests**

Run: `venv/bin/python -m pytest tests/test_scope_executor.py -q`
Expected: All pass.

**Step 5: Commit**

```bash
git add nebulus_swarm/minion/agent/tool_executor.py tests/test_scope_executor.py
git commit -m "feat: enforce file-level write scope in ToolExecutor"
```

---

### Task 5: Minion Loads Scope from Environment

**Files:**
- Modify: `nebulus_swarm/minion/main.py:36-70` (MinionConfig)
- Add test to: `tests/test_scope_executor.py`

**Step 1: Write failing test**

Add to `tests/test_scope_executor.py`:

```python
import os
from unittest.mock import patch


class TestMinionScopeLoading:
    def test_minion_config_loads_scope_from_env(self):
        from nebulus_swarm.minion.main import MinionConfig

        env = {
            "MINION_ID": "m-1",
            "GITHUB_REPO": "owner/repo",
            "GITHUB_ISSUE": "42",
            "GITHUB_TOKEN": "ghp_test",
            "MINION_SCOPE": '["src/**", "tests/**"]',
        }
        with patch.dict(os.environ, env, clear=True):
            config = MinionConfig.from_env()
        assert config.scope is not None
        assert config.scope.is_write_allowed("src/foo.py")
        assert not config.scope.is_write_allowed("README.md")

    def test_minion_config_no_scope_means_unrestricted(self):
        from nebulus_swarm.minion.main import MinionConfig

        env = {
            "MINION_ID": "m-1",
            "GITHUB_REPO": "owner/repo",
            "GITHUB_ISSUE": "42",
            "GITHUB_TOKEN": "ghp_test",
        }
        with patch.dict(os.environ, env, clear=True):
            config = MinionConfig.from_env()
        assert config.scope.is_write_allowed("any/file.py")
```

**Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_scope_executor.py::TestMinionScopeLoading -q`
Expected: AttributeError — MinionConfig has no `scope` field.

**Step 3: Modify MinionConfig**

In `nebulus_swarm/minion/main.py`:

1. Add import: `from nebulus_swarm.overlord.scope import ScopeConfig`
2. Add field to `MinionConfig`: `scope: ScopeConfig`
3. In `from_env()`, add:
   ```python
   scope=ScopeConfig.from_json(os.environ.get("MINION_SCOPE", "")),
   ```

**Step 4: Run tests**

Run: `venv/bin/python -m pytest tests/test_scope_executor.py -q`
Expected: All pass.

**Step 5: Commit**

```bash
git add nebulus_swarm/minion/main.py tests/test_scope_executor.py
git commit -m "feat: Minion loads MINION_SCOPE from environment"
```

---

### Task 6: Proposals — Data Model and Store

**Files:**
- Create: `nebulus_swarm/overlord/proposals.py`
- Create: `tests/test_proposals.py`

**Step 1: Write failing tests**

```python
# tests/test_proposals.py
"""Tests for the enhancement proposal system."""

from nebulus_swarm.overlord.proposals import (
    EnhancementProposal,
    ProposalStatus,
    ProposalStore,
    ProposalType,
)


class TestProposalTypes:
    def test_new_skill_type(self):
        assert ProposalType.NEW_SKILL.value == "new_skill"

    def test_statuses(self):
        assert ProposalStatus.PENDING.value == "pending"
        assert ProposalStatus.APPROVED.value == "approved"
        assert ProposalStatus.REJECTED.value == "rejected"
        assert ProposalStatus.IMPLEMENTED.value == "implemented"


class TestEnhancementProposal:
    def test_create_proposal(self):
        p = EnhancementProposal(
            type=ProposalType.NEW_SKILL,
            title="Add React testing skill",
            rationale="Minion failed React tests 3 times",
            proposed_action="Create a skill for React component testing",
        )
        assert p.id  # UUID auto-generated
        assert p.status == ProposalStatus.PENDING

    def test_is_actionable(self):
        p = EnhancementProposal(
            type=ProposalType.TOOL_FIX,
            title="Fix linting",
            rationale="Lint always fails",
            proposed_action="Update ruff config",
        )
        assert p.is_actionable  # pending
        p.status = ProposalStatus.APPROVED
        assert p.is_actionable  # approved but not implemented
        p.status = ProposalStatus.IMPLEMENTED
        assert not p.is_actionable


class TestProposalStore:
    def test_create_and_get(self, tmp_path):
        store = ProposalStore(db_path=str(tmp_path / "test.db"))
        p = EnhancementProposal(
            type=ProposalType.NEW_SKILL,
            title="Test proposal",
            rationale="Testing",
            proposed_action="Do something",
        )
        store.save(p)
        loaded = store.get(p.id)
        assert loaded is not None
        assert loaded.title == "Test proposal"

    def test_list_pending(self, tmp_path):
        store = ProposalStore(db_path=str(tmp_path / "test.db"))
        p1 = EnhancementProposal(
            type=ProposalType.NEW_SKILL,
            title="Pending",
            rationale="r",
            proposed_action="a",
        )
        p2 = EnhancementProposal(
            type=ProposalType.TOOL_FIX,
            title="Also pending",
            rationale="r",
            proposed_action="a",
        )
        store.save(p1)
        store.save(p2)
        pending = store.list_by_status(ProposalStatus.PENDING)
        assert len(pending) == 2

    def test_approve(self, tmp_path):
        store = ProposalStore(db_path=str(tmp_path / "test.db"))
        p = EnhancementProposal(
            type=ProposalType.CONFIG_CHANGE,
            title="Change config",
            rationale="r",
            proposed_action="a",
        )
        store.save(p)
        store.update_status(p.id, ProposalStatus.APPROVED)
        loaded = store.get(p.id)
        assert loaded.status == ProposalStatus.APPROVED

    def test_list_empty(self, tmp_path):
        store = ProposalStore(db_path=str(tmp_path / "test.db"))
        assert store.list_by_status(ProposalStatus.PENDING) == []

    def test_get_nonexistent_returns_none(self, tmp_path):
        store = ProposalStore(db_path=str(tmp_path / "test.db"))
        assert store.get("nonexistent-id") is None
```

**Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_proposals.py -q`
Expected: ImportError.

**Step 3: Implement proposals module**

```python
# nebulus_swarm/overlord/proposals.py
"""Enhancement proposal system for supervisor-identified improvements."""

import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Generator, List, Optional


class ProposalType(Enum):
    """Type of enhancement proposal."""

    NEW_SKILL = "new_skill"
    TOOL_FIX = "tool_fix"
    CONFIG_CHANGE = "config_change"
    WORKFLOW_IMPROVEMENT = "workflow_improvement"


class ProposalStatus(Enum):
    """Status of an enhancement proposal."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    IMPLEMENTED = "implemented"


@dataclass
class EnhancementProposal:
    """A structured proposal for system improvement."""

    type: ProposalType
    title: str
    rationale: str
    proposed_action: str
    estimated_impact: str = "Medium"
    risk: str = "Low"
    status: ProposalStatus = ProposalStatus.PENDING
    related_issues: List[int] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None

    @property
    def is_actionable(self) -> bool:
        """Check if proposal still needs action."""
        return self.status in (ProposalStatus.PENDING, ProposalStatus.APPROVED)


class ProposalStore:
    """SQLite-backed storage for enhancement proposals."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_dir()
        self._init_db()

    def _ensure_dir(self) -> None:
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    proposed_action TEXT NOT NULL,
                    estimated_impact TEXT DEFAULT 'Medium',
                    risk TEXT DEFAULT 'Low',
                    status TEXT NOT NULL DEFAULT 'pending',
                    related_issues TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                )
            """)

    def save(self, proposal: EnhancementProposal) -> None:
        """Save a proposal to the store."""
        import json

        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO proposals
                   (id, type, title, rationale, proposed_action,
                    estimated_impact, risk, status, related_issues,
                    created_at, resolved_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    proposal.id,
                    proposal.type.value,
                    proposal.title,
                    proposal.rationale,
                    proposal.proposed_action,
                    proposal.estimated_impact,
                    proposal.risk,
                    proposal.status.value,
                    json.dumps(proposal.related_issues),
                    proposal.created_at.isoformat(),
                    proposal.resolved_at.isoformat() if proposal.resolved_at else None,
                ),
            )

    def get(self, proposal_id: str) -> Optional[EnhancementProposal]:
        """Get a proposal by ID."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
            if row:
                return self._row_to_proposal(row)
            return None

    def list_by_status(self, status: ProposalStatus) -> List[EnhancementProposal]:
        """List proposals with a given status."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM proposals WHERE status = ? ORDER BY created_at DESC",
                (status.value,),
            ).fetchall()
            return [self._row_to_proposal(r) for r in rows]

    def update_status(
        self, proposal_id: str, status: ProposalStatus
    ) -> None:
        """Update a proposal's status."""
        resolved_at = None
        if status in (ProposalStatus.REJECTED, ProposalStatus.IMPLEMENTED):
            resolved_at = datetime.now().isoformat()

        with self._conn() as conn:
            conn.execute(
                "UPDATE proposals SET status = ?, resolved_at = ? WHERE id = ?",
                (status.value, resolved_at, proposal_id),
            )

    def _row_to_proposal(self, row: sqlite3.Row) -> EnhancementProposal:
        import json

        return EnhancementProposal(
            id=row["id"],
            type=ProposalType(row["type"]),
            title=row["title"],
            rationale=row["rationale"],
            proposed_action=row["proposed_action"],
            estimated_impact=row["estimated_impact"],
            risk=row["risk"],
            status=ProposalStatus(row["status"]),
            related_issues=json.loads(row["related_issues"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            resolved_at=datetime.fromisoformat(row["resolved_at"])
            if row["resolved_at"]
            else None,
        )
```

**Step 4: Run tests**

Run: `venv/bin/python -m pytest tests/test_proposals.py -q`
Expected: All pass.

**Step 5: Commit**

```bash
git add nebulus_swarm/overlord/proposals.py tests/test_proposals.py
git commit -m "feat: add enhancement proposal system with SQLite store"
```

---

### Task 7: Proposals CLI Commands

**Files:**
- Create: `nebulus_atom/commands/proposals.py`
- Create: `tests/test_proposals_cli.py`
- Modify: `nebulus_atom/main.py` (add proposals command)

**Step 1: Write failing tests**

```python
# tests/test_proposals_cli.py
"""Tests for the proposals CLI commands."""

from nebulus_atom.commands.proposals import format_proposal_list, format_proposal_detail
from nebulus_swarm.overlord.proposals import (
    EnhancementProposal,
    ProposalStatus,
    ProposalType,
)


class TestFormatProposalList:
    def test_empty_list(self):
        output = format_proposal_list([])
        assert "No pending proposals" in output

    def test_formats_proposals(self):
        proposals = [
            EnhancementProposal(
                type=ProposalType.NEW_SKILL,
                title="Add React skill",
                rationale="Failures",
                proposed_action="Create skill",
            ),
        ]
        output = format_proposal_list(proposals)
        assert "Add React skill" in output
        assert "new_skill" in output


class TestFormatProposalDetail:
    def test_shows_all_fields(self):
        p = EnhancementProposal(
            type=ProposalType.TOOL_FIX,
            title="Fix linter",
            rationale="Ruff config wrong",
            proposed_action="Update .ruff.toml",
            estimated_impact="Low",
            risk="Low",
        )
        output = format_proposal_detail(p)
        assert "Fix linter" in output
        assert "Ruff config wrong" in output
        assert "Update .ruff.toml" in output
```

**Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_proposals_cli.py -q`
Expected: ImportError.

**Step 3: Implement CLI module**

```python
# nebulus_atom/commands/proposals.py
"""CLI commands for managing enhancement proposals."""

from typing import List

from nebulus_swarm.overlord.proposals import EnhancementProposal


def format_proposal_list(proposals: List[EnhancementProposal]) -> str:
    """Format a list of proposals for terminal display."""
    if not proposals:
        return "No pending proposals."

    lines = []
    for p in proposals:
        lines.append(f"  [{p.type.value}] {p.title}")
        lines.append(f"    ID: {p.id[:8]}...  Status: {p.status.value}")
        lines.append("")
    return "\n".join(lines)


def format_proposal_detail(proposal: EnhancementProposal) -> str:
    """Format a single proposal with full detail."""
    lines = [
        f"Proposal: {proposal.title}",
        f"Type: {proposal.type.value}",
        f"Status: {proposal.status.value}",
        f"Impact: {proposal.estimated_impact}  Risk: {proposal.risk}",
        "",
        "Rationale:",
        f"  {proposal.rationale}",
        "",
        "Proposed Action:",
        f"  {proposal.proposed_action}",
    ]
    if proposal.related_issues:
        lines.append("")
        lines.append(f"Related Issues: {', '.join(f'#{i}' for i in proposal.related_issues)}")
    return "\n".join(lines)
```

**Step 4: Run tests**

Run: `venv/bin/python -m pytest tests/test_proposals_cli.py -q`
Expected: All pass.

**Step 5: Add `proposals` command to `main.py`**

Add to `nebulus_atom/main.py` after the `review_pr` command:

```python
@app.command()
def proposals(
    action: str = typer.Argument(..., help="Action: 'list', 'approve <id>', 'reject <id>'"),
    proposal_id: Optional[str] = typer.Argument(None, help="Proposal ID (for approve/reject)"),
):
    """Manage enhancement proposals."""
    from nebulus_atom.commands.proposals import format_proposal_list, format_proposal_detail
    # Implementation wired later when ProposalStore path is configured
    console = Console()
    console.print(f"[yellow]proposals {action} — not yet wired to store[/yellow]")
```

**Step 6: Commit**

```bash
git add nebulus_atom/commands/proposals.py tests/test_proposals_cli.py nebulus_atom/main.py
git commit -m "feat: add proposals CLI commands and formatters"
```

---

### Task 8: State DB — Add Evaluations and Proposals Tables

**Files:**
- Modify: `nebulus_swarm/overlord/state.py:42-94` (_init_db)
- Add tests to: `tests/test_evaluator.py`

**Step 1: Write failing test**

Add to `tests/test_evaluator.py`:

```python
class TestEvaluationStorage:
    def test_store_and_retrieve_evaluation(self, tmp_path):
        from nebulus_swarm.overlord.state import OverlordState

        state = OverlordState(db_path=str(tmp_path / "test.db"))
        result = EvaluationResult(
            pr_number=42,
            repo="owner/repo",
            test_score=CheckScore.PASS,
            lint_score=CheckScore.PASS,
            review_score=CheckScore.NEEDS_REVISION,
            revision_number=1,
            review_feedback="Needs error handling",
        )
        state.save_evaluation(result)
        history = state.get_evaluations(repo="owner/repo", pr_number=42)
        assert len(history) == 1
        assert history[0]["review_score"] == "needs_revision"
```

**Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_evaluator.py::TestEvaluationStorage -q`
Expected: AttributeError — `save_evaluation` not defined.

**Step 3: Add evaluations table to state.py**

Add to `_init_db()` in `nebulus_swarm/overlord/state.py`:

```python
cursor.execute("""
    CREATE TABLE IF NOT EXISTS evaluations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pr_number INTEGER NOT NULL,
        repo TEXT NOT NULL,
        test_score TEXT NOT NULL,
        lint_score TEXT NOT NULL,
        review_score TEXT NOT NULL,
        overall TEXT NOT NULL,
        revision_number INTEGER DEFAULT 0,
        feedback TEXT,
        evaluated_at TEXT NOT NULL
    )
""")
```

Add methods:

```python
def save_evaluation(self, result: "EvaluationResult") -> None:
    from nebulus_swarm.overlord.evaluator import EvaluationResult
    with self._get_connection() as conn:
        conn.execute(
            """INSERT INTO evaluations
               (pr_number, repo, test_score, lint_score, review_score,
                overall, revision_number, feedback, evaluated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result.pr_number, result.repo,
                result.test_score.value, result.lint_score.value,
                result.review_score.value, result.overall.value,
                result.revision_number, result.combined_feedback,
                result.timestamp.isoformat(),
            ),
        )

def get_evaluations(self, repo: str, pr_number: int) -> List[dict]:
    with self._get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM evaluations WHERE repo = ? AND pr_number = ? ORDER BY evaluated_at",
            (repo, pr_number),
        ).fetchall()
        return [dict(r) for r in rows]
```

**Step 4: Run tests**

Run: `venv/bin/python -m pytest tests/test_evaluator.py -q`
Expected: All pass.

**Step 5: Commit**

```bash
git add nebulus_swarm/overlord/state.py tests/test_evaluator.py
git commit -m "feat: add evaluations table to Overlord state DB"
```

---

### Task 9: Run Full Test Suite and Final Commit

**Step 1: Run all tests**

Run: `venv/bin/python -m pytest tests/ -q`
Expected: 642+ tests pass, 0 failures.

**Step 2: Verify no broken imports**

Run: `venv/bin/python -c "from nebulus_swarm.overlord.evaluator import Evaluator; from nebulus_swarm.overlord.scope import ScopeConfig; from nebulus_swarm.overlord.proposals import ProposalStore; print('All imports OK')"`

**Step 3: Final integration commit (if any unstaged changes)**

```bash
git add -A
git commit -m "chore: Phase 2 integration cleanup"
```
