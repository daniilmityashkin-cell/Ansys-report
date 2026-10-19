"""Инженерные формулы отчёта (ГОСТ Р 58622-2019, ГОСТ 31385-2023, СП 16.13330)."""
from __future__ import annotations
from .project import Project

G = 9.81
GAMMA_M = 1.05   # коэффициент надёжности по материалу
GAMMA_N = 1.05   # коэффициент надёжности по назначению
GAMMA_C = {"wall1": 0.7, "wall": 0.8, "utor": 1.2}   # коэф. условий работы


def design_resistance(yield_mpa: float, gamma_c: float) -> float:
    """R = σт·γc / (γm·γn), МПа."""
    return yield_mpa * gamma_c / (GAMMA_M * GAMMA_N)


def tangent_modulus(sig_u: float, sig_y: float, delta_pct: float, e_mpa: float) -> float:
    """E2 = (σвр − σт) / (Δ/100 − σт/E), МПа (билинейная диаграмма)."""
    return (sig_u - sig_y) / (delta_pct / 100 - sig_y / e_mpa)


def roof_force(p: Project):
    """F = γf (Mкр + ψ·Моб)·g, Н (только если массы заданы в анкете; при загрузке из Ansys сила берётся из проекта)."""
    L = p.loads
    if "roof_mass_kg" not in L:
        return None
    return L["roof_load_factor"] * (L["roof_mass_kg"] + L["combination_factor"] * sum(L["equipment_masses_kg"])) * G


def deviation_check(p: Project, step: float) -> list[dict]:
    """Проверка замеров отклонений образующих от вертикали по поясам (допуски: H/200 и H/200 + 30 мм, как в таблицах исходных данных).
    step - высота пояса, мм. Для каждого пояса: допуски, максимум |Δ| и число точек с превышением, для полного и пустого резервуара."""
    out = []
    for k in range(len(p.survey_full)):
        lim1 = step * (k + 1) / 200
        lim2 = lim1 + 30
        row = {"belt": k + 1, "H": step * (k + 1), "lim1": lim1, "lim2": lim2}
        for key, survey in (("full", p.survey_full), ("empty", p.survey_empty)):
            vals = survey[k]
            row[key] = {"max": max(abs(x) for x in vals), "n": len(vals),
                        "over1": sum(1 for x in vals if abs(x) > lim1),
                        "over2": sum(1 for x in vals if abs(x) > lim2)}
        out.append(row)
    return out


def calc_all(p: Project) -> dict:
    m, t, L = p.material, p.tank, p.loads
    sy = m["yield_mpa"]
    allow = sy / 1.5                      # [σ] = σ0,2 / 1,5
    def evaluate(results):
        return [{
            "belt": r["belt"], "thickness": t["belts_thickness"][r["belt"] - 1],
            "fiber": r["fiber"], "equivalent": r["equivalent"], "membrane": r["membrane"],
            # ГОСТ Р 58622-2019, табл. 13: для листов стенки критерий только мембранный σм <= 1,5[σ];
            # σф <= 3[σ] и σэ <= 3[σ] относятся к опорному кольцу, рёбрам жёсткости и ПРП (здесь - справочно)
            "ok_fiber": r["fiber"] <= 3 * allow,
            "ok_eq": r["equivalent"] <= 3 * allow,
            "ok_mem": r["membrane"] <= 1.5 * allow,
        } for r in results]
    belts = evaluate(p.results)
    belts_empty = evaluate(p.results_empty) if p.results_empty else None
    stab = p.stability
    valid = [s["k"] for s in stab if s["k"] > 0]       # k = 0 - результат не прочитан, это не «нулевой запас»
    kmin = min(valid) if valid else None
    missing = [s["case"] for s in stab if s["k"] <= 0]
    step = t["belt_height"]
    return {
        "R1": design_resistance(sy, GAMMA_C["wall1"]),
        "R2": design_resistance(sy, GAMMA_C["wall"]),
        "Rutor": design_resistance(sy, GAMMA_C["utor"]),
        "allow": allow, "allow15": 1.5 * allow, "allow3": 3 * allow,
        "E2": tangent_modulus(m["ultimate_mpa"], sy, m["elongation_pct"], m["young_modulus_mpa"]),
        "roof_force": roof_force(p),
        "wall_ins_n": L.get("wall_insulation_kg", 0) * 10, "roof_ins_n": L.get("roof_insulation_kg", 0) * 10,
        "limits_dev": [step * k / 200 for k in range(1, len(belts) + 1)],
        "heights": [step * k for k in range(1, len(belts) + 1)],
        "belts": belts, "belts_empty": belts_empty,
        "strength_ok": all(b["ok_mem"] for b in belts),
        "kmin": kmin, "stability_missing": missing,
        "stability_ok": kmin is not None and kmin >= p.raw["results"]["required_k"],
        "stability": stab,
        "max_eq": max(b["equivalent"] for b in belts),
        "max_mem": max(b["membrane"] for b in belts),
        "max_fiber": max(b["fiber"] for b in belts),
        "dev_check": deviation_check(p, step),
        "dev_max_full": max(abs(x) for b in p.survey_full for x in b),
        "dev_max_empty": max(abs(x) for b in p.survey_empty for x in b),
    }


def fmt(x: float, nd: int = 1) -> str:
    """Число в русском формате: запятая как разделитель."""
    return f"{x:.{nd}f}".replace(".", ",")
