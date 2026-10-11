"""Разбор model_data.json, выгруженного из Ansys Mechanical скриптом export_model_data.py.
Из проекта Ansys берутся: толщины, габариты, сетка, нагрузки, нивелировка (радиусы колец стенки)."""
from __future__ import annotations
import bisect
import json
import re
from pathlib import Path


def _num(s, default=None):
    m = re.search(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", str(s))
    return float(m.group(0)) if m else default


def _nums(s) -> list[float]:
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", str(s).replace("[", " [").split("[")[0] if False else str(s))
            if x not in ("",)]


def _quantity_values(s) -> list[float]:
    """'[-734643.9 [N]]' -> [-734643.9];  '[0 [m s^-1 s^-1],10 [m s^-1 s^-1]]' -> [0, 10]."""
    s = re.sub(r"\[[a-zA-Zа-я][^\[\]]*\]", "", str(s))        # убрать единицы в квадратных скобках
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", s)]


def load_model_data(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def belt_bodies(md: dict) -> list[dict]:
    out = []
    for b in md["bodies"]:
        m = re.match(md.get("belt_regex") or r"^p\s*(\d+)$", b["name"])
        if m:
            out.append({"n": int(m.group(1)), "thickness_mm": round(_num(b["thickness"]) * 1000, 3), "geo_id": b.get("geo_id")})
    return sorted(out, key=lambda x: x["n"])


def body_thickness_mm(md: dict, name: str):
    for b in md["bodies"]:
        if b["name"] == name:
            return round(_num(b["thickness"]) * 1000, 3)
    return None


def belt_ring_points(md: dict) -> dict[int, list[tuple[float, float]]]:
    """{номер пояса: [(угол°, радиус м)]} — верхнее кольцо пояса."""
    if md.get("belt_rings"):
        return {r["belt"]: [tuple(p) for p in r["points"]] for r in md["belt_rings"]}
    # запасной вариант (старый формат): кольца по высоте
    rings = {}
    for r in md.get("rings", []):
        k = round(r["x"] / 1.49)
        if k >= 1 and abs(r["x"] / 1.49 - k) < 0.01 and len(r["points"]) >= 400:
            rings[k] = [tuple(p) for p in r["points"]]
    return rings


def _interp(pts, a):
    ps = sorted(pts)
    ang, rad = [p[0] for p in ps], [p[1] for p in ps]
    i = bisect.bisect_left(ang, a)
    a0, r0 = (ang[i - 1], rad[i - 1]) if i > 0 else (ang[-1] - 360, rad[-1])
    a1, r1 = (ang[i], rad[i]) if i < len(ps) else (ang[0] + 360, rad[0])
    return r0 + (r1 - r0) * (a - a0) / (a1 - a0) if a1 != a0 else r0


def survey_from_rings(md: dict, r_nominal_m: float, n: int, start: float = 85.0) -> list[list[float]]:
    """Отклонения стенки (мм) по поясам [пояс][точка] — из радиусов колец сетки Ansys."""
    rings = belt_ring_points(md)
    step = 360 / n
    res = []
    for k in sorted(rings):
        row = []
        for j in range(n):
            a = ((start - step * j) + 180) % 360 - 180
            row.append(round((_interp(rings[k], a) - r_nominal_m) * 1000, 1))
        res.append(row)
    return res


def mean_radius_m(md: dict) -> float:
    rings = belt_ring_points(md)
    vals = [p[1] for pts in rings.values() for p in pts]
    return sum(vals) / len(vals)


def loads(md: dict, analysis: str | None = None) -> tuple[str, list[dict]]:
    """Нагрузки выбранного анализа (по умолчанию — первый статический, где гидростатика включена; иначе первый)."""
    ans = [a for a in md["analyses"] if a["type"] == "Static"]
    chosen = next((a for a in ans if a["name"] == analysis), None)
    if chosen is None:
        chosen = next((a for a in ans if any(c["type"] == "HydrostaticPressure" and c["suppressed"] != "True" for c in a["children"])), ans[0])
    out = []
    va = (md.get("vertical_axis") or "X").upper()
    for c in chosen["children"]:
        p, t = c["props"], c["type"]
        item = {"name": c["name"], "type": t, "suppressed": c["suppressed"] == "True"}
        if t == "EarthGravity":
            item["g"] = abs(_quantity_values(p.get(f"{va}Component", "0"))[0]); item["direction"] = p.get("Direction", "")
        elif t == "HydrostaticPressure":
            item["density"] = _num(p.get("FluidDensity"))
            xs = _quantity_values(p.get(f"{va}Component", ""))
            item["accel"] = xs[-1] if xs else None
            item["level_m"] = _num(p.get(f"{va}Coordinate"))
        elif t in ("Force", "Pressure", "LinePressure"):
            comps = {ax: (_quantity_values(p.get(f"{ax}Component", "0")) or [0.0])[0] for ax in "XYZ"}
            ax = max(comps, key=lambda k: abs(comps[k]))
            item["value"], item["axis"] = comps[ax], ax
        out.append(item)
    return chosen["name"], out


def mesh_info(md: dict) -> dict:
    mo = md.get("mesh_object", {})
    return {"nodes": md.get("node_count"), "elements": md.get("element_count") or int(_num(mo.get("Elements"), 0)),
            "element_size_mm": round((_num(mo.get("ElementSize"), 0) or 0) * 1000, 3),
            "order": mo.get("ElementOrder", ""), "mesher": mo.get("DefaultShellMesher", "")}


# ---- свойства материалов из Engineering Data (файл EngineeringData.xml проекта Workbench)
def _local(tag: str) -> str:
    return tag.split("}")[-1]


def read_engineering_data(path: Path) -> dict[str, dict[str, float]]:
    """{имя материала: {имя параметра: значение}} из EngineeringData.xml (разметка MatML Workbench).
    Значения в единицах СИ, как в файле (Па, кг/м3). Берётся первое число из списка значений."""
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    pnames, prnames = {}, {}
    for el in root.iter():
        t = _local(el.tag)
        if t in ("ParameterDetails", "PropertyDetails") and el.get("id"):
            name = next((_text(c) for c in el if _local(c.tag) == "Name"), "")
            (pnames if t == "ParameterDetails" else prnames)[el.get("id")] = name
    out: dict[str, dict[str, float]] = {}
    for mat in (e for e in root.iter() if _local(e.tag) == "Material"):
        bulk = next((c for c in mat if _local(c.tag) == "BulkDetails"), None)
        if bulk is None:
            continue
        mname = next((_text(c) for c in bulk if _local(c.tag) == "Name"), "")
        props: dict[str, float] = {}
        for pd in (c for c in bulk if _local(c.tag) == "PropertyData"):
            for pv in (c for c in pd if _local(c.tag) == "ParameterValue"):
                param = pnames.get(pv.get("parameter"), pv.get("parameter") or "")
                data = next((_text(c) for c in pv if _local(c.tag) == "Data"), "")
                m = re.search(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", data or "")
                if m and param not in props:
                    props[param] = float(m.group(0))
        if mname:
            out[mname] = props
    return out


def _text(el) -> str:
    return (el.text or "").strip()


def material_summary(props: dict[str, float]) -> dict:
    """Свойства для отчёта (МПа, кг/м3) из параметров Engineering Data. Чего нет в проекте - не включается."""
    def mpa(v):                       # Workbench хранит напряжения в Па
        return round(v / 1e6, 3) if v > 1e5 else round(v, 3)
    res = {}
    for key, names in (("density", ("Density",)), ("young_modulus_mpa", ("Young's Modulus", "Youngs Modulus")),
                       ("poisson", ("Poisson's Ratio", "Poissons Ratio")),
                       ("yield_mpa", ("Tensile Yield Strength", "Yield Strength")),
                       ("ultimate_mpa", ("Tensile Ultimate Strength",))):
        for n in names:
            if n in props:
                v = props[n]
                res[key] = v if key in ("density", "poisson") else mpa(v)
                break
    return res
