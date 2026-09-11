"""Реестр плагинов: автоматическое обнаружение модулей в plugins/.

Для подключения нового модуля достаточно положить файл в plugins/ —
реестр найдёт его по импорту и зарегистрирует. Никакой ручной настройки.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import Type

from .base import PluginDeps, PluginProtocol

log = logging.getLogger(__name__)


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, Type[PluginProtocol]] = {}

    def register(self, plugin_cls: Type[PluginProtocol]) -> None:
        if not plugin_cls.name or plugin_cls.name == "base":
            return
        self._plugins[plugin_cls.name] = plugin_cls
        log.debug("Зарегистрирован модуль: %s", plugin_cls.name)

    def auto_discover(self, package_name: str = "plugins") -> None:
        """Импортирует все файлы пакета plugins и регистрирует классы-плагины.

        Модуль считается плагином, если он импортируется и содержит класс,
        наследующий PluginProtocol (с непустым `name`).
        """
        package = importlib.import_module(package_name)
        for mod in pkgutil.iter_modules(package.__path__):
            module = importlib.import_module(f"{package_name}.{mod.name}")
            for _, obj in vars(module).items():
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, PluginProtocol)
                    and obj is not PluginProtocol
                ):
                    self.register(obj)
        log.info("Обнаружено модулей: %d", len(self._plugins))

    def names(self) -> list[str]:
        return sorted(self._plugins)

    def get(self, name: str) -> Type[PluginProtocol] | None:
        return self._plugins.get(name)

    def instantiate(self, name: str, deps: PluginDeps) -> PluginProtocol:
        cls = self.get(name)
        if cls is None:
            raise KeyError(f"Модуль '{name}' не найден. Доступно: {', '.join(self.names())}")
        return cls(deps)


_registry: PluginRegistry | None = None


def get_registry() -> PluginRegistry:
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
    return _registry
