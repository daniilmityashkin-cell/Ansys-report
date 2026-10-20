"""Данные для расчёта нагрузок, которые вводит заказчик (поля формы с префиксом l_) → входной словарь модуля ansys_report.loads."""
from __future__ import annotations

from ansys_report.geometry.rvs_core import number
from ansys_report.loads.rvs_loads import SNOW_SG_KPA, WIND_W0_KPA, TERRAIN, compute

DEFAULTS = {"l_on": "1", "l_density": "0.934", "l_fill": "11", "l_hydro": "11", "l_overp": "0", "l_vac": "0", "l_snow": "IV", "l_wind": "II",
            "l_terrain": "A", "l_roof_rise": "3.7", "l_deck": "4", "l_ryn": "420", "l_ins_t": "0", "l_ins_rho": "140", "l_equipment": ""}
SNOW = list(SNOW_SG_KPA)
WIND = list(WIND_W0_KPA)
TERRAINS = list(TERRAIN)


def parse_equipment(text: str, n_belts: int) -> list[dict]:
    """Строки вида «Название; количество; масса одной штуки, кг; пояса (1,2) или крыша» → список позиций оборудования."""
    items = []
    for ln, line in enumerate((text or "").replace("\r", "").split("\n"), 1):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 4:
            raise ValueError(f"Оборудование, строка {ln}: нужно «Название; количество; масса, кг; пояса или крыша».")
        belts, roof = [], False
        for tok in parts[3].replace(" ", ",").split(","):
            tok = tok.strip().lower()
            if not tok:
                continue
            if tok in ("крыша", "roof"):
                roof = True
            else:
                b = int(number(tok, f"Оборудование, строка {ln}: пояс"))
                if not 1 <= b <= n_belts:
                    raise ValueError(f"Оборудование, строка {ln}: пояса от 1 до {n_belts}.")
                belts.append(b)
        if not belts and not roof:
            raise ValueError(f"Оборудование, строка {ln}: укажите пояса или «крыша».")
        items.append({"name": parts[0], "count": number(parts[1], f"Оборудование, строка {ln}: количество"),
                      "mass_kg": number(parts[2], f"Оборудование, строка {ln}: масса"), "category": "equipment", "belts": belts, "roof": roof})
    return items


def build_loads_input(form, project: dict) -> dict | None:
    """None, если расчёт нагрузок не запрошен. Диаметр, высота, число и толщины поясов берутся из замеров."""
    if not form.get("l_on"):
        return None
    f = lambda k: (form.get(k) if form.get(k) not in (None, "") else DEFAULTS[k])
    D, H = number(project["diameter"], "Диаметр"), number(project["height"], "Высота")
    thick = [number(b[1], "Толщина пояса") for b in project["bands"]]
    n = len(thick)
    fill = number(f("l_fill"), "Высота налива")
    if fill > H:
        raise ValueError("Высота налива не может быть больше высоты стенки.")
    snow, wind, terrain = f("l_snow"), f("l_wind"), f("l_terrain").upper()
    if snow not in SNOW or wind not in WIND or terrain not in TERRAINS:
        raise ValueError("Выберите снеговой и ветровой район и тип местности из списков.")
    inp = {
        "diameter_m": D, "wall_height_m": H, "belt_height_m": H / n, "n_belts": n, "thicknesses_mm": thick,
        "product_density_t_m3": number(f("l_density"), "Плотность продукта"), "fill_height_m": fill,
        "hydrotest_height_m": number(f("l_hydro"), "Высота налива воды"), "max_fill_height_m": fill,
        "overpressure_pa": number(f("l_overp"), "Избыточное давление"), "vacuum_pa": number(f("l_vac"), "Вакуум"),
        "snow_district": snow, "wind_district": wind, "terrain": terrain, "aero_coef": 0.8,
        "roof_rise_m": number(f("l_roof_rise"), "Подъём крыши"), "roof_deck_thickness_m": number(f("l_deck"), "Толщина настила крыши") / 1000,
        "ryn_mpa": number(f("l_ryn"), "Предел текучести стали"), "e_mpa": 206000, "steel_density_kg_m3": 7850, "g": 9.8, "water_density_kg_m3": 1000,
        "gamma_m": 1.1, "gamma_n": 1.1, "gamma_c1": 0.7, "gamma_c2": 0.8, "gamma_c_rest": 0.8, "gamma_c_hydro": 0.9,
        "corrosion_weak_mm_year": 0.05, "corrosion_medium_mm_year": 0.1, "service_life_years": 40, "anticorrosion_life_years": 10, "diagnostics_interval_years": 10,
        "insulation_thickness_m": number(f("l_ins_t"), "Толщина теплоизоляции") / 1000, "insulation_density_kg_m3": number(f("l_ins_rho"), "Плотность теплоизоляции"),
        "equipment": parse_equipment(form.get("l_equipment", ""), n),
    }
    if inp["roof_rise_m"] <= 0 or inp["product_density_t_m3"] <= 0:
        raise ValueError("Подъём крыши и плотность продукта должны быть положительными.")
    compute(inp)         # проверка: расчёт должен сходиться на этих данных
    return inp
