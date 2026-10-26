# -*- coding: utf-8 -*-
# Пик в поясах 2-3 («Эксплуатация»): сетка 200 мм против 100 мм на гранях поясов 2-3. Проект не сохраняется.
import os, io, math, json, traceback
import System

OUT = r"C:\ansys_report_work"
PKG = r"C:\ansys_report_work\model"
log = []
res = {}


def L(t):
    log.append(t)


def rd(p, enc="utf-8"):
    fh = io.open(p, encoding=enc)
    try:
        return fh.read()
    finally:
        fh.close()

os.environ["AR_PKG"] = PKG
os.environ["ANSYS_REPORT_MESH_MM"] = "200"
_src = rd(r"C:\Ansys-report\ansys_scripts\build_model.py")
_src = _src[:_src.index(u"# --- сетка")]
exec(_src)


def nodal(sol, kind, face):
    r = sol.AddEquivalentStress() if kind == "eqv" else sol.AddMaximumPrincipalStress()
    r.Position = face
    r.EvaluateAllResults()
    p = os.path.join(OUT, "diag_mesh100_tmp.txt")
    r.ExportToTextFile(p)
    v = {}
    for i, line in enumerate(System.IO.File.ReadAllText(p).splitlines()):
        if i == 0:
            continue
        q = line.strip().split("\t")
        try:
            n = int(q[0]); s = float(q[1].replace(",", "."))
        except Exception:
            continue
        if s > v.get(n, -1e30):
            v[n] = s
    r.Delete()
    return v


def measure(tag, sol):
    md = ExtAPI.DataModel.MeshDataByName("Global")
    eq = nodal(sol, "eqv", ShellFaceType.TopAndBottom)
    mm = nodal(sol, "s1", ShellFaceType.Middle)
    out = {"nodes": md.NodeCount, "elements": md.ElementCount}
    for b in (1, 2, 3, 4):
        lo, hi = zones[b - 1][0], zones[b - 1][1]
        best_e, best_m, cnt = (0.0, None), (0.0, None), 0
        for nd in md.Nodes:
            if lo - 0.5 <= nd.Z <= hi + 0.5 and math.sqrt(nd.X ** 2 + nd.Y ** 2) > 13000:
                cnt += 1
                e, m = eq.get(nd.Id, 0.0), mm.get(nd.Id, 0.0)
                loc = (round(math.degrees(math.atan2(nd.Y, nd.X)), 1), round(nd.Z))
                if e > best_e[0]:
                    best_e = (e, loc)
                if m > best_m[0]:
                    best_m = (m, loc)
        out["belt%d" % b] = {"eqv_TB": best_e, "s1_mid": best_m, "nodes": cnt}
    res[tag] = out
    L(u"%s: %s" % (tag, json.dumps(out)))

try:
    model = ExtAPI.DataModel.Project.Model
    target = [a for a in model.Analyses if a.Name == u"AR: Эксплуатация"][0]
    sol = target.Solution
    if str(sol.Status) != "Done":
        sol.Solve(True)
    L(u"200 мм: статус %s" % sol.Status)
    measure("mesh200", sol)
    # сгущение на поясах 2-3
    ids = []
    for asm in ExtAPI.DataModel.GeoData.Assemblies:
        for part in asm.Parts:
            for body in part.Bodies:
                for f in body.Faces:
                    z = f.Centroid[2] * (1000.0 if abs(f.Centroid[2]) < 100 else 1.0)
                    if zones[1][0] < z < zones[2][1] and f.Area * (1e6 if f.Area < 10000 else 1.0) > 1e7:
                        ids.append(f.Id)
    L(u"грани поясов 2-3: %s" % ids)
    sel = ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
    sel.Ids = ids
    sz = model.Mesh.AddSizing()
    sz.Location = sel
    sz.ElementSize = Quantity(100, "mm")
    model.Mesh.GenerateMesh()
    md = ExtAPI.DataModel.MeshDataByName("Global")
    L(u"сетка перестроена: узлов %d, элементов %d" % (md.NodeCount, md.ElementCount))
    extra = apdl_thickness()
    for b_ in (apdl_band(), apdl_beams()):
        if b_:
            extra = (extra + u"\n" if extra else u"") + b_
    L(u"\n".join(blog))
    sn = [c for c in target.Children if "CommandSnippet" in str(c.DataModelObjectCategory)][0]
    old = sn.Input
    sn.Input = extra + u"\n" + old[old.index(u"! ANSYS REPORT: нагрузки случая"):]
    sol.Solve(True)
    L(u"100 мм: статус %s" % sol.Status)
    if str(sol.Status) != "Done":
        for m in ExtAPI.Application.Messages:
            L(u"  [%s] %s" % (m.Severity, m.DisplayString))
    else:
        measure("mesh100", sol)
except Exception as e:
    L(u"ОШИБКА: %s" % e)
    L(traceback.format_exc())
io.open(os.path.join(OUT, "diag_mesh100.json"), "w", encoding="utf-8").write(unicode(json.dumps(res, ensure_ascii=False, indent=1)))
io.open(os.path.join(OUT, "diag_mesh100_log.txt"), "w", encoding="utf-8").write(u"\n".join(log))
