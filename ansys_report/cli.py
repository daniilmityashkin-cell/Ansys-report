"""Командная строка: python -m ansys_report <команда> project.yaml [-o папка]"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
from .project import load_project, ProjectError
from .excel_gen import build_excel, export_points_txt
from .word_gen import build_report
from .util import out_names, slug


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ansys_report", description="Автоматизация отчётов по расчёту РВС в Ansys")
    ap.add_argument("command", choices=["excel", "word", "all", "gui", "wizard", "wizard-classic", "apdl", "geometry", "geometry-classic", "loads", "apply-loads", "report-from-ansys"], help="что сформировать")
    ap.add_argument("project", nargs="?", help="путь к project.yaml")
    ap.add_argument("-o", "--out", default="out", help="папка результата (по умолчанию ./out)")
    ap.add_argument("--loads", help="apply-loads: файл loads_data.py из пакета нагрузок")
    ap.add_argument("--anketa", help="report-from-ansys: файл anketa.json (поля отчёта: номер, позиция, исполнитель и т. д.)")
    ap.add_argument("--no-solve", action="store_true", help="report-from-ansys: не запускать расчёт, взять готовые результаты проекта")
    ap.add_argument("--axis", default="Z", help="apply-loads: вертикальная ось модели (X, Y или Z)")
    a = ap.parse_args(argv)
    if a.command == "loads":
        if not a.project:
            ap.error("укажите файл исходных данных для расчёта нагрузок (JSON)")
        import json
        from .loads.rvs_loads import compute
        from .loads.export import write_package
        res = compute(json.loads(Path(a.project).read_text(encoding="utf-8-sig")))
        pack = write_package(res, a.out)
        for k in ("json", "data", "summary"):
            print("Файл:", pack[k])
        for n in res["notes"]:
            print("Примечание:", n)
        bad = [s["belt"] for s in res["strength"] if not s["ok"]]
        print("Прочность стенки:", "обеспечена" if not bad else f"НЕ обеспечена в поясах {bad}")
        st = [b["belt"] for b in res["stability"]["belts"] if b["ok"] is False]
        print("Устойчивость стенки:", "обеспечена" if not st else f"НЕ обеспечена в поясах {st}")
        return 0
    if a.command == "apply-loads":
        if not (a.project and a.loads):
            ap.error("укажите проект Workbench (.wbpj/.wbpz) и --loads loads_data.py")
        from .ansys_connect import apply_loads_to_project, ConnectError
        try:
            apply_loads_to_project(a.project, a.loads, a.out, log=print, axis=a.axis)
            print("Готово. Журнал наложения нагрузок:", Path(a.out) / "log_loads.txt")
        except ConnectError as e:
            print(f"Ошибка: {e}", file=sys.stderr)
            return 2
        return 0
    if a.command == "report-from-ansys":
        if not a.project:
            ap.error("укажите проект Workbench (.wbpj)")
        import json
        from .wizard import build_from_ansys, FIELDS
        from .ansys_connect import ConnectError
        anketa = {k: d for k, _, d in FIELDS}
        if a.anketa:
            anketa.update({k: v for k, v in json.loads(Path(a.anketa).read_text(encoding="utf-8-sig")).items() if str(v).strip()})
        from .settings import ModelSettings
        if a.loads:
            anketa["loads_file"] = str(Path(a.loads).resolve())
            import os
            os.environ["ANSYS_REPORT_LOADS"] = anketa["loads_file"]      # скрипты выгрузки берут толщины поясов из loads_data.py
            try:                                                           # плотность продукта и уровень налива - из первого случая с гидростатикой
                ns: dict = {}
                exec(Path(anketa["loads_file"]).read_text(encoding="utf-8"), ns)
                Ld = ns["LOADS"]
                h = next(c["hydro"] for c in Ld["cases"] if c.get("hydro"))
                anketa.setdefault("fill_level", round(h["free_surface_mm"]))
                anketa.setdefault("product_density", round(h["gradient_mpa_mm"] * 1e9 / (Ld["gravity_mm_s2"] / 1000.0)))
            except Exception:       # noqa: BLE001
                pass
        axis = str(anketa.pop("vertical_axis", "Z")).upper()          # модель с сайта: вертикаль - ось Z
        try:
            files = build_from_ansys(a.project, a.out, anketa, log=print, solve=not a.no_solve, settings=ModelSettings(vertical_axis=axis, static_prefix="AR:", full_analysis="AR: Эксплуатация"))
        except (ConnectError, FileNotFoundError) as e:
            print(f"Ошибка: {e}", file=sys.stderr)
            return 2
        for f in files:
            print("Файл:", f)
        return 0
    if a.command == "wizard":
        from .webui import main as web_main
        return web_main()
    if a.command == "wizard-classic":
        from .wizard import main as wiz_main
        return wiz_main()
    if a.command == "gui":
        from .gui import main as gui_main
        return gui_main()
    if a.command == "geometry-classic":
        from .geometry.rvs_gui import main as geo_main
        geo_main()
        return 0
    if a.command == "geometry":
        if not a.project:
            ap.error("укажите путь к файлу замеров (JSON)")
        from .geometry.pipeline import build_from_points
        for f in build_from_points(a.project, a.out, {}):
            print("Файл:", f)
        return 0
    if not a.project:
        ap.error("укажите путь к project.yaml")
    try:
        p = load_project(a.project)
    except (ProjectError, FileNotFoundError, KeyError) as e:
        print(f"Ошибка исходных данных: {e}", file=sys.stderr); return 2
    out, tag = Path(a.out), p.tank["tag"]
    nm = out_names(tag, p.report["number"])
    if a.command == "apdl":
        from .apdl_gen import write_apdl
        print("APDL:", write_apdl(p, out / f"deform_{slug(tag)}_full.inp"))
        return 0
    if a.command in ("excel", "all"):
        print("Excel:", build_excel(p, out / nm["excel"]))
        print("Точки:", export_points_txt(p, p.survey_full, out / nm["full"]))
        print("Точки:", export_points_txt(p, p.survey_empty, out / nm["empty"]))
    if a.command in ("word", "all") and not p.has_results:
        print("Word-отчёт пропущен: нет результатов Ansys (results.full). Выгрузите их скриптом export_results.py.")
    elif a.command in ("word", "all"):
        path, missing = build_report(p, out / nm["word"])
        print("Word:", path)
        if missing: print(f"Нет {len(missing)} рисунков (вставлены заглушки): {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
