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
    ap.add_argument("command", choices=["excel", "word", "all", "gui", "wizard", "apdl"], help="что сформировать")
    ap.add_argument("project", nargs="?", help="путь к project.yaml")
    ap.add_argument("-o", "--out", default="out", help="папка результата (по умолчанию ./out)")
    a = ap.parse_args(argv)
    if a.command == "wizard":
        from .wizard import main as wiz_main
        return wiz_main()
    if a.command == "gui":
        from .gui import main as gui_main
        return gui_main()
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
