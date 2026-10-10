"""Сверка с цифрами отчёта-образца ТО-019-26 (РВС-9985 Т-001)."""
from pathlib import Path
import openpyxl
from ansys_report.project import load_project
from ansys_report.calc import calc_all
from ansys_report.excel_gen import build_excel
from ansys_report.word_gen import build_report

YAML = Path(__file__).parent.parent / "examples/T001/project.yaml"


def test_numbers_match_sample_report():
    c = calc_all(load_project(YAML))
    assert round(c["R1"], 2) == 206.35 and round(c["R2"], 2) == 235.83 and round(c["Rutor"], 2) == 353.74
    assert round(c["E2"], 1) == 743.7 and round(c["allow"], 1) == 216.7
    assert round(c["roof_force"], 1) == 734643.9
    assert c["strength_ok"] and c["kmin"] == 10.9


def test_excel_and_word_build(tmp_path):
    p = load_project(YAML)
    x = build_excel(p, tmp_path / "a.xlsx")
    wb = openpyxl.load_workbook(x)
    assert wb.sheetnames == ["Т-001 полный", "Т-001 пустой", "Проверка"]
    docx_path, missing = build_report(p, tmp_path / "a.docx")
    assert docx_path.stat().st_size > 10_000 and "fig01_general" in missing


def test_real_ansys_example(tmp_path):
    """Данные, выгруженные скриптом export_results.py из реального проекта Ansys."""
    p = load_project(Path(__file__).parent.parent / "examples/T001_ansys/project.yaml")
    c = calc_all(p)
    assert len(c["belts"]) == 12 and c["belts_empty"] and c["strength_ok"]
    assert [s["k"] for s in c["stability"][:3]] == [11.6, 11.6, 10.9] and c["stability_ok"]
    build_report(p, tmp_path / "r.docx")


def test_gui_core(tmp_path):
    from ansys_report.gui import build_all
    msgs = []
    files = build_all(YAML, tmp_path, msgs.append)
    assert len(files) == 4 and all(f.exists() for f in files) and any("Word" in m for m in msgs)
