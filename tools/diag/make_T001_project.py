r"""Проект Т-001 для сверки с эталоном: лист «Т-001 пустой» нивелировки Т001-Т004 + толщины поясов из эталонного отчёта.
Запуск: python tools/diag/make_T001_project.py "<Нивелировка Т001-Т004.xlsx>" C:\ansys_report_work\T001_project.json"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from server.tableinput import build_project, survey_from_xlsx  # noqa: E402

THICK = "16 14 13 12 12 12 12 12 11 11 11 11"                     # tests/data/reference_T001.json, tank.thickness_mm

if __name__ == "__main__":
    raw = Path(sys.argv[1]).read_bytes()
    m = survey_from_xlsx(raw, "Т-001 пустой")
    p = build_project(f"{m['diameter_m']:g}", f"{m['height_m']:g}", m["table"], THICK, "gens")
    Path(sys.argv[2]).write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    print("D =", m["diameter_m"], "м, H =", m["height_m"], "м, поясов", len(p["bands"]), "толщины", [b[1] for b in p["bands"]],
          "высоты поясов", [b[0] for b in p["bands"]], "образующих", len(p["angles"]), "отметок", len(p["heights"]))
