"""Тесты на обезличенном примере examples/demo (данные получены из реального проекта Ansys)."""
from pathlib import Path
import openpyxl
from ansys_report.project import load_project
from ansys_report.calc import calc_all
from ansys_report.excel_gen import build_excel
from ansys_report.word_gen import build_report

YAML = Path(__file__).parent.parent / "examples/demo/project.yaml"


def test_design_numbers():
    c = calc_all(load_project(YAML))
    assert round(c["R1"], 2) == 206.35 and round(c["R2"], 2) == 235.83 and round(c["Rutor"], 2) == 353.74
    assert round(c["E2"], 1) == 743.7 and round(c["allow"], 1) == 216.7
    assert c["strength_ok"] and c["kmin"] > 10 and c["stability_ok"]


def test_excel_and_word_build(tmp_path):
    p = load_project(YAML)
    x = build_excel(p, tmp_path / "a.xlsx")
    wb = openpyxl.load_workbook(x)
    assert wb.sheetnames == ["Т-001 полный", "Т-001 пустой", "Проверка"]
    docx_path, missing = build_report(p, tmp_path / "a.docx")
    assert docx_path.stat().st_size > 10_000 and "fig01_general" in missing



def test_gui_core(tmp_path):
    from ansys_report.gui import build_all
    msgs = []
    files = build_all(YAML, tmp_path, msgs.append)
    assert len(files) == 4 and all(f.exists() for f in files) and any("Word" in m for m in msgs)


def test_apdl_shift_matches_survey():
    """В узлах замера (пояс k, точка j) сдвиг должен равняться (полный − пустой)."""
    import math
    from ansys_report.apdl_gen import delta_table, radial_shift_mm, build_apdl
    p = load_project(Path(__file__).parent.parent / "examples/demo/project.yaml")
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
    y = Path(__file__).parent.parent / "examples/demo/project.yaml"
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
    src = Path(__file__).resolve().parent.parent / "examples" / "demo"
    data = tmp_path / "data"
    shutil.copytree(src, data, ignore=shutil.ignore_patterns("project.yaml", "survey_full.csv", "images"))
    yaml_path = make_project_folder(data, {"number": "ТО-777-26", "year": 2026, "tag": "Т-777", "tank_name": "РВС-1",
                                           "roof_radius": 34200, "executor_name": "Иванов И.И."})
    files = build_all(yaml_path, tmp_path / "out", log=lambda m: None)
    assert any(f.suffix == ".docx" for f in files) and any(f.suffix == ".xlsx" for f in files)


def test_roles_and_custom_belt_regex(tmp_path):
    """Соответствия: роли расчётов выбираются по настройке/имени, имена поясов — по регулярному выражению."""
    import json
    import re
    import shutil
    from ansys_report.settings import ModelSettings, pick_roles
    from ansys_report.ansys_connect import make_project_folder
    from ansys_report import ansys_import as ai
    names = ["Static Structural", "Static Structural 2", "Eigenvalue Buckling", "Static Structural Full"]
    assert pick_roles(names, ModelSettings()) == ("Static Structural Full", "Static Structural 2")
    assert pick_roles(names, ModelSettings(full_analysis="Static Structural", empty_analysis="Static Structural 2")) == \
        ("Static Structural", "Static Structural 2")
    assert pick_roles(["Eigenvalue Buckling"], ModelSettings()) == (None, None)
    src = Path(__file__).resolve().parent.parent / "examples" / "demo"
    data = tmp_path / "d"
    shutil.copytree(src, data, ignore=shutil.ignore_patterns("project.yaml", "survey_full.csv", "images"))
    # пояса названы иначе: «Belt_01…Belt_12»
    md = json.loads((data / "model_data.json").read_text(encoding="utf-8"))
    for b in md["bodies"]:
        m = re.match(r"^p\s*(\d+)$", b["name"])
        if m:
            b["name"] = "Belt_%02d" % int(m.group(1))
    md["belt_regex"] = r"^Belt_(\d+)$"
    (data / "model_data.json").write_text(json.dumps(md), encoding="utf-8")
    assert len(ai.belt_bodies(md)) == 12
    st = ModelSettings(buckling_labels={"Eigenvalue Buckling": "Ветер A", "Eigenvalue Buckling 2": "Ветер B"})
    p = load_project(make_project_folder(data, {"number": "N", "year": 2026, "tag": "T-1", "roof_radius": 1}, st))
    assert p.has_results and p.results_empty and "Ветер A" in p.stability[0]["case"]


