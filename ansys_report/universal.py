"""Универсальный отчёт: описание любого проекта Ansys без привязки к типу объекта.
Из выгрузки (model_data.json, engineering_data.xml, modes.csv, рисунки) собирается Word: объект, модель, материалы,
сетка, расчёты (настройки, нагрузки, закрепления), результаты (частоты, рисунки)."""
from __future__ import annotations
import csv
import json
import re
from collections import OrderedDict
from pathlib import Path

import docx

from .word_gen import Report, TEMPLATE, CENTER
from . import ansys_import as ai

SKIP_PROPS = {"Location", "Figures", "Images", "Comments", "Children", "Suppressed", "Name", "Visible", "Active",
              "ObjectState", "State"}
SETTINGS_LABELS = [
    ("MaximumModesToFind", "Число искомых мод"),
    ("LimitSearchToRange", "Поиск ограничен диапазоном частот"),
    ("SearchRangeMinimum", "Минимальная частота поиска"),
    ("SearchRangeMaximum", "Максимальная частота поиска"),
    ("Damped", "Учёт демпфирования"),
    ("SolverType", "Тип решателя"),
    ("SolverUnitSystem", "Система единиц решателя"),
    ("NumberOfSteps", "Число шагов нагружения"),
    ("StepEndTime", "Время конца шага"),
    ("LargeDeflection", "Большие перемещения"),
    ("MaximumModesToFind", "Число искомых мод"),
]
DIM_RU = {"ThreeD": "объёмное", "TwoD": "оболочка", "Solid": "объёмное", "Shell": "оболочка", "Surface": "оболочка",
          "Line": "линейное (балка)", "Beam": "линейное (балка)"}
TYPE_RU = {"Static": "статический прочностной", "Modal": "модальный", "Buckling": "расчёт на устойчивость",
           "Harmonic": "гармонический", "Transient": "переходный процесс", "Thermal": "тепловой"}


class _Shim:
    """Минимальный «проект» для оформления (колонтитулы, титул, поиск рисунков)."""
    def __init__(self, root: Path, report: dict, name: str, images: dict):
        self.report, self.tank = report, {"name": name, "tag": ""}
        self.root, self.raw = root, {"images_dir": "images", "images": images}


def _val(text: str) -> str:
    """'0.25 [m]' -> '0,25 м'; прочее — как есть."""
    t = str(text)
    m = re.match(r"^\s*(-?[\d.]+(?:[eE][-+]?\d+)?)\s*\[(.*)\]\s*$", t)
    if m:
        num, unit = m.groups()
        try:
            f = float(num)
            num = ("%g" % round(f, 6)).replace(".", ",") if abs(f) < 1e9 else ("%.3g" % f).replace(".", ",")
        except ValueError:
            pass
        return f"{num} {unit}".replace("m s^-1", "м/с").replace(" m", " м").replace(" Hz", " Гц")
    return {"True": "да", "False": "нет"}.get(t, t)


def _num(t) -> str:
    try:
        return ("%.4g" % float(t)).replace(".", ",")
    except (TypeError, ValueError):
        return str(t)


def _read_modes(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f)]


