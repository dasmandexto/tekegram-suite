"""Модуль: Заполнение профилей (аналог «Заполнение профилей» в TeleRaptor).

Массово обновляет имя/фамилию/био/юзернейм и (опционально) аватар
у аккаунтов из данных в data/profiles.txt:

    account|first_name|last_name|bio|username
    acc1|Иван|Иванов|Менеджер|ivan_m
    # пустые поля пропускаются; строка без account отбрасывается

Аватар: положите файл avatars/<account>.jpg — подставится при обновлении.

Защита: dry-run по умолчанию (--send для реального применения); между
аккаунтами — RateLimiter; FloodWaitError -> аккаунт пропускается до конца запуска.
Лимит смены юзернейма в Telegram жёсткий (~1/час) — ошибка логируется и не падает.

Запуск:
    python -m cli profiler                # dry-run: что будет сделано
    python -m cli profiler --send         # применить
    python -m cli profiler --send --avatar-dir avatars
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from telethon import functions
from telethon.errors import FloodWaitError, UsernameInvalidError, UsernameOccupiedError

from .base import PluginDeps, PluginProtocol

log = logging.getLogger(__name__)

MODULE = "profiler"


def parse_profiles(path: Path) -> list[dict]:
    """Читает строки `account|first|last|bio|username` -> список профилей."""
    if not path.exists():
        raise ValueError(f"Файл профилей не найден: {path}")
    out: list[dict] = []
    bad = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if not parts[0].strip():
            bad += 1
            continue
        row = {
            "account": parts[0].strip(),
            "first_name": parts[1].strip() if len(parts) > 1 else "",
            "last_name": parts[2].strip() if len(parts) > 2 else "",
            "bio": parts[3].strip() if len(parts) > 3 else "",
            "username": parts[4].strip() if len(parts) > 4 else "",
        }
        out.append(row)
    if bad:
        log.warning("Отброшено строк без account: %d", bad)
    if not out:
        raise ValueError("Нет ни одного профиля в файле")
    return out


class ProfilerPlugin(PluginProtocol):
    name = MODULE
    description = "Массовое обновление профилей: имя, био, юзернейм, аватар"

    def _parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(prog="tg-suite profiler", description=self.description)
        p.add_argument("--file", default=None, help="файл профилей (по умолчанию data/profiles.txt)")
        p.add_argument("--avatar-dir", default="avatars", help="каталог с аватарами avatars/<account>.jpg")
        p.add_argument("--send", action="store_true", help="реально применить (по умолчанию dry-run)")
        return p

    async def run(self, args: list[str]) -> None:
        ns = self._parser().parse_args(args)

        profiles_path = (
            Path(ns.file) if ns.file
            else self.deps.sessions.settings.db_path.parent / "profiles.txt"
        )
        profiles = parse_profiles(profiles_path)
        sessions = self.deps.sessions.list_session_names()
        if not sessions:
            raise ValueError("Нет сессий в каталоге sessions/")

        known = {r["account"] for r in profiles}
        for s in sessions:
            if s not in known:
                log.debug("Аккаунт %s: нет строки в profiles.txt — пропущен", s)

        if not ns.send:
            print("┌─ ПЛАН ЗАПОЛНЕНИЯ ПРОФИЛЕЙ (dry-run) ────────────────────────")
            for row in profiles:
                if row["account"] not in sessions:
                    print(f"│ {row['account']}: НЕТ СЕССИИ — пропущен")
                    continue
                print(
                    f"│ {row['account']}: имя={row['first_name'] or '—'} "
                    f"фамилия={row['last_name'] or '—'} био={row['bio'][:20] or '—'} "
                    f"юзернейм={row['username'] or '—'}"
                )
            print("└──────────────────────────────────────────────────────────────")
            log.info("DRY-RUN: для применения добавьте --send.")
            return

        if not self.deps.api_id or not self.deps.api_hash:
            raise ValueError("Нужны API_ID и API_HASH (my.telegram.org)")

        avatar_dir = Path(ns.avatar_dir)
        updated = failed = 0
        for row in profiles:
            if row["account"] not in sessions:
                continue
            await self.deps.rate_limiter.wait(row["account"])
            client = self.deps.sessions.build_client(
                row["account"], self.deps.api_id, self.deps.api_hash,
                self.deps.proxies.get_for(sessions.index(row["account"])),
            )
            try:
                await client.connect()
                if not client.is_connected():
                    raise ConnectionError("не удалось подключиться")
                if row["first_name"] or row["last_name"] or row["bio"]:
                    await client(functions.account.UpdateProfileRequest(
                        first_name=row["first_name"] or None,
                        last_name=row["last_name"] or None,
                        about=row["bio"] or None,
                    ))
                if row["username"]:
                    try:
                        await client(functions.account.UpdateUsernameRequest(row["username"]))
                    except UsernameOccupiedError:
                        log.warning("%s: юзернейм занят", row["account"])
                    except UsernameInvalidError:
                        log.warning("%s: юзернейм невалиден", row["account"])
                avatar = avatar_dir / f"{row['account']}.jpg"
                if avatar.exists():
                    uploaded = await client.upload_file(str(avatar))
                    await client(functions.account.UpdateProfilePhotoRequest(photo=uploaded))
                self.deps.storage.log_event(MODULE, "info", f"{row['account']}: профиль обновлён")
                updated += 1
            except FloodWaitError as exc:
                self.deps.rate_limiter.backoff(row["account"], exc.seconds)
                self.deps.storage.log_event(MODULE, "warn", f"{row['account']}: flood-wait {exc.seconds} c")
                failed += 1
            except Exception as exc:  # noqa: BLE001
                self.deps.storage.log_event(MODULE, "warn", f"{row['account']}: {type(exc).__name__}")
                failed += 1
            finally:
                await client.disconnect()

        self.deps.storage.log_event(MODULE, "info", f"обновлено {updated}, ошибок {failed}")
        log.info("Готово: обновлено=%d, ошибок=%d", updated, failed)
