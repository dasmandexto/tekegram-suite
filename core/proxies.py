"""Пул прокси: загрузка списка из файла и раздача по аккаунтам.

Правило TeleRaptor — один аккаунт = один стабильный прокси.
Поддерживаемые форматы строк в proxies.txt (по одной на строку):
    socks5://user:pass@host:port
    http://host:port
    host:port
    host:port:user:pass
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(slots=True)
class Proxy:
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    @property
    def key(self) -> str:
        return f"{self.host}:{self.port}"

    def as_telethon(self) -> tuple:
        """Кортеж в формате, который принимает Telethon как `proxy`."""
        return (self.scheme, self.host, self.port, self.username, self.password)


def parse_proxy_line(line: str) -> Proxy | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    if "://" in line:
        u = urlparse(line)
        scheme = u.scheme or "socks5"
        host = u.hostname
        port = u.port
        if not host or not port:
            raise ValueError(f"Не удалось распарсить прокси: {line!r}")
        return Proxy(scheme, host, port, u.username, u.password)

    parts = line.split(":")
    if len(parts) == 2:
        return Proxy("socks5", parts[0], int(parts[1]))
    if len(parts) == 4:
        return Proxy("socks5", parts[0], int(parts[1]), parts[2], parts[3])
    raise ValueError(f"Не удалось распарсить прокси: {line!r}")


class ProxyPool:
    def __init__(self):
        self._proxies: list[Proxy] = []

    def load_from_file(self, path: Path) -> int:
        if not path.exists():
            return 0
        added = 0
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                proxy = parse_proxy_line(raw)
                if proxy is not None:
                    self._proxies.append(proxy)
                    added += 1
        return added

    def add(self, proxy: Proxy) -> None:
        self._proxies.append(proxy)

    def get_random(self) -> Proxy | None:
        return random.choice(self._proxies) if self._proxies else None

    def get_for(self, index: int) -> Proxy | None:
        """Стабильный прокси для аккаунта с номером `index` (один аккаунт — один прокси)."""
        if not self._proxies:
            return None
        return self._proxies[index % len(self._proxies)]

    def __len__(self) -> int:
        return len(self._proxies)
