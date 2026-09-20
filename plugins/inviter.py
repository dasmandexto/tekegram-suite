"""Модуль: Инвайтер (аналог «Инвайтер» в TeleRaptor).

Приглашает пользователей из файла (например, выгрузки парсера) в чат/канал.

Формат входного файла — строки вида `key|...` (как у парсера):
    123456789|@user|Имя|members     -> берётся первое поле (id или @username)
Приоритет — @username: для числовых id без access_hash Telegram может
не отдать профиль (PeerIdInvalid) — такие строки логируются как ошибки.

Защита (по практике TeleRaptor и лимитам Telegram):
- dry-run по умолчанию: без --send только план;
- лимит в день на аккаунт: INVITE_DAILY_CAP из .env (по умолчанию 40);
- пауза между инвайтами: RateLimiter (MIN_DELAY_SECONDS..MAX_DELAY_SECONDS);
- FloodWaitError / PeerFloodError -> аккаунт останавливается до конца запуска;
- дедуп и возобновление: отмечаем успешные в sent_recipients (module=inviter),
  при перезапуске не повторяем — дорабатываем с того же места;
- opt-out уважается всегда.

Ошибки обрабатываются по типам: UserPrivacyRestrictedError (настройки
приватности не позволяют инвайт), UserNotMutualContactError, и т.д.

Запуск:
    python -m cli inviter @my_chat --file data/parsed_durov_2026-09-20.txt --limit 100
    python -m cli inviter @my_chat --file ... --send
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import (
    ChatAdminRequiredError,
    FloodWaitError,
    PeerFloodError,
    PeerIdInvalidError,
    UserChannelsTooMuchError,
    UserKickedError,
    UserNotMutualContactError,
    UserPrivacyRestrictedError,
)
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.functions.messages import AddChatUserRequest
from telethon.tl.types import PeerUser

from .base import PluginDeps, PluginProtocol

log = logging.getLogger(__name__)

MODULE = "inviter"


def parse_user_keys(path: Path) -> list[str]:
    """Читает файл парсера: первое поле каждой строки — id или @username."""
    if not path.exists():
        raise ValueError(f"Файл не найден: {path}")
    keys: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key = line.split("|")[0].strip()
        if key and key not in keys:
            keys.append(key)
    return keys


class InviterPlugin(PluginProtocol):
    name = MODULE
    description = "Инвайт пользователей из файла в чат/канал (лимиты, дедуп, dry-run)"

    @staticmethod
    def _norm(key: str) -> str:
        key = key.strip()
        return key[1:].lower() if key.startswith("@") else key

    def _parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(prog="tg-suite inviter", description=self.description)
        p.add_argument("target", help="чат/канал, куда инвайтить (@username или ссылка)")
        p.add_argument("--file", required=True, help="файл со списком (формат парсера)")
        p.add_argument("--limit", type=int, default=0, help="макс. приглашений за запуск (0 = все)")
        p.add_argument("--send", action="store_true", help="реально приглашать (по умолчанию dry-run)")
        return p

    async def run(self, args: list[str]) -> None:
        ns = self._parser().parse_args(args)

        if not self.deps.api_id or not self.deps.api_hash:
            raise ValueError("Инвайтеру нужны API_ID и API_HASH (my.telegram.org)")
        names = self.deps.sessions.list_session_names()
        if not names:
            raise ValueError("Нет сессий в каталоге sessions/")

        keys = parse_user_keys(Path(ns.file))
        optout = self._load_optout()
        keys = [k for k in keys if self._norm(k) not in optout]
        # дедуп + возобновление: не приглашаем тех, кого уже взяли
        keys = self.deps.storage.unseen_users(names[0], [self._norm(k) for k in keys], MODULE)
        if ns.limit > 0:
            keys = keys[: ns.limit]
        if not keys:
            log.info("Некого приглашать (пусто после фильтров/дедупа).")
            return

        cap = self.deps.sessions.settings.invite_daily_cap
        log.info("Инвайтер: %d адресатов, лимит в день на аккаунт: %d", len(keys), cap)

        if not ns.send:
            print("┌─ ПЛАН ИНВАЙТА (dry-run, ничего не отправлено) ──────────────")
            print(f"│ цель: {ns.target}")
            print(f"│ адресатов: {len(keys)} (первые: {', '.join(keys[:5])})")
            print("└──────────────────────────────────────────────────────────────")
            log.info("DRY-RUN: для реального инвайта добавьте --send.")
            return

        self.deps.storage.log_event(MODULE, "info", f"запуск: {len(keys)} в {ns.target}")
        await self._dispatch(names, ns.target, keys, cap)
        self.deps.storage.log_event(MODULE, "info", f"завершено: {len(keys)}")

    def _load_optout(self) -> set[str]:
        path = self.deps.sessions.settings.db_path.parent / "optout.txt"
        if not path.exists():
            return set()
        return {self._norm(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}

    async def _dispatch(self, names: list[str], target: str, keys: list[str], cap: int) -> None:
        tasks = []
        for i, name in enumerate(names):
            chunk = [k for idx, k in enumerate(keys) if idx % len(names) == i]
            if chunk:
                tasks.append(self._worker(name, target, chunk, cap))
        await asyncio.gather(*tasks)

    async def _worker(self, name: str, target: str, keys: list[str], cap: int) -> None:
        all_names = self.deps.sessions.list_session_names()
        proxy = self.deps.proxies.get_for(all_names.index(name))
        client = self.deps.sessions.build_client(name, self.deps.api_id, self.deps.api_hash, proxy)

        ok = restricted = failed = 0
        await client.connect()
        try:
            if self.deps.storage.count_sent_today(name, MODULE) >= cap:
                log.warning("Аккаунт %s: дневной лимит исчерпан, пропускаю.", name)
                return
            try:
                target_entity = await client.get_entity(target)
            except Exception as exc:  # noqa: BLE001
                log.error("Аккаунт %s: не вижу цель %s (%s)", name, target, exc)
                return
            is_channel = getattr(target_entity, "megagroup", False) or not hasattr(target_entity, "participants")

            for key in keys:
                if self.deps.storage.count_sent_today(name, MODULE) >= cap:
                    log.warning("Аккаунт %s: дневной лимит достигнут, стоп.", name)
                    break
                await self.deps.rate_limiter.wait(name)
                try:
                    user = await self._resolve(client, key)
                    if is_channel:
                        await client(InviteToChannelRequest(target_entity, [user]))
                    else:
                        await client(AddChatUserRequest(target_entity, user, 0))
                    self.deps.storage.mark_sent(name, self._norm(key), MODULE)
                    self.deps.storage.log_event(MODULE, "info", f"{name} -> {key}")
                    ok += 1
                except FloodWaitError as exc:
                    self.deps.rate_limiter.backoff(name, exc.seconds)
                    self.deps.storage.log_event(MODULE, "warn", f"{name}: flood-wait {exc.seconds} c")
                    break  # этот аккаунт больше не трогаем в этом запуске
                except PeerFloodError:
                    self.deps.rate_limiter.backoff(name, 3600)
                    self.deps.storage.log_event(MODULE, "warn", f"{name}: peer-flood, стоп на час")
                    break
                except UserPrivacyRestrictedError:
                    restricted += 1
                    self.deps.storage.log_event(MODULE, "warn", f"{name}: {key} — приватность не разрешает")
                except UserNotMutualContactError:
                    restricted += 1
                    self.deps.storage.log_event(MODULE, "warn", f"{name}: {key} — нет взаимного контакта")
                except UserChannelsTooMuchError:
                    restricted += 1
                    self.deps.storage.log_event(MODULE, "warn", f"{name}: {key} — слишком много чатов")
                except UserKickedError:
                    failed += 1
                    self.deps.storage.log_event(MODULE, "warn", f"{name}: {key} — кикнут из чата ранее")
                except (PeerIdInvalidError, ValueError):
                    failed += 1
                    self.deps.storage.log_event(MODULE, "warn", f"{name}: {key} — нет доступа к профилю (нужен @username)")
                except ChatAdminRequiredError:
                    log.error("Аккаунт %s: нет прав администратора в цели.", name)
                    break
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    self.deps.storage.log_event(MODULE, "warn", f"{name}: {key} {type(exc).__name__}")
        finally:
            await client.disconnect()
        log.info("Аккаунт %s: инвайтов=%d, приватность/лимиты=%d, ошибок=%d", name, ok, restricted, failed)

    @staticmethod
    async def _resolve(client: TelegramClient, key: str):
        if key.lstrip("@").isdigit():
            return await client.get_entity(PeerUser(int(key)))
        return await client.get_entity(key if key.startswith("@") else f"@{key}")
