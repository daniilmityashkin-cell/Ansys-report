# -*- coding: utf-8 -*-
# Собирает расчётную модель резервуара в Mechanical: материал, толщины поясов по высоте (APDL по участкам), сетка, затем накладывает нагрузки (apply_loads.py).
# Запускается из Open_in_Ansys.bat через журнал build_model.wbjn. НЕ ПРОВЕРЕНО в реальном Ansys: смотрите log_loads.txt и log_build.txt.
import os, io
import System


def _rd(path, enc="utf-8"):
    """Читает файл целиком и сразу закрывает (IronPython не закрывает неявно: повторное чтение даёт «файл занят»)."""
    fh_ = io.open(path, encoding=enc)
    try:
        return fh_.read()
    finally:
        fh_.close()

pkg = os.environ.get("AR_PKG") or ""
out = os.environ.get("ANSYS_REPORT_OUT") or os.path.join(pkg, "out")
System.IO.Directory.CreateDirectory(out)
blog = []


def bsay(t):
    blog.append(t)
    print(t)


def tmark(label):
    """Метка времени этапа (ansys_report/timing.py): длительность этапа - до следующей метки."""
    try:
        import time
        f_ = io.open(os.environ.get("AR_TIMING") or r"C:\ansys_report_work\timing.log", "a", encoding="utf-8")
        f_.write(u"%.3f\t%s\t%s\n" % (time.time(), os.environ.get("AR_TIMING_TAG", ""), label))
        f_.close()
    except Exception:
        pass

tmark(u"Сборка: материал, толщины, тела")

try:
    ExtAPI.Application.ActiveUnitSystem = MechanicalUnitSystem.StandardNMM
except Exception as e:
    bsay(u"Единицы: %s" % e)
model = ExtAPI.DataModel.Project.Model

# --- участки толщины: thickness_zones.csv (Участок;Первый пояс;Последний пояс;Низ, м;Верх, м;Толщина, мм)
zones = []
zpath = os.path.join(pkg, "thickness_zones.csv")
if os.path.exists(zpath):
    for i, line in enumerate(_rd(zpath, "utf-8-sig").splitlines()):
        if i == 0 or not line.strip():
            continue
        p = line.replace(u",", u".").split(u";")
        zones.append((float(p[3]) * 1000.0, float(p[4]) * 1000.0, float(p[5])))
bsay(u"Участков толщины: %d" % len(zones))
parts = {}
try:                                                     # parts.json: толщины днища, окрайки и крыши (если они достроены в модели)
    ppath = os.path.join(pkg, "parts.json")
    if os.path.exists(ppath):
        pj = _rd(ppath)
        for key in (u"disc_mm", u"annular_mm", u"roof_mm", u"band_width_mm", u"band_mm"):
            m_ = __import__("re").search(u'"%s":\\s*([0-9.]+)' % key, pj)
            if m_:
                parts[key] = float(m_.group(1))
except Exception as e:
    bsay(u"parts.json: %s" % e)
bsay(u"Части модели: %s" % parts)

# --- толщина тел (первая зона; остальные задаются APDL по высоте) и материал по умолчанию
try:
    bodies = model.Geometry.GetChildren(DataModelObjectCategory.Body, True)
    for b in bodies:
        try:
            if zones:
                b.Thickness = Quantity(zones[0][2], "mm")
        except Exception as e:
            bsay(u"  толщина тела %s: %s" % (b.Name, e))
    bsay(u"Тел в модели: %d" % len(bodies))
    for b in bodies:
        try:
            gb = b.GetGeoBody()
            bsay(u"  тело %s: граней %d, площадь %.1f м2" % (b.Name, len(gb.Faces), sum([f.Area for f in gb.Faces]) / 1e6))
        except Exception as e:
            bsay(u"  тело %s: %s" % (b.Name, e))
except Exception as e:
    bsay(u"ОШИБКА тел: %s" % e)


