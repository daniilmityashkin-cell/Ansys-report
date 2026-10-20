"""Данные для интерактивного 3D-просмотра на сайте: сетка отклонений стенки, измеренные точки, локальные дефекты (компактный JSON)."""
from __future__ import annotations
import numpy as np


def viewer_data(res: dict, nt: int = 181, nz: int = 73) -> dict:
    m = res["model"]
    theta = np.linspace(0, 2 * np.pi, nt)
    z = np.linspace(0, m.H, nz)
    grid = m.field(theta, z)                                     # [z][theta], мм
    pts = res["field"]                                           # [отметка][образующая], мм
    return {
        "R": m.R, "H": m.H, "D": m.D, "nt": nt, "nz": nz,
        "grid": np.round(grid, 1).ravel().tolist(),
        "angles": [float(a) for a in res["angles"]], "heights": [float(h) for h in res["heights"]],
        "points": np.round(pts, 1).ravel().tolist(),
        "dents": [{"name": d["name"], "angle": d["angle"], "z": d["z_m"], "depth": d["depth_mm"], "sign": d["sign"]} for d in res["dents"]],
        "min": float(min(grid.min(), pts.min())), "max": float(max(grid.max(), pts.max())),
    }
