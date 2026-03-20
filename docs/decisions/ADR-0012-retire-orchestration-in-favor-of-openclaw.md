# ADR-0012: Retire nebulus-atom Orchestration in Favor of OpenClaw

**Date:** 2026-02-25
**Status:** Accepted
**Deciders:** Jason L. West, Sr. (West AI Labs)
**Technical Story:** OpenClaw has been proven in production as a fully capable AI agent runtime across two instances (Moto on shurtugal-lnx, Cael on nebulus Mac Mini M4 Pro). nebulus-atom's orchestration, autonomy, dispatch, routing, and memory subsystems are now redundant. Maintaining two parallel orchestration stacks is unsustainable and introduces split-brain risk.

---

## Context and Problem Statement

nebulus-atom was designed as a homegrown AI agent orchestration layer for the Nebulus Stack. Its original scope covered:

1. **Ecosystem scanner** — walks all 8 Nebulus repos, builds a NetworkX dependency graph
2. **Autonomy engine** (`AutonomyEngine`) — decides what to work on without human prompting
3. **Dispatch engine + task parser** (`DispatchEngine`, `TaskParser`) — breaks work into sub-tasks, routes to workers
4. **Model router** (`ModelRouter`) — selects Claude/Gemini/etc. per task type and cost envelope
5. **Proposal manager** (`ProposalManager`) — human-in-the-loop approval flow for risky changes
6. **Memory/continuity layer** (`MemoryStore`) — persists agent state across sessions

In parallel, **OpenClaw** has been deployed to production and demonstrates feature parity with everything above *except* items 1 (ecosystem scanner) and 1a (dependency graph). OpenClaw provides:

- Multi-agent orchestration via `sessions_spawn` + sub-agent API
- Model routing via per-channel `openclaw.json` config
- Autonomous scheduled execution via `HEARTBEAT.md`
- Human-in-the-loop trust rules via `AGENTS.md`
- Memory/continuity via daily logs, `MEMORY.md`, and `session-state.json`
- Extensible tool integration via the Skill system

Maintaining two parallel orchestration implementations — nebulus-atom's Python-based stack and OpenClaw's runtime — is unsustainable. It creates dual maintenance burden, divergent trust models, potential split-brain scenarios when both systems attempt to dispatch work to the same Nebulus services, and confusion about which system is authoritative.

---

## Decision Drivers

- **Proven production deployment:** OpenClaw has been running live on two hosts with no critical incidents. nebulus-atom has not yet reached production-equivalent stability.
- **Redundancy with no upside:** Dispatch, routing, memory, and approval flow are implemented better in OpenClaw than in nebulus-atom's homegrown equivalents.
- **Unique value concentration:** nebulus-atom's only irreplaceable capability is multi-repo topology awareness (ecosystem scanner + dependency graph). Everything else is OpenClaw.
- **Operational risk:** Two systems issuing autonomous work orders against the same repos simultaneously is a correctness hazard — last-writer-wins conflicts, duplicate PR creation, contradictory plan execution.
- **Skill composability:** OpenClaw's Skill system allows nebulus-atom's remaining scanner/graph capability to be exposed as a read-only analysis tool without any orchestration surface area.

---

## Considered Options

### Option A: Keep Both — Federate Them
Run nebulus-atom as a sub-orchestrator beneath OpenClaw. nebulus-atom handles intra-Nebulus dispatching; OpenClaw handles top-level session management.

**Rejected.** Creates a two-tier dispatch model with unclear authority boundaries. Trust rules in `AGENTS.md` would need to cover both systems. Debugging failures requires understanding two codebases. No clear benefit over Option C.

### Option B: Keep Both — Scope-Separate Them
nebulus-atom owns Nebulus Stack work. OpenClaw owns external tasks (Discord, email, etc.).

**Rejected.** The Nebulus Stack is the primary workload. Splitting orchestration along this line means OpenClaw has no visibility into the most important work happening in the system. Also, the "Nebulus Stack work" category will grow and spill over, eroding the separation over time.

### Option C: Retire nebulus-atom Orchestration; Slim to Scanner + Graph ✅
Delete or archive all orchestration/autonomy/dispatch/routing/memory components from nebulus-atom. Retain the ecosystem scanner and dependency graph engine as a read-only library. Expose it to OpenClaw as a Skill.

**Accepted.** Eliminates the redundant surface area entirely. nebulus-atom's unique value is preserved and made *more* accessible through Skill invocation. OpenClaw becomes the single authoritative orchestration layer across the entire Nebulus Stack.

### Option D: Retire nebulus-atom Entirely
Archive the entire repo.

