# Overlord: Cross-Project Meta-Orchestrator

**Author:** West AI Labs
**Date:** 2026-02-05
**Status:** Phase 1 Complete
**Atom Version:** V3 (evolves the existing Swarm Overlord)

---

## 1. Vision

The Overlord is the evolution of Atom's Swarm supervisor into a **cross-project
meta-orchestrator**. Where the current Overlord dispatches Minions to work on
individual GitHub issues within a single repo, the new Overlord thinks across the
entire Nebulus ecosystem — understanding project relationships, dispatching agents
to multiple repos simultaneously, managing releases, enforcing standards, and
learning from every interaction.

The Overlord is what you'd get if a senior engineering manager had perfect memory,
never slept, and could spin up junior engineers on demand.

### What the Overlord Does

- **Observes**: Scans all managed repos for git state, open issues, stale branches,
  test health, dependency drift, and changelog gaps
- **Decides**: Prioritizes work across projects, identifies cross-repo dependencies,
  selects the right agent and model for each task
- **Dispatches**: Spawns Minion workers for implementation tasks, or executes
  lightweight chores (merges, tags, pushes) directly
- **Verifies**: Evaluates worker output, runs tests, reviews PRs before reporting
  completion
- **Learns**: Maintains cross-project memory — patterns, preferences, pitfalls,
  and project relationships
- **Reports**: Provides status summaries at any level of detail, from a quick
  health check to a full ecosystem audit

### What the Overlord Does NOT Do

- **Write code itself** — it dispatches workers for implementation
- **Push without approval** — the human-in-the-loop trust boundary is sacred
- **Modify its own capabilities** — skill evolution requires explicit user approval
- **Cross the trust boundary** — workers cannot escalate privileges through the
  Overlord

---

## 2. Architecture

### 2.1 Evolution, Not Revolution

The Overlord **replaces** the current `nebulus_swarm/overlord/` codebase. This is
not a new layer — it is an upgrade of the existing supervisor from single-repo
to multi-repo awareness. All existing capabilities (Docker-based Minion dispatch,
GitHub queue, Slack bot, evaluation, audit trail) are preserved and extended.

```
┌─────────────────────────────────────────────────────────┐
│                        USER                             │
│         (Human-in-the-Loop — Trust Boundary)            │
├──────────┬──────────────────┬───────────────────────────┤
│   CLI    │     Slack Bot    │      Gantry UI            │
│ (power)  │  (async/notify)  │   (dashboard/visual)      │
├──────────┴──────────────────┴───────────────────────────┤
│                  INTERFACE ADAPTER LAYER                 │
│           Normalizes commands + renders responses        │
├─────────────────────────────────────────────────────────┤
│                      OVERLORD CORE                      │
│                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  Autonomy   │  │   Project    │  │   Dispatch    │  │
│  │  Engine     │  │   Registry   │  │   Engine      │  │
│  │             │  │              │  │               │  │
│  │ • cron      │  │ • repo map   │  │ • minion pool │  │
│  │ • watchers  │  │ • dep graph  │  │ • model router│  │
│  │ • triggers  │  │ • standards  │  │ • scope mgr   │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  │
│                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  Evaluator  │  │   Memory     │  │   Audit       │  │
│  │             │  │   (Cross-    │  │   Trail       │  │
│  │ • tests     │  │    Project)  │  │               │  │
│  │ • lint      │  │ • patterns   │  │ • hash chain  │  │
│  │ • review    │  │ • preferences│  │ • signatures  │  │
│  │ • scoring   │  │ • relations  │  │ • compliance  │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  │
├─────────────────────────────────────────────────────────┤
│                    MINION WORKERS                        │
│        (Ephemeral containers, scoped to task)            │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Core Components

#### Project Registry

The Overlord maintains a registry of all managed projects with their metadata,
relationships, and health state.

```yaml
# ~/.atom/overlord.yml
projects:
  nebulus-core:
    path: ~/projects/west_ai_labs/nebulus-core
    remote: jlwestsr/nebulus-core
    role: shared-library
    branch_model: develop-main
    depends_on: []

  nebulus-prime:
    path: ~/projects/west_ai_labs/nebulus-prime
    remote: jlwestsr/nebulus-prime
    role: platform-deployment
    branch_model: develop-main
    depends_on: [nebulus-core]

  nebulus-edge:
    path: ~/projects/west_ai_labs/nebulus-edge
    remote: jlwestsr/nebulus-edge
    role: platform-deployment
    branch_model: develop-main
    depends_on: [nebulus-core]

  nebulus-atom:
    path: ~/projects/west_ai_labs/nebulus-atom
    remote: jlwestsr/nebulus-atom
    role: tooling
    branch_model: develop-main
    depends_on: []

  nebulus-gantry:
    path: ~/projects/west_ai_labs/nebulus-gantry
    remote: jlwestsr/nebulus-gantry
    role: frontend
    branch_model: develop-main
    depends_on: [nebulus-prime]

  nebulus-forge:
    path: ~/projects/west_ai_labs/nebulus-forge
    remote: jlwestsr/nebulus-forge
    role: tooling
    branch_model: develop-main
    depends_on: [nebulus-core]
