"""Генерация технического отчёта (Word) по принятой форме технического отчёта."""
from __future__ import annotations
from pathlib import Path
import docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Cm, RGBColor
from .calc import calc_all, fmt
from .project import Project
from . import text_ru as T

TEMPLATE = Path(__file__).parent / "templates" / "base.docx"
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV"]
CENTER = WD_ALIGN_PARAGRAPH.CENTER


class Report:
    def __init__(self, p: Project):
        self.p, self.c = p, calc_all(p)
        self.d = docx.Document(TEMPLATE)
        self.fig = 0
        self.tab = 0
        self.missing: list[str] = []

    # ---------- примитивы (оформление как в образце ТО-019-26: TNR 12, по ширине, отступ 1 см) ----------
    FONT = "Times New Roman"

    @classmethod
    def _run(cls, par, text, size=12, bold=False, italic=False):
        r = par.add_run(text)
        r.font.name = cls.FONT
        r._element.rPr.rFonts.set(qn("w:eastAsia"), cls.FONT)
        r.font.size = Pt(size); r.bold = bold; r.italic = italic
        r.font.color.rgb = RGBColor(0, 0, 0)
        return r

    def para(self, text="", style="Normal", bold=False, align=WD_ALIGN_PARAGRAPH.JUSTIFY, italic=False,
             size=12, indent=1.0, keep_next=False, space_before=0, space_after=0):
        par = self.d.add_paragraph(style=style)
        if text:
            self._run(par, text, size, bold, italic)
        pf = par.paragraph_format
        par.alignment = align
        pf.first_line_indent = Cm(indent) if indent else None
        pf.space_before, pf.space_after = Pt(space_before), Pt(space_after)
        pf.line_spacing = 1.0
        pf.keep_with_next = keep_next
        return par

    def h1(self, text, new_page=False):
        """Заголовок раздела: полужирный 12 пт, абзацный отступ, отбивка 12/6 пт."""
        h = self.d.add_paragraph(style="Heading 1")
        self._run(h, text, 12, bold=True)
        h.alignment = WD_ALIGN_PARAGRAPH.LEFT
        h.paragraph_format.first_line_indent = Cm(1.0)
        h.paragraph_format.space_before, h.paragraph_format.space_after = Pt(12), Pt(6)
        h.paragraph_format.keep_with_next = True
        h.paragraph_format.page_break_before = new_page
        return h

    def h2(self, text):
        """Подраздел (1.1, 2.1 …): полужирный 12 пт по ширине."""
        return self.para(text, bold=True, keep_next=True, space_before=6, space_after=3)

    def body(self, text): return self.para(text)

    def bullets(self, items):
        for it in items:
            self.para("- " + it, indent=1.25)

    def caption(self, text):
        return self.para(text, align=CENTER, indent=0, space_before=3, space_after=9)

    def page_break(self): self.d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def table(self, header: list[str], rows: list[list], widths=None, caption: str | None = None,
              fills: dict | None = None):
        if caption:
            self.tab += 1
            self.para(f"Таблица {self.tab} – {caption}", align=WD_ALIGN_PARAGRAPH.LEFT, indent=0,
                      keep_next=True, space_before=6, space_after=3)
        t = self.d.add_table(rows=1, cols=len(header))
        t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, h in enumerate(header):
            self._cell(t.rows[0].cells[i], h, bold=True, align=CENTER)
        self._repeat_header(t.rows[0])
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                self._cell(cells[i], str(v), align=CENTER if i else WD_ALIGN_PARAGRAPH.LEFT,
                           red=(str(v) == "Не выполнен"))
        if widths:
            t.autofit = False
            for i, w in enumerate(widths): t.columns[i].width = Cm(w)
            for r in t.rows:
                for i, w in enumerate(widths): r.cells[i].width = Cm(w)
        self.para(indent=0)
        return t

    @staticmethod
    def _cell(cell, text, bold=False, align=None, red=False):
        cell.text = ""
        par = cell.paragraphs[0]
        par.paragraph_format.space_after = Pt(0); par.paragraph_format.first_line_indent = Cm(0)
        if align is not None: par.alignment = align
        r = Report._run(par, text, 12, bold)
        if red: r.font.color.rgb = RGBColor(0xC0, 0, 0)

    @staticmethod
    def _repeat_header(row):
        trPr = row._tr.get_or_add_trPr()
        el = OxmlElement("w:tblHeader"); el.set(qn("w:val"), "true"); trPr.append(el)

    def figure(self, key: str, caption: str, width_cm=12.5):
        """Вставляет картинку из images_dir (файл <key>.png|jpg); иначе — заметная заглушка."""
        self.fig += 1
        img = self._find_image(key)
        if img:
            pp = self.para(indent=0, align=CENTER, keep_next=True, space_before=6)
            pp.add_run().add_picture(str(img), width=Cm(width_cm))
        else:
            self.missing.append(key)
            par = self.para(f"[Рисунок не найден: {key}.png — положите экспорт из Ansys в папку images]",
                            align=CENTER, italic=True, indent=0)
            par.runs[0].font.color.rgb = RGBColor(0xC0, 0, 0)
        self.caption(f"Рисунок {self.fig}. {caption}")

    def _find_image(self, key):
        folder = self.p.root / self.p.raw.get("images_dir", "images")
        mapped = (self.p.raw.get("images") or {}).get(key)   # явное соответствие рисунок -> файл из Ansys
        if mapped and (folder / mapped).exists():
            return folder / mapped
        for ext in (".png", ".jpg", ".jpeg"):
            f = folder / f"{key}{ext}"
            if f.exists(): return f
        return None

    def math(self, text):
        return self.para(text, align=CENTER, italic=True, indent=0, space_before=3, space_after=3)

    # ---------- части отчёта ----------
    def header_footer(self):
        r, t = self.p.report, self.p.tank
        sec = self.d.sections[0]
        tbl = sec.header.tables[0]
        self._set_cell_text(tbl.rows[0].cells[0].paragraphs[0], t["name"])
        self._set_cell_text(tbl.rows[0].cells[2].paragraphs[1], f"№ {r['number']}")
        fp = sec.footer.paragraphs[0]
        runs = [x for x in fp.runs if x.text]
        runs[0].text = str(r["year"]); runs[1].text = ""  # «202»+«6»

    @staticmethod
    def _set_cell_text(par, text):
        runs = [x for x in par.runs if x.text is not None]
        runs[0].text = text
        for x in runs[1:]: x.text = ""

    def title_page(self):
        """Титульный лист как в образце: всё 14 пт, по центру; заголовок полужирный."""
        r, t = self.p.report, self.p.tank
        C = dict(align=CENTER, indent=0, size=14)
        for _ in range(6): self.para(**C)
        self.para(f"ТЕХНИЧЕСКИЙ ОТЧЕТ №{r['number']}", bold=True, **C)
        self.para("по результатам расчета методом конечных элементов", **C)
        self.para(**C)
        self.para(r["title"], bold=True, **C)
        for _ in range(9): self.para(**C)
        tb = self.d.add_table(rows=1, cols=2)
        left, right = tb.rows[0].cells
        left.text = ""; right.text = ""
        self._run(left.paragraphs[0], "Выполнил:", 14)
        lines = [r["executor_position"], f"__________ / {r['executor_name']}/", f"«___» ___________ {r['year']} г."]
        right.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
        self._run(right.paragraphs[0], lines[0], 14)
        for ln in lines[1:]:
            pp = right.add_paragraph(); pp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            self._run(pp, ln, 14)
        # год — в рамке, прижатой к нижнему краю страницы (не зависит от числа строк выше)
        yp = self.para(f"{r['year']} г.", **C)
        fr = OxmlElement("w:framePr")
        for k, v in (("w:w", "9000"), ("w:hSpace", "0"), ("w:wrap", "around"), ("w:vAnchor", "margin"),
                     ("w:hAnchor", "margin"), ("w:xAlign", "center"), ("w:yAlign", "bottom")):
            fr.set(qn(k), v)
        yp._p.get_or_add_pPr().insert(0, fr)
        self.page_break()

    def toc(self):
        self.para("СОДЕРЖАНИЕ", bold=True, align=CENTER, indent=0, size=14, space_after=6)
        par = self.d.add_paragraph()
        run = par.add_run()
        for typ, txt in (("begin", None), (None, 'TOC \\o "1-2" \\h \\z \\u'), ("separate", None)):
            if typ:
                e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), typ); run._r.append(e)
            else:
                e = OxmlElement("w:instrText"); e.set(qn("xml:space"), "preserve"); e.text = txt; run._r.append(e)
        run.add_text("Правый клик → «Обновить поле», чтобы построить оглавление.")
        e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), "end"); run._r.append(e)
        self.page_break()
        # просим Word обновить поля при открытии
        st = self.d.settings.element
        uf = OxmlElement("w:updateFields"); uf.set(qn("w:val"), "true"); st.append(uf)

    def sec1(self):
        r = self.p.report
        self.h1("1 Вводная часть")
        self.para("1.1. Прочностной расчет проведен в соответствии с нормативными документами:", bold=True)
        self.bullets(T.NORMS_SHORT)
        self.para("1.2 Сведения о подрядчике, проводившем прочностной расчет", bold=True)
        self.body(r["contractor"].strip())
        if r.get("contractor_phone"): self.body(f"Тел. {r['contractor_phone']}.")

    def sec2(self):
        t, m, L, c = self.p.tank, self.p.material, self.p.loads, self.c
        n = len(t["belts_thickness"])
        self.h1("2 Информация об объекте моделирования")
        where = f" установлен на объекте: «{t['site']}»" + (f" (№ {t['site_number']})" if t.get("site_number") else "") if t.get("site") else ""
        self.body(f"Резервуар {t['name']}{where}" + (f" и предназначен для {t['purpose']}." if t.get("purpose") else "."))
        self.body("Габариты резервуара:")
        self.bullets([f"диаметр {t['diameter']} мм;", f"высота стенки {t['wall_height']} мм."])
        self.body("Общий вид резервуара показан на рисунке 1.")
        if t.get("fill_level"):
            self.body(f"Расчётный уровень налива продукта – {fmt(t['fill_level']/1000)} м. "
                      f"Плотность хранимого продукта составляет {fmt(t['product_density']/1000)} т/м3.")
        th = t["belts_thickness"]
        self.body("Номинальные толщины стенки по поясам: " + T.thickness_groups(th) + ".")
        self.body("Предельное отклонение от вертикали каждого листа любого пояса стенки ограничивается величиной "
                  "1/200 вертикального расстояния от окрайки днища до контролируемого пояса. Предельные значения "
                  f"для I – {ROMAN[n-1]} поясов: " + " – ".join(fmt(x) for x in c["limits_dev"]) + " мм.")
        self.body("Отклонения стенки от вертикали в каждом поясе замерялись в плоскостях x = "
                  + " – ".join(str(h) for h in c["heights"]) + " мм. "
                  + (f"Толщины поясов приняты по {t['kmd']}" if t.get("kmd") else "Толщины поясов приняты по расчётной модели."))
        self.figure("fig01_general", "Общий вид объекта исследования")
        rows = self.object_rows()
        self.table(["Наименование величин", "Значение"], rows, widths=[11, 5], caption="Характеристика объекта исследования")
        rows = [[f"{ROMAN[i]} пояс", fmt(x), fmt(x)] for i, x in enumerate(th)]
        if t.get("edge_thickness"):
            rows.append(["Окрайка днища", fmt(t["edge_thickness"]), fmt(t["edge_thickness"])])
        rows.append(["Днище резервуара", fmt(t["bottom_thickness"]), fmt(t["bottom_thickness"])])
        self.table(["Обозначение элемента", "Номинальная толщина стенки, мм", "Расчетная толщина стенки, мм"], rows,
                   caption="Толщина элементов")
        # 2.1 материал
        self.para("2.1 Механические характеристики материалов, используемых в расчете", bold=True)
        self.body(f"Материал резервуара – сталь {m['name']}. Характеристики материала согласно {m['standard']} приведены в таблице {self.tab+1}.")
        self.table(["Сталь", "Плотность, кг/м3", "Модуль Юнга, МПа", "Коэффициент Пуассона", "Предел прочности, МПа",
                    "Предел текучести, МПа", "Для толщин стенок, мм"],
                   [[m["name"], m["density"], m["young_modulus_mpa"], fmt(m["poisson"]), m["ultimate_mpa"], m["yield_mpa"], m["thickness_range"]]],
                   caption="Механические характеристики используемых материалов",
                   widths=[1.6, 2.3, 2.6, 2.7, 2.6, 2.6, 2.4])
        sy = m["yield_mpa"]
        self.body("Согласно ГОСТ 31385-2023 и СП 16.13330.2020 расчетные сопротивления:")
        self.math(f"1-й пояс: R = {sy}·0,7·1,0 / (1,05·1,05) = {fmt(c['R1'],2)} МПа")
        self.math(f"2-{len(th)}-й пояса: R = {sy}·0,8·1,0 / (1,05·1,05) = {fmt(c['R2'],2)} МПа")
        self.math(f"Уторный узел (с учетом пластических деформаций): R = {sy}·1,2·1,0 / (1,05·1,05) = {fmt(c['Rutor'],2)} МПа")
        self.body(f"Напряжения в первом поясе не должны превышать {c['R1']:.0f} МПа, со второго по {len(th)}-й пояс – "
                  f"{c['R2']:.0f} МПа. При субмоделировании уторного шва напряжения не должны превышать {c['Rutor']:.0f} МПа.")
        self.body(f"В модели материала стенки и окрайки днища использовалась упругопластическая модель с билинейной диаграммой "
                  f"деформирования: предел текучести σу = {sy} МПа, модуль упругости второго участка")
        self.math(f"E2 = (σвр − σу) / (Δ/100 − σу/E) = {fmt(c['E2'],1)} МПа")
        self.bullets([f"σвр = {m['ultimate_mpa']} МПа – временное сопротивление стали {m['name']};",
                      f"σу = {sy} МПа – предел текучести;", f"Δ = {m['elongation_pct']} – относительное удлинение, %;",
                      f"Е = {m['young_modulus_mpa']} МПа – модуль упругости."])
        self.para("2.2 Необходимый состав расчета", bold=True)
        for line in T.COMPOSITION: self.body(line)

    def sec3_4(self):
        me, t, L, c = self.p.raw["mesh"], self.p.tank, self.p.loads, self.c
        self.h1("3 Сетка конструкции")
        self.body(f"Количество узлов сетки после ее разбиения: {me['nodes']} шт., количество конечных элементов: {me['elements']} шт. "
                  f"Размер конечных элементов {fmt(me['element_size_mm'], 0)} мм, тип элемента {me['element_type']}.")
        self.figure("fig02_mesh_wall_bottom", "Сетка элементов стенки и днища")
        self.figure("fig03_mesh_wall_roof", "Сетка элементов стенки и кровли")
        self.h1("4 Граничные условия и нагрузки")
        self.body("На конструкцию действует:")
        la = self.p.raw.get("loads_ansys")
        if la:
            self.bullets(self.describe_loads(la))
        else:
            self.bullets(self.legacy_load_bullets())
        self.body("Допущения, принятые в модели:")
        self.bullets(T.ASSUMPTIONS)
        self.figure("fig04_loads", "Нагрузки")
        self.figure("fig05_hydrostatic", "Гидростатическое давление")

    # ---------- нагрузки и свойства объекта ----------
    AXIS = {"X": "оси X (вертикаль)", "Y": "оси Y", "Z": "оси Z"}
    DIRS = {"NegativeXAxis": "по оси −X, вертикально вниз", "PositiveXAxis": "по оси +X",
            "NegativeYAxis": "по оси −Y", "PositiveYAxis": "по оси +Y",
            "NegativeZAxis": "по оси −Z", "PositiveZAxis": "по оси +Z"}

    def describe_loads(self, la: dict) -> list[str]:
        """Список нагрузок из проекта Ansys: имя, тип, значение, направление."""
        labels, out = la.get("labels", {}), []
        for x in la["items"]:
            nm, t = x["name"], x["type"]
            lab = f" ({labels[nm]})" if nm in labels else ""
            if t == "EarthGravity":
                out.append(f"вес конструкций: ускорение свободного падения {fmt(x['g'], 5)} м/с2 ({self.DIRS.get(x['direction'], x['direction'])});")
            elif t == "HydrostaticPressure" and not x["suppressed"]:
                out.append(f"гидростатическое давление продукта плотностью {fmt(x['density'], 0)} кг/м3, уровень налива {fmt(x['level_m'])} м "
                           f"(ускорение {fmt(x['accel'], 1)} м/с2);")
            elif t == "HydrostaticPressure":
                out.append("гидростатическое давление в данном расчёте не учитывается;")
            elif t == "Force":
                out.append(f"«{nm}»{lab}: сила {fmt(abs(x['value']), 1)} Н, направление вдоль {self.AXIS[x['axis']]};")
            elif t == "LinePressure":
                out.append(f"«{nm}»{lab}: линейная нагрузка {fmt(abs(x['value']), 0)} Н/м по кромке стенки;")
            elif t == "Pressure":
                out.append(f"«{nm}»{lab}: давление {fmt(abs(x['value']), 0)} Па" + (" (в данном расчёте не учитывается);" if x["suppressed"] else ";"))
            elif t == "FixedSupport":
                out.append(f"закрепление модели: «{nm}»;")
        return out

    def object_rows(self) -> list[list]:
        t, L = self.p.tank, self.p.loads
        la = self.p.raw.get("loads_ansys")
        rows = [["Высота стенки резервуара, мм", t["wall_height"]], ["Радиус стенки резервуара, мм", fmt(t["diameter"] / 2, 0)]]
        if t.get("roof_radius"): rows.append(["Радиус сферической крыши, мм", t["roof_radius"]])
        if t.get("product"): rows.append(["Наименование хранимого продукта", t["product"]])
        if t.get("product_density"): rows.append(["Плотность продукта, кг/м3", fmt(t["product_density"], 0)])
        if t.get("fill_level"): rows.append(["Расчетный уровень налива продукта, мм", t["fill_level"]])
        if la:
            labels = la.get("labels", {})
            for x in la["items"]:
                if x["type"] == "Force":
                    rows.append([f"{x['name']}" + (f" – {labels[x['name']]}" if x['name'] in labels else "") + ", Н", fmt(abs(x["value"]), 1)])
                elif x["type"] == "LinePressure":
                    rows.append([f"{x['name']}" + (f" – {labels[x['name']]}" if x['name'] in labels else "") + ", Н/м", fmt(abs(x["value"]), 0)])
                elif x["type"] == "Pressure":
                    rows.append([f"{x['name']}" + (f" – {labels[x['name']]}" if x['name'] in labels else "") + ", Па", fmt(abs(x["value"]), 0)])
        elif L:
            rows += [["Нормативное внутреннее избыточное давление, кПа", fmt(L["overpressure_kpa"], 0)],
                     ["Коэффициент надежности по нагрузке", fmt(L["load_factor"])],
                     ["Собственный фактический вес крыши, оборудования и ограждений, кг", fmt(L["roof_mass_kg"] + sum(L["equipment_masses_kg"]), 1)],
                     ["Коэффициент надежности по нагрузке (крыша)", fmt(L["roof_load_factor"], 2)],
                     ["Нагрузка от веса теплоизоляции крыши, кг", L["roof_insulation_kg"]],
                     ["Нагрузка от веса теплоизоляции стенки, кг", L["wall_insulation_kg"]],
                     ["Нормативный вес от снегового покрова, кПа", fmt(L["snow_kpa"])],
                     ["Коэффициент надежности по снеговой нагрузке", fmt(L["snow_factor"])],
                     ["Учет сдувания снега с крыши", L["snow_blowoff"]], ["Тип местности", L["terrain"]],
                     ["Расчетное ветровое давление, кПа", fmt(L["wind_kpa"])]]
        for lab, val in (t.get("extra_rows") or []):
            rows.append([lab, val])
        if t.get("hazard_class"): rows.append(["Класс опасности резервуара по ГОСТ 31385", t["hazard_class"]])
        return rows

    def legacy_load_bullets(self) -> list[str]:
        t, L, c = self.p.tank, self.p.loads, self.c
        return [
            f"гидростатическое давление продукта плотностью {t['product_density']} кг/м3, высота налива {fmt(t['fill_level']/1000)} м;",
            "вес металлоконструкций стенки, задан приложением ускорения свободного падения;",
            f"расчетная снеговая нагрузка {fmt(L['snow_kpa'])} кПа, приложенная к верхней грани стенки: Fсн = {L['snow_linear_n_per_m']} Н/м;",
            f"нагрузка от веса крыши, оборудования и площадок: F = γf·(Mкр + ψ·Моб)·g = {fmt(L['roof_load_factor'],2)}·({L['roof_mass_kg']}+{fmt(L['combination_factor'],2)}·({' + '.join(str(x) for x in L['equipment_masses_kg'])}))·9,81 = {fmt(c['roof_force'],1)} Н;",
            f"расчетное избыточное давление Ри = {fmt(L['overpressure_factor'])}·{fmt(L['overpressure_kpa'],0)} = {fmt(L['overpressure_factor']*L['overpressure_kpa']*1000,0)} Па;",
            f"вес тепловой изоляции стенки, Fизол ст = {fmt(c['wall_ins_n'],0)} Н; вес тепловой изоляции крыши, Fизол кр = {fmt(c['roof_ins_n'],0)} Н;",
            "закрепление модели – по днищу, ограничение по всем осям."]

    def strength_table(self, caption, key, crit_name, limit, ok_key, limit_label, belts=None):
        rows = [[b["belt"], f"{b['belt']} пояс", fmt(b[key]), fmt(limit), "Выполнен" if b[ok_key] else "Не выполнен"]
                for b in (belts or self.c["belts"])]
        self.table(["№ п/п", "Конструктивный элемент резервуара", f"{crit_name}, МПа (максимум)", limit_label,
                    "Оценка выполнения критерия прочности"], rows, caption=caption, widths=[1.3, 4.4, 3.8, 3.8, 3.9])

    def sec5_6(self):
        c, t = self.c, self.p.tank
        self.h1("5 Результаты расчета на прочность")
        self.h1(f"5.1 Результаты расчета НДС РВС при наливе {fmt(t['fill_level']/1000)} м с отклонениями стенки для заполненного резервуара")
        self.body(f"Обеспечение прочности поясов основной стенки резервуара {t['name']} в соответствии с ГОСТ 58622-2019 оценивается по критериям:")
        self.bullets(["срединные (мембранные) напряжения в кольцевом направлении σm ≤ [σ], где [σ] = σ0,2 / 1,5 – номинальное допускаемое напряжение;",
                      "поверхностные (фибровые) напряжения в кольцевом направлении σф ≤ 3[σ];",
                      "эквивалентные по Мизесу поверхностные напряжения σe ≤ 3[σ]."])
        self.body(f"Допускаемые напряжения: [σ] = {self.p.material['yield_mpa']}/1,5 = {fmt(c['allow'])} МПа; 3[σ] = {fmt(c['allow3'],0)} МПа.")
        self.figure("fig06_eq_stress", "Эквивалентные поверхностные напряжения в стенке")
        self.figure("fig07_membrane", "Срединные (мембранные) напряжения в кольцевом направлении")
        self.figure("fig08_fiber", "Поверхностные (фибровые) напряжения в кольцевом направлении")
        self.figure("fig09_deform", "Деформации стенки")
        self.strength_table("Первые главные поверхностные (фибровые) напряжения", "fiber", "Максимальное расчетное значение",
                            c["allow3"], "ok_fiber", "Допустимое значение напряжений, 3[σ], МПа")
        self.strength_table("Эквивалентные по Мизесу поверхностные напряжения", "equivalent", "Максимальное расчетное значение",
                            c["allow3"], "ok_eq", "Допустимое значение напряжений, 3[σ], МПа")
        self.strength_table("Первые главные срединные (мембранные) напряжения", "membrane", "Максимальное расчетное значение",
                            c["allow"], "ok_mem", "Допустимое значение напряжений, [σ], МПа")
        self.h1(f"5.2 Результаты расчета НДС РВС при наливе {fmt(t['fill_level']/1000)} м с отклонениями стенки для пустого резервуара")
        self.figure("fig10_empty_eq", "Эквивалентные напряжения в стенке")
        self.figure("fig11_empty_mem", "Мембранные (срединные) напряжения в стенке")
        self.figure("fig12_empty_fiber", "Фибровые (поверхностные) напряжения в стенке")
        self.figure("fig13_empty_deform", "Деформации стенки")
        be = c["belts_empty"]
        if be:
            for cap, key, lim, ok, lab in (
                    ("Первые главные поверхностные (фибровые) напряжения, пустой резервуар", "fiber", c["allow3"], "ok_fiber", "Допустимое значение напряжений, 3[σ], МПа"),
                    ("Эквивалентные по Мизесу поверхностные напряжения, пустой резервуар", "equivalent", c["allow3"], "ok_eq", "Допустимое значение напряжений, 3[σ], МПа"),
                    ("Первые главные срединные (мембранные) напряжения, пустой резервуар", "membrane", c["allow"], "ok_mem", "Допустимое значение напряжений, [σ], МПа")):
                self.strength_table(cap, key, "Максимальное расчетное значение", lim, ok, lab, belts=be)
        self.h1("6 Результаты расчета РВС на устойчивость")
        self.h1("6.1 Результаты расчета РВС на устойчивость искривленного резервуара без гидростатического давления и с ветровой нагрузкой")
        for i, s in enumerate(self.c["stability"], 1):
            self.figure(f"fig_stab{i}", f"Коэффициент запаса устойчивости Fкр/F = k = {fmt(s['k']) if s['k'] > 0 else 'нет данных'}, {s['case'][0].lower() + s['case'][1:]}")
        rows = [[s["case"], fmt(s["k"]) if s["k"] > 0 else "нет данных",
                 "Не определена" if s["k"] <= 0 else ("Выполнен" if s["k"] >= self.p.raw["results"]["required_k"] else "Не выполнен")]
                for s in self.c["stability"]]
        self.table(["Расчетный случай", "Коэффициент запаса k", "Оценка"], rows, caption="Коэффициенты запаса устойчивости")

    def sec8(self):
        c, t, res = self.c, self.p.tank, self.p.raw["results"]
        self.h1("7 Выводы и рекомендации")
        s_ok = "прочность стенки обеспечена" if c["strength_ok"] else "прочность стенки НЕ обеспечена: критерии выполнены не по всем поясам"
        i = res.get("ideal")
        items = [
            f"Расчеты прочности стенки {t['name']} при наливе продукта плотностью {t['product_density']} кг/м3 до расчетной высоты {fmt(t['fill_level']/1000)} м "
            f"с учетом фактической формы стенки показали, что {s_ok}.",
            (f"Максимальные эквивалентные напряжения в стенке идеального РВС составили {i['equivalent']} МПа, мембранные – {i['membrane']} МПа, фибровые (меридиональные) – {i['fiber']} МПа." if i else None),
            f"Максимальные эквивалентные напряжения в стенке РВС с отклонениями от идеальной формы составили {fmt(c['max_eq'])} МПа, "
            f"мембранные – {fmt(c['max_mem'])} МПа, фибровые – {fmt(c['max_fiber'])} МПа (допускаемые: {fmt(c['allow'])} МПа для мембранных, {fmt(c['allow3'],0)} МПа для фибровых и эквивалентных).",
            (f"Минимальный запас устойчивости стенки составил k = {fmt(c['kmin'])} (требуется не менее {fmt(res['required_k'])}) – запас устойчивости " + ("достаточный." if c["stability_ok"] else "НЕДОСТАТОЧНЫЙ.")
             + (f" Коэффициент не получен для случаев: {', '.join(c['stability_missing'])}." if c["stability_missing"] else ""))
            if c["kmin"] is not None else "Коэффициент запаса устойчивости из проекта Ansys не получен (нет результатов расчёта на устойчивость).",
            f"Допустимый уровень налива продукта по условию прочности составил {fmt(res['max_fill_m'])} м." if c["strength_ok"] else
            "Для продолжения эксплуатации требуется снижение уровня налива или вывод резервуара в ремонт; допустимый уровень налива следует определить повторным расчетом."]
        for k, x in enumerate([x for x in items if x], 1): self.body(f"{k}. {x}")

    def appendices(self):
        self.h1("Приложение 1 – Перечень использованной нормативной технической и методической документации", new_page=True)
        for k, x in enumerate(T.NORMS_FULL, 1): self.body(f"{k}. {x}")
        self.h1("Приложение 2 – Перечень используемых терминов и определений")
        for term, dfn in T.TERMS:
            self.para(term, bold=True); self.body(dfn)
        self.h1("Приложение 3 – Исходные данные на выполнение прочностного расчета РВС", new_page=True)
        tag, n = self.p.tank["tag"], self.p.raw["survey"]["points_per_belt"]
        nb = len(self.p.tank["belts_thickness"])
        for title, dev in (("Отклонения стенки от вертикали полного резервуара, мм", self.p.survey_full),
                           ("Отклонения стенки от вертикали резервуара после опорожнения, мм", self.p.survey_empty)):
            hdr = ["Точка"] + [f"{ROMAN[b]}" for b in range(nb)]
            rows = [[i + 1] + [int(dev[b][i]) if float(dev[b][i]).is_integer() else fmt(dev[b][i]) for b in range(nb)] for i in range(n)]
            self.table(hdr, rows, caption=title)
        self.body("Требования к моделированию:")
        for line in T.REQUIREMENTS: self.body(line)

    def build(self, out: Path) -> Path:
        self.header_footer(); self.title_page(); self.toc()
        self.sec1(); self.sec2(); self.sec3_4(); self.sec5_6(); self.sec8(); self.appendices()
        out.parent.mkdir(parents=True, exist_ok=True)
        self.d.save(out)
        return out


def build_report(p: Project, out: Path) -> tuple[Path, list[str]]:
    rep = Report(p)
    path = rep.build(out)
    return path, rep.missing
