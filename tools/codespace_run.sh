#!/usr/bin/env bash
# Запуск сайта в GitHub Codespaces: публичный адрес порта подставляется автоматически.
set -e
cd "$(dirname "$0")/.."
if [ -n "$CODESPACE_NAME" ]; then
  export ASR_BASE_URL="https://${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  echo "Адрес сайта: $ASR_BASE_URL (порт 8000 должен быть Public: вкладка «Ports» → правой кнопкой → Port Visibility → Public)"
fi
export ASR_HOST=0.0.0.0
exec python -m server