```

**Fields:**

| Field | Purpose |
|-------|---------|
| `path` | Local filesystem path |
| `remote` | GitHub `owner/repo` |
| `role` | Semantic role: `shared-library`, `platform-deployment`, `frontend`, `tooling` |
| `branch_model` | Git workflow: `develop-main`, `trunk-based`, `gitflow` |
| `depends_on` | Upstream dependencies — changes here may require downstream updates |

#### Dependency Graph

The `depends_on` relationships form a DAG that the Overlord uses to:

- **Order releases**: Core must release before Prime/Edge can consume the update
- **Detect ripple effects**: A breaking change in Core triggers checks in all dependents
- **Coordinate multi-repo work**: "Update the LLM client" spans Core + Prime + Edge

```
nebulus-core ──────┬──▶ nebulus-prime ──▶ nebulus-gantry
                   ├──▶ nebulus-edge
                   └──▶ nebulus-forge

nebulus-atom (independent)
```

#### Autonomy Engine

The Overlord supports three autonomy levels, configurable per-project or globally.
The user can change levels at any time via CLI, Slack, or Gantry.

```yaml
# ~/.atom/overlord.yml
autonomy:
  global: proactive        # Default for all projects

  overrides:               # Per-project overrides
    nebulus-core: cautious  # Core is critical — always ask first
    nebulus-gantry: scheduled  # Gantry can run nightly health checks
