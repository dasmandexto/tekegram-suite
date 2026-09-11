"""Ядро: независимые от модулей сервисы (storage, rate limiter, прокси, сессии).

Слои:
- config   -> настройки из .env
- core     -> инфраструктура (ничего не знает про бизнес-модули)
- plugins  -> модули (спамер, парсер, инвайтер, ...), подключаются через реестр
- cli      -> точка входа, оркестрация
"""
from .context import Context
from .errors import (
    AccountError,
    ConfigError,
    FloodLimitError,
    PluginError,
    StopPlugin,
    TelegramSuiteError,
)
from .rate_limiter import RateLimiter
from .sessions import SessionPool
from .storage import Storage

__all__ = [
    "Context",
    "AccountError",
    "ConfigError",
    "FloodLimitError",
    "PluginError",
    "RateLimiter",
    "SessionPool",
    "Storage",
    "StopPlugin",
    "TelegramSuiteError",
]
