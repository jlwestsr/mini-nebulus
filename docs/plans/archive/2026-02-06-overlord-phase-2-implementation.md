# Overlord Phase 2: Dispatch + Autonomy — Implementation Plan

**Author:** West AI Labs
**Date:** 2026-02-06
**Status:** Implementation Plan
**Phase:** 2 of 5

---

## Context

Phase 1 shipped the foundation: project registry, scanner, dependency graph, action scope model, and cross-project memory (110 tests). Phase 2 adds the ability to **dispatch actions** across multiple projects with **configurable autonomy levels**.

This is the bridge from "observe and report" to "propose and execute."

---

## Goals

1. **Autonomy Engine** — Three levels (cautious/proactive/scheduled) with runtime switching
2. **Multi-repo Dispatch** — Coordinate tasks across multiple projects
3. **Model Router** — Intelligent task-to-model assignment (local → cloud-fast → cloud-heavy)
4. **Release Coordination** — Automated multi-repo releases with dependency awareness
5. **Pre-approved Actions** — Allow scheduled mode to auto-execute safe operations

---

## Architecture

### 1. Autonomy Engine

Manages the "how much freedom does the Overlord have?" question.

**Module:** `nebulus_swarm/overlord/autonomy.py`

```python
@dataclass
class AutonomyConfig:
    """Per-project autonomy configuration."""
    project: str
    level: str  # "cautious", "proactive", "scheduled"
    pre_approved_actions: list[str] = field(default_factory=list)
    escalation_rules: dict[str, str] = field(default_factory=dict)

class AutonomyEngine:
    """Manages autonomy levels and action approval."""

    def __init__(self, config: OverlordConfig):
        self.config = config
        self._load_autonomy_config()

    def get_level(self, project: str) -> str:
        """Get effective autonomy level for a project."""
        # Check project-specific override, fall back to global
        return self.config.autonomy_overrides.get(
            project, self.config.autonomy_global
        )

    def can_auto_execute(self, action: str, scope: ActionScope) -> bool:
        """Check if action can auto-execute under current autonomy."""
        level = self.get_level(scope.projects[0] if scope.projects else "")

        # Cautious: nothing auto-executes
        if level == "cautious":
            return False

        # Proactive: only read-only actions
        if level == "proactive":
            return not scope.affects_remote and not scope.destructive

        # Scheduled: check pre-approved list
        if level == "scheduled":
            return self._is_pre_approved(action, scope)

        return False

    def should_propose(self, action: str, scope: ActionScope) -> bool:
        """Check if Overlord should proactively propose this action."""
        level = self.get_level(scope.projects[0] if scope.projects else "")

        # Cautious: never proposes
        if level == "cautious":
            return False

        # Proactive: proposes low-medium impact actions
        if level == "proactive":
            return scope.estimated_impact in ("low", "medium")

        # Scheduled: proposes anything outside pre-approved list
        if level == "scheduled":
            return not self._is_pre_approved(action, scope)

        return False

    def _is_pre_approved(self, action: str, scope: ActionScope) -> bool:
        """Check if action is in the pre-approved list."""
        # Pre-approved actions are defined per-project in config
        # Examples: "merge develop to main", "clean stale branches", "run tests"
        for project in scope.projects:
            config = self._get_project_autonomy(project)
            if action in config.pre_approved_actions:
                return True
        return False
```

**Config schema:**

```yaml
# ~/.atom/overlord.yml
autonomy:
  global: proactive

  overrides:
    nebulus-core: cautious  # Core is critical — always ask
    nebulus-gantry: scheduled  # Gantry can run nightly tasks

  pre_approved:
    # Actions that 'scheduled' mode can auto-execute
    nebulus-gantry:
      - "clean stale branches"
      - "run tests"
      - "update dependency versions"
    nebulus-prime:
      - "run tests"
      - "clean stale branches"
```

---

### 2. Dispatch Engine

Coordinates task execution across multiple projects with blast radius awareness.

**Module:** `nebulus_swarm/overlord/dispatch.py`