```

| Level | Behavior | Example |
|-------|----------|---------|
| `cautious` | Command-only. Overlord observes and reports but never acts without an explicit command. | "Overlord, merge Core develop to main" |
| `proactive` | Scans and proposes. Overlord identifies work, presents a plan, and waits for approval before executing. | "I found 3 stale branches in Prime. Want me to clean them up?" |
| `scheduled` | Runs defined sweeps on a cron schedule. Executes pre-approved actions automatically, reports results. Escalates anything unexpected. | Nightly: run tests, check for dependency updates, clean stale branches. Report at 7 AM. |

**Escalation rule**: Regardless of autonomy level, the Overlord **always** escalates:
- Destructive operations (force push, branch delete, data migration)
- Cross-repo breaking changes
- Failed automated actions
- Anything outside the pre-approved action list

#### Dispatch Engine

Evolves the current `DockerManager` + `LLMPool` into a three-tier routing system.
The goal is to maximize local inference and minimize cloud token spend.

**Infrastructure: Dual-Machine Local Inference**

The ecosystem has **two machines** with local LLM capability:

```
┌─────────────────────────────────┐     ┌─────────────────────────────────┐
│  shurtugal-lnx (Dev Machine)   │     │  Mac Mini M4 Pro (Desk)         │
│                                 │     │                                 │
│  NVIDIA GPU + TabbyAPI          │     │  48GB Unified RAM + MLX         │
│  Qwen2.5-Coder-14B             │     │  qwen3-coder-30b (default)      │
│  ExLlamaV2                      │     │  qwen2.5-coder-32b             │
│  Port 5000                      │     │  llama3.1-8b                    │
│  Concurrent: 2                  │     │  Port 8080                      │
│                                 │     │  Managed by PM2                 │
│  Best for: fast mechanical      │     │  Best for: complex coding,      │
│  tasks while dev box is idle    │     │  feature impl, reviews          │
└─────────────────────────────────┘     └─────────────────────────────────┘
```

The Mac Mini is currently idle — activating it gives us a **30B-parameter coding
model for free**. With 48GB unified RAM, it can serve qwen3-coder-30b at good
speed on Apple Silicon with MLX. This is the primary workhorse for local inference.

**Three-Tier Model Router** (simplified from Gemini review feedback):

```yaml
# ~/.atom/overlord.yml
models:
  # Tier 1: Local inference — FREE, handles 60-70% of work
  local-prime:
    host: localhost                    # Linux dev machine
    endpoint: http://localhost:5000/v1
    model: Qwen2.5-Coder-14B
    tier: local
    concurrent: 2
    notes: TabbyAPI/ExLlamaV2 on NVIDIA GPU

  local-edge:
    host: nebulus               # Mac Mini M4 Pro on desk
    endpoint: http://nebulus:8080/v1
    model: qwen3-coder-30b
    tier: local
    concurrent: 2
    notes: MLX on Apple Silicon, 48GB RAM — primary local workhorse

  # Tier 2: Cloud fast — CHEAP, for quick decisions
  cloud-fast:
    endpoint: https://api.anthropic.com/v1
    model: claude-haiku-4-5-20251001
    tier: cloud-fast
    concurrent: 10

  # Tier 3: Cloud heavy — EXPENSIVE, for architecture + complex reasoning
  cloud-heavy:
    endpoint: https://api.anthropic.com/v1
    model: claude-sonnet-4-5-20250929
    tier: cloud-heavy
    concurrent: 3
```

**Task-to-Tier Mapping** (user can override any assignment):

| Task Type | Default Tier | Preferred Backend | Rationale |
|-----------|-------------|-------------------|-----------|
| Git chores (merge, tag, push) | None | Direct execution | No LLM needed |
| Code formatting, linting fixes | `local` | Either local | Mechanical, free |
| Test writing, boilerplate | `local` | `local-edge` (30B) | Better quality at 30B |
| Feature implementation | `local` | `local-edge` (30B) | 30B handles most features well |
| PR review, code review | `cloud-fast` | Haiku | Good speed + quality balance |
| Complex debugging | `cloud-fast` | Haiku or Sonnet | Depends on complexity |
| Architecture design, planning | `cloud-heavy` | Sonnet | Needs deep reasoning |
| Cross-project coordination | `cloud-heavy` | Sonnet | Needs ecosystem-wide context |

**Routing logic:**
1. Check if local backends are healthy (hit `/health` endpoint)
2. Prefer `local-edge` (30B) over `local-prime` (14B) when both are available
3. Fall back to cloud tier only when local is unavailable or task requires it
4. User can force a tier via `--tier cloud-heavy` on any dispatch command

#### Cross-Project Memory

A new memory layer that sits above per-project RAG. Stored in a dedicated
ChromaDB collection (or SQLite + embeddings) at `~/.atom/overlord/memory/`.

**What gets remembered:**

| Category | Examples |
|----------|---------|
| Project patterns | "Core uses Google-style docstrings", "Gantry frontend uses Zustand stores" |
| User preferences | "User prefers feature branches off develop", "User wants approval before push" |
| Cross-project relations | "Prime installs Core as editable dependency", "Gantry's backend talks to Prime's TabbyAPI" |
| Historical decisions | "We chose ChromaDB over Pinecone because of local-only requirement" |
| Failure patterns | "Edge MLX tests fail if Xcode CLI tools aren't installed" |
| Release history | "Core v0.1.0 tagged 2026-02-03, v0.1.1 tagged 2026-02-05" |

**Memory lifecycle:**

1. **Capture**: Overlord logs observations during every interaction
2. **Consolidate**: Periodic "sleep cycle" extracts patterns from raw observations
   (reuses Atom's existing Consolidator pattern)
3. **Recall**: Before any action, Overlord queries memory for relevant context
4. **Prune**: Stale or contradicted memories are marked and eventually removed

---

## 3. Interface Adapter Layer

All three interfaces (CLI, Slack, Gantry) share the same Overlord Core. The
Interface Adapter Layer normalizes input commands and renders output in the
appropriate format.

### 3.1 CLI Interface

For power users and scripting. Extends the existing `nebulus-atom` CLI.

```bash
# Ecosystem overview
nebulus-atom overlord status                    # Quick health of all projects
nebulus-atom overlord status --detailed         # Full report with git state, tests, issues

