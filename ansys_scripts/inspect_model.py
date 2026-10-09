# -*- coding: utf-8 -*-
# Диагностика модели для Ansys Mechanical 2026 R1 (IronPython). Ничего не меняет в проекте.
# Запуск: Mechanical -> Automation -> Scripting -> открыть/вставить файл -> Run.
# Результат: файл model_info.txt на Рабочем столе. Пришлите его содержимое.
import os, io
from collections import OrderedDict

out = os.path.join(os.path.expanduser("~"), "Desktop", "model_info.txt")
L = []

def p(s=u""):
    if not isinstance(s, basestring):
        s = unicode(s)
    L.append(s)

def safe(f, default=u"?"):
    try:
        return f()
    except Exception as e:
        return default

model = ExtAPI.DataModel.Project.Model
p(u"== Модель ==")
p(u"Версия: %s" % safe(lambda: ExtAPI.Application.Version))

p(u"\n== Тела геометрии (группы по типу и имени) ==")
bodies = model.Geometry.GetChildren(DataModelObjectCategory.Body, True)
p(u"Всего тел: %d" % len(bodies))
groups = OrderedDict()
for b in bodies:
    key = (str(safe(lambda: b.DimensionType)), b.Name)
    groups[key] = groups.get(key, 0) + 1
for (dim, name), n in groups.items():
    p(u"  %s | %s | %d шт." % (dim, name, n))

p(u"\n== Не-балочные тела подробно (первые 60) ==")
k = 0
for b in bodies:
    if str(safe(lambda: b.DimensionType)) == "Line" or b.Name.startswith("Beam"):
        continue
    k += 1
    if k > 60:
        break
    p(u"  %s | dim=%s | thickness=%s | material=%s | suppressed=%s" % (
        b.Name, safe(lambda: b.DimensionType), safe(lambda: b.Thickness),
        safe(lambda: b.Material), safe(lambda: b.Suppressed)))

p(u"\n== Named Selections ==")
for ns in safe(lambda: model.NamedSelections.Children, []):
    p(u"  %s" % ns.Name)

p(u"\n== Анализы ==")
for a in model.Analyses:
    p(u"\n-- %s (%s)" % (a.Name, safe(lambda: a.AnalysisType)))
    for c in a.Children:
        p(u"   [%s] %s" % (safe(lambda: c.GetType().Name), c.Name))
        if c.Name.startswith("Solution"):
            for r in c.Children:
                mx = safe(lambda: r.Maximum, u"-")
                p(u"        результат: %s | %s | max=%s" % (r.Name, safe(lambda: r.GetType().Name), mx))

with io.open(out, "w", encoding="utf-8") as f:
    f.write(u"\n".join(L))
print("Готово: " + out)
