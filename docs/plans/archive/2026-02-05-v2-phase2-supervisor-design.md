# V2 Phase 2: Supervisor/Worker Formalization

**Date:** 2026-02-05
**Status:** Approved Design
**Prerequisite:** V2 Phase 1 (complete)

## Overview

Phase 2 adds a quality gate, enhancement proposals, worker scope enforcement, and skill evolution to the existing Overlord/Minion architecture. All four features are implemented as extensions to the Overlord — no new services.

## 1. Evaluation Layer

**Module:** `nebulus_swarm/overlord/evaluator.py`

After a Minion completes work and creates a PR, the Overlord invokes the Evaluator instead of immediately posting to Slack.

### Evaluation Steps

1. **Tests** — Run `pytest` on the PR branch via `CheckRunner` from the reviewer module.
2. **Lint** — Run ruff/flake8 on changed files.
3. **LLM Review** — Existing `LLMReviewer` with pass/fail/revise decision.

Each check produces a score: `PASS`, `FAIL`, or `NEEDS_REVISION`. Overall result: pass if all pass, revise if any need revision, fail if any hard-fail.

### Revision Cycle

Maximum 2 revisions (3 total attempts):

1. Evaluator creates a `RevisionRequest` with specific feedback (test output, review issues).
2. Overlord spawns a new Minion container on the **same branch** with revision context injected into the system prompt.
3. Revision Minion has access to the original issue + evaluator feedback.
4. After revision, Evaluator runs again.
5. After 2 failed revisions, escalate to user via Slack.

### Data Model

```python
@dataclass
class EvaluationResult:
    pr_number: int
    repo: str
    test_score: CheckScore        # PASS | FAIL | NEEDS_REVISION
    lint_score: CheckScore
    review_score: CheckScore
    overall: CheckScore
    feedback: str                  # Combined feedback for revision
    revision_number: int           # 0 = first attempt
    timestamp: datetime

class CheckScore(Enum):
    PASS = "pass"
    FAIL = "fail"
    NEEDS_REVISION = "needs_revision"
```

Evaluation history stored in Overlord's SQLite state DB.

### Flow

```
Minion completes → creates PR → reports to Overlord
    │
    ▼
Evaluator.evaluate(repo, pr_number)
    │
    ├─ PASS → Post success to Slack, finalize PR
    ├─ NEEDS_REVISION (attempt < 3) → Spawn revision Minion on same branch
    └─ FAIL or max revisions → Escalate to user via Slack
```

## 2. Enhancement Proposal System

**Module:** `nebulus_swarm/overlord/proposals.py`

When the Evaluator identifies a capability gap, it creates a structured proposal for user approval. Proposals are **never auto-approved**.

### Triggers

- Same failure pattern across 2+ issues (e.g., "Minion keeps failing on React tests").
- Minion explicitly reports a blocker it cannot resolve.
- LLM review flags a systemic issue (e.g., "no error handling convention").

### Proposal Structure

```python
@dataclass
class EnhancementProposal:
    id: str                        # UUID
    type: ProposalType             # new_skill | tool_fix | config_change | workflow_improvement
    title: str
    rationale: str                 # What triggered it, evidence
    proposed_action: str           # What should be done
    estimated_impact: str          # Low | Medium | High
    risk: str                      # Low | Medium | High
    status: ProposalStatus         # pending | approved | rejected | implemented
    related_issues: list[int]      # Issue numbers that triggered this
    created_at: datetime
    resolved_at: Optional[datetime]

class ProposalType(Enum):
    NEW_SKILL = "new_skill"
    TOOL_FIX = "tool_fix"
    CONFIG_CHANGE = "config_change"
    WORKFLOW_IMPROVEMENT = "workflow_improvement"

class ProposalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    IMPLEMENTED = "implemented"
```

### Storage

SQLite table `proposals` in the Overlord state DB (same pattern as `minion_state`).

### User Interaction

**Slack:**
- Proposals posted to channel with Block Kit Approve/Reject buttons.
- Approval triggers dispatch (regular issue for most types, skill workflow for `new_skill`).

**CLI:**
- `nebulus-atom proposals list` — Show pending proposals.
- `nebulus-atom proposals approve <id>` — Approve a proposal.
- `nebulus-atom proposals reject <id>` — Reject with optional reason.

### Safety Constraint

The Overlord stores proposals and waits for user action. No autonomous self-improvement.

## 3. Worker Scope Enforcement

**Module:** `nebulus_swarm/overlord/scope.py`

The Overlord assigns each Minion a bounded file scope when dispatching work, restricting what the Minion can write to.

### Scope Assignment

1. Overlord analyzes the issue (labels, title, linked files) to determine relevant directories.
2. Overlord passes `MINION_SCOPE` env var to the container: JSON list of allowed path patterns.
   ```json
   ["src/components/**", "tests/components/**", "package.json"]
   ```
3. Minion's `ToolExecutor` loads scope on init and checks every write operation.

### Scope Modes

| Mode | Behavior | When Used |
|------|----------|-----------|
| `unrestricted` | No write restrictions (default) | Overlord can't determine scope |
| `directory` | Writes restricted to directories | Inferred from issue labels/file mentions |
| `explicit` | Writes restricted to exact file list | Targeted fixes |

### Enforcement