def apdl_thickness():
    """Секции оболочек для участков толщины: элементы стенки (AR_WALL) получают секцию по высоте центра элемента."""
    if len(zones) < 2 and not parts:
        return u""
    t = [u"/PREP7", u"*GET,e1,ELEM,0,NUM,MIN", u"*GET,matid,ELEM,e1,ATTR,MAT"]
    for k, (lo, hi, th) in enumerate(zones):
        t += [u"SECTYPE,%d,SHELL" % (901 + k), u"SECDATA,%r,matid,0,3" % th]
    for sec, key, comp in ((981, u"disc_mm", u"AR_BOTTOM"), (982, u"annular_mm", u"AR_ANNULAR"), (983, u"roof_mm", u"AR_ROOF")):
        if key in parts:
            t += [u"SECTYPE,%d,SHELL" % sec, u"SECDATA,%r,matid,0,3" % parts[key],
                  u"ALLSEL,ALL", u"CMSEL,S,%s,NODE" % comp, u"ESLN,S,1", u"EMODIF,ALL,SECNUM,%d" % sec]
    if len(zones) < 2:
        t.append(u"ALLSEL,ALL")
        return u"\n".join(t + [u"/SOLU"])
    # выборка по центру элемента (ESEL,R,CENT) вместо поэлементного цикла *DO: тот же результат, /PREP7 ~14 с -> ~1 с на каждое решение
    ax = ("X", "Y", "Z")[{"X": 0, "Y": 1, "Z": 2}[(os.environ.get("ANSYS_REPORT_AXIS") or "Z").upper()]]
    for k, (lo, hi, th) in enumerate(zones, 1):
        top = hi + 0.01 if k == len(zones) else hi - 0.001
        t += [u"ALLSEL,ALL", u"CMSEL,S,AR_WALL,NODE", u"ESLN,S,1", u"ESEL,R,CENT,%s,%r,%r" % (ax, lo - 0.01, top),
              u"*GET,ne_,ELEM,0,COUNT", u"*IF,ne_,GT,0,THEN", u"  EMODIF,ALL,SECNUM,%d" % (900 + k), u"*ENDIF"]
    t += [u"ALLSEL,ALL", u"/SOLU"]
    return u"\n".join(t)

EXTRA_APDL = apdl_thickness()                       # apply_loads.py добавляет этот блок в каждый расчётный случай


_lns = {}
try:                                                # exec вне функции с вложенными функциями (ограничение IronPython)
    exec(_rd(os.path.join(pkg, "loads_data.py")), _lns)
    WALL_H = float(_lns["LOADS"]["geometry"]["wall_height_mm"])
except Exception as e:
    WALL_H = 0.0


