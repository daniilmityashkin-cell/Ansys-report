"""Фоновые вычисления: замеры → геометрия и отчёт. Выполняются в отдельных процессах, чтобы не тормозить сайт."""
from __future__ import annotations
import concurrent.futures as cf
import json
from pathlib import Path


README_LOADS = """Наложение нагрузок на модель резервуара в Ansys Workbench.

В папке: loads_data.py - нагрузки (расчётные случаи), apply_loads.py - скрипт для Mechanical, loads.json и loads_summary.csv - те же нагрузки для просмотра.

Способ 1 (из программы Ansys Report):
    python -m ansys_report apply-loads "C:\\Projects\\Tank_1\\Tank_1.wbpj" --loads loads_data.py -o out
    Будет создан проект Tank_1_loads.wbpj, где для каждого расчётного случая добавлен свой Static Structural.

Способ 2 (вручную): положите loads_data.py в папку %TEMP%\\ansys_report_out, откройте модель в Mechanical,
Automation -> Scripting -> «+» -> вставьте содержимое apply_loads.py -> Run.

Важно: путь к проекту и имена файлов - только латиницей. Скрипт проверен на синтаксис, но запускался не во всех версиях Ansys:
проверьте направление стрелок давления (если нагрузки направлены внутрь, задайте переменную ANSYS_REPORT_FLIP=1)
и журнал log_loads.txt.
"""


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
        pack = write_package(compute_loads(json.loads(lp.read_text(encoding="utf-8"))), pack_dir)
        shutil.copy2(SCRIPTS / "apply_loads.py", pack_dir / "apply_loads.py")
        (pack_dir / "Как_наложить_нагрузки.txt").write_text(README_LOADS, encoding="utf-8")
        files += [pack["json"], pack["data"], pack["summary"], pack_dir / "apply_loads.py", pack_dir / "Как_наложить_нагрузки.txt"]
    return {"files": [str(f.relative_to(gen / "result")) for f in files]}


def compute_preview(gen_dir: str) -> None:
    """Просмотр результата (точки, поверхность, развёртка) - бесплатная часть, строится сразу после проверки замеров."""
    from ansys_report.geometry import check, figures
    gen = Path(gen_dir)
    res = check.analyze(check.load_project(gen / "input.json"))
    figures.make_preview(res, gen / "preview")


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
