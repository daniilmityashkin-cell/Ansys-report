"""Мелкие помощники: имена файлов и папок только латиницей (кириллица в путях ломает программы Ansys)."""
from __future__ import annotations
import re

_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
               ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"]))


def slug(text: str, default: str = "x") -> str:
    """'Т-001' -> 'T-001', 'РВС-9985' -> 'RVS-9985'; всё лишнее заменяется на '_'."""
    out = []
    for ch in str(text):
        low = ch.lower()
        if low in _TR:
            t = _TR[low]
            out.append(t.upper() if ch != low else t)
        else:
            out.append(ch)
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", "".join(out)).strip("_")
    return s or default


def out_names(tag: str, number: str) -> dict[str, str]:
    t, n = slug(tag, "tank"), slug(number, "report")
    return {"excel": f"Leveling_{t}.xlsx", "full": f"points_{t}_full.txt", "empty": f"points_{t}_empty.txt",
            "word": f"Report_{n}_{t}.docx", "folder": f"Report_{t}"}