def apdl_beams():
    """Балки каркаса крыши (радиальные, кольцевые, центральное и периферийное кольца) и опорное кольцо на верхнем поясе стенки:
    BEAM188 по узлам оболочки (общие узлы - совместная работа). Узлы выбираются по геометрии из сетки, цепочки сортируются по углу/радиусу."""
    import json, math
    bp_path = os.path.join(pkg, "beams.json")
    if not os.path.exists(bp_path):
        bsay(u"Балки: файла beams.json нет в пакете (%s) - каркас крыши не моделируется" % pkg)
        return u""
    bp = json.loads(_rd(bp_path))
    H = WALL_H
    R = float(bp["wall_radius_mm"])
    ax = {"X": 0, "Y": 1, "Z": 2}[(os.environ.get("ANSYS_REPORT_AXIS") or "Z").upper()]
    ia, ib = [i for i in (0, 1, 2) if i != ax]
    size = float(os.environ.get("ANSYS_REPORT_MESH_MM") or 200)
    tol = 0.6 * size
    md = ExtAPI.DataModel.MeshDataByName("Global")
    rs = max(2.0 * size, 0.5 * parts.get(u"band_width_mm", 0.0))   # радиус передачи силы с конца радиальной балки на оболочку (RBE3)
    roof, top, near = [], [], []
    for nd in md.Nodes:
        c = (nd.X, nd.Y, nd.Z)
        h = c[ax]
        x, y = c[ia], c[ib]
        rr = math.sqrt(x * x + y * y)
        if h >= H - 1.0:
            roof.append((nd.Id, x, y, rr, math.atan2(y, x)))
            if h <= H + 1.0 and rr > 0.9 * R:                # верхняя кромка стенки по факту (стенка не круглая: радиус по замерам)
                top.append((nd.Id, math.atan2(y, x)))
        if h >= H - 1.0 and rr > R - rs - 300.0:            # узлы связи: кромка стенки и крыша (узлы стенки ниже кромки дают пик на границе пятна)
            near.append((nd.Id, c))
    bsay(u"Балки: узлов крыши %d, узлов верхней кромки стенки %d" % (len(roof), len(top)))
    top_sel = [(i, a, R * math.cos(a), R * math.sin(a)) for (i, a) in top]
    secs, elems = [], []                                   # секции: (id, данные); элементы: (id секции, n1, n2)

    def add_sec(d):
        secs.append(d)
        return 951 + len(secs) - 1

    def chain(pairs, closed, sec_id, maxgap):
        # pairs: [(узел, ключ сортировки, x, y)], соседние по ключу соединяются балкой
        pairs.sort(key=lambda p: p[1])
        n = len(pairs)
        cnt = 0
        for i in range(n - 1 + (1 if closed else 0)):
            a, b = pairs[i], pairs[(i + 1) % n]
            if a[0] == b[0]:
                continue
            if math.sqrt((a[2] - b[2]) ** 2 + (a[3] - b[3]) ** 2) > maxgap:
                continue
            elems.append((sec_id, a[0], b[0]))
            cnt += 1
        return cnt
    total = 0
    if bp.get("top_ring") and top:
        sid = add_sec(bp["top_ring"])
        total += chain(list(top_sel), True, sid, 3 * size)
    wr = bp.get("wind_rings") or []
    if wr:                                                 # кольца жёсткости на стенке: балки по узлам границы поясов
        md2 = ExtAPI.DataModel.MeshDataByName("Global")
        for ring in wr:
            zr = float(ring["z_m"]) * 1000.0
            sel = []
            for nd in md2.Nodes:
                c = (nd.X, nd.Y, nd.Z)
                if abs(c[ax] - zr) < 1.0:
                    x, y = c[ia], c[ib]
                    if math.sqrt(x * x + y * y) > 0.5 * R:
                        sel.append((nd.Id, math.atan2(y, x), x, y))
            sid = add_sec(ring)
            n_ring = chain(sel, True, sid, 3 * size)
            total += n_ring
            bsay(u"Кольцо жёсткости z=%.2f м: узлов %d, элементов %d" % (zr / 1000.0, len(sel), n_ring))
    rc = float(bp.get("central_radius_mm") or 0.0)
    rings = []
    if bp.get("central"):
        rings.append((rc, bp["central"]))
    rl = bp.get("rings") or []
    for j, sdat in enumerate(rl, 1):
        rings.append((rc + (R - rc) * j / (len(rl) + 1.0), sdat))
    if bp.get("edge"):
        rings.append((R, bp["edge"]))
    for (r, sdat) in rings:
        sid = add_sec(sdat)
        if r >= R - 1.0:                                   # периферийное кольцо - по кромке стенки (без «зигзага» кромка <-> крыша)
            sel = list(top_sel)
        else:
            sel = [(i, a, x, y) for (i, x, y, rr, a) in roof if abs(rr - r) < tol]
        total += chain(sel, True, sid, 3 * size)
    ends = []                                              # концы радиальных балок у стенки: (номер элемента в elems, узел оболочки)
    if bp.get("radial") and bp.get("radial_count"):
        sid = add_sec(bp["radial"])
        n = int(bp["radial_count"])
        for k in range(n):
            th = math.radians(float(bp["first_angle_deg"]) + 360.0 * k / n)
            ct, st = math.cos(th), math.sin(th)
            sel = [(i, rr, x, y) for (i, x, y, rr, a) in roof if rc - tol <= rr <= R + 2 * size and abs(-x * st + y * ct) < tol and (x * ct + y * st) > 0]
            n0 = len(elems)
            total += chain(sel, False, sid, 3 * size)
            if len(elems) > n0:
                last = max(sel, key=lambda p: p[1])[0]
                for j in range(len(elems) - 1, n0 - 1, -1):
                    if last in elems[j][1:]:
                        ends.append((j, last))
                        break
    bsay(u"Балки: секций %d, элементов %d" % (len(secs), total))
    if not elems:
        return u""
    # конец радиальной балки - отдельный узел, связанный с оболочкой RBE3 (сила распределяется на узлы стенки и крыши в радиусе rs)
    slaves = []
    for j, nid in ends:
        q = md.NodeById(nid)
        p0 = (q.X, q.Y, q.Z)
        sl = [i for (i, c) in near if (c[0] - p0[0]) ** 2 + (c[1] - p0[1]) ** 2 + (c[2] - p0[2]) ** 2 <= rs * rs]
        slaves.append((j, nid, p0, sl))
    t = [u"/PREP7", u"*GET,etm,ETYP,0,NUM,MAX", u"et_b=etm+1", u"ET,et_b,188", u"*GET,e1,ELEM,0,NUM,MIN", u"*GET,matid,ELEM,e1,ATTR,MAT",
         u"*GET,nb0,NODE,0,NUM,MAXD"]
    for k, (j, nid, p0, sl) in enumerate(slaves, 1):
        t.append(u"N,nb0+%d,%r,%r,%r" % (k, p0[0], p0[1], p0[2]))
    for k, d in enumerate(secs):
        t += [u"SECTYPE,%d,BEAM,ASEC" % (951 + k), u"SECDATA,%r,%r,0,%r,0,%r,0,0,0,0,%r,%r" % (d["A"], d["Iyy"], d["Izz"], d["J"], d["D"], d["B"])]
    t += [u"TYPE,et_b", u"MAT,matid"]
    endmap = dict([(j, (nid, k)) for k, (j, nid, p0, sl) in enumerate(slaves, 1)])
    cur = None
    for j, (sid, a, b) in enumerate(elems):
        if sid != cur:
            t.append(u"SECNUM,%d" % sid)
            cur = sid
        if j in endmap:
            nid, k = endmap[j]
            a, b = [(u"nb0+%d" % k) if x == nid else (u"%d" % x) for x in (a, b)]
            t.append(u"E,%s,%s" % (a, b))
        else:
            t.append(u"E,%d,%d" % (a, b))
    for k, (j, nid, p0, sl) in enumerate(slaves, 1):
        t += [u"NSEL,NONE"] + node_ranges(sl) + [u"RBE3,nb0+%d,ALL,ALL" % k]
    t += [u"ALLSEL,ALL", u"/SOLU"]
    if slaves:
        bsay(u"Концы радиальных балок: %d, связь RBE3 с оболочкой в радиусе %.0f мм, узлов на конец %d..%d"
             % (len(slaves), rs, min([len(s[3]) for s in slaves]), max([len(s[3]) for s in slaves])))
    return u"\n".join(t)


