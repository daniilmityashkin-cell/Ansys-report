# -*- coding: utf-8 -*-
# Скрипт для Ansys Mechanical (IronPython). НЕ ПРОВЕРЕН на реальной модели — запускать и править по ошибкам.
# Запуск: Mechanical → вкладка Automation → Scripting → открыть файл → Run.
# Что делает: для каждого результата, у которого Scoping = Named Selection вида "belt_1".."belt_12",
# берёт максимум и пишет results_full.csv (belt,fiber,equivalent,membrane); сохраняет картинку каждого результата.
# Подготовка модели: в Named Selections создать belt_1..belt_N; для каждого пояса добавить результаты
# Equivalent Stress (-> equivalent), Maximum Principal Stress поверхностный (-> fiber) и membrane (-> membrane),
# в Name результата дописать суффикс _eq / _fiber / _mem, например "belt_3_eq".
import os, re
out = r"C:\ansys_report_out"
if not os.path.isdir(out):
    os.makedirs(out)
sol = ExtAPI.DataModel.Project.Model.Analyses[0].Solution
sol.EvaluateAllResults()
data = {}
for r in sol.Children:
    m = re.match(r"belt_(\d+)_(eq|fiber|mem)$", r.Name)
    if not m:
        continue
    belt, kind = int(m.group(1)), m.group(2)
    data.setdefault(belt, {})[kind] = r.Maximum.Value / 1e6   # Па -> МПа (проверить единицы модели!)
    r.Activate()
    Graphics.ExportImage(os.path.join(out, "%s.png" % r.Name))
with open(os.path.join(out, "results_full.csv"), "w") as f:
    f.write("belt,fiber,equivalent,membrane\n")
    for b in sorted(data):
        d = data[b]
        f.write("%d,%.1f,%.1f,%.1f\n" % (b, d.get("fiber", 0), d.get("eq", 0), d.get("mem", 0)))
print("Готово: " + out)
