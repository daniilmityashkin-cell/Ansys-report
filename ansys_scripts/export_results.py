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


def set_units():
    """Рисунки и таблицы в МПа и мм (единицы только в сеансе, проект не меняется)."""
    try:
        ExtAPI.Application.ActiveUnitSystem = MechanicalUnitSystem.StandardNMM
        log.append(u"единицы: Н, мм, МПа")
    except Exception as e:
        log.append(u"единицы не переключены (%s)" % e)


set_units()

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


def write(name, lines):
    f = io.open(os.path.join(out, name), "w", encoding="utf-8")
    f.write(u"\n".join(lines))
    f.close()

def fit_view(steep=False):
    # В фоновом режиме камера по умолчанию сильно приближена и стоит "на боку".
    # Вертикаль резервуара - ось X (гравитация по -X): ставим X "вверх", смотрим сбоку сверху, затем "показать всё".
    ok = False
    try:
        from Ansys.ACT.Math import Vector3D
        cam = Graphics.Camera
        up = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}[AXIS]
        v = (-1.2, -0.8, -0.5) if steep else (-0.5, -1, -0.6)     # steep: сверху, видна и внутренняя сторона стенки
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


def mpa(q):
    v = q.Value
    if str(q.Unit) == "Pa":
        v = v / 1e6
    return v

model = ExtAPI.DataModel.Project.Model
belts = {}
for b in model.Geometry.GetChildren(DataModelObjectCategory.Body, True):
    m = re.match(BELT_RE, b.Name)
    if m:
        belts[int(m.group(1))] = b.GetGeoBody().Id
if not belts:                          # пояса - грани одного тела (модель из пакета сайта): сортируем грани по высоте
    try:
        fl = []
        for asm in ExtAPI.DataModel.GeoData.Assemblies:
            for part in asm.Parts:
                for body in part.Bodies:
                    for f in body.Faces:
                        c = f.Centroid
                        fl.append((c[{"X": 0, "Y": 1, "Z": 2}[AXIS]], f.Id))
        fl.sort()
        for i, (vv, fid) in enumerate(fl):
            belts[i + 1] = fid
    except Exception as e:
        log.append(u"пояса-грани: %s" % e)
log.append(u"Найдено поясов: %d" % len(belts))