**Rejected** (for now). The ecosystem scanner and dependency graph are not replicated anywhere else. They provide genuine value for impact analysis before autonomous changes. Retiring the whole repo throws away the one thing nebulus-atom does that OpenClaw cannot.

---

## Decision Outcome

**Chosen option: Option C** — Retire nebulus-atom orchestration components; slim the repo to ecosystem scanner + dependency graph engine.

### Positive Consequences

- Single orchestration system in production: OpenClaw
- nebulus-atom becomes a focused, auditable read-only tool with a clear API contract
- OpenClaw gains ecosystem topology awareness via Skill invocation
- No more split-brain risk from dual autonomous dispatch
- Reduced maintenance surface by ~70% of nebulus-atom's codebase
- Trust model is unified: `AGENTS.md` is the single source of truth for what the agent is allowed to do

### Negative Consequences

- Migration work required to remove/archive components (estimated: 2-3 days)
- Any scripts or integrations importing nebulus-atom orchestration internals will break and need updating
- Gantry's `overlord_routing_enabled` setting will need to be deprecated

---

## Migration Plan

### Phase 1: Audit and Freeze (Day 1)

1. **Freeze nebulus-atom orchestration.** Merge any open PRs. Tag current HEAD as `pre-openclaw-migration` in git.
   ```bash
   cd /path/to/nebulus-atom
   git tag pre-openclaw-migration
   git push origin pre-openclaw-migration
   ```

2. **Identify all consumers.** Search across all 8 Nebulus repos for imports of the components being retired:
   ```bash
   grep -r "nebulus_swarm.overlord\|OverlordService\|overlord_service\|DispatchEngine\|TaskParser\|ModelRouter\|ProposalManager\|MemoryStore\|AutonomyEngine" \
     nebulus-core nebulus-prime nebulus-edge nebulus-atom nebulus-forge nebulus-gantry nebulus-mac-mini-4-pro nebulus-shurtugal-lnx
   ```

3. **Audit `gantry` config.** Locate and document all occurrences of `overlord_routing_enabled` in nebulus-gantry config files (YAML, TOML, .env). These must be deprecated in Phase 2.

4. **Map active cron jobs and heartbeat tasks** referencing nebulus-atom dispatch endpoints. Document them with their OpenClaw equivalents.

### Phase 2: Remove Orchestration Components (Day 1–2)

Delete (or move to `archive/` subdirectory for reference) the following modules from nebulus-atom:

| Module / File | Reason for Removal |
|---|---|
| `nebulus_swarm/overlord.py` | Core orchestration — replaced by OpenClaw `sessions_spawn` |
| `nebulus_swarm/overlord_service.py` (`OverlordService`) | Service wrapper for orchestration — redundant |
| `nebulus_atom/autonomy/` (entire package) | `AutonomyEngine` — replaced by OpenClaw HEARTBEAT.md loop |
| `nebulus_atom/dispatch/` (entire package) | `DispatchEngine`, `TaskParser` — replaced by OpenClaw sub-agents |
| `nebulus_atom/routing/` (entire package) | `ModelRouter` — replaced by `openclaw.json` model routing |
| `nebulus_atom/proposals/` (entire package) | `ProposalManager` — replaced by OpenClaw trust rules in AGENTS.md |
| `nebulus_atom/memory/` (entire package) | `MemoryStore` — replaced by OpenClaw daily logs + session-state.json |
| FastAPI routes: `/overlord/*`, `/dispatch/*`, `/autonomy/*` | API surface for retired components |

**Do not delete:**
- `nebulus_atom/scanner/` — ecosystem scanner, retained
- `nebulus_atom/graph/` — dependency graph engine, retained
- `nebulus_atom/api/scanner.py` — scanner API routes, retained and promoted to primary interface

**Gantry deprecation:**
- Remove `overlord_routing_enabled` from nebulus-gantry's routing config
- Add a deprecation warning log if the key is present: `"overlord_routing_enabled is deprecated as of ADR-0012; key ignored"`
- Schedule key removal for the next major nebulus-gantry release

### Phase 3: Build the OpenClaw Skill (Day 2–3)

Create `~/.openclaw/workspace/skills/nebulus-atom/SKILL.md` to expose scanner + graph as an OpenClaw Skill.

The Skill should provide:
- `scan_ecosystem` — trigger a full scan of all Nebulus repos, return dependency graph JSON
- `query_dependencies` — given a repo or module, return its upstream/downstream dependents
- `impact_analysis` — given a proposed change path, return a risk-ranked list of affected repos

