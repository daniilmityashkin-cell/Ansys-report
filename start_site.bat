@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo  ANSYS REPORT: запуск сайта для проверки
echo ================================================
where python >nul 2>nul
if errorlevel 1 (
  echo Python не найден. Установите Python 3.12 или 3.13 с python.org и поставьте галочку "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist .venv (
  echo Создаю окружение, 1-2 минуты, только в первый раз...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
echo Устанавливаю пакеты, в первый раз 2-5 минут...
findstr /v /i "cadquery" requirements-server.txt > .req_tmp.txt
python -m pip install -q -r .req_tmp.txt
if errorlevel 1 (
  echo Не удалось установить пакеты. Проверьте интернет и повторите запуск.
  del .req_tmp.txt
  pause
  exit /b 1
)
del .req_tmp.txt
python -m pip install -q cadquery-ocp || echo (CAD-библиотека не установилась: полная STEP-модель недоступна, остальное работает)
set ASR_FIRST_FREE=1
set ASR_MAX_REG_PER_IP=100
set ASR_BASE_URL=http://127.0.0.1:8000
echo.
echo Сайт: http://127.0.0.1:8000   (закрыть: Ctrl+C или закройте это окно)
echo Зарегистрируйтесь с любой почтой и паролем (данные только на этом компьютере).
start "" cmd /c "timeout /t 5 >nul & start http://127.0.0.1:8000"
python -m server
pause
