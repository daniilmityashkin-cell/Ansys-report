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


def test_other_tanks_excel_only(tmp_path):
    """Т-002…Т-004: замеры из образца, результатов Ansys ещё нет — собираются Excel и точки, Word пропускается."""
    from ansys_report.gui import build_all
    for tag, n in (("T002", 16), ("T003", 15), ("T004", 16)):
        y = Path(__file__).parent.parent / f"examples/{tag}_ansys/project.yaml"
        p = load_project(y)
        assert not p.has_results and len(p.survey_full) == 12 and len(p.survey_full[0]) == n
        files = build_all(y, tmp_path / tag, lambda m: None)
        assert len(files) == 3 and files[0].suffix == ".xlsx"


def test_apdl_shift_matches_survey():
    """В узлах замера (пояс k, точка j) сдвиг должен равняться (полный − пустой)."""
    import math
    from ansys_report.apdl_gen import delta_table, radial_shift_mm, build_apdl
    p = load_project(Path(__file__).parent.parent / "examples/T001_ansys/project.yaml")
    tbl = delta_table(p)
    s, h = p.raw["survey"], p.tank["belt_height"] / 1000
    n = s["points_per_belt"]
    for k in (1, 5, 12):
        for j in (0, 3, 7, 14):
            a = math.radians(s["start_angle"] - 360 / n * j)
            R = 14.25
            got = radial_shift_mm(p, tbl, k * h, R * math.cos(a), R * math.sin(a))
            want = p.survey_full[k - 1][j] - p.survey_empty[k - 1][j]
            assert abs(got - want) < 1e-6, (k, j, got, want)
    assert abs(radial_shift_mm(p, tbl, 0.0, 14.25, 0.0)) < 1e-9     # днище не двигается
    txt = build_apdl(p)
    assert "NMODIF" in txt and "*DIM,DLT,ARRAY,13,16" in txt and txt.isascii()


def test_report_from_ansys_model_data(tmp_path):
    """Режим «всё из Ansys»: геометрия, сетка, нагрузки и нивелировка «пустой» берутся из model_data.json."""
    import docx
    y = Path(__file__).parent.parent / "examples/T001_model/project.yaml"
    p = load_project(y)
    assert p.tank["belts_thickness"][:3] == [16.0, 14.0, 13.0] and p.tank["wall_height"] == 17880
    assert p.raw["mesh"]["nodes"] == 60694 and p.tank["fill_level"] == 17200
    assert len(p.survey_empty) == 12 and len(p.survey_empty[0]) == 15
    path, _ = build_report(p, tmp_path / "a.docx")
    text = "\n".join(x.text for x in docx.Document(path).paragraphs)
    assert "60694" in text and "734643,9" in text and "62907" not in text


def test_wizard_project_folder(tmp_path):
    """Папка выгрузки + анкета из мастера → project.yaml → Excel/Word (без запуска Ansys)."""
    import shutil
    from ansys_report.ansys_connect import make_project_folder
    from ansys_report.gui import build_all
    src = Path(__file__).resolve().parent.parent / "examples" / "T001_model"
    data = tmp_path / "data"
    shutil.copytree(src, data, ignore=shutil.ignore_patterns("project.yaml", "survey_full.csv", "images"))
    yaml_path = make_project_folder(data, {"number": "ТО-777-26", "year": 2026, "tag": "Т-777", "tank_name": "РВС-1",
                                           "roof_radius": 34200, "executor_name": "Иванов И.И."})
    files = build_all(yaml_path, tmp_path / "out", log=lambda m: None)
    assert any(f.suffix == ".docx" for f in files) and any(f.suffix == ".xlsx" for f in files)
