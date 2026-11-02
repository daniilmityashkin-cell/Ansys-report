# -*- coding: utf-8 -*-
# Рисунки отчёта как в эталоне (docs/REPORT_PARITY.md, tools/diag/etalon_T001_wb.md): figures/<ключ рисунка в отчёте>.png в папке выгрузки
# (ANSYS_REPORT_OUT). 1 - общий вид (полупрозрачная геометрия, пояса линиями, вид сверху-сбоку); 2, 3 - сетка в разрезе, пояса разными цветами
# (днище и стенка; стенка и кровля); 4 - нагрузки; 5 - гидростатическое давление; 6-9 - налив (σэ, σм, σф, перемещения), 10-13 - пустой;
# fig_stab1..4 - формы потери устойчивости (ветер Y, Z; моды 1, 2). Результаты 6-13 и формы - только стенка с днищем (крыша скрыта),
# изометрия (1, 1, 1) с вертикалью вверх, как сохранённая камера эталонного проекта.
# Нагрузки расчёта заданы APDL-фрагментом (Mechanical их не рисует): для рисунков 4-5 в сеансе добавляются видимые объекты
# с теми же величинами из loads_data.py. Запускается после выгрузки результатов; проект не сохраняется.
import os, io, math
import System

out = os.path.join(os.environ.get("ANSYS_REPORT_OUT") or os.path.join(os.environ["TEMP"], "ansys_report_out"), "figures")
System.IO.Directory.CreateDirectory(out)
log = []
AXIS = (os.environ.get("ANSYS_REPORT_AXIS") or "Z").upper()
model = ExtAPI.DataModel.Project.Model


def _rd(path, enc="utf-8"):
    fh_ = io.open(path, encoding=enc)
    try:
        return fh_.read()
    finally:
        fh_.close()


def tmark(label):
    """Метка времени этапа (ansys_report/timing.py)."""
    try:
        import time
        f_ = io.open(os.environ.get("AR_TIMING") or r"C:\ansys_report_work\timing.log", "a", encoding="utf-8")
        f_.write(u"%.3f\t%s\t%s\n" % (time.time(), os.environ.get("AR_TIMING_TAG", ""), label))
        f_.close()
    except Exception:
        pass


def V(x, y, z):
    """Вектор в осях модели: z - вертикаль резервуара."""
    from Ansys.ACT.Math import Vector3D
    if AXIS == "X":
        return Vector3D(z, x, y)
    if AXIS == "Y":
        return Vector3D(y, z, x)
    return Vector3D(x, y, z)


def camera(view, focus=None, height_mm=None):
    """view - направление от объекта к камере (x, y, z); focus - точка (мм) и высота сцены (мм) для приближения."""
    cam = Graphics.Camera
    cam.UpVector = V(0, 0, 1)
    cam.ViewVector = V(view[0], view[1], view[2])
    cam.UpVector = V(0, 0, 1)             # после смены направления взгляда «верх» мог повернуться: вертикаль резервуара вверх
    cam.SetFit()
    if focus is not None:
        p = {"X": (focus[2], focus[0], focus[1]), "Y": (focus[1], focus[2], focus[0])}.get(AXIS, focus)
        cam.FocalPoint = Point([p[0], p[1], p[2]], "mm")
        if height_mm:
            cam.SceneHeight = Quantity(height_mm, "mm")


def export(name, w=2000, h=1100, current=False):
    """current=True - снимок текущего окна графики (с линиями Draw3D: каркас крыши); иначе - отдельная отрисовка."""
    if current:                           # своё разрешение задаётся только при отдельной отрисовке
        Graphics.ExportImage(os.path.join(out, name + ".png"))
        log.append(u"ok: %s (текущее окно)" % name)
        return
    st = Ansys.Mechanical.Graphics.GraphicsImageExportSettings()
    st.CurrentGraphicsDisplay = False
    st.Resolution = GraphicsResolutionType.EnhancedResolution
    st.Width = w
    st.Height = h
    try:                                  # белый фон, как в эталоне
        st.Background = GraphicsBackgroundType.White
    except Exception:
        pass
    Graphics.ExportImage(os.path.join(out, name + ".png"), GraphicsImageExportFormat.PNG, st)
    log.append(u"ok: " + name)


