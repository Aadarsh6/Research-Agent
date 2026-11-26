"""
Simple SQLite storage — no server, one file, perfect for a minor project.

Stores every finished research run: topic, report (as JSON), sources
(as JSON) and the date/time, so the user can revisit past research.
"""

import json
import sqlite3
from datetime import datetime

import os

# Always next to the backend code, no matter where uvicorn is started from.
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research_history.db")


def _connect():
    """Open a connection with row access by column name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the table if it does not exist yet (safe to call often)."""
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS research (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                topic      TEXT NOT NULL,
                report     TEXT NOT NULL,   -- full report stored as JSON
                sources    TEXT NOT NULL,   -- references stored as JSON
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def save_research(topic: str, report: dict, sources: list[dict]) -> int:
    """Store one finished research run. Returns its database id."""
    conn = _connect()
    try:
        cursor = conn.execute(
            "INSERT INTO research (topic, report, sources, created_at) VALUES (?, ?, ?, ?)",
            (
                topic,
                json.dumps(report, ensure_ascii=False),
                json.dumps(sources, ensure_ascii=False),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_all_research() -> list[dict]:
    """Return all saved runs (newest first), without the heavy report text."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, topic, created_at FROM research ORDER BY id DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_research(run_id: int) -> dict | None:
    """Return one saved run including its report and sources."""
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM research WHERE id = ?", (run_id,)).fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    record = dict(row)
    record["report"] = json.loads(record["report"])
    record["sources"] = json.loads(record["sources"])
    return record


def delete_research(run_id: int):
    """Remove one research run from history."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM research WHERE id = ?", (run_id,))
        conn.commit()
    finally:
        conn.close()
