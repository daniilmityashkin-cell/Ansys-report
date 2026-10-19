"""Проверка замеров стенки резервуара по допускам и построение геометрии.

Вход - проект замеров (JSON формата «RVS Geometry»: диаметр, высота, углы образующих, отметки по высоте,
отклонения Δr в мм (+ наружу, − внутрь), пояса с толщинами, локальные вмятины).
Выход - оценка каждой точки по допускам H/200 и H/200 + 30 мм (ГОСТ 31385-2016, как в таблицах исходных данных),
сведения о вмятинах и CAD-поверхность (STEP/IGES) через ядро rvs_core.
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np

from . import rvs_core as rc

TOL_EXTRA_MM = 30.0     # добавка ко второму допуску, мм
TOL_DIVISOR = 200.0     # допуск 1/200 от высоты расположения точки


def load_project(source) -> dict:
    """Читает проект замеров из файла JSON (путь) или принимает уже загруженный словарь."""
    if isinstance(source, dict):
        return source
    return json.loads(Path(source).read_text(encoding="utf-8-sig"))


def analyze(project: dict) -> dict:
    """Оценка замеров по допускам. Допуски считаются по высоте отметки: A = H/200, B = H/200 + 30 мм (в мм)."""
    model = rc.TankModel(project)
    z = model.z
    angles = np.degrees(model.theta)
    field = model.field(model.theta, model.z)          # (отметки × образующие), мм, с учётом вмятин
    nz, ng = field.shape
    belts = []
    over_a_total = over_b_total = n_total = 0
    worst = []
    cell = np.zeros(field.shape, dtype=int)            # 0 - в допуске, 1 - выше A, 2 - выше B
    for j in range(1, nz):                              # отметка 0 - днище, замеры начинаются с первого пояса
        lim_a = z[j] * 1000.0 / TOL_DIVISOR
        lim_b = lim_a + TOL_EXTRA_MM
        row = np.abs(field[j])
        oa, ob = int((row > lim_a).sum()), int((row > lim_b).sum())
        cell[j] = (row > lim_a).astype(int) + (row > lim_b).astype(int)
        i = int(np.argmax(row))
        belts.append({"belt": j, "z_m": float(z[j]), "lim_a": float(lim_a), "lim_b": float(lim_b),
                      "max_abs": float(row[i]), "max_gen": i + 1, "over_a": oa, "over_b": ob, "n": ng})
        over_a_total += oa
        over_b_total += ob
        n_total += ng
        for g in range(ng):
            worst.append({"belt": j, "gen": g + 1, "angle": float(angles[g]), "z_m": float(z[j]), "dev": float(field[j, g]),
                          "lim_a": float(lim_a), "lim_b": float(lim_b), "ratio_a": float(row[g] / lim_a)})
    worst.sort(key=lambda r: -r["ratio_a"])
    gens = []
    for g in range(ng):
        col = np.abs(field[1:, g])
        gens.append({"gen": g + 1, "angle": float(angles[g]), "max_abs": float(col.max()),
                     "over_a": int((cell[1:, g] >= 1).sum()), "over_b": int((cell[1:, g] >= 2).sum())})
    dents = []
    for d in model.defects:
        depth = float(-np.min(d.values)) if d.sign < 0 else float(np.max(d.values))
        dents.append({"id": d.id, "name": d.name, "s_m": float(d.sc), "angle": float(d.sc / model.R * 180 / np.pi),
                      "z_m": float(d.zc), "depth_mm": depth, "sign": "вмятина" if d.sign < 0 else "выпучина",
                      "width_m": float(d.x[-1] - d.x[0]), "height_m": float(d.y[-1] - d.y[0]), "n_points": int(d.values.size)})
    return {
        "diameter_m": model.D, "height_m": model.H, "radius_m": model.R, "angles": angles.tolist(), "heights": z.tolist(),
        "field": field, "cell": cell, "belts": belts, "gens": gens, "worst": worst, "dents": dents,
        "bands": model.bands, "groups": rc.thickness_groups(model.bands),
        "n_points": n_total, "over_a": over_a_total, "over_b": over_b_total,
        "ok_a": over_a_total == 0, "ok_b": over_b_total == 0,
        "max_abs": max(b["max_abs"] for b in belts), "point_error": model.point_error,
        "includes_defects": model.includes_defects, "threshold": model.threshold, "model": model,
    }


def export_geometry(project: dict, out_dir: Path, tolerance_mm: float = 0.1, fmt: str = "STEP + IGES", log=print) -> dict:
    """Строит CAD-оболочку (STEP/IGES, мм, 1:1) и записывает вспомогательные файлы. Возвращает сведения о проверке."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model = rc.TankModel(project)
    poles, tu, tv, check = rc.make_cad(model, tolerance_mm, log)
    groups = rc.thickness_groups(model.bands)
    files = []
    if "STEP" in fmt:
        rc.step_write(out_dir / "Поверхность РВС.step", poles, tu, tv, groups)
        files.append(out_dir / "Поверхность РВС.step")
    if "IGES" in fmt:
        rc.iges_write(out_dir / "Поверхность РВС.igs", poles, tu, tv, groups)
        files.append(out_dir / "Поверхность РВС.igs")
    rc.save_metadata(model, out_dir, check)
    check["files"] = [str(f) for f in files]
    check["groups"] = groups
    return check
