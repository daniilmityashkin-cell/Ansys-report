"""Ввод замеров заказчиком на сайте: таблица из Excel + размеры → проект замеров (тот же формат, что и JSON)."""
from __future__ import annotations
import re

from ansys_report.geometry.rvs_core import number

MAX_GENS, MAX_BELTS = 160, 100


def _cells(text: str) -> list[list[str]]:
    rows = []
    for line in (text or "").replace("\r", "").split("\n"):
        if not line.strip():
            continue
        parts = re.split(r"\t|;", line) if ("\t" in line or ";" in line) else re.split(r"\s+", line.strip())
        rows.append([p.strip() for p in parts])
    return rows


def parse_thicknesses(text: str) -> list[float]:
    vals = [v for v in re.split(r"[\s;]+", (text or "").strip()) if v]
    if not vals:
        raise ValueError("Укажите толщины поясов, мм (через пробел или запятую с пробелом: 13 12 12 11 …).")
    out = []
    for i, v in enumerate(vals, 1):
        t = number(v.rstrip(","), f"Толщина пояса {i}")
        if t <= 0:
            raise ValueError(f"Толщина пояса {i} должна быть положительной.")
        out.append(t)
    return out


def build_project(diameter: str, height: str, table: str, thicknesses: str, rows_are: str = "gens") -> dict:
    """rows_are: 'gens' - строки таблицы = образующие, столбцы = пояса (как в таблицах заказчика);
    'belts' - строки = пояса, столбцы = образующие. Отклонения в мм: + наружу, − внутрь.
    Образующие равномерно по окружности (0°, 360°/n, …), пояса равной высоты H/число поясов."""
    D = number(diameter, "Диаметр")
    H = number(height, "Высота")
    if D <= 0 or H <= 0:
        raise ValueError("Диаметр и высота должны быть положительными.")
    rows = _cells(table)
    if not rows:
        raise ValueError("Вставьте таблицу замеров (скопируйте блок чисел из Excel).")
    width = {len(r) for r in rows}
    if len(width) != 1:
        raise ValueError("В таблице строки разной длины. Скопируйте прямоугольный блок без заголовков.")
    grid = [[number(v, f"Таблица, строка {j + 1}, столбец {i + 1}") for i, v in enumerate(r)] for j, r in enumerate(rows)]
    if rows_are == "gens":                                 # транспонируем: строки = пояса
        grid = [list(col) for col in zip(*grid)]
    n_belts, n_gens = len(grid), len(grid[0])
    if n_gens < 3 or n_belts < 1:
        raise ValueError("Нужно минимум 3 образующие и 1 пояс.")
    if n_gens > MAX_GENS or n_belts > MAX_BELTS:
        raise ValueError("Слишком большая таблица.")
    th = parse_thicknesses(thicknesses)
    if len(th) != n_belts:
        raise ValueError(f"Толщин указано {len(th)}, а поясов в таблице {n_belts}. Количество должно совпадать.")
    step = H / n_belts
    heights = [0.0] + [round(step * (k + 1), 9) for k in range(n_belts)]
    heights[-1] = H
    angles = [360.0 * i / n_gens for i in range(n_gens)]
    values = [["0"] * n_gens] + [[repr(v) for v in row] for row in grid]
    return {"version": "1.0", "diameter": repr(D), "height": repr(H), "angles": angles, "heights": heights, "values": values,
            "bands": [[repr(step), repr(t)] for t in th], "defects": [], "contour_threshold": "0.1", "wall_includes_defects": True}
