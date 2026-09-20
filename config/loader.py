"""Загрузка конфигурации из .env / config.ini / переменных окружения.

Единая точка истины по настройкам: все остальные слои получают объект Settings
через Context и не читают переменные окружения напрямую.

Устойчивость к формату пользователя:
  * ищет .env в трёх местах: текущий каталог, корень проекта, ~/.telegram-suite;
  * понимает BOM, CRLF, `export KEY=...`, кавычки, пробелы вокруг `=`,
    inline-комментарии (`API_ID=123 # мой id`), нижний/верхний регистр ключей;
  * если .env нигде нет — пробует config.ini (секция [telegram]);
  * настоящие переменные окружения имеют приоритет над файлом;
  * при отсутствии API-кредов report() объясняет, где файл искался.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover — dev-без dotenv
    load_dotenv = None


def _candidate_files(name: str, env_path: str | Path | None) -> list[Path]:
    """Кандидаты файла конфигурации в порядке приоритета."""
    if env_path:
        return [Path(env_path)]
    project_root = Path(__file__).resolve().parent.parent
    home = Path.home()
    return [
        Path.cwd() / name,
        project_root / name,
        home / ".telegram-suite" / name,
        home / name,
    ]


def _parse_env_text(text: str, into: dict[str, str]) -> None:
    """Ручной разбор .env: терпим к BOM, CRLF, export, кавычкам, регистру."""
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:].lstrip()
        key, _, value = line.partition("=")
        key = key.strip().upper()
        value = value.strip()

        def _unquote(val: str) -> str:
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                return val[1:-1].strip()
            return val

        # снимаем inline-комментарий, затем кавычки (в любом порядке появления)
        if " #" in value:
            value = value.split(" #", 1)[0].strip()
        value = _unquote(value)
        if key and key not in into:
            into[key] = value


def _load_env_candidates(env_path: str | Path | None, report: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    candidates = _candidate_files(".env", env_path)
    used = False
    for cand in candidates:
        report.append(f"env: {cand} [{'найден' if cand.exists() else 'нет'}]")
        if not cand.exists() or used and env_path:
            continue
        try:
            text = cand.read_text(encoding="utf-8-sig")
        except OSError as exc:
            report.append(f"env: {cand} не прочитан: {exc}")
            continue
        _parse_env_text(text, found)
        if env_path:  # явный путь — единственный источник
            used = True
    # env-переменные процесса имеют приоритет: они уже видны через os.getenv,
    # поэтому в found пишем только то, чего там нет.
    for key, value in found.items():
        if key not in os.environ:
            os.environ[key] = value
    return found


def _load_ini_candidates(report: list[str]) -> None:
    """Резерв: config.ini, секция [telegram] (api_id / api_hash в любом регистре)."""
    try:
        import configparser
    except ImportError:  # pragma: no cover
        return
    for cand in _candidate_files("config.ini", None):
        if not cand.exists():
            if str(cand) not in report:
                report.append(f"ini: {cand} [нет]")
            continue
        if str(cand) in report:
            continue
        report.append(f"ini: {cand} [найден]")
        parser = configparser.ConfigParser()
        try:
            parser.read(cand, encoding="utf-8-sig")
        except (OSError, configparser.Error):
            continue  # битый/чужой ini — молча пропускаем
        for section in parser.sections() + ["DEFAULT"]:
            for key, value in parser.items(section):
                norm = key.strip().upper()
                if norm == "API_ID" and "API_ID" not in os.environ:
                    os.environ["API_ID"] = value.strip()
                elif norm == "API_HASH" and "API_HASH" not in os.environ:
                    os.environ["API_HASH"] = value.strip()


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

    # Диагностика: где искали конфиг и что видели
    env_report: list[str] = field(default_factory=list)

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
    """Читает .env (кандидаты: cwd, корень проекта, ~/.telegram-suite), затем config.ini.

    require_api=True — жёсткая проверка: без API_ID/API_HASH бросает ValueError.
    """
    report: list[str] = []
    _load_env_candidates(env_path, report)
    _load_ini_candidates(report)

    raw_id = os.getenv("API_ID")
    raw_hash = os.getenv("API_HASH")
    if not raw_id or not raw_hash:
        report.append("итог: API_ID/API_HASH не найдены; проверьте файл .env в каталоге проекта")

    settings = Settings(
        api_id=int(raw_id.strip()) if raw_id and raw_id.strip().isdigit() else None,
        api_hash=(raw_hash.strip() if raw_hash and raw_hash.strip() else None),
        sessions_dir=Path(os.getenv("SESSIONS_DIR", "./sessions")),
        proxies_file=Path(os.getenv("PROXIES_FILE", "./proxies.txt")),
        db_path=Path(os.getenv("DB_PATH", "./data/app.db")),
        min_delay_seconds=float(os.getenv("MIN_DELAY_SECONDS", "30")),
        max_delay_seconds=float(os.getenv("MAX_DELAY_SECONDS", "90")),
        max_concurrency=int(os.getenv("MAX_CONCURRENCY", "5")),
        retry_attempts=int(os.getenv("RETRY_ATTEMPTS", "3")),
        invite_daily_cap=int(os.getenv("INVITE_DAILY_CAP", "40")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        env_report=report,
    )
    settings.validate(require_api=require_api)
    return settings
