@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Сначала один раз запустите start_site.bat: он подготовит окружение.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m ansys_report agent --install
echo.
echo Готово. Теперь кнопка "Собрать отчёт в Ansys" на сайте запускает расчёт на этом компьютере (без окон консоли).
echo Нужны: Ansys Mechanical 2026 R1 (переменная AWP_ROOT261) и свободная лицензия Mechanical.
pause
