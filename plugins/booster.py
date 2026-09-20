"""Модуль: Накрутка просмотров/реакций — ТОЛЬКО на свой контент (каркас).

Назначение: поднять просмотры/реакции на СВОЁ сообщение в СВОЁМ канале,
используя РЕАЛЬНЫЕ аккаунты из вашего пула (каждый «посмотрит» пост).
Это не эмуляция ботов-вьюверов: аккаунты настоящие, лимитированные.

КАК РАБОТАЕТ: parse ссылки https://t.me/<канал>/<id> -> каждому аккаунту
выполняется channels.ReadHistory (просмотр сообщения); опционально — реакция
(SendReactionRequest, только если пост в канале её позволяет).

НЕ РЕАЛИЗОВАНО (намеренно): фейковые аккаунты, обход ограничений,
глобальные бото-сети. Кулдаун на аккаунт — RateLimiter.

Запуск:
    python -m cli booster https://t.me/my_channel/123 --limit 50
    python -m cli booster https://t.me/my_channel/123 --limit 50 --send --reaction 👍
"""
from __future__ import annotations

import argparse
import logging
import re

from telethon import functions, types

from .base import PluginDeps, PluginProtocol

log = logging.getLogger(__name__)

MODULE = "booster"

RUN_CAP = 200  # максимум аккаунтов-просмотров за запуск

_LINK_RE = re.compile(r"t\.me/(?:s/)?([^/\s]+)/(\d+)")


def parse_post_link(link: str) -> tuple[str, int]:
    """'https://t.me/channel/123' -> ('channel', 123)."""
    m = _LINK_RE.search(link.strip())
    if not m:
        raise ValueError(f"Не похоже на ссылку на пост (t.me/<канал>/<id>): {link!r}")
    return m.group(1), int(m.group(2))


class BoosterPlugin(PluginProtocol):
    name = MODULE
    description = "Просмотры/реакции на СВОЙ пост пулом аккаунтов (лимитировано)"

    def _parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(prog="tg-suite booster", description=self.description)
        p.add_argument("post", help="ссылка на пост: https://t.me/<канал>/<id>")
        p.add_argument("--limit", type=int, default=0, help="макс. аккаунтов за запуск (макс. 200)")
        p.add_argument("--reaction", default=None, help="эмодзи-реакция (например 👍), опционально")
        p.add_argument("--send", action="store_true", help="реально выполнить (по умолчанию dry-run)")
        return p

    async def run(self, args: list[str]) -> None:
        ns = self._parser().parse_args(args)

        channel_ref, msg_id = parse_post_link(ns.post)
        sessions = self.deps.sessions.list_session_names()
        if not sessions:
            raise ValueError("Нет сессий в каталоге sessions/")
        watchers = sessions[: min(ns.limit, RUN_CAP) or RUN_CAP]

        if not ns.send:
            print("┌─ ПЛАН НАКРУТКИ (dry-run) ───────────────────────────────────")
            print(f"│ пост: t.me/{channel_ref}/{msg_id}")
            print(f"│ аккаунтов-просмотров: {len(watchers)} (лимит запуска: {RUN_CAP})")
            print(f"│ реакция: {ns.reaction or 'нет'}")
            print("└──────────────────────────────────────────────────────────────")
            log.info("DRY-RUN: для выполнения добавьте --send.")
            return

        if not self.deps.api_id or not self.deps.api_hash:
            raise ValueError("Нужны API_ID и API_HASH (my.telegram.org)")

        done = failed = 0
        for account in watchers:
            await self.deps.rate_limiter.wait(account)
            client = self.deps.sessions.build_client(
                account, self.deps.api_id, self.deps.api_hash,
                self.deps.proxies.get_for(sessions.index(account)),
            )
            try:
                await client.connect()
                if not client.is_connected():
                    raise ConnectionError("нет соединения")
                entity = await client.get_entity(channel_ref)
                await client(functions.channels.ReadHistoryRequest(entity, msg_id))
                if ns.reaction:
                    reaction = types.ReactionEmoji(emoticon=ns.reaction)
                    await client(functions.messages.SendReactionRequest(
                        peer=entity, msg_id=msg_id, reaction=[reaction],
                    ))
                self.deps.storage.log_event(MODULE, "info", f"{account}: просмотр t.me/{channel_ref}/{msg_id}")
                done += 1
            except Exception as exc:  # noqa: BLE001 — один аккаунт не роняет запуск
                self.deps.storage.log_event(MODULE, "warn", f"{account}: {type(exc).__name__}")
                log.debug("%s: %s", account, exc)
                failed += 1
            finally:
                await client.disconnect()

        self.deps.storage.log_event(MODULE, "info", f"просмотров {done}, ошибок {failed}")
        log.info("Готово: просмотров=%d, ошибок=%d", done, failed)
