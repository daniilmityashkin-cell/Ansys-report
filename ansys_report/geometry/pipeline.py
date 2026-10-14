"""Полный цикл по замерам: проект замеров (JSON) → оценка по допускам → геометрия (STEP/IGES) → рисунки → Word."""
from __future__ import annotations
import shutil
from pathlib import Path

from . import check, figures, rvs_core
from .report import PointsReport
from ..util import out_names


def build_from_points(project_file, out_dir, anketa: dict | None = None, log=print, export_cad: bool = True,
                      tolerance_mm: float = 0.1, fmt: str = "STEP + IGES") -> list[Path]:
    """Возвращает список созданных файлов. Все результаты - в подпапке «Geometry_<позиция>»."""
    anketa = anketa or {}
    project_file = Path(str(project_file).strip().strip('"'))
    if not project_file.exists():
        raise FileNotFoundError(f"Файл замеров не найден: {project_file}")
    tag = out_names(anketa.get("tag") or "tank", "x")["folder"].replace("Report_", "Geometry_")
    out = Path(out_dir) / tag
    out.mkdir(parents=True, exist_ok=True)
    log("Читаю замеры…")
    project = check.load_project(project_file)
    res = check.analyze(project)
    log(f"Замеров: {res['n_points']}; выше H/200: {res['over_a']}; выше H/200+30 мм: {res['over_b']}; "
        f"макс. |Δ| = {res['max_abs']:.1f} мм")
    files: list[Path] = []
    shutil.copy2(project_file, out / "Проект замеров.json")
    log("Строю рисунки…")
    figs = figures.make_all(res, out / "images")
    chk = None
    if export_cad:
        log("Строю поверхность для Ansys (STEP/IGES)…")
        chk = check.export_geometry(project, out / "cad", tolerance_mm, fmt, log)
        files += [Path(f) for f in chk["files"]]
    log("Собираю отчёт Word…")
    nm = out_names(anketa.get("tag") or "tank", anketa.get("number") or "report")
    docx_path = PointsReport(res, figs, anketa, chk).build(out / nm["word"].replace("Report_", "Geometry_report_"))
    files.insert(0, docx_path)
    try:                                         # интерактивный просмотр для инженера (HTML, 3D/развёртка с ползунками)
        rvs_core.report_write(out / "Просмотр геометрии.html", res["model"])
        files.append(out / "Просмотр геометрии.html")
    except Exception as e:                       # noqa: BLE001
        log(f"HTML-просмотр не создан: {e}")
    log(f"Результаты в папке: {out}")
    return files
