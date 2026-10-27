"""Конструкция резервуара, которую вводит заказчик: патрубки, днище, крыша, узлы, сечения балок (поля формы s_*) → словарь structure.json."""
from __future__ import annotations

import math

from ansys_report.geometry.rvs_core import number

BOTTOM = {"s_bot_on": "1", "s_bot_outside": "200", "s_bot_width": "1500", "s_bot_overlap": "100", "s_bot_slope": "100", "s_bot_plate_t": "8", "s_bot_ann_t": "12"}
ROOF = {"s_roof_on": "1", "s_roof_shape": "Сферическая", "s_roof_sphere_r": "50", "s_roof_cone_rise": "2", "s_roof_central_r": "1.3", "s_roof_radial": "24",
        "s_roof_first": "7.5", "s_roof_rings": "10", "s_roof_deck_t": "7", "s_roof_band_w": "1000", "s_roof_band_t": "10", "s_roof_band_drop": "200",
        "s_roof_beam_drop": "20", "s_roof_deck_inset": "200"}
NODES = {"s_node_on": "1", "s_node_ring_h": "200", "s_node_ring_t": "10", "s_node_up_l": "700", "s_node_up_h": "200", "s_node_up_t": "7",
         "s_node_lo_l": "1000", "s_node_lo_h": "100", "s_node_lo_t": "7"}
BEAMS = {"s_beam_radial": "Двутавр 24", "s_beam_central": "Швеллер 24П", "s_beam_rings": "Уголок L90×90×6", "s_beam_edge": "Швеллер 24П"}
DEFAULTS = {**BOTTOM, **ROOF, **NODES, **BEAMS}
SHAPES = ("Круглый", "Овальный")
ROOF_SHAPES = ("Сферическая", "Коническая")


def _n(f, key, label, lo=None, hi=None):
    v = number(f.get(key, ""), label)
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise ValueError(f"{label}: допустимо от {lo} до {hi}.")
    return v


def parse_nozzles(fields: dict[str, list[str]], D: float, H: float) -> list[dict]:
    rows = zip(*[fields.get(k, []) for k in ("s_nz_name", "s_nz_shape", "s_nz_width", "s_nz_height", "s_nz_z", "s_nz_angle", "s_nz_t", "s_nz_in", "s_nz_out")])
    out = []
    for i, (name, shape, w, h, z, ang, t, ins, outs) in enumerate(rows, 1):
        if not any(x.strip() for x in (w, h, z, ang, t)):
            continue                                               # пустая строка
        lab = f"Патрубок {i}"
        shape = shape if shape in SHAPES else "Круглый"
        width = number(w, f"{lab}: диаметр/ширина")
        height = width if shape == "Круглый" else number(h, f"{lab}: высота овала")
        zc = number(z, f"{lab}: высота центра")
        if not 0 < width <= 3000 or not 0 < height <= 3000:
            raise ValueError(f"{lab}: размеры сечения от 1 до 3000 мм.")
        if not height / 2000 <= zc <= H - height / 2000:
            raise ValueError(f"{lab}: патрубок не помещается по высоте стенки (0…{H:g} м).")
        angle = number(ang, f"{lab}: угол") % 360
        out.append({"name": name.strip() or lab, "shape": shape, "width_mm": width, "height_mm": height, "height_m": zc, "angle": angle,
                    "thickness_mm": number(t, f"{lab}: толщина"), "inside_mm": number(ins or "0", f"{lab}: длина внутри"),
                    "outside_mm": number(outs or "0", f"{lab}: длина снаружи")})
    if len(out) > 30:
        raise ValueError("Патрубков не больше 30.")
    return out


BEAM_GROUPS = (("Радиальные балки", "s_beam_radial", "radial"), ("Центральное кольцо", "s_beam_central", "central_ring"),
               ("Кольцевые балки", "s_beam_rings", "hoop_1"), ("Периферийный швеллер", "s_beam_edge", "channel"))


def project_sections(project: dict | None) -> dict:
    """Сечения, уже посчитанные в файле проекта «РВС Геометрия»: подпись (и имя) -> свойства. Нужны, чтобы профиль из файла (например серии Б), которого нет в каталоге, не отклонялся."""
    out = {}
    bs = (project or {}).get("beam_sections")
    for sec in (bs.values() if isinstance(bs, dict) else []):
        if isinstance(sec, dict) and (sec.get("computed") or sec.get("reference")):
            for key in (sec.get("label"), sec.get("name")):
                if key:
                    out[str(key).strip()] = sec
    return out


