"""Фоновые вычисления: замеры → геометрия и отчёт. Выполняются в отдельных процессах, чтобы не тормозить сайт."""
from __future__ import annotations
import concurrent.futures as cf
import json
from pathlib import Path


README_LOADS = """Наложение нагрузок на модель резервуара в Ansys Workbench.

В папке: loads_data.py - нагрузки (расчётные случаи), apply_loads.py - скрипт для Mechanical, loads.json и loads_summary.csv - те же нагрузки для просмотра.

Самый простой путь: папка ansys_model - запустите в ней Open_in_Ansys.bat (читайте README_RU.txt). Ниже - наложение на уже готовый проект.

Способ 1 (из программы Ansys Report):
    python -m ansys_report apply-loads "C:\\Projects\\Tank_1\\Tank_1.wbpj" --loads loads_data.py -o out
    Будет создан проект Tank_1_loads.wbpj, где для каждого расчётного случая добавлен свой Static Structural.

Способ 2 (вручную): положите loads_data.py в папку %TEMP%\\ansys_report_out, откройте модель в Mechanical,
Automation -> Scripting -> «+» -> вставьте содержимое apply_loads.py -> Run.

Важно: путь к проекту и имена файлов - только латиницей. Скрипт проверен на синтаксис, но запускался не во всех версиях Ansys:
проверьте направление стрелок давления (если нагрузки направлены внутрь, задайте переменную ANSYS_REPORT_FLIP=1)
и журнал log_loads.txt.
"""


