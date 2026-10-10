"""Главное окно продукта: выбрать проект Ansys → заполнить анкету → «Собрать отчёт».
Программа сама запускает Mechanical в фоне, выгружает данные и собирает Word + Excel."""
from __future__ import annotations
import json
import os
import sys
import threading
from datetime import date
from pathlib import Path

FIELDS = [  # ключ шаблона, подпись, значение по умолчанию
    ("number", "Номер отчёта", "ТО-001-26"),
    ("year", "Год", str(date.today().year)),
    ("title", "Название отчёта", "Резервуара РВС на прочность и устойчивость"),
    ("tank_name", "Тип/название резервуара", "РВС"),
    ("tag", "Позиция (номер)", "Т-001"),
    ("site", "Площадка / заказчик", ""),
    ("site_number", "Номер на площадке", ""),
    ("purpose", "Назначение", "хранения технологической воды"),
    ("product", "Продукт", "Техническая вода"),
    ("hazard_class", "Класс опасности", "КС-2а"),
    ("roof_radius", "Радиус крыши, мм", "34200"),
    ("kmd", "Документация (КМД)", ""),
    ("executor_position", "Должность исполнителя", ""),
    ("executor_name", "Исполнитель (Ф.И.О.)", ""),
    ("contractor", "Сведения об исполнителе", ""),
    ("phone", "Телефон", ""),
]
SETTINGS = Path.home() / ".ansys_report_settings.json"


def _load():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_from_ansys(project_file, out_dir, anketa, log=print, reuse_data=False, solve=True):
    """Полный цикл: Ansys → выгрузка → project.yaml → Word/Excel. Возвращает список файлов."""
    from .ansys_connect import extract, make_project_folder
    from .gui import build_all
    # отчёт всегда в отдельной подпапке "Отчёт <позиция>", чтобы не смешиваться с другими файлами
    from .util import out_names
    out_dir = Path(out_dir) / out_names(anketa.get("tag") or "tank", "x")["folder"]
    out_dir.mkdir(parents=True, exist_ok=True)
    data = out_dir / "_ansys_data"
    if not (reuse_data and (data / "model_data.json").exists()):
        extract(project_file, data, log, solve=solve)
    yaml_path = make_project_folder(data, anketa)
    log("Собираю отчёт…")
    files = build_all(yaml_path, out_dir, log)
    log(f"Отчёт лежит в папке: {out_dir}")
    return files


def enable_clipboard(root):
    """Ctrl+V/C/X/A и меню правой кнопки во всех полях ввода, в том числе при русской раскладке."""
    import tkinter as tk

    def ev(w, name):
        w.event_generate(name)
        return "break"

    def on_key(e):
        if not (e.state & 0x4):          # Ctrl не нажат
            return None
        name = {86: "<<Paste>>", 67: "<<Copy>>", 88: "<<Cut>>"}.get(e.keycode)   # коды клавиш V, C, X
        if name:
            return ev(e.widget, name)
        if e.keycode == 65:
            e.widget.select_range(0, "end"); return "break"
        return None

    def menu(e):
        m = tk.Menu(root, tearoff=0)
        for label, name in (("Вставить", "<<Paste>>"), ("Копировать", "<<Copy>>"), ("Вырезать", "<<Cut>>")):
            m.add_command(label=label, command=lambda n=name: e.widget.event_generate(n))
        e.widget.focus_set()
        m.tk_popup(e.x_root, e.y_root)

    root.bind_class("Entry", "<Control-KeyPress>", on_key)
    root.bind_class("Entry", "<Button-3>", menu)


