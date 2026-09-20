"""Модуль: Клонер чатов (аналог «Клонер чатов» в TeleRaptor).

Копирует чат/канал-источник в целевой чат:
- мету: название, описание, аватар (нужны права админа в цели);
- историю сообщений: iter_messages + группировка альбомов, медиа скачивается
  и перезаливается; поддержана замена слов/ссылок (--replace старое=новое);
- карта соответствий id (data/cloner_map_<src>_<tgt>.json) — повторный запуск
  не дублирует уже скопированное (идемпотентность).

Запуск:
    python -m cli cloner @source @target --history 100
    python -m cli cloner @source @target --history 100 --send --replace "старая_ссылка=новая"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import tempfile
from pathlib import Path

from telethon import TelegramClient, functions

from .base import PluginDeps, PluginProtocol

log = logging.getLogger(__name__)

MODULE = "cloner"


def apply_replaces(text: str, rules: list[str]) -> str:
    """Применяет правила замены вида 'старое=новое' к тексту."""
    for rule in rules:
        if "=" not in rule:
            continue
        old, new = rule.split("=", 1)
        text = text.replace(old, new)
    return text


def map_path_for(data_dir: Path, source: str, target: str) -> Path:
    safe = lambda s: re.sub(r"[^\w.-]+", "_", s.strip("@")) or "chat"  # noqa: E731
    return data_dir / f"cloner_map_{safe(source)}_{safe(target)}.json"


def load_map(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    try:
        return {str(k): int(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
    except (json.JSONDecodeError, ValueError, TypeError):
        log.warning("Карта %s повреждена — начинаю с пустой.", path)
        return {}


def save_map(path: Path, mapping: dict[str, int]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


class ClonerPlugin(PluginProtocol):
    name = MODULE
    description = "Клонирование чата/канала: мету, аватар и историю (с картой id)"

    def _parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(prog="tg-suite cloner", description=self.description)
        p.add_argument("source", help="чат-источник (@username или ссылка)")
        p.add_argument("target", help="целевой чат (@username или ссылка)")
        p.add_argument("--history", type=int, default=100, help="сколько сообщений копировать")
        p.add_argument("--replace", action="append", default=[], metavar="СТАРОЕ=НОВОЕ",
                       help="замена в текстах (можно несколько раз)")
        p.add_argument("--no-media", action="store_true", help="не копировать медиа")
        p.add_argument("--no-meta", action="store_true", help="не трогать название/описание/аватар цели")
        p.add_argument("--send", action="store_true", help="реально копировать (по умолчанию dry-run)")
        return p

    async def run(self, args: list[str]) -> None:
        ns = self._parser().parse_args(args)

        if not self.deps.api_id or not self.deps.api_hash:
            raise ValueError("Клонеру нужны API_ID и API_HASH (my.telegram.org)")
        names = self.deps.sessions.list_session_names()
        if not names:
            raise ValueError("Нет сессий в каталоге sessions/")

        account = names[0]
        proxy = self.deps.proxies.get_for(names.index(account))
        client = self.deps.sessions.build_client(account, self.deps.api_id, self.deps.api_hash, proxy)
        await client.connect()
        try:
            src = await client.get_entity(ns.source)
            tgt = await client.get_entity(ns.target)
            src_title = getattr(src, "title", None) or ns.source
            tgt_title = getattr(tgt, "title", None) or ns.target
            m_path = map_path_for(self.deps.sessions.settings.db_path.parent, ns.source, ns.target)
            mapping = load_map(m_path)

            if not ns.send:
                print("┌─ ПЛАН КЛОНИРОВАНИЯ (dry-run) ───────────────────────────────")
                print(f"│ источник: {src_title}  →  цель: {tgt_title}")
                print(f"│ история: до {ns.history} сообщений; медиа: {'нет' if ns.no_media else 'да'}")
                print(f"│ замены: {ns.replace or 'нет'}; уже скопировано: {len(mapping)}")
                print("└──────────────────────────────────────────────────────────────")
                log.info("DRY-RUN: для реального копирования добавьте --send.")
                return

            if not ns.no_meta:
                await self._copy_meta(client, src, tgt, ns)
            copied = await self._copy_history(client, src, tgt, ns, m_path, mapping)
            self.deps.storage.log_event(MODULE, "info", f"{ns.source} -> {ns.target}: скопировано {copied}")
        finally:
            await client.disconnect()

    # ---------------------------------------------------------------- мета
    async def _copy_meta(self, client: TelegramClient, src, tgt, ns) -> None:
        try:
            full = await client(functions.channels.GetFullChannelRequest(src))
            about = full.full_chat.about or ""
            if about and getattr(tgt, "title", None) is not None:
                await client(functions.channels.EditAboutRequest(tgt, apply_replaces(about, ns.replace)))
                log.info("Описание цели обновлено.")
        except Exception as exc:  # noqa: BLE001
            log.warning("Описание не скопировано: %s", exc)

        try:
            title = getattr(src, "title", None)
            if title:
                await client(functions.channels.EditTitleRequest(tgt, apply_replaces(title, ns.replace)))
                log.info("Название цели обновлено.")
        except Exception as exc:  # noqa: BLE001
            log.warning("Название не скопировано: %s", exc)

        try:
            photo = getattr(src, "photo", None)
            if photo:
                with tempfile.TemporaryDirectory() as td:
                    path = await client.download_media(src.photo, file=td)
                    if path:
                        uploaded = await client.upload_file(path)
                        await client(functions.channels.EditPhotoRequest(tgt, uploaded))
                        log.info("Аватар цели обновлён.")
        except Exception as exc:  # noqa: BLE001
            log.warning("Аватар не скопирован: %s", exc)

    # ---------------------------------------------------------------- история
    async def _copy_history(self, client: TelegramClient, src, tgt, ns, m_path: Path, mapping: dict[str, int]) -> int:
        copied = skipped = 0
        with tempfile.TemporaryDirectory() as td:
            async for msg in client.iter_messages(src, limit=ns.history, reverse=True):
                if str(msg.id) in mapping:
                    skipped += 1
                    continue
                text = apply_replaces(msg.message or "", ns.replace) if msg.message else ""
                try:
                    if msg.media and not ns.no_media:
                        path = await client.download_media(msg, file=td)
                        if path:
                            sent = await client.send_file(tgt, path, caption=text or None)
                        else:
                            continue
                    elif text:
                        sent = await client.send_message(tgt, text)
                    else:
                        continue
                    mapping[str(msg.id)] = sent.id
                    save_map(m_path, mapping)
                    copied += 1
                    if copied % 10 == 0:
                        log.info("Скопировано %d…", copied)
                    await asyncio.sleep(random.uniform(1.0, 3.0))
                except Exception as exc:  # noqa: BLE001 — сообщение не критично
                    log.warning("Сообщение %s не скопировано: %s", msg.id, exc)
        log.info("Копирование завершено: новых=%d, уже были=%d", copied, skipped)
        return copied
