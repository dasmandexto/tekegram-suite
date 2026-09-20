"""Модуль: Регистратор — регистрация ОДНОГО аккаунта на ваш номер (каркас).

Назначение: интерактивно зарегистрировать новый аккаунт Telegram на номер,
которым ВЫ владеете (ввод кода вручную). Это НЕ ферма аккаунтов:

НЕ РЕАЛИЗОВАНО (намеренно): интеграции с SMS-активаторами, обход капч,
массовая регистрация. Регистрация аккаунтов на чужие номера и массовая
ферма нарушают правила Telegram — модуль лишь упрощает легальную
регистрацию своих аккаунтов и стартовую настройку профиля.

После регистрации профиль настраивается (имя/фамилия/био) и сессия
сохраняется в SESSIONS_DIR под именем --name.

Запуск:
    python -m cli registrator --name acc5 --phone +79991234567 \
        --first-name Иван --last-name Иванов --bio "Менеджер"
Код придёт в Telegram/ SMS на этот номер — введите его в консоли.
"""
from __future__ import annotations

import argparse
import logging

from telethon import functions
from telethon.errors import (
    FloodWaitError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from .base import PluginDeps, PluginProtocol

log = logging.getLogger(__name__)

MODULE = "registrator"


class RegistratorPlugin(PluginProtocol):
    name = MODULE
    description = "Интерактивная регистрация ОДНОГО аккаунта (свой номер, ручной ввод кода)"

    def _parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(prog="tg-suite registrator", description=self.description)
        p.add_argument("--name", required=True, help="имя файла сессии (например acc5)")
        p.add_argument("--phone", required=True, help="ваш номер в E.164 (+7999...)")
        p.add_argument("--first-name", required=True, help="имя профиля")
        p.add_argument("--last-name", default=None, help="фамилия (опционально)")
        p.add_argument("--bio", default=None, help="био профиля (опционально)")
        return p

    async def run(self, args: list[str]) -> None:
        ns = self._parser().parse_args(args)

        if not self.deps.api_id or not self.deps.api_hash:
            raise ValueError("Нужны API_ID и API_HASH (my.telegram.org)")
        if ns.name in self.deps.sessions.list_session_names():
            raise ValueError(f"Сессия '{ns.name}' уже существует — выберите другое имя")

        client = self.deps.sessions.build_client(
            ns.name, self.deps.api_id, self.deps.api_hash,
            self.deps.proxies.get_for(0),
        )
        try:
            await client.connect()
            try:
                await client.start(phone=ns.phone)  # интерактивный ввод кода
            except SessionPasswordNeededError as exc:
                raise ValueError(
                    "Номер уже привязан к аккаунту с 2FA: используйте checker/profiler, а не регистратор"
                ) from exc
            except PhoneNumberInvalidError as exc:
                raise ValueError(f"Некорректный номер: {ns.phone}") from exc
            except FloodWaitError as exc:
                self.deps.rate_limiter.backoff(ns.name, exc.seconds)
                raise ValueError(f"Флуд-лимит от Telegram: подождите {exc.seconds} c") from exc

            me = await client.get_me()
            if me is None:
                raise ValueError("Не удалось получить профиль после регистрации")

            await client(functions.account.UpdateProfileRequest(
                first_name=ns.first_name,
                last_name=ns.last_name,
                about=ns.bio,
            ))
            self.deps.storage.set_account_status(ns.name, "alive", "только что зарегистрирован")
            self.deps.storage.log_event(MODULE, "info", f"зарегистрирован {ns.name} ({ns.phone})")
            log.info("Аккаунт %s зарегистрирован, профиль настроен. Сессия: sessions/%s.session", ns.name, ns.name)
        finally:
            await client.disconnect()