def node_ranges(ids):
    """NSEL,A по номерам узлов, подряд идущие номера - одним диапазоном."""
    ids = sorted(set(ids))
    out, i = [], 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[j] + 1:
            j += 1
        out.append(u"NSEL,A,NODE,,%d,%d" % (ids[i], ids[j]) if j > i else u"NSEL,A,NODE,,%d" % ids[i])
        i = j + 1
    return out


def apdl_band():
    """Опорная полоса крыши (ширина band_width_mm от кромки стенки, толщина band_mm из parts.json): секция оболочки 984 у края крыши."""
    import math
    w, tb = parts.get(u"band_width_mm", 0.0), parts.get(u"band_mm", 0.0)
    if w <= 0 or tb <= parts.get(u"roof_mm", 0.0) or WALL_H <= 0:
        return u""
    H = WALL_H
    ax = {"X": 0, "Y": 1, "Z": 2}[(os.environ.get("ANSYS_REPORT_AXIS") or "Z").upper()]
    ia, ib = [i for i in (0, 1, 2) if i != ax]
    md = ExtAPI.DataModel.MeshDataByName("Global")
    nb = 360
    edge = [0.0] * nb                                      # радиус кромки стенки по углу (шаг 1°): стенка по замерам не круглая
    roof = []
    for nd in md.Nodes:
        c = (nd.X, nd.Y, nd.Z)
        if c[ax] >= H - 1.0:
            x, y = c[ia], c[ib]
            rr = math.sqrt(x * x + y * y)
            k = int((math.degrees(math.atan2(y, x)) + 180.0) * nb / 360.0) % nb
            roof.append((nd.Id, rr, k))
            if c[ax] <= H + 1.0:
                edge[k] = max(edge[k], rr)
    if max(edge) <= 0:
        return u""
    for k in range(nb):                                    # пустые ячейки - по ближайшей заполненной
        d = 1
        while edge[k] <= 0 and d < nb:
            edge[k] = max(edge[(k - d) % nb], edge[(k + d) % nb])
            d += 1
    sel = [i for (i, rr, k) in roof if edge[k] - rr <= w + 1.0]
    bsay(u"Опорная полоса крыши: %g x %g мм, узлов %d" % (w, tb, len(sel)))
    t = [u"/PREP7", u"*GET,e1,ELEM,0,NUM,MIN", u"*GET,matid,ELEM,e1,ATTR,MAT", u"SECTYPE,984,SHELL", u"SECDATA,%r,matid,0,3" % tb,
         u"ALLSEL,ALL", u"CMSEL,S,AR_ROOF,NODE", u"ESLN,S,1", u"NSEL,NONE"] + node_ranges(sel) + [u"ESLN,R,1", u"EMODIF,ALL,SECNUM,984", u"ALLSEL,ALL", u"/SOLU"]
    return u"\n".join(t)


