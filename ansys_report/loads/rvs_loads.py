"""Расчёт нагрузок на вертикальный стальной резервуар (РВС/РВСП): перенос методики из Excel «Расчёт резервуара на прочность и устойчивость»
(ГОСТ 31385-2016, СП 20.13330). Входные данные вводит заказчик, на выходе - нагрузки для прикладывания в Ansys и проверки прочности и устойчивости.

Ссылки вида [C29] - ячейки исходного Excel. Места, где Excel содержит особенности, перенесены как есть и помечены «Excel:»;
их нужно подтвердить у автора методики (см. поле `notes` результата).
"""
from __future__ import annotations
import math

SNOW_SG_KPA = {"I": 0.5, "II": 1.0, "III": 1.5, "IV": 2.0, "V": 2.5, "VI": 3.0, "VII": 3.5, "VIII": 4.0}          # [I4] расчётное значение веса снегового покрова
WIND_W0_KPA = {"Ia": 0.17, "I": 0.23, "II": 0.30, "III": 0.38, "IV": 0.48, "V": 0.60, "VI": 0.73, "VII": 0.85}  # [I6] нормативное ветровое давление
TERRAIN = {"A": {"k10": 1.0, "alpha": 0.15, "zeta10": 0.76}, "B": {"k10": 0.65, "alpha": 0.20, "zeta10": 1.06}, "C": {"k10": 0.4, "alpha": 0.25, "zeta10": 1.78}}  # [E146:H150]
# [L147:S154] коэффициент пространственной корреляции пульсаций ветра: строки - диаметр, столбцы - высота
NU_D = [0.1, 5, 10, 20, 40, 80, 160]
NU_H = [5, 10, 20, 40, 80, 160, 350]
NU_TABLE = [[0.95, 0.92, 0.88, 0.83, 0.76, 0.67, 0.56], [0.89, 0.87, 0.84, 0.80, 0.73, 0.65, 0.54], [0.85, 0.84, 0.81, 0.77, 0.71, 0.64, 0.53],
            [0.80, 0.78, 0.76, 0.73, 0.68, 0.61, 0.51], [0.72, 0.72, 0.70, 0.67, 0.63, 0.57, 0.48], [0.63, 0.63, 0.61, 0.59, 0.56, 0.51, 0.44],
            [0.53, 0.53, 0.52, 0.50, 0.47, 0.44, 0.38]]
PSI = {"l1": 1.0, "l2": 0.95, "l3": 0.95, "t1": 1.0, "t2": 0.9, "t3": 0.7}       # [M100:M105] коэффициенты сочетаний нагрузок
CE = 0.85                                                                       # [M106] коэффициент, учитывающий снос снега
BETA_M = [1.8751, 4.69409, 7.85476, 10.99554, 14.13717]                          # [B123:B127]


def _num(d: dict, key: str, default=None):
    v = d.get(key, default)
    if v is None:
        raise ValueError(f"Не задано: {key}")
    return float(v)


def _match(arr: list[float], x: float) -> int:
    """Как MATCH(x; массив; 1) в Excel, индекс с нуля; значение меньше первого - берётся первый интервал."""
    i = 0
    for k, a in enumerate(arr):
        if a <= x:
            i = k
    return i


def min_constructive_thickness_mm(D: float) -> float:       # [J30]
    return 5 if D <= 16 else 6 if D <= 25 else 8 if D <= 40 else 10 if D <= 65 else 12


def minus_tolerance_mm(D: float) -> float:                   # [F14] Excel: выбирается по диаметру D (а не по толщине листа) - перенесено как есть
    return 0.5 if D <= 16 else 0.6 if D <= 25 else 0.8


def wind_k(terrain: str, z: float) -> float:                 # [M137:M144], [C147]
    t = TERRAIN[terrain]
    if terrain == "A":
        if z <= 5: return 0.75
        if z <= 10: return 0.5 + 0.05 * z
    elif terrain == "B":
        if z <= 5: return 0.5
        if z <= 10: return 0.35 + 0.03 * z
    else:
        if z <= 10: return 0.4
    return t["k10"] * (z / 10) ** (2 * t["alpha"])


