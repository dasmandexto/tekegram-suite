"""Контекст приложения: DI-контейнер, собирающий все сервисы ядра.

Каждый плагин получает Context и через него обращается к хранилищу,
rate limiter'у, пулу прокси и пулу сессий.
"""
from __future__ import annotations

import logging

from config import Settings
from .proxies import ProxyPool
from .rate_limiter import RateLimiter
from .sessions import SessionPool
from .storage import Storage

log = logging.getLogger(__name__)


class Context:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.storage = Storage(settings.db_path)
        self.rate_limiter = RateLimiter(
            min_delay=settings.min_delay_seconds,
            max_delay=settings.max_delay_seconds,
        )
        self.proxies = ProxyPool()
        self.sessions = SessionPool(settings)

        loaded = self.proxies.load_from_file(settings.proxies_file)
        log.info(
            "Контекст готов: сессий=%d, прокси=%d, БД=%s",
            self.sessions.count,
            loaded,
            settings.db_path,
        )

    def close(self) -> None:
        self.storage.close()