def beam_sections(f: dict, known: dict | None = None) -> list[dict]:
    """Четыре группы сечений крыши: подпись -> свойства (каталог профилей, габариты или значения; профиль из файла проекта берётся как есть)."""
    from ansys_report.loads.profiles import section_props
    out = []
    for group, field, _ in BEAM_GROUPS:
        label = f.get(field, "").strip()
        if not label:
            raise ValueError(f"Сечение «{group}» не задано. Выберите профиль из списка.")
        sec = (known or {}).get(label)
        if sec is not None:
            c = sec.get("computed") or sec.get("reference") or {}
            props = {"name": sec.get("name") or label, "label": label, "computed": {k: c.get(k) for k in ("area_cm2", "Ix_cm4", "Iy_cm4")}, "dimensions_m": sec.get("dimensions_m", {})}
        else:
            try:
                props = section_props(label)
            except ValueError as e:
                raise ValueError(f"{group}: {e}") from None
        out.append({"group": group, "section": label, "props": props})
    return out


def build_structure(fields: dict[str, list[str]], D: float, H: float, project: dict | None = None) -> dict | None:
    """fields: имя поля -> список значений. None, если ничего из конструкции не введено. project - файл проекта (сечения из него принимаются как есть)."""
    f = {k: (v[0] if v else "") for k, v in fields.items()}
    s: dict = {"nozzles": parse_nozzles(fields, D, H)}
    R = D / 2
    if f.get("s_bot_on"):
        b = {"outside_mm": _n(f, "s_bot_outside", "Днище: выступ окрайки", 0, 1000), "annular_width_mm": _n(f, "s_bot_width", "Днище: ширина окрайки", 100, 5000),
             "overlap_mm": _n(f, "s_bot_overlap", "Днище: нахлёст", 0, 1000), "slope_denominator": _n(f, "s_bot_slope", "Днище: уклон 1:", 10, 10000),
             "plate_thickness_mm": _n(f, "s_bot_plate_t", "Днище: толщина", 1, 100), "annular_thickness_mm": _n(f, "s_bot_ann_t", "Днище: толщина окрайки", 1, 100)}
        if b["annular_width_mm"] <= b["outside_mm"]:
            raise ValueError("Днище: ширина окрайки должна быть больше выступа наружу.")
        s["bottom"] = b
    if f.get("s_roof_on"):
        shape = f.get("s_roof_shape") if f.get("s_roof_shape") in ROOF_SHAPES else "Сферическая"
        r = {"shape": shape, "sphere_radius_m": _n(f, "s_roof_sphere_r", "Крыша: радиус сферы", 1, 1000), "cone_rise_m": _n(f, "s_roof_cone_rise", "Крыша: подъём конуса", 0.05, 30),
             "central_radius_m": _n(f, "s_roof_central_r", "Крыша: радиус центрального кольца", 0.1, R), "radial_count": int(_n(f, "s_roof_radial", "Крыша: радиальных балок", 4, 120)),
             "first_angle_deg": _n(f, "s_roof_first", "Крыша: угол первой балки", -360, 360), "ring_count": int(_n(f, "s_roof_rings", "Крыша: промежуточных колец", 0, 40)),
             "deck_thickness_mm": _n(f, "s_roof_deck_t", "Крыша: толщина настила", 1, 50), "plate_width_mm": _n(f, "s_roof_band_w", "Крыша: ширина опорной полосы", 10, 3000),
             "plate_thickness_mm": _n(f, "s_roof_band_t", "Крыша: толщина опорной полосы", 1, 100), "plate_drop_mm": _n(f, "s_roof_band_drop", "Крыша: опускание полосы", 0, 2000),
             "beam_drop_mm": _n(f, "s_roof_beam_drop", "Крыша: опускание каркаса", 0, 2000), "deck_inset_mm": _n(f, "s_roof_deck_inset", "Крыша: отступ настила", 0, 2000)}
        if shape == "Сферическая" and r["sphere_radius_m"] <= R:
            raise ValueError("Крыша: радиус сферы должен быть больше радиуса резервуара.")
        r["rise_m"] = (r["sphere_radius_m"] - math.sqrt(r["sphere_radius_m"] ** 2 - R * R)) if shape == "Сферическая" else r["cone_rise_m"]
        s["roof"] = r
        if f.get("s_node_on"):
            s["roof_nodes"] = {"ring_height_mm": _n(f, "s_node_ring_h", "Узлы: высота круговой пластины", 1, 2000), "ring_thickness_mm": _n(f, "s_node_ring_t", "Узлы: толщина круговой пластины", 1, 100),
                               "upper_length_mm": _n(f, "s_node_up_l", "Узлы: верхние, длина", 1, 5000), "upper_height_mm": _n(f, "s_node_up_h", "Узлы: верхние, высота", 1, 2000),
                               "upper_thickness_mm": _n(f, "s_node_up_t", "Узлы: верхние, толщина", 1, 100), "lower_length_mm": _n(f, "s_node_lo_l", "Узлы: нижние, длина", 1, 5000),
                               "lower_height_mm": _n(f, "s_node_lo_h", "Узлы: нижние, высота", 1, 2000), "lower_thickness_mm": _n(f, "s_node_lo_t", "Узлы: нижние, толщина", 1, 100)}
        s["beam_sections"] = beam_sections(f, project_sections(project))
    if not (s["nozzles"] or "bottom" in s or "roof" in s):
        return None
    s["D"], s["H"] = D, H
    return s


