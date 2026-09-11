"""Веб-интерфейс (аналог «Телераптор Веб»): локальный сервер поверх модулей.

Запуск:
    python -m cli web            # или
    python -m web --env .env
Открыть в браузере: http://127.0.0.1:8000
"""
from .app import create_app

__all__ = ["create_app"]
