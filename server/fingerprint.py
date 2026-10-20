"""Отпечаток замеров: одни и те же данные на разных аккаунтах распознаются, даже если изменить мелочи (округление до 1 мм)."""
from __future__ import annotations
import hashlib
import json

from ansys_report.geometry.rvs_core import number


def data_key(project: dict) -> str:
    try:
        key = {
            "D": round(number(project["diameter"], "D"), 1), "H": round(number(project["height"], "H"), 1),
            "v": [[round(number(v, "v")) for v in row] for row in project["values"]],
            "t": [round(number(b[1], "t")) for b in project["bands"]],
            "d": sorted(round(number(d.get("anchor", 0), "a")) for d in project.get("defects", [])),
        }
    except Exception:  # noqa: BLE001
        return ""
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