def mesh_dents():
    """Сгущение сетки у вмятин (dents.json из пакета: центр и радиус сферы, мм): Sizing «сфера влияния» на грани стенки.
    ANSYS_REPORT_DENT_MESH_MM - размер элемента в зоне (100 по умолчанию, 0 - без сгущения). Сетка 200 мм занижает пик во вмятине на 7-19 %."""
    import json
    dsize = float(os.environ.get("ANSYS_REPORT_DENT_MESH_MM") or 100)
    dp = os.path.join(pkg, "dents.json")
    if dsize <= 0 or not os.path.exists(dp):
        return 0
    dents = json.loads(_rd(dp))
    ax = {"X": 0, "Y": 1, "Z": 2}[(os.environ.get("ANSYS_REPORT_AXIS") or "Z").upper()]
    fz = []
    for b in model.Geometry.GetChildren(DataModelObjectCategory.Body, True):
        for f in b.GetGeoBody().Faces:
            fz.append((f.Centroid[ax], f.Id))
    k_ = 1000.0 if WALL_H and max([abs(z) for z, i in fz]) < 0.05 * WALL_H else 1.0
    sel = ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
    sel.Ids = [i for z, i in fz if 0.002 * WALL_H < z * k_ < 0.998 * WALL_H]    # только грани стенки: сфера на всё тело портит картинки (днище многоугольником, «точки»)
    for k, d in enumerate(dents, 1):
        # узлы «стенка-крыша» и «стенка-днище» остаются на опорной сетке (800 мм хватает на переход 100 -> 200 мм): пик там от сетки не сходится (50/100/200 мм), а мембранные - да
        d["radius_mm"] = max(500.0, min(d["radius_mm"], min(WALL_H - d["z_mm"], d["z_mm"]) - 800.0))
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
        sz.ElementSize = Quantity(dsize, "mm")
    bsay(u"Сгущение сетки у вмятин: %d зон на %d гранях стенки, элемент %g мм, радиусы %s мм" % (len(dents), len(sel.Ids), dsize, u", ".join([u"%.0f" % d["radius_mm"] for d in dents])))
    return len(dents)