class UniversalReport(Report):
    def __init__(self, data_dir: Path, anketa: dict | None = None):
        self.dir = Path(data_dir)
        self.md = json.loads((self.dir / "model_data.json").read_text(encoding="utf-8"))
        ed = self.dir / "engineering_data.xml"
        self.mats = ai.read_engineering_data(ed) if ed.exists() else {}
        self.modes = _read_modes(self.dir / "modes.csv")
        a = anketa or {}
        year = a.get("year") or ""
        report = {"number": a.get("number") or "", "year": year or 2026,
                  "title": a.get("title") or "Расчёт методом конечных элементов в Ansys Mechanical",
                  "executor_position": a.get("executor_position") or "", "executor_name": a.get("executor_name") or "",
                  "contractor": a.get("contractor") or "", "contractor_phone": a.get("phone") or ""}
        self.anketa = a
        self.obj_name = a.get("tank_name") or "Объект"
        self.p = _Shim(self.dir, report, self.obj_name, {})
        self.d = docx.Document(TEMPLATE)
        self.fig = self.tab = 0
        self.missing: list[str] = []
        self.images = self._collect_images()

    # ---------- рисунки ----------
    def _collect_images(self) -> list[tuple[str, str]]:
        """[(ключ, подпись)] по файлам images/: общий вид, сетка, затем результаты по расчётам."""
        folder = self.dir / "images"
        out, raw = [], {}
        if not folder.exists():
            return out
        files = sorted(p.name for p in folder.glob("*.png"))
        for fn in files:
            stem = fn[:-4]
            if stem in ("fig01_general", "fig02_mesh_wall_bottom", "fig03_mesh_wall_roof", "fig04_loads", "fig05_hydrostatic"):
                continue
            key = f"u_{len(out) + 1}"
            raw[key] = fn
            out.append((key, stem.replace("_", " ")))
        self.p.raw["images"] = raw
        return out

    def _shrink(self, name: str) -> str | None:
        """Крупные снимки (4000 px) уменьшаем для документа."""
        f = self.dir / "images" / name
        if not f.exists():
            return None
        try:
            from PIL import Image
            with Image.open(f) as im:
                if im.width > 1800:
                    im.thumbnail((1800, 1800))
                    im.save(f)
        except Exception:       # noqa: BLE001
            pass
        return name

    # ---------- разделы ----------
    def sec_object(self):
        a, md = self.anketa, self.md
        self.h1("1 Общие сведения")
        items = [("Наименование объекта", self.obj_name), ("Позиция", a.get("tag")), ("Площадка / заказчик", a.get("site")),
                 ("Назначение", a.get("purpose")), ("Документация", a.get("kmd"))]
        rows = [[k, v] for k, v in items if v]
        self.body("Технический отчёт содержит описание конечно-элементной модели и результатов расчёта, "
                  "выполненного в программном комплексе Ansys Mechanical.")
        if rows:
            self.table(["Параметр", "Значение"], rows, widths=[6.5, 10], caption="Сведения об объекте", size=11)
        self.h1("2 Описание модели")
        bodies = md.get("bodies", [])
        groups: "OrderedDict[tuple, int]" = OrderedDict()
        for b in bodies:
            dim = DIM_RU.get(str(b.get("dimension")), "–")
            th = b.get("thickness")
            th = _val(th) if th and not str(th).startswith("0 ") else "–"
            groups[(b["name"], dim, b.get("material") or "–", th)] = groups.get((b["name"], dim, b.get("material") or "–", th), 0) + 1
        bb = md.get("bbox") or {}
        ax = md.get("vertical_axis") or "X"
        self.h2(f"2.1 Геометрия")
        s = f"Модель состоит из {len(bodies)} тел"
        if bb:
            k = 0.001 if bb["rmax"] > 500 else 1.0                  # координаты узлов в мм (проект в мм) или в м
            s += (f"; габарит по вертикали: {self._m((bb['xmax'] - bb['xmin']) * k)} м, "
                  f"наибольший радиус: {self._m(bb['rmax'] * k)} м")
        self.body(s + ".")
        if self._find_image("fig01_general"):
            self.figure("fig01_general", "Общий вид модели")
        rows = [[n, d, m, th, c] for (n, d, m, th), c in groups.items()]
        self.table(["Тело", "Тип", "Материал", "Толщина", "Кол-во"], rows, widths=[4.2, 3.4, 4.2, 2.6, 2.0],
                   caption="Состав модели", size=10)

    @staticmethod
    def _m(v) -> str:
        return ("%.3g" % v).replace(".", ",") if abs(v) < 1000 else str(round(v))

    def sec_materials(self):
        self.h2("2.2 Материалы")
        assigned = {m["name"]: (m.get("props") or {}).get("AssignedBodies", "–") for m in self.md.get("materials", [])}
        names = list(assigned) or list(self.mats)
        if not names:
            self.body("Сведения о материалах в выгрузке отсутствуют.")
            return
        rows = []
        for n in names:
            pr = self.mats.get(n, {})
            sm = ai.material_summary(pr) if pr else {}
            f = lambda k: (str(sm[k]).replace(".", ",") if k in sm else "–")      # noqa: E731
            snd = pr.get("Speed of Sound")
            rows.append([n, f("density"), f("young_modulus_mpa"), f("poisson"), f("yield_mpa"),
                         f("ultimate_mpa"), (str(snd).replace(".", ",") if snd else "–"), assigned.get(n, "–")])
        self.body("Свойства материалов приняты по данным проекта Ansys (Engineering Data) и приведены в таблице "
                  f"{self.tab + 1}.")
        self.table(["Материал", "Плотность, кг/м³", "Модуль Юнга, МПа", "Коэфф. Пуассона", "Предел текучести, МПа",
                    "Предел прочности, МПа", "Скорость звука, м/с", "Назначен телам"], rows,
                   widths=[2.9, 1.9, 2.1, 1.9, 2.1, 2.1, 1.9, 1.9], caption="Свойства материалов", size=9)
        free = [n for n in names if str(assigned.get(n)) in ("0", "–")]
        if free:
            self.body("Внимание: материал " + ", ".join(free) + " не назначен ни одному телу модели.")

    def sec_mesh(self):
        md = self.md
        mo = md.get("mesh_object") or {}
        self.h1("3 Сетка конструкции")
        parts = []
        if md.get("node_count"):
            parts.append(f"количество узлов сетки: {md['node_count']} шт.")
        if md.get("element_count"):
            parts.append(f"количество конечных элементов: {md['element_count']} шт.")
        if mo.get("ElementSize"):
            parts.append(f"размер элементов: {_val(mo['ElementSize'])}")
        if mo.get("ElementOrder"):
            parts.append("порядок элементов: " + {"Linear": "линейный", "Quadratic": "квадратичный"}.get(mo["ElementOrder"], mo["ElementOrder"]))
        self.body("Параметры сетки: " + "; ".join(parts) + "." if parts else "Параметры сетки в выгрузке отсутствуют.")
        if self._find_image("fig02_mesh_wall_bottom"):
            self.figure("fig02_mesh_wall_bottom", "Конечно-элементная модель (сетка)")

    def _n(self, base: int) -> int:
        """Номер раздела: после «Исходных нагрузок» (раздел 4, если он есть) последующие сдвигаются на 1."""
        return base + (1 if getattr(self, "_loads_shown", False) else 0)

    def sec_loads(self):
        """Раздел «Исходные нагрузки»: из файла loads_data.py пакета (если передан в анкете как loads_file)."""
        lf = self.anketa.get("loads_file")
        if not lf or not Path(lf).exists():
            return
        ns: dict = {}
        try:
            exec(Path(lf).read_text(encoding="utf-8"), ns)
            L = ns["LOADS"]
        except Exception:       # noqa: BLE001
            return
        f = lambda v, n=2: ("%.*f" % (n, float(v))).replace(".", ",")          # noqa: E731
        self._loads_shown = True
        self.h1("4 Исходные нагрузки")
        self.body("Нагрузки рассчитаны по методике ГОСТ 31385-2016 и СП 20.13330 и наложены на модель сценарием Mechanical. "
                  "Значения приведены расчётные (с коэффициентами сочетаний, принятыми в расчёте нагрузок).")
        g = L.get("gravity_mm_s2", 9800.0) / 1000.0
        geo = L.get("geometry") or {}
        if geo:
            self.body(f"Резервуар: диаметр {f(geo.get('diameter_mm', 0) / 1000)} м, высота стенки {f(geo.get('wall_height_mm', 0) / 1000)} м, "
                      f"поясов {geo.get('n_belts', '–')}, высота пояса {f(geo.get('belt_height_mm', 0) / 1000)} м. Ускорение свободного падения {f(g, 2)} м/с².")
        rows = []
        for c in L.get("cases") or []:
            h = c.get("hydro") or {}
            parts = ["собственный вес" if c.get("gravity") else "", "массы оборудования и изоляции" if c.get("masses") else ""]
            if h:
                grad = float(h.get("gradient_mpa_mm", 0))
                top = float(h.get("free_surface_mm", 0))
                rho = grad * 1e9 / g if g else 0
                parts.append(f"гидростатика: плотность {f(rho, 0)} кг/м³, уровень {f(top / 1000)} м, давление у днища {f(grad * top * 1000)} кПа")
            if c.get("uniform_mpa"):
                parts.append(f"давление в газовом пространстве {f(c['uniform_mpa'] * 1000)} кПа")
            if c.get("roof_extra_mpa"):
                parts.append(f"нагрузка на крышу {f(c['roof_extra_mpa'] * 1000, 3)} кПа")
            w = c.get("wind") or []
            if w:
                ps = [abs(x["p_mpa"]) * 1000 for x in w]
                parts.append(f"ветер: {f(min(ps), 3)}–{f(max(ps), 3)} кПа по высоте")
            rows.append([c["name"], "; ".join(x for x in parts if x)])
        if rows:
            self.table(["Расчётный случай", "Нагрузки"], rows, widths=[4.5, 12], caption="Нагрузки по расчётным случаям", size=10)
        wind = next((c["wind"] for c in L.get("cases") or [] if c.get("wind")), [])
        if wind:
            self.table(["Участок по высоте, м", "Ветровая нагрузка, кПа"],
                       [[f"{f(x['z_lo_mm'] / 1000)}–{f(x['z_hi_mm'] / 1000)}", f(abs(x["p_mpa"]) * 1000, 3)] for x in wind],
                       widths=[6, 6], caption="Ветровая нагрузка по высоте", size=10)

    def sec_analyses(self):
        self.sec_loads()
        self.h1(f"{self._n(4)} Расчётные случаи")
        analyses = self.md.get("analyses", [])
        if not analyses:
            self.body("В проекте расчётные случаи не найдены.")
            return
        for i, a in enumerate(analyses, 1):
            self.h2(f"{self._n(4)}.{i} {a['name']}")
            self.body(f"Тип расчёта: {TYPE_RU.get(a.get('type'), a.get('type') or '–')}.")
            st = next((c for c in a["children"] if c["type"] == "ANSYSAnalysisSettings"), None)
            if st:
                rows = [[lbl, _val(st["props"][k])] for k, lbl in dict(SETTINGS_LABELS).items() if k in st["props"]]
                if rows:
                    self.table(["Параметр", "Значение"], rows, widths=[8.5, 8], caption=f"Настройки расчёта «{a['name']}»", size=10)
            loads = [c for c in a["children"] if c["type"] not in ("ANSYSAnalysisSettings", "InitialCondition")]
            if loads:
                rows = []
                for c in loads:
                    kv = [f"{k}: {_val(v)}" for k, v in c["props"].items()
                          if k not in SKIP_PROPS and not str(v).startswith(("List[", "<")) and str(v) not in ("", "None")][:4]
                    rows.append([c["name"], c["type"], "; ".join(kv) or "–"])
                self.table(["Нагрузка / закрепление", "Тип", "Параметры"], rows, widths=[4.5, 4, 8],
                           caption=f"Нагрузки и граничные условия, «{a['name']}»", size=10)

    def _strength_rows(self, summ) -> list[list]:
        """Строки проверки прочности: максимум Equivalent Stress по участкам толщины против расчётного сопротивления (loads_file)."""
        lf = self.anketa.get("loads_file")
        if not lf or not Path(lf).exists():
            return []
        try:
            ns: dict = {}
            exec(Path(lf).read_text(encoding="utf-8"), ns)
            res = ns["LOADS"].get("resistance_mpa") or {}
        except Exception:       # noqa: BLE001
            return []
        if not res:
            return []
        rows = []
        for r in summ:
            m = re.match(r"^Equivalent Stress \((?:участок|пояс) (\d+)\)$", r["result"])
            if not m:
                continue
            try:
                sig = float(r["max"])
            except ValueError:
                continue
            rr = res["hydrotest"] if "идроисп" in r["analysis"] else res["operation"]
            ok = sig <= rr
            rows.append([r["analysis"], m.group(1), _num(sig), _num(rr), _num(rr / sig if sig else 0), "обеспечена" if ok else "не обеспечена"])
        return rows

    def sec_results(self):
        self.h1(f"{self._n(5)} Результаты расчёта")
        shown = False
        if self.modes:
            self.h2(f"{self._n(5)}.1 Собственные частоты и формы колебаний")
            rows = [[r["analysis"], r["mode"], ("%g" % float(r["value"])).replace(".", ","), r.get("unit", "")]
                    for r in self.modes]
            self.table(["Расчёт", "Мода", "Значение", "Ед."], rows, widths=[7.5, 2.2, 3.8, 2.5],
                       caption="Результаты по модам", size=10)
            shown = True
        summ = _read_modes(self.dir / "results_summary.csv")
        if summ:
            self.h2(f"{self._n(5)}.2 Сводка результатов" if self.modes else f"{self._n(5)}.1 Сводка результатов")
            rows = [[r["analysis"], r["result"], _num(r["max"]), _num(r["min"]), r.get("unit", "")] for r in summ]
            self.table(["Расчёт", "Результат", "Максимум", "Минимум", "Ед."], rows, widths=[4.2, 5.2, 2.6, 2.6, 1.8],
                       caption="Экстремальные значения результатов", size=10)
            shown = True
        if self._strength_rows(summ):
            n = f"{self._n(5)}.{3 if (self.modes and summ) else 2 if (self.modes or summ) else 1}"
            self.h2(f"{n} Проверка прочности по эквивалентным напряжениям")
            self.body("Эквивалентные напряжения по Мизесу сопоставлены с расчётным сопротивлением стали, определённым в расчёте нагрузок "
                      "(для гидроиспытаний принимается своё значение коэффициента условий работы). Максимумы получены по конечно-элементной модели "
                      "с фактической геометрией стенки.")
            self.table(["Расчётный случай", "Пояс", "σ экв, МПа", "Расчётное сопротивление, МПа", "Запас", "Вывод"],
                       self._strength_rows(summ), widths=[4.6, 2.4, 2.2, 3.0, 1.8, 2.8], caption="Проверка прочности", size=10)
            shown = True
        if self.images:
            self.h2(f"{self._n(5)}.3 Графические результаты" if (self.modes and summ) else
                    f"{self._n(5)}.2 Графические результаты" if (self.modes or summ) else f"{self._n(5)}.1 Графические результаты")
            for key, cap in self.images:
                self._shrink(self.p.raw["images"][key])
                self.figure(key, cap)
            shown = True
        if False:
            self.h2("5.2 Графические результаты" if self.modes else "5.1 Графические результаты")
            for key, cap in self.images:
                self._shrink(self.p.raw["images"][key])
                self.figure(key, cap)
            shown = True
        if not shown:
            self.body("Результаты расчёта в проекте отсутствуют: расчёт не решён или результаты не сохранены. "
                      "Решите расчёт в Ansys (Solve), сохраните проект и повторите сборку отчёта.")

    def build(self, out: Path) -> Path:
        self.header_footer()
        self.title_page()
        self.toc()
        self._shrink("fig02_mesh_wall_bottom")
        self.sec_object(); self.sec_materials(); self.sec_mesh(); self.sec_analyses(); self.sec_results()
        out.parent.mkdir(parents=True, exist_ok=True)
        self.d.save(out)
        return out


def build_universal(data_dir: Path, out: Path, anketa: dict | None = None) -> tuple[Path, list[str]]:
    rep = UniversalReport(data_dir, anketa)
    path = rep.build(out)
    return path, rep.missing
