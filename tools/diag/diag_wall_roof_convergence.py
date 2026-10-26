# -*- coding: utf-8 -*-
# 1) Сходимость σ у кромки «стенка-крыша» (случай «Вакуум»): сферы 1,5 м на кромке, сетка 200/100/50 мм (вмятины без сгущения).
# 2) Картинки «Эксплуатации»: без/со сгущением у вмятин, полосы/плавный контур. Проект не сохраняется.
import os, io, math, json, traceback
import System

OUT = r"C:\ansys_report_work"
IMG = os.path.join(OUT, "diag_edge_img")
System.IO.Directory.CreateDirectory(IMG)
log = []
res = {}


def wfile(path, text):
    fh = io.open(path, "w", encoding="utf-8")
    try:
        fh.write(text)
    finally:
        fh.close()


def L(t):
    log.append(t)
    wfile(os.path.join(OUT, "diag_edge_log.txt"), u"\n".join(log))


def rd(p):
    fh = io.open(p, encoding="utf-8")
    try:
        return fh.read()
    finally:
        fh.close()

os.environ["AR_PKG"] = r"C:\ansys_report_work\model"
os.environ["ANSYS_REPORT_MESH_MM"] = "200"
_src = rd(r"C:\Ansys-report\ansys_scripts\build_model.py")
exec(_src[:_src.index(u"# --- сетка")])
H = WALL_H
R = 14250.0
CENTERS = [(7.5, u"балка 7,5°"), (52.5, u"балка 52,5° (вмятина 1 рядом)"), (30.0, u"между балками 30°")]
added = []


def clear_sizing():
    for c in list(model.Mesh.Children):
        if c.Name.startswith(u"AR сетка") or c.Name.startswith(u"DIAG"):
            c.Delete()
    for c in list(model.CoordinateSystems.Children):
        if c.Name.startswith(u"AR вмятина") or c.Name.startswith(u"DIAG"):
            c.Delete()


def wall_face_ids():
    ids = []
    for asm in ExtAPI.DataModel.GeoData.Assemblies:
        for part in asm.Parts:
            for body in part.Bodies:
                for f in body.Faces:
                    z = f.Centroid[2] * (1000.0 if abs(f.Centroid[2]) < 100 else 1.0)
                    if 0.002 * H < z < 0.998 * H:
                        ids.append(f.Id)
    return ids


def dents_on_faces():
    dents = json.loads(rd(os.path.join(os.environ["AR_PKG"], "dents.json")))
    sel = ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
    sel.Ids = wall_face_ids()
    L(u"  граней стенки: %d" % len(sel.Ids))
    for k, d in enumerate(dents, 1):
        cs = model.CoordinateSystems.AddCoordinateSystem()
        cs.Name = u"AR вмятина %d" % k
        cs.OriginDefineBy = CoordinateSystemAlignmentType.Fixed
        cs.OriginX = Quantity(d["x_mm"], "mm")
        cs.OriginY = Quantity(d["y_mm"], "mm")
        cs.OriginZ = Quantity(d["z_mm"], "mm")
        sz = model.Mesh.AddSizing()
        sz.Name = u"AR сетка вмятины %d" % k
        sz.Location = sel
        sz.Type = SizingType.SphereOfInfluence
        sz.SphereCenter = cs
        sz.SphereRadius = Quantity(d["radius_mm"], "mm")
        sz.ElementSize = Quantity(100, "mm")


def edge_spheres(size):
    body = model.Geometry.GetChildren(DataModelObjectCategory.Body, True)[0]
    sel = ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
    sel.Ids = [body.GetGeoBody().Id]
    for ang, nm in CENTERS:
        cs = model.CoordinateSystems.AddCoordinateSystem()
        cs.Name = u"DIAG кромка %g" % ang
        cs.OriginDefineBy = CoordinateSystemAlignmentType.Fixed
        cs.OriginX = Quantity(R * math.cos(math.radians(ang)), "mm")
        cs.OriginY = Quantity(R * math.sin(math.radians(ang)), "mm")
        cs.OriginZ = Quantity(H, "mm")
        sz = model.Mesh.AddSizing()
        sz.Name = u"DIAG сетка кромки %g" % ang
        sz.Location = sel
        sz.Type = SizingType.SphereOfInfluence
        sz.SphereCenter = cs
        sz.SphereRadius = Quantity(1500, "mm")
        sz.ElementSize = Quantity(size, "mm")


def remesh_and_snippets(names):
    model.Mesh.GenerateMesh()
    del blog[:]
    extra = apdl_thickness()
    for b_ in (apdl_band(), apdl_beams()):
        if b_:
            extra = (extra + u"\n" if extra else u"") + b_
    for an in model.Analyses:
        if an.Name in names:
            sn = [c for c in an.Children if "CommandSnippet" in str(c.DataModelObjectCategory)][0]
            old = sn.Input
            sn.Input = extra + u"\n" + old[old.index(u"! ANSYS REPORT: нагрузки случая"):]
    md = ExtAPI.DataModel.MeshDataByName("Global")
    L(u"  сетка: узлов %d; %s" % (md.NodeCount, u" | ".join([b for b in blog if u"Концы" in b])))


