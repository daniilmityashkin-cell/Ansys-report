"""Автоподключение к Ansys: найти установку, открыть проект Mechanical в фоне (без окна),
запустить скрипты выгрузки, собрать папку проекта отчёта (project.yaml + model_data.json + CSV + рисунки).

Нужны: установленный Ansys Mechanical (лицензия клиента) и пакет ansys-mechanical-core."""
from __future__ import annotations
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "ansys_scripts"
SCRIPT_ORDER = ["export_model_data.py", "export_results.py", "export_model_images.py"]
TEMPLATE_YAML = Path(__file__).resolve().parent / "templates" / "project_template.yaml"


class ConnectError(Exception):
    pass


def find_ansys() -> dict[int, Path]:
    """Установки Ansys по переменным AWP_ROOT###. Возвращает {версия: путь}, например {261: Path(...)}."""
    found = {}
    for k, v in os.environ.items():
        m = re.fullmatch(r"AWP_ROOT(\d{3})", k)
        if m and Path(v).exists():
            found[int(m.group(1))] = Path(v)
    return dict(sorted(found.items(), reverse=True))


def find_mechdb(project: str | Path, work: Path) -> Path:
    """Файл Mechanical (.mechdb) по файлу проекта Workbench (.wbpj / .wbpz) или сам .mechdb."""
    project = Path(project)
    if not project.exists():
        raise ConnectError(f"Файл не найден: {project}")
    if project.suffix.lower() == ".mechdb":
        return project
    if project.suffix.lower() == ".wbpz":
        dest = work / "unpacked"
        with zipfile.ZipFile(project) as z:
            z.extractall(dest)
        wbpj = next(dest.glob("*.wbpj"), None)
        if wbpj is None:
            raise ConnectError("В архиве .wbpz нет файла .wbpj")
        project = wbpj
    files_dir = project.with_name(project.stem + "_files")
    cands = sorted(files_dir.rglob("*.mechdb"), key=lambda p: p.stat().st_mtime, reverse=True) if files_dir.exists() else []
    if not cands:
        raise ConnectError(
            "В проекте не найден файл расчёта Mechanical (.mechdb). Откройте проект в Ansys, "
            "выполните расчёт, сохраните проект (File → Save) и повторите.")
    return cands[0]


_OPEN_VARIANTS = [
    'ExtAPI.DataModel.Project.Open(r"{p}")',
    'ExtAPI.Application.Open(r"{p}")',
    'DataModel.Project.Open(r"{p}")',
]
_CHECK = 'str(len(list(ExtAPI.DataModel.Project.Model.Geometry.GetChildren(DataModelObjectCategory.Body, True))))'


def _open_project(mech, path: Path, log):
    """Открывает .mechdb в запущенном Mechanical (пробует несколько вариантов API, проверяет что модель загрузилась)."""
    if hasattr(mech, "open"):
        try:
            mech.open(str(path))
        except Exception as e:
            log(f"  open(): {e}")
    for tpl in [None] + _OPEN_VARIANTS:
        try:
            if tpl:
                mech.run_python_script(tpl.format(p=path))
            n = int(mech.run_python_script(_CHECK))
            if n > 0:
                log(f"Проект открыт, тел в модели: {n}")
                return
        except Exception as e:
            log(f"  не вышло ({tpl}): {str(e)[:120]}")
    raise ConnectError("Не удалось открыть проект в Mechanical в фоновом режиме")


def _system_name(mechdb: Path) -> str:
    """Имя системы Workbench по файлу .mechdb (например SYS-2.mechdb -> SYS-2)."""
    return mechdb.stem


