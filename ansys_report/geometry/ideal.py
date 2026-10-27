"""Идеальный РВС для сравнения по ТЗ: те же размеры и толщины, но без отклонений образующих и без вмятин."""
from __future__ import annotations
import copy


def ideal_project(project: dict) -> dict:
    p = copy.deepcopy(project)
    p["values"] = [[0.0] * len(row) for row in p["values"]]
    p["defects"] = []
    p["wall_includes_defects"] = False
    return p
