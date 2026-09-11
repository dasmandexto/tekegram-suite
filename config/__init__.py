"""Пакет конфигурации: загрузка .env и валидация настроек."""
from .loader import Settings, load_settings

__all__ = ["Settings", "load_settings"]
