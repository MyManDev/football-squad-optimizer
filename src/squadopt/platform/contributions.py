"""Moderated community observations. Never a prediction or solver input."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any


class ContributionsLimitedError(Exception):
    """The bounded community inbox cannot accept another observation yet."""


class ContributionStore:
    """A separate SQLite file; atomic submissions and host-only moderation.

    No raw visitor addresses are persisted. A daily keyed digest enforces a small
    submission quota; a global quota also bounds abuse from distributed clients.
    Opening the store does not read any advice queue or model cache.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=3)
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY, season TEXT NOT NULL, player_id INTEGER NOT NULL,
                player_name TEXT NOT NULL, author TEXT NOT NULL, body TEXT NOT NULL,
                source TEXT NOT NULL, created REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', moderated REAL
            );
            CREATE INDEX IF NOT EXISTS comments_public ON comments(status, season, player_id, id);
            CREATE TABLE IF NOT EXISTS attempts (client TEXT NOT NULL, created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS attempts_time ON attempts(created);
        """)
        connection.execute(
            "INSERT OR IGNORE INTO settings VALUES ('salt', ?)", (secrets.token_hex(32),)
        )
        connection.commit()
        return connection

    def submit(
        self,
        *,
        season: str,
        player_id: int,
        player_name: str,
        author: str,
        body: str,
        source: str,
        client: str,
        now: float | None = None,
    ) -> int:
        stamp = time.time() if now is None else now
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            salt = db.execute("SELECT value FROM settings WHERE key='salt'").fetchone()[0]
            digest = hmac.new(
                salt.encode(), f"{int(stamp // 86400)}:{client}".encode(), hashlib.sha256
            ).hexdigest()
            db.execute("DELETE FROM attempts WHERE created < ?", (stamp - 86400,))
            recent = db.execute(
                "SELECT count(*), sum(client = ?) FROM attempts WHERE created > ?",
                (digest, stamp - 3600),
            ).fetchone()
            capacity = db.execute("SELECT count(*) FROM comments").fetchone()[0]
            if recent[0] >= 50 or (recent[1] or 0) >= 3 or capacity >= 10000:
                raise ContributionsLimitedError
            duplicate = db.execute(
                "SELECT id FROM comments WHERE season=? AND player_id=? AND author=? "
                "AND body=? AND source=? AND created>? AND status = 'pending'",
                (season, player_id, author, body, source, stamp - 86400),
            ).fetchone()
            if duplicate:
                return int(duplicate[0])
            db.execute("INSERT INTO attempts VALUES (?, ?)", (digest, stamp))
            cursor = db.execute(
                "INSERT INTO comments (season,player_id,player_name,author,body,source,created) "
                "VALUES (?,?,?,?,?,?,?)",
                (season, player_id, player_name, author, body, source, stamp),
            )
            assert cursor.lastrowid is not None
            return cursor.lastrowid

    def public(self, season: str, player_id: int, before: int = 2**63 - 1) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,season,player_id,player_name,author,body,source,created "
                    "FROM comments "
                    "WHERE status='approved' AND season=? AND player_id=? AND id<? "
                    "ORDER BY id DESC LIMIT 50",
                    (season, player_id, before),
                )
            ]

    def pending(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM comments WHERE status='pending' ORDER BY id LIMIT 100"
                )
            ]

    def moderate(self, comment_id: int, status: str) -> None:
        if status not in ("approved", "rejected"):
            raise ValueError("Choose approved or rejected")
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "UPDATE comments SET status=?, moderated=? WHERE id=?",
                (status, time.time(), comment_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Unknown comment")