def _renamed_demo(tmp_path):
    """Копия примера с другими именами: пояса «Ring_01…», расчёты «Strength …/Buckle …» (проверка автоматики соответствий)."""
    import json
    import re
    import shutil
    src = Path(__file__).resolve().parent.parent / "examples" / "demo"
    data = tmp_path / "renamed"
    shutil.copytree(src, data, ignore=shutil.ignore_patterns("project.yaml", "survey_full.csv", "images"))
    ren = {"Static Structural Full": "Strength Full", "Static Structural 2": "Strength Empty",
           "Static Structural": "Strength Wind", "Eigenvalue Buckling 2": "Buckle Z", "Eigenvalue Buckling": "Buckle Y"}

    def new(name):
        for old in sorted(ren, key=len, reverse=True):      # сначала длинные имена
            if name == old:
                return ren[old]
        return name

    md = json.loads((data / "model_data.json").read_text(encoding="utf-8"))
    for b in md["bodies"]:
        m = re.match(r"^p\s*(\d+)$", b["name"])
        if m:
            b["name"] = "Ring_%02d" % int(m.group(1))
    md["belt_regex"] = r"^Ring_(\d+)$"
    for a in md["analyses"]:
        a["name"] = new(a["name"])
    (data / "model_data.json").write_text(json.dumps(md), encoding="utf-8")
    for f in list(data.glob("*_belts.csv")):
        base = f.stem[: -len("_belts")].replace("_", " ")
        f.rename(data / (new(base).replace(" ", "_") + "_belts.csv"))
    rows = (data / "stability.csv").read_text(encoding="utf-8").splitlines()
    (data / "stability.csv").write_text("\n".join([rows[0]] + [new(r.split(",")[0]) + "," + ",".join(r.split(",")[1:]) for r in rows[1:]]),
                                         encoding="utf-8")
    img = data / "images"
    img.mkdir()
    from docx.shared import Pt  # noqa: F401  (python-docx уже нужен)
    import struct, zlib
    png = (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0) +
           struct.pack(">I", zlib.crc32(b"IHDR" + struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))) + struct.pack(">I", 12) + b"IDAT" +
           zlib.compress(b"\x00\x00\x00\x00") + struct.pack(">I", zlib.crc32(b"IDAT" + zlib.compress(b"\x00\x00\x00\x00"))) +
           struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND")))
    for n in ("Strength_Full_Equivalent_Stress", "Strength_Empty_Equivalent_Stress", "Buckle_Y_Total_Deformation",
              "Buckle_Z_Total_Deformation_2"):
        (img / (n + ".png")).write_bytes(png)
    return data


def test_renamed_project_gives_same_report(tmp_path):
    from ansys_report.settings import ModelSettings
    from ansys_report.ansys_connect import make_project_folder
    from ansys_report.gui import build_all
    orig = calc_all(load_project(YAML))
    data = _renamed_demo(tmp_path)
    st = ModelSettings(belt_regex=r"^Ring_(\d+)$", static_prefix="Strength", buckling_prefix="Buckle",
                       buckling_labels={"Buckle Y": "Направление ветра Y", "Buckle Z": "Направление ветра Z"})
    y = make_project_folder(data, {"number": "N", "year": 2026, "tag": "T-2", "roof_radius": 1}, st)
    p = load_project(y)
    c = calc_all(p)
    assert c["max_eq"] == orig["max_eq"] and c["max_fiber"] == orig["max_fiber"] and c["kmin"] == orig["kmin"]
    assert [s["case"] for s in c["stability"]][0].startswith("Направление ветра Y")
    assert p.raw["ansys"]["analysis_full"] == "Strength Full"
    assert p.raw["images"]["fig06_eq_stress"] == "Strength_Full_Equivalent_Stress.png"
    assert p.raw["images"]["fig10_empty_eq"] == "Strength_Empty_Equivalent_Stress.png"
    assert p.raw["images"]["fig_stab1"] == "Buckle_Y_Total_Deformation.png"
    files = build_all(y, tmp_path / "out", log=lambda m: None)
    assert any(f.suffix == ".docx" for f in files)
