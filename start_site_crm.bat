@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo  ANSYS REPORT: сайт + CRM + расчётный сервер Ansys на этом компьютере
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
python -m pip install -q -r requirements-server.txt
rem первый запуск CRM: вход администратора (без скобок в блоке if - cmd их не любит)
if exist crm_data\crm.db goto crm_ready
echo.
echo Первый запуск CRM: задайте вход администратора.
set /p CRMMAIL=Почта администратора CRM: 
set /p CRMPASS=Пароль, не короче 8 символов: 
python -m crm adduser "%CRMMAIL%" "%CRMPASS%" admin
:crm_ready
rem CRM в отдельном окне, порт 8100 (доступна и с телефона в той же Wi-Fi)
start "CRM ANSYS REPORT" cmd /k "set CRM_HOST=0.0.0.0&& set CRM_SITE_URL=http://127.0.0.1:8000&& .venv\Scripts\python -m crm"
for /f "usebackq delims=" %%t in ("crm_data\api_token.txt") do set ASR_CRM_TOKEN=%%t
rem расчётный сервер: на время разработки - этот компьютер (Ansys здесь); берёт заказы из очереди сайта
if not exist server_data mkdir server_data
python -c "from server.config import Settings; Settings()" >nul
for /f "usebackq delims=" %%w in ("server_data\worker_token.txt") do set ASR_WORKER_TOKEN=%%w
start "Расчётный сервер Ansys" /min cmd /k ".venv\Scripts\python -m ansys_report worker --server http://127.0.0.1:8000 --token %ASR_WORKER_TOKEN%"
set ASR_CRM_URL=http://127.0.0.1:8100
set ASR_HOST=0.0.0.0
set ASR_MAX_REG_PER_IP=100
echo.
echo Сайт: http://127.0.0.1:8000     CRM: http://127.0.0.1:8100
echo С телефона в той же Wi-Fi: http://АДРЕС_КОМПЬЮТЕРА:8000 и :8100, адрес - команда ipconfig, строка IPv4
start "" http://127.0.0.1:8100
python -m server
pause