Skill invocation pattern (example in SKILL.md):
```bash
# Full ecosystem scan
python -m nebulus_atom.scanner.cli scan --output json

# Dependency query
python -m nebulus_atom.graph.cli query --node nebulus-core --direction downstream

# Impact analysis
python -m nebulus_atom.graph.cli impact --changed-files "nebulus-core/src/shared/config.py"
```

The Skill must:
- Be **read-only** — no writes, no dispatch, no side effects
- Return structured JSON consumable by OpenClaw tool parsing
- Log invocations to the OpenClaw daily log for audit trail
- Document required Python environment and nebulus-atom installation path in SKILL.md

### Phase 4: Validation (Day 3)

1. **Run ecosystem scanner** via the new Skill from an OpenClaw session. Verify the dependency graph is complete and accurate.
2. **Verify Gantry starts cleanly** without `overlord_routing_enabled` present.
3. **Verify no import errors** across nebulus-core, nebulus-prime, nebulus-edge, nebulus-forge after removal.
4. **Run any existing nebulus-atom tests** that cover scanner/graph — these must pass. Tests covering retired components should be deleted or moved to `archive/tests/`.
5. **Update nebulus-atom README** to clearly document its new scope: "read-only ecosystem analysis tool."

### Phase 5: Communicate and Document (Day 3)

1. Update `nebulus-atom/README.md` — new scope, new API surface, deprecation notice for removed components
2. Update `nebulus-gantry` docs — remove `overlord_routing_enabled` from configuration reference
3. Post migration summary to West AI Labs internal notes / Discord
4. Update `MEMORY.md` on both OpenClaw instances (Moto, Cael) with note: nebulus-atom is now scanner-only; use `nebulus-atom` Skill for ecosystem queries

---

## Components Retained in nebulus-atom

| Component | Purpose | Interface |
|---|---|---|
| `EcosystemScanner` | Walks all 8 Nebulus repos, builds topology map | CLI + Python API |
| `DependencyGraph` | NetworkX-based directed graph of inter-repo/module deps | Python API + JSON export |
| `ImpactAnalyzer` | Answers "what breaks if I change X" | CLI + Python API |
| FastAPI `/scan` routes | HTTP interface for scanner (used by OpenClaw Skill) | REST API |

Everything else is retired.

---

## Architectural View: Before and After

### Before (Dual Stack)

```
OpenClaw (shurtugal-lnx / mac-mini)
  ├── Session management
  ├── Model routing
  ├── Heartbeat autonomy
  ├── Trust / approval
  └── Memory

nebulus-atom (running independently)
  ├── OverlordService (autonomous dispatch)         ← REDUNDANT
  ├── AutonomyEngine (decides work autonomously)    ← REDUNDANT
  ├── DispatchEngine + TaskParser                   ← REDUNDANT
  ├── ModelRouter                                   ← REDUNDANT
  ├── ProposalManager                               ← REDUNDANT
  ├── MemoryStore                                   ← REDUNDANT
  ├── EcosystemScanner                              ← UNIQUE VALUE
  └── DependencyGraph                               ← UNIQUE VALUE
```

### After (Single Stack)

```
OpenClaw (shurtugal-lnx / mac-mini) — AUTHORITATIVE ORCHESTRATOR
  ├── Session management
  ├── Model routing (openclaw.json)
  ├── Heartbeat autonomy (HEARTBEAT.md)
  ├── Trust / approval (AGENTS.md)
  ├── Memory (daily logs, MEMORY.md, session-state.json)
  └── Skills
        └── nebulus-atom Skill ──────────────────────────┐

nebulus-atom — READ-ONLY ANALYSIS TOOL                   │
  ├── EcosystemScanner  ◄──────────────────────────────── ┘
  └── DependencyGraph
```

---

## Links and References

- OpenClaw production config: `~/.openclaw/workspace/` (shurtugal-lnx, mac-mini)
- AGENTS.md trust model: `~/.openclaw/workspace/AGENTS.md`
- HEARTBEAT.md autonomy loop: `~/.openclaw/workspace/HEARTBEAT.md`
- nebulus-gantry overlord setting: see `gantry/config/routing.yaml` → `overlord_routing_enabled`
- `OverlordService` implementation: `nebulus-atom/nebulus_swarm/overlord_service.py`
- `nebulus_swarm.overlord` module: `nebulus-atom/nebulus_swarm/overlord.py`
- Related ADRs: ADR-0008 (OpenClaw adoption), ADR-0010 (Gantry routing architecture)
- Pre-migration git tag: `pre-openclaw-migration`
