@echo off
rem Collects Ansys logs into diag\diag.txt and pushes them to branch diag-logs so the developer can read them.
rem Logs are committed in a separate worktree (C:\ansys_report_work\diag_wt): the working copy and its branch stay untouched.
setlocal
cd /d "%~dp0"
set "W=C:\ansys_report_work\model"
set "WT=C:\ansys_report_work\diag_wt"
for /f %%H in ('git rev-parse HEAD') do set "HEADSHA=%%H"
git worktree prune >nul 2>&1
if not exist "%WT%\.git" git worktree add --force --detach "%WT%" %HEADSHA% >nul 2>&1
git -C "%WT%" fetch -q origin diag-logs >nul 2>&1
git -C "%WT%" checkout -q -f -B diag-logs %HEADSHA%
rem saved files (diag\report_30000.docx and the like) are carried over from the previous diag-logs; diag.txt and report.docx are replaced below
git -C "%WT%" checkout origin/diag-logs -- diag >nul 2>&1
if not exist "%WT%\diag" mkdir "%WT%\diag"
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
for /r "%W%\report" %%F in (solve_*.out) do (
  echo ===== %%F =====
  powershell -NoProfile -Command "Select-String -LiteralPath '%%F' -Pattern 'cores','processes','Distributed','DISTRIBUTED','HPC','Elapsed','CPU time','checked out','LICENSE','license' | Select-Object -First 25 | ForEach-Object { $_.Line.Trim() }"
)
) > "%WT%\diag\diag.txt" 2>&1
if exist "%WT%\diag\report.docx" del "%WT%\diag\report.docx"
for /r "%W%\report" %%F in (Report_*.docx) do copy /y "%%F" "%WT%\diag\report.docx" >nul
pushd "%WT%"
git add -f -A diag
git status --short
git -c user.name=ansys-report -c user.email=ansys-report@local commit -m "diag logs"
git push -f origin diag-logs
popd
echo Logs sent (branch diag-logs).