# Project management
nebulus-atom overlord scan                      # Scan all repos, report findings
nebulus-atom overlord scan nebulus-core          # Scan specific project

# Dispatch
nebulus-atom overlord dispatch "merge Core develop to main and tag v0.2.0"
nebulus-atom overlord dispatch "run tests across all projects"
nebulus-atom overlord dispatch "clean up stale branches in Prime and Edge"

# Release coordination
nebulus-atom overlord release nebulus-core v0.2.0   # Coordinated release with downstream checks

# Autonomy control
nebulus-atom overlord autonomy                      # Show current levels
nebulus-atom overlord autonomy --global scheduled    # Change global level
nebulus-atom overlord autonomy --project core cautious  # Override for specific project

# Memory
nebulus-atom overlord memory search "ChromaDB configuration"
nebulus-atom overlord memory forget "outdated pattern about X"

# Configuration
nebulus-atom overlord config                    # Show current config
nebulus-atom overlord projects add ~/new-repo   # Register a new project
nebulus-atom overlord projects remove old-repo  # Unregister a project

# Auto-discovery (scans workspace, generates starter YAML)
nebulus-atom overlord discover ~/projects/west_ai_labs
nebulus-atom overlord discover --dry-run        # Preview without writing
```

### 3.2 Slack Interface

For async monitoring and quick commands. Evolves the existing `slack_bot.py`.

```
@atom status                          → Ecosystem health summary
@atom status core                     → Specific project status
@atom merge core develop to main      → Dispatch merge task
@atom approve                         → Approve pending proposal
@atom deny                            → Deny pending proposal
@atom autonomy proactive              → Change autonomy level
@atom pause                           → Pause all scheduled tasks
@atom resume                          → Resume scheduled tasks
```

**Proactive notifications (when autonomy allows):**

```
🔔 Overlord: Found 3 commits on Core develop not yet on main.
   Merge and tag v0.1.1?
   [Approve] [Deny] [Details]

🔔 Overlord: Nightly test sweep complete.
   ✅ Core: 142 passed
   ✅ Atom: 826 passed
   ⚠️  Prime: 2 warnings (deprecation)
   ❌ Edge: 1 failure (test_mlx_connection)
   [View Details] [Dispatch Fix]