def flush_log():
    f_ = io.open(os.path.join(out, "log_figures.txt"), "w", encoding="utf-8")
    f_.write(u"\n".join(log))
    f_.close()


def step(name, fn):
    tmark(u"Рисунок: %s" % name)
    log.append(u"-- %s" % name)
    flush_log()                            # журнал после каждого шага: при падении Mechanical видно, на чём
    try:
        fn()
    except Exception as e:
        import traceback
        log.append(u"ОШИБКА %s: %s | %s" % (name, e, traceback.format_exc().replace("\n", " ")[-400:]))
    flush_log()


bodies = model.Geometry.GetChildren(DataModelObjectCategory.Body, True)
H = 0.0
try:
    ns_ = {}
    exec(_rd(os.environ["ANSYS_REPORT_LOADS"]), ns_)
    LOADS = ns_["LOADS"]
    H = float(LOADS["geometry"]["wall_height_mm"])
    R = float(LOADS["geometry"]["diameter_mm"]) / 2.0
except Exception as e:
    LOADS, R = None, 0.0
    log.append(u"loads_data.py: %s" % e)


def nsel(name):
    for n in model.NamedSelections.Children:
        if n.Name == name:
            return n
    return None


def wall_faces():
    """Грани стенки снизу вверх (центр между 0 и H)."""
    ax = {"X": 0, "Y": 1, "Z": 2}[AXIS]
    fl = []
    for b in bodies:
        for f in b.GetGeoBody().Faces:
            fl.append((f.Centroid[ax], f.Id))
    k = 1000.0 if H and max([abs(z) for z, i in fl]) < 0.05 * H else 1.0
    return [i for z, i in sorted(fl) if 0.002 * H < z * k < 0.998 * H]


def view_reset():
    Graphics.SectionPlanes.Clear()
    Graphics.ViewOptions.ShowLegend = True
    Graphics.ViewOptions.ShowTriad = True