def structure_from_project(p: dict) -> dict | None:
    """Конструкция из файла проекта (формат программы геометрии: nozzles, bottom, roof, roof_nodes, beam_sections)."""
    D, H = float(p["diameter"]), float(p["height"])
    R = D / 2
    s: dict = {"nozzles": [], "D": D, "H": H}
    for i, n in enumerate(p.get("nozzles") or [], 1):
        w = float(n.get("width_mm", 0))
        h = float(n.get("height_mm", w))
        anchor = float(n.get("anchor", 0))
        angle = anchor % 360 if "Угол" in str(n.get("mode", "Угол")) else (anchor / R * 180 / math.pi) % 360     # иначе - расстояние по дуге, м
        s["nozzles"].append({"name": n.get("name") or f"Патрубок {i}", "shape": n.get("shape") if n.get("shape") in SHAPES else "Круглый", "width_mm": w, "height_mm": h,
                             "height_m": float(n.get("height_m", 0)), "angle": angle, "thickness_mm": float(n.get("thickness_mm", 0)),
                             "inside_mm": float(n.get("inside_mm", 0)), "outside_mm": float(n.get("outside_mm", 0))})
    b = p.get("bottom") or {}
    if b.get("enabled"):
        s["bottom"] = {k: float(b[k]) for k in ("outside_mm", "annular_width_mm", "overlap_mm", "slope_denominator", "plate_thickness_mm", "annular_thickness_mm") if k in b}
    r = p.get("roof") or {}
    if r.get("enabled"):
        g = lambda k, d=0.0: float(r.get(k, d))   # noqa: E731
        shape = r.get("shape") if r.get("shape") in ROOF_SHAPES else "Сферическая"
        rr = {"shape": shape, "sphere_radius_m": g("sphere_radius_m", 50), "cone_rise_m": g("cone_rise_m", 2), "central_radius_m": g("central_radius_m", 1.3),
              "radial_count": int(g("radial_count", 24)), "first_angle_deg": g("first_angle_deg"), "ring_count": int(g("ring_count", 10)),
              "deck_thickness_mm": g("deck_thickness_mm", 7), "plate_width_mm": g("plate_width_mm", 1000), "plate_thickness_mm": g("plate_thickness_mm", 10),
              "plate_drop_mm": g("plate_drop_mm", 200), "beam_drop_mm": g("beam_drop_mm", 20), "deck_inset_mm": g("deck_inset_mm", 200)}
        rr["rise_m"] = (rr["sphere_radius_m"] - math.sqrt(max(rr["sphere_radius_m"] ** 2 - R * R, 0))) if shape == "Сферическая" else rr["cone_rise_m"]
        s["roof"] = rr
        nd = p.get("roof_nodes") or {}
        if nd.get("enabled"):
            s["roof_nodes"] = {k: float(nd[k]) for k in ("ring_height_mm", "ring_thickness_mm", "upper_length_mm", "upper_height_mm", "upper_thickness_mm",
                                                         "lower_length_mm", "lower_height_mm", "lower_thickness_mm") if k in nd}
        bs = p.get("beam_sections") or {}
        label = lambda k: (bs.get(k) or {}).get("label", "")   # noqa: E731
        rings = [label(k) for k in sorted((k for k in bs if k.startswith("hoop")), key=lambda k: int(k.split("_")[1]))]
        s["beam_sections"] = [{"group": "Радиальные балки", "section": label("radial")}, {"group": "Центральное кольцо", "section": label("central_ring")},
                              {"group": "Кольцевые балки", "section": ", ".join(dict.fromkeys(x for x in rings if x))},
                              {"group": "Периферийный швеллер", "section": label("edge") or label("channel")}]
    return s if (s["nozzles"] or "bottom" in s or "roof" in s) else None
