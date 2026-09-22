"""SQLite persistence for video generation tasks.

Everything that touches the database lives here. Swapping to Postgres means
reimplementing this module (the SQL is close to portable; the UPSERT and
PRAGMA calls are the SQLite-specific parts).
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DEFAULT_DB_PATH = os.environ.get("VIDEOGEN_DB", "videogen.db")

TASKS_TABLE = "video_tasks"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(
    db_path: str | Path = DEFAULT_DB_PATH, check_same_thread: bool = True
) -> sqlite3.Connection:
    """Open a connection.

    The API server polls in a background thread, so it passes
    check_same_thread=False and keeps one connection per thread.
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


def columns(conn: sqlite3.Connection, table: str = TASKS_TABLE) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def _sqlite_type(value: Any) -> str:
    if isinstance(value, bool) or isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    return "TEXT"


def ensure_columns(
    conn: sqlite3.Connection, row: Mapping[str, Any], table: str = TASKS_TABLE
) -> list[str]:
    """Add a column for any response field we have not seen before.

    The API grows new parameters over time; rather than dropping them into a
    JSON blob only, give each one a real column. Additive only — nothing is
    ever dropped or retyped.
    """
    existing = set(columns(conn, table))
    added: list[str] = []
    for key, value in row.items():
        if key in existing:
            continue
        col_type = _sqlite_type(value)
        conn.execute(f'ALTER TABLE {table} ADD COLUMN "{key}" {col_type}')
        added.append(f"{key} {col_type}")
    if added:
        conn.commit()
    return added


def upsert_task(
    conn: sqlite3.Connection,
    row: Mapping[str, Any],
    table: str = TASKS_TABLE,
    overwrite: Iterable[str] = (),
) -> None:
    """Insert or update a task row by id, leaving untouched columns alone.

    None values never overwrite an existing non-null value, so a later poll
    that omits a field cannot erase what an earlier one recorded.

    `overwrite` names columns that are recomputed from scratch each time and
    so must be written verbatim, NULLs included. Cost columns work this way:
    a queued task carries a "projected..." note that the final, token-priced
    value clears, and COALESCE would otherwise keep the stale note alongside
    the exact price.
    """
    if "id" not in row:
        raise ValueError("row must contain 'id'")

    ensure_columns(conn, row, table)

    forced = set(overwrite)
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    col_sql = ", ".join(f'"{c}"' for c in cols)
    updates = ", ".join(
        (f'"{c}" = excluded."{c}"' if c in forced
         else f'"{c}" = COALESCE(excluded."{c}", {table}."{c}")')
        for c in cols if c != "id"
    )
    sql = (
        f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}"
    )
    conn.execute(sql, [_bind(row[c]) for c in cols])
    conn.commit()


def _bind(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def bump_poll(conn: sqlite3.Connection, task_id: str) -> None:
    conn.execute(
        f"UPDATE {TASKS_TABLE} SET poll_count = poll_count + 1, last_polled_at = ? "
        "WHERE id = ?",
        (utcnow(), task_id),
    )
    conn.commit()


def replace_references(
    conn: sqlite3.Connection, task_id: str, references: Sequence[Mapping[str, Any]]
) -> None:
    conn.execute("DELETE FROM task_references WHERE task_id = ?", (task_id,))
    conn.executemany(
        "INSERT INTO task_references (task_id, position, ref_type, role, url) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (task_id, i, r.get("ref_type"), r.get("role"), r.get("url"))
            for i, r in enumerate(references)
        ],
    )
    conn.commit()


def log_event(
    conn: sqlite3.Connection, task_id: str, status: str | None, detail: str | None = None
) -> None:
    conn.execute(
        "INSERT INTO task_events (task_id, observed_at, status, detail) VALUES (?, ?, ?, ?)",
        (task_id, utcnow(), status, detail),
    )
    conn.commit()


def last_event_status(conn: sqlite3.Connection, task_id: str) -> str | None:
    row = conn.execute(
        "SELECT status FROM task_events WHERE task_id = ? ORDER BY event_id DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    return row["status"] if row else None


def get_task(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT * FROM {TASKS_TABLE} WHERE id = ?", (task_id,)
    ).fetchone()


def unfinished_tasks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT * FROM {TASKS_TABLE} "
        "WHERE status IS NULL OR status NOT IN ('succeeded', 'failed', 'cancelled') "
        "ORDER BY submitted_at"
    ).fetchall()


def list_tasks(
    conn: sqlite3.Connection, status: str | None = None, limit: int = 50
) -> list[sqlite3.Row]:
    if status:
        return conn.execute(
            "SELECT * FROM v_video_tasks WHERE status = ? "
            "ORDER BY created_at_utc DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM v_video_tasks ORDER BY created_at_utc DESC LIMIT ?", (limit,)
    ).fetchall()


def export_csv(conn: sqlite3.Connection, path: str | Path, view: str = "v_video_tasks") -> int:
    import csv

    rows: Iterable[sqlite3.Row] = conn.execute(f"SELECT * FROM {view}").fetchall()
    rows = list(rows)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if rows:
            writer.writerow(rows[0].keys())
            writer.writerows([list(r) for r in rows])
    return len(rows)
