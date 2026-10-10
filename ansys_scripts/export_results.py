# -*- coding: utf-8 -*-
# Выгрузка результатов из Ansys Mechanical 2026 R1 (IronPython) для генератора отчётов.
# Запуск: Automation -> Scripting -> вкладка "+" -> вставить -> Run.
# Результат в папке %TEMP%\ansys_report_out:
#   <анализ>_belts.csv   belt,fiber,equivalent,membrane  (МПа, максимум по поясам p1..p12)
#   stability.csv        analysis,mode,k                 (коэффициенты запаса устойчивости)
#   *.png                картинки существующих результатов
#   log.txt              что получилось / ошибки
# Скрипт временно добавляет результаты по поясам и сразу удаляет их. Проект после запуска не сохраняйте.
import os, io, re
import System

out = os.environ.get("ANSYS_REPORT_OUT") or os.path.join(os.environ["TEMP"], "ansys_report_out")
System.IO.Directory.CreateDirectory(out)
log = []

def write(name, lines):
    f = io.open(os.path.join(out, name), "w", encoding="utf-8")
    f.write(u"\n".join(lines))
    f.close()

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


def mpa(q):
    v = q.Value
    if str(q.Unit) == "Pa":
        v = v / 1e6
    return v

model = ExtAPI.DataModel.Project.Model
belts = {}
for b in model.Geometry.GetChildren(DataModelObjectCategory.Body, True):
    m = re.match(r"^p\s*(\d+)$", b.Name)
    if m:
        belts[int(m.group(1))] = b.GetGeoBody().Id
log.append(u"Найдено поясов: %d" % len(belts))

stab = [u"analysis,mode,k"]
for a in model.Analyses:
    sol = a.Solution
    aname = a.Name.replace(" ", "_")
    # 1. картинки существующих результатов
    for r in sol.Children:
        if r.Name.startswith("Solution Information"):
            continue
        try:
            r.Activate()
            fit_view()
            Graphics.ExportImage(os.path.join(out, "%s_%s.png" % (aname, r.Name.replace(" ", "_"))))
        except Exception as e:
            log.append(u"картинка %s/%s: %s" % (a.Name, r.Name, e))
    # 2. устойчивость: коэффициент запаса = ReportedFrequency у результатов Eigenvalue Buckling
    if a.Name.startswith("Eigenvalue"):
        for r in sol.Children:
            if r.GetType().Name == "TotalDeformation":
                stab.append(u"%s,%d,%.4f" % (a.Name, r.Mode, r.ReportedFrequency.Value))
    # 3. прочность: максимумы по поясам
    elif a.Name.startswith("Static"):
        created = []
        rows = {}
        try:
            for i in sorted(belts):
                sel = ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
                sel.Ids = [belts[i]]
                eq = sol.AddEquivalentStress()
                eq.Location = sel
                fb = sol.AddMaximumPrincipalStress()
                fb.Location = sel
                mem = sol.AddMaximumPrincipalStress()
                mem.Location = sel
                mem.Position = type(mem.Position).Middle
                created.append((i, eq, fb, mem))
            sol.EvaluateAllResults()
            lines = [u"belt,fiber,equivalent,membrane"]
            for i, eq, fb, mem in created:
                lines.append(u"%d,%.2f,%.2f,%.2f" % (i, mpa(fb.Maximum), mpa(eq.Maximum), mpa(mem.Maximum)))
            write("%s_belts.csv" % aname, lines)
            log.append(u"%s: выгружено %d поясов" % (a.Name, len(created)))
        except Exception as e:
            log.append(u"%s: ОШИБКА %s" % (a.Name, e))
        for t in created:
            for r in t[1:]:
                r.Delete()

write("stability.csv", stab)
write("log.txt", log)
print(u"\n".join(log))
print("Готово: " + out)
