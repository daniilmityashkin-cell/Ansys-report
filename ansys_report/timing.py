"""Замер времени прогона по этапам: каждая точка дописывает в общий файл строку «время<TAB>тег<TAB>этап».
Метка означает начало этапа; длительность этапа - до следующей метки. Пишут: помощник (agent.py), журналы Workbench,
скрипты Mechanical (свою копию функции tmark), report-from-ansys. Файл: AR_TIMING (по умолчанию C:\\ansys_report_work\\timing.log),
тег: AR_TIMING_TAG (идеальный РВС / фактическая форма)."""
from __future__ import annotations
import os
import time
from pathlib import Path

DEFAULT = r"C:\ansys_report_work\timing.log"


def path() -> Path:
    return Path(os.environ.get("AR_TIMING") or DEFAULT)


def mark(label: str) -> None:
    try:
        with open(path(), "a", encoding="utf-8") as f:
            f.write(f"{time.time():.3f}\t{os.environ.get('AR_TIMING_TAG', '')}\t{label}\n")
    except OSError:
        pass


def read(p: str | Path | None = None) -> list[tuple[float, str, str]]:
    rows = []
    for line in Path(p or path()).read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            try:
                rows.append((float(parts[0]), parts[1], parts[2]))
            except ValueError:
                pass
    rows.sort(key=lambda r: r[0])
    return rows


def stages(rows: list[tuple[float, str, str]]) -> list[dict]:
    """Этапы по порядку: метка -> следующая метка. Последняя метка («конец») длительности не имеет."""
    out = []
    for (t0, tag, label), (t1, _, _) in zip(rows, rows[1:]):
        out.append({"tag": tag, "stage": label, "start": t0, "seconds": t1 - t0, "group": label.split(":")[0].strip()})
    return out


def table_md(rows: list[tuple[float, str, str]]) -> str:
    """Таблица Markdown: по этапам и по группам (часть метки до двоеточия), с долей от общего времени."""
    st = stages(rows)
    total = sum(s["seconds"] for s in st) or 1.0
    lines = [f"Всего: {total:.0f} с ({total / 60:.1f} мин)", "", "| Тег | Этап | секунд | % |", "|---|---|---|---|"]
    lines += [f"| {s['tag']} | {s['stage']} | {s['seconds']:.1f} | {100 * s['seconds'] / total:.1f} |" for s in st]
    groups: dict[tuple[str, str], float] = {}
    for s in st:
        groups[(s["tag"], s["group"])] = groups.get((s["tag"], s["group"]), 0.0) + s["seconds"]
    lines += ["", "По группам:", "", "| Тег | Группа | секунд | % |", "|---|---|---|---|"]
    lines += [f"| {t} | {g} | {v:.1f} | {100 * v / total:.1f} |" for (t, g), v in sorted(groups.items(), key=lambda kv: -kv[1])]
    return "\n".join(lines)
