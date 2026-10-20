"""Фоновые вычисления: замеры → геометрия и отчёт. Выполняются в отдельных процессах, чтобы не тормозить сайт."""
from __future__ import annotations
import concurrent.futures as cf
import json
from pathlib import Path


def compute(gen_dir: str, title: str) -> dict:
    """Запускается в рабочем процессе: читает input.json, пишет файлы в result/. Возвращает список файлов."""
    from ansys_report.geometry.pipeline import build_from_points
    gen = Path(gen_dir)
    files = build_from_points(gen / "input.json", gen / "result", {"tag": "tank", "tank_name": title, "number": ""}, log=lambda s: None)
    return {"files": [str(Path(f).relative_to(gen / "result")) for f in files]}


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