- **Reads**: Always allowed. Minion needs full context to understand the codebase.
- **Writes** (`write_file`, `edit_file`): Checked against scope. Blocked with error message if outside.
- **run_command**: Allowed. Working directory must be within workspace (existing check).
- **Violation**: Tool returns error explaining the restriction. Minion can ask a question to request expanded scope (routed to user via Slack).

### Implementation

Extend `nebulus_swarm/minion/agent/tool_executor.py`:

```python
class ToolExecutor:
    def __init__(self, workspace: Path, scope: Optional[ScopeConfig] = None):
        self.workspace = workspace
        self.scope = scope or ScopeConfig.unrestricted()

    def _check_write_scope(self, filepath: str) -> Optional[str]:
        """Return error message if write is outside scope, None if allowed."""
        if self.scope.mode == ScopeMode.UNRESTRICTED:
            return None
        # Check against allowed patterns...
```

No changes to the Minion agent itself — scope is enforced at the tool executor level, transparent to the LLM.

## 4. Skill Evolution Workflow

When a new skill is needed (identified via enhancement proposal or user request), the system follows a structured lifecycle.

### Lifecycle

1. **Draft** — Overlord generates a skill spec from the proposal context (name, description, triggers, instructions outline). Stored as a `SkillDraft` in SQLite.
2. **Approve** — User reviews via Slack or CLI (`nebulus-atom skills drafts`). Can modify triggers or instructions before approving.
3. **Implement** — Overlord dispatches a Minion to write the `.yaml` skill file following the existing schema (`nebulus_swarm/minion/skills/schema.py`). Minion gets the approved spec as issue context.
4. **Validate** — Evaluator checks: valid YAML, matches schema, triggers don't conflict with existing skills. LLM review confirms instructions are coherent.
5. **Deploy** — Skill file committed to `.nebulus/skills/` via PR. User merges.

### No Hot-Loading

Skills only become active after the PR is merged and the next Minion picks them up. The user always reviews skill content in a PR.

### Skill Registry

Overlord maintains a `skills` table tracking:
- Known skills and their origin (manual vs evolved)
- Usage count per skill
- Success rate (issues completed successfully when skill was loaded)

Low success rate feeds back into the proposal system — Evaluator can propose a skill revision.

## Integration Summary

```
Issue arrives (GitHub label or Slack command)
    │
    ▼
Overlord assigns scope (file patterns from issue analysis)
    │
    ▼
Minion executes (scoped ToolExecutor, loaded skills)
    │
    ▼
Evaluator runs (tests → lint → LLM review)
    │
    ├─ PASS → Post to Slack, finalize PR
    ├─ NEEDS_REVISION → Re-dispatch with feedback (max 2x)
    └─ FAIL (after retries) → Escalate to user via Slack
                                    │
                                    ▼
                        Evaluator detects pattern?
                        ├─ Yes → Create EnhancementProposal
                        │           │
                        │           ▼
                        │       User approves via Slack/CLI
                        │           │
                        │           ▼
                        │       type == new_skill?
                        │       ├─ Yes → Skill evolution workflow
                        │       └─ No  → Dispatch as regular issue
                        └─ No  → Done
```

## File Changes

### New Files

| File | Purpose |
|------|---------|
| `nebulus_swarm/overlord/evaluator.py` | EvaluationResult, Evaluator class, revision dispatch |
| `nebulus_swarm/overlord/proposals.py` | EnhancementProposal, ProposalStore, Slack formatting |
| `nebulus_swarm/overlord/scope.py` | ScopeConfig, ScopeMode, scope inference from issues |
| `nebulus_atom/commands/proposals.py` | CLI commands for proposal management |
| `tests/test_evaluator.py` | Evaluator tests |
| `tests/test_proposals.py` | Proposal system tests |
| `tests/test_scope.py` | Scope enforcement tests |

### Modified Files

| File | Change |
|------|--------|
| `nebulus_swarm/overlord/main.py` | Wire evaluator into post-completion, dispatch revisions |
| `nebulus_swarm/overlord/state.py` | Add `evaluations`, `proposals`, `skills` tables |
| `nebulus_swarm/minion/agent/tool_executor.py` | Add write-scope checking |
| `nebulus_swarm/minion/main.py` | Load `MINION_SCOPE` env var, pass to ToolExecutor |
| `nebulus_swarm/overlord/slack_bot.py` | Proposal buttons, evaluation summaries |
| `nebulus_atom/main.py` | Add `proposals` CLI command group |

## Implementation Order

1. **Evaluator** (item 6) — Foundation. Tests + lint + LLM review pipeline, revision dispatch.
2. **Scope enforcement** (item 8) — Independent. ToolExecutor changes + scope env var.
3. **Proposals** (item 7) — Depends on evaluator for pattern detection. SQLite + Slack + CLI.
4. **Skill evolution** (item 9) — Depends on proposals. Draft/approve/implement lifecycle.

## Testing Strategy

Each module gets its own test file with mocked dependencies:
- Evaluator: Mock CheckRunner, LLMReviewer, test scoring logic and revision dispatch
- Scope: Test pattern matching, violation detection, unrestricted mode
- Proposals: Test CRUD, status transitions, Slack formatting
- Skill evolution: Test lifecycle state machine, validation
