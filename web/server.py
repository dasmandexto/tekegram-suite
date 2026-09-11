"""Запуск веб-сервера (аналог «Телераптор Веб»)."""
from __future__ import annotations

import argparse

import uvicorn

from config import Settings
from core.logging_setup import setup_logging
from .app import create_app


def run_web(settings: Settings, argv: list[str] | None = None) -> int:
    setup_logging(settings.log_level)
    parser = argparse.ArgumentParser(prog="tg-suite web", description="Веб-интерфейс Telegram Suite")
    parser.add_argument("--host", default="127.0.0.1", help="адрес (по умолчанию 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="порт (по умолчанию 8000)")
    ns = parser.parse_args(argv)

    app = create_app(settings)
    print(f"\n  Telegram Suite Web:  http://{ns.host}:{ns.port}\n")
    uvicorn.run(app, host=ns.host, port=ns.port)
    return 0
