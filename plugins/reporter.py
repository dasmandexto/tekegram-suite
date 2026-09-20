"""Модуль: Репортер — жалобы на нарушителей (каркас с жёсткими лимитами).

Отчёт по правилам: вы жалуетесь на КОНКРЕТНЫЕ нарушения (спам, мошенничество),
по одному отчёту на цель, с дневным лимитом. Это НЕ инструмент для массовых
абузных «закатов» конкурентов — лимиты и dry-run ограничивают злоупотребление.

Файл целей data/report_targets.txt (по одной цели в строку, '#' — комментарий):
    @spam_channel
    https://t.me/scam_user

Причины (reason): spam, violence, childabuse, pornography, copyright,
other (default: spam).

Запуск:
    python -m cli reporter --file data/report_targets.txt --reason spam
    python -m cli reporter --file ... --send        # реально отправить
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from telethon import functions, types
from telethon.errors import FloodWaitError

from .base import PluginDeps, PluginProtocol

log = logging.getLogger(__name__)

MODULE = "reporter"

RUN_CAP = 25  # максимум целей за один запуск — жёсткий предел

REASONS = ("spam", "violence", "childabuse", "pornography", "copyright", "other")


def parse_targets(path: Path) -> list[str]:
    if not path.exists():
        raise ValueError(f"Файл целей не найден: {path}")
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line not in out:
            out.append(line)
    return out


def reason_obj(name: str):
    """Строка -> конструктор причины Telegram (защита от смены API).

    В разных версиях Telethon класс называется по-разному:
    ReportReasonSpam (новые слои) / InputReportReasonSpam (старые).
    """
    variants = {
        "spam": ("InputReportReasonSpam", "ReportReasonSpam"),
        "violence": ("InputReportReasonViolence", "ReportReasonViolence"),
        "childabuse": ("InputReportReasonChildAbuse", "ReportReasonChildAbuse"),
        "pornography": ("InputReportReasonPornography", "ReportReasonPornography"),
        "copyright": ("InputReportReasonCopyright", "ReportReasonCopyright"),
        "other": ("InputReportReasonOther", "ReportReasonOther"),
    }
    for cls_name in variants[name]:
        cls = getattr(types, cls_name, None)
        if cls is not None:
            return cls()
    raise ValueError(f"Текущая версия Telethon не поддерживает причину '{name}'")


class ReporterPlugin(PluginProtocol):
    name = MODULE
    description = "Жалобы на нарушителей (по одному на цель, дневной лимит, dry-run)"

    def _parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(prog="tg-suite reporter", description=self.description)
        p.add_argument("--file", default=None, help="файл целей (по умолчанию data/report_targets.txt)")
        p.add_argument("--reason", choices=REASONS, default="spam", help="причина жалобы")
        p.add_argument("--comment", default="", help="комментарий к жалобе (для 'other')")
        p.add_argument("--limit", type=int, default=0, help="макс. целей за запуск (макс. 25)")
        p.add_argument("--send", action="store_true", help="реально отправить (по умолчанию dry-run)")
        return p

    async def run(self, args: list[str]) -> None:
        ns = self._parser().parse_args(args)

        targets_path = (
            Path(ns.file) if ns.file
            else self.deps.sessions.settings.db_path.parent / "report_targets.txt"
        )
        targets = parse_targets(targets_path)[: min(ns.limit, RUN_CAP) or RUN_CAP]
        sessions = self.deps.sessions.list_session_names()
        if not sessions:
            raise ValueError("Нет сессий в каталоге sessions/")

        if not ns.send:
            print("┌─ ПЛАН ЖАЛОБ (dry-run) ──────────────────────────────────────")
            print(f"│ целей: {len(targets)} (лимит запуска: {RUN_CAP}); причина: {ns.reason}")
            for t in targets[:10]:
                print(f"│   → {t}")
            print("└──────────────────────────────────────────────────────────────")
            log.info("DRY-RUN: для отправки добавьте --send.")
            return

        if not self.deps.api_id or not self.deps.api_hash:
            raise ValueError("Нужны API_ID и API_HASH (my.telegram.org)")

        account = sessions[0]
        client = self.deps.sessions.build_client(
            account, self.deps.api_id, self.deps.api_hash,
            self.deps.proxies.get_for(sessions.index(account)),
        )
        reason = reason_obj(ns.reason)
        sent = failed = 0
        await client.connect()
        try:
            for target in targets:
                if self.deps.storage.count_sent_today(account, MODULE) >= RUN_CAP:
                    log.warning("Дневной лимит жалоб исчерпан для %s", account)
                    break
                await self.deps.rate_limiter.wait(account)
                try:
                    peer = await client.get_entity(target)
                    await client(functions.account.ReportPeerRequest(
                        peer=peer, reason=reason, message=ns.comment or None,
                    ))
                    self.deps.storage.mark_sent(account, target, MODULE)
                    self.deps.storage.log_event(MODULE, "info", f"{account}: жалоба на {target}")
                    sent += 1
                except FloodWaitError as exc:
                    self.deps.rate_limiter.backoff(account, exc.seconds)
                    self.deps.storage.log_event(MODULE, "warn", f"{account}: flood-wait {exc.seconds} c")
                    break
                except Exception as exc:  # noqa: BLE001
                    self.deps.storage.log_event(MODULE, "warn", f"{account}: {target} {type(exc).__name__}")
                    failed += 1
        finally:
            await client.disconnect()
        self.deps.storage.log_event(MODULE, "info", f"жалоб отправлено {sent}, ошибок {failed}")
        log.info("Готово: отправлено=%d, ошибок=%d", sent, failed)
