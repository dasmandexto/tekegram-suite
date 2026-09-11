"""Базовый контракт плагина.

Плагин не знает про Telethon напрямую: он получает `deps` — уже готовые
сервисы ядра (storage, rate limiter, прокси, сессии) и api_id/api_hash.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from core import RateLimiter, SessionPool, Storage
from core.proxies import ProxyPool


@dataclass(slots=True)
class PluginDeps:
    storage: Storage
    rate_limiter: RateLimiter
    proxies: ProxyPool
    sessions: SessionPool
    api_id: int | None
    api_hash: str | None


class PluginProtocol(ABC):
    """Контракт модуля.

    name        — короткое имя для CLI и журнала (например, "spamer")
    description — описание для справки CLI
    """

    name: str = "base"
    description: str = ""

    def __init__(self, deps: PluginDeps):
        self.deps = deps

    @abstractmethod
    async def run(self, args: list[str]) -> None:
        """Точка входа модуля. args — аргументы, переданные после имени модуля."""
