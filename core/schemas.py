"""Единые схемы настроек модулей (в стиле TeleRaptor: у каждого модуля
свой набор полей — потоки/задержки/лимиты/тексты, общие и персональные).

Схемы используются веб-интерфейсом для авто-генерации форм настроек
и единым рантаймом (/api/run/{module}) для сборки argv.

Структура модуля в словаре:
    fields     — поля формы: {key, label, type, default, ...}
                 type: text | textarea | number | bool | select
    positional — какие key идут в argv позиционно (без флага)
    send_flag  — имя булевого флага реального запуска (dry-run по умолчанию)
    api_required — нужен ли API_ID/API_HASH
    interactive  — требует ручного ввода в консоли (запуск только через CLI)
"""
from __future__ import annotations

MODULE_SCHEMAS: dict[str, dict] = {
    "checker": {
        "fields": [
            {"key": "account", "label": "Аккаунт (пусто = все)", "type": "text", "default": ""},
        ],
        "positional": ["account"],
        "send_flag": None,
        "api_required": True,
    },
    "broadcast": {
        "fields": [
            {"key": "message", "label": "Текст сообщения ({username}, спинтакс {а|б})",
             "type": "textarea", "default": "", "required": True, "placeholder": "Привет, {username}! {Выпуск|Пост} готов."},
            {"key": "limit", "label": "Лимит адресатов за запуск (0 = все)", "type": "number", "default": 0},
            {"key": "recipient", "label": "Только одному адресату (пусто = всем opt-in)", "type": "text", "default": ""},
        ],
        "positional": ["message"],
        "send_flag": "send",
        "api_required": True,
    },
    "parser": {
        "fields": [
            {"key": "source", "label": "Источник (@канал или ссылка)", "type": "text", "default": "", "required": True},
            {"key": "mode", "label": "Режим", "type": "select", "default": "members",
             "options": [("members", "Участники"), ("activity", "Активность (авторы сообщений)")]},
            {"key": "limit", "label": "Лимит пользователей (0 = сколько дадут)", "type": "number", "default": 200},
            {"key": "output", "label": "Файл результата (пусто = data/parsed_...)", "type": "text", "default": ""},
        ],
        "positional": ["source"],
        "send_flag": None,
        "api_required": True,
    },
    "inviter": {
        "fields": [
            {"key": "target", "label": "Цель (@чат или ссылка)", "type": "text", "default": "", "required": True},
            {"key": "file", "label": "Файл списка (формат парсера)", "type": "text", "default": "", "required": True},
            {"key": "limit", "label": "Лимит приглашений за запуск (0 = все)", "type": "number", "default": 0},
        ],
        "positional": ["target"],
        "send_flag": "send",
        "api_required": True,
    },
    "cloner": {
        "fields": [
            {"key": "source", "label": "Источник (@чат или ссылка)", "type": "text", "default": "", "required": True},
            {"key": "target", "label": "Цель (@чат или ссылка)", "type": "text", "default": "", "required": True},
            {"key": "history", "label": "Сколько сообщений копировать", "type": "number", "default": 100},
            {"key": "replace", "label": "Замена 'старое=новое'", "type": "text", "default": ""},
            {"key": "no_media", "label": "Без медиа", "type": "bool", "default": False},
            {"key": "no_meta", "label": "Не трогать название/аватар", "type": "bool", "default": False},
        ],
        "positional": ["source", "target"],
        "send_flag": "send",
        "api_required": True,
    },
    "autoresponder": {
        "fields": [
            {"key": "rules", "label": "Файл правил (пусто = data/autoresponder.txt)", "type": "text", "default": ""},
            {"key": "cooldown", "label": "Кулдаун на диалог, сек", "type": "number", "default": 3600},
            {"key": "duration", "label": "Время работы, сек (0 = до остановки)", "type": "number", "default": 3600},
            {"key": "chat", "label": "Доп. чат для ответов (пусто = только ЛС)", "type": "text", "default": ""},
        ],
        "positional": [],
        "send_flag": None,
        "api_required": True,
    },
    "phonechecker": {
        "fields": [
            {"key": "file", "label": "Файл номеров (по одному в строке)", "type": "text", "default": "", "required": True},
            {"key": "batch", "label": "Номеров за запрос (макс. 200)", "type": "number", "default": 100},
            {"key": "limit", "label": "Лимит номеров за запуск (0 = все)", "type": "number", "default": 0},
        ],
        "positional": [],
        "send_flag": None,
        "api_required": True,
    },
    "profiler": {
        "fields": [
            {"key": "file", "label": "Файл профилей (пусто = data/profiles.txt)", "type": "text", "default": ""},
            {"key": "avatar_dir", "label": "Каталог аватаров", "type": "text", "default": "avatars"},
        ],
        "positional": [],
        "send_flag": "send",
        "api_required": True,
    },
    "tdata2session": {
        "fields": [
            {"key": "src", "label": "Корень с tdata", "type": "text", "default": "", "required": True},
            {"key": "out", "label": "Каталог для *.session (пусто = sessions/)", "type": "text", "default": ""},
        ],
        "positional": [],
        "send_flag": None,
        "api_required": False,
    },
    "reporter": {
        "fields": [
            {"key": "file", "label": "Файл целей (пусто = data/report_targets.txt)", "type": "text", "default": ""},
            {"key": "reason", "label": "Причина", "type": "select", "default": "spam",
             "options": [("spam", "Спам"), ("violence", "Насилие"), ("childabuse", "Вред детям"),
                          ("pornography", "Порнография"), ("copyright", "Нарушение авторских прав"), ("other", "Другое")]},
            {"key": "comment", "label": "Комментарий", "type": "text", "default": ""},
            {"key": "limit", "label": "Лимит целей за запуск (макс. 25)", "type": "number", "default": 0},
        ],
        "positional": [],
        "send_flag": "send",
        "api_required": True,
    },
    "booster": {
        "fields": [
            {"key": "post", "label": "Ссылка на свой пост (t.me/<канал>/<id>)", "type": "text", "default": "", "required": True},
            {"key": "limit", "label": "Аккаунтов-просмотров (макс. 200)", "type": "number", "default": 0},
            {"key": "reaction", "label": "Реакция (эмодзи, опционально)", "type": "text", "default": ""},
        ],
        "positional": ["post"],
        "send_flag": "send",
        "api_required": True,
    },
    "registrator": {
        "fields": [
            {"key": "name", "label": "Имя сессии", "type": "text", "default": "", "required": True},
            {"key": "phone", "label": "Ваш номер (E.164)", "type": "text", "default": "", "required": True},
            {"key": "first_name", "label": "Имя", "type": "text", "default": "", "required": True},
            {"key": "last_name", "label": "Фамилия", "type": "text", "default": ""},
            {"key": "bio", "label": "Био", "type": "text", "default": ""},
        ],
        "positional": [],
        "send_flag": None,
        "api_required": True,
        "interactive": True,  # ручной ввод кода — только через CLI
    },
}

