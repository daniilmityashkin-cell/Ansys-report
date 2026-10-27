@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Сначала один раз запустите start_site.bat: он подготовит окружение.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
echo Проверка совместимости с установленным Ansys (1-3 минуты, окно Ansys не показывается)...
python -m ansys_report check-ansys %*
echo.
echo Результат: C:\ansys_report_work\probe_api_<версия>.txt  - пришлите этот файл разработчику.
pause
