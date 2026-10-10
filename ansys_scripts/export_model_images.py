# -*- coding: utf-8 -*-
# Картинки модели для отчёта: общий вид, сетка, нагрузки, гидростатика.
# Запуск как export_results.py (Automation -> Scripting -> "+" -> вставить -> Run).
# Файлы сохраняются в %TEMP%\ansys_report_out под именами, которые ищет генератор отчёта.
import os, io
import System

out = os.environ.get("ANSYS_REPORT_OUT") or os.path.join(os.environ["TEMP"], "ansys_report_out")
System.IO.Directory.CreateDirectory(out)
log = []
model = ExtAPI.DataModel.Project.Model


def fit_view():
    # В фоновом режиме камера по умолчанию сильно приближена и стоит "на боку".
    # Вертикаль резервуара - ось X (гравитация по -X): ставим X "вверх", смотрим сбоку сверху, затем "показать всё".
    ok = False
    try:
        from Ansys.ACT.Math import Vector3D
        cam = Graphics.Camera
        cam.UpVector = Vector3D(1, 0, 0)
        cam.ViewVector = Vector3D(-0.5, -1, -0.6)
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

def tank_dims():
    """Высота (по X) и радиус стенки по узлам сетки, в метрах. None - если определить не удалось."""
    try:
        md = ExtAPI.DataModel.MeshDataByName("Global")
        xs, rs = [], []
        for n in md.Nodes:
            xs.append(n.X)
            rs.append((n.Y * n.Y + n.Z * n.Z) ** 0.5)
        return min(xs), max(xs), max(rs)
    except Exception as e:
        log.append(u"размеры резервуара не определены: %s" % e)
        return None


def zoom_to(x, radius, scene_height, log_name=""):
    """Навести камеру на точку стенки на высоте x (ближайшую к камере) и приблизить."""
    k = (1.0 + 0.36) ** 0.5
    pt = (x, radius * 1.0 / k, radius * 0.6 / k)
    cam = Graphics.Camera
    errs = []
    for mod, cls in (("Ansys.ACT.Math", "Vector3D"), ("Ansys.ACT.Interfaces.Common", "Point3D"),
                     ("System.Windows.Media.Media3D", "Point3D")):
        try:
            if mod.startswith("System.Windows"):
                import clr
                clr.AddReference("PresentationCore")
            m = __import__(mod, fromlist=[cls])
            cam.FocalPoint = getattr(m, cls)(pt[0], pt[1], pt[2])
            cam.SceneHeight = scene_height
            log.append(u"приближение %s: %s.%s" % (log_name, mod, cls))
            return
        except Exception as e:
            errs.append(u"%s.%s: %s" % (mod, cls, e))
    raise Exception(u"; ".join(errs))


def snap(obj, name, focus=None):
    try:
        obj.Activate()
        fit_view()
        if focus:
            try:
                zoom_to(focus[0], focus[1], focus[2], name)
            except Exception as e:
                log.append(u"приближение %s не вышло: %s" % (name, e))
        Graphics.ExportImage(os.path.join(out, name + ".png"))
        log.append(u"ok: " + name)
    except Exception as e:
        log.append(u"ОШИБКА %s: %s" % (name, e))

dims = tank_dims()
if dims:
    xmin, xmax, rad = dims
    bottom = (xmin + 0.6, rad, 3.5)      # нижний край стенки у днища
    top = (xmax - 0.6, rad, 3.5)         # верхний край стенки у кровли
else:
    bottom = top = None
snap(model.Geometry, "fig01_general")
snap(model.Mesh, "fig02_mesh_wall_bottom", bottom)
snap(model.Mesh, "fig03_mesh_wall_roof", top)
for a in model.Analyses:
    if a.Name.startswith("Static"):
        for c in a.Children:
            if c.Name == "Hydrostatic Pressure":
                snap(c, "fig05_hydrostatic")
            if c.Name == u"Fкр":
                snap(c, "fig04_loads")
        break

f = io.open(os.path.join(out, "log_images.txt"), "w", encoding="utf-8")
f.write(u"\n".join(log))
f.close()
print(u"\n".join(log))
