# Nebulus Atom V2 — Standalone Agent Management Platform

**Date:** 2026-02-05
**Status:** Design Brief
**Goal:** Transform Atom from a dev-focused CLI into a standalone, independently installable agent management platform with a human-in-the-loop trust boundary.

## Current State

Atom has two packages today:

| Package | Purpose | State |
|---------|---------|-------|
| `nebulus_atom` | Standalone CLI agent — Typer, MVC architecture, 63 Python files | Working CLI with services for MCP, RAG, skills, tools, telemetry |
| `nebulus_swarm` | Distributed Overlord/Minion orchestration | Overlord (state, command parsing, model routing, Docker mgmt, GitHub queue, Slack bot) + Minion (agent, LLM client, tools, skills, git ops, reporter) |

**What works:** CLI agent, PR reviewer, skill system, tool executor, RAG, MCP service, Streamlit dashboard
**What's hardcoded:** `localhost:5000/v1` (TabbyAPI), model name `Meta-Llama-3.1-8B-Instruct-exl2-8_0`
**Deployment:** Docker Compose (`docker-compose.swarm.yml`) for Swarm mode
**Tests:** 642 passing, 0 failures (as of 2026-02-05)
**Standalone:** Confirmed — zero nebulus-core imports. All LLM clients use `openai` SDK directly with configurable `base_url`.
**V2 Phase 1:** COMPLETE — configurable LLM, configurable vector store, pip packaging, smoke tests all done.
**V2 Phase 2:** COMPLETE (core items) — evaluator, scope enforcement, enhancement proposals. 691 tests.
**V2 Phase 3:** COMPLETE — Proposals CLI wired, Evaluator.evaluate() method, LLM connection pool, Minion pool integration, backend compatibility matrix, skill evolution workflow. 738 tests passing (47 new).
**V2 Phase 4:** COMPLETE — Provisioning config documentation, example configs, MCP client integration with graceful degradation. 754 tests passing (16 new).
**V2 Phase 5:** COMPLETE — Small-model auditor, hybrid audit trail with hash chains, platform health API client, certification packages. 826 tests passing (72 new).
**Overlord Phase 1:** COMPLETE — Project registry, scanner, dependency graph, action scope, cross-project memory, CLI commands (status/scan/config/discover/graph/memory/scope). 110 overlord tests passing.

## V2 Vision

Atom is a **standalone product** — like Open WebUI or Cursor. Users download it, install it, configure it for their LLM backend, and it works. On Nebulus appliances, provisioning writes the config. Atom does NOT depend on nebulus-core.

### Core Architecture: Supervisor/Worker with Human Approval

```
┌──────────────────────────────────────────────────────┐
│                        User                           │
│                    (Human-in-the-Loop)                │
└──────────────┬───────────────────▲───────────────────┘
               │ approves work     │ proposes enhancements
               │ dispatches tasks  │ reports findings
               ▼                   │
┌──────────────────────────────────────────────────────┐
│              Supervisor (Overlord)                     │
│                                                       │
│  - Understands full project context                   │
│  - Decomposes tasks into worker assignments           │
│  - Dispatches workers with bounded scope              │
│  - Evaluates worker output (quality, correctness)     │
│  - Identifies capability gaps:                        │
│      - New skills workers need                        │
│      - Bug fixes in worker tooling                    │
│      - Feature enhancements for better results        │
│  - Reports enhancement proposals to User              │
│  - NEVER self-improves without User approval          │
│                                                       │
└──────────┬──────────────────────▲────────────────────┘
           │ assigns tasks        │ reports results
           │ provides context     │ returns artifacts
           ▼                      │
┌──────────────────────────────────────────────────────┐
│                Workers (Minions)                       │
│                                                       │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐              │
│  │ Worker 1│  │ Worker 2│  │ Worker N│  (concurrent) │
│  └─────────┘  └─────────┘  └─────────┘              │
│                                                       │
│  - Execute discrete, bounded tasks                    │
│  - Use skills + tools within their scope              │
│  - Report results back to Supervisor                  │
│  - No awareness of other workers                      │
│  - No ability to modify their own capabilities        │
│                                                       │
└──────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────┐
│           Any OpenAI-Compatible LLM Backend           │
│  TabbyAPI · vLLM · MLX · Ollama · OpenAI · Anthropic │
│                                                       │
│  REQUIREMENT: Must handle concurrent requests         │
│  (multiple workers query simultaneously)              │
└──────────────────────────────────────────────────────┘
```

### Trust Boundary (Critical Design Constraint)

The Supervisor operates under a strict trust boundary:

