"""Пакет «Открыть в Ansys»: заказчик запускает Open_in_Ansys.bat - Workbench собирает проект из STEP (материал, толщины, сетка), накладывает нагрузки
и остаётся открытым. Работает на компьютере заказчика, с его установкой Ansys. Имена файлов - только латиницей (Workbench не любит кириллицу в путях)."""
from __future__ import annotations
import json
import shutil
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "ansys_scripts"
VERSIONS = [261, 252, 251, 242, 241, 232, 231]

JOURNAL = '''# -*- coding: utf-8 -*-
# Журнал Workbench: проект Static Structural из STEP, сетка, нагрузки. Запуск: RunWB2.exe -R build_model.wbjn (переменная AR_PKG - папка пакета).
import os, traceback
pkg = os.environ["AR_PKG"]
status = os.path.join(pkg, "out", "wb_status.txt")
if not os.path.isdir(os.path.dirname(status)):
    os.makedirs(os.path.dirname(status))
def st(m):
    f = open(status, "a")
    f.write(m + "\\n")
    f.close()
st("START")
try:
    template1 = None
    for kw in ({"TemplateName": "Static Structural", "Solver": "ANSYS"},
               {"TemplateName": "Static Structural", "Solver": "Mechanical"},
               {"TemplateName": "Static Structural"},
               {"TemplateName": "Static Structural (ANSYS)"},
               {"TemplateName": "Static Structural (Samcef)"}):
        try:
            template1 = GetTemplate(**kw)
            st("TEMPLATE OK: " + repr(kw))
            break
        except:
            st("TEMPLATE FAIL " + repr(kw) + ": " + traceback.format_exc().splitlines()[-1])
    if template1 is None:
        raise Exception("Static Structural template not available in this Workbench (check licence / installed Mechanical)")
    system1 = template1.CreateSystem()
    geometry1 = system1.GetContainer(ComponentName="Geometry")
    geometry1.SetFile(FilePath=os.path.join(pkg, "model.step"))
    try:
        system1.GetComponent(Name="Geometry").Update(AllDependencies=True)
    except:
        st("GEOMETRY UPDATE: " + traceback.format_exc().replace("\\n", " | "))
    system1.GetComponent(Name="Model").Refresh()
    model1 = system1.GetContainer(ComponentName="Model")
    model1.Edit()
    st("MECHANICAL OPEN")
    model1.SendCommand(Language="Python", Command="import io, os\\nexec(io.open(os.path.join(os.environ['AR_PKG'], 'build_model.py'), encoding='utf-8').read())")
    st("BUILD DONE")
    Save(FilePath=os.path.join(pkg, "Tank_model.wbpj"), Overwrite=True)
    st("SAVED")
except:
    st("ERROR " + traceback.format_exc().replace("\\n", " | "))
'''


def _bat(axis: str, mesh_mm: float) -> str:
    finds = "\n".join(f'if not defined WB if defined AWP_ROOT{v} set "WB=%AWP_ROOT{v}%\\Framework\\bin\\Win64\\RunWB2.exe"' for v in VERSIONS)
    return f'''@echo off
setlocal
set "SRC=%~dp0"
set "WB="
{finds}
if not defined WB (
  echo Ansys Workbench not found. Install Ansys or set AWP_ROOT### environment variable.
  pause
  exit /b 1
)
set "WORK=C:\\ansys_report_work\\model"
if exist "%WORK%" rmdir /s /q "%WORK%"
mkdir "%WORK%"
xcopy "%SRC%*" "%WORK%\\" /E /I /Y >nul
set "AR_PKG=%WORK%\\"
set "ANSYS_REPORT_OUT=%WORK%\\out"
set "ANSYS_REPORT_AXIS={axis}"
set "ANSYS_REPORT_MESH_MM={mesh_mm:g}"
echo Starting Workbench, please wait a few minutes...
"%WB%" -R "%WORK%\\build_model.wbjn"
echo.
echo Project: %WORK%\\Tank_model.wbpj
echo Logs: %WORK%\\out\\log_build.txt and log_loads.txt
if not defined AR_NOPAUSE pause
'''


