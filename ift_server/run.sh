#!/usr/bin/env bash
# Автозапуск ИФТ-рассылки (для ручного старта и Cron на Linux).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

mkdir -p logs downloads

if [[ -x "$ROOT/venv/bin/python" ]]; then
  PYTHON="$ROOT/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  echo "Не найден Python (venv/bin/python или python3)" >&2
  exit 1
fi

exec "$PYTHON" "$ROOT/main.py"
