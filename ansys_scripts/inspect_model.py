# -*- coding: utf-8 -*-
# Диагностика модели для Ansys Mechanical 2026 R1 (IronPython). Ничего не меняет в проекте.
# Запуск: Automation -> Scripting -> вставить -> Run (зелёный треугольник).
# Результат: файл model_info.txt на Рабочем столе.
import os, io

out = os.path.join(os.path.expanduser("~"), "Desktop", "model_info.txt")
L = []

def p(s=u""):
    if not isinstance(s, basestring):
        s = unicode(s)
    L.append(s)

def g(obj, name, default=u"?"):
    # getattr без исключений наружу
    return getattr(obj, name, default)

def tname(obj):
    t = getattr(obj, "GetType", None)
    return t().Name if t else u"?"

model = ExtAPI.DataModel.Project.Model

p(u"== Тела геометрии (группы по типу и имени) ==")
bodies = list(model.Geometry.GetChildren(DataModelObjectCategory.Body, True))
p(u"Всего тел: %d" % len(bodies))
groups = {}
order = []
for b in bodies:
    key = (unicode(g(b, "DimensionType")), b.Name)
    if key not in groups:
        groups[key] = 0
        order.append(key)
    groups[key] += 1
for key in order:
    p(u"  %s | %s | %d шт." % (key[0], key[1], groups[key]))

p(u"\n== Не-балочные тела подробно ==")
for b in bodies:
    if b.Name.startswith("Beam"):
        continue
    p(u"  %s | dim=%s | thickness=%s | material=%s | suppressed=%s" % (
        b.Name, g(b, "DimensionType"), g(b, "Thickness"), g(b, "Material"), g(b, "Suppressed")))

p(u"\n== Named Selections ==")
ns = g(model, "NamedSelections", None)
if ns is not None:
    for c in ns.Children:
        p(u"  %s" % c.Name)

p(u"\n== Анализы ==")
shown = False
for a in model.Analyses:
    p(u"\n-- %s | %s" % (a.Name, g(a, "AnalysisType")))
    for c in a.Children:
        p(u"   [%s] %s" % (tname(c), c.Name))
        if c.Name.startswith("Solution"):
            for r in c.Children:
                p(u"        результат: %s | %s | max=%s" % (r.Name, tname(r), g(r, "Maximum", u"-")))
                if not shown:
                    shown = True
                    p(u"        свойства первого результата: " + u", ".join(
                        [x for x in dir(r) if not x.startswith("_")]))

f = io.open(out, "w", encoding="utf-8")
f.write(u"\n".join(L))
f.close()
print("Готово: " + out)
