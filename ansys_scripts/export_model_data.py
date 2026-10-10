# -*- coding: utf-8 -*-
# Выгрузка ВСЕХ данных модели из Ansys Mechanical 2026 R1 (IronPython) в model_data.json.
# Запуск: Automation -> Scripting -> "+" -> вставить -> Run. Ничего в проекте не меняет.
# Результат: %TEMP%\ansys_report_out\model_data.json  (+ model_data_log.txt)
# Если появится окно Exception на какой-то строке - закройте его и нажмите Run/Continue, скрипт продолжит.
import os, io, math
import System

out = os.path.join(os.environ["TEMP"], "ansys_report_out")
System.IO.Directory.CreateDirectory(out)
data = {"errors": []}
model = ExtAPI.DataModel.Project.Model


def s(v):
    try:
        return unicode(v)
    except Exception:
        return u"?"


def dumps(o, ind=0):
    """Мини-сериализатор JSON (в IronPython нет модуля _json, стандартный json вызывает окно ошибки)."""
    pad = u" " * (ind + 1)
    if o is None:
        return u"null"
    if isinstance(o, bool):
        return u"true" if o else u"false"
    if isinstance(o, (int, long, float)):
        return unicode(o)
    if isinstance(o, dict):
        if not o:
            return u"{}"
        return u"{\n" + u",\n".join(pad + dumps(unicode(k)) + u": " + dumps(v, ind + 1) for k, v in o.items()) + u"\n" + u" " * ind + u"}"
    if isinstance(o, (list, tuple)):
        if not o:
            return u"[]"
        if all(isinstance(x, (int, long, float)) for x in o):
            return u"[" + u", ".join(unicode(x) for x in o) + u"]"
        return u"[\n" + u",\n".join(pad + dumps(x, ind + 1) for x in o) + u"\n" + u" " * ind + u"]"
    t = unicode(o).replace(u"\\", u"\\\\").replace(u'"', u'\\"').replace(u"\n", u"\\n").replace(u"\r", u"").replace(u"\t", u" ")
    return u'"' + t + u'"'


def props(obj):
    """Все видимые свойства объекта дерева: {имя: строка}."""
    d = {}
    names = getattr(obj, "GetVisiblePropertyNames", None)
    if names is None:
        return d
    try:
        for n in names():
            try:
                d[s(n)] = s(obj.GetPropertyValue(n))
            except Exception as e:
                d[s(n)] = u"<ошибка: %s>" % e
    except Exception as e:
        data["errors"].append(u"props %s: %s" % (s(getattr(obj, "Name", "?")), e))
    return d


# ---- тела
bodies = []
for b in model.Geometry.GetChildren(DataModelObjectCategory.Body, True):
    if s(b.Name).startswith("Beam"):
        continue
    bodies.append({"name": s(b.Name), "dimension": s(getattr(b, "DimensionType", "?")),
                   "thickness": s(getattr(b, "Thickness", "?")), "material": s(getattr(b, "Material", "?")),
                   "suppressed": s(getattr(b, "Suppressed", "?")),
                   "geo_id": getattr(b.GetGeoBody(), "Id", None) if hasattr(b, "GetGeoBody") else None})
data["bodies"] = bodies
data["beam_count"] = len([1 for b in model.Geometry.GetChildren(DataModelObjectCategory.Body, True) if s(b.Name).startswith("Beam")])

# ---- сетка
mesh_info = props(model.Mesh)
data["mesh_object"] = mesh_info
try:
    md = ExtAPI.DataModel.MeshDataByName("Global")
    data["node_count"] = md.NodeCount
    data["element_count"] = md.ElementCount
    nodes = [(n.X, n.Y, n.Z) for n in md.Nodes]
    rmax = max(math.sqrt(y * y + z * z) for x, y, z in nodes)
    data["bbox"] = {"xmax": max(n[0] for n in nodes), "xmin": min(n[0] for n in nodes), "rmax": rmax}
    rings = {}
    for x, y, z in nodes:
        r = math.sqrt(y * y + z * z)
        if r > rmax - 0.3:
            rings.setdefault(round(x, 3), []).append((round(math.degrees(math.atan2(z, y)), 2), round(r, 5)))
    data["rings"] = [{"x": k, "points": sorted(v)} for k, v in sorted(rings.items()) if len(v) >= 100]
except Exception as e:
    data["errors"].append(u"сетка/узлы: %s" % e)

# ---- материалы
mats = []
try:
    for m in model.Materials.Children:
        mats.append({"name": s(m.Name), "props": props(m)})
except Exception as e:
    data["errors"].append(u"материалы: %s" % e)
data["materials"] = mats

# ---- анализы: нагрузки, настройки, результаты
ans = []
for a in model.Analyses:
    item = {"name": s(a.Name), "type": s(getattr(a, "AnalysisType", "?")), "children": [], "results": []}
    for c in a.Children:
        if s(c.Name).startswith("Solution"):
            for r in c.Children:
                if s(r.Name).startswith("Solution Information"):
                    continue
                res = {"name": s(r.Name), "type": s(r.GetType().Name)}
                for k in ("Maximum", "Minimum", "Mode", "ReportedFrequency", "Position", "NormalOrientation"):
                    v = getattr(r, k, None)
                    if v is not None:
                        res[k] = s(v)
                item["results"].append(res)
        else:
            item["children"].append({"name": s(c.Name), "type": s(c.GetType().Name),
                                     "suppressed": s(getattr(c, "Suppressed", "?")), "props": props(c)})
    ans.append(item)
data["analyses"] = ans

f = io.open(os.path.join(out, "model_data.json"), "w", encoding="utf-8")
f.write(dumps(data))
f.close()
print("Готово: %s | тел: %d | узлов: %s | колец: %d | ошибок: %d" % (
    os.path.join(out, "model_data.json"), len(bodies), data.get("node_count"), len(data.get("rings", [])), len(data["errors"])))
for e in data["errors"]:
    print(e)
