@echo off
chcp 65001 >nul
rem Двойной щелчок: собирает отчёт Word и Excel из examples\T001_ansys\project.yaml в папку out
rem Перед первым запуском: pip install -r requirements.txt
python -m ansys_report all examples\T001_ansys\project.yaml -o out
echo.
echo Готово. Файлы в папке out.
pause
