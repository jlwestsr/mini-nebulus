# Nebulus Swarm: Overlord + Minions Architecture

**Date:** 2026-02-02
**Status:** APPROVED
**Authors:** @jlwestsr, Claude Opus 4.5

## Executive Summary

Nebulus Swarm extends Nebulus Atom into an autonomous, distributed agent system. An always-on **Overlord** monitors Slack and GitHub, spawning ephemeral **Minion** containers to implement features and fix bugs autonomously. Work is queued via GitHub Issues with labels, and humans interact through Slack.

## 1. High-Level Architecture

### Components

| Component | Role | Runtime | LLM |
|-----------|------|---------|-----|
| **Overlord** | Control plane - watches Slack, manages Minions, maintains state | Always-on (lightweight container) | Small/cheap (8B) or rule-based |
| **Minion** | Worker - pulls repo, implements features, creates PRs | Ephemeral (container per job) | Large (30B+ for quality) |
| **GitHub** | Work queue (Issues with labels) + code storage | External service | N/A |
| **Slack** | Human interface - chat with Overlord, receive updates | External service | N/A |

### System Diagram

```
┌─────────────────────────────────────────────────────────┐
│                   NEBULUS OVERLORD                       │
│            (lightweight, always-on, watches Slack)       │
│                                                          │
│  • Listens to Slack 24/7                                │
│  • Spawns/stops Minions on demand                       │
│  • Relays status updates from Minions                   │
│  • Manages cron-triggered queue sweeps                  │
└──────────────────────┬──────────────────────────────────┘
                       │ spawns/manages
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   ┌─────────┐    ┌─────────┐    ┌─────────┐
   │ Minion  │    │ Minion  │    │ Minion  │
   │    1    │    │    2    │    │    3    │
   └─────────┘    └─────────┘    └─────────┘
      repo A         repo A         repo B
```

### Trigger Modes

1. **Cron** - Overlord wakes Minions on schedule to check for `nebulus-ready` issues
2. **On-demand** - User tells Overlord via Slack: "Start working on issue #42 now"
3. **Hybrid** - Cron runs overnight, user can interrupt/prioritize via Slack during the day

## 2. Overlord Design

### Responsibilities

- Watch Slack channel 24/7 for messages
- Parse commands ("start #42", "status", "pause", "list queue")
- Maintain state of all active Minions and their current tasks
- Spawn/stop Minion containers via Docker API
- Query GitHub Issues API for `nebulus-ready` labeled items
- Relay Minion progress updates to Slack
- Handle cron-triggered sweeps

### Tech Stack

| Concern | Choice | Why |
|---------|--------|-----|
| Runtime | Python asyncio | Matches existing Nebulus Atom codebase |
| Slack Integration | Slack Bolt SDK | Official, handles websocket connection |
| Container Management | Docker SDK for Python | Spawn/stop Minion containers |
| State Storage | SQLite | Simple, file-based, survives restarts |
| LLM (optional) | Local 8B or regex/rules | Only needs to understand commands, not code |

### State Schema

```sql
CREATE TABLE minions (
    id TEXT PRIMARY KEY,
    container_id TEXT,
    repo TEXT,
    issue_number INTEGER,
    status TEXT,  -- 'working', 'idle', 'error'
    started_at TIMESTAMP,
    last_heartbeat TIMESTAMP
);

CREATE TABLE work_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    minion_id TEXT,
    repo TEXT,
    issue_number INTEGER,
    pr_number INTEGER,
    status TEXT,  -- 'success', 'failed', 'timeout'
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT
);
```

### Slack Commands

Natural language, parsed by Overlord:

| Command | Action |
|---------|--------|
| "What's the status?" | List active Minions and their tasks |
| "Work on issue #42" | Spawn Minion for that issue |
| "Stop the minion on #42" | Kill that container |
| "What's in the queue?" | Query GitHub for `nebulus-ready` issues |
| "Prioritize #45" | Bump priority (add `high-priority` label) |
| "Pause" | Stop processing queue (Minions finish current work) |
| "Resume" | Resume queue processing |

## 3. Minion Design

### Lifecycle

```
Spawned → Clone Repo → Read Issue → Work → Commit → Push → Create PR → Report → Die
```

### Characteristics

- Fresh Docker container (sandboxed, isolated)
- Based on existing Nebulus Atom image
- Single mission: one GitHub issue
- Ephemeral - does its job and shuts down

### Environment Variables

