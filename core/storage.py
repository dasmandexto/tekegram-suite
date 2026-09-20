"""SQLite-хранилище: статусы аккаунтов, дедуп получателей, журнал событий.

Реализует ключевую защиту из TeleRaptor — режим «без пересечений»:
один и тот же пользователь не получает сообщение от одного аккаунта дважды.

Внимание: для старта используется синхронный sqlite3 с блокировкой —
этого достаточно для первых модулей. Под нагрузкой (рассылки на десятки
тысяч получателей) перейти на aiosqlite или Redis.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Iterable


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    # ---------- schema ----------
    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS account_status (
                    account      TEXT NOT NULL,
                    checked_at   TEXT NOT NULL DEFAULT (datetime('now')),
                    status       TEXT NOT NULL,
                    detail       TEXT,
                    PRIMARY KEY (account)
                );

                -- дедуп: (аккаунт, модуль, получатель) — режим «без пересечений»
                CREATE TABLE IF NOT EXISTS sent_recipients (
                    account    TEXT NOT NULL,
                    module     TEXT NOT NULL DEFAULT 'spam',
                    user_key   TEXT NOT NULL,   -- @username / user_id / телефон
                    sent_at    TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (account, module, user_key)
                );

                CREATE TABLE IF NOT EXISTS events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts         TEXT NOT NULL DEFAULT (datetime('now')),
                    module     TEXT,
                    level      TEXT,
                    message    TEXT
                );
                """
            )

    # ---------- статусы аккаунтов ----------
    def set_account_status(self, account: str, status: str, detail: str | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO account_status (account, checked_at, status, detail) "
                "VALUES (?, datetime('now'), ?, ?)",
                (account, status, detail),
            )

    def account_status(self, account: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM account_status WHERE account = ?", (account,)
            ).fetchone()
        return dict(row) if row else None

    def all_account_statuses(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM account_status").fetchall()
        return [dict(r) for r in rows]

    # ---------- дедуп получателей ----------
    def is_sent(self, account: str, user_key: str, module: str = "spam") -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM sent_recipients WHERE account = ? AND user_key = ? AND module = ?",
                (account, user_key, module),
            ).fetchone()
        return row is not None

    def mark_sent(self, account: str, user_key: str, module: str = "spam") -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO sent_recipients (account, user_key, module) VALUES (?, ?, ?)",
                (account, user_key, module),
            )

    def unseen_users(self, account: str, user_keys: Iterable[str], module: str = "spam") -> list[str]:
        """Фильтр «без пересечений»: возвращает только тех, кому аккаунт ещё не писал."""
        keys = list(dict.fromkeys(user_keys))
        if not keys:
            return []
        with self._lock:
            placeholders = ",".join("?" * len(keys))
            rows = self._conn.execute(
                f"SELECT user_key FROM sent_recipients WHERE account = ? AND module = ? "
                f"AND user_key IN ({placeholders})",
                (account, module, *keys),
            ).fetchall()
        seen = {r["user_key"] for r in rows}
        return [k for k in keys if k not in seen]

    # ---------- журнал ----------
    def log_event(self, module: str, level: str, message: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO events (module, level, message) VALUES (?, ?, ?)",
                (module, level, message),
            )

    def count_sent_today(self, account: str, module: str = "inviter") -> int:
        """Сколько действий module аккаунт совершил сегодня (дневные лимиты)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM sent_recipients "
                "WHERE account = ? AND module = ? AND date(sent_at) = date('now')",
                (account, module),
            ).fetchone()
        return row["c"]

    def recent_events(self, limit: int = 50) -> list[dict]:
        """Последние события журнала (для веб-интерфейса), новые сверху."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, module, level, message FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
