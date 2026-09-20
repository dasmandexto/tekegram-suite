"""Модуль: Конвертер tdata → session (аналог «Конвертера» в TeleRaptor).

Конвертирует папки tdata (Telegram Desktop) в файлы сессий Telethon,
БЕЗ нового входа — переиспользуя auth_key из tdata.

Зависимость: opentele (бинарный разбор tdata руками НЕ пишем).
    pip install opentele

Как найти tdata: %APPDATA%/Telegram Desktop/tdata (Windows) или
~/Library/... (Mac). Для конвертации указывайте папку, содержащую каталог
`tdata` (или сам каталог tdata — определяется автоматически).

Запуск:
    python -m cli tdata2session --src ~/tdata_root --out sessions
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .base import PluginDeps, PluginProtocol

log = logging.getLogger(__name__)

MODULE = "tdata2session"


def find_tdata_dirs(root: Path) -> list[Path]:
    """Ищет каталоги tdata: сам root, его подкаталог tdata/ или все подкаталоги с tdata/."""
    if not root.exists():
        raise ValueError(f"Каталог не найден: {root}")
    found: list[Path] = []

    def is_tdata(p: Path) -> bool:
        return p.is_dir() and (p / "key_datas").exists()

    candidates = [root] + [p for p in root.iterdir() if p.is_dir()]
    for cand in candidates:
        if is_tdata(cand):
            found.append(cand)
        elif (cand / "tdata").is_dir() and is_tdata(cand / "tdata"):
            found.append(cand / "tdata")
    uniq: list[Path] = []
    for p in found:
        if p not in uniq:
            uniq.append(p)
    return uniq


class TdataConverterPlugin(PluginProtocol):
    name = MODULE
    description = "Конвертация tdata (Telegram Desktop) в *.session Telethon через opentele"

    def _parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(prog="tg-suite tdata2session", description=self.description)
        p.add_argument("--src", required=True, help="корень с tdata (папка или её родитель)")
        p.add_argument("--out", default=None, help="каталог для *.session (по умолчанию SESSIONS_DIR)")
        return p

    async def run(self, args: list[str]) -> None:
        ns = self._parser().parse_args(args)

        try:
            from opentele.td import TDesktop  # noqa: F401
            from opentele.tg import TelegramClient as OtpTelegramClient
            from opentele.api import UseCurrentSession
        except ImportError as exc:
            raise ValueError(
                "Нужна библиотека opentele: pip install opentele\n"
                f"({exc})"
            ) from exc

        src = Path(ns.src)
        out_dir = Path(ns.out) if ns.out else self.deps.sessions.settings.sessions_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        tdata_dirs = find_tdata_dirs(src)
        if not tdata_dirs:
            raise ValueError(
                f"В '{src}' не найдено каталогов tdata (нет key_datas). Укажите папку tdata или её родителя."
            )
        log.info("Найдено tdata-каталогов: %d", len(tdata_dirs))

        ok = failed = 0
        for i, tdata in enumerate(tdata_dirs, 1):
            out_path = out_dir / f"tdata_{i}"
            try:
                tdesk = TDesktop.FromTData(str(tdata))
                if not tdesk.isLoaded():
                    raise ValueError(f"tdata не загружен: {tdata}")
                otp_client = OtpTelegramClient.FromTDesktop(
                    tdesk, session=str(out_path), flag=UseCurrentSession
                )
                otp_client.Save()
                self.deps.storage.log_event(MODULE, "info", f"{tdata} -> {out_path}.session")
                log.info("[%d/%d] OK: %s -> %s.session", i, len(tdata_dirs), tdata, out_path)
                ok += 1
            except Exception as exc:  # noqa: BLE001 — повреждённый tdata не роняет пакет
                self.deps.storage.log_event(MODULE, "warn", f"{tdata}: {type(exc).__name__}")
                log.warning("[%d/%d] ошибка: %s (%s)", i, len(tdata_dirs), tdata, exc)
                failed += 1

        self.deps.storage.log_event(MODULE, "info", f"конвертировано {ok}, ошибок {failed}")
        log.info("Готово: конвертировано=%d, ошибок=%d, каталог: %s", ok, failed, out_dir)