```yaml
MINION_ID: "minion-abc123"
GITHUB_REPO: "west_ai_labs/nebulus-atom"
GITHUB_ISSUE: "42"
GITHUB_TOKEN: "${secret}"
OVERLORD_CALLBACK_URL: "http://overlord:8080/minion/report"
NEBULUS_BASE_URL: "http://192.168.4.30:8080/v1"
NEBULUS_MODEL: "qwen3-coder-30b"
NEBULUS_TIMEOUT: "600"
NEBULUS_STREAMING: "false"
```

### Workflow Steps

1. **Clone** - `git clone` the repo into `/workspace`
2. **Branch** - `git checkout -b minion/issue-42`
3. **Read Issue** - Fetch issue body + comments from GitHub API
4. **Analyze** - Use cognition system to understand task complexity
5. **Work** - Implement the feature/fix using existing Nebulus Atom tools
6. **Test** - Run `pytest` if tests exist
7. **Commit** - Commit changes with message referencing issue
8. **Push** - Push branch to origin
9. **PR** - Create pull request via GitHub API, link to issue
10. **Report** - POST to Overlord: `{status: "complete", pr_url: "..."}`
11. **Die** - Container exits, gets cleaned up

### Communication with Overlord

- **Heartbeat** - Every 60s: "Still working on #42..."
- **Progress** - When milestones hit: "Tests passing, creating PR..."
- **Completion** - Final report with PR link or error details

## 4. Data Flow & Communication

### Sequence Diagram

```
┌─────┐       ┌───────┐      ┌──────────┐      ┌────────┐      ┌────────┐
│ You │       │ Slack │      │ Overlord │      │ Minion │      │ GitHub │
└──┬──┘       └───┬───┘      └────┬─────┘      └───┬────┘      └───┬────┘
   │              │               │                │               │
   │ "work on #42"│               │                │               │
   │─────────────>│               │                │               │
   │              │  message      │                │               │
   │              │──────────────>│                │               │
   │              │               │  fetch issue   │               │
   │              │               │───────────────────────────────>│
   │              │               │  issue details │               │
   │              │               │<───────────────────────────────│
   │              │               │                │               │
   │              │               │  spawn container               │
   │              │               │───────────────>│               │
   │              │  "Starting!"  │                │               │
   │              │<──────────────│                │               │
   │ notification │               │                │  clone repo   │
   │<─────────────│               │                │──────────────>│
   │              │               │                │               │
   │              │               │  heartbeat     │  [working...] │
   │              │               │<───────────────│               │
   │              │  "Progress...│                │               │
   │              │<──────────────│                │               │
   │              │               │                │  push + PR    │
   │              │               │                │──────────────>│
   │              │               │  complete!     │               │
   │              │               │<───────────────│               │
   │              │  "PR ready!"  │                │               │
   │              │<──────────────│                │               │
   │ notification │               │  cleanup       │               │
   │<─────────────│               │───────────────>│ (dies)        │
   │              │               │                │               │
```

### Message Formats

**Minion → Overlord (HTTP POST):**
```json
{
    "minion_id": "minion-abc123",
    "event": "heartbeat | progress | complete | error",
    "issue": 42,
    "message": "Running tests...",
    "data": {"pr_url": "...", "branch": "..."}
}
```

**Overlord → Slack:**
```
🤖 Minion working on #42: Running tests...
✅ Minion completed #42: PR ready → github.com/org/repo/pull/43
❌ Minion failed on #42: Tests failing - see logs
```

### Overlord Internal API

| Endpoint | Purpose |
|----------|---------|
| `POST /minion/report` | Receive Minion heartbeats/completion |
| `GET /status` | Health check + active Minion list |
| `POST /spawn` | Manually trigger a Minion (internal) |

## 5. Error Handling & Recovery

### Failure Modes

