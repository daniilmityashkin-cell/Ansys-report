"""Простое окно: выбрать project.yaml и папку результата, нажать «Собрать отчёт».
Запуск: python -m ansys_report gui   (или двойной щелчок по run_gui.bat)"""
from __future__ import annotations
import os
import sys
import threading
from pathlib import Path
from .project import load_project, ProjectError
from .excel_gen import build_excel, export_points_txt
from .word_gen import build_report
from .util import out_names


def build_all(project_yaml: str | Path, out_dir: str | Path, log=print) -> list[Path]:
    """Собирает Excel, файлы точек и Word. log(строка) вызывается по ходу работы. Возвращает список файлов."""
    p = load_project(project_yaml)
    out, tag = Path(out_dir), p.tank["tag"]
    nm = out_names(tag, p.report["number"])
    files = []
    files.append(build_excel(p, out / nm["excel"])); log(f"Excel: {files[-1]}")
    for name, dev in (("full", p.survey_full), ("empty", p.survey_empty)):
        files.append(export_points_txt(p, dev, out / nm[name])); log(f"Точки: {files[-1]}")
    if not p.has_results:
        log("Word-отчёт пропущен: нет результатов Ansys (файл results.full не найден). Excel и точки готовы.")
        return files
    path, missing = build_report(p, out / nm["word"])
    files.append(path); log(f"Word: {path}")
    if missing:
        log(f"ВНИМАНИЕ: нет {len(missing)} рисунков (в отчёте красные заглушки): {', '.join(missing)}")
    else:
        log("Все рисунки найдены.")
    return files


def main() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext

    root = tk.Tk()
    root.title("Автоматизация отчётов Ansys (РВС)")
    root.geometry("760x520")
    proj = tk.StringVar(value=str(Path("examples/demo/project.yaml")))
    outd = tk.StringVar(value=str(Path("out")))

    def row(r, label, var, pick):
        tk.Label(root, text=label, anchor="w").grid(row=r, column=0, sticky="w", padx=8, pady=6)
        tk.Entry(root, textvariable=var, width=70).grid(row=r, column=1, padx=4)
        tk.Button(root, text="Выбрать…", command=pick).grid(row=r, column=2, padx=8)

    row(0, "Файл project.yaml", proj, lambda: proj.set(filedialog.askopenfilename(
        filetypes=[("YAML", "*.yaml *.yml")]) or proj.get()))
    row(1, "Папка результата", outd, lambda: outd.set(filedialog.askdirectory() or outd.get()))
    box = scrolledtext.ScrolledText(root, height=20, state="disabled")
    box.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)
    root.grid_rowconfigure(3, weight=1); root.grid_columnconfigure(1, weight=1)

    def log(msg):
        def put():
            box.configure(state="normal"); box.insert("end", msg + "\n"); box.see("end"); box.configure(state="disabled")
        root.after(0, put)

    def work():
        btn.configure(state="disabled")
        try:
            log("Сборка…")
            build_all(proj.get(), outd.get(), log)
            log("Готово. Откройте папку результата.")
        except ProjectError as e:
            log(f"ОШИБКА в исходных данных: {e}")
        except PermissionError:
            log("ОШИБКА: файл открыт в Word/Excel. Закройте его и повторите.")
        except Exception as e:  # noqa: BLE001
            log(f"ОШИБКА: {type(e).__name__}: {e}")
        finally:
            root.after(0, lambda: btn.configure(state="normal"))

    btn = tk.Button(root, text="Собрать отчёт", height=2, command=lambda: threading.Thread(target=work, daemon=True).start())
    btn.grid(row=2, column=0, columnspan=2, sticky="we", padx=8, pady=4)
    tk.Button(root, text="Открыть папку", command=lambda: os.startfile(outd.get()) if sys.platform == "win32" else None
              ).grid(row=2, column=2, padx=8)
    root.mainloop()
    return 0