```python
@dataclass
class DispatchPlan:
    """A multi-step execution plan."""
    task: str
    steps: list[DispatchStep]
    scope: ActionScope
    estimated_duration: int  # seconds
    requires_approval: bool

@dataclass
class DispatchStep:
    """A single atomic step in a dispatch plan."""
    action: str
    project: str
    dependencies: list[str]  # IDs of steps that must complete first
    model_tier: str  # "local", "cloud-fast", "cloud-heavy", or None
    timeout: int

class DispatchEngine:
    """Coordinates task execution across multiple projects."""

    def __init__(
        self,
        config: OverlordConfig,
        autonomy: AutonomyEngine,
        graph: DependencyGraph,
        model_router: ModelRouter,
    ):
        self.config = config
        self.autonomy = autonomy
        self.graph = graph
        self.router = model_router

    def plan(self, task: str) -> DispatchPlan:
        """Convert a high-level task into an execution plan."""
        # Parse task (e.g., "merge Core develop to main and tag v0.2.0")
        # Return plan with steps, dependencies, scope
        pass

    def execute(self, plan: DispatchPlan) -> DispatchResult:
        """Execute a dispatch plan."""
        # Check autonomy — can we auto-execute or need approval?
        if plan.requires_approval:
            if not self._get_user_approval(plan):
                return DispatchResult(status="cancelled", reason="User denied")

        # Execute steps in dependency order
        results = []
        for step in self._topological_order(plan.steps):
            result = self._execute_step(step)
            results.append(result)
            if not result.success:
                return DispatchResult(status="failed", steps=results)

        return DispatchResult(status="success", steps=results)

    def _execute_step(self, step: DispatchStep) -> StepResult:
        """Execute a single step."""
        if step.model_tier:
            # LLM-powered step — dispatch to worker
            return self._dispatch_to_worker(step)
        else:
            # Direct execution (git command, script, etc.)
            return self._execute_direct(step)
```

**Key patterns:**

1. **Task decomposition** — Break "release Core v0.2.0" into:
   - Check tests pass
   - Merge develop → main
   - Tag v0.2.0
   - Update dependents (Prime, Edge, Forge)
   - Run tests on dependents
   - Push if all pass

2. **Dependency resolution** — Use graph to determine order (Core before Prime)

3. **Blast radius awareness** — Evaluate scope before execution, escalate if too broad

4. **Rollback on failure** — If step 3 fails, undo steps 1-2

---

### 3. Model Router

Maps tasks to the right model tier based on complexity and cost.

**Module:** `nebulus_swarm/overlord/model_router.py`

```python
@dataclass
class ModelEndpoint:
    """An available model endpoint."""
    name: str
    endpoint: str
    model: str
    tier: str  # "local", "cloud-fast", "cloud-heavy"
    concurrent: int
    health_check_url: str

class ModelRouter:
    """Routes tasks to appropriate model tiers."""

    def __init__(self, config: OverlordConfig):
        self.endpoints = self._load_endpoints(config)
        self.tier_preference = ["local", "cloud-fast", "cloud-heavy"]

    def select_model(self, task_type: str, complexity: str = "medium") -> ModelEndpoint:
        """Select the best model for a task."""
        # Task type → tier mapping
        tier = self._infer_tier(task_type, complexity)

        # Find healthy endpoint in that tier
        for endpoint in self._get_tier_endpoints(tier):
            if self._is_healthy(endpoint):
                return endpoint

        # Fallback to next tier
        return self._fallback(tier)

    def _infer_tier(self, task_type: str, complexity: str) -> str:
        """Map task type + complexity to tier."""
        # Mechanical tasks → local
        if task_type in ("format", "lint", "boilerplate"):
            return "local"

        # Feature implementation → local (if available)
        if task_type == "feature" and complexity in ("low", "medium"):
            return "local"

        # Code review → cloud-fast (Haiku is good at this)
        if task_type == "review":
            return "cloud-fast"

        # Architecture, planning → cloud-heavy (needs reasoning)
        if task_type in ("architecture", "planning", "debugging"):
            if complexity == "high":
                return "cloud-heavy"
            return "cloud-fast"

        return "cloud-fast"  # Default

    def _is_healthy(self, endpoint: ModelEndpoint) -> bool:
        """Check if endpoint is responding."""
        try:
            response = requests.get(
                endpoint.health_check_url, timeout=2
            )
            return response.status_code == 200
        except:
            return False
```

**Tier mapping table:**

| Task Type | Complexity | Tier | Model |
|-----------|-----------|------|-------|
| Git chores | - | None | Direct execution |
| Code formatting | - | local | Either 14B or 30B |
| Linting fixes | - | local | Either 14B or 30B |
| Boilerplate | - | local | Prefer 30B |
| Feature (simple) | low | local | Prefer 30B |
| Feature (moderate) | medium | local | Prefer 30B |
| Feature (complex) | high | cloud-fast | Haiku |
| Code review | medium | cloud-fast | Haiku |
| Debugging | high | cloud-heavy | Sonnet |
| Architecture | high | cloud-heavy | Sonnet |
| Planning | high | cloud-heavy | Sonnet |

**Health checking:**

- Hit `/health` on each local endpoint at startup
- Refresh health status every 5 minutes
- If local backend is down, fall back to cloud tier automatically

