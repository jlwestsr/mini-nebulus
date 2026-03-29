# Swarm Dashboard Design

**Date:** 2026-02-03
**Status:** APPROVED
**Authors:** @jlwestsr, Claude Opus 4.5

## Goal

A standalone Streamlit dashboard for monitoring the Nebulus Swarm: real-time minion status, work history, GitHub queue, and aggregate metrics. Read-only ops view with auto-refresh.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Placement | New app in `nebulus_swarm/dashboard/` | Different domain from CLI telemetry, different deployment context |
| Data source | SQLite + API hybrid | Real-time from Overlord HTTP API, historical from state.db |
| Pages | Live, History, Queue, Metrics | Full ops coverage: monitoring + review + analytics |
| Refresh | Auto-refresh with toggle (10s) | Live monitoring when watching, stable view when reading |
| Auth | None (V1) | Read-only, private network. Can add later. |

## Architecture

```
nebulus_swarm/dashboard/
├── __init__.py
├── app.py              # Entry point, sidebar, page routing, auto-refresh
├── data.py             # SwarmDataClient (API + SQLite)
└── pages/
    ├── live.py          # Active minions, health, pending questions
    ├── history.py       # Work log with filters
    ├── queue.py         # Pending GitHub issues
    └── metrics.py       # Success rate, duration, throughput charts
```

**Data flow:**
```
Overlord HTTP API ──→ SwarmDataClient ──→ Streamlit Pages
  GET /status              │
  GET /queue               │
                           │
state.db (SQLite) ─────────┘
  work_history table
  minions table
```

**Entry point:**
```bash
streamlit run nebulus_swarm/dashboard/app.py
```

## SwarmDataClient

Single class that abstracts both data sources:

```python
class SwarmDataClient:
    def __init__(self, overlord_url: str, state_db_path: str):
        self._url = overlord_url
        self._state = OverlordState(db_path=state_db_path)

    # Real-time (API)
    def get_status(self) -> dict: ...         # GET /status
    def get_queue(self) -> list[dict]: ...    # GET /queue

    # Historical (SQLite)
    def get_work_history(self, repo=None, status=None, limit=50) -> list[dict]: ...
    def get_metrics(self, days=7) -> dict: ...
```

API responses are cached for 5 seconds to avoid hammering the Overlord during auto-refresh.

## Page Designs

### Live Status Page

**Top row** - Metric cards (`st.metric()`):
- Overlord health (healthy/unhealthy)
- Active minions / max concurrent
- Queue status (paused/active)
- Docker availability

**Active Minions table:**
- Columns: ID, repo, issue #, status, elapsed time, last heartbeat
- Stale heartbeats (>2 min) get warning indicator
- Issue numbers link to GitHub
- Empty state: "No active minions"

**Pending Questions section:**
- Shows minions waiting for human answers (from E.2 feature)
- Displays question text, wait time, "answer in Slack" note
- Data from `pending_questions` field added to `/status` response

### Work History Page

**Filter bar:**
- Repo selector (dropdown from available repos)
- Status filter (all/completed/failed/timeout)
- Limit slider (10-100, default 50)

**History table** (`st.dataframe()`):
- Columns: repo, issue #, status (color-coded), PR # (linked), duration, error, timestamp
- Sorted by most recent first
- Green = completed, red = failed, orange = timeout

**Summary row:**
- Total records, completion rate, average duration

**Data:** `OverlordState.get_work_history()` with added `status` filter parameter.

### Queue Page

**Queue summary:**
- Total pending issues
- Available minion slots
- Queue processing status (paused/active)

**Pending issues table:**
- Columns: repo, issue #, title, priority, age
- Sorted by priority then age

**Data:** New `GET /queue` endpoint on Overlord that caches last scan results. If Overlord unreachable or no scan yet: "Queue data unavailable - waiting for next scan."

### Metrics Page

**Time range selector:** Last 24h, 7 days, 30 days, all time.

**Success Rate:**
- Big number with color indicator (green >80%, yellow >50%, red below)
- Breakdown bar: X completed, Y failed, Z timeout

**Duration Trends:**
- Bar chart: average duration per day (`st.bar_chart()`)
- Stats: median, fastest, slowest

**Throughput:**
- Line chart: tasks completed per day

**Failure Analysis:**
- Table grouped by error type with count and most recent message

**Data:** SQL aggregations on work_history table via pandas DataFrames.

## Overlord Changes

### `/status` endpoint addition

Add `pending_questions` to the response:

```python
async def _status_handler(self, request):
    return web.json_response({
        ...existing fields...
        "pending_questions": [
            {
                "minion_id": pq.minion_id,
                "question_id": pq.question_id,
                "issue_number": pq.issue_number,
                "question_text": pq.question_text,
                "asked_at": pq.asked_at.isoformat(),
                "answered": pq.answered,
            }
            for pq in self._pending_questions.values()
        ],
    })
```

### New `GET /queue` endpoint

```python
# Cached last scan results
self._last_queue_scan: list[dict] = []

async def _queue_handler(self, request):
    return web.json_response({
        "issues": self._last_queue_scan,
        "paused": self._paused,
    })
```

Updated during `_sweep_queue()` to cache scan results.

### State query enhancement

Add `status` filter to `get_work_history()`:

```python
def get_work_history(self, repo=None, status=None, limit=50):
    query = "SELECT * FROM work_history WHERE 1=1"
    params = []
    if repo:
        query += " AND repo = ?"
        params.append(repo)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY completed_at DESC LIMIT ?"
    params.append(limit)
    ...
```

## Error Handling

| Scenario | Handling |
|----------|----------|
| Overlord unreachable | Red banner on Live/Queue pages, History/Metrics still work |
| State DB missing | Empty states ("No work history yet") |
| State DB empty | Graceful empty tables and zero-value metrics |
| API timeout | Show last cached data with "stale" indicator |
| Auto-refresh off | Static page until manual refresh |

## Configuration

| Env Var | Default | Purpose |
|---------|---------|---------|
| `OVERLORD_URL` | `http://localhost:8080` | Overlord HTTP base URL |
| `OVERLORD_STATE_DB` | `/var/lib/overlord/state.db` | Path to state database |

Both also configurable in sidebar for development.

## Files to Create/Modify

| File | Action |
|------|--------|
| `nebulus_swarm/dashboard/__init__.py` | Create |
| `nebulus_swarm/dashboard/app.py` | Create |
| `nebulus_swarm/dashboard/data.py` | Create |
| `nebulus_swarm/dashboard/pages/live.py` | Create |
| `nebulus_swarm/dashboard/pages/history.py` | Create |
| `nebulus_swarm/dashboard/pages/queue.py` | Create |
| `nebulus_swarm/dashboard/pages/metrics.py` | Create |
| `nebulus_swarm/overlord/main.py` | Add pending_questions to /status, add GET /queue |
| `nebulus_swarm/overlord/state.py` | Add status filter to get_work_history() |
| `tests/test_swarm_dashboard.py` | Create |

## Testing

- SwarmDataClient: mocked HTTP responses + test SQLite database
- Page functions: verify rendering with sample data (no browser tests)
- Overlord endpoints: test new /queue endpoint and /status additions
- State query: test status filter on get_work_history()

---

**Document History:**
| Date | Author | Change |
|------|--------|--------|
| 2026-02-03 | @jlwestsr, Claude | Initial design |
