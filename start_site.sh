#!/usr/bin/env bash
# Запуск сайта для проверки (Linux/macOS): ./start_site.sh  ->  http://127.0.0.1:8000
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Нужен Python 3.12 или 3.13"; exit 1; }
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
grep -vi cadquery requirements-server.txt > .req_tmp.txt
python -m pip install -q -r .req_tmp.txt || { echo "Не удалось установить пакеты"; rm -f .req_tmp.txt; exit 1; }
rm -f .req_tmp.txt
python -m pip install -q cadquery-ocp || echo "(CAD-библиотека не установилась: полная STEP-модель недоступна, остальное работает)"
export ASR_FIRST_FREE=1 ASR_MAX_REG_PER_IP=100 ASR_BASE_URL=http://127.0.0.1:8000
echo "Сайт: http://127.0.0.1:8000  (остановить: Ctrl+C)"
python -m server
