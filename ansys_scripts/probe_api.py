# -*- coding: utf-8 -*-
# Проверка совместимости: какие вызовы Mechanical, которыми пользуется ANSYS REPORT, есть в этой версии Ansys (IronPython).
# Ничего не меняет в проекте заказчика: работает на пустой модели. Результат: probe_api.txt в папке ANSYS_REPORT_OUT.
import io
import os
import sys
import traceback

lines = []


def say(t):
    lines.append(t)


def chk(label, expr, ns):
    """Вычисляет выражение; OK или причина. Обязательные вызовы (REQ) важнее косметических (OPT)."""
    try:
        v = eval(expr, ns)
        say(u"OK   %-62s" % label)
        return v
    except Exception as e:
        say(u"НЕТ  %-62s %s" % (label, str(e)[:110]))
        return None


ns = {}
try:
    ns.update(globals())
except Exception:
    pass
say(u"Python: %s" % sys.version.split("\n")[0])
for label, expr in ((u"Версия приложения", "str(ExtAPI.Application.Version)"), (u"Единицы: ActiveUnitSystem", "str(ExtAPI.Application.ActiveUnitSystem)")):
    try:
        say(u"%s: %s" % (label, eval(expr, ns)))
    except Exception as e:
        say(u"%s: НЕТ (%s)" % (label, str(e)[:80]))

say(u"")
say(u"--- Обязательные (без них расчёт не построится) ---")
M = chk(u"ExtAPI.DataModel.Project.Model", "ExtAPI.DataModel.Project.Model", ns)
ns["M"] = M
if M is not None:
    for label, expr in ((u"Model.AddStaticStructuralAnalysis", "M.AddStaticStructuralAnalysis"), (u"Model.AddEigenvalueBucklingAnalysis", "M.AddEigenvalueBucklingAnalysis"),
                        (u"Model.AddNamedSelection", "M.AddNamedSelection"), (u"Model.AddCoordinateSystem", "M.AddCoordinateSystem"), (u"Model.Mesh", "M.Mesh"),
                        (u"Mesh.AddSizing", "M.Mesh.AddSizing"), (u"Mesh.AddFaceMeshing", "M.Mesh.AddFaceMeshing"), (u"Mesh.GenerateMesh", "M.Mesh.GenerateMesh"),
                        (u"Mesh.ElementSize", "M.Mesh.ElementSize"), (u"Model.Geometry", "M.Geometry")):
        chk(label, expr, ns)
for label, expr in ((u"ExtAPI.DataModel.GeoData.Assemblies", "ExtAPI.DataModel.GeoData.Assemblies"), (u"ExtAPI.DataModel.MeshDataByName", "ExtAPI.DataModel.MeshDataByName"),
                    (u"SelectionManager.CreateSelectionInfo", "ExtAPI.SelectionManager.CreateSelectionInfo"), (u"SelectionTypeEnum.GeometryEntities", "SelectionTypeEnum.GeometryEntities"),
                    (u"SizingType.SphereOfInfluence", "SizingType.SphereOfInfluence"), (u"AutomaticTimeStepping.On", "AutomaticTimeStepping.On"),
                    (u"CoordinateSystemAlignmentType.Fixed", "CoordinateSystemAlignmentType.Fixed"), (u"Quantity", "Quantity(1, 'mm')"), (u"Application.Messages", "ExtAPI.Application.Messages")):
    chk(label, expr, ns)

say(u"")
say(u"--- Анализы (создаются на пустой модели) ---")
st = bk = None
try:
    st = M.AddStaticStructuralAnalysis()
    say(u"OK   создан Static Structural")
except Exception as e:
    say(u"НЕТ  создание Static Structural: %s" % str(e)[:110])
