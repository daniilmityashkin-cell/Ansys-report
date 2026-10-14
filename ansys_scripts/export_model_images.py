# -*- coding: utf-8 -*-
# Картинки модели для отчёта: общий вид, сетка, нагрузки, гидростатика.
# Запуск как export_results.py (Automation -> Scripting -> "+" -> вставить -> Run).
# Файлы сохраняются в %TEMP%\ansys_report_out под именами, которые ищет генератор отчёта.
import os, io
import System

out = os.environ.get("ANSYS_REPORT_OUT") or os.path.join(os.environ["TEMP"], "ansys_report_out")
System.IO.Directory.CreateDirectory(out)
log = []

BELT_RE = os.environ.get("ANSYS_REPORT_BELT_REGEX") or r"^p\s*(\d+)$"
AXIS = (os.environ.get("ANSYS_REPORT_AXIS") or "X").upper()
STATIC_PREFIX = os.environ.get("ANSYS_REPORT_STATIC") or "Static"
EIGEN_PREFIX = os.environ.get("ANSYS_REPORT_EIGEN") or "Eigenvalue"


def vc(x, y, z):
    """Координаты узла -> (вертикаль, a, b): вертикаль резервуара приводится к «X» отчёта."""
    if AXIS == "Y":
        return (y, z, x)
    if AXIS == "Z":
        return (z, x, y)
    return (x, y, z)

model = ExtAPI.DataModel.Project.Model

try:                        # рисунки и легенды в МПа и мм (только в сеансе, проект не меняется)
    ExtAPI.Application.ActiveUnitSystem = MechanicalUnitSystem.StandardNMM
    log.append(u"единицы: Н, мм, МПа")
except Exception as e:
    log.append(u"единицы не переключены (%s)" % e)


def fit_view(steep=0):
    # В фоновом режиме камера по умолчанию сильно приближена и стоит "на боку".
    # Вертикаль резервуара - ось X (гравитация по -X): ставим X "вверх", смотрим сбоку сверху, затем "показать всё".
    ok = False
    try:
        from Ansys.ACT.Math import Vector3D
        cam = Graphics.Camera
        up = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}[AXIS]
        v = {0: (-0.5, -1, -0.6), 1: (-1.0, -0.8, -0.5), 2: (-1.4, -0.4, -0.3)}[steep]   # 1-2: сверху, видна внутренняя сторона стенки
        view = {"X": v, "Y": (v[2], v[0], v[1]), "Z": (v[1], v[2], v[0])}[AXIS]
        cam.UpVector = Vector3D(up[0], up[1], up[2])
        cam.ViewVector = Vector3D(view[0], view[1], view[2])
        ok = True
    except Exception:
        pass
    if not ok:
        try:
            Graphics.Camera.SetSpecificViewOrientation(ViewOrientationType.Iso)
        except Exception:
            pass
    try:
        Graphics.Camera.SetFit()
    except Exception:
        pass

def export_png(path, hires=False):
    """Экспорт картинки. hires - крупный снимок 4000x2500 (из него программа вырезает фрагменты сетки)."""
    if hires:
        try:
            st = Ansys.Mechanical.Graphics.GraphicsImageExportSettings()
            st.CurrentGraphicsDisplay = False
            st.Resolution = GraphicsResolutionType.EnhancedResolution
            st.Width = 4000
            st.Height = 2500
            Graphics.ExportImage(path, GraphicsImageExportFormat.PNG, st)
            return
        except Exception as e:
            log.append(u"снимок высокого разрешения не вышел (%s), делаю обычный" % e)
    Graphics.ExportImage(path)


def snap(obj, name, hires=False, steep=0):
    """obj - один объект дерева или список объектов (показываются вместе)."""
    try:
        if isinstance(obj, list):
            Tree.Activate(obj)
        else:
            obj.Activate()
        fit_view(steep)
        export_png(os.path.join(out, name + ".png"), hires)
        log.append(u"ok: " + name)
    except Exception as e:
        log.append(u"ОШИБКА %s: %s" % (name, e))

snap(model.Geometry, "fig01_general")
snap(model.Mesh, "fig02_mesh_wall_bottom", True)
snap(model.Mesh, "fig03_mesh_wall_roof", True)
SKIP_TYPES = ("InitialCondition", "ANSYSAnalysisSettings", "Solution", "SolutionInformation")
for a in model.Analyses:
    if a.Name.startswith(STATIC_PREFIX):
        loads, hydro = [], None
        for c in a.Children:
            tn = c.GetType().Name
            if tn in SKIP_TYPES:
                continue
            try:
                if str(c.Suppressed) == "True":
                    continue
            except Exception:
                pass
            loads.append(c)
            if tn == "HydrostaticPressure" and hydro is None:
                hydro = c
        log.append(u"нагрузок и закреплений: %d" % len(loads))
        if loads:
            snap(loads, "fig04_loads", False, 1)        # все нагрузки вместе, вид сверху
            if log[-1].startswith(u"ОШИБКА"):
                snap(loads[0], "fig04_loads")             # запасной путь: первая нагрузка
        if hydro is not None:
            snap(hydro, "fig05_hydrostatic", False, 2)  # внутренняя сторона стенки, где давление
        break

f = io.open(os.path.join(out, "log_images.txt"), "w", encoding="utf-8")
f.write(u"\n".join(log))
f.close()
print(u"\n".join(log))
