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


def _rd(path, enc="utf-8"):
    """Читает файл целиком и сразу закрывает (IronPython не закрывает неявно: повторное чтение даёт «файл занят»)."""
    fh_ = io.open(path, encoding=enc)
    try:
        return fh_.read()
    finally:
        fh_.close()

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

def prep_results_view():
    """Вид результатов как в эталонном отчёте: сплошная цветовая заливка без линий сетки (иначе мелкая сетка закрывает цвета)."""
    for name, fn in ((u"ShowMesh", lambda: setattr(Graphics.ViewOptions, "ShowMesh", False)),
                     (u"ExtraModelDisplay", lambda: setattr(Graphics.ViewOptions.ResultPreference, "ExtraModelDisplay", ExtraModelDisplay.NoWireframe)),
                     (u"ShowEdges", lambda: setattr(Graphics.ViewOptions, "ShowEdges", False))):
        try:
            fn()
        except Exception as e:
            log.append(u"вид результатов: %s: %s" % (name, e))


def export_img(path):
    """Картинка результата в повышенном разрешении (для Word 12,5 см достаточно 2000x1300), запасной путь - обычный экспорт."""
    try:
        st = Ansys.Mechanical.Graphics.GraphicsImageExportSettings()
        st.CurrentGraphicsDisplay = False
        st.Resolution = GraphicsResolutionType.EnhancedResolution
        st.Width = 2000
        st.Height = 1300
        Graphics.ExportImage(path, GraphicsImageExportFormat.PNG, st)
    except Exception as e:
        log.append(u"картинка высокого разрешения не вышла (%s), обычный экспорт" % e)
        Graphics.ExportImage(path)


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


def _wall_faces_sorted():
    """Грани стенки снизу вверх: центр грани между отметками 0 и H (днище и окрайка у 0, крыша выше H исключаются).
    H берём из loads_data.py (ANSYS_REPORT_LOADS); GeoData отдаёт метры или мм."""
    H = None
    lp = os.environ.get("ANSYS_REPORT_LOADS")
    if lp and os.path.exists(lp):
        ns_ = {}
        exec(_rd(lp), ns_)
        H = ns_["LOADS"]["geometry"]["wall_height_mm"]
    fl_ = []
    ax_ = {"X": 0, "Y": 1, "Z": 2}[AXIS]
    for asm in ExtAPI.DataModel.GeoData.Assemblies:
        for part in asm.Parts:
            for body in part.Bodies:
                for f in body.Faces:
                    fl_.append((f.Centroid[ax_], f.Id))
    if H:
        mx_ = 0.0
        for v_, i_ in fl_:
            if abs(v_) > mx_:
                mx_ = abs(v_)
        k = 1000.0 if mx_ < 0.05 * H else 1.0
        keep_ = []
        for v_, i_ in fl_:
            if 0.002 * H < v_ * k < 0.998 * H:
                keep_.append((v_, i_))
        fl_ = keep_
    fl_.sort()
    return fl_

model = ExtAPI.DataModel.Project.Model
prep_results_view()
belts = {}
for b in model.Geometry.GetChildren(DataModelObjectCategory.Body, True):
    m = re.match(BELT_RE, b.Name)
    if m:
        belts[int(m.group(1))] = b.GetGeoBody().Id
if not belts:                          # пояса - грани одного тела (модель из пакета сайта): сортируем грани стенки по высоте
    try:
        for i, (vv, fid) in enumerate(_wall_faces_sorted()):
            belts[i + 1] = fid
    except Exception as e:
        log.append(u"пояса-грани: %s" % e)
log.append(u"Найдено поясов: %d" % len(belts))

stab = [u"analysis,mode,k"]
modes = [u"analysis,type,mode,value,unit"]
summary = [u"analysis,result,max,min,unit"]
for a in model.Analyses:
    sol = a.Solution
    aname = re.sub(u'[<>:"/\\\\|?*,;()\\s]', u"_", a.Name)                    # без символов, недопустимых в именах файлов Windows
    try:                                   # расчёт не решён в проекте - при включённой опции решаем сейчас (проект не сохраняется)
        if os.environ.get("ANSYS_REPORT_SOLVE") == "1" and str(sol.Status) == "SolveRequired":
            log.append(u"%s: расчёт не решён, запускаю решение (может занять несколько минут)" % a.Name)
            sol.Solve(True)
            log.append(u"%s: после решения статус: %s" % (a.Name, sol.Status))
            if str(sol.Status) == "SolveRequired" and a.Name.startswith(STATIC_PREFIX):       # нелинейный расчёт не сошёлся - решаем линейно
                try:
                    if a.AnalysisSettings.LargeDeflection:
                        a.AnalysisSettings.LargeDeflection = False
                        log.append(u"%s: нелинейный расчёт не решён, повторяю линейный" % a.Name)
                        sol.Solve(True)
                        log.append(u"%s: после линейного решения статус: %s" % (a.Name, sol.Status))
                except Exception as e:
                    log.append(u"  линейный повтор: %s" % e)
            if str(sol.Status) == "SolveRequired":          # причина - в сообщениях Mechanical и в solve.out
                try:
                    for msg in ExtAPI.Application.Messages:
                        log.append(u"  сообщение [%s]: %s" % (msg.Severity, msg.DisplayString))
                except Exception as e:
                    log.append(u"  сообщения: %s" % e)
                try:
                    wd = sol.WorkingDir
                    log.append(u"  папка решателя: %s" % wd)
                    for fn in (u"solve.out", u"file0.err", u"file.err"):
                        fp = os.path.join(wd, fn)
                        if os.path.exists(fp):
                            lines = open(fp).read().splitlines()[-40:]
                            log.append(u"  --- %s (хвост) ---" % fn)
                            log.extend([unicode(x, "utf-8", "replace") for x in lines])
                except Exception as e:
                    log.append(u"  файлы решателя: %s" % e)
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
        if r.Name.startswith("Solution Information") or r.Name.startswith("Equivalent Stress ("):
            continue                                      # картинки результатов по отдельным поясам (12 штук на случай) в отчёт не нужны
        try:
            r.Activate()
            if is_eigen:
                try:
                    Graphics.ViewOptions.ResultPreference.DeformationScaling = DeformationScaling.Auto
                except Exception:
                    pass
            fit_view(is_eigen)
            export_img(os.path.join(out, "%s_%s.png" % (aname, re.sub(u'[<>:"/\\\\|?*,;()\\s]', u"_", r.Name))))
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
                    export_img(os.path.join(out, "%s_%s.png" % (aname, re.sub(u'[<>:"/\\\\|?*,;()\\s]', u"_", r.Name))))
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
                kval = None
                for attr in ("ReportedLoadMultiplier", "ReportedFrequency"):       # у Eigenvalue Buckling - множитель нагрузки (запас устойчивости)
                    try:
                        v = getattr(r, attr)
                        kval = v.Value if hasattr(v, "Value") else float(v)
                        if kval:
                            break
                    except Exception as e:
                        log.append(u"  %s/%s: %s: %s" % (a.Name, r.Name, attr, e))
                log.append(u"  устойчивость %s, форма %s: k = %s" % (a.Name, r.Mode, kval))
                stab.append(u'"%s",%d,%.4f' % (a.Name, r.Mode, kval or 0.0))
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
