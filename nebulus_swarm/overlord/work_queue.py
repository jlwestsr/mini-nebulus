"""SQLite-backed work queue with state machine for the Overlord.

Provides task lifecycle management with dependency tracking, locking,
audit logging, and GitHub Issue sync support. Follows the same SQLite
patterns as memory.py and proposal_manager.py.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".atom" / "overlord" / "work_queue.db"

# Valid task statuses
VALID_STATUSES = frozenset(
    {"backlog", "active", "dispatched", "in_review", "completed", "failed"}
)

# Valid task priorities
VALID_PRIORITIES = frozenset({"low", "medium", "high", "critical"})

# State machine: source -> set of valid targets
TRANSITIONS: dict[str, set[str]] = {
    "backlog": {"active", "failed"},
    "active": {"dispatched", "backlog", "failed"},
    "dispatched": {"in_review", "failed"},
    "in_review": {"completed", "failed", "active"},
    "failed": {"backlog"},
    "completed": set(),  # terminal
}


@dataclass
class Task:
    """A work queue task."""

    id: str
    title: str
    project: str
    status: str = "backlog"
    priority: str = "medium"
    complexity: str = "medium"
    description: Optional[str] = None
    external_id: Optional[str] = None
    external_source: Optional[str] = None
    locked_by: Optional[str] = None
    locked_at: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 2
    mirror_path: Optional[str] = None
    token_budget: Optional[int] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class TaskLogEntry:
    """An entry in the task audit log."""

    id: int = 0
    task_id: str = ""
    old_status: str = ""
    new_status: str = ""
    changed_by: str = ""
    timestamp: str = ""
    reason: Optional[str] = None


@dataclass
class DispatchResultRecord:
    """A record of a dispatch execution against a task."""

    task_id: str = ""
    worker_id: str = ""
    model_id: str = ""
    branch_name: str = ""
    mission_brief_path: str = ""
    review_status: str = ""
    usage_stats: dict = field(default_factory=dict)
    output_log: str = ""
    tokens_used: int = 0
    created_at: str = ""
    id: int = 0


class WorkQueue:
    """SQLite-backed work queue with state machine enforcement."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Initialize the work queue.

        Args:
            db_path: Path to SQLite database file.
                     Defaults to ~/.atom/overlord/work_queue.db.
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a database connection with row factory and FK enforcement."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    external_id TEXT,
                    external_source TEXT,
                    project TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL DEFAULT 'backlog'
                        CHECK(status IN (
                            'backlog', 'active', 'dispatched',
                            'in_review', 'completed', 'failed'
                        )),
                    priority TEXT NOT NULL DEFAULT 'medium'
                        CHECK(priority IN ('low', 'medium', 'high', 'critical')),
                    complexity TEXT NOT NULL DEFAULT 'medium',
                    locked_by TEXT,
                    locked_at TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 2,
                    mirror_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(external_id, external_source)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_dependencies (
                    task_id TEXT NOT NULL,
                    depends_on_task_id TEXT NOT NULL,
                    PRIMARY KEY (task_id, depends_on_task_id),
                    CHECK(task_id != depends_on_task_id),
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                    FOREIGN KEY (depends_on_task_id) REFERENCES tasks(id)
                        ON DELETE CASCADE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    old_status TEXT NOT NULL,
                    new_status TEXT NOT NULL,
                    changed_by TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    reason TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dispatch_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    model_id TEXT NOT NULL DEFAULT '',
                    branch_name TEXT NOT NULL DEFAULT '',
                    mission_brief_path TEXT NOT NULL DEFAULT '',
                    review_status TEXT NOT NULL DEFAULT '',
                    usage_stats TEXT DEFAULT '{}',
                    output_log TEXT DEFAULT '',
                    tokens_used INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cost_ledger (
                    date TEXT PRIMARY KEY,
                    tokens_input INTEGER NOT NULL DEFAULT 0,
                    tokens_output INTEGER NOT NULL DEFAULT 0,
                    estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
                    ceiling_usd REAL NOT NULL DEFAULT 10.0,
                    updated_at TEXT NOT NULL
                )
            """)

            # Idempotent column additions for schema migration
            self._add_column_if_missing(cursor, "tasks", "token_budget", "INTEGER")
            self._add_column_if_missing(
                cursor,
                "tasks",
                "max_retries",
                "INTEGER NOT NULL DEFAULT 2",
            )
            self._add_column_if_missing(
                cursor,
                "dispatch_results",
                "tokens_used",
                "INTEGER NOT NULL DEFAULT 0",
            )

            # Indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_status
                ON tasks(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_project
                ON tasks(project)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_external
                ON tasks(external_id, external_source)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_log_task_id
                ON task_log(task_id)
            """)

    @staticmethod
    def _add_column_if_missing(
        cursor: sqlite3.Cursor,
        table: str,
        column: str,
        col_type: str,
    ) -> None:
        """Add a column to a table if it doesn't already exist.

        Args:
            cursor: Active database cursor.
            table: Table name.
            column: Column name.
            col_type: Column type definition.
        """
        info = cursor.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {row["name"] for row in info}
        if column not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        """Convert a database row to a Task."""
        keys = row.keys()
        return Task(
            id=row["id"],
            title=row["title"],
            project=row["project"],
            status=row["status"],
            priority=row["priority"],
            complexity=row["complexity"],
            description=row["description"],
            external_id=row["external_id"],
            external_source=row["external_source"],
            locked_by=row["locked_by"],
            locked_at=row["locked_at"],
            retry_count=row["retry_count"],
            max_retries=row["max_retries"],
            mirror_path=row["mirror_path"],
            token_budget=row["token_budget"] if "token_budget" in keys else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_log_entry(self, row: sqlite3.Row) -> TaskLogEntry:
        """Convert a database row to a TaskLogEntry."""
        return TaskLogEntry(
            id=row["id"],
            task_id=row["task_id"],
            old_status=row["old_status"],
            new_status=row["new_status"],
            changed_by=row["changed_by"],
            timestamp=row["timestamp"],
            reason=row["reason"],
        )

    def _row_to_dispatch_result(self, row: sqlite3.Row) -> DispatchResultRecord:
        """Convert a database row to a DispatchResultRecord."""
        keys = row.keys()
        return DispatchResultRecord(
            id=row["id"],
            task_id=row["task_id"],
            worker_id=row["worker_id"],
            model_id=row["model_id"],
            branch_name=row["branch_name"],
            mission_brief_path=row["mission_brief_path"],
            review_status=row["review_status"],
            usage_stats=json.loads(row["usage_stats"]) if row["usage_stats"] else {},
            output_log=row["output_log"],
            tokens_used=row["tokens_used"] if "tokens_used" in keys else 0,
            created_at=row["created_at"],
        )

    def add_task(
        self,
        title: str,
        project: str,
        *,
        description: Optional[str] = None,
        priority: str = "medium",
        complexity: str = "medium",
        external_id: Optional[str] = None,
        external_source: Optional[str] = None,
        mirror_path: Optional[str] = None,
        token_budget: Optional[int] = None,
    ) -> str:
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    id, title, project, description, status, priority,
                    complexity, external_id, external_source, mirror_path,
                    token_budget, retry_count, max_retries, created_at, updated_at
                ) VALUES (?, ?, ?, ?, "backlog", ?, ?, ?, ?, ?, ?, 0, 2, ?, ?)
                """,
                (
                    task_id,
                    title,
                    project,
                    description,
                    priority,
                    complexity,
                    external_id,
                    external_source,
                    mirror_path,
                    token_budget,
                    now,
                    now,
                ),
            )

        logger.info("Created task %s: %s [%s]", task_id[:8], title, project)
        return task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID.

        Args:
            task_id: UUID of the task.

        Returns:
            Task if found, None otherwise.
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return self._row_to_task(row) if row else None

    def update_task(
        self,
        task_id: str,
        *,
        token_budget: Optional[int] = None,
    ) -> None:
        """Update mutable fields on a task.

        Args:
            task_id: UUID of the task.
            token_budget: New per-task token budget (None = no change).

        Raises:
            ValueError: If the task does not exist.
        """
        updates: list[str] = []
        params: list[object] = []

        if token_budget is not None:
            updates.append("token_budget = ?")
            params.append(token_budget)

        if not updates:
            return

        updates.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(task_id)

        sql = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?"
        with self._get_connection() as conn:
            cursor = conn.execute(sql, params)
            if cursor.rowcount == 0:
                raise ValueError(f"Task not found: {task_id}")

    def list_tasks(
        self,
        *,
        status: Optional[str] = None,
        project: Optional[str] = None,
        limit: int = 50,
    ) -> list[Task]:
        """List tasks with optional filters.

        Args:
            status: Filter by status.
            project: Filter by project.
            limit: Maximum number of results.

        Returns:
            List of Task objects, newest first.
        """
        sql = "SELECT * FROM tasks WHERE 1=1"
        params: list[object] = []

        if status:
            sql += " AND status = ?"
            params.append(status)
        if project:
            sql += " AND project = ?"
            params.append(project)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_task(row) for row in rows]

    def transition(
        self,
        task_id: str,
        new_status: str,
        changed_by: str,
        reason: Optional[str] = None,
    ) -> Task:
        """Transition a task to a new status, enforcing the state machine.

        Args:
            task_id: UUID of the task.
            new_status: Target status.
            changed_by: Who initiated the transition.
            reason: Optional reason for the transition.

        Returns:
            The updated Task.

        Raises:
            ValueError: If the transition is invalid or task not found.
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Task not found: {task_id}")

            old_status = row["status"]

            if new_status not in TRANSITIONS.get(old_status, set()):
                raise ValueError(f"Invalid transition: {old_status} -> {new_status}")

            now = datetime.now(timezone.utc).isoformat()
            retry_count = row["retry_count"]

            # Increment retry on failed -> backlog
            if old_status == "failed" and new_status == "backlog":
                retry_count += 1

            conn.execute(
                """
                UPDATE tasks
                SET status = ?, retry_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_status, retry_count, now, task_id),
            )

            # Write audit log
            conn.execute(
                """
                INSERT INTO task_log
                    (task_id, old_status, new_status, changed_by, timestamp, reason)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, old_status, new_status, changed_by, now, reason),
            )

            # Re-read updated task
            updated = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return self._row_to_task(updated)

    def lock_task(self, task_id: str, worker_id: str) -> Task:
        """Lock a task for a worker.

        Args:
            task_id: UUID of the task.
            worker_id: ID of the worker claiming the lock.

        Returns:
            The updated Task.

        Raises:
            ValueError: If the task is already locked or not found.
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Task not found: {task_id}")
            if row["locked_by"]:
                raise ValueError(f"Task {task_id} already locked by {row['locked_by']}")

            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE tasks SET locked_by = ?, locked_at = ?, updated_at = ? WHERE id = ?",
                (worker_id, now, now, task_id),
            )

            updated = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return self._row_to_task(updated)

    def unlock_task(self, task_id: str) -> None:
        """Release a lock on a task.

        Args:
            task_id: UUID of the task.
        """
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE tasks SET locked_by = NULL, locked_at = NULL, "
                "updated_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), task_id),
            )

    def reclaim_stale_locks(self, timeout_minutes: int = 30) -> list[str]:
        """Unlock tasks that have been locked longer than timeout_minutes.

        Args:
            timeout_minutes: Minutes after which a lock is considered stale.

        Returns:
            List of task IDs that were unlocked.
        """
        from datetime import timedelta

        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
        ).isoformat()

        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id FROM tasks WHERE locked_by IS NOT NULL AND locked_at < ?",
                (cutoff,),
            ).fetchall()

            task_ids = [row["id"] for row in rows]
            if task_ids:
                placeholders = ",".join("?" for _ in task_ids)
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    f"UPDATE tasks SET locked_by = NULL, locked_at = NULL, "
                    f"updated_at = ? WHERE id IN ({placeholders})",
                    [now] + task_ids,
                )

            return task_ids

    def get_eligible_for_dispatch(self, project: Optional[str] = None) -> list[Task]:
        """Get tasks that are active, unlocked, and have no pending dependencies.

        Args:
            project: Optional project filter.

        Returns:
            List of eligible Task objects.
        """
        sql = """
            SELECT t.* FROM tasks t
            WHERE t.status = 'active'
              AND t.locked_by IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM task_dependencies td
                  JOIN tasks dep ON dep.id = td.depends_on_task_id
                  WHERE td.task_id = t.id
                    AND dep.status != 'completed'
              )
        """
        params: list[object] = []

        if project:
            sql += " AND t.project = ?"
            params.append(project)

        sql += " ORDER BY t.created_at ASC"

        with self._get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_task(row) for row in rows]

    def add_dependency(self, task_id: str, depends_on_task_id: str) -> None:
        """Add a dependency between tasks.

        Args:
            task_id: The task that depends on another.
            depends_on_task_id: The task that must complete first.

        Raises:
            ValueError: If task_id == depends_on_task_id.
            sqlite3.IntegrityError: If the dependency already exists or
                references nonexistent tasks.
        """
        if task_id == depends_on_task_id:
            raise ValueError("A task cannot depend on itself")

        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO task_dependencies (task_id, depends_on_task_id) "
                "VALUES (?, ?)",
                (task_id, depends_on_task_id),
            )

    def get_dependencies(self, task_id: str) -> list[Task]:
        """Get tasks that a given task depends on.

        Args:
            task_id: The dependent task.

        Returns:
            List of dependency Task objects.
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT t.* FROM tasks t
                JOIN task_dependencies td ON t.id = td.depends_on_task_id
                WHERE td.task_id = ?
                """,
                (task_id,),
            ).fetchall()
            return [self._row_to_task(row) for row in rows]

    def get_task_log(self, task_id: str) -> list[TaskLogEntry]:
        """Get the audit log for a task.

        Args:
            task_id: UUID of the task.

        Returns:
            List of TaskLogEntry objects, ordered by timestamp.
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM task_log WHERE task_id = ? ORDER BY timestamp ASC",
                (task_id,),
            ).fetchall()
            return [self._row_to_log_entry(row) for row in rows]

    def record_dispatch_result(self, result: DispatchResultRecord) -> int:
        """Record a dispatch execution result.

        Args:
            result: The dispatch result to record.

        Returns:
            The auto-generated ID of the new record.
        """
        now = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO dispatch_results (
                    task_id, worker_id, model_id, branch_name,
                    mission_brief_path, review_status, usage_stats,
                    output_log, tokens_used, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.task_id,
                    result.worker_id,
                    result.model_id,
                    result.branch_name,
                    result.mission_brief_path,
                    result.review_status,
                    json.dumps(result.usage_stats),
                    result.output_log,
                    result.tokens_used,
                    now,
                ),
            )
            return cursor.lastrowid

    def get_dispatch_results(self, task_id: str) -> list[DispatchResultRecord]:
        """Get dispatch results for a task.

        Args:
            task_id: UUID of the task.

        Returns:
            List of DispatchResultRecord objects, newest first.
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM dispatch_results WHERE task_id = ? "
                "ORDER BY created_at DESC",
                (task_id,),
            ).fetchall()
            return [self._row_to_dispatch_result(row) for row in rows]

    def record_token_usage(
        self,
        tokens_input: int,
        tokens_output: int,
        estimated_cost_usd: float,
        ceiling_usd: float = 10.0,
    ) -> None:
        """Record token usage for today in the cost ledger.

        Args:
            tokens_input: Number of input tokens used.
            tokens_output: Number of output tokens used.
            estimated_cost_usd: Estimated cost for this usage.
            ceiling_usd: Daily ceiling in USD.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            existing = conn.execute(
                "SELECT * FROM cost_ledger WHERE date = ?", (today,)
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE cost_ledger
                    SET tokens_input = tokens_input + ?,
                        tokens_output = tokens_output + ?,
                        estimated_cost_usd = estimated_cost_usd + ?,
                        ceiling_usd = ?,
                        updated_at = ?
                    WHERE date = ?
                    """,
                    (
                        tokens_input,
                        tokens_output,
                        estimated_cost_usd,
                        ceiling_usd,
                        now,
                        today,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO cost_ledger
                        (date, tokens_input, tokens_output,
                         estimated_cost_usd, ceiling_usd, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        today,
                        tokens_input,
                        tokens_output,
                        estimated_cost_usd,
                        ceiling_usd,
                        now,
                    ),
                )

    def get_daily_usage(self, date: Optional[str] = None) -> Optional[dict]:
        """Get token usage for a given date.

        Args:
            date: Date string (YYYY-MM-DD). Defaults to today.

        Returns:
            Dict with usage data, or None if no records for the date.
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM cost_ledger WHERE date = ?", (date,)
            ).fetchone()
            if not row:
                return None
            return {
                "date": row["date"],
                "tokens_input": row["tokens_input"],
                "tokens_output": row["tokens_output"],
                "estimated_cost_usd": row["estimated_cost_usd"],
                "ceiling_usd": row["ceiling_usd"],
                "updated_at": row["updated_at"],
            }

    def check_budget_available(self, ceiling_usd: float = 10.0) -> tuple[bool, float]:
        """Check if daily budget is still available.

        Args:
            ceiling_usd: Daily ceiling in USD to check against.

        Returns:
            Tuple of (is_available, usage_percentage).
            is_available is False when usage >= ceiling.
        """
        usage = self.get_daily_usage()
        if not usage:
            return True, 0.0

        spent = usage["estimated_cost_usd"]
        pct = (spent / ceiling_usd * 100) if ceiling_usd > 0 else 100.0
        return spent < ceiling_usd, pct

    def upsert_from_github(
        self,
        external_id: str,
        external_source: str,
        title: str,
        project: str,
        *,
        description: Optional[str] = None,
        priority: str = "medium",
        token_budget: Optional[int] = None,
    ) -> tuple[str, bool]:
        now = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM tasks WHERE external_id = ? AND external_source = ?",
                (external_id, external_source),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE tasks
                    SET title = ?, description = ?, priority = ?, updated_at = ?
                    WHERE external_id = ? AND external_source = ?
                    """,
                    (title, description, priority, now, external_id, external_source),
                )
                return existing["id"], False
            else:
                task_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO tasks (
                        id, external_id, external_source, project, title,
                        description, status, priority, complexity,
                        retry_count, max_retries, token_budget, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, "backlog", ?, "medium", 0, 2, ?, ?, ?)
                    """,
                    (
                        task_id,
                        external_id,
                        external_source,
                        project,
                        title,
                        description,
                        priority,
                        token_budget,
                        now,
                        now,
                    ),
                )
                return task_id, True


__all__ = [
    "DEFAULT_DB_PATH",
    "DispatchResultRecord",
    "Task",
    "TaskLogEntry",
    "TRANSITIONS",
    "VALID_PRIORITIES",
    "VALID_STATUSES",
    "WorkQueue",
]