def nodal(sol, kind, face):
    r = sol.AddEquivalentStress() if kind == "eqv" else sol.AddMaximumPrincipalStress()
    r.Position = face
    r.EvaluateAllResults()
    p = os.path.join(OUT, "diag_edge_tmp.txt")
    r.ExportToTextFile(p)
    v = {}
    for i, line in enumerate(System.IO.File.ReadAllText(p).splitlines()):
        q = line.strip().split("\t")
        if i == 0:
            continue
        try:
            n = int(q[0]); s = float(q[1].replace(",", "."))
        except Exception:
            continue
        v[n] = max(v.get(n, -1e30), s)
    r.Delete()
    return v


def measure_edge(tag, sol):
    md = ExtAPI.DataModel.MeshDataByName("Global")
    eq = nodal(sol, "eqv", ShellFaceType.TopAndBottom)
    mm = nodal(sol, "eqv", ShellFaceType.Middle)
    out = {}
    for ang, nm in CENTERS:
        cx, cy = R * math.cos(math.radians(ang)), R * math.sin(math.radians(ang))
        be, bm, n = (0.0, None), (0.0, None), 0
        for nd in md.Nodes:
            if (nd.X - cx) ** 2 + (nd.Y - cy) ** 2 + (nd.Z - H) ** 2 < 1000.0 ** 2:
                n += 1
                loc = (round(math.degrees(math.atan2(nd.Y, nd.X)), 2), round(nd.Z))
                e, m = eq.get(nd.Id, 0.0), mm.get(nd.Id, 0.0)
                if e > be[0]:
                    be = (e, loc)
                if m > bm[0]:
                    bm = (m, loc)
        out[nm] = {"eqv_TB": be, "eqv_mid": bm, "nodes_r1000": n}
    allmax = max(eq.values())
    b12 = 0.0
    for nd in md.Nodes:
        if 16500 <= nd.Z <= H + 0.5 and math.sqrt(nd.X ** 2 + nd.Y ** 2) > 13000:
            b12 = max(b12, eq.get(nd.Id, 0.0))
    out["max_all"] = allmax
    out["belt12_max"] = b12
    res[tag] = out
    L(u"%s: %s" % (tag, json.dumps(out, ensure_ascii=False)))


def shot(sol, name, smooth):
    from Ansys.ACT.Math import Vector3D
    r = [c for c in sol.Children if c.Name == u"Equivalent Stress"][0]
    r.EvaluateAllResults()
    Graphics.ViewOptions.ShowMesh = False
    rp = Graphics.ViewOptions.ResultPreference
    cur = rp.ExtraModelDisplay
    rp.GetType().GetProperty("ExtraModelDisplay").SetValue(rp, getattr(type(cur), "NoWireframe"), None)
    cv = rp.ContourView
    names = [n for n in dir(type(cv)) if n[:1].isupper() and ("Contour" in n or "Fill" in n or "Iso" in n)]
    target = getattr(type(cv), "SmoothContours" if smooth else "ContourBands")
    try:
        rp.ContourView = target
    except Exception as e:
        L(u"  ContourView прямо: %s" % e)
        rp.GetType().GetProperty("ContourView").SetValue(rp, target, None)
    L(u"  картинка %s: ContourView=%s (варианты %s)" % (name, rp.ContourView, names))
    r.Activate()
    cam = Graphics.Camera
    cam.UpVector = Vector3D(0, 0, 1)
    cam.ViewVector = Vector3D(-1, -0.6, -0.5)
    cam.SetFit()
    st = Ansys.Mechanical.Graphics.GraphicsImageExportSettings()
    st.CurrentGraphicsDisplay = False
    st.Resolution = GraphicsResolutionType.EnhancedResolution
    st.Width = 2000
    st.Height = 1300
    Graphics.ExportImage(os.path.join(IMG, name + ".png"), GraphicsImageExportFormat.PNG, st)

try:
    model = ExtAPI.DataModel.Project.Model
    vac = [a for a in model.Analyses if u"Вакуум" in a.Name and a.AnalysisType == AnalysisType.Static][0]
    exp = [a for a in model.Analyses if a.Name == u"AR: Эксплуатация"][0]
    VN, EN = vac.Name, exp.Name
    # картинки: сферы у вмятин на гранях стенки (а не на теле)
    clear_sizing()
    dents_on_faces()
    L(u"C: сгущение у вмятин, сферы на гранях стенки")
    remesh_and_snippets([EN])
    exp.Solution.Solve(True)
    L(u"  статус %s" % exp.Solution.Status)
    shot(exp.Solution, u"C_faces_bands", False)
    shot(exp.Solution, u"C_faces_smooth", True)
    # сходимость у кромки (вмятины без сгущения)
    clear_sizing()
    L(u"кромка 200 мм")
    remesh_and_snippets([VN])
    vac.Solution.Solve(True)
    measure_edge("edge200", vac.Solution)
    for size in (100, 50):
        clear_sizing()
        edge_spheres(size)
        L(u"кромка %d мм" % size)
        remesh_and_snippets([VN])
        vac.Solution.Solve(True)
        L(u"  статус %s" % vac.Solution.Status)
        measure_edge("edge%d" % size, vac.Solution)
except Exception as e:
    L(u"ОШИБКА: %s" % e)
    L(traceback.format_exc())
wfile(os.path.join(OUT, "diag_edge.json"), unicode(json.dumps(res, ensure_ascii=False, indent=1)))
L(u"готово")