def frame_polylines():
    """Каркас крыши из beams.json пакета (радиальные балки, кольца) по поверхности крыши: высота - средняя z узлов сетки крыши по радиусу."""
    import json
    pkg = os.environ.get("AR_PKG") or os.path.dirname(os.environ.get("ANSYS_REPORT_LOADS") or "")
    bp_path = os.path.join(pkg, "beams.json")
    if not os.path.exists(bp_path):
        return []
    bp = json.loads(_rd(bp_path))
    md = ExtAPI.DataModel.MeshDataByName("Global")
    bins = {}
    for nd in md.Nodes:
        if nd.Z > H - 1.0:
            k = int(math.sqrt(nd.X ** 2 + nd.Y ** 2) // 250)
            bins.setdefault(k, []).append(nd.Z)
    zr = dict([(k, sum(v) / len(v)) for k, v in bins.items()])

    def z_at(r):
        k = int(r // 250)
        while k not in zr and k > 0:
            k -= 1
        return zr.get(k, H) + 120.0                     # чуть над настилом, чтобы линии не тонули в оболочке
    rc = float(bp.get("central_radius_mm") or 0.0)
    rings = ([rc] if bp.get("central") else []) + [rc + (R - rc) * j / (len(bp.get("rings") or []) + 1.0) for j in range(1, len(bp.get("rings") or []) + 1)]
    lines = []
    n = int(bp.get("radial_count") or 0)
    for k in range(n):
        a = math.radians(float(bp.get("first_angle_deg") or 0.0) + 360.0 * k / n)
        lines.append([(r * math.cos(a), r * math.sin(a), z_at(r)) for r in [rc + (R - rc) * i / 20.0 for i in range(21)]])
    for r in rings + [R]:
        lines.append([(r * math.cos(2 * math.pi * i / 96), r * math.sin(2 * math.pi * i / 96), z_at(min(r, R - 1))) for i in range(97)])
    return lines


def pix(p):
    """Результат WorldToPixel -> [x, y] (объект с X/Y или последовательность)."""
    try:
        return [float(p.X), float(p.Y)]
    except Exception:
        q = list(p)
        return [float(q[0]), float(q[1])]


# --- разрезы: вертикальная плоскость через ось (рис. 2, 3) и горизонтальная над кромкой стенки (крыша скрыта, рис. 4-17)
CUT_SIGN = float(os.environ.get("AR_CUT_SIGN") or 1.0)        # Mechanical оставляет сторону, куда направлена нормаль плоскости (проверено на рисунках)


def add_plane(center, direction, name):
    sp = Ansys.Mechanical.Graphics.SectionPlane()
    sp.Center = Point(list(center), "mm")
    sp.Direction = direction
    sp.Name = name
    Graphics.SectionPlanes.Add(sp)
    sp.Active = True
    return sp


def cut_roof():
    """Открытый верх: срез чуть выше кромки стенки (крыша - грань того же тела, скрыть её иначе нельзя)."""
    Graphics.SectionPlanes.Clear()
    c = {"X": (H + 5.0, 0.0, 0.0), "Y": (0.0, H + 5.0, 0.0)}.get(AXIS, (0.0, 0.0, H + 5.0))
    add_plane(c, V(0, 0, -CUT_SIGN), u"AR без крыши")           # остаётся сторона, куда смотрит нормаль: вниз


def section_half():
    """Разрез по вертикальной плоскости через ось: половина резервуара (x < 0) срезана."""
    add_plane((0.0, 0.0, 0.0), V(CUT_SIGN, 0, 0), u"AR разрез")
    log.append(u"разрез: плоскостей %d" % Graphics.SectionPlanes.Count)


def window_frame(name, lines, crop=None):
    """Каркас крыши линиями Draw3D в окне + пиксели линий (name_frame.json) для переноса на снимок высокого разрешения
    (ansys_connect.overlay_roof_frame): Mechanical рисует Draw3D только в окне, а снимок высокого разрешения - без них."""
    import json
    ctx = None
    if lines:
        try:
            ctx = Graphics.CreateAndOpenDraw3DContext()
            ctx.Color = 0x2E5E2E
            ctx.LineWeight = 3
            for pl in lines:
                flat = []
                for (x, y, z) in pl:
                    flat += [x, y, z]
                ctx.DrawPolyline(flat)
            ctx.Close()
        except Exception as e:
            log.append(u"Draw3D: %s" % e)
    export(name + "_window", current=True)
    try:
        pts = [[pix(Graphics.WorldToPixel([x, y, z])) for (x, y, z) in pl] for pl in lines]
        data = {"polylines": pts}
        if crop:                           # приближение к узлу: снимок высокого разрешения вписывает всю модель, поэтому кадр вырезается в Python
            data["crop_frac"] = list(crop)  # центр кадра (доли ширины и высоты снимка) и размер кадра (доля)
        fj = io.open(os.path.join(out, name + "_frame.json"), "w", encoding="utf-8")
        fj.write(unicode(json.dumps(data)))
        fj.close()
    except Exception as e:
        log.append(u"WorldToPixel: %s" % e)
    return ctx


def drop_context(ctx):
    if ctx is None:
        return
    try:
        Graphics.RemoveContext(ctx)
    except Exception:
        ctx.Visible = False


def half_lines(lines):
    """Части линий каркаса в оставленной разрезом половине (x >= 0)."""
    res = []
    for pl in lines:
        cur = []
        for p_ in pl:
            if p_[0] * CUT_SIGN >= 0.0:
                cur.append(p_)
            else:
                if len(cur) >= 2:
                    res.append(cur)
                cur = []
        if len(cur) >= 2:
            res.append(cur)
    return res


# --- рис. 1: общий вид - полупрозрачная зелёная геометрия, пояса и края граней линиями, каркас крыши, вид сверху-сбоку;
# поля обрезаются по резервуару (ansys_connect.overlay_roof_frame)
def fig01():
    view_reset()
    Graphics.ViewOptions.ShowMesh = False
    model.Geometry.DisplayStyle = type(model.Geometry.DisplayStyle).BodyColor
    for b in bodies:
        b.Color = 0x8FBF8F            # светло-зелёный (BGR/RGB одинаково для серо-зелёного)
        b.Transparency = 0.45
    Graphics.ViewOptions.ShowLegend = False
    Graphics.ViewOptions.ShowRuler = False
    Graphics.ViewOptions.ShowTriad = False
    model.Geometry.Activate()
    camera((-1.0, -0.75, 0.75))
    ctx = window_frame("fig01_general", frame_polylines())
    export("fig01_general", w=2514, h=1584)
    drop_context(ctx)
    Graphics.ViewOptions.ShowRuler = True
    Graphics.ViewOptions.ShowTriad = True
    for b in bodies:
        b.Transparency = 0.0


def full_analysis():
    an = [a for a in model.Analyses if a.Name == (os.environ.get("ANSYS_REPORT_FULL") or u"AR: Эксплуатация")]
    return an[0] if an else [a for a in model.Analyses if a.Name.startswith(u"AR:")][0]


belt_res = []


def undeformed():
    """Результат на недеформированной форме (иначе автомасштаб искажает рисунок сетки)."""
    rp = Graphics.ViewOptions.ResultPreference
    cur = rp.DeformationScaling
    names = [n for n in dir(type(cur)) if n[:1].isupper() and not n.startswith(("To", "Get", "Is", "Compare", "Equals", "Format", "HasFlag", "Parse", "Try", "Memberwise", "Reference"))]
    for nm in ("Undeformed", "TrueScale", "True"):
        if nm in names:
            rp.DeformationScaling = getattr(type(cur), nm)
            return
    log.append(u"масштаб деформаций: нет подходящего (%s)" % names)


# цвета как у тел эталона (рис. 2, 3): днище серое, пояса снизу вверх, крыша голубая
BELT_RGB = [(150, 160, 175), (125, 160, 120), (200, 155, 115), (165, 200, 190), (220, 210, 125), (185, 185, 205),
            (175, 175, 135), (145, 145, 145), (115, 135, 165), (105, 135, 95), (170, 170, 105), (145, 165, 185)]
BOTTOM_RGB, ROOF_RGB = (205, 205, 205), (185, 210, 235)


def band_color(lg, i, rgb):
    """Цвет полосы легенды: в разных версиях Mechanical принимает целое 0xBBGGRR / 0xRRGGBB или System.Drawing.Color."""
    r_, g_, b_ = rgb
    errs = []
    for c in (r_ + (g_ << 8) + (b_ << 16), ):
        try:
            lg.SetBandColor(i, c)
            return True
        except Exception as e:
            errs.append(u"%s" % e)
    try:
        import clr
        clr.AddReference("System.Drawing")
        from System.Drawing import Color as DColor
        lg.SetBandColor(i, DColor.FromArgb(255, r_, g_, b_))
        return True
    except Exception as e:
        errs.append(u"%s" % e)
    if i == 0:
        log.append(u"цвет полосы: %s" % u" | ".join(errs))
    return False


def show_elements():
    """Рёбра элементов поверх заливки результата (сетка на рис. 2, 3)."""
    rp = Graphics.ViewOptions.ResultPreference
    cur = rp.ExtraModelDisplay
    names = [n for n in dir(type(cur)) if n[:1].isupper()]
    for nm in ("ShowElements", "ShowElementOutlines", "UndeformedModel"):
        if nm in names:
            rp.GetType().GetProperty("ExtraModelDisplay").SetValue(rp, getattr(type(cur), nm), None)
            log.append(u"рёбра элементов: %s" % nm)
            return
    log.append(u"рёбра элементов: нет подходящего (%s)" % names)


def belt_colors():
    """Пояса разными цветами: результат «высота узла» (LOC по вертикали), полосы легенды = днище, пояса, крыша, цвета - как тела эталона.
    Стенка - одно тело с гранями-поясами, а Mechanical красит по телу; объекты Thickness на окраску не влияют."""
    sol = full_analysis().Solution
    r = sol.AddUserDefinedResult()
    r.Expression = "LOC" + AXIS
    r.Name = u"Сетка"
    r.EvaluateAllResults()
    belt_res.append(r)
    r.Activate()
    undeformed()
    rp = Graphics.ViewOptions.ResultPreference
    rp.ShowMaximum = False
    rp.ShowMinimum = False
    n = max(len(wall_faces()), 3)
    try:
        lg = Ansys.Mechanical.Graphics.Tools.CurrentLegendSettings()
        lg.NumberOfBands = n + 2
        bounds = [1.0] + [H * k / float(n) for k in range(1, n)] + [H + 1.0]
        for i, ub in enumerate(bounds):
            lg.SetUpperBound(i, Quantity(ub, "mm"))
        ok = band_color(lg, 0, BOTTOM_RGB)
        for k in range(n):
            ok = band_color(lg, k + 1, BELT_RGB[k % len(BELT_RGB)]) and ok
        ok = band_color(lg, n + 1, ROOF_RGB) and ok
        log.append(u"легенда: полос %d, цвета %s" % (n + 2, u"заданы" if ok else u"НЕ заданы"))
    except Exception as e:
        log.append(u"легенда: %s" % e)
    show_elements()
    return r


def hide_legend():
    """Без легенды и заголовка результата (рис. 2, 3 - сетка, как в эталоне)."""
    Graphics.ViewOptions.ShowLegend = False
    try:
        lg = Ansys.Mechanical.Graphics.Tools.CurrentLegendSettings()
        done = []
        for nm in ("Visible", "IsVisible", "ShowLegend", "Show"):
            if hasattr(lg, nm):
                try:
                    setattr(lg, nm, False)
                    done.append(nm)
                except Exception:
                    pass
        log.append(u"легенда скрыта: ShowLegend=%s, %s; свойства легенды: %s" % (Graphics.ViewOptions.ShowLegend, done,
                   u", ".join([n for n in dir(lg) if n[:1].isupper()])))
    except Exception as e:
        log.append(u"легенда: %s" % e)


def mesh_view(r):
    r.Activate()
    show_elements()
    Graphics.ViewOptions.ShowMesh = True
    hide_legend()


# --- рис. 2: сетка в разрезе у узла стенка-днище, днище изнутри (пояса своими цветами)
def fig02():
    view_reset()
    r = belt_colors()
    section_half()
    mesh_view(r)
    camera((-1.0, -0.35, 0.75), focus=(R * 0.35, -R * 0.3, 0.0), height_mm=0.9 * R)
    hide_legend()
    ctx = window_frame("fig02_mesh_wall_bottom", [], crop=(0.48, 0.50, 0.62))      # узел стенка-днище, днище изнутри
    export("fig02_mesh_wall_bottom", w=2514, h=1584)
    drop_context(ctx)


# --- рис. 3: сетка в разрезе у узла стенка-крыша, крыша с каркасом (каркас - BEAM188 из APDL, в Mechanical не виден: дорисовывается линиями)
def fig03():
    mesh_view(belt_res[0])
    camera((-1.0, -0.35, 0.75), focus=(R * 0.35, -R * 0.5, H), height_mm=0.6 * R)
    hide_legend()
    ctx = window_frame("fig03_mesh_wall_roof", half_lines(frame_polylines()), crop=(0.58, 0.45, 0.50))   # узел стенка-крыша
    export("fig03_mesh_wall_roof", w=2514, h=1584)
    drop_context(ctx)
    Graphics.SectionPlanes.Clear()
    Graphics.ViewOptions.ShowMesh = False
    for r in belt_res:
        r.Delete()


# --- рис. 4-5: нагрузки «AR: Эксплуатация» видимыми объектами Mechanical (величины - из loads_data.py)
shown = []


def loads_objects():
    an = full_analysis()
    case = [c for c in LOADS["cases"] if c.get("hydro")][0]
    g = an.AddEarthGravity()
    g.Direction = getattr(GravityOrientationType, "Negative" + AXIS + "Axis")
    shown.append(g)
    hp = an.AddHydrostaticPressure()
    hp.Location = nsel("AR_WALL")
    hp.FluidDensity = Quantity(round(case["hydro"]["gradient_mpa_mm"] * 1e12 / LOADS["gravity_mm_s2"], 1), "kg m^-3")     # ρ = (dp/dz) / g
    try:
        hp.DefineBy = LoadDefineBy.Components
    except Exception:
        pass
    for c in ("X", "Y", "Z"):              # ускорение (сила тяжести вниз) и точка свободной поверхности на оси
        try:
            getattr(hp, c + "Component").Output.DiscreteValues = [Quantity(LOADS["gravity_mm_s2"] if c == AXIS else 0.0, "mm s^-2")]   # «ускорение» вверх = сила тяжести вниз
            setattr(hp, c + "Coordinate", Quantity(case["hydro"]["free_surface_mm"] if c == AXIS else 0.0, "mm"))
        except Exception as e:
            log.append(u"гидростатика %s: %s" % (c, e))
    hp.Name = u"Гидростатическое давление"
    shown.append(hp)
    roof_f = float((LOADS.get("model") or {}).get("roof_force_n") or 0.0)
    if roof_f:                             # схема эталона Т-001: силы на верхнюю кромку стенки (как в apply_loads.py), подписи как на рис. 4 эталона
        g_ = LOADS["gravity_mm_s2"] / 1000.0
        ins_r = sum([m["mass_kg"] for m in LOADS["point_masses"] if m["location"] == "roof" and m.get("category") == "insulation"]) * g_
        ins_w = sum([m["mass_kg"] for m in LOADS["point_masses"] if m["location"].startswith("belt_") and m.get("category") == "insulation"]) * g_
        snow = -case["roof_extra_mpa"] * math.pi * R * R
        edge = top_edge()
        for name, val, loc in ((u"Fкр", roof_f, edge), (u"Fизол ст", ins_w, nsel("AR_WALL")), (u"Fизол кр", ins_r, edge), (u"Fсн", snow, edge)):
            if val <= 0 or loc is None:
                continue
            f_ = an.AddForce()
            f_.Location = loc
            f_.DefineBy = LoadDefineBy.Components
            getattr(f_, AXIS + "Component").Output.DiscreteValues = [Quantity(-val, "N")]
            f_.Name = name
            shown.append(f_)
    elif case.get("roof_extra_mpa"):
        p = an.AddPressure()
        p.Location = nsel("AR_ROOF")
        p.Magnitude.Output.DiscreteValues = [Quantity(-case["roof_extra_mpa"], "MPa")]
        p.Name = u"Крыша: снег, вес"
        shown.append(p)
    return an, hp


def top_edge():
    """Верхняя кромка стенки: рёбра граней стенки у отметки H длиной больше половины окружности."""
    ax = {"X": 0, "Y": 1, "Z": 2}[AXIS]
    ids = []
    for b in bodies:
        for e in b.GetGeoBody().Edges:
            c = e.Centroid
            k = 1000.0 if abs(e.Length) < 0.05 * R else 1.0
            if abs(c[ax] * k - H) < 0.002 * H and e.Length * k > math.pi * R:
                ids.append(e.Id)
    if not ids:
        return None
    sel = ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
    sel.Ids = ids
    return sel


def fig04_05():
    """Как рис. 9 эталона: изометрия, открытый верх (крыша срезана плоскостью над кромкой), видны стрелки и подписи нагрузок."""
    view_reset()
    Graphics.ViewOptions.ShowMesh = False
    an, hp = loads_objects()
    an.Activate()
    cut_roof()
    Graphics.Redraw()
    iso_view(keep_cut=True)
    export("fig04_loads")
    hp.Activate()
    cut_roof()                             # после активации объекта нагрузки разрез сбрасывается
    Graphics.ViewOptions.ShowMesh = True
    iso_view(keep_cut=True)
    Graphics.ViewOptions.ShowMesh = True
    export("fig05_hydrostatic")
    Graphics.SectionPlanes.Clear()
    for o in shown:
        o.Delete()


# --- рис. 6-13 и формы потери устойчивости: только стенка с днищем и окрайкой (крыша скрыта), изометрия
def wall_scope():
    ids = []
    for nm in ("AR_WALL", "AR_BOTTOM", "AR_ANNULAR"):
        n = nsel(nm)
        if n is not None:
            ids += list(n.Location.Ids)
    sel = ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
    sel.Ids = ids
    return sel


def iso_view(keep_cut=False):
    if keep_cut:
        Graphics.ViewOptions.ShowLegend = True
        Graphics.ViewOptions.ShowTriad = True
    else:
        view_reset()
        cut_roof()
    Graphics.ViewOptions.ShowMesh = False
    try:
        Graphics.ViewOptions.ShowLogo = False
    except Exception:
        pass
    try:                                   # без каркаса и рёбер элементов поверх заливки (как export_results.prep_results_view)
        rp = Graphics.ViewOptions.ResultPreference
        rp.GetType().GetProperty("ExtraModelDisplay").SetValue(rp, getattr(type(rp.ExtraModelDisplay), "NoWireframe"), None)
    except Exception as e:
        log.append(u"ExtraModelDisplay: %s" % e)
    camera((1.0, 1.0, 1.0))


CAPTIONS = {"eq": u"Эквивалентные напряжения", "mem": u"Срединные (мембранные) напряжения", "fib": u"Поверхностные (фибровые) напряжения",
            "def": u"Перемещения"}


def result_figs(an, items, mode=None):
    """items: [(имя файла, тип результата: eq|mem|fib|def)]. Результаты создаются на время снимка и удаляются."""
    sol = an.Solution
    sc = wall_scope()
    made = []
    for key, kind in items:
        if kind == "eq":
            r = sol.AddEquivalentStress()
        elif kind in ("mem", "fib"):
            r = sol.AddMaximumPrincipalStress()
            if kind == "mem":
                r.Position = type(r.Position).Middle
        else:
            r = sol.AddTotalDeformation()
            if mode:
                r.Mode = mode
        r.Location = sc
        r.Name = CAPTIONS.get(kind, kind)
        made.append((key, r))
    sol.EvaluateAllResults()
    for key, r in made:
        try:
            r.Activate()
            undeformed()
            iso_view()
            export(key)
        except Exception as e:
            log.append(u"ОШИБКА %s: %s" % (key, e))
    for key, r in made:
        try:
            r.Delete()
        except Exception:
            pass


def empty_analysis():
    st = [a for a in model.Analyses if a.Name.startswith(u"AR:") and a.AnalysisType == AnalysisType.Static]
    em = [a for a in st if u"пуст" in a.Name.lower()]
    return em[0] if em else None


def fig06_13():
    result_figs(full_analysis(), [("fig06_eq_stress", "eq"), ("fig07_membrane", "mem"), ("fig08_fiber", "fib"), ("fig09_deform", "def")])
    em = empty_analysis()
    if em is not None:
        result_figs(em, [("fig10_empty_eq", "eq"), ("fig11_empty_mem", "mem"), ("fig12_empty_fiber", "fib"), ("fig13_empty_deform", "def")])


def fig_stab():
    eig = sorted([a for a in model.Analyses if a.Name.startswith(os.environ.get("ANSYS_REPORT_EIGEN") or "Eigenvalue")], key=lambda a: a.Name)
    k = 1
    for a in eig:
        for mode in (1, 2):
            result_figs(a, [("fig_stab%d" % k, "def")], mode=mode)
            k += 1


tmark(u"Рисунки: начало")
WANT = (os.environ.get("AR_FIGS") or "").split(",")
if (os.environ.get("ANSYS_REPORT_IMAGES") or "all").lower() == "none":       # идеальный РВС: рисунки не нужны
    WANT = ["-"]
for nm, fn in (("fig01", fig01), ("fig02", fig02), ("fig03", fig03), ("fig04-05", fig04_05), ("fig06-13", fig06_13), ("fig_stab", fig_stab)):
    if WANT == [""] or nm in WANT:
        step(nm, fn)
flush_log()
