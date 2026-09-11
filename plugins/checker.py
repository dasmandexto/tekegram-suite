"""Модуль: Чекер аккаунтов (аналог «Чекер аккаунтов» в TeleRaptor).

Самый безопасный модуль для старта: не отправляет сообщения, ничего не
добавляет — только проверяет живы ли аккаунты и нет ли спамблока/бана.

Использует Telethon:
- client.connect()        — установка соединения через прокси
- client.get_me()         — получение профиля; ошибка => аккаунт мёртв/забанен
- FloodWaitError          — аккаунт временно ограничен (спамблок)
- (AuthKeyError и т.п.)   — сессия недействительна

При обнаружении флуд-лимита аккаунт «замораживается» на время
backoff в rate limiter.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from typing import Awaitable, Callable

from telethon import TelegramClient
from telethon.errors import (
    AuthKeyUnregisteredError,
    FloodWaitError,
    PhoneNumberBannedError,
)

from core import AccountError, FloodLimitError
from .base import PluginDeps, PluginProtocol

log = logging.getLogger(__name__)


class CheckerPlugin(PluginProtocol):
    name = "checker"
    description = "Проверка живости аккаунтов: статус, спамблок, бан"

    def __init__(self, deps: PluginDeps):
        super().__init__(deps)
        if not deps.api_id or not deps.api_hash:
            raise ValueError("Чекеру нужны API_ID и API_HASH (my.telegram.org)")

    async def run(self, args: list[str]) -> None:
        names = self.deps.sessions.list_session_names()
        if not names:
            raise ValueError(
                f"В каталоге сессий '{self.deps.sessions.settings.sessions_dir}' "
                "нет файлов *.session. Добавьте сессии или конвертируйте tdata."
            )

        only = None
        if args and args[0] in names:
            only = args[0]

        targets = [only] if only else names
        log.info("Чекер: проверяю %d аккаунтов из %d", len(targets), len(names))

        await self.check(targets, self._on_result)
        self.deps.storage.log_event("checker", "info", f"Проверено аккаунтов: {len(targets)}")

    async def _on_result(self, name: str, status: str, detail: str | None) -> None:
        self.deps.storage.set_account_status(name, status, detail)
        log.info("Аккаунт %-20s -> %s%s", name, status, f" ({detail})" if detail else "")

    async def check(
        self,
        names: list[str],
        on_result: Callable[[str, str, str | None], Awaitable[None]],
    ) -> None:
        sem = asyncio.Semaphore(self.deps.sessions.settings.max_concurrency)

        async def one(name: str) -> None:
            async with sem:
                proxy = self.deps.proxies.get_for(self.deps.sessions.list_session_names().index(name))
                client = self.deps.sessions.build_client(name, self.deps.api_id, self.deps.api_hash, proxy)
                status, detail = await self._check_one(client, name)
                await client.disconnect()
                await on_result(name, status, detail)

        await asyncio.gather(*(one(n) for n in names))

    async def _check_one(self, client: TelegramClient, name: str) -> tuple[str, str | None]:
        try:
            await client.connect()
        except FloodLimitError:
            raise
        except Exception as exc:  # noqa: BLE001 — прокси/сеть
            return "error", f"сеть: {exc.__class__.__name__}: {exc}"
        if not client.is_connected():
            return "error", "не удалось подключиться"

        try:
            me = await client.get_me()
        except PhoneNumberBannedError:
            return "banned", "номер забанен"
        except FloodWaitError as exc:
            wait = exc.seconds
            self.deps.rate_limiter.backoff(name, wait)
            return "flood", f"флуд-лимит, пауза {wait} c"
        except AuthKeyUnregisteredError:
            return "dead", "сессия невалидна (auth key уничтожен)"
        except AccountError as exc:
            return "dead", str(exc)
        except Exception as exc:  # noqa: BLE001
            return "error", f"{exc.__class__.__name__}: {exc}"

        if me is None:
            return "dead", "get_me вернул None"
        return "alive", (me.username or me.id or "ok")