1. **Supervisor CAN:** Dispatch tasks, evaluate output, identify gaps, propose enhancements
2. **Supervisor CANNOT:** Build new skills, modify worker capabilities, change its own behavior, or install dependencies — without explicit User approval
3. **Workers CAN:** Execute tasks within their assigned scope using existing skills/tools
4. **Workers CANNOT:** Communicate with each other, modify their own skills, or access resources outside their scope

This is not a suggestion — it is the **core safety architecture** that makes Atom deployable to customers who are wary of autonomous AI agents (Moltbot/Clawdbot backlash).

**Approval flow for enhancements:**
```
Supervisor identifies gap → writes enhancement proposal → presents to User →
User reviews and approves/modifies/rejects → Supervisor dispatches approved work →
Worker implements enhancement → Supervisor evaluates result → User verifies
```

## V2 Work Items

### Phase 1: Standalone Product (Prerequisite)

Make Atom installable and configurable without any Nebulus dependency.

1. ~~**Remove nebulus-core imports**~~ **DONE (2026-02-05)** — Audit confirmed zero nebulus-core imports. All four LLM client locations use the `openai` SDK directly with configurable `base_url`. Atom is already fully standalone.

2. ~~**Configurable LLM backend**~~ **DONE (2026-02-05)** — Settings module with config file (`~/.atom/config.yml` or project-local `.atom.yml`) + env var overrides (`ATOM_LLM_BASE_URL`, `ATOM_LLM_MODEL`, `ATOM_LLM_API_KEY`). Sensible defaults, env vars take precedence over config file.

3. ~~**Configurable vector store**~~ **DONE (2026-02-05)** — ChromaDB connection configurable (embedded vs HTTP mode, host, port) via same settings system.

4. ~~**Package for pip install**~~ **DONE (2026-02-05)** — `pip install .` works in fresh venv, entry points (`nebulus-atom`, `mn`) functional, no nebulus-core dependency.

5. ~~**Standalone smoke test**~~ **DONE (2026-02-05)** — Tests verify config loading with defaults, env var overrides, CLI entry point importability. 642 tests passing (up from 605).

### Phase 2: Supervisor/Worker Formalization

The Overlord/Minion code exists but needs the human approval loop and evaluation layer.

6. ~~**Supervisor evaluation layer**~~ **DONE (2026-02-05)** — `nebulus_swarm/overlord/evaluator.py` with `_score()` method for scoring logic (pass/fail/needs-revision). CheckRunner + LLMReviewer orchestration via `evaluate()` left as integration point for Overlord wiring. Evaluations table added to `state.py`. 16 new tests.

7. ~~**Enhancement proposal system**~~ **DONE (2026-02-05)** — `nebulus_swarm/overlord/proposals.py` with data model + SQLite store. `nebulus_atom/commands/proposals.py` CLI formatters (stubbed — wiring to ProposalStore is follow-up). 12 new tests.

8. ~~**Worker scope enforcement**~~ **DONE (2026-02-05)** — `nebulus_swarm/overlord/scope.py` data model. `tool_executor.py` integrated with scope checking on writes. Minion loads scope from `MINION_SCOPE` env var. 20 new tests.

9. ~~**Skill evolution workflow**~~ **DONE (2026-02-05)** — `nebulus_swarm/overlord/skill_evolution.py`. When a new skill is needed:
   - Supervisor drafts skill spec (inputs, outputs, constraints)
   - User approves spec
   - Worker implements skill
   - Supervisor validates skill against spec
   - User confirms deployment to skill library

### Phase 3: Concurrent Inference

10. ~~**LLM connection pooling**~~ **DONE (2026-02-05)** — `nebulus_swarm/overlord/llm_pool.py` with asyncio.Semaphore, configurable concurrency limit (`ATOM_LLM_CONCURRENCY`), queue management, pool stats, graceful fallback on 429/503. Integrated with Minion LLM client for Swarm mode, bypassed for standalone.

11. ~~**Backend compatibility matrix**~~ **DONE (2026-02-05)** — Documented in `docs/concurrent-inference-matrix.md`:
    | Backend | Concurrent Support | Notes |
    |---------|-------------------|-------|
    | TabbyAPI | Yes | ExLlamaV2 batching supported |
    | vLLM | Yes | Designed for concurrent serving |
    | MLX Serving | Limited | Single-request optimized |
    | Ollama | No | Sequential only — why it was abandoned |
    | OpenAI API | Yes | Cloud, rate-limited |
    | Anthropic API | Yes | Cloud, rate-limited |

### Phase 4: Nebulus Integration (Optional)

Only relevant when Atom is deployed on Nebulus appliances. Not needed for standalone use.