stab = [u"analysis,mode,k"]
modes = [u"analysis,type,mode,value,unit"]
summary = [u"analysis,result,max,min,unit"]
for a in model.Analyses:
    sol = a.Solution
    aname = a.Name.replace(" ", "_")
    try:                                   # расчёт не решён в проекте - при включённой опции решаем сейчас (проект не сохраняется)
        if os.environ.get("ANSYS_REPORT_SOLVE") == "1" and str(sol.Status) == "SolveRequired":
            log.append(u"%s: расчёт не решён, запускаю решение (может занять несколько минут)" % a.Name)
            sol.Solve(True)
            log.append(u"%s: после решения статус: %s" % (a.Name, sol.Status))
    except Exception as e:
        log.append(u"%s: ОШИБКА решения: %s" % (a.Name, e))
    try:                                   # в фоне результаты не вычислены, пока их не потребуют - вычисляем сразу
        sol.EvaluateAllResults()
    except Exception as e:
        log.append(u"%s: EvaluateAllResults: %s" % (a.Name, e))
    try:
        log.append(u"%s: статус решения: %s" % (a.Name, sol.Status))
    except Exception:
        pass
    # 1. картинки существующих результатов (формы потери устойчивости смотрим сверху)
    is_eigen = a.Name.startswith(EIGEN_PREFIX)
    for r in sol.Children:
        if r.Name.startswith("Solution Information"):
            continue
        try:
            r.Activate()
            if is_eigen:
                try:
                    Graphics.ViewOptions.ResultPreference.DeformationScaling = DeformationScaling.Auto
                except Exception:
                    pass
            fit_view(is_eigen)
            Graphics.ExportImage(os.path.join(out, "%s_%s.png" % (aname, r.Name.replace(" ", "_"))))
        except Exception as e:
            log.append(u"картинка %s/%s: %s" % (a.Name, r.Name, e))
    # 1a. полные поля по всей стенке (эквивалентные, мембранные, фибровые), единицы МПа
    if a.Name.startswith(STATIC_PREFIX):
        tmp = []
        try:
            eqf = sol.AddEquivalentStress(); eqf.Name = "AR Equivalent"
            mm = sol.AddMaximumPrincipalStress(); mm.Name = "AR Membrane"; mm.Position = type(mm.Position).Middle
            fbf = sol.AddMaximumPrincipalStress(); fbf.Name = "AR Fiber"
            tmp = [eqf, mm, fbf]
            sol.EvaluateAllResults()
            for r in tmp:
                try:
                    r.Activate()
                    fit_view()
                    Graphics.ExportImage(os.path.join(out, "%s_%s.png" % (aname, r.Name.replace(" ", "_"))))
                except Exception as e:
                    log.append(u"картинка %s/%s: %s" % (a.Name, r.Name, e))
        except Exception as e:
            log.append(u"%s: полные поля: %s" % (a.Name, e))
        for r in tmp:
            try:
                r.Delete()
            except Exception:
                pass
    # 1b. универсальная сводка: частоты мод и максимумы/минимумы существующих результатов
    for r in sol.Children:
        if r.Name.startswith("Solution Information"):
            continue
        try:
            tn = r.GetType().Name
            if tn == "TotalDeformation" and not a.Name.startswith(EIGEN_PREFIX) and "Modal" in str(a.AnalysisType):
                try:
                    f = r.ReportedFrequency
                    modes.append(u'"%s","%s",%s,%.6g,%s' % (a.Name, a.AnalysisType, r.Mode, f.Value, f.Unit))
                except Exception:
                    pass
            mx, mn = r.Maximum, r.Minimum
            summary.append(u'"%s","%s",%.6g,%.6g,%s' % (a.Name, r.Name, mx.Value, mn.Value, mx.Unit))
        except Exception:
            pass
    # 2. устойчивость: коэффициент запаса = ReportedFrequency у результатов Eigenvalue Buckling
    if a.Name.startswith(EIGEN_PREFIX):
        for r in sol.Children:
            if r.GetType().Name == "TotalDeformation":
                stab.append(u'"%s",%d,%.4f' % (a.Name, r.Mode, r.ReportedFrequency.Value))
    # 3. прочность: максимумы по поясам
    elif a.Name.startswith(STATIC_PREFIX):
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
            try:
                log.append(u"%s: статус решения: %s; папка: %s" % (a.Name, sol.Status, a.WorkingDir))
                try:
                    fl = [os.path.basename(x) for x in System.IO.Directory.GetFiles(a.WorkingDir)]
                    log.append(u"  файлов в папке: %d: %s" % (len(fl), u", ".join(fl[:15])))
                except Exception as e:
                    log.append(u"  папка недоступна: %s" % e)
            except Exception as e:
                log.append(u"%s: диагностика: %s" % (a.Name, e))
            sol.EvaluateAllResults()
            vals = [mpa(t[1].Maximum) for t in created]
            if not any(vals):
                # запасной путь: активировать каждый результат (заставляет Mechanical прочитать файл результатов)
                log.append(u"%s: после EvaluateAllResults значения нулевые, пробую Activate" % a.Name)
                for t in created:
                    for r in t[1:]:
                        try:
                            r.Activate()
                        except Exception as e:
                            log.append(u"  Activate/Evaluate: %s" % e)
                            break
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
if len(modes) > 1:
    write("modes.csv", modes)
if len(summary) > 1:
    write("results_summary.csv", summary)
write("log.txt", log)
print(u"\n".join(log))
print("Готово: " + out)