REPORT_BAT = '''@echo off
rem Technical report from the Workbench project built by Open_in_Ansys.bat (solves in background, extracts results, writes Word/Excel).
setlocal
set "SRC=%~dp0"
set "WORK=C:\\ansys_report_work\\model"
if not exist "%WORK%\\Tank_model.wbpj" (
  echo Project not found: %WORK%\\Tank_model.wbpj  - run Open_in_Ansys.bat first.
  pause
  exit /b 1
)
set "OUT=%WORK%\\report"
set "EXE="
if exist "%ProgramFiles%\\AnsysReport\\AnsysReport.exe" set "EXE=%ProgramFiles%\\AnsysReport\\AnsysReport.exe"
if exist "%LocalAppData%\\Programs\\AnsysReport\\AnsysReport.exe" set "EXE=%LocalAppData%\\Programs\\AnsysReport\\AnsysReport.exe"
if not defined ANSYS_REPORT_HOME if exist "%USERPROFILE%\\Ansys-report\\ansys_report" set "ANSYS_REPORT_HOME=%USERPROFILE%\\Ansys-report"
if not defined ANSYS_REPORT_HOME if exist "C:\\Ansys-report\\ansys_report" set "ANSYS_REPORT_HOME=C:\\Ansys-report"
if defined ANSYS_REPORT_HOME set "PYTHONPATH=%ANSYS_REPORT_HOME%;%PYTHONPATH%"
echo Building the technical report, please wait (solving + extracting results, 5-20 minutes)...
if defined EXE (
  "%EXE%" report-from-ansys "%WORK%\\Tank_model.wbpj" --anketa "%SRC%anketa.json" --loads "%SRC%loads_data.py" -o "%OUT%"
) else (
  python -m ansys_report report-from-ansys "%WORK%\\Tank_model.wbpj" --anketa "%SRC%anketa.json" --loads "%SRC%loads_data.py" -o "%OUT%"
)
echo.
echo Report folder: %OUT%
if not defined AR_NODIAG if defined ANSYS_REPORT_HOME if exist "%ANSYS_REPORT_HOME%\\diag.bat" call "%ANSYS_REPORT_HOME%\\diag.bat"
if not defined AR_NOPAUSE pause
'''


RUN_ALL_BAT = '''@echo off
set "AR_NOPAUSE=1"
call "%~dp0Open_in_Ansys.bat"
call "%~dp0Make_report.bat"
set "AR_NOPAUSE="
echo.
echo Done. Project: C:\\ansys_report_work\\model\\Tank_model.wbpj , report: C:\\ansys_report_work\\model\\report
pause
'''


README = """Модель резервуара с нагрузками - открыть в Ansys.

Что нужно: установленный Ansys Workbench (Mechanical) с действующей лицензией.

1. Распакуйте архив в любую папку.
2. Дважды щёлкните Open_in_Ansys.bat.
3. Откроется Workbench: проект Static Structural собирается из model.step - материал, толщины поясов, сетка, затем нагрузки.
   В Mechanical в дереве будут расчётные случаи «AR: Эксплуатация», «AR: Эксплуатация с ветром», «AR: Гидроиспытания», «AR: Вакуум, снег и ветер».
4. Проект сохраняется в C:\\ansys_report_work\\model\\Tank_model.wbpj. Журналы: C:\\ansys_report_work\\model\\out\\log_build.txt и log_loads.txt.

Технический отчёт: после сборки модели дважды щёлкните Make_report.bat (или сразу Run_all.bat - сборка модели и отчёт подряд).
Скрипт запустит расчёт в Workbench в фоне, выгрузит результаты и соберёт Word/Excel в C:\\ansys_report_work\\model\\report.
Для этого на компьютере должна быть установлена программа ANSYS REPORT (AnsysReport_Setup.exe) или Python с папкой проекта (C:\\Ansys-report или %USERPROFILE%\\Ansys-report, либо переменная ANSYS_REPORT_HOME) и пакеты из requirements.txt.
Реквизиты отчёта (номер, позиция, площадка, исполнитель) можно поправить в anketa.json до запуска.

Состав: model.step - геометрия (мм), thickness_zones.csv - участки толщины, loads_data.py - нагрузки, apply_loads.py и build_model.py - скрипты Mechanical,
build_model.wbjn - журнал Workbench.

Проверьте после открытия: направление стрелок давления (если нагрузки направлены внутрь резервуара, замените в Open_in_Ansys.bat строку
set "ANSYS_REPORT_FLIP=1" - добавьте её перед запуском Workbench), толщины поясов, размер сетки.
Скрипты проверены на синтаксис, но запускались не во всех версиях Ansys: при ошибке пришлите журналы на поддержку сервиса.
"""


def write_open_package(dest: str | Path, step: str | Path, zones_csv: str | Path, loads_data: str | Path, axis: str = "Z", mesh_mm: float = 150,
                       anketa: dict | None = None, parts: dict | None = None) -> Path:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(step, dest / "model.step")
    shutil.copy2(zones_csv, dest / "thickness_zones.csv")
    shutil.copy2(loads_data, dest / "loads_data.py")
    for name in ("apply_loads.py", "build_model.py"):
        shutil.copy2(SCRIPTS / name, dest / name)
    (dest / "build_model.wbjn").write_text(JOURNAL, encoding="utf-8")
    (dest / "Open_in_Ansys.bat").write_text(_bat(axis, mesh_mm), encoding="ascii", newline="\r\n")
    (dest / "Make_report.bat").write_text(REPORT_BAT, encoding="ascii", newline="\r\n")
    (dest / "Run_all.bat").write_text(RUN_ALL_BAT, encoding="ascii", newline="\r\n")
    import json
    (dest / "parts.json").write_text(json.dumps(parts or {}, ensure_ascii=False, indent=1), encoding="utf-8")
    (dest / "anketa.json").write_text(json.dumps(anketa or {}, ensure_ascii=False, indent=1), encoding="utf-8")
    (dest / "README_RU.txt").write_text(README, encoding="utf-8")
    return dest