def extract_via_workbench(project: Path, out: Path, log, ver: int, install: Path, mechdb: Path) -> None:
    """Основной способ: Workbench в фоне открывает проект (со всеми файлами результатов) и запускает
    наши скрипты внутри Mechanical через журнал (SendCommand)."""
    import subprocess
    exe = install / "Framework" / "bin" / "Win64" / "RunWB2.exe"
    if not exe.exists():
        raise ConnectError(f"Не найден {exe}")
    final_out = out
    work = Path(tempfile.mkdtemp(prefix="ansys_report_wb_"))
    out = work / "out"                      # в журнале Workbench только латинские пути
    out.mkdir()
    try:
        sysname = _system_name(mechdb).replace(" ", "").replace("-", "")
        status = out / "wb_status.txt"
        body = []
        for name in SCRIPT_ORDER:
            code = "import io\nexec(io.open(r" + repr(str(SCRIPTS / name)) + ", encoding='utf-8').read())"
            body.append('    model.SendCommand(Language="Python", Command=' + repr(code) + ')')
            body.append('    st("DONE ' + name + '")')
        journal = work / "run.wbjn"
        journal.write_text(
            "import os, traceback\n"
            f'os.environ["ANSYS_REPORT_OUT"] = r"{out}"\n'
            f'status = r"{status}"\n'
            "def st(m):\n"
            '    f = open(status, "a")\n'
            '    f.write(m + "\\n")\n'
            "    f.close()\n"
            'st("JOURNAL START")\n'
            "try:\n"
            f'    Open(FilePath=r"{project}")\n'
            "    target = None\n"
            "    for s in GetAllSystems():\n"
            '        st("SYSTEM " + s.Name)\n'
            f'        if s.Name.replace(" ", "").replace("-", "") == "{sysname}":\n'
            "            target = s\n"
            "    if target is None:\n"
            '        raise Exception("system not found")\n'
            '    model = target.GetContainer(ComponentName="Model")\n'
            "    model.Edit()\n"
            '    st("MECHANICAL OPEN")\n'
            + "\n".join(body) + "\n"
            "    model.Exit()\n"
            "except:\n"
            '    st("ERROR " + traceback.format_exc().replace("\\n", " | "))\n',
            encoding="utf-8")
        env = dict(os.environ, ANSYS_REPORT_OUT=str(out))
        log("Запускаю Workbench в фоне и открываю проект (несколько минут)…")
        runlog = out / "wb_run.log"
        with open(runlog, "w", encoding="utf-8", errors="replace") as lf:
            proc = subprocess.Popen([str(exe), "-B", "-R", str(journal)], stdout=lf, stderr=subprocess.STDOUT, env=env)
            proc.wait()
        log(f"  Workbench завершился с кодом {proc.returncode}")
        try:
            tail = [l for l in runlog.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()][:8]
            for l in tail:
                log("  wb> " + l[:200])
        except Exception:
            pass
        if status.exists():
            for line in status.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("ERROR"):
                    log("  ! Workbench: " + line[:300])
                elif line.startswith("SYSTEM"):
                    log("  система в проекте: " + line[7:])
                elif line.startswith("DONE"):
                    log("  готово: " + line[5:])
        else:
            log("  ! Workbench не оставил отчёта о работе (журнал не выполнился)")
        for item in out.iterdir():          # переносим результат в папку отчёта (там могут быть русские буквы)
            if item.name in ("wb_status.txt", "wb_run.log") or item.is_file():
                shutil.copy2(item, final_out / item.name)
            elif item.is_dir():
                shutil.copytree(item, final_out / item.name, dirs_exist_ok=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _pyrepr(text: str) -> str:
    return repr(text)


def extract(project: str | Path, out_dir: str | Path, log=print, version: int | None = None) -> Path:
    """Запускает Mechanical в фоне, открывает проект, выгружает данные в out_dir. Возвращает out_dir."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for old in list(out.iterdir()):          # убираем файлы прошлой выгрузки, чтобы не принять их за новые
        if old.is_file():
            old.unlink()
        elif old.name == "images":
            shutil.rmtree(old, ignore_errors=True)
    installs = find_ansys()
    if not installs:
        raise ConnectError("Ansys не найден на этом компьютере (нет переменной AWP_ROOT###). Установите Ansys Mechanical.")
    ver = version or next(iter(installs))
    log(f"Найден Ansys версии {ver}")
    work = Path(tempfile.mkdtemp(prefix="ansys_report_"))
    try:
        mechdb = find_mechdb(project, work)
        wbpj = Path(project)
        if wbpj.suffix.lower() == ".wbpj" and ver in installs:
            try:
                extract_via_workbench(wbpj, out, log, ver, installs[ver], mechdb)
                if (out / "model_data.json").exists():
                    _report_problems(out, log)
                    return out
                log("Через Workbench не вышло, пробую запасной способ…")
            except Exception as e:  # noqa: BLE001
                log(f"Workbench-способ не сработал ({e}), пробую запасной способ…")
        try:
            from ansys.mechanical.core import launch_mechanical
        except ImportError as e:
            raise ConnectError("Не установлен пакет ansys-mechanical-core (pip install ansys-mechanical-core)") from e
        # Mechanical меняет файл при открытии — работаем с копией, исходный проект не трогаем
        # копируем всю папку MECH: рядом с .mechdb лежат файлы результатов расчёта (.rst), без них новые результаты = 0
        mdir = work / "MECH"
        shutil.copytree(mechdb.parent, mdir)
        local = mdir / mechdb.name
        log(f"Проект: {mechdb.name}. Запускаю Mechanical в фоне (1–3 минуты)…")
        os.environ["ANSYS_REPORT_OUT"] = str(out)
        mech = launch_mechanical(batch=True, version=ver, cleanup_on_exit=True)
        try:
            _open_project(mech, local, log)
            for name in SCRIPT_ORDER:
                log(f"Выгрузка: {name}…")
                mech.run_python_script((SCRIPTS / name).read_text(encoding="utf-8"))
                log(f"  готово: {name}")
        finally:
            try:
                mech.exit(force=True)
            except Exception:
                pass
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if not (out / "model_data.json").exists():
        raise ConnectError("Выгрузка не создала model_data.json. Смотрите model_data_log.txt в папке " + str(out))
    _report_problems(out, log)
    return out


def _report_problems(out: Path, log):
    """Показывает ошибки скриптов и предупреждает, если напряжения по поясам выгрузились нулями."""
    for name in ("log.txt", "model_data_log.txt", "log_images.txt"):
        f = out / name
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                if "ОШИБКА" in line:
                    log(f"  ! {name}: {line}")
    for f in out.glob("*_belts.csv"):
        rows = f.read_text(encoding="utf-8").splitlines()[1:]
        if rows and all(float(x) == 0 for r in rows for x in r.split(",")[1:]):
            log(f"  ! {f.name}: все напряжения равны 0 - результаты расчёта не прочитаны. "
                "Откройте проект в Ansys, убедитесь что расчёт выполнен (зелёные галочки), сохраните и повторите.")


# доли кадра (x0, y0, x1, y1): где в общем виде резервуара (камера: X вверх, вид сбоку сверху) нижний и верхний край стенки
_CROPS = {"fig02_mesh_wall_bottom": (0.22, 0.58, 0.62, 0.92), "fig03_mesh_wall_roof": (0.22, 0.10, 0.62, 0.42)}


def crop_mesh_views(img_dir: Path, log=print) -> None:
    """Из крупных снимков сетки вырезает фрагменты (стенка+днище, стенка+кровля). Нужен Pillow."""
    try:
        from PIL import Image
    except ImportError:
        log("  ! Нет пакета Pillow (pip install Pillow): рисунки сетки останутся общим видом")
        return
    for name, (x0, y0, x1, y1) in _CROPS.items():
        f = Path(img_dir) / (name + ".png")
        if not f.exists():
            continue
        with Image.open(f) as im:
            w, h = im.size
            if w < 2500:                      # снимок высокого разрешения не получился - не режем
                continue
            im.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h))).save(f)


def make_project_folder(data_dir: str | Path, anketa: dict | None = None) -> Path:
    """Из папки выгрузки делает папку проекта отчёта с project.yaml (анкета — из шаблона + переданные поля)."""
    d = Path(data_dir)
    img = d / "images"
    img.mkdir(exist_ok=True)
    for f in d.glob("*.png"):
        shutil.move(str(f), img / f.name)
    crop_mesh_views(img)
    text = TEMPLATE_YAML.read_text(encoding="utf-8")
    for key, val in (anketa or {}).items():
        text = text.replace("{{" + key + "}}", str(val))
    text = re.sub(r"\{\{\w+\}\}", "", text)
    (d / "project.yaml").write_text(text, encoding="utf-8")
    return d / "project.yaml"