12. ~~**Provisioning config template**~~ **DONE (2026-02-05)** — Created `docs/provisioning-config.md` with complete configuration reference, `examples/nebulus-config.yml` ready-to-use template, and `examples/atom.env.example` for Docker deployments. Covers all Tier 1/2/3 platforms with recommended settings.

13. ~~**MCP server connection**~~ **DONE (2026-02-05)** — Created `nebulus_swarm/integrations/mcp_client.py` with optional MCP client. Configurable via `ATOM_MCP_URL` environment variable. Graceful degradation when MCP unavailable. Tools prefixed with `mcp_` to avoid conflicts. 16 tests covering all scenarios.

### Phase 5: Compliance & Resilience (Regulated Industries)

Informed by Claude–Gemini brainstorming session (2026-02-05). These items should be designed before the architecture hardens but implemented after Phase 2.

14. ~~**Small-model auditor**~~ **DONE (2026-02-05)** — Created `nebulus_swarm/overlord/auditor.py` with structural validation. Checks Python syntax (AST), JSON schema, safety patterns (eval, exec, dangerous shell calls). Optional LLM review via `ATOM_AUDITOR_MODEL`. Config: `ATOM_AUDITOR_ENABLED` (default false), `ATOM_AUDITOR_STRICT`. 21 tests.

15. ~~**Hybrid audit trail**~~ **DONE (2026-02-05)** — Created `nebulus_swarm/overlord/audit_trail.py` with hash chain tamper evidence and optional Ed25519 signing. `SemanticLog` captures task lifecycle events. CLI commands `audit verify` and `audit export`. 15 tests.

16. ~~**Platform health API**~~ **DONE (2026-02-05)** — Created `nebulus_swarm/integrations/health_client.py`. Queries platform for thermal_level, vram_percent, cpu_percent, inference_latency. Timeout multipliers: 1.5x warm, 2.0x hot, 3.0x critical. Dispatch pause at level 3. Model switch at VRAM >90%. 23 tests.

17. ~~**Certification Packages**~~ **DONE (2026-02-05)** — Created `nebulus_swarm/overlord/certification.py`. `CertificationPackage` bundles proposal + diff + test results + auditor score + evaluator score + impact analysis. `CertificationBuilder` with fluent API. JSON export for compliance audits. 13 tests.

**Future (V3):**
- Hardware-signed execution receipts (Secure Enclave / TPM signing every inference result)
- Cross-quantization jitter testing (run critical prompts through different quantizations to detect quantization-induced hallucinations)

## Mapping to Existing Code

| V2 Concept | Existing Code | Delta |
|------------|---------------|-------|
| Supervisor | `nebulus_swarm/overlord/` | Add evaluation layer, enhancement proposals, approval workflow |
| Workers | `nebulus_swarm/minion/` | Add scope enforcement, bounded contexts |
| Skills | `nebulus_atom/skills/`, `nebulus_swarm/minion/skills/` | Unify skill system, add evolution workflow |
| LLM Client | `nebulus_swarm/minion/agent/llm_client.py`, `nebulus_atom/services/openai_service.py` | Make configurable, add connection pooling |
| Config | `nebulus_atom/config.py` | Replace hardcoded values with config file + env vars |
| Dashboard | `nebulus_swarm/dashboard/`, `nebulus_atom/ui/dashboard.py` | Add enhancement proposal UI, worker status, queue depth |
| MCP | `nebulus_atom/services/mcp_service.py` | Make optional (Nebulus integration only) |
| RAG | `nebulus_atom/services/rag_service.py` | Make vector store configurable |

## Out of Scope (This Design)

- Atom as a web service (keep as CLI + optional dashboard for now)
- Multi-user Atom (single operator model for V2)
- Atom self-hosting (no auto-update, no self-deployment)
- Integration with CI/CD pipelines (future work)
- Atom-to-Atom communication (fleet mode — future work)

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Removing core dependency breaks RAG/MCP | Medium | Audit imports first, replicate only what's needed |
| Concurrent inference overwhelms LLM backend | High | Connection pooling with backpressure, configurable concurrency limit |
| Enhancement approval loop slows development | Low | Batch proposals, allow "auto-approve" for low-risk categories (with User opt-in) |
| Worker scope enforcement too restrictive | Medium | Start permissive, tighten based on real-world failures |
| Two skill systems (atom + swarm) diverge | Medium | Unify in Phase 2 before adding new skills |

## Customer Deployment Note

Atom is **opt-in only** on Nebulus customer appliances. It is not installed by default. This is a deliberate business decision based on current public sentiment around autonomous AI agents. The human-in-the-loop trust boundary is the key differentiator that makes Atom deployable where competitors are not trusted.