```

### 3.3 Gantry UI (Module-Based)

The Overlord's visual control plane is delivered as a **Gantry Module** — an
installable package that plugs into Gantry's module system rather than being
hardcoded into Gantry's codebase. This keeps Gantry's core clean and establishes
the pattern for future modules.

See: `nebulus-gantry/docs/plans/2026-02-05-gantry-module-system.md` for the full
module architecture specification.

**How it works:**

1. Atom declares a Gantry module via Python entry point:
   ```toml
   [project.entry-points."gantry.modules"]
   overlord = "nebulus_atom.gantry:module_manifest"
   ```

2. Gantry discovers the module at startup, registers its API routes, sidebar
   navigation, and admin tabs

3. The Overlord module provides its own frontend bundle (React components) that
   Gantry loads dynamically

**Navigation:** The Overlord gets its own **top-level sidebar entry** — not buried
inside the Admin panel. When a user clicks "Overlord" in the sidebar, they enter
the Overlord's own page with its own tab navigation. This gives the ecosystem
dashboard first-class visibility alongside Chat, Settings, and Admin.

```
┌─────────────────────────────────────────────┐
│  Sidebar          │  Main Content            │
│                   │                          │
│  💬 Chat          │  ┌─────────────────────┐ │
│  🔧 Settings      │  │ Ecosystem │ Dispatch │ │
│  🛡️ Admin         │  │ Memory  │ Audit     │ │
│  ⚡ Overlord  ◄── │  ├─────────────────────┤ │
│                   │  │                     │ │
│                   │  │  [Active Tab View]  │ │
│                   │  │                     │ │
│                   │  └─────────────────────┘ │
└─────────────────────────────────────────────┘
```

**Module views:**

| View | Content |
|------|---------|
| **Ecosystem Dashboard** | All projects with git state, test status, last activity. Dependency graph visualization. |
| **Project Detail** | Branches, recent commits, open issues, test results, agent activity history |
| **Dispatch Console** | Natural language task input, live agent progress, output review |
| **Memory Browser** | Search and manage Overlord's cross-project memory |
| **Audit Log** | Filterable timeline of all Overlord actions with hash chain verification |
| **Autonomy Settings** | Visual controls for autonomy levels per project |

**Atom package structure for the Gantry module:**

```text
nebulus_atom/
└── gantry/
    ├── __init__.py          # module_manifest definition
    ├── router.py            # FastAPI router (API endpoints)
    ├── schemas.py           # Pydantic request/response models
    ├── services.py          # Service layer (calls Overlord Core)
    └── frontend/
        ├── package.json     # Standalone React build
        ├── src/
        │   ├── OverlordPage.tsx         # Top-level page (owns tab navigation)
        │   ├── EcosystemDashboard.tsx
        │   ├── ProjectDetail.tsx
        │   ├── DispatchConsole.tsx
        │   ├── MemoryBrowser.tsx
        │   ├── AuditLog.tsx
        │   └── AutonomySettings.tsx
        └── dist/            # Built bundle served by Gantry
```

---

## 4. Operational Modes

### 4.1 Interactive Mode

The user is actively working and issues commands. This is today's workflow —
what happened in this conversation when deploying agents to merge and tag the
three repos.

**Flow:**

```
User: "Let's check on the projects"
Overlord: [scans all repos, reports status]
User: "Merge Core and Prime, tag Edge"
Overlord: [dispatches agents, monitors, reports results]
User: "Push all three"
Overlord: [executes pushes, confirms]
```

### 4.2 Background Mode

The Overlord runs as a daemon, monitoring repos and executing scheduled tasks.
Reports via Slack or accumulates a summary for the next interactive session.

**Scheduled actions (configurable):**

| Schedule | Action | Autonomy Required |
|----------|--------|-------------------|
| Hourly | Health check (git status, service endpoints) | `scheduled` |
| Nightly | Run test suites across all projects | `scheduled` |
| Nightly | Check for stale branches (> 7 days inactive) | `proactive` (proposes cleanup) |
| Weekly | Dependency drift check (outdated packages) | `proactive` (proposes updates) |
| On push | Run CI-equivalent validation | `scheduled` |

### 4.3 Coordinated Release Mode

A special workflow for releasing changes that span multiple projects.

**Example: Core v0.2.0 release**

```
1. Overlord checks: all Core tests pass
2. Overlord checks: develop is clean and ahead of main
3. Overlord merges develop → main, tags v0.2.0
4. Overlord checks dependents: Prime, Edge, Forge all depend on Core
5. Overlord updates Core version in Prime's requirements → runs tests
6. Overlord updates Core version in Edge's requirements → runs tests
7. If all pass: proposes "Release Core v0.2.0 and update all dependents?"
8. User approves → Overlord pushes all changes
9. Overlord logs the coordinated release in memory + audit trail
```

---

## 5. Trust Boundary & Safety

The existing trust boundary from Atom V2 is **preserved and extended**.

### 5.1 Permission Model

```
┌─────────────────────────────────────────────┐
│              ALWAYS ALLOWED                  │
│                                              │
│  • Read any managed repo (git status, log)   │
│  • Run tests (read-only validation)          │
│  • Scan for issues, branches, dependencies   │
│  • Query memory                              │
│  • Generate reports and summaries            │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│         REQUIRES APPROVAL (unless            │
│         pre-approved via autonomy config)     │
│                                              │
│  • Git merge / tag                           │
│  • Git push to remote                        │
│  • Create / close GitHub issues              │
│  • Create / merge pull requests              │
│  • Modify files in any project               │
│  • Install or update dependencies            │
│  • Spawn Minion workers                      │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│            ALWAYS REQUIRES APPROVAL          │
│        (cannot be pre-approved)              │
│                                              │
│  • Force push                                │
│  • Delete branches on remote                 │
│  • Modify Overlord's own configuration       │
│  • Change autonomy levels                    │
│  • Modify trust boundary rules               │
│  • Access secrets or credentials             │
└─────────────────────────────────────────────┘
```

### 5.2 Blast Radius Control

Every dispatched action carries a **scope declaration**:

```python
@dataclass
class ActionScope:
    projects: list[str]           # Which projects are affected
    branches: list[str]           # Which branches are touched
    destructive: bool             # Can this lose data?
    reversible: bool              # Can this be undone?
    affects_remote: bool          # Does this touch GitHub?
    estimated_impact: str         # "low", "medium", "high"
