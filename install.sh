#!/usr/bin/env bash
# Telegram Suite — однострочный установщик.
#
# Из GitHub:
#   curl -sSL https://raw.githubusercontent.com/USER/telegram-suite/main/install.sh | bash
# Или локально (из каталога проекта):
#   bash install.sh
set -euo pipefail

REPO_URL="${1:-https://github.com/USER/telegram-suite.git}"
DIR="${2:-telegram-suite}"

echo "==> Telegram Suite: установка"

if [ -d "$DIR/.git" ]; then
  echo "Каталог $DIR уже есть — обновляю..."
  cd "$DIR"
  git pull --ff-only
else
  echo "Клонирую $REPO_URL ..."
  git clone --depth 1 "$REPO_URL" "$DIR"
  cd "$DIR"
fi

echo "==> Виртуальное окружение"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Зависимости"
pip install --upgrade pip -q
pip install -q -r requirements.txt

echo "==> Настройка"
[ -f .env ] || cp .env.example .env
mkdir -p sessions data

echo
echo "Готово! Дальше:"
echo "  1) откройте .env и впишите API_ID / API_HASH (my.telegram.org → API development tools)"
echo "  2) положите сессии в sessions/ (по одному *.session на аккаунт)"
echo "  3) запуск:"
echo "     .venv/bin/python -m cli --list"
echo "     .venv/bin/python -m cli checker"
echo "     .venv/bin/python -m cli web      # веб-интерфейс: http://127.0.0.1:8000"
