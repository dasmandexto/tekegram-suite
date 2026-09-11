"""Плагины: бизнес-модули, подключаемые через реестр.

Каждый новый модуль TeleRaptor (спамер, парсер, инвайтер, клонер чатов,
автоответчик, конвертер tdata и т.д.) — это один Python-файл в plugins/,
наследующий PluginProtocol.
"""
from .base import PluginDeps, PluginProtocol
from .registry import PluginRegistry, get_registry

__all__ = ["PluginDeps", "PluginProtocol", "PluginRegistry", "get_registry"]
