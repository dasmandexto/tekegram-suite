"""Загрузка конфигурации из .env + базовые настройки проекта.

Единая точка истины по настройкам: все остальные слои получают объект Settings
через Context и не читают переменные окружения напрямую.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover — dev-без dotenv
    load_dotenv = None


def _load_env_file(path: Path | None) -> None:
    # По умолчанию — .env из текущего каталога (как ожидает CLI и install.sh).
    target = path if path is not None else Path(".env")
    if target.exists() and load_dotenv is not None:
        load_dotenv(target)


@dataclass(slots=True)
class Settings:
    # API credentials (my.telegram.org)
    api_id: int | None = None
    api_hash: str | None = None

    # Пути
    sessions_dir: Path = Path("./sessions")
    proxies_file: Path = Path("./proxies.txt")
    db_path: Path = Path("./data/app.db")

    # Rate limiting: пауза между действиями одного аккаунта
    min_delay_seconds: float = 30.0
    max_delay_seconds: float = 90.0

    # Планировщик
    max_concurrency: int = 5
    retry_attempts: int = 3

    # Инвайтер: дневной лимит приглашений на аккаунт
    invite_daily_cap: int = 40

    # Логирование
    log_level: str = "INFO"

    def validate(self, *, require_api: bool = False) -> None:
        if require_api and (not self.api_id or not self.api_hash):
            raise ValueError("API_ID и API_HASH обязательны (my.telegram.org, раздел API development tools)")
        if self.min_delay_seconds <= 0 or self.max_delay_seconds < self.min_delay_seconds:
            raise ValueError(f"Некорректные задержки: min={self.min_delay_seconds}, max={self.max_delay_seconds}")
        if self.max_concurrency < 1:
            raise ValueError("MAX_CONCURRENCY должен быть >= 1")
        if self.invite_daily_cap < 1:
            raise ValueError("INVITE_DAILY_CAP должен быть >= 1")
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


def load_settings(env_path: str | Path | None = None, *, require_api: bool = False) -> Settings:
    """Читает .env (по умолчанию — файл .env в cwd), собирает и валидирует Settings.

    require_api=True — жёсткая проверка: без API_ID/API_HASH бросает ValueError.
    """
    path = Path(env_path) if env_path else None
    _load_env_file(path)

    raw_id = os.getenv("API_ID")
    settings = Settings(
        api_id=int(raw_id) if raw_id and raw_id.strip() else None,
        api_hash=os.getenv("API_HASH") or None,
        sessions_dir=Path(os.getenv("SESSIONS_DIR", "./sessions")),
        proxies_file=Path(os.getenv("PROXIES_FILE", "./proxies.txt")),
        db_path=Path(os.getenv("DB_PATH", "./data/app.db")),
        min_delay_seconds=float(os.getenv("MIN_DELAY_SECONDS", "30")),
        max_delay_seconds=float(os.getenv("MAX_DELAY_SECONDS", "90")),
        max_concurrency=int(os.getenv("MAX_CONCURRENCY", "5")),
        retry_attempts=int(os.getenv("RETRY_ATTEMPTS", "3")),
        invite_daily_cap=int(os.getenv("INVITE_DAILY_CAP", "40")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
    settings.validate(require_api=require_api)
    return settings
