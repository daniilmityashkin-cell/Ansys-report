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


def roof_force(p: Project) -> float:
    """F = γf (Mкр + ψ·Моб)·g, Н."""
    L = p.loads
    return L["roof_load_factor"] * (L["roof_mass_kg"] + L["combination_factor"] * sum(L["equipment_masses_kg"])) * G


def calc_all(p: Project) -> dict:
    m, t, L = p.material, p.tank, p.loads
    sy = m["yield_mpa"]
    allow = sy / 1.5                      # [σ] = σ0,2 / 1,5
    belts = []
    for r in p.results:
        i = r["belt"]
        belts.append({
            "belt": i, "thickness": t["belts_thickness"][i - 1],
            "fiber": r["fiber"], "equivalent": r["equivalent"], "membrane": r["membrane"],
            "ok_fiber": r["fiber"] <= 3 * allow,
            "ok_eq": r["equivalent"] <= 3 * allow,
            "ok_mem": r["membrane"] <= allow,
        })
    stab = p.raw["results"]["stability"]
    kmin = min(s["k"] for s in stab)
    step = t["belt_height"]
    return {
        "R1": design_resistance(sy, GAMMA_C["wall1"]),
        "R2": design_resistance(sy, GAMMA_C["wall"]),
        "Rutor": design_resistance(sy, GAMMA_C["utor"]),
        "allow": allow, "allow3": 3 * allow,
        "E2": tangent_modulus(m["ultimate_mpa"], sy, m["elongation_pct"], m["young_modulus_mpa"]),
        "roof_force": roof_force(p),
        "wall_ins_n": L["wall_insulation_kg"] * 10, "roof_ins_n": L["roof_insulation_kg"] * 10,
        "limits_dev": [step * k / 200 for k in range(1, len(belts) + 1)],
        "heights": [step * k for k in range(1, len(belts) + 1)],
        "belts": belts,
        "strength_ok": all(b["ok_fiber"] and b["ok_eq"] and b["ok_mem"] for b in belts),
        "kmin": kmin, "stability_ok": kmin >= p.raw["results"]["required_k"],
        "max_eq": max(b["equivalent"] for b in belts),
        "max_mem": max(b["membrane"] for b in belts),
        "max_fiber": max(b["fiber"] for b in belts),
        "dev_max_full": max(abs(x) for b in p.survey_full for x in b),
        "dev_max_empty": max(abs(x) for b in p.survey_empty for x in b),
    }


def fmt(x: float, nd: int = 1) -> str:
    """Число в русском формате: запятая как разделитель."""
    return f"{x:.{nd}f}".replace(".", ",")
