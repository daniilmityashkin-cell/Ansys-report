@echo off
rem Сайт для разработки: сам перезапускается при правке кода (python), шаблоны и стили подхватываются при обновлении страницы.
cd /d "%~dp0"
set ASR_PORT=8000
python -m uvicorn server.wsgi:app --host 127.0.0.1 --port 8000 --reload --reload-dir server --reload-dir ansys_report