```

The Overlord evaluates scope before execution and escalates if the blast radius
exceeds the current autonomy level's threshold.

---

## 6. Implementation Phases

### Phase 1: Foundation (Overlord Core + CLI)

**Goal:** Replace the current Swarm Overlord with the multi-project-aware version.
CLI interface only. Cautious autonomy only.

**Deliverables:**

- [x] Project Registry (`~/.atom/overlord.yml` parsing + validation)
- [x] Auto-discovery command (`overlord discover` — scans workspace for repos,
      generates starter YAML; explicit YAML config stays as source of truth)
- [x] Ecosystem Scanner (git state, test health, branch analysis across all repos)
- [x] CLI commands: `overlord status`, `overlord scan`, `overlord config`, `overlord discover`
- [x] Dependency graph construction and traversal
- [x] Action scope model and blast radius evaluation
- [x] Cross-project memory store (SQLite-backed, text search)
- [x] CLI commands: `overlord graph`, `overlord memory`, `overlord scope`
- [ ] Migration path from existing `nebulus_swarm/overlord/`

**Tests:** 110 tests — registry (18), scanner (14), graph (21), action scope (20), memory (17), CLI (19). All passing.

### Phase 2: Dispatch + Autonomy

**Goal:** Dispatch tasks to workers across multiple repos. Configurable autonomy.

**Deliverables:**

- [ ] Autonomy Engine (three levels, per-project overrides, runtime switching)
- [ ] Multi-repo Dispatch Engine (evolve DockerManager for cross-repo tasks)
- [ ] Model Router (task → model mapping based on complexity + cost)
- [ ] CLI commands: `overlord dispatch`, `overlord autonomy`, `overlord release`
- [ ] Coordinated release workflow
- [ ] Pre-approved action lists for scheduled autonomy

**Tests:** Dispatch routing tests, autonomy level enforcement, release coordination.

### Phase 3: Slack + Background Mode

**Goal:** Async interface and daemon mode for continuous monitoring.

**Deliverables:**

- [ ] Slack Bot upgrade (multi-project commands, approval buttons, notifications)
- [ ] Background daemon mode (scheduled sweeps, health checks)
- [ ] Proactive proposal system (detect → propose → await approval → execute)
- [ ] Notification routing (Slack for urgent, accumulate for non-urgent)
- [ ] Cron-style schedule configuration

**Tests:** Slack command parsing, schedule execution, notification routing.

### Phase 4: Gantry Integration

**Goal:** Visual control plane in Gantry's admin UI.

**Deliverables:**

- [ ] Gantry backend: Overlord API endpoints (status, dispatch, memory, audit)
- [ ] Gantry frontend: Dashboard, project detail, dispatch console
- [ ] Dependency graph visualization (interactive)
- [ ] Memory browser
- [ ] Audit log viewer with hash chain verification
- [ ] Autonomy settings UI

**Tests:** API endpoint tests, UI component tests.

### Phase 5: Observability + Reporting

**Goal:** The Overlord tracks its own performance and presents data for human
decision-making. (Downgraded from "Meta-Evaluation" per Gemini review — automated
self-correction is low ROI at this scale. The human adjusts based on data.)

**Deliverables:**

- [ ] Dispatch outcome tracking (task → model → result → duration)
- [ ] Performance dashboards (which models succeed at which task types)
- [ ] Cross-project skill discovery: surface skills from one repo to another
- [ ] Memory consolidation "sleep cycle" (batch pattern extraction)
- [ ] Weekly/monthly summary reports (what was dispatched, what succeeded/failed)

**Tests:** Outcome tracking accuracy, report generation.

---

## 7. Configuration Reference

```yaml
# ~/.atom/overlord.yml — Full configuration reference

