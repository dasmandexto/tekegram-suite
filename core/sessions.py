"""Пул Telethon-сессий: аккаунты = файлы *.session в SESSIONS_DIR.

Один файл сессии = один аккаунт (как в TeleRaptor). Файлы создаются
Telethon'ом при первом входе; готовые сессии можно также конвертировать
из tdata/telethon-сессий других софтов.
"""
from __future__ import annotations

import logging
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import Settings
from .proxies import Proxy

log = logging.getLogger(__name__)


class SessionPool:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._dir = settings.sessions_dir

    def list_session_names(self) -> list[str]:
        """Имена аккаунтов: файлы *.session без расширения, по возрастанию."""
        if not self._dir.exists():
            return []
        names = sorted(p.stem for p in self._dir.glob("*.session") if p.is_file())
        return names

    def build_client(
        self,
        name: str,
        api_id: int,
        api_hash: str,
        proxy: Proxy | None = None,
        string_session: str | None = None,
    ) -> TelegramClient:
        """Создаёт клиента для аккаунта `name`.

        string_session — необязательно: если передать строковую сессию
        (например, после конвертации tdata -> session), клиент будет работать
        без сохранения файла.
        """
        if string_session:
            session = StringSession(string_session)
        else:
            # Telethon сам добавит расширение .session к пути
            session = str(self._dir / name)

        return TelegramClient(
            session,
            api_id,
            api_hash,
            proxy=proxy.as_telethon() if proxy else None,
            connection_retries=3,
            request_retries=3,
        )

    @property
    def count(self) -> int:
        return len(self.list_session_names())
