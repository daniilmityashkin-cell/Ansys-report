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
    def report(self): return self.raw["report"]
    @property
    def tank(self): return self.raw["tank"]
    @property
    def material(self): return self.raw["material"]
    @property
    def loads(self): return self.raw["loads"]


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
    for sec in ("report", "tank", "material", "loads", "survey", "results"):
        if sec not in raw:
            raise ProjectError(f"В project.yaml нет раздела '{sec}'")
    t = raw["tank"]
    n = len(t["belts_thickness"])
    if abs(n * t["belt_height"] - t["wall_height"]) > 1:
        raise ProjectError(f"{n} поясов × {t['belt_height']} мм ≠ высоте стенки {t['wall_height']} мм")
    s = raw["survey"]
    full = _load_survey(root / s["full"], n, s["points_per_belt"])
    empty = _load_survey(root / s["empty"], n, s["points_per_belt"])
    res = _load_belts(root / raw["results"]["full"], n)
    res_empty = _load_belts(root / raw["results"]["empty"], n) if raw["results"].get("empty") else None
    return Project(root, raw, full, empty, res, res_empty, _load_stability(root, raw["results"]))


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