# ─── Project Registry ───────────────────────────────────
projects:
  nebulus-core:
    path: ~/projects/west_ai_labs/nebulus-core
    remote: jlwestsr/nebulus-core
    role: shared-library
    branch_model: develop-main
    depends_on: []
    test_command: pytest
    validate_command: pre-commit run --all-files

# ─── Autonomy ───────────────────────────────────────────
autonomy:
  global: proactive
  overrides:
    nebulus-core: cautious

# ─── Models (Three-Tier: local → cloud-fast → cloud-heavy) ──
models:
  local-prime:
    host: localhost
    endpoint: http://localhost:5000/v1
    model: Qwen2.5-Coder-14B
    tier: local
    concurrent: 2
    notes: TabbyAPI/ExLlamaV2 on NVIDIA GPU (dev machine)
  local-edge:
    host: nebulus
    endpoint: http://nebulus:8080/v1
    model: qwen3-coder-30b
    tier: local
    concurrent: 2
    notes: MLX on Apple Silicon, 48GB RAM (primary local workhorse)
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

# ─── Scheduling (for 'scheduled' autonomy) ──────────────
schedule:
  health_check:
    cron: "0 * * * *"          # Hourly
    action: scan
  nightly_tests:
    cron: "0 2 * * *"          # 2 AM daily
    action: test-all
  stale_branch_sweep:
    cron: "0 3 * * 0"          # 3 AM Sunday
    action: clean-stale-branches
    threshold_days: 7

# ─── Notifications ──────────────────────────────────────
notifications:
  slack:
    enabled: true
    channel: "#nebulus-ops"
    urgent: true               # Send immediately for failures
  summary:
    enabled: true
    schedule: "0 7 * * *"      # 7 AM daily digest

# ─── Memory ─────────────────────────────────────────────
memory:
  store: ~/.atom/overlord/memory/
  consolidation_schedule: "0 4 * * *"   # 4 AM daily
  max_raw_observations: 10000
  embedding_model: sentence-transformers/all-MiniLM-L6-v2

# ─── Audit ──────────────────────────────────────────────
audit:
  store: ~/.atom/overlord/audit.db
  signing_key: ~/.atom/overlord/signing.key   # Optional Ed25519
  retention_days: 365
