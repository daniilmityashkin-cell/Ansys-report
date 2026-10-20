# -*- coding: utf-8 -*-
# Накладывает нагрузки (loads_data.py) на модель резервуара в Mechanical: на каждый расчётный случай создаётся свой Static Structural,
# в нём - опоры, ускорение свободного падения и блок Commands (APDL) с давлениями (гидростатика, избыточное давление, вакуум, снег, ветер)
# и силами от масс оборудования и теплоизоляции. Запускается через Workbench (как остальные скрипты) или вручную: Automation -> Scripting.
# НЕ ПРОВЕРЕНО в реальном Ansys: проверьте направление стрелок давления (если не так - переменная ANSYS_REPORT_FLIP=1) и журнал log_loads.txt.
import os, io
import System

out = os.environ.get("ANSYS_REPORT_OUT") or os.path.join(os.environ["TEMP"], "ansys_report_out")
System.IO.Directory.CreateDirectory(out)
AXIS = (os.environ.get("ANSYS_REPORT_AXIS") or "Z").upper()       # вертикаль модели: геометрия из «RVS Geometry» - Z
FLIP = os.environ.get("ANSYS_REPORT_FLIP") == "1"                  # поменять направление давления, если нормали оболочек смотрят внутрь
USE_MASSES = os.environ.get("ANSYS_REPORT_NO_MASSES") != "1"
log = []


def say(t):
    log.append(t)
    print(t)

ns_globals = {}
path = os.environ.get("ANSYS_REPORT_LOADS") or os.path.join(out, "loads_data.py")      # при ручном запуске: положите loads_data.py в эту папку
exec(io.open(path, encoding="utf-8").read(), ns_globals)
L = ns_globals["LOADS"]
D = L["geometry"]["diameter_mm"]
H = L["geometry"]["wall_height_mm"]
R = D / 2.0
try:
    ExtAPI.Application.ActiveUnitSystem = MechanicalUnitSystem.StandardNMM
except Exception as e:
    say(u"Единицы: %s" % e)
model = ExtAPI.DataModel.Project.Model
AX = {"X": 0, "Y": 1, "Z": 2}[AXIS]
VERT = ("X", "Y", "Z")[AX]


def vcoord(c):
    return c[AX]


# ---------- 1. Классификация граней: стенка, крыша, днище (по высоте центра и площади) ----------
def faces_of_model():
    res = []
    geo = ExtAPI.DataModel.GeoData
    for asm in geo.Assemblies:
        for part in asm.Parts:
            for body in part.Bodies:
                for f in body.Faces:
                    res.append(f)
    return res

faces = faces_of_model()
scale = None
cent = []
for f in faces:
    c = f.Centroid
    cent.append((f, [c[0], c[1], c[2]], f.Area))
if not cent:
    raise Exception(u"в модели нет граней")
span = max(abs(vcoord(c)) for _, c, _ in cent)
scale = 1.0 if span < H * 0.05 else (1000.0 if span < H * 50 else 1.0)       # GeoData отдаёт метры или мм: приводим к мм
say(u"Грани: %d, масштаб координат к мм: %g" % (len(cent), scale))
wall_area = 3.14159 * D * H
groups = {"wall": [], "roof": [], "bottom": [], "other": []}
for f, c, a in cent:
    z = vcoord(c) * scale
    area = a * scale * scale
    if area < 0.02 * wall_area:
        groups["other"].append(f)
    elif z < 0.03 * H:
        groups["bottom"].append(f)
    elif z > 0.995 * H:
        groups["roof"].append(f)
    else:
        groups["wall"].append(f)
say(u"Стенка: %d, крыша: %d, днище: %d, прочие (патрубки и т.п.): %d" % (len(groups["wall"]), len(groups["roof"]), len(groups["bottom"]), len(groups["other"])))


def named_selection(name, entities):
    if not entities:
        return None
    try:
        for old in model.NamedSelections.GetChildren[Ansys.ACT.Automation.Mechanical.NamedSelection](False):
            if old.Name == name:
                old.Delete()
    except Exception as e:
        say(u"  (не удалось проверить прежние выборки: %s)" % e)
    sel = ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
    sel.Entities = entities
    ns = model.AddNamedSelection()
    ns.Name = name
    ns.Location = sel
    return ns

ns_wall = named_selection("AR_WALL", groups["wall"])
ns_roof = named_selection("AR_ROOF", groups["roof"])
ns_bottom = named_selection("AR_BOTTOM", groups["bottom"])
edges = []
for f in groups["wall"] + groups["bottom"]:
    for e in f.Edges:
        c = e.Centroid
        if abs(vcoord(c) * scale) < 0.005 * H and e.Length * scale > 0.5 * 3.14159 * D:
            edges.append(e)
ns_base = named_selection("AR_BASE_EDGE", edges)
say(u"Именованные выборки: AR_WALL=%s AR_ROOF=%s AR_BOTTOM=%s AR_BASE_EDGE=%d рёбер" % (ns_wall is not None, ns_roof is not None, ns_bottom is not None, len(edges)))


# ---------- 2. APDL для расчётного случая ----------
def fmt(x):
    return repr(float(x))


