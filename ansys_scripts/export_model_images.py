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


def snap(obj, name, hires=False):
    try:
        obj.Activate()
        fit_view()
        export_png(os.path.join(out, name + ".png"), hires)
        log.append(u"ok: " + name)
    except Exception as e:
        log.append(u"ОШИБКА %s: %s" % (name, e))

snap(model.Geometry, "fig01_general")
snap(model.Mesh, "fig02_mesh_wall_bottom", True)
snap(model.Mesh, "fig03_mesh_wall_roof", True)
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
