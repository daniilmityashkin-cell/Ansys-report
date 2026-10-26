r"""Сверка сквозного прогона Т-001 с эталоном (tests/data/reference_T001.json): таблицы по поясам и сводка в Markdown.
Запуск: python tools/diag/compare_T001.py C:\ansys_report_work\e2e_T001 > tools/diag/compare_T001_tables.md
В папке прогона: _ansys_data (AR__Эксплуатация_belts.csv, results_summary.csv, stability.csv) и отчёт .docx."""
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = json.loads((ROOT / "tests" / "data" / "reference_T001.json").read_text(encoding="utf-8"))
CASE = "AR__Эксплуатация"                   # налив 17,2 м (l_fill), фактическая форма


def belts(d: Path) -> dict[int, dict]:
    rows = list(csv.DictReader((d / "_ansys_data" / f"{CASE}_belts.csv").open(encoding="utf-8")))
    return {int(r["belt"]): {k: float(r[k]) for k in ("fiber", "equivalent", "membrane")} for r in rows}


def summary(d: Path) -> dict:
    out = {}
    for r in csv.reader((d / "_ansys_data" / "results_summary.csv").open(encoding="utf-8")):
        if len(r) >= 3 and r[1] in ("Total Deformation", "Equivalent Stress"):
            out[(r[0], r[1])] = r[2]
    return out


def table(ours: dict[int, dict], key: str, ref_key: str, title: str) -> list[str]:
    ref = REF["per_belt_max_mpa"][ref_key]
    t = [f"### {title}", "", "| Пояс | толщина, мм | наш, МПа | эталон, МПа | разница, % |", "|---|---|---|---|---|"]
    for i, r in enumerate(ref, 1):
        o = ours[i][key]
        d = 100.0 * (o - r) / r
        mark = " **!**" if abs(d) > 10 else ""
        t.append(f"| {i} | {REF['tank']['thickness_mm'][i - 1]} | {o:.1f} | {r:.1f} | {d:+.1f}{mark} |")
    return t + [""]


def main(d: Path) -> str:
    ours = belts(d)
    s = summary(d)
    doc = next(d.glob("*.docx"), None)
    fill = ""
    if doc is not None:
        import docx
        fill = next((p.text for p in docx.Document(doc).paragraphs if p.text.startswith("Допустимая высота")), "")
    lines = table(ours, "membrane", "membrane_first_principal", "Мембранные (срединные) σ1")
    lines += table(ours, "equivalent", "equivalent_mises", "Эквивалентные (Мизес), Top/Bottom")
    lines += table(ours, "fiber", "fibre_first_principal", "Фибровые σ1, Top/Bottom")
    a = REF["summary"]["actual"]
    lines += ["### Сводка", "", "| Показатель | наш | эталон |", "|---|---|---|",
              f"| σэкв max (стенка, налив 17,2 м), МПа | {max(v['equivalent'] for v in ours.values()):.1f} | {a['equivalent_mpa']} |",
              f"| σм max, МПа | {max(v['membrane'] for v in ours.values()):.1f} | {a['membrane_mpa']} |",
              f"| σф max, МПа | {max(v['fiber'] for v in ours.values()):.1f} | {a['fibre_mpa']} |",
              f"| перемещение max, мм | {float(s.get(('AR: Эксплуатация', 'Total Deformation'), 'nan')):.1f} | {a['deformation_mm']} |",
              f"| допустимый налив | {re.sub(r'^.*составляет ', '', fill) or '-'} | {REF['summary']['allowed_fill_m']} м |", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    print(main(Path(sys.argv[1])))
