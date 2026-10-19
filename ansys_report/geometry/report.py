"""Word-отчёт «Оценка геометрии стенки резервуара по замерам»: исходные данные, допуски, оценка по точкам, геометрия, выводы."""
from __future__ import annotations
from pathlib import Path

import docx

from ..word_gen import Report, TEMPLATE
from ..universal import _Shim

ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX"]


def _f(x, nd=1) -> str:
    s = f"{x:.{nd}f}"
    return s.replace(".", ",").replace("-", "−") if s.startswith("-") else s.replace(".", ",")


class PointsReport(Report):
    def __init__(self, res: dict, figs: dict, anketa: dict | None = None, export_check: dict | None = None):
        a = anketa or {}
        self.res, self.check = res, export_check
        self.anketa = a
        report = {"number": a.get("number") or "", "year": a.get("year") or 2026,
                  "title": a.get("title") or "Оценка геометрии стенки резервуара по результатам геодезических измерений",
                  "executor_position": a.get("executor_position") or "", "executor_name": a.get("executor_name") or "",
                  "contractor": a.get("contractor") or "", "contractor_phone": a.get("phone") or ""}
        self.obj = a.get("tank_name") or "Резервуар"
        images = {k: Path(v).name for k, v in figs.items()}
        root = Path(next(iter(figs.values()))).parent.parent if figs else Path(".")
        self.p = _Shim(root, report, self.obj, images)
        self.p.raw["images_dir"] = Path(next(iter(figs.values()))).parent.name if figs else "images"
        self.d = docx.Document(TEMPLATE)
        self.fig = self.tab = 0
        self.missing: list[str] = []

    # ---------- разделы ----------
    def sec1(self):
        r, a = self.res, self.anketa
        self.h1("1 Исходные данные")
        self.h2("1.1 Параметры резервуара")
        rows = [["Наименование объекта", self.obj]]
        if a.get("tag"):
            rows.append(["Позиция", a["tag"]])
        if a.get("site"):
            rows.append(["Площадка", a["site"]])
        rows += [["Диаметр, м", _f(r["diameter_m"], 2)], ["Высота стенки, м", _f(r["height_m"], 2)],
                 ["Число поясов", len(r["bands"])], ["Число образующих", len(r["angles"])],
                 ["Число точек замера (без днища)", r["n_points"]], ["Число локальных участков (вмятин, выпучин)", len(r["dents"])]]
        self.table(["Наименование величины", "Значение"], rows, widths=[11, 5], caption="Характеристика объекта")
        self.h2("1.2 Результаты измерений")
        self.body("Отклонения образующих стенки от вертикали измерены по поясам. Знак «+» – отклонение наружу, «−» – внутрь, значения в мм. "
                  "На отметке 0 (уторный узел) отклонение принято равным нулю.")
        f, z, ang = r["field"], r["heights"], r["angles"]
        step = 13
        for k0 in range(0, len(ang), step):
            cols = list(range(k0, min(k0 + step, len(ang))))
            head = ["Z, м"] + [f"№{g + 1}" for g in cols]
            rows = [[_f(z[j], 2)] + [_f(f[j, g], 1) for g in cols] for j in range(len(z))]
            w0 = 1.5
            wd = (16.0 - w0) / len(cols)
            self.table(head, rows, widths=[w0] + [wd] * len(cols), size=9,
                       caption="Отклонения образующих стенки от вертикали, мм" + (f" (образующие {cols[0] + 1}–{cols[-1] + 1})" if len(ang) > step else ""))
        self.h2("1.3 Пояса и толщины стенки")
        rows = [[ROMAN[b["number"] - 1] if b["number"] <= len(ROMAN) else b["number"], _f(b["bottom_m"], 3), _f(b["top_m"], 3), _f(b["thickness_mm"], 1)]
                for b in r["bands"]]
        self.table(["Пояс", "Низ, м", "Верх, м", "Толщина, мм"], rows, widths=[3, 4, 4, 4], caption="Пояса стенки")
        if r["dents"]:
            self.h2("1.4 Локальные дефекты")
            rows = [[d["name"], d["sign"], _f(d["s_m"], 2), _f(d["angle"], 1), _f(d["z_m"], 2), _f(d["depth_mm"], 1),
                     f"{_f(d['width_m'], 1)} × {_f(d['height_m'], 1)}"] for d in r["dents"]]
            self.table(["Участок", "Вид", "s, м", "φ, °", "Z, м", "Глубина, мм", "Размер, м"], rows, widths=[3.2, 2.2, 1.8, 1.8, 1.8, 2.4, 2.8],
                       caption="Локальные дефекты геометрии стенки", size=10)

    def sec2(self):
        self.h1("2 Нормативные требования и допуски")
        self.body("В соответствии с ГОСТ Р 58622-2019 (п. 7.2.3.1) в модели стенки резервуара учитываются толщины поясов, отклонения образующих стенки "
                  "от вертикали и моменты инерции опорного кольца. Отклонения образующих строятся по результатам геодезических измерений, "
                  "выполненных при минимальном уровне налива согласно технологической карте.")
        self.body("Допускаемые отклонения образующих от вертикали принимаются по ГОСТ 31385-2016 в виде двух значений для каждого пояса: "
                  "H/200 и H/200 + 30 мм, где H – вертикальное расстояние от окрайки днища до контролируемого пояса.")
        rows = [[ROMAN[b["belt"] - 1] if b["belt"] <= len(ROMAN) else b["belt"], _f(b["z_m"] * 1000, 0), _f(b["lim_a"], 1), _f(b["lim_b"], 1)]
                for b in self.res["belts"]]
        self.table(["Пояс", "H, мм", "Допуск H/200, мм", "Допуск H/200 + 30 мм, мм"], rows, widths=[2.5, 3, 4.5, 5],
                   caption="Допускаемые отклонения образующих от вертикали")

    def sec3(self):
        r = self.res
        self.h1("3 Оценка отклонений по точкам")
        self.body(f"Каждый из {r['n_points']} замеров сопоставлен с допусками соответствующего пояса. Результаты по поясам приведены в таблице ниже, "
                  "оценка каждой точки – на рисунке 1, отклонения образующих по высоте на фоне допусков – на рисунке 2.")
        rows = [[ROMAN[b["belt"] - 1] if b["belt"] <= len(ROMAN) else b["belt"], _f(b["lim_a"], 1), _f(b["lim_b"], 1), _f(b["max_abs"], 1),
                 f"№{b['max_gen']}", f"{b['over_a']} из {b['n']}", f"{b['over_b']} из {b['n']}"] for b in r["belts"]]
        self.table(["Пояс", "Допуск H/200, мм", "Допуск H/200+30, мм", "Макс. |Δ|, мм", "Образующая", "Выше H/200", "Выше H/200+30"],
                   rows, widths=[1.8, 2.4, 2.6, 2.4, 2.3, 2.4, 2.6], size=10, caption="Оценка отклонений по поясам")
        self.figure("geo_pointmap", "Оценка точек замера по допускам (число в ячейке – отклонение, мм)", 15.5)
        self.figure("geo_tolerance", "Отклонения образующих по высоте и допуски H/200 и H/200 + 30 мм", 13)
        worst = [w for w in r["worst"] if w["ratio_a"] > 1][:10]
        if worst:
            rows = [[ROMAN[w["belt"] - 1] if w["belt"] <= len(ROMAN) else w["belt"], f"№{w['gen']}", _f(w["angle"], 0), _f(w["z_m"], 2), _f(w["dev"], 1),
                     _f(w["lim_a"], 1), _f(w["lim_b"], 1), _f(w["ratio_a"], 2)] for w in worst]
            self.table(["Пояс", "Образующая", "φ, °", "Z, м", "Δ, мм", "H/200", "H/200+30", "|Δ| / (H/200)"], rows,
                       widths=[1.6, 2.4, 1.6, 1.8, 1.8, 2.0, 2.2, 3.0], size=10, caption="Точки с наибольшим превышением допуска H/200")

    def sec4(self):
        r = self.res
        self.h1("4 Восстановленная геометрия стенки")
        self.body("По результатам замеров построена гладкая поверхность стенки: по окружности использованы периодические, по высоте – естественные "
                  "кубические сплайны радиального отклонения; локальные дефекты учтены отдельными участками с плавным переходом к основной стенке. "
                  f"Погрешность воспроизведения измеренных точек не превышает {_f(max(r['point_error'], 0.001), 3)} мм.")
        self.figure("geo_unfold", "Развёртка стенки: радиальное отклонение Δr, мм", 16)
        self.figure("geo_surface3d", "Восстановленная поверхность стенки (отклонения увеличены в 20 раз)", 12.5)
        for d in r["dents"]:
            self.figure(f"geo_dent{d['id']}", f"{d['name']}: глубина {_f(d['depth_mm'], 1)} мм", 10)
        if self.check:
            c = self.check
            self.body(f"Для расчёта в Ansys геометрия экспортирована в виде единой оболочки с общими рёбрами между участками разной толщины "
                      f"(единицы – мм, масштаб 1:1). Контрольная погрешность экспорта: {_f(c['max_error_mm'], 4)} мм при допуске {_f(c['tolerance_mm'], 2)} мм.")
            rows = [[g["index"], f"{g['first_belt']}–{g['last_belt']}", _f(g["bottom_m"], 3), _f(g["top_m"], 3), _f(g["thickness_mm"], 1)] for g in c["groups"]]
            self.table(["Поверхность", "Пояса", "Низ, м", "Верх, м", "Толщина, мм"], rows, widths=[3, 3, 3.5, 3.5, 3.5],
                       caption="Участки поверхности для назначения толщины оболочки в расчётной модели")

    def sec5(self):
        r = self.res
        self.h1("5 Выводы")
        wb = max(r["belts"], key=lambda b: b["max_abs"])
        items = [
            f"Выполнена оценка {r['n_points']} замеров отклонений образующих стенки {self.obj} от вертикали.",
            (f"Допуск H/200 выполнен во всех точках." if r["ok_a"] else
             f"Допуск H/200 превышен в {r['over_a']} из {r['n_points']} точек."),
            (f"Расширенный допуск H/200 + 30 мм выполнен во всех точках." if r["ok_b"] else
             f"Расширенный допуск H/200 + 30 мм превышен в {r['over_b']} из {r['n_points']} точек."),
            f"Максимальное по модулю отклонение составило {_f(r['max_abs'], 1)} мм ({ROMAN[wb['belt'] - 1] if wb['belt'] <= len(ROMAN) else wb['belt']} пояс, образующая №{wb['max_gen']}).",
        ]
        if r["dents"]:
            dm = max(r["dents"], key=lambda d: d["depth_mm"])
            items.append(f"Выявлено локальных дефектов: {len(r['dents'])}; наибольшая глубина – {_f(dm['depth_mm'], 1)} мм ({dm['name']}).")
        items.append("Построенная поверхность стенки передаётся в расчётную модель для оценки напряжённо-деформированного состояния и устойчивости "
                     "в соответствии с ГОСТ Р 58622-2019 (таблица 13).")
        for k, x in enumerate(items, 1):
            self.body(f"{k}. {x}").paragraph_format.keep_together = True

    def build(self, out: Path) -> Path:
        self.header_footer()
        self.title_page()
        self.toc()
        self.sec1(); self.sec2(); self.sec3(); self.sec4(); self.sec5()
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        self.d.save(out)
        return out