def main() -> int:
    import tkinter as tk
    from tkinter import filedialog, scrolledtext

    st = _load()
    root = tk.Tk()
    enable_clipboard(root)
    root.title("Автоматизация отчётов Ansys")
    root.geometry("820x760")
    proj = tk.StringVar(value=st.get("project", ""))
    outd = tk.StringVar(value=st.get("out", str(Path.home() / "Documents" / "AnsysReport")))
    reuse = tk.BooleanVar(value=False)
    solve = tk.BooleanVar(value=st.get("solve", True))
    vars_ = {k: tk.StringVar(value=st.get("anketa", {}).get(k, d)) for k, _, d in FIELDS}

    tk.Label(root, text="1. Проект Ansys (.wbpj / .wbpz)", font=("", 10, "bold")).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 0))
    tk.Entry(root, textvariable=proj, width=80).grid(row=1, column=0, padx=8, sticky="we")
    tk.Button(root, text="Выбрать…", command=lambda: proj.set(filedialog.askopenfilename(
        filetypes=[("Проект Ansys", "*.wbpj *.wbpz *.mechdb")]) or proj.get())).grid(row=1, column=1, padx=8)
    tk.Label(root, text="2. Папка для отчёта", font=("", 10, "bold")).grid(row=2, column=0, sticky="w", padx=8, pady=(8, 0))
    tk.Entry(root, textvariable=outd, width=80).grid(row=3, column=0, padx=8, sticky="we")
    tk.Button(root, text="Выбрать…", command=lambda: outd.set(filedialog.askdirectory() or outd.get())).grid(row=3, column=1, padx=8)

    form = tk.LabelFrame(root, text="3. Сведения для отчёта (их нет в Ansys)")
    form.grid(row=4, column=0, columnspan=2, sticky="we", padx=8, pady=8)
    for i, (k, label, _) in enumerate(FIELDS):
        tk.Label(form, text=label, anchor="w").grid(row=i // 2, column=(i % 2) * 2, sticky="w", padx=6, pady=2)
        tk.Entry(form, textvariable=vars_[k], width=32).grid(row=i // 2, column=(i % 2) * 2 + 1, padx=6, pady=2)
    tk.Checkbutton(root, text="Не запускать Ansys заново (взять уже выгруженные данные)", variable=reuse
                   ).grid(row=5, column=0, sticky="w", padx=8)
    tk.Checkbutton(root, text="Дорешать расчёты, если в проекте они не решены (дольше, проект не сохраняется)", variable=solve
                   ).grid(row=5, column=1, sticky="w", padx=8)
    box = scrolledtext.ScrolledText(root, height=12, state="disabled")
    box.grid(row=7, column=0, columnspan=2, sticky="nsew", padx=8, pady=8)
    root.grid_rowconfigure(7, weight=1); root.grid_columnconfigure(0, weight=1)

    def log(msg):
        def put():
            box.configure(state="normal"); box.insert("end", msg + "\n"); box.see("end"); box.configure(state="disabled")
        root.after(0, put)

    last = [None]

    def open_folder():
        if sys.platform != "win32":
            return
        if last[0]:
            import subprocess
            subprocess.Popen(["explorer", "/select,", str(Path(last[0]))])   # открыть папку и выделить Word-файл
        else:
            os.startfile(outd.get())

    def work():
        btn.configure(state="disabled")
        anketa = {k: v.get() for k, v in vars_.items()}
        try:
            SETTINGS.write_text(json.dumps({"project": proj.get(), "out": outd.get(), "anketa": anketa, "solve": solve.get()},
                                           ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        try:
            files = build_from_ansys(proj.get().strip().strip('"'), outd.get().strip().strip('"'), anketa, log, reuse.get(), solve.get())
            last[0] = next((f for f in files if f.suffix == ".docx"), files[0] if files else None)
            log("ГОТОВО. Нажмите «Открыть папку».")
        except PermissionError:
            log("ОШИБКА: файл открыт в Word/Excel. Закройте его и повторите.")
        except Exception as e:  # noqa: BLE001
            log(f"ОШИБКА: {type(e).__name__}: {e}")
        finally:
            root.after(0, lambda: btn.configure(state="normal"))

    btn = tk.Button(root, text="СОБРАТЬ ОТЧЁТ", height=2, bg="#2e7d32", fg="white",
                    command=lambda: threading.Thread(target=work, daemon=True).start())
    btn.grid(row=6, column=0, sticky="we", padx=8)
    tk.Button(root, text="Открыть папку", command=open_folder
              ).grid(row=6, column=1, padx=8)
    root.mainloop()
    return 0