def wind_zeta(terrain: str, z: float) -> float:              # [O137:O144]
    t = TERRAIN[terrain]
    if terrain == "A":
        if z <= 5: return 0.85
        if z <= 10: return 0.94 - 0.018 * z
    elif terrain == "B":
        if z <= 5: return 1.22
        if z <= 10: return 1.38 - 0.032 * z
    else:
        if z <= 10: return 1.78
    return t["zeta10"] * (z / 10) ** (-t["alpha"])


def wind_nu(H_total: float, D: float) -> float:              # [V146:V164] двойная линейная интерполяция по таблице корреляции
    ih = min(_match(NU_H, H_total), len(NU_H) - 2)
    idm = min(_match(NU_D, D), len(NU_D) - 2)
    h1, h2, d1, d2 = NU_H[ih], NU_H[ih + 1], NU_D[idm], NU_D[idm + 1]
    c_d1h1, c_d2h1, c_d1h2, c_d2h2 = NU_TABLE[idm][ih], NU_TABLE[idm + 1][ih], NU_TABLE[idm][ih + 1], NU_TABLE[idm + 1][ih + 1]
    dh, dd = h2 - H_total, d2 - D
    v_d1 = c_d1h2 - dh * (c_d1h2 - c_d1h1) / (h2 - h1)
    v_d2 = c_d2h2 - dh * (c_d2h2 - c_d2h1) / (h2 - h1)
    return v_d2 + dd * (v_d1 - v_d2) / (d2 - d1)


def model_params(inp: dict, w0_kpa: float) -> dict:
    """Данные расчётной модели Ansys из «Данных для отчёта» (как в эталоне Т-001, tools/diag/etalon_T001_wb.md):
    material - сталь заказчика (только заданные поля, иначе материал Mechanical не трогаем);
    roof_force_n - F = γf·(Mкр + ψ·ΣMоб)·g, g = 9,81 (как в формуле раздела 4), прикладывается к верхней кромке стенки вместо веса крыши по геометрии;
    wind_disturbance_mpa - ветер-возмущение для устойчивости: нормативное давление w0 вектором по всей стенке (в эталоне 300 Па)."""
    mat = {}
    for key, name in (("e_mpa", "e_mpa"), ("poisson", "poisson"), ("steel_density_kg_m3", "density_kg_m3")):
        if inp.get(key) not in (None, ""):
            mat[name] = _num(inp, key)
    out = {"material": mat, "wind_disturbance_mpa": w0_kpa / 1000.0}
    if inp.get("roof_mass_kg") not in (None, ""):
        eq = [float(x) for x in (inp.get("roof_equipment_kg") or [])]
        gf, psi = _num(inp, "roof_gf", 1.05), _num(inp, "psi", 0.95)
        out["roof_force_n"] = gf * (_num(inp, "roof_mass_kg") + psi * sum(eq)) * 9.81
    return out