---

### 4. Release Coordinator

Automates coordinated releases across dependent projects.

**Module:** `nebulus_swarm/overlord/release.py`

```python
@dataclass
class ReleaseSpec:
    """Specification for a coordinated release."""
    project: str
    version: str
    source_branch: str = "develop"
    target_branch: str = "main"
    update_dependents: bool = True
    push_to_remote: bool = False

class ReleaseCoordinator:
    """Coordinates releases across dependent projects."""

    def __init__(
        self,
        config: OverlordConfig,
        graph: DependencyGraph,
        dispatch: DispatchEngine,
        memory: OverlordMemory,
    ):
        self.config = config
        self.graph = graph
        self.dispatch = dispatch
        self.memory = memory

    def plan_release(self, spec: ReleaseSpec) -> DispatchPlan:
        """Plan a coordinated release."""
        steps = []

        # Step 1: Validate source project
        steps.append(DispatchStep(
            action="validate_tests",
            project=spec.project,
            dependencies=[],
            model_tier=None,
            timeout=300,
        ))

        # Step 2: Merge + tag
        steps.append(DispatchStep(
            action=f"merge {spec.source_branch} to {spec.target_branch}",
            project=spec.project,
            dependencies=["validate_tests"],
            model_tier=None,
            timeout=60,
        ))

        steps.append(DispatchStep(
            action=f"tag {spec.version}",
            project=spec.project,
            dependencies=[f"merge {spec.source_branch} to {spec.target_branch}"],
            model_tier=None,
            timeout=30,
        ))

        # Step 3: Update dependents (if requested)
        if spec.update_dependents:
            downstream = self.graph.get_downstream(spec.project)
            for dep_project in downstream:
                steps.append(DispatchStep(
                    action=f"update {spec.project} to {spec.version}",
                    project=dep_project,
                    dependencies=[f"tag {spec.version}"],
                    model_tier=None,
                    timeout=120,
                ))

                steps.append(DispatchStep(
                    action="validate_tests",
                    project=dep_project,
                    dependencies=[f"update {spec.project} to {spec.version}"],
                    model_tier=None,
                    timeout=300,
                ))

        # Step 4: Push (if requested)
        if spec.push_to_remote:
            affected = self.graph.get_affected_by(spec.project)
            steps.append(DispatchStep(
                action="push to remote",
                project=spec.project,
                dependencies=[f"tag {spec.version}"],
                model_tier=None,
                timeout=60,
            ))

        scope = ActionScope(
            projects=self.graph.get_affected_by(spec.project),
            branches=[spec.source_branch, spec.target_branch],
            destructive=False,
            reversible=False if spec.push_to_remote else True,
            affects_remote=spec.push_to_remote,
            estimated_impact="high",
        )

        return DispatchPlan(
            task=f"Release {spec.project} {spec.version}",
            steps=steps,
            scope=scope,
            estimated_duration=sum(s.timeout for s in steps),
            requires_approval=True,  # Releases always need approval
        )

    def execute_release(self, spec: ReleaseSpec) -> DispatchResult:
        """Execute a coordinated release."""
        plan = self.plan_release(spec)
        result = self.dispatch.execute(plan)

        # Log to memory
        if result.status == "success":
            self.memory.remember(
                category="release",
                content=f"{spec.project} {spec.version} released",
                project=spec.project,
                downstream_updated=self.graph.get_downstream(spec.project),
            )

        return result
```

**Example workflow:**

```bash
# User command
nebulus-atom overlord release nebulus-core v0.2.0

# Overlord plans:
1. Run tests on Core
2. Merge develop → main
3. Tag v0.2.0
4. Update Core version in Prime, Edge, Forge
5. Run tests on Prime, Edge, Forge
6. Ask: "All tests pass. Push to remote?"

# User approves
Overlord pushes Core, Prime, Edge, Forge
Overlord logs the coordinated release to memory
```

---

## Implementation Steps

### Step 1: Autonomy Engine (2 modules + CLI + tests)

**Files to create:**

| File | Purpose |
|------|---------|
| `nebulus_swarm/overlord/autonomy.py` | AutonomyEngine, AutonomyConfig |
| `tests/test_overlord_autonomy.py` | 15-20 tests |

**Files to modify:**

| File | Change |
|------|--------|
| `nebulus_swarm/overlord/registry.py` | Add `pre_approved` to autonomy config schema |
| `nebulus_atom/commands/overlord_commands.py` | Add `overlord autonomy` command group |
| `tests/test_overlord_commands.py` | Add CLI tests for autonomy commands |

**CLI commands:**

