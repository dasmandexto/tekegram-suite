# Telegram Suite — модульный набор инструментов для Telegram

Проектирование по мотивам сервиса **TeleRaptor** (try.teleraptor.ru): рассылки,
парсинг, инвайтинг, автоматизация. Архитектура модульная: каждый модуль —
отдельный файл в `plugins/`, подключается автоматически через реестр.
Есть консольный интерфейс и веб-интерфейс (по аналогии с «Телераптор Веб»).

> ⚠️ **Важно.** Модуль рассылки (`broadcast`) работает **только по подписчикам
> с явным согласием (opt-in)**. Массовые рассылки без согласия нарушают правила
> Telegram и ведут к блокировке аккаунтов. Используйте инструменты в рамках
> закона вашей юрисдикции.

## Возможности

- **checker** — проверка аккаунтов: жив / бан / спамблок (ничего не отправляет).
- **broadcast** — рассылка по opt-in подписчикам: dry-run по умолчанию, opt-out,
  дедуп «без пересечений» (аккаунт не пишет одному адресату дважды), случайные
  паузы, авто-заморозка аккаунта при флуд-лимите, **спинтакс**.
- **спинтакс** — `{вариант1|вариант2}`: каждый получатель получает случайный
  вариант; поддерживаются вложенность (`{привет|здравствуйте, {друг|приятель}}`)
  и экранирование `\{`. Количество комбинаций проверяется до отправки, в вебе
  есть кнопка «Спинтакс: варианты» для предпросмотра.
- **web** — локальный веб-интерфейс в браузере (FastAPI + uvicorn).
- Каркас для новых модулей: парсер, инвайтер, клонер чатов, автоответчик и т.д.

## Установка

Вариант А — из Git-репозитория (после публикации на GitHub):

```bash
curl -sSL https://raw.githubusercontent.com/USER/telegram-suite/main/install.sh | bash
```

Вариант Б — из архива / вручную:

```bash
git clone https://github.com/USER/telegram-suite.git   # или распаковать архив
cd telegram-suite
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # вписать API_ID, API_HASH (my.telegram.org → API tools)
mkdir -p sessions data          # сессии: по одному *.session на аккаунт
```

## Использование

```bash
python -m cli --list                       # доступные модули
python -m cli --sessions                   # аккаунты со статусами
python -m cli checker                      # проверить все аккаунты
python -m cli broadcast "Текст {username}" # dry-run: план, ничего не шлёт
python -m cli broadcast --send "Текст"     # реальная отправка (только opt-in)
python -m cli web                          # веб-интерфейс → http://127.0.0.1:8000
```

### Веб-интерфейс (аналог «Телераптор Веб»)

`python -m cli web` (или `python -m web`) поднимает локальный сервер;
открывается в браузере по адресу `http://127.0.0.1:8000`. На одной странице:

- список модулей и **статусы аккаунтов** (из чекера);
- кнопка **«Проверить аккаунты»** — запускает чекер в фоне;
- **рассылка**: текст (можно `{username}` и спинтакс), кнопка
  «Предпросмотр (dry-run)» с числом и списком получателей, кнопка
  «Спинтакс: варианты» (число комбинаций и примеры), кнопка «Отправить»
  (после подтверждения);
- список **подписчиков (opt-in)** и **opt-out** с добавлением в один клик;
- **журнал событий** (кто → кому → когда).

API (JSON) — те же функции, что и у CLI: `/api/overview`, `/api/checker`,
`/api/broadcast/state`, `/api/broadcast/preview`, `/api/broadcast/send`,
`/api/broadcast/unsubscribe`, `/api/spintax/preview`,
`/api/tasks/{id}` (статус фоновой задачи).

### Рассадка по подписчикам (opt-in)

Адресаты — `data/subscribers.txt`, строка = `key|YYYY-MM-DD|source`
(`key` = `@username` или user_id, `YYYY-MM-DD` — **дата согласия**, `source` —
источник). Строки без даты согласия отбрасываются и логируются; сырые списки
участников групп/каналов модуль не принимает. `data/optout.txt` исключается
всегда. Добавить в opt-out: `python -m cli broadcast --unsubscribe @user`.

## Структура

```
telegram-suite/
├── config/            # настройки из .env (dataclass Settings + валидация)
├── core/              # инфраструктура: storage, rate_limiter, proxies, sessions, context
├── plugins/           # модули: base, registry, checker.py, broadcast.py
├── web/               # веб-интерфейс: app.py (FastAPI), server.py, static/
├── cli/               # консольная точка входа (python -m cli ...)
├── install.sh         # однострочный установщик
├── smoke_test.py      # smoke-тесты (без сети)
├── .env.example, requirements.txt, README.md, LICENSE, .gitignore
```

## Как добавить новый модуль

1. Создать `plugins/<module>.py` (наследовать `PluginProtocol`, задать `name`,
   `description`, реализовать `run(args)`).
2. Готово — реестр подхватит модуль автоматически: `python -m cli <name>`.
3. Для веб-интерфейса добавить эндпоинт в `web/app.py`.

Плагин получает только `PluginDeps` (storage, rate_limiter, proxies, sessions,
api_id, api_hash) — вся инфраструктура уже готова.

## Карта модулей TeleRaptor → статус в проекте

| Модуль TeleRaptor            | Статус                       |
|------------------------------|------------------------------|
| Чекер аккаунтов              | `plugins/checker.py` — готов |
| Рассылка в ЛС (opt-in)       | `plugins/broadcast.py` — готов |
| Веб-интерфейс                | `web/` — готов               |
| Парсер аудитории             | `plugins/parser.py` — TODO   |
| Инвайтер                     | `plugins/inviter.py` — TODO  |
| Клонер чатов                 | `plugins/cloner.py` — TODO   |
| Автоответчик                 | `plugins/autoresponder.py` — TODO |
| Заполнение профилей          | `plugins/profiler.py` — TODO |
| Чекер номеров                | TODO                         |
| Конвертер tdata → session    | TODO                         |

## Публикация на GitHub

Скрипт `install.sh` обращается к `github.com/USER/telegram-suite` — замените
`USER` на ваш логин (в install.sh и в команде ниже). Команды для публикации:

```bash
cd telegram-suite
git init
git add -A
git commit -m "Telegram Suite: CLI + web + broadcast (opt-in) + installer"
git branch -M main
git remote add origin https://github.com/USER/telegram-suite.git
git push -u origin main
```

Секреты уже исключены через `.gitignore` (`.env`, `*.session`, `data/`, `sessions/`).

## Лицензия

MIT (см. `LICENSE`).
