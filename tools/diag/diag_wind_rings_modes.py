# -*- coding: utf-8 -*-
# Кольца жёсткости: та же сетка, APDL с кольцами и без; 30 форм потери устойчивости, первая форма стенки.
import os, io, math, json, traceback, shutil
import System
OUT = r"C:\ansys_report_work"
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
    wfile(os.path.join(OUT, "diag_rmodes80_log.txt"), u"\n".join(log))
def rd(p):
    fh = io.open(p, encoding="utf-8")
    try:
        return fh.read()
    finally:
        fh.close()
os.environ["AR_PKG"] = os.path.join(OUT, "model")
os.environ["ANSYS_REPORT_MESH_MM"] = "200"
_src = rd(r"C:\Ansys-report\ansys_scripts\build_model.py")
exec(_src[:_src.index(u"# --- сетка")])
NR = os.path.join(OUT, "pkg_norings")
System.IO.Directory.CreateDirectory(NR)
bj = json.loads(rd(os.path.join(OUT, "model", "beams.json")))
bj["wind_rings"] = []
wfile(os.path.join(NR, "beams.json"), unicode(json.dumps(bj, ensure_ascii=False)))
H = WALL_H
def export(r):
    r.EvaluateAllResults()
    p = os.path.join(OUT, "diag_rmodes_tmp.txt")
    r.ExportToTextFile(p)
    v = {}
    for i, line in enumerate(System.IO.File.ReadAllText(p).splitlines()):
        q = line.strip().split("\t")
        if i == 0:
            continue
        try:
            v[int(q[0])] = float(q[1].replace(",", "."))
        except Exception:
            pass
    return v
try:
    model = ExtAPI.DataModel.Project.Model
    vac = [a for a in model.Analyses if u"Вакуум" in a.Name and a.AnalysisType == AnalysisType.Static][0]
    bk = [a for a in model.Analyses if a.AnalysisType == AnalysisType.Buckling][0]
    bk.AnalysisSettings.MaximumModesToFind = 80
    md = ExtAPI.DataModel.MeshDataByName("Global")
    zone = {}
    for nd in md.Nodes:
        zone[nd.Id] = u"днище" if nd.Z < 1 else (u"крыша" if nd.Z > H + 1 else u"стенка")
    for tag, p_ in ((u"с кольцами", os.path.join(OUT, "model")), (u"без колец", NR)):
        pkg = p_
        del blog[:]
        extra = apdl_thickness()
        for b_ in (apdl_band(), apdl_beams()):
            if b_:
                extra = (extra + u"\n" if extra else u"") + b_
        L(u"%s: %s" % (tag, u" | ".join([b for b in blog if u"Кольцо" in b or u"элементов" in b])))
        sn = [c for c in vac.Children if "CommandSnippet" in str(c.DataModelObjectCategory)][0]
        old = sn.Input
        sn.Input = extra + u"\n" + old[old.index(u"! ANSYS REPORT: нагрузки случая"):]
        vac.Solution.Solve(True)
        td = vac.Solution.AddTotalDeformation()
        u = export(td)
        td.Delete()
        uw = max([u.get(n, 0.0) for n in zone if zone[n] == u"стенка"])
        bk.Solution.Solve(True)
        L(u"  статусы %s / %s; вакуум: макс. перемещение стенки %.2f мм" % (vac.Solution.Status, bk.Solution.Status, uw))
        modes = []
        nsw = [n for n in model.NamedSelections.Children if n.Name == u"AR_WALL"][0]
        rall = bk.Solution.AddTotalDeformation()
        rw = bk.Solution.AddTotalDeformation()
        rw.Location = nsw
        for mode in range(1, 81):
            rall.Mode = mode
            rw.Mode = mode
            rall.EvaluateAllResults()
            rw.EvaluateAllResults()
            k = None
            for a in ("ReportedLoadMultiplier", "LoadMultiplier", "ReportedFrequency"):
                try:
                    k = float(str(getattr(rall, a)).split()[0].replace(",", "."))
                    break
                except Exception:
                    pass
            share = rw.Maximum.Value / max(rall.Maximum.Value, 1e-12)
            modes.append({"mode": mode, "k": k, "wall_share": round(share, 2)})
        rall.Delete()
        rw.Delete()
        first_wall = [m for m in modes if m["wall_share"] > 0.5]
        res[tag] = {"u_wall_vacuum_mm": uw, "modes": modes, "first_wall_mode": first_wall[0] if first_wall else None}
        L(u"  k1..3: %s; первая форма стенки: %s" % ([m["k"] for m in modes[:3]], first_wall[0] if first_wall else u"нет среди 30"))
except Exception as e:
    L(u"ОШИБКА: %s" % e)
    L(traceback.format_exc())
wfile(os.path.join(OUT, "diag_rmodes80.json"), unicode(json.dumps(res, ensure_ascii=False, indent=1)))
L(u"готово")
