# -*- coding: utf-8 -*-
# Рисунки отчёта как в эталоне (docs/REPORT_PARITY.md): figures/fig01..fig05.png в папке выгрузки (ANSYS_REPORT_OUT).
# 1 - общий вид (полупрозрачная геометрия, пояса линиями, вид сверху-сбоку); 2, 3 - сетка в разрезе, пояса разными цветами
# (днище и стенка; стенка и кровля); 4 - нагрузки; 5 - гидростатическое давление.
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
    Graphics.ExportImage(os.path.join(out, name + ".png"), GraphicsImageExportFormat.PNG, st)
    log.append(u"ok: " + name)


def step(name, fn):
    tmark(u"Рисунок: %s" % name)
    try:
        fn()
    except Exception as e:
        import traceback
        log.append(u"ОШИБКА %s: %s | %s" % (name, e, traceback.format_exc().replace("\n", " ")[-400:]))


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


def draw_frame(color=0x2E5E2E, weight=3):
    lines = frame_polylines()
    if not lines:
        return None
    ctx = Graphics.CreateAndOpenDraw3DContext()
    ctx.Color = color
    ctx.LineWeight = weight
    for pl in lines:
        flat = []
        for (x, y, z) in pl:
            flat += [x, y, z]
        try:
            ctx.DrawPolyline(flat)
        except Exception as e:
            log.append(u"DrawPolyline: %s" % e)
            break
    ctx.Close()
    log.append(u"каркас крыши: линий %d" % len(lines))
    return ctx


# --- рис. 1: общий вид - полупрозрачная зелёная геометрия, пояса и края граней линиями, вид сверху-сбоку
def fig01():
    view_reset()
    Graphics.ViewOptions.ShowMesh = False
    model.Geometry.DisplayStyle = type(model.Geometry.DisplayStyle).BodyColor
    for b in bodies:
        b.Color = 0x8FBF8F            # светло-зелёный (BGR/RGB одинаково для серо-зелёного)
        b.Transparency = 0.45
    Graphics.ViewOptions.ShowLegend = False
    Graphics.ViewOptions.ShowRuler = False
    model.Geometry.Activate()
    camera((-1.0, -0.75, 0.75))
    try:
        frame = draw_frame()
    except Exception as e:
        frame = None
        log.append(u"каркас: %s" % e)
    export("fig01_window", current=True)                  # проверка: окно с каркасом (низкое разрешение)
    try:                                                   # каркас в пиксели окна: наносится на снимок высокого разрешения в Python
        import json
        pts = []
        for pl in frame_polylines():
            row = []
            for (x, y, z) in pl:
                row.append(pix(Graphics.WorldToPixel([x, y, z])))
            pts.append(row)
        log.append(u"WorldToPixel: центр днища -> %s" % pix(Graphics.WorldToPixel([0.0, 0.0, 0.0])))
        fj = io.open(os.path.join(out, "fig01_frame.json"), "w", encoding="utf-8")
        fj.write(unicode(json.dumps({"polylines": pts})))
        fj.close()
    except Exception as e:
        log.append(u"WorldToPixel: %s" % e)
    export("fig01", w=2514, h=1584)
    if frame is not None:
        try:
            Graphics.RemoveContext(frame)
        except Exception:
            frame.Visible = False
    Graphics.ViewOptions.ShowRuler = True
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
            log.append(u"масштаб деформаций: %s (варианты %s)" % (nm, names))
            return
    log.append(u"масштаб деформаций: нет подходящего (%s)" % names)


def belt_colors():
    """Пояса разными цветами: результат «высота узла» (LOCZ) с числом полос = числу поясов от 0 до H - полоса совпадает с поясом
    (пояса одной высоты). Стенка - одно тело с гранями-поясами, а Mechanical красит по телу; объекты Thickness на окраску не влияют."""
    sol = full_analysis().Solution
    r = sol.AddUserDefinedResult()
    r.Expression = "LOC" + AXIS
    r.Name = u"Пояса стенки"
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
        lg.NumberOfBands = n
        for i in range(n):                         # полоса 0 - нижняя
            lg.SetUpperBound(i, Quantity(H * (i + 1) / float(n), "mm"))
        log.append(u"легенда: полос %d" % n)
    except Exception as e:
        log.append(u"легенда: %s" % e)
    return r


def section_half():
    """Разрез по вертикальной плоскости через ось: половина резервуара срезана."""
    sp = Ansys.Mechanical.Graphics.SectionPlane()
    sp.Center = Point([0.0, 0.0, 0.0], "mm")
    sp.Direction = V(1, 0, 0)
    sp.Name = u"AR разрез"
    Graphics.SectionPlanes.Add(sp)
    sp.Active = True
    log.append(u"разрез: плоскостей %d" % Graphics.SectionPlanes.Count)


# --- рис. 2: сетка стенки и днища в разрезе (пояса разными цветами), камера у узла стенка-днище
def fig02():
    view_reset()
    r = belt_colors()
    Graphics.ViewOptions.ShowMesh = True
    Graphics.ViewOptions.ShowLegend = False
    section_half()
    r.Activate()
    Graphics.ViewOptions.ShowLegend = False
    camera((-1.0, -0.35, 0.75), focus=(R * 0.35, -R * 0.3, 0.0), height_mm=0.9 * R)
    export("fig02")


# --- рис. 3: сетка стенки и кровли в разрезе, камера у узла стенка-кровля
def fig03():
    Graphics.ViewOptions.ShowMesh = True
    Graphics.ViewOptions.ShowLegend = False
    belt_res[0].Activate()
    camera((-1.0, -0.35, 0.75), focus=(R * 0.35, -R * 0.5, H), height_mm=0.6 * R)
    export("fig03")
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
    if case.get("roof_extra_mpa"):
        p = an.AddPressure()
        p.Location = nsel("AR_ROOF")
        p.Magnitude.Output.DiscreteValues = [Quantity(-case["roof_extra_mpa"], "MPa")]
        p.Name = u"Крыша: снег, вес"
        shown.append(p)
    return an, hp


def fig04_05():
    view_reset()
    Graphics.ViewOptions.ShowMesh = False
    an, hp = loads_objects()
    an.Activate()
    Graphics.Redraw()
    camera((-1.0, -0.75, 0.45))
    camera((-1.0, -0.75, 0.45))
    export("fig04")
    hp.Activate()
    Graphics.ViewOptions.ShowMesh = True
    camera((-1.0, -0.75, 0.9))
    export("fig05")
    for o in shown:
        o.Delete()


tmark(u"Рисунки: начало")
WANT = (os.environ.get("AR_FIGS") or "").split(",")
if (os.environ.get("ANSYS_REPORT_IMAGES") or "all").lower() == "none":       # идеальный РВС: рисунки не нужны
    WANT = ["-"]
for nm, fn in (("fig01", fig01), ("fig02", fig02), ("fig03", fig03), ("fig04-05", fig04_05)):
    if WANT == [""] or nm in WANT:
        step(nm, fn)
f = io.open(os.path.join(out, "log_figures.txt"), "w", encoding="utf-8")
f.write(u"\n".join(log))
f.close()
