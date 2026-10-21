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
        for key in (u"disc_mm", u"annular_mm", u"roof_mm"):
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
    t += [u"*DIM,zlo,ARRAY,%d" % len(zones), u"*DIM,zhi,ARRAY,%d" % len(zones)]
    for k, (lo, hi, th) in enumerate(zones, 1):
        t += [u"zlo(%d)=%r" % (k, lo - 0.01), u"zhi(%d)=%r" % (k, hi + 0.01 if k == len(zones) else hi)]
    ax = ("X", "Y", "Z")[{"X": 0, "Y": 1, "Z": 2}[(os.environ.get("ANSYS_REPORT_AXIS") or "Z").upper()]]
    t += [u"ALLSEL,ALL", u"CMSEL,S,AR_WALL,NODE", u"ESLN,S,1", u"*GET,emax,ELEM,0,NUM,MAX", u"*DO,ee,1,emax", u"*IF,ESEL(ee),EQ,1,THEN",
          u"  *GET,zc,ELEM,ee,CENT,%s" % ax, u"  *DO,kk,1,%d" % len(zones),
          u"    *IF,zc,GE,zlo(kk),AND,zc,LT,zhi(kk),THEN", u"      EMODIF,ee,SECNUM,900+kk", u"    *ENDIF", u"  *ENDDO", u"*ENDIF", u"*ENDDO",
          u"ALLSEL,ALL", u"/SOLU"]
    return u"\n".join(t)

EXTRA_APDL = apdl_thickness()                       # apply_loads.py добавляет этот блок в каждый расчётный случай

# --- сетка
try:
    size = float(os.environ.get("ANSYS_REPORT_MESH_MM") or 150)
    model.Mesh.ElementSize = Quantity(size, "mm")
    model.Mesh.GenerateMesh()
    bsay(u"Сетка построена, размер элемента %g мм" % size)
except Exception as e:
    bsay(u"ОШИБКА сетки: %s" % e)

# --- нагрузки
os.environ["ANSYS_REPORT_LOADS"] = os.path.join(pkg, "loads_data.py")
os.environ["ANSYS_REPORT_REUSE_FIRST"] = "1"
try:
    exec(_rd(os.path.join(pkg, "apply_loads.py")))
except Exception as e:
    bsay(u"ОШИБКА наложения нагрузок: %s" % e)

# --- вид: ось Z вверх, изометрия сверху, показать всё
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
