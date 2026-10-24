"""Пакет нагрузок для Ansys: сочетания нагрузок (расчётные случаи) и файл данных для скрипта apply_loads.py (работает в Mechanical).

Единицы пакета - как в Mechanical «Н-мм-МПа»: давление МПа, длина мм, сила Н. Знак давления в пакете: «+» - изнутри наружу (внутреннее давление),
«−» - снаружи внутрь (вакуум, снег, ветер).
"""
from __future__ import annotations
import csv
import json
from pathlib import Path

from .rvs_loads import PSI, CE


def build_cases(res: dict, design: bool = True, fill_levels_m=None) -> list[dict]:
    """Расчётные случаи. design=True - с коэффициентами надёжности и сочетаний из методики (1,2·p; 1,4·снег; 1,2·ψ·вакуум; 0,5·ψ·ветер)."""
    L, I = res["loads"], res["inputs"]
    g = L["gravity_m_s2"]
    f_p, f_v, f_snow, f_wind = (1.2, 1.2 * PSI["l3"], 1.4 * PSI["t1"] * CE, 0.5 * PSI["t2"]) if design else (1.0, 1.0, CE, 1.0)
    p_over = L["overpressure_mpa"] * f_p
    vac = L["vacuum_mpa"] * f_v
    snow = (L["snow_mpa"]["design"] if design else L["snow_mpa"]["characteristic"])
    wind = [{"z_lo_mm": w["z_bottom_m"] * 1000, "z_hi_mm": w["z_top_m"] * 1000, "p_mpa": -(w["total_mpa"] or 0) * f_wind} for w in L["wind"]]
    ho, hg = L["hydrostatic_operation"], L["hydrostatic_hydrotest"]

    def hydro(h):  # градиент МПа/мм и уровень свободной поверхности, мм
        return {"gradient_mpa_mm": h["density_kg_m3"] * g * 1e-9, "free_surface_mm": h["fill_height_m"] * 1000}
    cases = [
        {"id": "op", "name": "Эксплуатация", "gravity": True, "masses": True, "hydro": hydro(ho), "uniform_mpa": p_over, "roof_extra_mpa": -snow, "wind": []},
        {"id": "op_wind", "name": "Эксплуатация с ветром", "gravity": True, "masses": True, "hydro": hydro(ho), "uniform_mpa": p_over, "roof_extra_mpa": -snow, "wind": wind},
        {"id": "hydrotest", "name": "Гидроиспытания", "gravity": True, "masses": True, "hydro": hydro(hg), "uniform_mpa": 0.0, "roof_extra_mpa": 0.0, "wind": []},
        {"id": "vacuum", "name": "Вакуум, снег и ветер (пустой резервуар)", "gravity": True, "masses": True, "hydro": None,
         "uniform_mpa": -vac, "roof_extra_mpa": -snow, "wind": wind},
    ]
    for lv in (fill_levels_m or []):          # серия уровней налива для определения допустимой высоты (те же давление и снег, без ветра)
        cases.append({"id": "fill_%g" % lv, "name": "Налив %g м" % lv, "gravity": True, "masses": True,
                      "hydro": hydro({"density_kg_m3": ho["density_kg_m3"], "fill_height_m": lv}), "uniform_mpa": p_over, "roof_extra_mpa": -snow, "wind": []})
    return cases


def _json_default(o):
    raise TypeError(type(o))


def write_package(res: dict, out_dir: str | Path, design: bool = True, fill_levels_m=None) -> dict:
    """Записывает loads.json (для просмотра), loads_data.py (для скрипта в Mechanical), loads_summary.csv (таблица для отчёта)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    I, L = res["inputs"], res["loads"]
    data = {
        "geometry": {"diameter_mm": I["D"] * 1000, "wall_height_mm": I["H"] * 1000, "n_belts": I["n_belts"], "belt_height_mm": I["belt_height"] * 1000},
        "gravity_mm_s2": L["gravity_m_s2"] * 1000,
        "cases": build_cases(res, design, fill_levels_m),
        "point_masses": [{"name": m["name"], "category": m["category"], "mass_kg": m["mass_kg"], "location": m["location"]} for m in L["point_masses"]
                         if not m["name"].startswith("Пояс стенки")],
        "belt_z_mm": [[b * I["belt_height"] * 1000, (b + 1) * I["belt_height"] * 1000] for b in range(I["n_belts"])],
        "belt_thickness_mm": [float(t["nominal_mm"]) for t in res["thickness"]],
        "design_factors": design,
        "resistance_mpa": {"operation": float(min(res["materials"]["R_operation"])), "hydrotest": float(res["materials"]["R_hydrotest"])},
    }
    (out / "loads.json").write_text(json.dumps({"input_summary": I, "loads": L, "cases": data["cases"], "notes": res["notes"]}, ensure_ascii=False, indent=1,
                                               default=_json_default), encoding="utf-8")
    (out / "loads_data.py").write_text("# -*- coding: utf-8 -*-\nLOADS = " + repr(data) + "\n", encoding="utf-8")
    rows = [["Нагрузка", "Значение", "Единицы"],
            ["Гидростатика, эксплуатация: плотность продукта", L["hydrostatic_operation"]["density_kg_m3"], "кг/м3"],
            ["Гидростатика, эксплуатация: уровень налива", L["hydrostatic_operation"]["fill_height_m"], "м"],
            ["Гидростатика, гидроиспытания: уровень воды", L["hydrostatic_hydrotest"]["fill_height_m"], "м"],
            ["Избыточное давление", L["overpressure_mpa"] * 1000, "кПа"], ["Вакуум", L["vacuum_mpa"] * 1000, "кПа"],
            ["Снеговая нагрузка (характеристическая)", L["snow_mpa"]["characteristic"] * 1000, "кПа"], ["Снеговая нагрузка (расчётная)", L["snow_mpa"]["design"] * 1000, "кПа"],
            ["Пульсационная составляющая ветра", L["wind_pulsation_kpa"], "кПа"]]
    rows += [[f"Ветер на высоте {w['z_top_m']:g} м (пояс {w['belt']})", None if w["total_mpa"] is None else w["total_mpa"] * 1000, "кПа"] for w in L["wind"]]
    with (out / "loads_summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f, delimiter=";").writerows(rows)
    return {"json": out / "loads.json", "data": out / "loads_data.py", "summary": out / "loads_summary.csv", "cases": data["cases"]}
