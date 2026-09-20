"""Модуль: Парсер аудитории (аналог «Парсер аудитории» в TeleRaptor).

Два режима:
- members  — участники канала/группы через GetParticipantsRequest (батчами по 200);
- activity — «по активности»: собираем авторов сообщений из последних сообщений
  (итерируем iter_messages и берём sender_id), показывает живых людей, а не ботов.

Результат — файл data/parsed_<источник>_<дата>.txt, по строке на пользователя:
    user_id|@username|Имя|источник
Файл подходит для инвайтера (plugins/inviter.py). Важно: факт парсинга — это
НЕ согласие; в broadcast такие списки не пройдут фильтр opt-in без даты согласия.

Защита от флуда: паузы между батчами, FloodWaitError -> пауза на время сервера.

Запуск:
    python -m cli parser @durov --limit 500
    python -m cli parser @durov --mode activity --limit 1000
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import logging
import random
import re

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsRecent, PeerUser

from .base import PluginDeps, PluginProtocol

log = logging.getLogger(__name__)

MODULE = "parser"


def safe_name(name: str) -> str:
    """Имя источника -> безопасная часть имени файла."""
    return re.sub(r"[^\w.-]+", "_", name.strip("@")).strip("_") or "source"


class ParserPlugin(PluginProtocol):
    name = MODULE
    description = "Сбор участников/активности из групп и каналов"

    def _parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(prog="tg-suite parser", description=self.description)
        p.add_argument("source", help="@username или ссылка на канал/группу")
        p.add_argument("--limit", type=int, default=200, help="макс. пользователей (0 = сколько дадут)")
        p.add_argument(
            "--mode", choices=["members", "activity"], default="members",
            help="members — участники; activity — авторы последних сообщений",
        )
        p.add_argument("--output", default=None, help="путь к файлу результата (по умолчанию data/parsed_...)")
        return p

    async def run(self, args: list[str]) -> None:
        ns = self._parser().parse_args(args)

        if not self.deps.api_id or not self.deps.api_hash:
            raise ValueError("Парсеру нужны API_ID и API_HASH (my.telegram.org)")
        names = self.deps.sessions.list_session_names()
        if not names:
            raise ValueError("Нет сессий в каталоге sessions/")

        account = names[0]
        proxy = self.deps.proxies.get_for(names.index(account))
        client = self.deps.sessions.build_client(account, self.deps.api_id, self.deps.api_hash, proxy)

        await client.connect()
        try:
            entity = await client.get_entity(ns.source)
            title = getattr(entity, "title", None) or getattr(entity, "username", None) or str(ns.source)

            if ns.mode == "members":
                rows = await self._parse_members(client, account, entity, ns.limit)
            else:
                rows = await self._parse_activity(client, entity, ns.limit)
        finally:
            await client.disconnect()

        if not rows:
            log.info("Ничего не собрано (закрытая группа или пустой источник).")
            return

        out_path = self._output_path(ns.output, ns.source)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as fh:
            fh.write(f"# источник: {ns.source} ({title}) | режим: {ns.mode} | {dt.date.today()}\n")
            for user_id, username, name, src in rows:
                fh.write(f"{user_id}|{username}|{name}|{src}\n")

        self.deps.storage.log_event(MODULE, "info", f"{ns.source}: собрано {len(rows)} ({ns.mode})")
        log.info("Готово: %d пользователей -> %s", len(rows), out_path)

    def _output_path(self, output: str | None, source: str):
        if output:
            from pathlib import Path

            return Path(output)
        from pathlib import Path

        data_dir = self.deps.sessions.settings.db_path.parent
        return data_dir / f"parsed_{safe_name(source)}_{dt.date.today()}.txt"

    async def _parse_members(self, client: TelegramClient, account: str, entity, limit: int) -> list[tuple]:
        rows: list[tuple] = []
        offset = 0
        seen: set[int] = set()
        while limit <= 0 or len(rows) < limit:
            batch = 200 if limit <= 0 else min(200, limit - len(rows))
            try:
                resp = await client(
                    GetParticipantsRequest(entity, ChannelParticipantsRecent(), offset, batch, 0)
                )
            except FloodWaitError as exc:
                log.warning("Флуд-лимит: пауза %d c", exc.seconds)
                self.deps.rate_limiter.backoff(account, exc.seconds)
                await asyncio.sleep(exc.seconds + 2)
                continue

            if not resp.participants:
                break
            users_by_id = {u.id: u for u in resp.users}
            for p in resp.participants:
                if p.user_id in seen:
                    continue
                seen.add(p.user_id)
                u = users_by_id.get(p.user_id)
                if u is None or getattr(u, "bot", False):
                    continue
                username = f"@{u.username}" if getattr(u, "username", None) else ""
                name = " ".join(filter(None, [u.first_name, u.last_name])).strip()
                rows.append((p.user_id, username, name, "members"))
            offset += len(resp.participants)
            if offset >= getattr(resp, "count", offset) or len(resp.participants) < batch:
                break
            await asyncio.sleep(random.uniform(2.0, 5.0))
        return rows

    async def _parse_activity(self, client: TelegramClient, entity, limit: int) -> list[tuple]:
        sender_ids: list[int] = []
        async for msg in client.iter_messages(entity, limit=limit or 1000):
            if msg.sender_id and not sender_ids.count(msg.sender_id):
                sender_ids.append(msg.sender_id)
        rows: list[tuple] = []
        for uid in sender_ids:
            username, name = "", ""
            try:
                u = await client.get_entity(PeerUser(uid))
                username = f"@{u.username}" if getattr(u, "username", None) else ""
                name = " ".join(filter(None, [u.first_name, u.last_name])).strip()
            except Exception as exc:  # noqa: BLE001 — нет доступа к профилю, пишем id
                log.debug("не удалось получить профиль %s: %s", uid, exc)
            rows.append((uid, username, name, "activity"))
        return rows
