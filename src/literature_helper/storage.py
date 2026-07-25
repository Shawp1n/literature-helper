from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .models import (
    ACTIVE_STATUSES,
    LiteratureMetadata,
    Task,
    TaskStatus,
    classify_query,
    utc_now,
)


_UNSET = object()


class TaskStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    query_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_url TEXT,
                    download_path TEXT,
                    literature_json TEXT,
                    validation_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    message TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_events_task_id ON events(task_id, id);
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "literature_json" not in columns:
                connection.execute(
                    "ALTER TABLE tasks ADD COLUMN literature_json TEXT"
                )

    def create(self, query: str) -> Task:
        task_id = uuid.uuid4().hex[:12]
        now = utc_now()
        task = Task(
            id=task_id,
            query=query,
            query_type=classify_query(query),
            status=TaskStatus.CREATED,
            request_url=None,
            download_path=None,
            literature=None,
            validation=None,
            error=None,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    id, query, query_type, status, request_url, download_path,
                    literature_json, validation_json, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.query,
                    task.query_type,
                    task.status.value,
                    None,
                    None,
                    None,
                    None,
                    None,
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO events (task_id, status, message, created_at) VALUES (?, ?, ?, ?)",
                (task.id, task.status.value, "任务已创建", now),
            )
        return task

    def update(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        message: str | None = None,
        request_url: str | None = None,
        download_path: Path | None = None,
        literature: LiteratureMetadata | None | object = _UNSET,
        validation: dict[str, Any] | None = None,
        error: str | None | object = _UNSET,
    ) -> Task:
        current = self.get(task_id)
        now = utc_now()
        request_value = request_url if request_url is not None else current.request_url
        download_value = (
            str(download_path)
            if download_path is not None
            else (str(current.download_path) if current.download_path else None)
        )
        validation_value = (
            json.dumps(validation, ensure_ascii=False)
            if validation is not None
            else (
                json.dumps(current.validation, ensure_ascii=False)
                if current.validation is not None
                else None
            )
        )
        literature_value = (
            json.dumps(literature.to_dict(), ensure_ascii=False)
            if isinstance(literature, LiteratureMetadata)
            else (
                json.dumps(current.literature.to_dict(), ensure_ascii=False)
                if literature is _UNSET and current.literature is not None
                else None
            )
        )
        error_value = current.error if error is _UNSET else error

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = ?, request_url = ?, download_path = ?,
                    literature_json = ?, validation_json = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    request_value,
                    download_value,
                    literature_value,
                    validation_value,
                    error_value,
                    now,
                    task_id,
                ),
            )
            connection.execute(
                "INSERT INTO events (task_id, status, message, created_at) VALUES (?, ?, ?, ?)",
                (task_id, status.value, message, now),
            )
        return self.get(task_id)

    def get(self, task_id: str) -> Task:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"找不到任务: {task_id}")
        return self._row_to_task(row)

    def list(self, *, limit: int = 20) -> list[Task]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def events(self, task_id: str) -> list[dict[str, Any]]:
        self.get(task_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT status, message, created_at
                FROM events WHERE task_id = ? ORDER BY id
                """,
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def active(self) -> list[Task]:
        values = tuple(item.value for item in ACTIVE_STATUSES)
        placeholders = ",".join("?" for _ in values)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM tasks WHERE status IN ({placeholders}) ORDER BY created_at",
                values,
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def publish_attempt_exists(self, query: str) -> bool:
        """Return True once this query has reached the one-shot publish boundary."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM events AS e
                JOIN tasks AS t ON t.id = e.task_id
                WHERE t.query = ? AND e.status = ?
                LIMIT 1
                """,
                (query, TaskStatus.PUBLISHED.value),
            ).fetchone()
        return row is not None

    def pending_reviews(self) -> list[Task]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM tasks
                WHERE status = ?
                ORDER BY created_at
                """,
                (TaskStatus.DOWNLOADED_PENDING_REVIEW.value,),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            query=row["query"],
            query_type=row["query_type"],
            status=TaskStatus(row["status"]),
            request_url=row["request_url"],
            download_path=Path(row["download_path"]) if row["download_path"] else None,
            literature=(
                LiteratureMetadata.from_dict(json.loads(row["literature_json"]))
                if row["literature_json"]
                else None
            ),
            validation=json.loads(row["validation_json"]) if row["validation_json"] else None,
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
