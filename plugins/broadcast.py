"""Модуль: broadcast — рассылка ТОЛЬКО по подписчикам (opt-in).

Принципиально важно
-------------------
Это НЕ «спамер» и НЕ модуль несанкционированных рассылок. Модуль отправляет
сообщения только адресатам, которые явно дали согласие (opt-in): каждая строка
файла подписчиков обязательно содержит дату согласия и источник, где согласие
получено. Сырые списки участников групп/каналов модуль принимать отказывается —
строки без метки согласия отбрасываются, и это логируется.

Безопасные режимы по умолчанию
------------------------------
1. dry-run: по умолчанию модуль только показывает план рассылки и НИЧЕГО
   не отправляет. Реальная отправка — только с флагом --send.
2. opt-out: адресаты из optout.txt не получают сообщений никогда.
   Добавить в opt-out:  python -m cli broadcast --unsubscribe @user
3. лимиты: задержки из .env (MIN_DELAY_SECONDS / MAX_DELAY_SECONDS) через
   RateLimiter; FloodWaitError → аккаунт «замораживается» на время от Telegram.

Формат data/subscribers.txt (рядом с БД, каталог data/):
    @username|2026-01-01T10:00:00|telegram
    123456789|2026-01-02|site
    # строки без "|" или без даты считаются НЕ валидными и отбрасываются

Примеры запуска:
    python -m cli broadcast "Привет, {username}!"            # dry-run (план)
    python -m cli broadcast --send "Привет, {username}!"     # реальная отправка
    python -m cli broadcast --recipient @alice "Спасибо за подписку!"
    python -m cli broadcast --unsubscribe @alice             # в opt-out
    python -m cli broadcast --send --limit 50 "Текст"        # не больше 50 адресатов
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PeerIdInvalidError,
    UsernameNotOccupiedError,
)

from core import spintax
from .base import PluginDeps, PluginProtocol

log = logging.getLogger(__name__)

MODULE = "broadcast"


class BroadcastPlugin(PluginProtocol):
    name = MODULE
    description = "Рассылка подписчикам (только opt-in, dry-run по умолчанию, opt-out)"

    # ---------------------------------------------------------------- helpers
    def _data_dir(self) -> Path:
        return self.deps.sessions.settings.db_path.parent

    @staticmethod
    def _norm(key: str) -> str:
        """Нормализация адресата: @x и X считаются одним ключом."""
        key = key.strip()
        if key.startswith("@"):
            return key[1:].lower()
        return key

    def _valid_consent(self, text: str) -> bool:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                datetime.strptime(text.strip(), fmt)
                return True
            except ValueError:
                continue
        return False

    # ---------------------------------------------------------------- данные
    def _load_subscribers(self) -> list[tuple[str, str, str]]:
        """Загружает opt-in подписчиков. Строка без даты согласия = отказ."""
        path = self._data_dir() / "subscribers.txt"
        if not path.exists():
            raise ValueError(
                f"Файл подписчиков не найден: {path}\n"
                "Формат: key|YYYY-MM-DD|source (key = @username или user_id)"
            )
        out: list[tuple[str, str, str]] = []
        rejected = 0
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) < 2:
                rejected += 1
                continue
            key, consent = parts[0].strip(), parts[1].strip()
            if not key or not self._valid_consent(consent):
                rejected += 1
                continue
            source = parts[2].strip() if len(parts) > 2 else "unknown"
            out.append((self._norm(key), consent, source))
        if rejected:
            log.warning("Отклонено невалидных строк (нет согласия): %d", rejected)
        if not out:
            raise ValueError("Нет ни одного подписчика с меткой согласия (key|YYYY-MM-DD|source)")
        return out

    def _load_optout(self) -> set[str]:
        path = self._data_dir() / "optout.txt"
        if not path.exists():
            return set()
        return {
            self._norm(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }

    def _add_optout(self, key: str) -> Path:
        path = self._data_dir() / "optout.txt"
        key = self._norm(key)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{key}|{datetime.now().isoformat(timespec='seconds')}\n")
        self.deps.storage.log_event(MODULE, "info", f"opt-out: {key}")
        log.info("Добавлен в opt-out: %s (%s)", key, path)
        return path

    # ---------------------------------------------------------------- CLI
    def _parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(prog="tg-suite broadcast", description=self.description)
        p.add_argument("message", nargs="?", help="текст сообщения ({username} подставляется)")
        p.add_argument("--send", action="store_true", help="реально отправить (по умолчанию dry-run)")
        p.add_argument("--recipient", metavar="KEY", help="отправить только одному подписчику")
        p.add_argument("--limit", type=int, default=0, help="макс. адресатов за запуск (0 = все)")
        p.add_argument("--unsubscribe", metavar="KEY", help="добавить адресата в opt-out и выйти")
        return p

    async def run(self, args: list[str]) -> None:
        parsed = self._parser().parse_args(args)

        if parsed.unsubscribe:
            self._add_optout(parsed.unsubscribe)
            return

        if not parsed.message:
            self._parser().error("укажите текст сообщения")

        # спинтакс: проверяем корректность ДО любых действий
        combos = None
        if spintax.has_spintax(parsed.message):
            try:
                combos = spintax.count_combinations(parsed.message)
            except spintax.SpintaxError as exc:
                raise ValueError(f"Ошибка спинтакса: {exc}") from exc
            log.info("Спинтакс: %d комбинаций", combos)

        subscribers = self._load_subscribers()
        optout = self._load_optout()

        # фильтр по --recipient: только если адресат есть среди opt-in подписчиков
        if parsed.recipient:
            wanted = self._norm(parsed.recipient)
            matched = [s for s in subscribers if s[0] == wanted]
            if not matched:
                raise ValueError(
                    f"'{parsed.recipient}' нет среди подписчиков с согласием; "
                    "отправка вне opt-in списка запрещена"
                )
            subscribers = matched

        # фильтр opt-out
        before = len(subscribers)
        subscribers = [s for s in subscribers if s[0] not in optout]
        dropped_optout = before - len(subscribers)

        if parsed.limit > 0:
            subscribers = subscribers[: parsed.limit]

        if not subscribers:
            log.info("Некому отправлять (после opt-out фильтра).")
            return

        if not parsed.send:
            self._print_plan(subscribers, dropped_optout, parsed.message, combos)
            log.info("DRY-RUN: отправка не выполнялась. Для реальной отправки добавьте --send.")
            return

        # реальная отправка требует API-креды и сессии
        if not self.deps.api_id or not self.deps.api_hash:
            raise ValueError("Для отправки нужны API_ID и API_HASH (my.telegram.org)")
        names = self.deps.sessions.list_session_names()
        if not names:
            raise ValueError(
                f"Нет сессий в '{self.deps.sessions.settings.sessions_dir}'. "
                "Добавьте *.session (по одному файлу на аккаунт)."
            )

        self.deps.storage.log_event(MODULE, "info", f"запуск: адресатов={len(subscribers)}")
        await self._dispatch(names, subscribers, parsed.message)
        self.deps.storage.log_event(MODULE, "info", f"завершено: адресатов={len(subscribers)}")

    # ---------------------------------------------------------------- dry-run
    def _print_plan(
        self,
        subscribers: list[tuple[str, str, str]],
        dropped: int,
        message: str,
        combos: int | None = None,
    ) -> None:
        print("┌─ ПЛАН РАССЫЛКИ (dry-run, ничего не отправлено) ─────────────")
        print(f"│ получателей после opt-in: {len(subscribers)}  (в opt-out: {dropped})")
        if combos is not None:
            print(f"│ спинтакс: {combos} комбинаций (каждому — случайный вариант)")
        print(f"│ текст: {message[:60]!r}")
        for key, consent, source in subscribers[:10]:
            print(f"│   → {key}  (согласие {consent}, {source})")
        if len(subscribers) > 10:
            print(f"│   … и ещё {len(subscribers) - 10}")
        print("└──────────────────────────────────────────────────────────────")

    # ---------------------------------------------------------------- отправка
    async def _dispatch(self, names: list[str], subscribers: list[tuple[str, str, str]], message: str) -> None:
        """Распределяет адресатов между аккаунтами (round-robin) и шлёт параллельно."""
        tasks = []
        for i, name in enumerate(names):
            chunk = [s for idx, s in enumerate(subscribers) if idx % len(names) == i]
            if chunk:
                tasks.append(self._worker(name, chunk, message))
        await asyncio.gather(*tasks)

    async def _worker(self, name: str, chunk: list[tuple[str, str, str]], message: str) -> None:
        names = self.deps.sessions.list_session_names()
        proxy = self.deps.proxies.get_for(names.index(name))
        client = self.deps.sessions.build_client(name, self.deps.api_id, self.deps.api_hash, proxy)

        await client.connect()
        sent = failed = skipped = 0
        try:
            for key, consent, source in chunk:
                if self.deps.storage.is_sent(name, key, MODULE):
                    skipped += 1
                    continue
                await self.deps.rate_limiter.wait(name)
                try:
                    entity = await client.get_entity(key)
                    # спинтакс: каждый получатель получает случайный вариант
                    text = spintax.generate(message).replace("{username}", key)
                    await client.send_message(entity, text)
                    self.deps.storage.mark_sent(name, key, MODULE)
                    self.deps.storage.log_event(MODULE, "info", f"{name} -> {key}")
                    sent += 1
                except FloodWaitError as exc:
                    self.deps.rate_limiter.backoff(name, exc.seconds)
                    self.deps.storage.log_event(MODULE, "warn", f"{name}: flood-wait {exc.seconds} c")
                    failed += 1
                except (PeerIdInvalidError, UsernameNotOccupiedError):
                    self.deps.storage.log_event(MODULE, "warn", f"{name}: {key} недоступен")
                    failed += 1
                except Exception as exc:  # noqa: BLE001 — сеть/протокол
                    self.deps.storage.log_event(MODULE, "warn", f"{name}: {key} {type(exc).__name__}")
                    failed += 1
        finally:
            await client.disconnect()
        log.info(
            "Аккаунт %s: отправлено=%d, ошибок=%d, пропущено(дубль)=%d",
            name, sent, failed, skipped,
        )
