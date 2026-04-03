from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mailboxes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    tokens_json TEXT NOT NULL,
                    last_history_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def upsert_mailbox(
        self,
        *,
        email: str,
        tokens: dict[str, Any],
        last_history_id: str | None,
    ) -> int:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM mailboxes WHERE email = ?",
                (email,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE mailboxes
                    SET tokens_json = ?, last_history_id = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE email = ?
                    """,
                    (json.dumps(tokens), last_history_id, email),
                )
                conn.commit()
                return int(existing["id"])

            cursor = conn.execute(
                """
                INSERT INTO mailboxes (email, tokens_json, last_history_id)
                VALUES (?, ?, ?)
                """,
                (email, json.dumps(tokens), last_history_id),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_mailboxes(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, email, tokens_json, last_history_id, created_at, updated_at
                FROM mailboxes
                ORDER BY id ASC
                """
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_mailbox(self, mailbox_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, email, tokens_json, last_history_id, created_at, updated_at
                FROM mailboxes
                WHERE id = ?
                """,
                (mailbox_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def update_tokens(self, mailbox_id: int, tokens: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE mailboxes
                SET tokens_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (json.dumps(tokens), mailbox_id),
            )
            conn.commit()

    def update_history_id(self, mailbox_id: int, history_id: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE mailboxes
                SET last_history_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (history_id, mailbox_id),
            )
            conn.commit()

    def delete_mailbox(self, mailbox_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM mailboxes WHERE id = ?", (mailbox_id,))
            conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["tokens"] = json.loads(data.pop("tokens_json"))
        return data
