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


def extract(project: str | Path, out_dir: str | Path, log=print, version: int | None = None) -> Path:
    """Запускает Mechanical в фоне, открывает проект, выгружает данные в out_dir. Возвращает out_dir."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    installs = find_ansys()
    if not installs:
        raise ConnectError("Ansys не найден на этом компьютере (нет переменной AWP_ROOT###). Установите Ansys Mechanical.")
    ver = version or next(iter(installs))
    log(f"Найден Ansys версии {ver}")
    try:
        from ansys.mechanical.core import launch_mechanical
    except ImportError as e:
        raise ConnectError("Не установлен пакет ansys-mechanical-core (pip install ansys-mechanical-core)") from e
    work = Path(tempfile.mkdtemp(prefix="ansys_report_"))
    try:
        mechdb = find_mechdb(project, work)
        # Mechanical меняет файл при открытии — работаем с копией, исходный проект не трогаем
        local = work / "model.mechdb"
        shutil.copy2(mechdb, local)
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
    return out


def make_project_folder(data_dir: str | Path, anketa: dict | None = None) -> Path:
    """Из папки выгрузки делает папку проекта отчёта с project.yaml (анкета — из шаблона + переданные поля)."""
    d = Path(data_dir)
    img = d / "images"
    img.mkdir(exist_ok=True)
    for f in d.glob("*.png"):
        shutil.move(str(f), img / f.name)
    text = TEMPLATE_YAML.read_text(encoding="utf-8")
    for key, val in (anketa or {}).items():
        text = text.replace("{{" + key + "}}", str(val))
    text = re.sub(r"\{\{\w+\}\}", "", text)
    (d / "project.yaml").write_text(text, encoding="utf-8")
    return d / "project.yaml"