def build_argv(schema: dict, values: dict) -> tuple[list[str], bool]:
    """Собирает argv для CLI-плагина из значений формы (схема -> аргументы).

    Возвращает (argv, real_run): real_run=True, если передан send_flag.
    Позиционные поля идут без флага, bool=True — как голый флаг (дефисы:
    no_media -> --no-media), значения, равные default, не тащатся в argv
    (плагин возьмёт тот же default). Бросает ValueError при незаполненном
    обязательном поле.
    """
    send_flag = schema.get("send_flag")
    real = bool(values.get(send_flag)) if send_flag else False
    positional = set(schema.get("positional", []))
    argv: list[str] = []
    for field in schema["fields"]:
        key = field["key"]
        if key == send_flag:
            continue
        val = values.get(key, field.get("default"))
        if val in (None, "", False):
            if field.get("required"):
                raise ValueError(f"Заполните поле: {field['label']}")
            continue
        if key in positional:
            argv.append(str(val))
        elif field["type"] == "bool":
            argv.append(f"--{key.replace('_', '-')}")
        elif not field.get("required") and val == field.get("default"):
            continue  # значение = default: плагин применит то же самое
        else:
            argv += [f"--{key.replace('_', '-')}", str(val)]
    if send_flag and real:
        argv.append(f"--{send_flag}")
    return argv, real


def validate_schema_module(name: str, schema: dict) -> list[str]:
    """Проверка схемы: возвращает список проблем (пустой = ОК)."""
    problems: list[str] = []
    if not schema.get("fields"):
        problems.append(f"{name}: нет полей")
    keys = [f["key"] for f in schema.get("fields", [])]
    if len(keys) != len(set(keys)):
        problems.append(f"{name}: дубли полей")
    for key in schema.get("positional", []):
        if key not in keys:
            problems.append(f"{name}: positional '{key}' нет в fields")
    # send_flag — служебный флаг реального запуска, в fields его сознательно нет
    for f in schema.get("fields", []):
        if f["type"] == "select" and not f.get("options"):
            problems.append(f"{name}: select '{f['key']}' без options")
    return problems


__all__ = ["MODULE_SCHEMAS", "build_argv", "validate_schema_module"]
