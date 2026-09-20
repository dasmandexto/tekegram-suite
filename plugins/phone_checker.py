"""Модуль: Чекер номеров (аналог «Чекер номеров» в TeleRaptor).

Проверяет, зарегистрирован ли номер в Telegram, через импорт контактов:
    ImportContactsRequest -> вернувшиеся users = «registered»;
    не вернувшиеся = «not_registered». Коды/SMS НЕ запрашиваются.

Гигиена аккаунта: импортированные контакты сразу удаляются
(DeleteContactsRequest), аккаунт остаётся чистым.

Нормализация к E.164: пробелы/скобки/дефисы выкидываются; локальный
российский формат 8XXXXXXXXXX (11 цифр) конвертируется в +7XXXXXXXXXX;
без «+» и не 8-старт — считаем, что номер уже международный. Строки,
не дающие 8–15 цифр, отбрасываются с предупреждением.

Результат: data/checked_numbers_<дата>.txt, строка:
    phone|registered|user_id|@username|Имя

Защита: батчи (по умолчанию 100), паузы 1–3 c между батчами,
FloodWaitError -> пауза на время, указанное сервером, затем повтор батча.

Запуск:
    python -m cli phonechecker --file numbers.txt
    python -m cli phonechecker --file numbers.txt --batch 50 --limit 500
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import logging
import random
import re
from pathlib import Path

from telethon import functions, types
from telethon.errors import FloodWaitError

from .base import PluginDeps, PluginProtocol

log = logging.getLogger(__name__)

MODULE = "phonechecker"


def normalize_phone(raw: str) -> str | None:
    """Нормализация к E.164 (+ и 8–15 цифр); None = не номер."""
    raw = raw.strip()
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]  # локальный формат 8XXXXXXXXXX -> +7XXXXXXXXXX
    if not 8 <= len(digits) <= 15:
        return None
    return "+" + digits


def parse_numbers(path: Path) -> list[str]:
    """Читает номера из файла (по одному в строке), нормализует, дедуп."""
    if not path.exists():
        raise ValueError(f"Файл номеров не найден: {path}")
    out: list[str] = []
    bad = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        phone = normalize_phone(line)
        if phone is None:
            bad += 1
            continue
        if phone not in out:
            out.append(phone)
    if bad:
        log.warning("Отброшено невалидных строк: %d", bad)
    if not out:
        raise ValueError("Нет ни одного валидного номера (нужен E.164 или 8XXXXXXXXXX)")
    return out


def chunked(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


class PhoneCheckerPlugin(PluginProtocol):
    name = MODULE
    description = "Проверка номеров на регистрацию в Telegram (без SMS, батчами)"

    def _parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(prog="tg-suite phonechecker", description=self.description)
        p.add_argument("--file", required=True, help="файл с номерами (по одному в строке)")
        p.add_argument("--batch", type=int, default=100, help="номеров за один запрос (макс. 200)")
        p.add_argument("--limit", type=int, default=0, help="макс. номеров за запуск (0 = все)")
        return p

    async def run(self, args: list[str]) -> None:
        ns = self._parser().parse_args(args)

        if not self.deps.api_id or not self.deps.api_hash:
            raise ValueError("Чекеру номеров нужны API_ID и API_HASH (my.telegram.org)")
        names = self.deps.sessions.list_session_names()
        if not names:
            raise ValueError("Нет сессий в каталоге sessions/")

        numbers = parse_numbers(Path(ns.file))
        if ns.limit > 0:
            numbers = numbers[: ns.limit]
        batch = max(1, min(ns.batch, 200))
        log.info("Чекер номеров: %d номеров, батчи по %d", len(numbers), batch)

        account = names[0]
        proxy = self.deps.proxies.get_for(names.index(account))
        client = self.deps.sessions.build_client(account, self.deps.api_id, self.deps.api_hash, proxy)

        rows: list[tuple[str, str, str, str, str]] = []
        await client.connect()
        try:
            for chunk in chunked(numbers, batch):
                rows.extend(await self._check_chunk(client, account, chunk))
                await asyncio.sleep(random.uniform(1.0, 3.0))
        finally:
            await client.disconnect()

        out_path = self.deps.sessions.settings.db_path.parent / f"checked_numbers_{dt.date.today()}.txt"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as fh:
            fh.write("# phone|status|user_id|username|name\n")
            for phone, status, user_id, username, name in rows:
                fh.write(f"{phone}|{status}|{user_id}|{username}|{name}\n")

        registered = sum(1 for r in rows if r[1] == "registered")
        self.deps.storage.log_event(MODULE, "info", f"проверено {len(rows)}, зарегистрировано {registered}")
        log.info("Готово: %d/%d зарегистрировано -> %s", registered, len(rows), out_path)

    async def _check_chunk(self, client, account: str, chunk: list[str]) -> list[tuple]:
        rows: list[tuple] = []
        for attempt in (1, 2):  # один повтор после флуд-паузы
            try:
                contacts = [
                    types.InputPhoneContact(
                        random_id=random.randrange(1 << 62), phone=phone
                    )
                    for phone in chunk
                ]
                resp = await client(functions.contacts.ImportContactsRequest(contacts))
                break
            except FloodWaitError as exc:
                log.warning("Флуд-лимит: пауза %d c (попытка %d)", exc.seconds, attempt)
                self.deps.rate_limiter.backoff(account, exc.seconds)
                await asyncio.sleep(exc.seconds + 2)
                if attempt == 2:
                    raise
        else:  # pragma: no cover
            return []

        # Telegram возвращает phone без '+'
        users_by_phone = {
            u.phone: u for u in resp.users if getattr(u, "phone", None)
        }
        matched = []
        for phone in chunk:
            u = users_by_phone.get(phone.lstrip("+"))
            if u is None:
                rows.append((phone, "not_registered", "", "", ""))
                continue
            matched.append(u)
            username = f"@{u.username}" if getattr(u, "username", None) else ""
            name = " ".join(filter(None, [u.first_name, u.last_name])).strip()
            rows.append((phone, "registered", str(u.id), username, name))

        if matched:  # не оставляем импортированные контакты в аккаунте
            try:
                await client(functions.contacts.DeleteContactsRequest(matched))
            except Exception as exc:  # noqa: BLE001 — чистка не критична
                log.debug("Не удалось удалить импортированные контакты: %s", exc)
        return rows
