@echo off
rem Double click: builds Word + Excel report from examples\T001_ansys\project.yaml into folder out
rem First time only: pip install -r requirements.txt
python -m ansys_report all examples\T001_ansys\project.yaml -o out
echo.
echo Done. See folder out.
pause
