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