def mesh_annular_ring():
    """Кольцо окрайки снаружи стенки (узкая грань днища шириной ~200 мм): mapped-сетка. PrimeMesh на длинном узком кольце
    крупного резервуара (РВС-30000, окружность 143 м) сетит грань частично - «One or more faces failed to mesh», расчёт не идёт."""
    ax = {"X": 0, "Y": 1, "Z": 2}[(os.environ.get("ANSYS_REPORT_AXIS") or "Z").upper()]
    fz = []
    for b in model.Geometry.GetChildren(DataModelObjectCategory.Body, True):
        for f in b.GetGeoBody().Faces:
            fz.append((f.Centroid[ax], f.Area, f.Id))
    k_ = 1000.0 if WALL_H and max([abs(z) for z, a, i in fz]) < 0.05 * WALL_H else 1.0
    bot = [(a, i) for z, a, i in fz if abs(z * k_) < 0.002 * WALL_H]
    if len(bot) < 2:
        return 0
    amax = max([a for a, i in bot])
    ids = [i for a, i in bot if a < 0.2 * amax]
    if ids:
        sel = ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
        sel.Ids = ids
        fm = model.Mesh.AddFaceMeshing()
        fm.Name = u"AR сетка окрайки"
        fm.Location = sel
        bsay(u"Кольцо окрайки: mapped-сетка на %d гранях" % len(ids))
    return len(ids)


# --- сетка
try:
    size = float(os.environ.get("ANSYS_REPORT_MESH_MM") or 200)
    model.Mesh.ElementSize = Quantity(size, "mm")
    tmark(u"Сборка: построение сетки")
    try:
        mesh_dents()
    except Exception as e:
        bsay(u"Сгущение у вмятин не задано: %s" % e)
    ExtAPI.Application.Messages.Clear()
    model.Mesh.GenerateMesh()
    _merr = [m.DisplayString for m in ExtAPI.Application.Messages if str(m.Severity) == "Error" and "mesh" in m.DisplayString.lower()]
    if _merr:          # mapped-сетка окрайки - только при сбое: на РВС-10000 она не нужна и стоит +4 мин, на РВС-30000 без неё сетка не строится
        bsay(u"Сетка с ошибкой (%s) - mapped-сетка на кольце окрайки и повтор" % _merr[0][:80])
        tmark(u"Сборка: повтор сетки (mapped окрайка)")
        try:
            mesh_annular_ring()
        except Exception as e:
            bsay(u"Сетка окрайки не задана: %s" % e)
        model.Mesh.GenerateMesh()
    bsay(u"Сетка построена, размер элемента %g мм" % size)
except Exception as e:
    bsay(u"ОШИБКА сетки: %s" % e)
tmark(u"Сборка: APDL полосы и балок (поиск узлов)")
try:
    _bd = apdl_band()
    if _bd:
        EXTRA_APDL = (EXTRA_APDL + u"\n" if EXTRA_APDL else u"") + _bd
except Exception as e:
    bsay(u"Опорная полоса крыши не задана: %s" % e)
try:
    _bm = apdl_beams()
    if _bm:
        EXTRA_APDL = (EXTRA_APDL + u"\n" if EXTRA_APDL else u"") + _bm
        bsay(u"Балки каркаса крыши добавлены в расчёт")
except Exception as e:
    bsay(u"Балки не добавлены: %s" % e)


