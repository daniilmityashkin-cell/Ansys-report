"""Допустимая высота налива по условию прочности: серия расчётов при разных уровнях, интерполяция по мембранным напряжениям."""
from __future__ import annotations
import csv
from pathlib import Path


def allowable_fill(series: list[dict], limit_mpa: float) -> dict:
    """series: [{level_m, membrane, ...}]. Возвращает {"level_m", "unlimited"}: уровень, при котором мембранные напряжения достигают limit_mpa
    (линейная интерполяция между соседними расчётами; напряжения растут с уровнем), либо unlimited=True, если предел не достигнут до верхнего расчётного уровня."""
    pts = sorted(((float(x["level_m"]), float(x["membrane"])) for x in series), key=lambda p: p[0])
    if not pts:
        return {"level_m": None, "unlimited": False}
    prev = None
    for lv, mem in pts:
        if mem > limit_mpa:
            if prev is None:
                return {"level_m": round(lv * limit_mpa / mem, 1), "unlimited": False}       # ниже первого уровня: пропорционально (напряжения ~ уровню)
            lv0, m0 = prev
            return {"level_m": round(lv0 + (lv - lv0) * (limit_mpa - m0) / (mem - m0), 1), "unlimited": False}
        prev = (lv, mem)
    return {"level_m": pts[-1][0], "unlimited": True}


def read_series(data_dir: Path, cases: list[dict], prefix: str, fname) -> list[dict]:
    """Максимумы по поясам из <расчёт>_belts.csv для случаев с гидростатикой без ветра: «Эксплуатация» и «Налив …»."""
    out = []
    for c in cases:
        if not c.get("hydro") or c.get("wind") or c["id"] == "hydrotest":
            continue
        f = Path(data_dir) / f"{fname(prefix + c['name'])}_belts.csv"
        if not f.exists():
            continue
        rows = list(csv.DictReader(f.open(encoding="utf-8-sig", newline="")))
        if not rows:
            continue
        out.append({"level_m": round(c["hydro"]["free_surface_mm"] / 1000.0, 2),
                    "membrane": round(max(float(r["membrane"]) for r in rows), 1),
                    "fiber": round(max(float(r["fiber"]) for r in rows), 1),
                    "equivalent": round(max(float(r["equivalent"]) for r in rows), 1)})
    return sorted(out, key=lambda x: x["level_m"])
