"""Адаптивный rate limiter: паузы между действиями одного аккаунта.

Правила из практики TeleRaptor:
- случайная задержка в диапазоне [min, max] перед каждым действием аккаунта
  (рандомизация — часть анти-детекта);
- при FloodWaitError аккаунт «замораживается» на время, указанное сервером
  (backoff), и очередь остальных аккаунтов не блокируется.
"""
from __future__ import annotations

import asyncio
import random
import time
from collections import defaultdict


class RateLimiter:
    def __init__(self, min_delay: float = 30.0, max_delay: float = 90.0):
        if min_delay <= 0 or max_delay < min_delay:
            raise ValueError(f"Некорректные задержки: min={min_delay}, max={max_delay}")
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._last_action: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def wait(self, account_key: str) -> None:
        """Ждёт, пока для account_key пройдёт случайная пауза с прошлого действия."""
        async with self._locks[account_key]:
            now = time.monotonic()
            last = self._last_action.get(account_key)
            if last is not None:
                need = last + random.uniform(self.min_delay, self.max_delay)
                if now < need:
                    await asyncio.sleep(need - now)
            self._last_action[account_key] = time.monotonic()

    def backoff(self, account_key: str, seconds: float) -> None:
        """После FloodWaitError: не трогаем аккаунт ещё `seconds` секунд."""
        if seconds > 0:
            self._last_action[account_key] = time.monotonic() + seconds
