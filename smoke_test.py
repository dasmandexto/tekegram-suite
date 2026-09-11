"""Smoke-тесты: проверка, что фундамент и модули работоспособны.

Запуск:  python smoke_test.py
Не требует сети и реальных аккаунтов — только установленные зависимости.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ---- 1. Импорты ----
import core  # noqa: F401
import plugins  # noqa: F401
from config import load_settings
from core.context import Context
from core.proxies import Proxy, ProxyPool, parse_proxy_line
from core.rate_limiter import RateLimiter
from core.sessions import SessionPool
from plugins import PluginDeps, get_registry

FAILED: list[str] = []


def check(name: str, ok: bool, note: str = "") -> None:
    tag = "OK " if ok else "FAIL"
    print(f"[{tag}] {name} {note}")
    if not ok:
        FAILED.append(name)


# ---- 2. Конфиг ----
with tempfile.TemporaryDirectory() as td:
    env = Path(td) / ".env"
    env.write_text(
        "API_ID=12345\nAPI_HASH=abc\n"
        f"SESSIONS_DIR={td}/sessions\nDB_PATH={td}/data/app.db\n"
        "PROXIES_FILE=/nonexistent.txt\nMIN_DELAY_SECONDS=5\nMAX_DELAY_SECONDS=10\n",
        encoding="utf-8",
    )
    settings = load_settings(env)
    check("config: загрузка .env", settings.api_id == 12345 and settings.api_hash == "abc")
    check("config: создание каталогов", settings.sessions_dir.exists())

    # невалидные задержки ловятся
    import os
    os.environ["MIN_DELAY_SECONDS"] = "50"
    os.environ["MAX_DELAY_SECONDS"] = "10"
    try:
        load_settings(Path(td) / "none.env")
        check("config: валидация задержек", False)
    except ValueError:
        check("config: валидация задержек", True)
    # убираем за собой, чтобы не протекли в другие тесты
    os.environ.pop("MIN_DELAY_SECONDS", None)
    os.environ.pop("MAX_DELAY_SECONDS", None)

# ---- 3. Прокси ----
p1 = parse_proxy_line("socks5://user:pass@1.2.3.4:1080")
check("proxies: socks5 с логином", p1 is not None and p1.scheme == "socks5" and p1.username == "user")
p2 = parse_proxy_line("5.6.7.8:3128")
check("proxies: host:port", p2 is not None and p2.port == 3128)
check("proxies: Telethon-кортеж", p1.as_telethon() == ("socks5", "1.2.3.4", 1080, "user", "pass"))

# ---- 4. Rate limiter ----
rl = RateLimiter(0.001, 0.002)
rl.backoff("a", 5)  # флуд-заморозка аккаунта; остальные не блокируются
assert "a" in rl._last_action
check("rate_limiter: backoff", rl._last_action["a"] > 0)

# ---- 5. Storage + дедуп ----
with tempfile.TemporaryDirectory() as td:
    from core.storage import Storage

    st = Storage(Path(td) / "app.db")
    st.set_account_status("acc1", "alive", "ok")
    check("storage: статус аккаунта", st.account_status("acc1")["status"] == "alive")
    st.mark_sent("acc1", "@user1")
    check("storage: дедуп (уже писал)", st.is_sent("acc1", "@user1"))
    left = st.unseen_users("acc1", ["@user1", "@user2"])
    check("storage: unseen_users фильтрует", left == ["@user2"])
    st.mark_sent("acc1", "@user1", module="parser")
    check("storage: дедуп раздельный по модулям", st.is_sent("acc1", "@user1", "parser"))
    st.log_event("test", "info", "hello")
    st.close()
    check("storage: sqlite создаётся", Path(td, "app.db").exists())

# ---- 6. Реестр плагинов ----
reg = get_registry()
reg.auto_discover()
names = reg.names()
check("registry: найден checker", "checker" in names, f"(модули: {', '.join(names)})")

# ---- 7. Контекст + инстанцирование плагина ----
with tempfile.TemporaryDirectory() as td:
    fake = Path(td) / ".env"
    fake.write_text(f"SESSIONS_DIR={td}/sessions\nDB_PATH={td}/data/app.db\n", encoding="utf-8")
    ctx = Context(load_settings(fake))
    check("context: сессий 0", ctx.sessions.count == 0)
    deps = PluginDeps(
        storage=ctx.storage,
        rate_limiter=ctx.rate_limiter,
        proxies=ctx.proxies,
        sessions=ctx.sessions,
        api_id=1,
        api_hash="x",
    )
    plugin = reg.instantiate("checker", deps)
    check("registry: инстанцирован checker", plugin.name == "checker")
    ctx.close()

# ---- 8. Поведение без API-кредов ----
with tempfile.TemporaryDirectory() as td:
    env = Path(td) / ".env"
    env.write_text(f"SESSIONS_DIR={td}/sessions\nDB_PATH={td}/data/app.db\n", encoding="utf-8")
    deps_empty = PluginDeps(Storage(Path(td) / "app.db"), RateLimiter(1, 2), ProxyPool(), SessionPool(load_settings(env)), None, None)
    from plugins.checker import CheckerPlugin

    try:
        CheckerPlugin(deps_empty)
        check("checker: требует API-креды", False)
    except ValueError:
        check("checker: требует API-креды", True)

print()
if FAILED:
    print(f"SMOKE: провалено: {FAILED}")
    sys.exit(1)
print(f"SMOKE: все проверки пройдены ({len(dir())})")
sys.exit(0)
