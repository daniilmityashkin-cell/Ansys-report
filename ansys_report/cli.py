"""Командная строка: python -m ansys_report <команда> project.yaml [-o папка]"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
from .project import load_project, ProjectError
from .excel_gen import build_excel, export_points_txt
from .word_gen import build_report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ansys_report", description="Автоматизация отчётов по расчёту РВС в Ansys")
    ap.add_argument("command", choices=["excel", "word", "all"], help="что сформировать")
    ap.add_argument("project", help="путь к project.yaml")
    ap.add_argument("-o", "--out", default="out", help="папка результата (по умолчанию ./out)")
    a = ap.parse_args(argv)
    try:
        p = load_project(a.project)
    except (ProjectError, FileNotFoundError, KeyError) as e:
        print(f"Ошибка исходных данных: {e}", file=sys.stderr); return 2
    out, tag = Path(a.out), p.tank["tag"]
    if a.command in ("excel", "all"):
        print("Excel:", build_excel(p, out / f"Нивелировка {tag}.xlsx"))
        print("Точки:", export_points_txt(p, p.survey_full, out / f"points_{tag}_full.txt"))
        print("Точки:", export_points_txt(p, p.survey_empty, out / f"points_{tag}_empty.txt"))
    if a.command in ("word", "all"):
        path, missing = build_report(p, out / f"ТО_{p.report['number']}_{tag}.docx")
        print("Word:", path)
        if missing: print(f"Нет {len(missing)} рисунков (вставлены заглушки): {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