def compute(inp: dict) -> dict:
    """Полный расчёт. Единицы входа: м, мм, кг, Па, МПа, кг/м3 (плотность продукта - т/м3), как в Excel."""
    D, Hw, hb = _num(inp, "diameter_m"), _num(inp, "wall_height_m"), _num(inp, "belt_height_m")
    n = int(_num(inp, "n_belts"))
    rho, g = _num(inp, "product_density_t_m3"), _num(inp, "g", 9.8)
    p_pa, pv_pa = _num(inp, "overpressure_pa", 0), _num(inp, "vacuum_pa", 0)
    Hop, Hgt = _num(inp, "fill_height_m"), _num(inp, "hydrotest_height_m", inp.get("fill_height_m"))
    Hmax = _num(inp, "max_fill_height_m", Hop)
    ryn, E = _num(inp, "ryn_mpa"), _num(inp, "e_mpa", 206000)
    gm, gn = _num(inp, "gamma_m", 1.1), _num(inp, "gamma_n", 1.1)
    rho_s = _num(inp, "steel_density_kg_m3", 7790)
    hk = _num(inp, "roof_rise_m")
    notes: list[str] = []
    if abs(Hw - hb * n) > 1e-6:
        notes.append(f"Высота стенки {Hw} м не равна числу поясов × высота пояса ({n} × {hb} м).")
    snow_d, wind_d, terrain = str(inp.get("snow_district", "")), str(inp.get("wind_district", "")), str(inp.get("terrain", "A")).upper()
    if inp.get("snow_kpa") is None and snow_d not in SNOW_SG_KPA: raise ValueError("Снеговой район: I…VIII")
    if inp.get("wind_kpa") is None and wind_d not in WIND_W0_KPA: raise ValueError("Ветровой район: Ia, I…VII")
    if terrain not in TERRAIN: raise ValueError("Тип местности: A, B или C")
    # снег и ветер числом (кПа, как в исходных данных заказчика) приоритетнее района
    Sg = float(inp["snow_kpa"]) if inp.get("snow_kpa") is not None else SNOW_SG_KPA[snow_d]
    w0 = float(inp["wind_kpa"]) if inp.get("wind_kpa") is not None else WIND_W0_KPA[wind_d]
    gf_snow = float(inp.get("snow_gf") or 1.4)

    # --- расчётные сопротивления [C29:C34]
    R_op = [ryn * inp_g / gm / gn for inp_g in (_num(inp, "gamma_c1", 0.7), _num(inp, "gamma_c2", 0.8), _num(inp, "gamma_c_rest", 0.8))]
    R_gt = ryn * _num(inp, "gamma_c_hydro", 0.9) / gm / gn
    dtm = minus_tolerance_mm(D)
    # --- припуск на коррозию [F20:F23]
    life, anti, interval = _num(inp, "service_life_years", 40), _num(inp, "anticorrosion_life_years", 10), _num(inp, "diagnostics_interval_years", 10)
    unprotected = max(interval - anti, 0)
    checks = math.floor(life / interval)
    dtc_weak = checks * unprotected * _num(inp, "corrosion_weak_mm_year", 0.05)
    dtc_med = checks * unprotected * _num(inp, "corrosion_medium_mm_year", 0.1)
    dtc = [dtc_med if i in (0, n - 1) else dtc_weak for i in range(n)]

    # --- предварительная толщина поясов [F30:L37]
    def hoop_head(i: int, H: float) -> float:      # (ρ g (H - h (i-1)) + 1.2 p) · D/2 , МПа·м
        return (0.001 * rho * g * (H - hb * i) + 1.2 * p_pa * 1e-6) * D / 2
    td, tg, thick_pre = [], [], []
    for i in range(n):
        Ri = R_op[min(i, 2)]
        td.append(hoop_head(i, Hop) / Ri * 1000)
        tg.append(hoop_head(i, Hop) / R_gt * 1000)     # Excel: в строке гидроиспытаний взяты плотность продукта и уровень эксплуатации [H30]
        thick_pre.append(math.ceil(max(td[i] + dtc[i] + dtm, tg[i] + dtm, min_constructive_thickness_mm(D) + dtm) - 1e-12))
    notes.append("Excel [H30:H37]: проверка при гидроиспытаниях считается с плотностью продукта и уровнем эксплуатации (N5), а не воды и уровня гидроиспытаний (N6).")
    notes.append("Excel [F14]: минусовой допуск проката выбирается по диаметру резервуара, а не по толщине листа.")
    nominal = [float(x) for x in inp["thicknesses_mm"]] if inp.get("thicknesses_mm") else [float(x) for x in thick_pre]
    if len(nominal) != n:
        raise ValueError(f"Толщин поясов {len(nominal)}, а поясов {n}.")
    tr = [(nominal[i] - dtm - dtc[i]) / 1000 for i in range(n)]       # расчётные толщины, м [C137:C144]

    # --- массы [S29:S51]
    Rroof = hk / 2 + D ** 2 / (8 * hk)
    Aroof = 2 * math.pi * Rroof * hk
    deck_mass = Aroof * _num(inp, "roof_deck_thickness_m") * rho_s
    ins_t, ins_rho = _num(inp, "insulation_thickness_m", 0), _num(inp, "insulation_density_kg_m3", 0)
    roof_ins_mass = float(inp["roof_insulation_kg"]) if inp.get("roof_insulation_kg") is not None else Aroof * ins_t * ins_rho
    ring_mass = 3.14 * D * _num(inp, "roof_support_ring_kg_m", 0)         # Excel: π принято равным 3,14
    beams_mass = (_num(inp, "roof_radial_beam_kg_m", 0) * _num(inp, "roof_radial_beam_length_m", 0) * _num(inp, "roof_radial_beams_count", 0)
                  + _num(inp, "roof_ring_beam_kg_m", 0) * _num(inp, "roof_ring_beams_length_m", 0))
    roof_metal = deck_mass + beams_mass + ring_mass
    wall_ins_mass = float(inp["wall_insulation_kg"]) if inp.get("wall_insulation_kg") is not None else math.pi * D * Hw * ins_t * ins_rho
    belt_mass = [rho_s * hb * math.pi / 4 * ((D + nominal[i] / 1000) ** 2 - D ** 2) for i in range(n)]

    # --- распределение масс по поясам и крыше (колонки: пояса 0..n-1 и крыша n) [A55:Z87]
    mass = {"metal": [0.0] * (n + 1), "equipment": [0.0] * (n + 1), "insulation": [0.0] * (n + 1)}
    items = [{"name": "Радиальные и кольцевые балки", "category": "metal", "total_kg": beams_mass, "belts": [], "roof": True},
             {"name": "Настил крыши", "category": "metal", "total_kg": deck_mass, "belts": [], "roof": True},
             {"name": "Опорное кольцо крыши", "category": "metal", "total_kg": ring_mass, "belts": [n], "roof": False},
             {"name": "Тепловая изоляция крыши", "category": "insulation", "total_kg": roof_ins_mass, "belts": [], "roof": True},
             {"name": "Тепловая изоляция стенки", "category": "insulation", "total_kg": wall_ins_mass, "belts": list(range(1, n + 1)), "roof": False}]
    items += [{"name": f"Пояс стенки {i + 1}", "category": "metal", "total_kg": belt_mass[i], "belts": [i + 1], "roof": False} for i in range(n)]
    for e in inp.get("equipment", []) or []:
        items.append({"name": e.get("name", ""), "category": e.get("category", "equipment"), "total_kg": float(e["count"]) * float(e["mass_kg"]),
                      "belts": [int(b) for b in e.get("belts", [])], "roof": bool(e.get("roof"))})
    placed = []
    for it in items:
        spots = [b - 1 for b in it["belts"]] + ([n] if it["roof"] else [])
        if not spots:
            raise ValueError(f"Позиция «{it['name']}» не привязана ни к поясу, ни к крыше.")
        share = it["total_kg"] / len(spots)
        for s in spots:
            mass[it["category"]][s] += share
        placed.append({**it, "per_spot_kg": share, "spots": spots})
    # масса выше расчётной точки (низ пояса i) = пояса i..n и крыша [R88:Z90]
    above = {c: [sum(mass[c][i:]) for i in range(n + 1)] for c in mass}
    Gm = [m * g * 1e-6 for m in above["metal"]]
    Go = [m * g * 1e-6 for m in above["equipment"]]
    Gt = [m * g * 1e-6 for m in above["insulation"]]

    # --- прочность стенки [A99:J106]
    snow_design = gf_snow * PSI["t1"] * CE * Sg / 1000      # МПа
    snow_char = CE * Sg / 1000
    if inp.get("snow_line_n_m") not in (None, ""):           # снег задан погонной силой на кромку (как в эталоне Т-001): Fсн = r·S/2 -> S = 2·Fсн/r
        snow_design = 2 * float(inp["snow_line_n_m"]) / (D / 2) * 1e-6
        snow_char = snow_design / (gf_snow * PSI["t1"] * CE)
    strength = []
    for i in range(n):
        hoop = (0.001 * rho * g * (Hop - hb * i) + 1.2 * p_pa * 1e-6) * (D / 2) / tr[i]
        mer = ((1.05 * Gm[i] + 1.05 * Go[i] * PSI["l1"] + 1.3 * Gt[i] * PSI["l2"]) / (2 * 3.14 * (D / 2) * tr[i]) + snow_design / tr[i] * (D / 2))
        eq = math.sqrt(mer ** 2 + mer * hoop + hoop ** 2)
        Ri = R_op[min(i, 2)]
        strength.append({"belt": i + 1, "hoop_mpa": hoop, "meridional_mpa": mer, "equivalent_mpa": eq, "resistance_mpa": Ri, "ok": Ri >= eq})

    # --- собственные частоты [A109:D132]
    mu_w = math.pi * (D / 2) ** 2 * _num(inp, "water_density_kg_m3", 1000)
    tr_avg = sum(tr) / n
    mu_s = 2 * math.pi * (D / 2) * tr_avg * rho_s
    mu_i = 2 * math.pi * (D / 2) * ins_t * ins_rho
    h_w, h_s, h_i = Hmax / 2, Hw / 2, Hw / 2
    m_w, m_s, m_i = mu_w * Hmax, mu_s * Hw, mu_i * Hw
    h_e = (m_w * Hmax / 2 + m_s * Hw / 2 + m_i * Hw / 2) / (m_w + m_s + m_i)
    mu_e = (mu_w * h_w ** 3 + mu_s * h_s ** 3 + mu_i * h_i ** 3) / h_e ** 3
    I = math.pi * (D / 2) ** 3 * tr_avg
    freqs = []
    for m in range(1, 11):
        beta = BETA_M[m - 1] if m <= 5 else (2 * m - 1) * math.pi / 2
        alpha = -1.7639 + 3.6646 * m
        freqs.append(beta ** 2 / (2 * math.pi * Hw ** 2 * alpha) * math.sqrt(E * 1e6 * I / mu_e))

    # --- ветер [A146:V164, K137:R144]
    z_eq = 0.8 * (Hw + hk)
    f_lim = math.sqrt(w0 * 1000 * wind_k(terrain, z_eq) * 1.4) / 940 / 0.0077
    static_ok = freqs[0] > f_lim
    if not static_ok:
        notes.append("Первая частота колебаний ниже предельной: пульсационная составляющая ветра требует динамического расчёта (в Excel «АХТУНГ»).")
    nu = wind_nu(Hw + 0.7 * hk, D)
    c_aero = _num(inp, "aero_coef", 0.8)
    wind = []
    for i in range(n):
        z = hb * (i + 1)
        wm = w0 * wind_k(terrain, z) * c_aero
        wind.append({"belt": i + 1, "z_m": z, "k": wind_k(terrain, z), "zeta": wind_zeta(terrain, z), "wm_kpa": wm})
    wg = (wind[0]["wm_kpa"] * wind[0]["zeta"] * nu) if static_ok else None
    notes.append("Excel [Q137]: пульсационная составляющая ветра рассчитана для высоты первого пояса и принята одинаковой для всех поясов.")
    for wd in wind:
        wd["w_mpa"] = ((wg + wd["wm_kpa"]) * 1e-3) if wg is not None else None

    # --- устойчивость [A137:V144]
    t_min = min(tr)
    e_par = (D / 2) / t_min
    c0 = (0.04 + 40 / e_par if 400 <= e_par < 1220 else 0.085 - 1e-5 * e_par if 1220 <= e_par < 2500 else 0.065 - 2e-6 * e_par if 2500 <= e_par < 5000 else None)
    if c0 is None:
        raise ValueError("Параметр R/t вне диапазона 400…5000: проверьте толщины поясов и диаметр.")
    sigma1_cr = c0 * E / e_par
    Hr, acc = [0.0] * n, 0.0
    for i in range(n - 1, -1, -1):
        acc += hb * (min(tr[i:]) / tr[i]) ** 2.5
        Hr[i] = acc
    sigma2_cr = 0.55 * (D / 2) / Hr[0] * E / e_par ** 1.5
    stability = []
    for i in range(n):
        s2 = None if wind[i]["w_mpa"] is None else (1.2 * PSI["l3"] * pv_pa * 1e-6 + 0.5 * PSI["t2"] * wind[i]["w_mpa"]) * e_par
        s1 = ((1.05 * Gm[i] + 1.05 * Go[i] * PSI["l1"] + 1.3 * Gt[i] * PSI["l2"]) / (2 * 3.14 * (D / 2) * tr[i])
              + (snow_design + 1.2 * pv_pa * 1e-6 * PSI["l3"]) / tr[i] * (D / 2))
        u = None if s2 is None else s1 / sigma1_cr + s2 / sigma2_cr
        # [X137:X144] предельная редуцированная высота, при которой U = 1 (ставится кольцо жёсткости); возможно, только если меридиональное условие s1 < sigma1_cr
        hr_max = None if (u is None or u <= 1 or s1 >= sigma1_cr or not s2) else 0.55 * (D / 2) * E / e_par ** 1.5 * (1 - s1 / sigma1_cr) / s2
        stability.append({"belt": i + 1, "hoop_mpa": s2, "meridional_mpa": s1, "utilization": u, "ok": None if u is None else u <= 1,
                          "reduced_height_m": Hr[i], "ring_hr_max_m": hr_max})
    fixable = [b["ring_hr_max_m"] for b in stability if b["ring_hr_max_m"] is not None]
    if any(b["ok"] is False for b in stability):
        if len(fixable) == sum(1 for b in stability if b["ok"] is False):
            notes.append("Устойчивость стенки не обеспечена; её даёт кольцо жёсткости с редуцированной высотой не более %.2f м (Excel [X137:X144])." % min(fixable))
        else:
            notes.append("Устойчивость стенки не обеспечена; одним кольцом жёсткости не исправить (меридиональные напряжения превышают критические) - нужно увеличить толщины.")
    w_top = wind[-1]["w_mpa"]
    ring_w = None if w_top is None else 1.4 * w_top / 215 / R_op[2] * D ** 2 * Hw * 1e6      # [B172] требуемый момент сопротивления кольца жёсткости, см3

    # --- нагрузки для прикладывания в расчётной модели (МПа, кг, Н)
    loads = {
        "gravity_m_s2": g,
        "hydrostatic_operation": {"density_kg_m3": rho * 1000, "fill_height_m": Hop, "overpressure_mpa": p_pa * 1e-6},
        "hydrostatic_hydrotest": {"density_kg_m3": _num(inp, "water_density_kg_m3", 1000), "fill_height_m": Hgt, "overpressure_mpa": 0.0},
        "overpressure_mpa": p_pa * 1e-6, "vacuum_mpa": pv_pa * 1e-6,
        "snow_mpa": {"characteristic": snow_char, "design": snow_design},
        "wind": [{"belt": w["belt"], "z_bottom_m": hb * w["belt"] - hb, "z_top_m": w["z_m"], "mean_kpa": w["wm_kpa"], "total_mpa": w["w_mpa"]} for w in wind],
        "wind_pulsation_kpa": wg, "wind_correlation_nu": nu,
        "point_masses": [{"name": it["name"], "category": it["category"], "mass_kg": it["per_spot_kg"],
                          "location": ("roof" if s == n else f"belt_{s + 1}")} for it in placed for s in it["spots"]
                         if it["category"] != "metal" or not it["name"].startswith(("Пояс стенки", "Настил", "Радиальные"))],
        "insulation": {"thickness_m": ins_t, "density_kg_m3": ins_rho},
        "combination_factors": {"gamma_f": {"overpressure": 1.2, "weight_metal": 1.05, "weight_equipment": 1.05, "weight_insulation": 1.3, "snow": 1.4, "wind": 1.4, "vacuum": 1.2},
                                "psi": PSI, "ce": CE},
    }
    return {
        "model": model_params(inp, w0),
        "inputs": {"D": D, "H": Hw, "n_belts": n, "belt_height": hb, "snow_district": snow_d, "wind_district": wind_d, "terrain": terrain, "Sg_kpa": Sg, "w0_kpa": w0},
        "materials": {"R_operation": R_op, "R_hydrotest": R_gt, "dt_minus_mm": dtm, "dt_corrosion_mm": dtc, "corrosion_checks": checks},
        "thickness": [{"belt": i + 1, "td_mm": td[i], "tg_mm": tg[i], "nominal_pre_mm": thick_pre[i], "nominal_mm": nominal[i], "design_m": tr[i]} for i in range(n)],
        "roof": {"radius_m": Rroof, "area_m2": Aroof, "deck_mass_kg": deck_mass, "insulation_mass_kg": roof_ins_mass, "ring_mass_kg": ring_mass,
                 "beams_mass_kg": beams_mass, "metal_mass_kg": roof_metal},
        "wall": {"insulation_mass_kg": wall_ins_mass, "belt_mass_kg": belt_mass},
        "weights_above_mn": {"metal": Gm, "equipment": Go, "insulation": Gt},
        "strength": strength, "frequency": {"f_hz": freqs, "f_lim_hz": f_lim, "static_wind_ok": static_ok, "z_eq_m": z_eq,
                                            "mu_water": mu_w, "mu_wall": mu_s, "inertia_m4": I},
        "wind": wind, "wind_pulsation_kpa": wg, "nu": nu,
        "stability": {"belts": stability, "sigma1_cr_mpa": sigma1_cr, "sigma2_cr_mpa": sigma2_cr, "e_par": e_par},
        "ring_modulus_cm3": ring_w,
        "loads": loads, "equipment_distribution": placed, "notes": notes,
    }
