"""Автоподключение к Ansys: найти установку, открыть проект Mechanical в фоне (без окна),
запустить скрипты выгрузки, собрать папку проекта отчёта (project.yaml + model_data.json + CSV + рисунки).

Нужны: установленный Ansys Mechanical (лицензия клиента) и пакет ansys-mechanical-core."""
from __future__ import annotations
import os
import re
import json
import shutil
import tempfile
import time
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


# метка времени этапа в журнале Workbench (ansys_report/timing.py)
_JOURNAL_TMARK = r'''def tmark(label):
    try:
        import io, time
        f = io.open(os.environ.get('AR_TIMING') or r'C:\ansys_report_work\timing.log', 'a', encoding='utf-8')
        f.write(u'%.3f\t%s\t%s\n' % (time.time(), os.environ.get('AR_TIMING_TAG', ''), label))
        f.close()
    except:
        pass
'''


def extract_via_workbench(project: Path, out: Path, log, ver: int, install: Path, mechdb: Path,
                          scripts: list[str] | None = None, extra_files: dict | None = None, extra_env: dict | None = None,
                          save_as: Path | None = None) -> None:
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
    env_extra = dict(extra_env or {})
    for key, src in (extra_files or {}).items():       # файлы для скриптов кладём во временную латинскую папку
        dst = out / Path(src).name
        shutil.copy2(src, dst)
        env_extra[key] = str(dst)
    try:
        sysname = _system_name(mechdb).replace(" ", "").replace("-", "")
        status = out / "wb_status.txt"
        body = []
        for name in (scripts or SCRIPT_ORDER):
            code = "import io\nexec(io.open(r" + repr(str(SCRIPTS / name)) + ", encoding='utf-8').read())"
            body.append('    tmark(u"WB выгрузка: скрипт ' + name + '")')
            body.append('    model.SendCommand(Language="Python", Command=' + repr(code) + ')')
            body.append('    st("DONE ' + name + '")')
        journal = work / "run.wbjn"
        journal.write_text(
            "# -*- coding: utf-8 -*-\n"                 # без этой строки IronPython не выполняет журнал с кириллицей (метки времени)
            "import os, traceback\n"
            f'os.environ["ANSYS_REPORT_OUT"] = r"{out}"\n'
            f'status = r"{status}"\n'
            "def st(m):\n"
            '    f = open(status, "a")\n'
            '    f.write(m + "\\n")\n'
            "    f.close()\n"
            + _JOURNAL_TMARK +
            'st("JOURNAL START")\n'
            'tmark(u"WB выгрузка: журнал запущен, открытие проекта")\n'
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
            '    tmark(u"WB выгрузка: запуск Mechanical")\n'
            "    model.Edit()\n"
            '    st("MECHANICAL OPEN")\n'
            + "\n".join(body) + "\n"
            '    tmark(u"WB выгрузка: выход из Mechanical, закрытие Workbench")\n'
            "    model.Exit()\n"
            + (f'    Save(FilePath=r"{save_as}", Overwrite=True)\n' if save_as else "") +
            "except:\n"
            '    st("ERROR " + traceback.format_exc().replace("\\n", " | "))\n',
            encoding="utf-8")
        env = dict(os.environ, ANSYS_REPORT_OUT=str(out), **env_extra)
        log("Запускаю Workbench в фоне и открываю проект (несколько минут)…")
        from . import timing
        timing.mark("WB выгрузка: запуск Workbench")
        runlog = out / "wb_run.log"
        with open(runlog, "w", encoding="utf-8", errors="replace") as lf:
            proc = subprocess.Popen([str(exe), "-B", "-R", str(journal)], stdout=lf, stderr=subprocess.STDOUT, env=env, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            started = time.time()
            while True:                      # сообщаем, что программа жива: Workbench работает без окна
                try:
                    proc.wait(timeout=45)
                    break
                except subprocess.TimeoutExpired:
                    mins = int((time.time() - started) // 60)
                    seen = ""
                    if status.exists():
                        last = [l for l in status.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
                        seen = f" (последний шаг: {last[-1][:60]})" if last else ""
                    log(f"  Workbench работает… {mins} мин{seen}")
        timing.mark("Отчёт: после Workbench (данные, отчёт Word/Excel)")
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


def copy_engineering_data(mechdb: Path, out: Path, log) -> None:
    """Копирует EngineeringData.xml проекта Workbench (свойства материалов) в папку выгрузки как engineering_data.xml."""
    root = next((p for p in [mechdb, *mechdb.parents] if p.name.endswith("_files")), None)
    if root is None:
        log("  Свойства материалов: папка проекта _files не найдена, берутся значения из анкеты")
        return
    wanted = set()
    try:
        import json
        md = json.loads((out / "model_data.json").read_text(encoding="utf-8"))
        wanted = {b.get("material") for b in md.get("bodies", [])}
    except Exception:       # noqa: BLE001
        pass
    from . import ansys_import as ai
    best = None
    for f in sorted(root.rglob("EngineeringData.xml"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            mats = ai.read_engineering_data(f)
        except Exception:   # noqa: BLE001
            continue
        if wanted & set(mats):
            best = f
            break
        best = best or f
    if best is None:
        log("  Свойства материалов: файл Engineering Data не найден, берутся значения из анкеты")
        return
    shutil.copy2(best, out / "engineering_data.xml")
    log(f"  Свойства материалов взяты из проекта Ansys ({best.name})")


def extract_with_shape(wbpj: Path, out: Path, log, ver: int, install: Path, mechdb: Path, survey_full: Path, settings) -> None:
    """Форма «полного» резервуара: 1) выгрузка модели; 2) макрос APDL по замерам; 3) вставка макроса в расчёт, решение, результаты."""
    from .settings import ModelSettings, pick_roles
    from .project import load_project
    from .apdl_gen import write_apdl
    import json
    st = settings or ModelSettings()
    shutil.copy2(survey_full, out / "survey_full.csv")
    log("Этап 1 из 2: выгрузка модели для расчёта формы стенки…")
    extract_via_workbench(wbpj, out, log, ver, install, mechdb, scripts=["export_model_data.py"])
    md = json.loads((out / "model_data.json").read_text(encoding="utf-8"))
    full, _ = pick_roles([a["name"] for a in md.get("analyses", [])], st)
    if not full:
        raise ConnectError("В проекте не найден расчёт прочности для «полного» резервуара")
    yaml_path = make_project_folder(out, None, st)
    apdl = write_apdl(load_project(yaml_path), out / "full_shape.inp")
    log(f"Макрос формы стенки построен по замерам; будет применён к расчёту «{full}»")
    log("Этап 2 из 2: применение формы, решение и выгрузка результатов (дольше обычного)…")
    extract_via_workbench(wbpj, out, log, ver, install, mechdb,
                          scripts=["apply_full_shape.py", "export_results.py", "export_model_images.py"],
                          extra_files={"ANSYS_REPORT_APDL": apdl}, extra_env={"ANSYS_REPORT_FULL_NAME": full})


def extract(project: str | Path, out_dir: str | Path, log=print, version: int | None = None, solve: bool = True, settings=None,
            survey_full: str | Path | None = None) -> Path:
    """Запускает Mechanical в фоне, открывает проект, выгружает данные в out_dir. Возвращает out_dir."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    os.environ["ANSYS_REPORT_SOLVE"] = "1" if solve else "0"
    from .settings import ModelSettings
    os.environ.update((settings or ModelSettings()).env())      # соответствия имён и оси для скриптов в Mechanical
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
                if survey_full:
                    extract_with_shape(wbpj, out, log, ver, installs[ver], mechdb, Path(survey_full), settings)
                else:
                    extract_via_workbench(wbpj, out, log, ver, installs[ver], mechdb)
                if (out / "model_data.json").exists():
                    copy_engineering_data(mechdb, out, log)
                    _report_problems(out, log)
                    return out
                log("Через Workbench не вышло, пробую запасной способ…")
            except ConnectError:
                raise
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
    try:
        copy_engineering_data(mechdb, out, log)
    except NameError:
        pass
    _report_problems(out, log)
    return out


def _report_problems(out: Path, log):
    """Показывает ошибки скриптов и предупреждает, если напряжения по поясам выгрузились нулями."""
    f0 = out / "log.txt"
    if f0.exists():
        for line in f0.read_text(encoding="utf-8").splitlines():
            if "SolveRequired" in line and "папка" not in line:
                log(f"  ! {line.strip()} - в проекте Ansys этот расчёт не решён (нужно Solve)")
    for name in ("log.txt", "model_data_log.txt", "log_images.txt", "log_shape.txt"):
        f = out / name
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                if "ОШИБКА" in line or "ПРОПУЩЕНО" in line:
                    log(f"  ! {name}: {line}")
    import csv
    st = out / "stability.csv"
    if st.exists():
        for parts in list(csv.reader(st.read_text(encoding="utf-8").splitlines()))[1:]:
            if len(parts) >= 3 and float(parts[-1]) <= 0:
                log(f"  ! stability.csv: для «{parts[0]}», мода {parts[1]} коэффициент равен 0 - результат расчёта на устойчивость не прочитан")
    files = list(out.glob("*_belts.csv"))
    zero = []
    for f in files:
        rows = list(csv.reader(f.read_text(encoding="utf-8").splitlines()))[1:]
        if rows and all(float(x) == 0 for r in rows for x in r[1:]):
            zero.append(f.name)
            log(f"  ! {f.name}: все напряжения равны 0 - результаты расчёта не прочитаны. "
                "Откройте проект в Ansys, убедитесь что расчёт выполнен (зелёные галочки), сохраните и повторите.")
    if files and len(zero) == len(files):          # ни один случай не решён: отчёт с нулями и «Выполнен» выпускать нельзя
        why = []
        if f0.exists():
            why = sorted({ln.strip() for ln in f0.read_text(encoding="utf-8").splitlines() if "[Error]" in ln})
        raise ConnectError("Расчёт в Ansys не выполнен ни для одного случая (напряжения по поясам равны 0), отчёт не формируется."
                           + (" Сообщения Mechanical: " + "; ".join(why[:3]) if why else ""))


# доли кадра (x0, y0, x1, y1): где в общем виде резервуара (камера: X вверх, вид сбоку сверху) нижний и верхний край стенки
_CROPS = {"fig02_mesh_wall_bottom": (0.12, 0.45, 0.52, 0.77), "fig03_mesh_wall_roof": (0.22, 0.10, 0.62, 0.42)}


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


def _fname(analysis: str) -> str:
    """Имя случая в имени файла: так же, как в export_results.py (без символов, недопустимых в Windows)."""
    return re.sub(r'[<>:"/\\|?*,;()\s]', "_", analysis)


def _blocks(d: Path, settings) -> dict[str, str]:
    """Блоки project.yaml, зависящие от названий расчётов в проекте: роли расчётов, файлы результатов, рисунки."""
    import json
    from .settings import pick_roles
    md = json.loads((d / "model_data.json").read_text(encoding="utf-8"))
    names = [a["name"] for a in md.get("analyses", [])]
    full, empty = pick_roles(names, settings)
    lines = ["results:"]
    if full:
        lines.append(f"  full: {_fname(full)}_belts.csv")
    if empty:
        lines.append(f"  empty: {_fname(empty)}_belts.csv")
    eigen = []
    st = d / "stability.csv"
    if st.exists():
        import csv as _csv
        for row in list(_csv.reader(st.read_text(encoding="utf-8").splitlines()))[1:]:
            name = row[0] if row else ""
            if name and name not in eigen:
                eigen.append(name)
    lines += ["  stability_csv: stability.csv", "  stability_modes: 2", "  stability_labels:"]
    q = lambda t: json.dumps(str(t), ensure_ascii=False)          # строка YAML в двойных кавычках с экранированием
    for n in eigen:
        lines.append(f'    {q(n)}: {q((settings.buckling_labels or {}).get(n, n))}')
    lines += ["  required_k: 1.0", "", "images_dir: images", "images:"]
    img = d / "images"

    def add(key, aname, *results):
        for r in results:
            f = f"{_fname(aname)}_{r}.png"
            if (img / f).exists():
                lines.append(f"  {key}: {f}")
                return

    if full:
        add("fig06_eq_stress", full, "AR_Equivalent", "Equivalent_Stress")
        add("fig07_membrane", full, "AR_Membrane", "Membrane_Stress")
        add("fig08_fiber", full, "AR_Fiber", "Maximum_Principal_Stress", "Bending_Stress")
        add("fig09_deform", full, "Total_Deformation")
    if empty:
        add("fig10_empty_eq", empty, "AR_Equivalent", "Equivalent_Stress")
        add("fig11_empty_mem", empty, "AR_Membrane", "Membrane_Stress")
        add("fig12_empty_fiber", empty, "AR_Fiber", "Bending_Stress", "Maximum_Principal_Stress")
        add("fig13_empty_deform", empty, "Total_Deformation")
    k = 1
    for n in eigen:
        add(f"fig_stab{k}", n, "Total_Deformation"); k += 1
        add(f"fig_stab{k}", n, "Total_Deformation_2"); k += 1
    return {"analysis_full": full or "", "results_block": "\n".join(lines[:lines.index("")]),
            "images_block": "\n".join(lines[lines.index("") + 1:])}


def _has_belts(d: Path) -> bool:
    try:
        from . import ansys_import as ai
        return bool(ai.belt_bodies(json.loads((d / "model_data.json").read_text(encoding="utf-8"))))
    except Exception:       # noqa: BLE001
        return True


def make_project_folder(data_dir: str | Path, anketa: dict | None = None, settings=None) -> Path:
    """Из папки выгрузки делает папку проекта отчёта с project.yaml (анкета — из шаблона + переданные поля)."""
    from .settings import ModelSettings
    d = Path(data_dir)
    img = d / "images"
    img.mkdir(exist_ok=True)
    for f in d.glob("*.png"):
        shutil.move(str(f), img / f.name)
    if (d / "model_data.json").exists() and _has_belts(d):
        crop_mesh_views(img)
    text = TEMPLATE_YAML.read_text(encoding="utf-8")
    values = {"elongation_pct": 21, "roof_radius": 0}       # запасные значения полей, без которых расчёт невозможен
    values.update({k: v for k, v in (anketa or {}).items() if str(v).strip() != ""})
    values.update(_blocks(d, settings or ModelSettings()))
    for key, val in values.items():
        text = text.replace("{{" + key + "}}", str(val))
    text = re.sub(r"\{\{\w+\}\}", "", text)
    (d / "project.yaml").write_text(text, encoding="utf-8")
    return d / "project.yaml"


def apply_loads_to_project(project: str | Path, loads_data: str | Path, out_dir: str | Path, log=print, save_as: str | Path | None = None,
                           axis: str = "Z", version: int | None = None) -> Path:
    """Накладывает нагрузки (loads_data.py из пакета нагрузок) на модель в проекте Workbench: по расчётному случаю - свой Static Structural.
    Проект сохраняется под новым именем (save_as), исходный не меняется. Нужен установленный Ansys и модель резервуара (геометрия, сетка)."""
    project, out = Path(project), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    installs = find_ansys()
    if not installs:
        raise ConnectError("Ansys не найден (нет переменной AWP_ROOT###).")
    ver = version or next(iter(installs))
    work = Path(tempfile.mkdtemp(prefix="ansys_report_loads_"))
    try:
        wbpj = project
        mechdb = find_mechdb(project, work)                       # .wbpz распаковывается во временную папку
        if project.suffix.lower() == ".wbpz":
            wbpj = next((work / "unpacked").glob("*.wbpj"))
        target = Path(save_as) if save_as else project.with_name(project.stem + "_loads.wbpj")
        extract_via_workbench(wbpj, out, log, ver, installs[ver], mechdb, scripts=["apply_loads.py"],
                              extra_files={"ANSYS_REPORT_LOADS": str(loads_data)}, extra_env={"ANSYS_REPORT_AXIS": axis}, save_as=target)
        log(f"Проект с нагрузками: {target}")
        return target
    finally:
        shutil.rmtree(work, ignore_errors=True)