| Failure Mode | Detection | Recovery |
|--------------|-----------|----------|
| Minion crashes mid-work | No heartbeat for 5 min | Overlord kills container, reports to Slack, marks issue as `needs-attention` |
| LLM times out (cold start) | Minion reports timeout | Retry once with warm-up ping first, then fail gracefully |
| Tests fail | Minion detects pytest exit code | Create PR anyway but mark as `draft`, report failure details |
| Git push rejected | Minion gets error | Pull latest, rebase, retry once, then fail with details |
| GitHub API rate limit | 403 response | Back off, notify Overlord, pause queue processing |
| Overlord crashes | Systemd/Docker restart policy | Auto-restart, Minions continue (they're independent), reconnect to Slack |

### Minion Self-Protection

```python
# Max runtime to prevent runaway Minions
MINION_TIMEOUT = 30 * 60  # 30 minutes max per issue

# If task seems too big, bail early
if cognition_result.complexity == "COMPLEX" and cognition_result.estimated_steps > 20:
    report_to_overlord("error", "Task too complex for autonomous work, needs human breakdown")
    sys.exit(1)
```

### Overlord Watchdog

```python
async def watchdog_loop():
    while True:
        for minion in get_active_minions():
            if time_since(minion.last_heartbeat) > timedelta(minutes=5):
                kill_container(minion.container_id)
                notify_slack(f"☠️ Minion on #{minion.issue} went silent, terminated")
                update_github_label(minion.issue, "needs-attention")
        await asyncio.sleep(60)
```

### Graceful Degradation

- If GitHub is down → Overlord reports "GitHub unavailable", pauses queue, retries hourly
- If LLM backend is down → Same pattern, with option to try fallback model
- If Slack is down → Overlord logs locally, queues messages, delivers when reconnected

## 6. Deployment & Configuration

### Container Architecture

```
nebulus-server
├── overlord (always running)
│   ├── Port 8080 (internal API)
│   ├── Volume: /var/lib/overlord/state.db
│   └── Network: nebulus-swarm
│
└── minion-pool (spawned on demand)
    ├── minion-abc123 (working on #42)
    ├── minion-def456 (working on #45)
    └── ... (up to MAX_CONCURRENT_MINIONS)
```

### Docker Compose

```yaml
version: "3.8"
services:
  overlord:
    image: nebulus-overlord:latest
    container_name: overlord
    restart: unless-stopped
    environment:
      - SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN}
      - SLACK_CHANNEL_ID=${SLACK_CHANNEL_ID}
      - GITHUB_TOKEN=${GITHUB_TOKEN}
      - NEBULUS_BASE_URL=http://192.168.4.30:8080/v1
      - NEBULUS_MODEL=qwen3-coder-30b
      - MAX_CONCURRENT_MINIONS=3
      - CRON_SCHEDULE=0 2 * * *
    volumes:
      - overlord-state:/var/lib/overlord
      - /var/run/docker.sock:/var/run/docker.sock
    networks:
      - nebulus-swarm

volumes:
  overlord-state:

networks:
  nebulus-swarm:
    driver: bridge
```

### Configuration File

```yaml
# /etc/nebulus/swarm.yaml
overlord:
  slack:
    bot_token: ${SLACK_BOT_TOKEN}
    channel_id: "C07XXXXXX"

  github:
    token: ${GITHUB_TOKEN}
    watched_repos:
      - west_ai_labs/nebulus-atom
      - west_ai_labs/other-project
    work_label: "nebulus-ready"

  minions:
    max_concurrent: 3
    timeout_minutes: 30
    image: nebulus-minion:latest

  cron:
    enabled: true
    schedule: "0 2 * * *"

  llm:
    base_url: http://192.168.4.30:8080/v1
    model: qwen3-coder-30b
    timeout: 600
    streaming: false
```

## 7. Testing & Verification

### Testing Layers

| Layer | What We Test | How |
|-------|--------------|-----|
| Unit | Overlord command parsing, state management | pytest with mocks |
| Unit | Minion workflow steps (clone, branch, PR) | pytest with mocks |
| Integration | Overlord ↔ Minion communication | Docker Compose test environment |
| Integration | GitHub API interactions | VCR cassettes (recorded responses) |
| End-to-End | Full flow: Slack → Overlord → Minion → PR | Test repo + test Slack channel |

### Test Repository

Create `west_ai_labs/nebulus-swarm-testbed` with:
- Simple Python project
- Pre-written "easy win" issues (`Add a multiply function`)
- Used exclusively for E2E testing

### Verification Checklist

**Overlord:**
- [ ] Connects to Slack and responds to "ping"
- [ ] Parses natural language commands correctly
- [ ] Spawns Minion container on demand
- [ ] Receives heartbeats and updates state
- [ ] Cleans up dead Minions after timeout
- [ ] Survives restart (state persists in SQLite)

**Minion:**
- [ ] Clones repo successfully
- [ ] Creates branch with correct naming
- [ ] Reads issue and understands task
- [ ] Makes appropriate code changes
- [ ] Runs tests if present
- [ ] Creates PR linked to issue
- [ ] Reports completion to Overlord
- [ ] Dies cleanly after work

**Full Flow:**
- [ ] Slack "work on #1" → PR created in < 10 min
- [ ] Cron trigger processes queue correctly
- [ ] Multiple Minions can run in parallel
- [ ] Failed Minion gets cleaned up, Slack notified

### Smoke Test Script

```bash
#!/bin/bash
# scripts/smoke-test.sh
# Quick validation after deployment

echo "1. Testing Overlord ping..."
# Posts "ping" to Slack → expects "pong"

echo "2. Creating test issue..."
# Creates test issue with nebulus-ready label

echo "3. Triggering Minion..."
# Tells Overlord to work on it

echo "4. Waiting for PR..."
# Waits for PR (timeout 15 min)

echo "5. Verifying PR..."
# Verifies PR exists and links to issue
```

## 8. Implementation Roadmap

### Phase 1: Overlord Foundation (Week 1)
- [ ] Create `nebulus_swarm/` package structure
- [ ] Slack Bolt integration - connect, listen, respond to "ping"
- [ ] Basic command parser (regex-based, upgrade to LLM later)
- [ ] SQLite state management
- [ ] Docker SDK integration - spawn/kill containers
- [ ] Health check endpoint

### Phase 2: Minion MVP (Week 2)
- [ ] Minion Dockerfile based on Nebulus Atom
- [ ] Entrypoint script: clone → branch → read issue
- [ ] Integrate existing Nebulus Atom agent for the "work" phase
- [ ] Heartbeat reporting to Overlord
- [ ] Git push + PR creation via GitHub API
- [ ] Completion reporting

### Phase 3: Wire It Together (Week 3)
- [ ] Overlord spawns Minion on Slack command
- [ ] Minion reports back, Overlord relays to Slack
- [ ] Watchdog for stuck Minions
- [ ] End-to-end test with testbed repo
- [ ] Error handling for common failures

### Phase 4: Cron & Polish (Week 4)
- [ ] Cron-triggered queue sweeps
- [ ] GitHub label management (`nebulus-ready` → `in-progress` → `in-review`)
- [ ] Multiple repo support
- [ ] Concurrent Minion limits
- [ ] LLM warm-up ping before heavy work

### Phase 5: Production Hardening (Week 5)
- [ ] Logging and observability (integrate with existing telemetry)
- [ ] Graceful shutdown handling
- [ ] Rate limiting for GitHub API
- [ ] Documentation and runbooks
- [ ] Deployment scripts for Nebulus server

### Phase 6: Automated PR Review (Future)

> **Note:** Initially, all Minion PRs will be reviewed manually by the human operator.
> This allows us to catch local LLM quirks, build a "failure corpus" for prompt tuning,
> and understand when 8B vs 30B models are appropriate. Phase 6 should only be
> implemented after sufficient manual review experience.

- [ ] AI Reviewer agent examines Minion PRs before notifying human
- [ ] Automated checks: tests pass, code style, security scan, complexity analysis
- [ ] Reviewer adds inline comments on concerning code
- [ ] Reviewer posts summary: approval or request-changes with reasoning
- [ ] Human receives pre-screened PRs with AI review notes
- [ ] Configurable auto-merge for low-risk, reviewer-approved PRs

**Review Flow (Phase 6):**
```
Minion creates PR → AI Reviewer examines → Posts review notes → Human final approval
```

### Stretch Goals (Future)
- [ ] Overlord uses LLM for natural language understanding
- [ ] Minion can ask clarifying questions via Slack before starting
- [ ] Web dashboard showing Minion status and history
- [ ] Multi-LLM support (route simple tasks to 8B, complex to 30B)

## 9. References

- [OpenClaw](https://openclaw.ai/) - Proactive AI agent with cron jobs and persistent memory
- [SWE-agent](https://github.com/SWE-agent/SWE-agent) - GitHub issue solving agent from Princeton/Stanford
- [AWS Remote SWE Agents](https://github.com/aws-samples/remote-swe-agents) - GitHub Actions triggered agent system
- [Slack Bolt SDK](https://slack.dev/bolt-python/) - Official Python framework for Slack apps
- [Docker SDK for Python](https://docker-py.readthedocs.io/) - Programmatic container management

---

**Document History:**
| Date | Author | Change |
|------|--------|--------|
| 2026-02-02 | @jlwestsr, Claude | Initial design |
| 2026-02-02 | @jlwestsr, Claude | Added Phase 6: Automated PR Review |
