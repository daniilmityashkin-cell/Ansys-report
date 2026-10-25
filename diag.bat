@echo off
rem Collects Ansys logs into diag\diag.txt and pushes them to branch diag-logs so the developer can read them.
setlocal
cd /d "%~dp0"
set "W=C:\ansys_report_work\model"
if not exist diag mkdir diag
(
for %%F in ("%W%\out\log_build.txt" "%W%\out\log_loads.txt" "%W%\out\wb_status.txt" ) do (
  echo ===== %%~F =====
  if exist "%%~F" (type "%%~F") else (echo [no file])
)
for /r "%W%\report" %%F in (model_data.json) do (
  if exist "%%F" (
    echo ===== %%F =====
    powershell -NoProfile -Command "$j=Get-Content -Raw -Encoding UTF8 -LiteralPath '%%F' | ConvertFrom-Json; 'errors:'; $j.errors; 'bodies:'; $j.bodies | ForEach-Object { $_.name + ' ' + $_.thickness }; 'belts_from_faces: ' + $j.belts_from_faces; 'belt_regex: ' + $j.belt_regex"
  )
)
for /r "%W%\report" %%F in (log.txt wb_status.txt) do (
  echo ===== %%F =====
  type "%%F"
)
for /r "%W%\Tank_model_files" %%F in (solve.out file0.err file.err *.err) do (
  if exist "%%F" (
    echo ===== %%F =====
    powershell -NoProfile -Command "Get-Content -LiteralPath '%%F' -Tail 80"
  )
)
) > diag\diag.txt 2>&1
git checkout -B diag-logs >nul 2>&1
if exist diag\report.docx del diag\report.docx
for /r "%W%\report" %%F in (Report_*.docx) do copy /y "%%F" diag\report.docx >nul
if exist diag\report.docx git add -f diag\report.docx
git add -f diag\diag.txt
git status --short
git -c user.name=ansys-report -c user.email=ansys-report@local commit -m "diag logs"
git push -f origin diag-logs
echo Logs sent (branch diag-logs).
git checkout - >nul 2>&1
