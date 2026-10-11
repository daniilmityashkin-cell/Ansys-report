# -*- coding: utf-8 -*-
# Вставляет в расчёт "полного" резервуара APDL-макрос формы стенки (по замерам нивелировки) и решает расчёт.
# Запускается программой автоматически внутри Mechanical (через Workbench). Проект не сохраняется.
import os, io

out = os.environ.get("ANSYS_REPORT_OUT") or os.path.join(os.environ["TEMP"], "ansys_report_out")
name = os.environ.get("ANSYS_REPORT_FULL_NAME") or ""
apdl = os.environ.get("ANSYS_REPORT_APDL") or ""
log = []
model = ExtAPI.DataModel.Project.Model
try:
    target = None
    for a in model.Analyses:
        if a.Name == name:
            target = a
    if target is None:
        raise Exception(u"расчёт '%s' не найден" % name)
    if not apdl or not os.path.exists(apdl):
        raise Exception(u"файл макроса не найден: %s" % apdl)
    text = io.open(apdl, encoding="utf-8").read()
    old = [c for c in target.Children if c.GetType().Name == "CommandSnippet"]
    foreign = [c for c in old if c.Name != "AR full shape"]
    if foreign:
        # свои Commands пользователя (например, форма уже вставлена вручную): второй раз не применяем, чтобы форма не удвоилась
        log.append(u"ПРОПУЩЕНО: в расчёте '%s' уже есть Commands ('%s') - форма стенки не вставлена. "
                   u"Если это не форма стенки, удалите их и повторите." % (name, foreign[0].Name))
    else:
        for c in old:                           # наш прошлый макрос заменяем
            c.Delete()
        snip = target.AddCommandSnippet()
        snip.Name = "AR full shape"
        snip.AppendText(text)
        log.append(u"Макрос формы стенки вставлен в расчёт '%s' (%d строк)" % (name, text.count("\n")))
        target.Solution.Solve(True)
        log.append(u"Расчёт '%s' после применения формы: %s" % (name, target.Solution.Status))
except Exception as e:
    log.append(u"ОШИБКА формы стенки: %s" % e)

f = io.open(os.path.join(out, "log_shape.txt"), "w", encoding="utf-8")
f.write(u"\n".join(log))
f.close()
print(u"\n".join(log))