if st is not None:
    ns["st"] = st
    for label, expr in ((u"Static.AnalysisSettings.LargeDeflection", "st.AnalysisSettings.LargeDeflection"), (u"Static.AnalysisSettings.AutomaticTimeStepping", "st.AnalysisSettings.AutomaticTimeStepping"),
                        (u"Static.AddFixedSupport", "st.AddFixedSupport"), (u"Static.Solution", "st.Solution"), (u"Solution.AddEquivalentStress", "st.Solution.AddEquivalentStress"),
                        (u"Solution.AddMaximumPrincipalStress", "st.Solution.AddMaximumPrincipalStress"), (u"Solution.AddTotalDeformation", "st.Solution.AddTotalDeformation"),
                        (u"Solution.Solve", "st.Solution.Solve"), (u"Solution.Status", "st.Solution.Status")):
        chk(label, expr, ns)
    try:
        st.AddCommandSnippet()
        say(u"OK   Static.AddCommandSnippet()")
    except Exception as e:
        say(u"НЕТ  Static.AddCommandSnippet(): %s" % str(e)[:110])
try:
    bk = M.AddEigenvalueBucklingAnalysis()
    say(u"OK   создан Eigenvalue Buckling")
except Exception as e:
    say(u"НЕТ  создание Eigenvalue Buckling: %s" % str(e)[:110])
if bk is not None:
    ns["bk"] = bk
    for label, expr in ((u"Buckling.AnalysisSettings.MaximumModesToFind", "bk.AnalysisSettings.MaximumModesToFind"), (u"Buckling.Solution", "bk.Solution")):
        chk(label, expr, ns)
    for attr in (u"PreStressICEnvironment", u"PreStressEnvironment"):
        try:
            icd = getattr(bk, "InitialConditions", None)
            found = False
            for src in (bk, getattr(bk, "InitialCondition", None), icd):
                if src is not None and hasattr(src, attr):
                    found = True
            say(u"%s  привязка предварительного нагружения: %s" % (u"OK  " if found else u"НЕТ ", attr))
        except Exception as e:
            say(u"НЕТ  %s: %s" % (attr, str(e)[:80]))
    for attr in (u"IncludeNegativeLoadMultiplier",):
        try:
            say(u"%s  Buckling.AnalysisSettings.%s" % (u"OK  " if hasattr(bk.AnalysisSettings, attr) else u"НЕТ ", attr))
        except Exception as e:
            say(u"НЕТ  %s: %s" % (attr, str(e)[:80]))

say(u"")
say(u"--- Картинки и вид (косметика: при отсутствии пропускаются) ---")
for label, expr in ((u"Graphics.ExportImage", "Graphics.ExportImage"), (u"Graphics.Camera.SetSpecificViewOrientation", "Graphics.Camera.SetSpecificViewOrientation"),
                    (u"ViewOrientationType.Iso", "ViewOrientationType.Iso"), (u"GraphicsResolutionType.EnhancedResolution", "GraphicsResolutionType.EnhancedResolution"),
                    (u"Ansys.Mechanical.Graphics.GraphicsImageExportSettings", "Ansys.Mechanical.Graphics.GraphicsImageExportSettings"),
                    (u"Graphics.ViewOptions.ShowMesh", "Graphics.ViewOptions.ShowMesh"), (u"ViewOptions.ResultPreference.ExtraModelDisplay", "Graphics.ViewOptions.ResultPreference.ExtraModelDisplay"),
                    (u"ViewOptions.ResultPreference.DeformationScaling", "Graphics.ViewOptions.ResultPreference.DeformationScaling"),
                    (u"Enums.ExtraModelDisplay.NoWireframe", "Ansys.Mechanical.DataModel.Enums.ExtraModelDisplay.NoWireframe")):
    chk(label, expr, ns)

missing = [l for l in lines if l.startswith(u"НЕТ")]
say(u"")
say(u"Итого: не найдено %d вызовов из проверенных." % len(missing))
try:
    out = os.environ.get("ANSYS_REPORT_OUT") or os.environ.get("TEMP") or "."
    f = io.open(os.path.join(out, "probe_api.txt"), "w", encoding="utf-8")
    f.write(u"\n".join(lines) + u"\n")
    f.close()
except Exception:
    traceback.print_exc()