def apdl_case(case):
    z = ("X", "Y", "Z")[AX]
    sign = -1.0 if FLIP else 1.0
    t = []
    t.append(u"! ANSYS REPORT: нагрузки случая '%s'. Давление: + изнутри наружу (грань 1, нормали наружу). FLIP=%s" % (case["name"], FLIP))
    if case["gravity"]:
        t.append(u"ACEL,%s,%s,%s" % tuple(fmt(L["gravity_mm_s2"]) if i == AX else u"0" for i in range(3)))
    t.append(u"*DIM,wz_lo,ARRAY,%d\n*DIM,wz_hi,ARRAY,%d\n*DIM,wp,ARRAY,%d" % tuple([max(len(case["wind"]), 1)] * 3))
    for i, w in enumerate(case["wind"], 1):
        t.append(u"wz_lo(%d)=%s\nwz_hi(%d)=%s\nwp(%d)=%s" % (i, fmt(w["z_lo_mm"]), i, fmt(w["z_hi_mm"]), i, fmt(w["p_mpa"])))
    hy = case.get("hydro")
    grad = hy["gradient_mpa_mm"] if hy else 0.0
    zfs = hy["free_surface_mm"] if hy else 0.0
    t.append(u"pu=%s\nproof=%s\ngrad=%s\nzfs=%s\nnw=%d\nsg=%s" % (fmt(case["uniform_mpa"]), fmt(case["roof_extra_mpa"]), fmt(grad), fmt(zfs), len(case["wind"]), fmt(sign)))
    body = [
        u"ALLSEL,ALL",
        u"%s" % (u"CMSEL,S,AR_WALL,NODE\nESLN,S,1\n" if ns_wall is not None else u""),
        u"*GET,emax,ELEM,0,NUM,MAX",
        u"*DO,ee,1,emax",
        u"*IF,ESEL(ee),EQ,1,THEN",
        u"  *GET,zc,ELEM,ee,CENT,%s" % z,
        u"  pv=pu",
        u"  *IF,grad,GT,0,AND,zc,LT,zfs,THEN",
        u"    pv=pv+grad*(zfs-zc)",
        u"  *ENDIF",
        u"  *IF,nw,GT,0,THEN",
        u"    *DO,kk,1,nw",
        u"      *IF,zc,GE,wz_lo(kk),AND,zc,LT,wz_hi(kk),THEN",
        u"        pv=pv+wp(kk)",
        u"      *ENDIF",
        u"    *ENDDO",
        u"  *ENDIF",
        u"  SFE,ee,1,PRES,,sg*pv",
        u"*ENDIF",
        u"*ENDDO",
    ] if ns_wall is not None else []
    t.extend(body)
    if ns_roof is not None:
        t += [u"ALLSEL,ALL", u"CMSEL,S,AR_ROOF,NODE", u"ESLN,S,1", u"SFE,ALL,1,PRES,,sg*(pu+proof)"]
    if ns_bottom is not None and hy:
        t += [u"ALLSEL,ALL", u"CMSEL,S,AR_BOTTOM,NODE", u"ESLN,S,1", u"SFE,ALL,1,PRES,,sg*(pu+grad*zfs)"]
    # силы от масс оборудования и теплоизоляции (метал. конструкции модели учитываются самой моделью и ускорением)
    if case["masses"] and USE_MASSES:
        g = L["gravity_mm_s2"] / 1000.0
        by_loc = {}
        for m in L["point_masses"]:
            by_loc[m["location"]] = by_loc.get(m["location"], 0.0) + m["mass_kg"]
        for loc, kg in sorted(by_loc.items()):
            if loc == "roof" and ns_roof is not None:
                t += [u"ALLSEL,ALL", u"CMSEL,S,AR_ROOF,NODE"]
            elif loc.startswith("belt_") and ns_wall is not None:
                k = int(loc[5:]) - 1
                lo, hi = L["belt_z_mm"][k]
                t += [u"ALLSEL,ALL", u"CMSEL,S,AR_WALL,NODE", u"NSEL,R,LOC,%s,%s,%s" % (z, fmt(lo - 0.01), fmt(hi + 0.01))]
            else:
                continue
            t += [u"*GET,nn,NODE,0,COUNT", u"*IF,nn,GT,0,THEN", u"fn=%s/nn" % fmt(-kg * g), u"F,ALL,F%s,fn" % z, u"*ENDIF"]
    t.append(u"ALLSEL,ALL")
    return u"\n".join(t)


# ---------- 3. Расчётные случаи ----------
base = None
for a in model.Analyses:
    if a.Name.startswith("Static"):
        base = a
        break
for case in L["cases"]:
    try:
        an = model.AddStaticStructuralAnalysis()
        an.Name = u"AR: " + case["name"]
        if ns_base is not None:
            fx = an.AddFixedSupport()
            fx.Location = ns_base
        if ns_bottom is not None:
            fl = an.AddFrictionlessSupport()
            fl.Location = ns_bottom
        sn = an.AddCommandSnippet()
        sn.Name = u"AR нагрузки: " + case["name"]
        sn.AppendText(apdl_case(case))
        say(u"Случай '%s': создан, нагрузки заданы" % case["name"])
    except Exception as e:
        say(u"ОШИБКА случая '%s': %s" % (case["name"], e))

f = io.open(os.path.join(out, "log_loads.txt"), "w", encoding="utf-8")
f.write(u"\n".join(log))
f.close()