```

---

## 8. Relationship to Existing Codebase

| Existing Module | Disposition | Notes |
|----------------|-------------|-------|
| `nebulus_swarm/overlord/main.py` | **Evolve** | Becomes the Overlord Core entry point |
| `nebulus_swarm/overlord/state.py` | **Evolve** | Extends to multi-project state |
| `nebulus_swarm/overlord/docker_manager.py` | **Keep** | Minion container management stays |
| `nebulus_swarm/overlord/slack_bot.py` | **Evolve** | Multi-project commands, approval buttons |
| `nebulus_swarm/overlord/github_queue.py` | **Evolve** | Scans multiple repos |
| `nebulus_swarm/overlord/llm_pool.py` | **Evolve** | Becomes Model Router with multi-backend |
| `nebulus_swarm/overlord/evaluator.py` | **Keep** | Worker evaluation logic stays |
| `nebulus_swarm/overlord/proposals.py` | **Keep** | Enhancement proposal system stays |
| `nebulus_swarm/overlord/scope.py` | **Evolve** | Adds ActionScope + blast radius |
| `nebulus_swarm/overlord/skill_evolution.py` | **Keep** | Skill lifecycle stays |
| `nebulus_swarm/overlord/audit_trail.py` | **Keep** | Audit system stays, gains more event types |
| `nebulus_swarm/overlord/auditor.py` | **Keep** | Compliance auditor stays |
| `nebulus_swarm/minion/` | **Keep** | Worker agents unchanged |
| `nebulus_atom/services/rag_service.py` | **Extend** | Cross-project memory layer on top |
| `nebulus_atom/services/telemetry_service.py` | **Keep** | Standalone telemetry unchanged |

---

## 9. Success Criteria

The Overlord is successful when:

1. **"What's the state of everything?"** gets an accurate, instant answer
2. **Routine chores** (merges, tags, pushes, branch cleanup) happen without manual
   git commands
3. **Cross-repo releases** are coordinated automatically with dependency awareness
4. **The user's preferences** are remembered and applied consistently
5. **Nothing breaks silently** — every action is audited, every failure is escalated
6. **The trust boundary holds** — the Overlord never exceeds its granted autonomy

---

## 10. Resolved Decisions (Gemini Architecture Review)

These decisions were reached through a cross-AI architecture review on 2026-02-05
(Claude as lead architect, Gemini as reviewer).

| # | Topic | Resolution |
|---|-------|-----------|
| 1 | **Dependency isolation** | Same-process modules for now (YAGNI). Document constraint in `gantry-sdk`. If a real conflict arises between modules, introduce a sidecar pattern where the module runs its own FastAPI service and Gantry proxies to it. |
| 2 | **CSS collisions** | Non-issue with Tailwind utility classes. SDK recommends prefixed custom classes as a safety convention. No Shadow DOM needed. |
| 3 | **Audit hash chains** | Keep existing (shipped in Atom V2, zero maintenance cost). Don't expand — no new audit features beyond what exists. |
| 4 | **Meta-evaluation** | Downgraded to "Observability + Reporting" (Phase 5). Overlord tracks dispatch outcomes and presents data. Human decides. Automated self-correction is low ROI at this scale. |
| 5 | **Model router** | Three tiers: `local`, `cloud-fast`, `cloud-heavy`. Simple task-type mapping with user override. No dynamic cost optimization. Two local machines provide free inference for 60-70% of work. |
| 6 | **Phase ordering** | Keep current order. Parallelize Gantry module system + Overlord work streams (different repos, independent). CLI is useful from day one. |
| 7 | **Auto-discovery** | `overlord discover` command scans workspace root for repos and generates starter YAML. Explicit `overlord.yml` config stays as source of truth for metadata (`role`, `depends_on`, `branch_model`). |
| 8 | **Bundle format (Gantry)** | ESM (Standard ES Modules). IIFE is a pre-Vite relic. |
| 9 | **Shared state (Gantry)** | API-only for data. Typed `EventBus` via `gantry-sdk` for UI affordances (toasts, confirmations). No direct Zustand store access. |

## 11. Open Questions

- **Minion evolution**: Should Minions also become multi-project-aware, or should
  the Overlord always decompose cross-repo tasks into single-repo Minion tasks?
- **Remote Overlord**: Should the Overlord be able to run on a remote server
  (e.g., the Prime box or Mac Mini) and manage repos via SSH/API, or always run
  locally? (Note: with dual-machine inference, the Mac Mini is already a remote
  resource — extending this to remote Overlord execution is a natural next step.)
- **Multi-user**: Is this always single-user (the owner), or could multiple team
  members interact with the same Overlord instance?
