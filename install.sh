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
  git fetch --depth 1 origin main
  # Локальные правки отслеживаемых файлов (README и т.п.) затираем,
  # но .env, sessions/ и data/ не отслеживаются и остаются нетронутыми.
  git reset --hard origin/main
  git clean -qfd -e .env -e sessions -e data -e .venv
else
  echo "Клонирую $REPO_URL ..."
  git clone --depth 1 "$REPO_URL" "$DIR"
  cd "$DIR"
fi

echo "==> Виртуальное окружение"
# На Debian/Ubuntu команда 'python' часто отсутствует — используем python3.
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  command -v python3 >/dev/null 2>&1 || { echo "ОШИБКА: не найден python3. Установите: apt-get install -y python3 python3-venv" >&2; exit 1; }
  PYTHON=python3
fi
$PYTHON -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Зависимости"
pip install --upgrade pip -q
pip install -q -r requirements.txt

echo "==> Настройка"
[ -f .env ] || cp .env.example .env
mkdir -p sessions data

echo
echo "Готово! Дальше (не копируйте этот текст целиком — выполняйте по одной команде):"
echo "  1) nano .env   # впишите API_ID / API_HASH (my.telegram.org → API development tools)"
echo "  2) положите сессии в sessions/ (по одному *.session на аккаунт)"
echo "  3) запуск (всегда через .venv/bin/python или после 'source .venv/bin/activate'):"
echo "     .venv/bin/python -m cli --list"
echo "     .venv/bin/python -m cli checker"
echo "     .venv/bin/python -m cli web      # веб-интерфейс: http://127.0.0.1:8000"
