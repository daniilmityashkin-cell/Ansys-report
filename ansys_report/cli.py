"""Командная строка: python -m ansys_report <команда> project.yaml [-o папка]"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
from .project import load_project, ProjectError
from .excel_gen import build_excel, export_points_txt
from .word_gen import build_report
from .util import out_names, slug


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ansys_report", description="Автоматизация отчётов по расчёту РВС в Ansys")
    ap.add_argument("command", choices=["excel", "word", "all", "gui", "wizard", "wizard-classic", "apdl", "geometry", "geometry-classic", "loads", "apply-loads", "report-from-ansys", "package", "agent", "worker", "extract-ideal", "check-ansys"], help="что сформировать")
    ap.add_argument("project", nargs="?", help="путь к project.yaml")
    ap.add_argument("-o", "--out", default="out", help="папка результата (по умолчанию ./out)")
    ap.add_argument("--loads", help="apply-loads: файл loads_data.py из пакета нагрузок")
    ap.add_argument("--anketa", help="report-from-ansys: файл anketa.json (поля отчёта: номер, позиция, исполнитель и т. д.)")
    ap.add_argument("--version", type=int, help="check-ansys: версия Ansys (221 = 2022 R1, 222, 231, 232, 241, 242, 251, 252, 261 = 2026 R1); по умолчанию самая новая")
    ap.add_argument("--server", help="worker: адрес сайта (очередь расчётов)")
    ap.add_argument("--token", help="worker: токен расчётного сервера (ASR_WORKER_TOKEN)")
    ap.add_argument("--install", action="store_true", help="agent: зарегистрировать ссылки ansysreport:// в Windows")
    ap.add_argument("--ideal", help="report-from-ansys: ideal.json с результатами идеального РВС (без отклонений)")
    ap.add_argument("--no-solve", action="store_true", help="report-from-ansys: не запускать расчёт, взять готовые результаты проекта")
    ap.add_argument("--axis", default="Z", help="apply-loads: вертикальная ось модели (X, Y или Z)")
    a = ap.parse_args(argv)
    if a.command == "extract-ideal":
        # идеальный РВС: решить расчёты в проекте Ansys и записать максимумы напряжений и запас устойчивости в ideal.json
        import json, csv, os, tempfile
        from .ansys_connect import extract
        from .settings import ModelSettings
        if not a.project or not a.loads:
            ap.error("укажите проект .wbpj и --loads loads_data.py")
        os.environ["ANSYS_REPORT_LOADS"] = str(Path(a.loads).resolve())
        os.environ.setdefault("ANSYS_REPORT_IMAGES", "none")          # из идеального РВС нужны только максимумы и k - картинки не снимаем
        data = Path(tempfile.mkdtemp(prefix="ar_ideal_"))
        extract(a.project, data, log=print, solve=True, settings=ModelSettings(vertical_axis="Z", static_prefix="AR:", full_analysis="AR: Эксплуатация"))
        best = {"equivalent": 0.0, "membrane": 0.0, "fiber": 0.0}
        for f in data.glob("*_belts.csv"):
            for row in csv.DictReader(f.open(encoding="utf-8-sig", newline="")):
                for k, col in (("equivalent", "equivalent"), ("membrane", "membrane"), ("fiber", "fiber")):
                    best[k] = max(best[k], float(row[col]))
        ks = []
        st = data / "stability.csv"
        if st.exists():
            ks = [float(r[-1]) for r in list(csv.reader(st.open(encoding="utf-8")))[1:] if r and float(r[-1]) > 0]
        res = {k: round(v, 1) for k, v in best.items()}
        res["k"] = round(min(ks), 2) if ks else None
        from .ansys_connect import wall_deform_mm
        dm = wall_deform_mm(data, "AR: Эксплуатация")
        if dm is not None:
            res["deform_mm"] = round(dm, 2)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        print("Идеальный РВС:", res)
        return 0
    if a.command == "check-ansys":
        from . import compat
        try:
            compat.check_ansys(a.version)
        except Exception as e:      # noqa: BLE001
            print("Ошибка:", e)
            return 1
        return 0
    if a.command == "worker":                      # расчётный сервер: python -m ansys_report worker --server URL --token TOKEN
        import os
        from . import agent
        server = a.server or os.environ.get("ASR_SITE_URL", "http://127.0.0.1:8000")
        token = a.token or os.environ.get("ASR_WORKER_TOKEN", "")
        if not token:
            ap.error("укажите --token (ASR_WORKER_TOKEN сайта, файл server_data/worker_token.txt)")
        return agent.worker(server, token)
    if a.command == "agent":
        from . import agent
        if a.install or not a.project:
            return agent.install()
        return agent.run(a.project)
    if a.command == "package":
        # файл проекта программы геометрии (.json) -> готовый пакет для Ansys (ansys_model) без сайта
        if not a.project:
            ap.error("укажите файл проекта (.json)")
        import json, shutil, tempfile
        from server.loadsinput import build_loads_input
        from server.structinput import structure_from_project
        from server.jobs import compute
        proj = json.loads(Path(a.project).read_text(encoding="utf-8-sig"))
        gen = Path(tempfile.mkdtemp(prefix="ar_pkg_"))
        (gen / "input.json").write_text(json.dumps(proj, ensure_ascii=False), encoding="utf-8")
        (gen / "structure.json").write_text(json.dumps(structure_from_project(proj), ensure_ascii=False), encoding="utf-8")
        (gen / "loads_input.json").write_text(json.dumps(build_loads_input({"l_on": "1"}, proj), ensure_ascii=False), encoding="utf-8")
        print("Строю геометрию и нагрузки (1-2 минуты)...")
        compute(str(gen), "Резервуар")
        err = gen / "result" / "belts_src" / "assembly_error.txt"
        if err.exists():
            print("ВНИМАНИЕ: днище/крыша не достроены:", err.read_text(encoding="utf-8"))
        src = gen / "result" / "ansys_model"
        dst = Path(a.out)
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)
        step = dst / "model.step"
        print(f"Пакет готов: {dst} (model.step {step.stat().st_size / 1e6:.1f} МБ)")
        return 0
    if a.command == "loads":
        if not a.project:
            ap.error("укажите файл исходных данных для расчёта нагрузок (JSON)")
        import json
        from .loads.rvs_loads import compute
        from .loads.export import write_package
        res = compute(json.loads(Path(a.project).read_text(encoding="utf-8-sig")))
        pack = write_package(res, a.out)
        for k in ("json", "data", "summary"):
            print("Файл:", pack[k])
        for n in res["notes"]:
            print("Примечание:", n)
        bad = [s["belt"] for s in res["strength"] if not s["ok"]]
        print("Прочность стенки:", "обеспечена" if not bad else f"НЕ обеспечена в поясах {bad}")
        st = [b["belt"] for b in res["stability"]["belts"] if b["ok"] is False]
        print("Устойчивость стенки:", "обеспечена" if not st else f"НЕ обеспечена в поясах {st}")
        return 0
    if a.command == "apply-loads":
        if not (a.project and a.loads):
            ap.error("укажите проект Workbench (.wbpj/.wbpz) и --loads loads_data.py")
        from .ansys_connect import apply_loads_to_project, ConnectError
        try:
            apply_loads_to_project(a.project, a.loads, a.out, log=print, axis=a.axis)
            print("Готово. Журнал наложения нагрузок:", Path(a.out) / "log_loads.txt")
        except ConnectError as e:
            print(f"Ошибка: {e}", file=sys.stderr)
            return 2
        return 0
    if a.command == "report-from-ansys":
        if not a.project:
            ap.error("укажите проект Workbench (.wbpj)")
        import json
        from .wizard import build_from_ansys, FIELDS
        from .ansys_connect import ConnectError
        anketa = {k: d for k, _, d in FIELDS}
        if a.anketa:
            anketa.update({k: v for k, v in json.loads(Path(a.anketa).read_text(encoding="utf-8-sig")).items() if str(v).strip()})
        from .settings import ModelSettings
        import os
        os.environ.setdefault("ANSYS_REPORT_IMAGES", "report")            # картинки только тех случаев, что идут в отчёт
        if a.loads:
            anketa["loads_file"] = str(Path(a.loads).resolve())
            import os
            os.environ["ANSYS_REPORT_LOADS"] = anketa["loads_file"]      # скрипты выгрузки берут толщины поясов из loads_data.py
            try:                                                           # плотность продукта и уровень налива - из первого случая с гидростатикой
                ns: dict = {}
                exec(Path(anketa["loads_file"]).read_text(encoding="utf-8"), ns)
                Ld = ns["LOADS"]
                h = next(c["hydro"] for c in Ld["cases"] if c.get("hydro"))
                anketa.setdefault("fill_level", round(h["free_surface_mm"]))
                anketa.setdefault("product_density", round(h["gradient_mpa_mm"] * 1e9 / (Ld["gravity_mm_s2"] / 1000.0)))
            except Exception:       # noqa: BLE001
                pass
        if a.ideal and Path(a.ideal).exists():
            anketa["ideal"] = json.loads(Path(a.ideal).read_text(encoding="utf-8"))
        axis = str(anketa.pop("vertical_axis", "Z")).upper()          # модель с сайта: вертикаль - ось Z
        try:
            files = build_from_ansys(a.project, a.out, anketa, log=print, solve=not a.no_solve, settings=ModelSettings(vertical_axis=axis, static_prefix="AR:", full_analysis="AR: Эксплуатация",
                                                                                          buckling_labels={"Eigenvalue Устойчивость пустого резервуара": "Пустой резервуар: вакуум, снег и ветер"}))
        except (ConnectError, FileNotFoundError) as e:
            print(f"Ошибка: {e}", file=sys.stderr)
            return 2
        for f in files:
            print("Файл:", f)
        return 0
    if a.command == "wizard":
        from .webui import main as web_main
        return web_main()
    if a.command == "wizard-classic":
        from .wizard import main as wiz_main
        return wiz_main()
    if a.command == "gui":
        from .gui import main as gui_main
        return gui_main()
    if a.command == "geometry-classic":
        from .geometry.rvs_gui import main as geo_main
        geo_main()
        return 0
    if a.command == "geometry":
        if not a.project:
            ap.error("укажите путь к файлу замеров (JSON)")
        from .geometry.pipeline import build_from_points
        for f in build_from_points(a.project, a.out, {}):
            print("Файл:", f)
        return 0
    if not a.project:
        ap.error("укажите путь к project.yaml")
    try:
        p = load_project(a.project)
    except (ProjectError, FileNotFoundError, KeyError) as e:
        print(f"Ошибка исходных данных: {e}", file=sys.stderr); return 2
    out, tag = Path(a.out), p.tank["tag"]
    nm = out_names(tag, p.report["number"])
    if a.command == "apdl":
        from .apdl_gen import write_apdl
        print("APDL:", write_apdl(p, out / f"deform_{slug(tag)}_full.inp"))
        return 0
    if a.command in ("excel", "all"):
        print("Excel:", build_excel(p, out / nm["excel"]))
        print("Точки:", export_points_txt(p, p.survey_full, out / nm["full"]))
        print("Точки:", export_points_txt(p, p.survey_empty, out / nm["empty"]))
    if a.command in ("word", "all") and not p.has_results:
        print("Word-отчёт пропущен: нет результатов Ansys (results.full). Выгрузите их скриптом export_results.py.")
    elif a.command in ("word", "all"):
        path, missing = build_report(p, out / nm["word"])
        print("Word:", path)
        if missing: print(f"Нет {len(missing)} рисунков (вставлены заглушки): {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
