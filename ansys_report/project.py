"""Загрузка и проверка исходных данных проекта (project.yaml + CSV)."""
from __future__ import annotations
import csv
from dataclasses import dataclass
from pathlib import Path
import yaml


class ProjectError(ValueError):
    pass


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise ProjectError(f"Не найден файл: {path}")
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@dataclass
class Project:
    root: Path
    raw: dict
    survey_full: list[list[float]]    # [belt][point], мм
    survey_empty: list[list[float]]
    results: list[dict]               # по поясам: belt, fiber, equivalent, membrane
    results_empty: list[dict] | None = None   # то же для пустого резервуара (необязательно)
    stability: list[dict] | None = None       # [{case, k}] — из yaml или stability.csv

    @property
    def has_results(self) -> bool:
        return bool(self.results)

    @property
    def report(self): return self.raw["report"]
    @property
    def tank(self): return self.raw["tank"]
    @property
    def material(self): return self.raw["material"]
    @property
    def loads(self): return self.raw.get("loads", {})


def _load_survey(path: Path, n_belts: int, n_points: int) -> list[list[float]]:
    rows = _read_csv(path)
    if len(rows) != n_points:
        raise ProjectError(f"{path.name}: ожидалось {n_points} точек на пояс, найдено {len(rows)}")
    belts = []
    for b in range(1, n_belts + 1):
        key = f"belt{b}"
        if key not in rows[0]:
            raise ProjectError(f"{path.name}: нет столбца {key}")
        try:
            belts.append([float(r[key].replace(",", ".")) for r in rows])
        except ValueError as e:
            raise ProjectError(f"{path.name}, {key}: нечисловое значение ({e})")
    return belts


def load_project(yaml_path: str | Path) -> Project:
    yaml_path = Path(yaml_path)
    root = yaml_path.parent
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    for sec in ("report", "tank", "material", "survey"):
        if sec not in raw:
            raise ProjectError(f"В project.yaml нет раздела '{sec}'")
    md = _apply_ansys(raw, root)
    t = raw["tank"]
    n = len(t["belts_thickness"])
    if abs(n * t["belt_height"] - t["wall_height"]) > 1:
        raise ProjectError(f"{n} поясов × {t['belt_height']} мм ≠ высоте стенки {t['wall_height']} мм")
    s = raw["survey"]
    full_file = s.get("full")
    full = _load_survey(root / full_file, n, s["points_per_belt"]) if full_file and (root / str(full_file)).exists() else None
    if md is not None and (s.get("empty") in (None, "auto") or not (root / str(s["empty"])).exists()):
        from . import ansys_import as ai
        empty = ai.survey_from_rings(md, t["diameter"] / 2000, s["points_per_belt"], s.get("start_angle", 85))
        if len(empty) != n:
            raise ProjectError(f"Из Ansys получено колец: {len(empty)}, поясов в модели: {n} (запустите export_model_data.py заново)")
    else:
        empty = _load_survey(root / s["empty"], n, s["points_per_belt"])
    if full is None:      # замеров «полного» нет — форма как у пустого (без дополнительной деформации)
        full = [row[:] for row in empty]
    rr = raw.get("results") or {}
    res = _load_belts(root / rr["full"], n) if rr.get("full") and (root / rr["full"]).exists() else []
    res_empty = _load_belts(root / rr["empty"], n) if rr.get("empty") and (root / rr["empty"]).exists() else None
    return Project(root, raw, full, empty, res, res_empty, _load_stability(root, rr) if res else [])


def _apply_ansys(raw: dict, root: Path):
    """Если в project.yaml есть раздел ansys.model_data — геометрия, сетка и нагрузки берутся из проекта Ansys."""
    a = raw.get("ansys")
    if not a or not a.get("model_data"):
        return None
    from . import ansys_import as ai
    md = ai.load_model_data(root / a["model_data"])
    t = raw.setdefault("tank", {})
    belts = ai.belt_bodies(md)
    if not belts:
        raise ProjectError("В model_data.json нет тел p1…p12 (пояса стенки)")
    t["belts_thickness"] = [b["thickness_mm"] for b in belts]
    for key, body in (("bottom_thickness", "dno"), ("edge_thickness", "okrayka")):
        v = ai.body_thickness_mm(md, body)
        if v is not None:
            t[key] = v
    xmax = (md.get("bbox") or {}).get("xmax")
    if xmax:
        t["wall_height"] = round(xmax * 1000)
        t["belt_height"] = round(xmax * 1000 / len(belts))
    t["diameter"] = a.get("nominal_diameter_mm") or round(2 * ai.mean_radius_m(md) * 100) * 10
    an_name, loads = ai.loads(md, a.get("analysis_full"))
    raw["loads_ansys"] = {"analysis": an_name, "items": loads, "labels": a.get("load_labels", {})}
    hydro = next((x for x in loads if x["type"] == "HydrostaticPressure" and not x["suppressed"]), None)
    if hydro:
        t["fill_level"] = round(hydro["level_m"] * 1000)
        t["product_density"] = hydro["density"]
    mi = ai.mesh_info(md)
    raw["mesh"] = {"nodes": mi["nodes"], "elements": mi["elements"], "element_size_mm": mi["element_size_mm"],
                   "element_type": a.get("element_type") or ("SHELL181" if mi["order"] == "Linear" else "SHELL281")}
    return md


def _num(x) -> float:
    return float(str(x).replace(",", "."))


def _load_belts(path: Path, n: int) -> list[dict]:
    res = [{"belt": int(r["belt"]), "fiber": _num(r["fiber"]), "equivalent": _num(r["equivalent"]),
            "membrane": _num(r["membrane"])} for r in _read_csv(path)]
    if len(res) != n:
        raise ProjectError(f"{path.name}: {len(res)} поясов, а в модели {n}")
    return res


def _load_stability(root: Path, r: dict) -> list[dict]:
    """Либо список в yaml (stability), либо stability.csv из export_results.py:
    stability_csv + stability_labels {"Eigenvalue Buckling": "Ветер Y"} + stability_modes (сколько мод брать)."""
    if r.get("stability_csv"):
        labels, modes = r.get("stability_labels", {}), int(r.get("stability_modes", 2))
        out = []
        for row in _read_csv(root / r["stability_csv"]):
            if int(row["mode"]) <= modes:
                out.append({"case": f"{labels.get(row['analysis'], row['analysis'])}, мода {row['mode']}",
                            "k": round(_num(row["k"]), 1)})
        return out
    return list(r.get("stability", []))
