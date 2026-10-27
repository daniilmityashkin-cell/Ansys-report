"""Каркас крыши и кольцо опоры крыши из файла проекта программы геометрии -> beams.json для пакета Ansys.
Сечения задаются свойствами (площадь, моменты инерции), а не контуром: так результат не зависит от ориентации профиля в КЭ."""
from __future__ import annotations
import math


def _sec(s: dict, strong_only: bool) -> dict:
    c = s.get("computed") or s.get("reference") or {}
    A = float(c.get("area_cm2", 0)) * 100.0                     # мм2
    ix, iy = float(c.get("Ix_cm4", 0)) * 1e4, float(c.get("Iy_cm4", 0)) * 1e4      # мм4
    d = s.get("dimensions_m", {})
    D, B, tw, tf = (float(d.get(k, 0)) * 1000 for k in ("D", "Base", "TW", "TF"))
    if strong_only:          # радиальные балки работают на вертикальный изгиб: берём сильную ось в обе стороны (настил раскрепляет в плоскости крыши)
        i1 = i2 = max(ix, iy)
    else:                    # кольцевые балки: изгиб в двух плоскостях - среднее значение
        i1 = i2 = (ix + iy) / 2.0
    J = (2 * B * tf ** 3 + max(D - 2 * tf, 0) * tw ** 3) / 3.0
    return {"name": s.get("name", ""), "A": round(A, 3), "Iyy": round(i1, 1), "Izz": round(i2, 1), "J": round(max(J, 1.0), 1), "D": round(D, 2), "B": round(B, 2)}


def wind_rings(project: dict) -> list[dict]:
    """Кольца жёсткости на стенке (шаг 06 студии): высота привязывается к ближайшей границе поясов (там узлы сетки), сечение - плоская полка.
    Работа кольца - изгиб в плоскости круга (против овализации): I = t * b^3 / 12 по радиальной ширине b."""
    import re
    hs = [float(x) for x in (project.get("heights") or [])]
    out = []
    for r in project.get("wind_rings") or []:
        try:
            h = float(str(r["h"]).replace(",", "."))
        except (KeyError, ValueError):
            continue
        cand = [z for z in hs[1:-1]] or hs
        if not cand:
            continue
        z = min(cand, key=lambda c: abs(c - h))
        m = re.findall(r"\d+(?:[.,]\d+)?", str(r.get("flange") or "100 x 10"))
        b, t = (float(m[0].replace(",", ".")), float(m[1].replace(",", "."))) if len(m) >= 2 else (100.0, 10.0)
        I = t * b ** 3 / 12.0
        out.append({"z_m": z, "requested_m": h, "A": round(b * t, 1), "Iyy": round(I, 1), "Izz": round(I, 1), "J": round(b * t ** 3 / 3.0, 1), "D": t, "B": b})
    return out


def with_structure_sections(project: dict, structure: dict | None) -> dict:
    """Конструкция, введённая в студии (structure.json: крыша, узлы, сечения балок с готовыми свойствами), дополняет проект до формата файла «РВС Геометрия»,
    который читает beams_package. Сечения и параметры крыши из студии имеют приоритет: пользователь мог заменить профиль после загрузки файла."""
    st = structure or {}
    roof = st.get("roof")
    if not roof or not st.get("beam_sections"):
        return project
    out = dict(project)
    r = dict(out.get("roof") or {})
    r.update(enabled=True, radial_count=roof.get("radial_count", r.get("radial_count", 0)), ring_count=roof.get("ring_count", r.get("ring_count", 0)),
             central_radius_m=roof.get("central_radius_m", r.get("central_radius_m", 0)), first_angle_deg=roof.get("first_angle_deg", r.get("first_angle_deg", 0)))
    out["roof"] = r
    nodes = st.get("roof_nodes")
    if nodes and not (out.get("roof_nodes") or {}).get("enabled"):
        out["roof_nodes"] = {"enabled": True, **{k: v for k, v in nodes.items()}}
    props = {g["group"]: g.get("props") for g in st["beam_sections"] if g.get("props")}
    bs = dict(out.get("beam_sections") if isinstance(out.get("beam_sections"), dict) else {})
    def put(key, p):                                               # профиль из файла проекта (с тем же именем) оставляем: у колец он может быть разным по номерам
        if not (isinstance(bs.get(key), dict) and bs[key].get("name") == p.get("name")):
            bs[key] = p
    for group, key in (("Радиальные балки", "radial"), ("Центральное кольцо", "central_ring"), ("Периферийный швеллер", "channel")):
        if props.get(group):
            put(key, props[group])
    if props.get("Кольцевые балки"):
        ring = props["Кольцевые балки"]
        changed = not (isinstance(bs.get("hoop_1"), dict) and bs["hoop_1"].get("name") == ring.get("name"))      # подпись в студии - это имя кольца №1
        for j in range(1, int(float(r.get("ring_count", 0))) + 1):
            if changed or not isinstance(bs.get(f"hoop_{j}"), dict):
                bs[f"hoop_{j}"] = ring
    out["beam_sections"] = bs
    return out


def beams_package(project: dict, wall_radius_mm: float) -> dict | None:
    """None, если в проекте нет крыши с каркасом (сечения заданы только подписями - такие данные в файле программы геометрии есть, в ручном вводе нет)."""
    bs, roof = project.get("beam_sections"), project.get("roof")
    wr = wind_rings(project)
    if not isinstance(bs, dict) or not isinstance(roof, dict) or not roof.get("enabled"):
        return {"wall_radius_mm": wall_radius_mm, "wind_rings": wr, "radial": None, "central": None, "edge": None, "rings": [], "radial_count": 0, "central_radius_mm": 0.0, "first_angle_deg": 0.0} if wr else None
    n_rad = int(float(roof.get("radial_count", 0)))
    n_ring = int(float(roof.get("ring_count", 0)))
    rc = float(str(roof.get("central_radius_m", 0)).replace(",", ".")) * 1000.0
    out = {"wall_radius_mm": wall_radius_mm, "central_radius_mm": rc, "radial_count": n_rad, "first_angle_deg": float(str(roof.get("first_angle_deg", 0)).replace(",", ".")),
           "radial": _sec(bs["radial"], True) if "radial" in bs else None,
           "central": _sec(bs["central_ring"], False) if "central_ring" in bs else None,
           "edge": _sec(bs["channel"], False) if "channel" in bs else None,
           "rings": [_sec(bs[f"hoop_{j}"], False) for j in range(1, n_ring + 1) if f"hoop_{j}" in bs],
           "wind_rings": wr,
           "assumption": "кольцевые балки расположены на равных расстояниях между центральным кольцом и стенкой; оси сечений - по средним/сильным моментам инерции"}
    nodes = project.get("roof_nodes") or {}
    if nodes.get("enabled") and nodes.get("ring_thickness_mm") and nodes.get("ring_height_mm"):
        t, h = float(nodes["ring_thickness_mm"]), float(nodes["ring_height_mm"])
        out["top_ring"] = {"A": t * h, "Iyy": t * h ** 3 / 12.0, "Izz": h * t ** 3 / 12.0, "J": h * t ** 3 / 3.0, "D": h, "B": t}
    return out
