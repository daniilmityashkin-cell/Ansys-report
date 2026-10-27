"""Проверка совместимости с установленной версией Ansys (2022 R1 ... 2026 R1): Workbench в фоне создаёт пустой Static Structural,
открывает Mechanical и прогоняет ansys_scripts/probe_api.py: какие вызовы API, нужные программе, в этой версии есть, а каких нет.
Запуск: python -m ansys_report check-ansys [--version 242]. Результат: C:\\ansys_report_work\\probe_api.txt (его присылают разработчику)."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .ansys_connect import SCRIPTS, ConnectError, find_ansys, pick_version

NAMES = {221: "2022 R1", 222: "2022 R2", 231: "2023 R1", 232: "2023 R2", 241: "2024 R1", 242: "2024 R2", 251: "2025 R1", 252: "2025 R2", 261: "2026 R1"}


def version_name(v: int) -> str:
    return NAMES.get(v, f"версия {v}")


JOURNAL = '''# -*- coding: utf-8 -*-
import os, traceback
status = r"{status}"
def st(m):
    f = open(status, "a")
    f.write(m + "\\n")
    f.close()
st("START")
try:
    tpl = None
    for kw in ({{"TemplateName": "Static Structural", "Solver": "ANSYS"}}, {{"TemplateName": "Static Structural", "Solver": "Mechanical"}},
               {{"TemplateName": "Static Structural"}}, {{"TemplateName": "Static Structural (ANSYS)"}}):
        try:
            tpl = GetTemplate(**kw)
            st("TEMPLATE OK: " + repr(kw))
            break
        except:
            st("TEMPLATE FAIL " + repr(kw))
    if tpl is None:
        raise Exception("Static Structural template not available (check licence / installed Mechanical)")
    system1 = tpl.CreateSystem()
    model1 = system1.GetContainer(ComponentName="Model")
    model1.Edit()
    st("MECHANICAL OPEN")
    model1.SendCommand(Language="Python", Command={command})
    st("PROBE DONE")
    model1.Exit()
except:
    st("ERROR " + traceback.format_exc().replace("\\n", " | "))
'''


def journal_text(status: Path, probe: Path) -> str:
    """Журнал Workbench. Пути Windows (C:\\Ansys-report\\ansys_scripts...) подставляются через repr: иначе \\a, \\x и т. п. портят строку."""
    command = repr("import io\nexec(io.open(" + repr(str(probe)) + ", encoding='utf-8').read())")
    return JOURNAL.format(status=str(status).replace("\\", "/"), command=command)


def check_ansys(version: int | None = None, out_dir: str | Path | None = None, log=print, timeout_s: int = 900) -> Path:
    installs = find_ansys()
    if not installs:
        raise ConnectError("Ansys не найден на этом компьютере (нет переменной окружения AWP_ROOT###, например AWP_ROOT261).")
    ver = pick_version(installs, version)
    exe = installs[ver] / "Framework" / "bin" / "Win64" / "RunWB2.exe"
    if not exe.exists():
        raise ConnectError(f"Не найден {exe}")
    log(f"Ansys {version_name(ver)} ({installs[ver]}); установлены: {', '.join(version_name(v) for v in installs)}")
    work = Path(tempfile.mkdtemp(prefix="ansys_report_probe_"))
    out = work / "out"                       # только латинские пути для журнала Workbench
    out.mkdir()
    status = out / "wb_status.txt"
    journal = work / "probe.wbjn"
    journal.write_text(journal_text(status, SCRIPTS / "probe_api.py"), encoding="utf-8")
    env = dict(os.environ, ANSYS_REPORT_OUT=str(out))
    log("Запускаю Workbench в фоне (1-3 минуты)...")
    runlog = out / "wb_run.log"
    started = time.time()
    with open(runlog, "w", encoding="utf-8", errors="replace") as lf:
        proc = subprocess.Popen([str(exe), "-B", "-R", str(journal)], stdout=lf, stderr=subprocess.STDOUT, env=env, stdin=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            log("! Workbench не завершился за %d минут, остановлен" % (timeout_s // 60))
    log(f"Workbench завершился с кодом {proc.returncode} за {int(time.time() - started)} с")
    dest = Path(out_dir or os.environ.get("ANSYS_REPORT_AGENT_DIR") or r"C:\ansys_report_work")
    dest.mkdir(parents=True, exist_ok=True)
    report = dest / f"probe_api_{ver}.txt"
    parts = [f"ANSYS REPORT: проверка совместимости, Ansys {version_name(ver)} ({ver})\n"]
    probe = out / "probe_api.txt"
    parts.append(probe.read_text(encoding="utf-8", errors="replace") if probe.exists() else "probe_api.txt не создан: скрипт в Mechanical не выполнился.\n")
    if status.exists():
        parts.append("\n--- журнал Workbench ---\n" + status.read_text(encoding="utf-8", errors="replace"))
    if runlog.exists():
        parts.append("\n--- вывод Workbench ---\n" + runlog.read_text(encoding="utf-8", errors="replace")[:4000])
    report.write_text("".join(parts), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    text = report.read_text(encoding="utf-8")
    missing = [l for l in text.splitlines() if l.startswith("НЕТ")]
    log(f"Готово: {report}")
    log("Не найдено вызовов: %d" % len(missing) + ("" if not missing else "\n  " + "\n  ".join(m[:130] for m in missing[:25])))
    return report