def _ansys_pack(gen: Path, project: dict, belts_dir: Path, dest: Path, title: str, loads_data, lp: Path):
    """Пакет «открыть в Ansys» для заданных замеров: пояса-грани, днище/окрайка/крыша, каркас крыши. Возвращает папку пакета или None."""
    from ansys_report.geometry import check as gcheck
    bm = gcheck.export_belt_model(project, belts_dir)
    step, zones = bm["step"], bm["zones"]                        # пояса стенки - отдельные грани: результаты Ansys по поясам
    parts = {}
    try:                                                           # достраиваем окрайку, днище и крышу (нужен Open CASCADE)
        from ansys_report.geometry.assembly import build_full_step, default_structure
        sp = gen / "structure.json"
        structure = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        li = json.loads(lp.read_text(encoding="utf-8"))
        base = default_structure(float(li["diameter_m"]), float(li["wall_height_m"]), li.get("roof_rise_m"))
        struct = {"bottom": {**base["bottom"], **(structure.get("bottom") or {})}, "roof": {**base["roof"], **(structure.get("roof") or {})}}
        full = bm["step"].parent / "model_full.step"
        info = build_full_step(step, full, struct)
        if full.stat().st_size > 100_000_000:                       # очень подробная геометрия (много вмятин): полная модель слишком тяжёлая для Ansys
            raise RuntimeError("полная модель %d МБ: оставлена только стенка" % (full.stat().st_size // 1_000_000))
        step = full
        b, r = struct["bottom"], struct["roof"]
        parts = {"disc_mm": float(b["plate_thickness_mm"]), "annular_mm": float(b["annular_thickness_mm"]),
                 "roof_mm": float(r.get("deck_thickness_mm") or li.get("roof_deck_thickness_m", 0.004) * 1000), "rise_mm": info["rise_mm"]}
    except Exception as e:   # noqa: BLE001
        belts_dir.mkdir(parents=True, exist_ok=True)
        (belts_dir / "assembly_error.txt").write_text(f"{type(e).__name__}: {e}", encoding="utf-8")
    if not (step.exists() and zones.exists()):
        return None
    from ansys_report.loads.launcher import write_open_package
    md = write_open_package(dest, step, zones, loads_data,
                            anketa={"tag": title, "tank_name": title, "steel_yield_mpa": json.loads(lp.read_text(encoding="utf-8")).get("ryn_mpa", "")}, parts=parts)
    try:                                                           # каркас крыши и опорное кольцо (если заданы в файле проекта) - балочные элементы в Ansys
        from ansys_report.loads.beams import beams_package
        bp = beams_package(project, float(str(project["diameter"]).replace(",", ".")) * 500.0)
        if bp:
            (md / "beams.json").write_text(json.dumps(bp, ensure_ascii=False), encoding="utf-8")
    except Exception as e:   # noqa: BLE001
        (belts_dir / "beams_error.txt").write_text(f"{type(e).__name__}: {e}", encoding="utf-8")
        (md / "beams_error.txt").write_text(f"{type(e).__name__}: {e}", encoding="utf-8")
    return md


def compute(gen_dir: str, title: str) -> dict:
    """Запускается в рабочем процессе: читает input.json, пишет файлы в result/. Возвращает список файлов."""
    from ansys_report.geometry.pipeline import build_from_points
    gen = Path(gen_dir)
    files = build_from_points(gen / "input.json", gen / "result", {"tag": "tank", "tank_name": title, "number": ""}, log=lambda s: None)
    files = [Path(f) for f in files]
    lp = gen / "loads_input.json"
    if lp.exists():                                                  # расчёт нагрузок: пакет для Ansys + скрипт, который накладывает их в Workbench
        import shutil
        from ansys_report.ansys_connect import SCRIPTS
        from ansys_report.loads.export import write_package
        from ansys_report.loads.rvs_loads import compute as compute_loads
        pack_dir = gen / "result" / "loads"
        loads_res = compute_loads(json.loads(lp.read_text(encoding="utf-8")))
        fill0 = float(loads_res["loads"]["hydrostatic_operation"]["fill_height_m"])
        Hw = float(loads_res["inputs"]["H"])
        levels = [lv for lv in (round(Hw * f, 1) for f in (0.4, 0.7, 0.95)) if abs(lv - fill0) > 0.5]     # серия уровней налива для допустимой высоты
        pack = write_package(loads_res, pack_dir, fill_levels_m=levels)
        pack_ideal = write_package(loads_res, gen / "result" / "loads_ideal")                              # идеальный бак считается без серии уровней
        shutil.copy2(SCRIPTS / "apply_loads.py", pack_dir / "apply_loads.py")
        (pack_dir / "Как_наложить_нагрузки.txt").write_text(README_LOADS, encoding="utf-8")
        files += [pack["json"], pack["data"], pack["summary"], pack_dir / "apply_loads.py", pack_dir / "Как_наложить_нагрузки.txt"]
        proj_main = json.loads((gen / "input.json").read_text(encoding="utf-8-sig"))
        md = _ansys_pack(gen, proj_main, gen / "result" / "belts_src", gen / "result" / "ansys_model", title, pack["data"], lp)
        if md is not None:
            try:                                                       # идеальный РВС (без отклонений и вмятин) - отдельная модель для сравнения по ТЗ
                from ansys_report.geometry.ideal import ideal_project
                _ansys_pack(gen, ideal_project(proj_main), gen / "result" / "belts_ideal", md / "ideal", title + " (идеальный)", pack_ideal["data"], lp)
            except Exception as e:   # noqa: BLE001
                (gen / "result" / "belts_src" / "ideal_error.txt").write_text(f"{type(e).__name__}: {e}", encoding="utf-8")
            files += [p for p in sorted(md.iterdir()) if p.is_file()]
    return {"files": [str(f.relative_to(gen / "result")) for f in files]}


def compute_preview(gen_dir: str) -> None:
    """Просмотр результата (точки, поверхность, развёртка) - бесплатная часть, строится сразу после проверки замеров.
    Ошибка записывается в preview/error.txt, чтобы страница не ждала бесконечно."""
    gen = Path(gen_dir)
    try:
        from ansys_report.geometry import check, figures
        res = check.analyze(check.load_project(gen / "input.json"))
        from ansys_report.geometry.viewer_data import viewer_data
        import json
        pv = gen / "preview"
        pv.mkdir(parents=True, exist_ok=True)
        tmp = pv / "viewer.json.tmp"                      # сначала данные 3D (атомарно), картинки - потом: страница считает просмотр готовым по картинке
        tmp.write_text(json.dumps(viewer_data(res), separators=(",", ":")), encoding="utf-8")
        tmp.replace(pv / "viewer.json")
        for d, info in zip(res["model"].defects, res["dents"]):
            figures.dent_plot(res, d, info, pv / f"dent{info['id']}.png")
        figures.make_preview(res, pv)
        (pv / "ready").write_text("1")                     # признак: все файлы просмотра записаны целиком
    except Exception as e:   # noqa: BLE001
        (gen / "preview").mkdir(parents=True, exist_ok=True)
        (gen / "preview" / "error.txt").write_text(f"{type(e).__name__}: {e}", encoding="utf-8")


class JobRunner:
    """Очередь: пул процессов; по завершении вызывает on_done(gen_id, result|None, error|'')."""
    def __init__(self, workers: int, inline: bool, on_done):
        self.inline, self.on_done = inline, on_done
        self.pool = None if inline else cf.ProcessPoolExecutor(max_workers=max(1, workers))

    def submit(self, gen_id: int, gen_dir: Path, title: str):
        if self.inline:
            try:
                self.on_done(gen_id, compute(str(gen_dir), title), "")
            except Exception as e:   # noqa: BLE001
                self.on_done(gen_id, None, f"{type(e).__name__}: {e}")
            return
        fut = self.pool.submit(compute, str(gen_dir), title)

        def done(f):
            try:
                self.on_done(gen_id, f.result(), "")
            except Exception as e:   # noqa: BLE001
                self.on_done(gen_id, None, f"{type(e).__name__}: {e}")
        fut.add_done_callback(done)

    def submit_preview(self, gen_dir: Path):
        if self.inline:
            try:
                compute_preview(str(gen_dir))
            except Exception:   # noqa: BLE001
                pass
            return
        self.pool.submit(compute_preview, str(gen_dir))

    def shutdown(self):
        if self.pool:
            self.pool.shutdown(wait=False, cancel_futures=True)