def apdl_material():
    """Сталь из «Данных для отчёта» (LOADS["model"]["material"]: E, ν, плотность) вместо Structural Steel - на все материалы модели
    (оболочки и балки из одной стали). Если задан вес крыши F (roof_force_n), элементы крыши и её каркаса (центр выше верха стенки)
    получают такой же материал без плотности: вес крыши прикладывается силой F к верхней кромке стенки (apply_loads.py), как в эталоне Т-001."""
    m = (_lns.get("LOADS") or {}).get("model") or {}
    mat = m.get("material") or {}
    t = [u"/PREP7", u"*GET,nmat_,MAT,0,NUM,MAX"]
    if mat:
        t.append(u"*DO,im_,1,nmat_")
        if mat.get("e_mpa"):
            t.append(u"  MP,EX,im_,%r" % float(mat["e_mpa"]))
        if mat.get("poisson") is not None:
            t.append(u"  MP,NUXY,im_,%r" % float(mat["poisson"]))
        if mat.get("density_kg_m3"):
            t.append(u"  MP,DENS,im_,%.6g" % (float(mat["density_kg_m3"]) * 1e-12))        # кг/м3 -> т/мм3 (единицы Н-мм-МПа)
        t.append(u"*ENDDO")
        bsay(u"Материал из данных заказчика: %s" % mat)
    if m.get("roof_force_n") and WALL_H > 0:
        ax = ("X", "Y", "Z")[{"X": 0, "Y": 1, "Z": 2}[(os.environ.get("ANSYS_REPORT_AXIS") or "Z").upper()]]
        t += [u"*GET,e1_,ELEM,0,NUM,MIN", u"*GET,mat1_,ELEM,e1_,ATTR,MAT", u"mroof_=nmat_+1",
              u"MPCOPY,,mat1_,mroof_", u"MPDELE,DENS,mroof_", u"MP,DENS,mroof_,0",
              u"ESEL,S,CENT,%s,%r,%r" % (ax, WALL_H - 1.0, WALL_H * 10.0), u"ESEL,U,ENAME,,154,156",
              u"*GET,ner_,ELEM,0,COUNT", u"*IF,ner_,GT,0,THEN", u"  EMODIF,ALL,MAT,mroof_", u"*ENDIF"]
        bsay(u"Вес крыши: силой F = %.1f Н на верхнюю кромку стенки, крыша и её каркас без плотности" % m["roof_force_n"])
    if len(t) == 2:
        return u""
    return u"\n".join(t + [u"ALLSEL,ALL", u"/SOLU"])


try:
    _bmat = apdl_material()
    if _bmat:
        EXTRA_APDL = (EXTRA_APDL + u"\n" if EXTRA_APDL else u"") + _bmat
except Exception as e:
    bsay(u"Материал/вес крыши не заданы: %s" % e)

# --- нагрузки
tmark(u"Сборка: нагрузки и расчётные случаи (apply_loads)")
os.environ["ANSYS_REPORT_LOADS"] = os.path.join(pkg, "loads_data.py")
os.environ["ANSYS_REPORT_REUSE_FIRST"] = "1"
try:
    exec(_rd(os.path.join(pkg, "apply_loads.py")))
except Exception as e:
    bsay(u"ОШИБКА наложения нагрузок: %s" % e)

# --- вид: ось Z вверх, изометрия сверху, показать всё
tmark(u"Сборка: вид и журнал")
try:
    from Ansys.ACT.Math import Vector3D
    cam = Graphics.Camera
    cam.UpVector = Vector3D(0, 0, 1)
    cam.ViewVector = Vector3D(-1.0, -0.8, -0.5)
    cam.SetFit()
    bsay(u"Вид: Z вверх")
except Exception as e:
    bsay(u"Вид (Z вверх) не установлен: %s" % e)

f = io.open(os.path.join(out, "log_build.txt"), "w", encoding="utf-8")
f.write(u"\n".join(blog))
f.close()