```bash
overlord autonomy                           # Show current levels
overlord autonomy --global proactive        # Set global level
overlord autonomy --project core cautious   # Override for project
overlord autonomy --list-approved           # Show pre-approved actions
```

**Tests:**

- Can auto-execute under scheduled mode if pre-approved
- Cannot auto-execute under cautious mode
- Proactive mode proposes low/medium impact actions
- Project overrides beat global settings
- Escalation for high-impact actions

**Deliverable:** ~500 lines code + 20 tests

---

### Step 2: Model Router (1 module + tests)

**Files to create:**

| File | Purpose |
|------|---------|
| `nebulus_swarm/overlord/model_router.py` | ModelRouter, ModelEndpoint |
| `tests/test_overlord_model_router.py` | 15-20 tests |

**Files to modify:**

| File | Change |
|------|--------|
| `nebulus_swarm/overlord/registry.py` | Add `models` section to config schema |

**Config schema:**

```yaml
models:
  local-prime:
    endpoint: http://localhost:5000/v1
    model: Qwen2.5-Coder-14B
    tier: local
    concurrent: 2
  local-edge:
    endpoint: http://nebulus:8080/v1
    model: qwen3-coder-30b
    tier: local
    concurrent: 2
  cloud-fast:
    endpoint: https://api.anthropic.com/v1
    model: claude-haiku-4-5-20251001
    tier: cloud-fast
    concurrent: 10
  cloud-heavy:
    endpoint: https://api.anthropic.com/v1
    model: claude-sonnet-4-5-20250929
    tier: cloud-heavy
    concurrent: 3
```

**Tests:**

- Task type → tier mapping
- Health check behavior
- Fallback to next tier when primary is down
- Concurrent request limiting
- User override (force a tier)

**Deliverable:** ~400 lines code + 20 tests

---

### Step 3: Dispatch Engine (2 modules + CLI + tests)

**Files to create:**

| File | Purpose |
|------|---------|
| `nebulus_swarm/overlord/dispatch.py` | DispatchEngine, DispatchPlan, DispatchStep |
| `nebulus_swarm/overlord/task_parser.py` | Natural language task → DispatchPlan |
| `tests/test_overlord_dispatch.py` | 20-25 tests |
| `tests/test_overlord_task_parser.py` | 10-15 tests |

**Files to modify:**

| File | Change |
|------|--------|
| `nebulus_atom/commands/overlord_commands.py` | Add `overlord dispatch` command |
| `tests/test_overlord_commands.py` | Add dispatch CLI tests |

**CLI command:**

```bash
overlord dispatch "merge Core develop to main"
overlord dispatch "clean stale branches in Prime and Edge"
overlord dispatch "run tests across all projects"
overlord dispatch "release Core v0.2.0" --push
```

**Tests:**

- Task parsing (string → plan)
- Dependency ordering of steps
- Blast radius calculation
- Autonomy check integration
- Rollback on failure
- Direct execution (git commands)
- Worker dispatch (LLM-powered tasks)

**Deliverable:** ~800 lines code + 35 tests

---

### Step 4: Release Coordinator (1 module + CLI + tests)

**Files to create:**

| File | Purpose |
|------|---------|
| `nebulus_swarm/overlord/release.py` | ReleaseCoordinator, ReleaseSpec |
| `tests/test_overlord_release.py` | 15-20 tests |

**Files to modify:**

| File | Change |
|------|--------|
| `nebulus_atom/commands/overlord_commands.py` | Add `overlord release` command |
| `tests/test_overlord_commands.py` | Add release CLI tests |

**CLI command:**

```bash
overlord release nebulus-core v0.2.0                  # Plan only
overlord release nebulus-core v0.2.0 --execute        # Plan + execute
overlord release nebulus-core v0.2.0 --push           # Push after success
overlord release nebulus-core v0.2.0 --no-dependents  # Skip downstream updates
```

**Tests:**

- Release plan generation
- Downstream update steps
- Test validation at each stage
- Push gating
- Memory logging
- Rollback on test failure

**Deliverable:** ~600 lines code + 20 tests

---

### Step 5: Integration + End-to-End Tests

**Files to create:**

| File | Purpose |
|------|---------|
| `tests/test_overlord_e2e.py` | End-to-end dispatch workflows |

**Test scenarios:**

1. **Cautious mode** — propose merge, wait for approval, execute
2. **Proactive mode** — auto-propose stale branch cleanup
3. **Scheduled mode** — auto-execute pre-approved actions
4. **Release flow** — Core release → update Prime → run tests → push
5. **Fallback routing** — local backend down → cloud-fast
6. **Failure rollback** — step 3 fails → undo steps 1-2

