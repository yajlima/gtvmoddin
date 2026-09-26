"""SQLite store for inbound/outbound messages and delivery statuses."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    direction   TEXT NOT NULL,          -- 'in' or 'out'
    wa_id       TEXT NOT NULL,          -- the other party's number
    name        TEXT,                   -- contact profile name (inbound)
    type        TEXT NOT NULL,
    text        TEXT,
    media_id    TEXT,
    reply_to    TEXT,
    timestamp   INTEGER NOT NULL,
    status      TEXT,
    raw         TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_peer ON messages (wa_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_time ON messages (timestamp);
"""

COLUMNS = ("id", "direction", "wa_id", "name", "type", "text", "media_id", "reply_to", "timestamp", "status")


class Store:
    def __init__(self, path: str | Path):
        path = Path(path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        # Shared between the MCP worker threads and the webhook thread.
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def add(self, *, id: str, direction: str, wa_id: str, type: str, text: str | None = None,
            name: str | None = None, media_id: str | None = None, reply_to: str | None = None,
            timestamp: int | None = None, status: str | None = None, raw: dict | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO messages (id, direction, wa_id, name, type, text, media_id,"
                " reply_to, timestamp, status, raw) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (id, direction, wa_id, name, type, text, media_id, reply_to,
                 int(timestamp or time.time()), status, json.dumps(raw) if raw else None),
            )

    def set_status(self, message_id: str, status: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE messages SET status = ? WHERE id = ?", (status, message_id))

    def _query(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def get(self, message_id: str) -> dict | None:
        rows = self._query(f"SELECT {', '.join(COLUMNS)} FROM messages WHERE id = ?", (message_id,))
        return rows[0] if rows else None

    def chats(self, limit: int = 20) -> list[dict]:
        return self._query(
            """
            SELECT m.wa_id,
                   (SELECT name FROM messages n WHERE n.wa_id = m.wa_id AND n.name IS NOT NULL
                     ORDER BY timestamp DESC LIMIT 1) AS name,
                   MAX(m.timestamp) AS last_timestamp,
                   COUNT(*) AS message_count,
                   SUM(CASE WHEN m.direction = 'in' AND COALESCE(m.status, '') != 'read'
                            THEN 1 ELSE 0 END) AS unread
            FROM messages m GROUP BY m.wa_id ORDER BY last_timestamp DESC LIMIT ?
            """,
            (limit,),
        )

    def messages(self, wa_id: str, limit: int = 50, before: int | None = None) -> list[dict]:
        rows = self._query(
            f"SELECT {', '.join(COLUMNS)} FROM messages WHERE wa_id = ? AND timestamp < ?"
            " ORDER BY timestamp DESC, rowid DESC LIMIT ?",
            (wa_id, before or 2**62, limit),
        )
        return rows[::-1]  # oldest first reads like a chat

    def search(self, query: str, limit: int = 50) -> list[dict]:
        like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        return self._query(
            f"SELECT {', '.join(COLUMNS)} FROM messages WHERE text LIKE ? ESCAPE '\\'"
            " ORDER BY timestamp DESC LIMIT ?",
            (like, limit),
        )

    def inbound_since(self, rowid: int, wa_id: str | None = None) -> list[dict]:
        sql = f"SELECT rowid AS _rowid, {', '.join(COLUMNS)} FROM messages WHERE direction = 'in' AND rowid > ?"
        args: tuple = (rowid,)
        if wa_id:
            sql += " AND wa_id = ?"
            args += (wa_id,)
        return self._query(sql + " ORDER BY rowid", args)

    def max_rowid(self) -> int:
        return self._query("SELECT COALESCE(MAX(rowid), 0) AS r FROM messages")[0]["r"]
