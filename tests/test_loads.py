"""Расчёт нагрузок: сверка с числами самого Excel (пример РВСП-10000, Уренгой)."""
import json
from pathlib import Path

import pytest

from ansys_report.loads.rvs_loads import compute, wind_nu

DATA = json.loads((Path(__file__).parent / "data" / "loads_excel_10000.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def res():
    return compute(DATA["input"])


def close(a, b, rel=1e-6, abs_=1e-9):
    assert a == pytest.approx(b, rel=rel, abs=abs_)


def test_thickness_and_masses_match_excel(res):
    x = DATA["excel"]
    close(res["materials"]["dt_minus_mm"], x["dtm"])
    for i, t in enumerate(res["thickness"]):
        close(t["td_mm"], x["td"][i]); close(t["tg_mm"], x["tg"][i]); close(t["nominal_pre_mm"], x["L"][i])
    r = res["roof"]
    close(r["radius_m"], x["roof_R"]); close(r["area_m2"], x["roof_area"]); close(r["deck_mass_kg"], x["deck_mass"])
    close(r["insulation_mass_kg"], x["roof_insul"]); close(r["ring_mass_kg"], x["ring_mass"]); close(r["beams_mass_kg"], x["beams_mass"])
    close(r["metal_mass_kg"], x["roof_metal"]); close(res["wall"]["insulation_mass_kg"], x["wall_insul"]); close(res["wall"]["belt_mass_kg"][0], x["belt_mass1"])


def test_weights_above_point_match_excel(res):
    x = DATA["excel"]
    for key, name in (("Gm", "metal"), ("Go", "equipment"), ("Gt", "insulation")):
        for a, b in zip(res["weights_above_mn"][name], x[key]):
            close(a, b)


def test_strength_matches_excel(res):
    x = DATA["excel"]
    for i, s in enumerate(res["strength"]):
        close(s["hoop_mpa"], x["sigma2"][i]); close(s["meridional_mpa"], x["sigma1"][i]); close(s["equivalent_mpa"], x["sigma_eq"][i])
        close(s["resistance_mpa"], x["R"][i]); assert s["ok"] is True


def test_frequency_and_wind_match_excel(res):
    x = DATA["excel"]
    for a, b in zip(res["frequency"]["f_hz"][:5], x["f"]):
        close(a, b, rel=1e-5)
    close(res["frequency"]["f_lim_hz"], x["flim"]); assert res["frequency"]["static_wind_ok"] is x["static"]
    close(res["frequency"]["z_eq_m"], x["zeq"]); close(res["nu"], x["nu"])
    for i, w in enumerate(res["wind"]):
        close(w["wm_kpa"], x["wm"][i]); close(w["k"], x["k"][i]); close(w["zeta"], x["zeta"][i]); close(w["w_mpa"], x["w"][i])
    close(res["wind_pulsation_kpa"], x["wg"])


def test_stability_matches_excel(res):
    x = DATA["excel"]
    st = res["stability"]
    close(st["sigma1_cr_mpa"], x["sigma1cr"]); close(st["sigma2_cr_mpa"], x["sigma2cr"], rel=1e-6)
    for i, b in enumerate(st["belts"]):
        close(b["hoop_mpa"], x["s2"][i]); close(b["meridional_mpa"], x["s1"][i]); close(b["utilization"], x["U"][i]); close(b["reduced_height_m"], x["Hr"][i])
    close(res["ring_modulus_cm3"], x["ring_W"])


def test_loads_for_ansys_and_validation():
    res = compute(DATA["input"])
    L = res["loads"]
    assert L["snow_mpa"]["design"] == pytest.approx(1.4 * 0.85 * 2.0 / 1000)
    assert L["hydrostatic_operation"]["density_kg_m3"] == pytest.approx(934)
    assert len(L["wind"]) == 8 and L["wind"][0]["z_top_m"] == pytest.approx(1.5)
    assert any(m["location"] == "roof" for m in L["point_masses"]) and any(m["location"] == "belt_1" for m in L["point_masses"])
    bad = dict(DATA["input"], snow_district="XX")
    with pytest.raises(ValueError):
        compute(bad)
    bad = dict(DATA["input"], thicknesses_mm=[9, 9])
    with pytest.raises(ValueError):
        compute(bad)
    close(wind_nu(14.59, 34.2), 0.72822)


def test_package_for_ansys(tmp_path):
    from ansys_report.loads.export import write_package, build_cases
    res = compute(DATA["input"])
    assert [c["id"] for c in build_cases(res)] == ["op", "vacuum"]                      # по умолчанию - только случаи, входящие в отчёт
    pack = write_package(res, tmp_path, all_cases=True)
    ns = {}
    exec((tmp_path / "loads_data.py").read_text(encoding="utf-8"), ns)               # файл данных исполняется как обычный Python (так читает скрипт в Mechanical)
    L = ns["LOADS"]
    assert [c["id"] for c in L["cases"]] == ["op", "op_wind", "hydrotest", "vacuum"]
    assert L["geometry"]["diameter_mm"] == pytest.approx(34200) and L["geometry"]["n_belts"] == 8
    op = L["cases"][0]
    assert op["hydro"]["gradient_mpa_mm"] == pytest.approx(934 * 9.8e-9)             # МПа/мм
    assert op["roof_extra_mpa"] == pytest.approx(-1.4 * 0.85 * 2 / 1000)             # снег на крыше, расчётный
    wind = L["cases"][1]["wind"]
    assert len(wind) == 8 and wind[0]["z_lo_mm"] == 0 and wind[-1]["z_hi_mm"] == pytest.approx(12000) and all(w["p_mpa"] < 0 for w in wind)
    assert L["cases"][3]["hydro"] is None and L["cases"][3]["uniform_mpa"] == 0       # вакуум в примере = 0
    roof = [m for m in L["point_masses"] if m["location"] == "roof"]
    assert any("изоляция" in m["name"].lower() for m in roof)
    assert (tmp_path / "loads_summary.csv").read_text(encoding="utf-8-sig").startswith("Нагрузка;Значение")
    characteristic = build_cases(res, design=False)[0]
    assert characteristic["roof_extra_mpa"] == pytest.approx(-0.85 * 2 / 1000)


def test_apply_loads_script_is_valid_python():
    import ast
    ast.parse((Path(__file__).parents[1] / "ansys_scripts" / "apply_loads.py").read_text(encoding="utf-8"))


def _build_model_funcs(pkg, parts, nodes, wall_h):
    """Функции apdl_* из ansys_scripts/build_model.py (IronPython) на синтетической сетке: ExtAPI подменён."""
    import ast, io, math, os, types
    src = (Path(__file__).parents[1] / "ansys_scripts" / "build_model.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("_rd", "apdl_beams", "node_ranges", "apdl_band")]
    nd = [types.SimpleNamespace(Id=i, X=x, Y=y, Z=z) for i, (x, y, z) in enumerate(nodes, 1)]
    md = types.SimpleNamespace(Nodes=nd, NodeById=lambda i: nd[i - 1])
    api = types.SimpleNamespace(DataModel=types.SimpleNamespace(MeshDataByName=lambda name: md))
    g = {"os": os, "io": io, "math": math, "pkg": str(pkg), "parts": parts, "WALL_H": wall_h, "ExtAPI": api, "bsay": lambda t: None}
    exec(compile(tree, "build_model.py", "exec"), g)
    return g


def test_roof_beams_rbe3_and_edge_rings_on_out_of_round_wall(tmp_path, monkeypatch):
    import json, math
    monkeypatch.setenv("ANSYS_REPORT_MESH_MM", "200")
    R, H = 5000.0, 6000.0
    nodes = []
    for k in range(160):                                       # стенка: кромка z=H некруглая (+-60 мм), два ряда ниже
        a = 2 * math.pi * k / 160
        r = R + 60 * math.cos(3 * a)
        for z in (H, H - 200, H - 400):
            nodes.append((r * math.cos(a), r * math.sin(a), z))
        for j in range(1, 20):                                 # крыша: кольца узлов внутрь от кромки
            rr = r - 200 * j
            nodes.append((rr * math.cos(a), rr * math.sin(a), H + 10 * j))
    (tmp_path / "beams.json").write_text(json.dumps({
        "wall_radius_mm": R, "central_radius_mm": 1200.0, "radial_count": 8, "first_angle_deg": 0.0,
        "radial": {"A": 3765.6, "Iyy": 4.05e7, "Izz": 4.05e7, "J": 77454.0, "D": 250.0, "B": 125.0},
        "edge": {"A": 3063.9, "Iyy": 1.58e7, "Izz": 1.58e7, "J": 72878.5, "D": 240.0, "B": 90.0},
        "top_ring": {"A": 2000.0, "Iyy": 6.67e6, "Izz": 16666.7, "J": 66666.7, "D": 200.0, "B": 10.0}}), encoding="utf-8")
    parts = {"roof_mm": 7.0, "band_width_mm": 1000.0, "band_mm": 10.0}
    g = _build_model_funcs(tmp_path, parts, nodes, H)
    t = g["apdl_beams"]().splitlines()
    assert t[0] == "/PREP7" and t[-1] == "/SOLU"
    assert sum(1 for s in t if s.startswith("N,nb0+")) == 8 and sum(1 for s in t if s.startswith("RBE3,nb0+") and s.endswith(",ALL,ALL")) == 8
    assert sum(1 for s in t if s.startswith("E,") and "nb0+" in s) == 8       # последний элемент каждой радиальной балки - на отдельный узел
    assert not any(s.startswith("CERIG") for s in t)
    top = {i for i, (x, y, z) in enumerate(nodes, 1) if z == H}
    e_ring = [s for s in t if s.startswith("E,") and "nb0" not in s and {int(v) for v in s[2:].split(",")} <= top]
    assert len(e_ring) == 2 * 160                              # опорное и периферийное кольца замкнуты по всей кромке, а не по |r-R|<5
    i_rbe = t.index("RBE3,nb0+1,ALL,ALL")                      # узлы связи: в радиусе 500 мм (половина опорной полосы), кромка стенки и крыша
    sel = []
    for s in t[max(i for i in range(i_rbe) if t[i] == "NSEL,NONE") + 1:i_rbe]:
        a = [int(v) for v in s.split(",")[4:]]
        sel += list(range(a[0], a[-1] + 1))
    zs = {nodes[i - 1][2] for i in sel}
    assert 5 < len(sel) < 40 and min(zs) == H and max(zs) > H
    b = g["apdl_band"]().splitlines()
    assert "SECDATA,10.0,matid,0,3" in b and "EMODIF,ALL,SECNUM,984" in b
    assert g["node_ranges"]([5, 3, 4, 9]) == ["NSEL,A,NODE,,3,5", "NSEL,A,NODE,,9"]
    parts["band_mm"] = 7.0                                     # полоса не толще настила - секция не нужна
    assert g["apdl_band"]() == ""


def test_wind_rings_snap_to_belt_boundaries():
    from ansys_report.loads.beams import wind_rings, beams_package
    p = {"heights": [0, 1.5, 3.0, 4.5, 6.0], "wind_rings": [{"h": 3.2, "flange": "100 × 10"}, {"h": 4.4}]}
    r = wind_rings(p)
    assert [x["z_m"] for x in r] == [3.0, 4.5]
    assert r[0]["A"] == 1000.0 and abs(r[0]["Iyy"] - 10 * 100 ** 3 / 12) < 1
    assert beams_package(p, 14000.0)["wind_rings"] == r          # без крыши - только кольца
