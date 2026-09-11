"""FastAPI-приложение: веб-обёртка над модулями (checker, broadcast).

Один Context создаётся на старте приложения и переиспользуется всеми
запросами (SQLite, пул прокси, rate limiter). Долгие операции (чекер,
рассылка) запускаются в фоне через asyncio.create_task, статус — в /api/tasks.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import Settings
from core import Context
from plugins import PluginDeps, get_registry

log = logging.getLogger(__name__)

_tasks: dict[str, dict] = {}


def _build_deps(ctx: Context, settings: Settings) -> PluginDeps:
    return PluginDeps(
        storage=ctx.storage,
        rate_limiter=ctx.rate_limiter,
        proxies=ctx.proxies,
        sessions=ctx.sessions,
        api_id=settings.api_id,
        api_hash=settings.api_hash,
    )


def create_app(settings: Settings) -> FastAPI:
    ctx = Context(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        ctx.close()

    app = FastAPI(title="Telegram Suite Web", lifespan=lifespan)
    registry = get_registry()
    registry.auto_discover()

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ---------------- страница ----------------
    @app.get("/")
    async def index():
        return FileResponse(str(static_dir / "index.html"))

    # ---------------- обзор ----------------
    @app.get("/api/overview")
    async def overview():
        modules = [
            {"name": n, "description": registry.get(n).description}
            for n in registry.names()
        ]
        accounts = []
        for name in ctx.sessions.list_session_names():
            st = ctx.storage.account_status(name)
            accounts.append(
                {
                    "name": name,
                    "status": st["status"] if st else "unknown",
                    "detail": st["detail"] if st else None,
                }
            )
        events = ctx.storage.recent_events(limit=50)
        return {
            "modules": modules,
            "accounts": accounts,
            "events": events,
            "api_id_set": bool(settings.api_id),
        }

    # ---------------- чекер ----------------
    @app.post("/api/checker")
    async def run_checker():
        if not settings.api_id or not settings.api_hash:
            raise HTTPException(400, "нужны API_ID и API_HASH (my.telegram.org)")
        names = ctx.sessions.list_session_names()
        if not names:
            raise HTTPException(400, "нет сессий в каталоге sessions/")
        task_id = uuid.uuid4().hex[:8]
        _tasks[task_id] = {"status": "running", "type": "checker", "total": len(names)}
        plugin = registry.instantiate("checker", _build_deps(ctx, settings))

        async def work():
            try:
                await plugin.check(names, plugin._on_result)
                _tasks[task_id]["status"] = "done"
            except Exception as exc:  # noqa: BLE001
                _tasks[task_id].update(status="error", error=str(exc))

        asyncio.create_task(work())
        return {"task_id": task_id}

    # ---------------- broadcast ----------------
    def _broadcast_plugin():
        return registry.instantiate("broadcast", _build_deps(ctx, settings))

    def _optin_list(plugin):
        try:
            subs = plugin._load_subscribers()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        optout = plugin._load_optout()
        return [s for s in subs if s[0] not in optout]

    @app.get("/api/broadcast/state")
    async def broadcast_state():
        plugin = _broadcast_plugin()
        try:
            subs = plugin._load_subscribers()
        except ValueError as exc:
            return {"subscribers": [], "optout": sorted(plugin._load_optout()), "error": str(exc)}
        return {
            "subscribers": [{"key": k, "consent": c, "source": s} for k, c, s in subs],
            "optout": sorted(plugin._load_optout()),
        }

    @app.post("/api/broadcast/preview")
    async def broadcast_preview(payload: dict):
        message = (payload.get("message") or "").strip()
        if not message:
            raise HTTPException(400, "укажите текст сообщения")
        subs = _optin_list(_broadcast_plugin())
        return {
            "count": len(subs),
            "recipients": [{"key": k, "consent": c, "source": s} for k, c, s in subs[:200]],
        }

    @app.post("/api/broadcast/send")
    async def broadcast_send(payload: dict):
        message = (payload.get("message") or "").strip()
        if not message:
            raise HTTPException(400, "укажите текст сообщения")
        if not settings.api_id or not settings.api_hash:
            raise HTTPException(400, "для отправки нужны API_ID и API_HASH")
        names = ctx.sessions.list_session_names()
        if not names:
            raise HTTPException(400, "нет сессий в каталоге sessions/")
        plugin = _broadcast_plugin()
        subs = _optin_list(plugin)
        if not subs:
            raise HTTPException(400, "некому отправлять (после opt-in/opt-out фильтров)")

        task_id = uuid.uuid4().hex[:8]
        _tasks[task_id] = {"status": "running", "type": "broadcast", "total": len(subs)}

        async def work():
            try:
                await plugin._dispatch(names, subs, message)
                _tasks[task_id]["status"] = "done"
            except Exception as exc:  # noqa: BLE001
                _tasks[task_id].update(status="error", error=str(exc))

        asyncio.create_task(work())
        return {"task_id": task_id, "recipients": len(subs)}

    @app.post("/api/broadcast/unsubscribe")
    async def broadcast_unsubscribe(payload: dict):
        key = (payload.get("key") or "").strip()
        if not key:
            raise HTTPException(400, "укажите адресата")
        _broadcast_plugin()._add_optout(key)
        return {"ok": True}

    # ---------------- спинтакс --------------
    @app.post("/api/spintax/preview")
    async def spintax_preview(payload: dict):
        from core import spintax

        text = (payload.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "пустой текст")
        if not spintax.has_spintax(text):
            return {"has_spintax": False, "combinations": 1, "sample": [text]}
        try:
            combos = spintax.count_combinations(text)
        except spintax.SpintaxError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "has_spintax": True,
            "combinations": combos,
            "sample": spintax.sample_variants(text, 5),
        }

    # ---------------- задачи ----------------
    @app.get("/api/tasks/{task_id}")
    async def task_status(task_id: str):
        task = _tasks.get(task_id)
        if not task:
            raise HTTPException(404, "задача не найдена")
        return task

    return app
