# -*- coding: utf-8 -*-
# Эксперимент «узел стенка-крыша»: новый EXTRA_APDL из build_model.py (RBE3 на концах радиальных балок, кольца по кромке, опорная полоса)
# подставляется в случай «Вакуум», решаются он и устойчивость; метрики -> diag_fix_<вариант>.json. Проект не сохраняется.
import os, io, math, json, traceback
import System

OUT = r"C:\ansys_report_work"
PKG = r"C:\ansys_report_work\model"
VAR = io.open(os.path.join(OUT, "diag_variant.txt"), encoding="utf-8").read().strip() or "fix"
log = []
res = {"variant": VAR}


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
_src = rd(r"C:\ansys_report_work\build_model_base.py" if VAR == "base" else r"C:\Ansys-report\ansys_scripts\build_model.py")
_src = _src[:_src.index(u"# --- сетка")]
try:
    exec(_src)
except Exception as e:
    L(u"exec build_model: %s" % e)
try:
    if VAR == "rbe3":                       # без опорной полосы
        parts.pop(u"band_width_mm", None)
        parts.pop(u"band_mm", None)
    L(u"parts: %s" % parts)
    extra = apdl_thickness()
    bd = apdl_band() if "apdl_band" in globals() else u""
    if VAR == "rs1000":                     # чувствительность: радиус связи RBE3 1000 мм (полоса уже задана)
        parts[u"band_width_mm"] = 2000.0
    bm = apdl_beams()
    for b_ in (bd, bm):
        if b_:
            extra = (extra + u"\n" if extra else u"") + b_
    L(u"\n".join(blog))
    io.open(os.path.join(OUT, "diag_fix_extra_%s.txt" % VAR), "w", encoding="utf-8").write(extra)
    model = ExtAPI.DataModel.Project.Model
    target = [a for a in model.Analyses if u"Вакуум" in a.Name and a.AnalysisType == AnalysisType.Static][0]
    sn = [c for c in target.Children if "CommandSnippet" in str(c.DataModelObjectCategory)][0]
    old = sn.Input
    i0 = old.index(u"! ANSYS REPORT: нагрузки случая")
    sn.Input = extra + u"\n" + old[i0:]
    L(u"сниппет заменён: было %d строк, стало %d" % (len(old.splitlines()), len(sn.Input.splitlines())))
    sol = target.Solution
    sol.Solve(True)
    L(u"статика: %s" % sol.Status)
    try:
        wd = target.WorkingDir
        L(u"папка решения: %s" % wd)
        err = System.IO.File.ReadAllText(os.path.join(wd, "file0.err")) if os.path.exists(os.path.join(wd, "file0.err")) else u""
        out_ = System.IO.File.ReadAllText(os.path.join(wd, "solve.out"))
        for key in (u"RBE3", u"constraint equation", u"ERROR", u"SECNUM", u"984"):
            hits = [l.strip() for l in (err + u"\n" + out_).splitlines() if key.lower() in l.lower()]
            L(u"  в выводе '%s': %d %s" % (key, len(hits), u" | ".join(hits[:4])))
    except Exception as e:
        L(u"вывод решателя: %s" % e)
    if str(sol.Status) != "Done":
        for m in ExtAPI.Application.Messages:
            L(u"  [%s] %s" % (m.Severity, m.DisplayString))
        raise Exception(u"статика не решена")
    belts = {}
    for r in sol.Children:
        if r.Name.startswith(u"Equivalent Stress"):
            r.EvaluateAllResults()
            belts[r.Name] = r.Maximum.Value
        if r.Name == u"Total Deformation":
            r.EvaluateAllResults()
            res["total_def_mm"] = r.Maximum.Value
    res["results"] = belts
    md = ExtAPI.DataModel.MeshDataByName("Global")

    def nodal(face):
        r = sol.AddEquivalentStress()
        r.Position = face
        r.EvaluateAllResults()
        p = os.path.join(OUT, "diag_fix_tmp.txt")
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
            if s > v.get(n, -1.0):
                v[n] = s
        mx = r.Maximum.Value
        r.Delete()
        return v, mx
    tb, mtb = nodal(ShellFaceType.TopAndBottom)
    mid, mmid = nodal(ShellFaceType.Middle)
    res["max_tb"], res["max_mid"] = mtb, mmid
    H = 18000.0
    zones = [(lo, hi) for (lo, hi, th) in globals()["zones"]]
    bel_tb, bel_mid = {}, {}
    ring, roofmax = [], (0.0, 0)
    top = []
    for nd in md.Nodes:
        r_ = math.sqrt(nd.X ** 2 + nd.Y ** 2)
        s1, s2 = tb.get(nd.Id, 0.0), mid.get(nd.Id, 0.0)
        top.append((s1, nd.Id, nd.X, nd.Y, nd.Z))
        if r_ > 13000 and nd.Z < H - 1.0 or (abs(nd.Z - H) < 1.0 and r_ > 13000):
            for k, (lo, hi) in enumerate(zones, 1):
                if lo - 0.5 <= nd.Z <= hi + 0.5:
                    bel_tb[k] = max(bel_tb.get(k, 0.0), s1)
                    bel_mid[k] = max(bel_mid.get(k, 0.0), s2)
        if abs(nd.Z - H) < 1.0 and r_ > 13000:
            ring.append((s1, s2, math.degrees(math.atan2(nd.Y, nd.X)), nd.Id))
        elif nd.Z > H + 1.0 and s1 > roofmax[0]:
            roofmax = (s1, nd.Id)
    res["belt_tb"] = bel_tb
    res["belt_mid"] = bel_mid
    res["roof_inner_max"] = roofmax
    top.sort(reverse=True)
    res["top20"] = [{"seqv": s, "node": n, "z": z, "r": math.sqrt(x * x + y * y), "ang": math.degrees(math.atan2(y, x))} for (s, n, x, y, z) in top[:20]]
    ring.sort(reverse=True)
    res["ring_top15"] = ring[:15]
    bins = {}
    for r_ in ring:
        d = (r_[2] - 7.5) % 15.0
        d = min(d, 15.0 - d)
        bins.setdefault(int(d // 1.5), []).append(r_)
    res["ring_bins"] = [(k * 1.5, len(b), sum([x[0] for x in b]) / len(b), max([x[0] for x in b]), sum([x[1] for x in b]) / len(b), max([x[1] for x in b]))
                        for k, b in sorted(bins.items())]
    # устойчивость
    bk = [a for a in model.Analyses if a.AnalysisType == AnalysisType.Buckling][0]
    bk.Solution.Solve(True)
    L(u"устойчивость: %s" % bk.Solution.Status)
    ks = []
    for r in bk.Solution.Children:
        if r.Name.startswith(u"Total Deformation"):
            r.EvaluateAllResults()
            for attr in ("ReportedLoadMultiplier", "LoadMultiplier", "ReportedFrequency"):
                if hasattr(r, attr):
                    try:
                        ks.append((r.Name, float(str(getattr(r, attr)).split()[0].replace(",", "."))))
                        break
                    except Exception as e:
                        L(u"  %s.%s: %s" % (r.Name, attr, e))
    res["buckling_k"] = ks
except Exception as e:
    L(u"ОШИБКА: %s" % e)
    L(traceback.format_exc())
f = io.open(os.path.join(OUT, "diag_fix_%s.json" % VAR), "w", encoding="utf-8")
f.write(unicode(json.dumps(res, ensure_ascii=False, indent=1)))
f.close()
f = io.open(os.path.join(OUT, "diag_fix_%s_log.txt" % VAR), "w", encoding="utf-8")
f.write(u"\n".join(log))
f.close()