**Deliverable:** ~400 lines code + 10 E2E tests

---

## Test Summary

| Module | Unit Tests | E2E Tests | Total |
|--------|-----------|-----------|-------|
| Autonomy Engine | 20 | - | 20 |
| Model Router | 20 | - | 20 |
| Dispatch Engine | 35 | - | 35 |
| Release Coordinator | 20 | - | 20 |
| Integration | - | 10 | 10 |
| **Total** | **95** | **10** | **105** |

**Phase 1 + Phase 2 = 215 tests**

---

## Configuration Reference

Full `~/.atom/overlord.yml` with Phase 2 additions:

```yaml
# ─── Projects (Phase 1) ──────────────────────────────
projects:
  nebulus-core:
    path: ~/projects/west_ai_labs/nebulus-core
    remote: jlwestsr/nebulus-core
    role: shared-library
    branch_model: develop-main
    depends_on: []

# ─── Autonomy (Phase 2) ──────────────────────────────
autonomy:
  global: proactive

  overrides:
    nebulus-core: cautious
    nebulus-gantry: scheduled

  pre_approved:
    nebulus-gantry:
      - "clean stale branches"
      - "run tests"
      - "update dependency versions"
    nebulus-prime:
      - "run tests"
      - "clean stale branches"

# ─── Models (Phase 2) ────────────────────────────────
models:
  local-prime:
    endpoint: http://localhost:5000/v1
    model: Qwen2.5-Coder-14B
    tier: local
    concurrent: 2
    health_check_url: http://localhost:5000/health

  local-edge:
    endpoint: http://nebulus:8080/v1
    model: qwen3-coder-30b
    tier: local
    concurrent: 2
    health_check_url: http://nebulus:8080/health

  cloud-fast:
    endpoint: https://api.anthropic.com/v1
    model: claude-haiku-4-5-20251001
    tier: cloud-fast
    concurrent: 10

  cloud-heavy:
    endpoint: https://api.anthropic.com/v1
    model: claude-sonnet-4-5-20250929
    tier: cloud-heavy
    concurrent: 3

# ─── Dispatch (Phase 2) ──────────────────────────────
dispatch:
  max_concurrent_steps: 5
  step_timeout_default: 300
  rollback_on_failure: true
```

---

## Success Criteria

Phase 2 is complete when:

1. **Autonomy levels work** — Cautious blocks everything, proactive proposes, scheduled auto-executes pre-approved
2. **Model router works** — Tasks route to correct tier, fallback on health check failure
3. **Dispatch executes plans** — Multi-step plans run in dependency order
4. **Release coordinator works** — "release Core v0.2.0" updates downstream and runs their tests
5. **All 105 tests pass** — Unit + E2E coverage
6. **CLI is usable** — `overlord dispatch`, `overlord release`, `overlord autonomy` commands work end-to-end

---

## Open Questions

1. **Task parsing** — Use LLM to parse natural language tasks, or hand-rolled parser with pattern matching?
2. **Worker pool** — Reuse existing DockerManager as-is, or extend it for multi-project awareness?
3. **Approval UX** — CLI-only approval (blocking), or also support async approval via Slack/Gantry?
4. **State persistence** — Should in-flight dispatch plans persist to disk in case Overlord crashes?
5. **Telemetry** — Track dispatch outcomes (duration, model used, success/failure) for observability in Phase 5?

---

## Dependencies

**Requires from Phase 1:**
- `registry.py` — Project config
- `graph.py` — Dependency traversal
- `action_scope.py` — Blast radius evaluation
- `memory.py` — Logging dispatch outcomes

**Requires from existing Swarm:**
- `docker_manager.py` — Minion container orchestration
- `llm_pool.py` — Concurrent LLM request handling (will become ModelRouter)

**New external dependencies:**
- None — uses existing `requests`, `pyyaml`, `rich`, `typer`

---

## Timeline Estimate

| Task | Effort | Duration |
|------|--------|----------|
| Step 1: Autonomy Engine | 500 lines + 20 tests | 1 day |
| Step 2: Model Router | 400 lines + 20 tests | 1 day |
| Step 3: Dispatch Engine | 800 lines + 35 tests | 2 days |
| Step 4: Release Coordinator | 600 lines + 20 tests | 1 day |
| Step 5: Integration + E2E | 400 lines + 10 tests | 1 day |
| **Total** | **2,700 lines + 105 tests** | **6 days** |

This assumes full-time focused work. With testing, debugging, and iteration, expect 7-10 days.

---

## Next Steps

Ready to proceed with Step 1 (Autonomy Engine)?
