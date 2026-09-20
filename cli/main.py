"""Консольная точка входа проекта (аналог консольного интерфейса TeleRaptor).

Примеры:
    python -m cli list                # список аккаунтов (сессий)
    python -m cli checker             # проверить все аккаунты
    python -m cli checker <имя>       # проверить один аккаунт
    python -m cli web                 # веб-интерфейс: http://127.0.0.1:8000
    python -m cli web --port 9000     # веб-интерфейс на другом порту
    python -m cli --help
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from config import load_settings
from core import StopPlugin
from core.logging_setup import setup_logging
from plugins import PluginDeps, get_registry


def build_parser() -> argparse.ArgumentParser:
    registry = get_registry()
    registry.auto_discover()

    parser = argparse.ArgumentParser(
        prog="tg-suite",
        description="Модульный набор инструментов для Telegram (по мотивам TeleRaptor)",
    )
    parser.add_argument("--env", default=None, help="путь к файлу .env (по умолчанию ./.env)")
    parser.add_argument("--list", action="store_true", help="показать доступные модули и выйти")
    parser.add_argument("--sessions", action="store_true", help="показать список аккаунтов и выйти")
    parser.add_argument("module", nargs="?", help=f"имя модуля: {', '.join(registry.names())}, web")
    parser.add_argument("module_args", nargs="*", help="аргументы модуля (например --port 9000)")
    return parser


def main(argv: list[str] | None = None) -> int:
    # parse_known_args: флаги вида `--port 9000` для модуля web уходят в `unknown`
    # и передаются модулю; для остальных модулей неизвестные флаги — это ошибка.
    parser = build_parser()
    args, unknown = parser.parse_known_args(argv)

    if args.list:
        registry = get_registry()
        for name in registry.names():
            cls = registry.get(name)
            print(f"  {name:14s} — {cls.description}" if cls else name)
        return 0

    settings = load_settings(args.env, require_api=False)

    if args.sessions:
        from core import Context

        ctx = Context(settings)
        names = ctx.sessions.list_session_names()
        print(f"Аккаунтов (сессий): {len(names)}")
        for n in names:
            status = ctx.storage.account_status(n)
            mark = f" [{status['status']}]" if status else ""
            print(f"  {n}{mark}")
        ctx.close()
        return 0

    if not args.module:
        print("Укажите модуль. Список: --list")
        return 2

    if args.module == "web":
        from web.server import run_web

        return run_web(settings, args.module_args + unknown)

    if unknown:
        print(f"Неизвестные аргументы для модуля '{args.module}': {' '.join(unknown)}")
        return 2

    setup_logging(settings.log_level)

    registry = get_registry()
    if not registry.get(args.module):
        print(f"Модуль '{args.module}' не найден. Доступно: {', '.join(registry.names())}")
        return 2

    from core import Context

    ctx = Context(settings)
    try:
        # require_api=True НЕ ставим: dry-run модулей (broadcast, checker) не должен
        # требовать API-креды. Модули сами проверяют креды перед реальной отправкой.
        settings.validate()
        deps = PluginDeps(
            storage=ctx.storage,
            rate_limiter=ctx.rate_limiter,
            proxies=ctx.proxies,
            sessions=ctx.sessions,
            api_id=settings.api_id,
            api_hash=settings.api_hash,
        )
        plugin = registry.instantiate(args.module, deps)
        asyncio.run(plugin.run(args.module_args))
    except KeyboardInterrupt:
        print("\nОстановлено пользователем.")
        return 130
    except StopPlugin:
        print("\nОстановлено.")
        return 0
    except Exception as exc:  # noqa: BLE001 — печатаем причину и выходим с кодом
        print(f"Ошибка: {exc}")
        if "API_ID" in str(exc):
            # Самодиагностика: показываем, где искали .env и что видели.
            print("\nДиагностика конфигурации (где искали .env / config.ini):")
            for line in settings.env_report:
                print(f"  {line}")
            print("  → впишите ключи в .env в каталоге проекта, формат:")
            print("    API_ID=12345678")
            print("    API_HASH=abcdef0123456789abcdef0123456789")
        return 1
    finally:
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
