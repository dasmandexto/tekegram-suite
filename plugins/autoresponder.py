"""Модуль: Автоответчик (аналог «Автоответчик» в TeleRaptor).

Отвечает на входящие сообщения по правилам из файла data/autoresponder.txt:
    триггер|ответ          (триггер — подстрока, без учёта регистра)
    |ответ                 (пустой триггер = ответ на любое сообщение)
    # комментарий

Предохранители (анти-петля):
- реагирует ТОЛЬКО на входящие (свои исходящие игнорируются by Telethon);
- никогда не отвечает ботам и сам себе — защиты от бото-петель;
- кулдаун на диалог: одному чату не чаще --cooldown секунд (по умолчанию 3600),
  кулдаун персистентный (хранится в дедуп-таблице, переживает перезапуск);
- по умолчанию только личные сообщения; --chat @группа добавляет диалог в группе;
- в ответах работает спинтакс: |Привет! {Рады видеть|Здравствуйте}|

Запуск:
    python -m cli autoresponder --duration 3600     # час, потом стоп
    python -m cli autoresponder --duration 0        # пока не остановите (Ctrl+C)
    python -m cli autoresponder --chat @my_chat --cooldown 60
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path

from telethon import events

from core import spintax
from .base import PluginDeps, PluginProtocol

log = logging.getLogger(__name__)

MODULE = "autoresponder"


def parse_rules(path: Path) -> list[tuple[str, str]]:
    """Читает правила: строки `триггер|ответ`, пустой триггер = на всё."""
    if not path.exists():
        raise ValueError(
            f"Файл правил не найден: {path}\nФормат: триггер|ответ (|ответ — на любое сообщение)"
        )
    rules: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "|" not in line:
            continue
        trigger, reply = line.split("|", 1)
        trigger, reply = trigger.strip(), reply.strip()
        if reply:
            rules.append((trigger, reply))
    if not rules:
        raise ValueError(f"В файле правил нет ни одного правила с ответом: {path}")
    return rules


def rule_matches(trigger: str, text: str) -> bool:
    """Пустой триггер матчит всё, иначе — подстрока без учёта регистра."""
    if not trigger:
        return True
    return trigger.lower() in text.lower()


class AutoresponderPlugin(PluginProtocol):
    name = MODULE
    description = "Автоответы на входящие по правилам (кулдаун, анти-петля)"

    def _parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(prog="tg-suite autoresponder", description=self.description)
        p.add_argument("--rules", default=None, help="файл правил (по умолчанию data/autoresponder.txt)")
        p.add_argument("--chat", action="append", default=[], metavar="@ЧАТ",
                       help="отвечать и в этом чате/группе (можно несколько раз)")
        p.add_argument("--cooldown", type=int, default=3600, help="сек между ответами одному диалогу")
        p.add_argument("--duration", type=int, default=0, help="сек работы (0 = до Ctrl+C)")
        return p

    async def run(self, args: list[str]) -> None:
        ns = self._parser().parse_args(args)

        if not self.deps.api_id or not self.deps.api_hash:
            raise ValueError("Автоответчику нужны API_ID и API_HASH (my.telegram.org)")
        names = self.deps.sessions.list_session_names()
        if not names:
            raise ValueError("Нет сессий в каталоге sessions/")

        rules_path = (
            Path(ns.rules) if ns.rules
            else self.deps.sessions.settings.db_path.parent / "autoresponder.txt"
        )
        rules = parse_rules(rules_path)
        log.info("Правил загружено: %d, кулдаун: %d c, аккаунтов: %d", len(rules), ns.cooldown, len(names))

        allowed_chats: set[int] | None = None
        if ns.chat:
            allowed_chats = set()  # заполним id после первого подключения (по одному клиенту)
        await asyncio.gather(*(
            self._worker(name, rules, ns.cooldown, ns.chat, ns.duration)
            for name in names
        ))
        self.deps.storage.log_event(MODULE, "info", f"остановлен (аккаунтов: {len(names)})")

    async def _worker(self, name: str, rules: list[tuple[str, str]], cooldown: int,
                      chat_filters: list[str], duration: int) -> None:
        all_names = self.deps.sessions.list_session_names()
        proxy = self.deps.proxies.get_for(all_names.index(name))
        client = self.deps.sessions.build_client(name, self.deps.api_id, self.deps.api_hash, proxy)

        await client.connect()
        try:
            me = await client.get_me()
            allowed_ids: set[int] | None = None
            if chat_filters:
                allowed_ids = set()
                for ref in chat_filters:
                    try:
                        ent = await client.get_entity(ref)
                        allowed_ids.add(ent.id)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("Аккаунт %s: чат %s недоступен (%s)", name, ref, exc)

            async def handler(event) -> None:
                try:
                    await self._handle(event, name, me.id, rules, cooldown, allowed_ids)
                except Exception as exc:  # noqa: BLE001 — ошибка одного сообщения не роняет воркера
                    log.debug("autoresponder/%s: %s", name, exc)

            client.add_event_handler(handler, events.NewMessage(incoming=True))
            log.info("Аккаунт %s: автоответчик активен%s", name,
                     f" (чаты: {chat_filters})" if allowed_ids is not None else " (только ЛС)")

            stop_at = time.monotonic() + duration if duration > 0 else None
            while stop_at is None or time.monotonic() < stop_at:
                await asyncio.sleep(1)
        finally:
            await client.disconnect()
            log.info("Аккаунт %s: автоответчик остановлен", name)

    async def _handle(self, event, name: str, own_id: int, rules, cooldown: int,
                      allowed_ids: set[int] | None) -> None:
        msg = event.message
        text = (msg.message or "").strip()
        if not text or text.startswith("/"):        # сервисные/командные — мимо
            return
        if allowed_ids is not None:
            if msg.chat_id not in allowed_ids:      # per-chat enable
                return
        elif not msg.is_private:                    # по умолчанию только ЛС
            return

        sender = await event.get_sender()
        if sender is None or getattr(sender, "bot", False) or sender.id == own_id:
            return                                  # боты и своё эхо — анти-петля

        key = str(msg.chat_id)
        since = self.deps.storage.seconds_since(name, MODULE, key)
        if since is not None and since < cooldown:  # кулдаун на диалог
            return

        for trigger, reply in rules:
            if rule_matches(trigger, text):
                await msg.reply(spintax.generate(reply))
                self.deps.storage.mark_sent(name, key, MODULE)
                self.deps.storage.log_event(MODULE, "info", f"{name} -> диалог {key}")
                log.info("Аккаунт %s: ответил в диалог %s", name, key)
                return
