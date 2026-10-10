@echo off
rem Builds AnsysReport.exe (PyInstaller) and, if Inno Setup is installed, the installer.
rem Run from the repository root:  installer\build_installer.bat
setlocal
cd /d "%~dp0\.."
python -m pip install -r requirements.txt pyinstaller || goto :err
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
python -m PyInstaller --noconfirm --clean --windowed --name AnsysReport ^
  --add-data "ansys_report\templates;ansys_report\templates" ^
  --add-data "ansys_report\web;ansys_report\web" ^
  --add-data "ansys_scripts;ansys_scripts" ^
  --exclude-module ansys --exclude-module grpc --exclude-module tkinter ^
  launcher.py || goto :err
echo.
echo Program folder: dist\AnsysReport  (run dist\AnsysReport\AnsysReport.exe)
set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if exist "%ISCC%" (
  "%ISCC%" installer\AnsysReport.iss || goto :err
  echo Installer: installer\Output\AnsysReport_Setup.exe
) else (
  echo Inno Setup 6 not found - installer not built. Install it from https://jrsoftware.org/isdl.php and run again.
)
goto :eof
:err
echo BUILD FAILED
exit /b 1
