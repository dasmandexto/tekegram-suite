"""Типовые ошибки проекта."""


class TelegramSuiteError(Exception):
    """Базовая ошибка проекта."""


class ConfigError(TelegramSuiteError):
    """Некорректная конфигурация."""


class PluginError(TelegramSuiteError):
    """Ошибка в плагине."""


class AccountError(TelegramSuiteError):
    """Ошибка, связанная с состоянием аккаунта (бан, спамблок и т.п.)."""


class FloodLimitError(AccountError):
    """Аккаунт упёрся во флуд-лимит (FloodWaitError / PeerFloodError)."""


class StopPlugin(BaseException):
    """Сигнал плагину остановиться штатно (Ctrl+C и т.п.)."""
