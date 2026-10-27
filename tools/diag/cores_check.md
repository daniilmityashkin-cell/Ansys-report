# Ядра, время решения и лицензии MAPDL (проверка 26.10.2026)

## Почему в C:\ansys_report_work не было solve.out

- Сквозной прогон (`Make_report.bat` -> журнал Workbench из `ansys_connect.extract_via_workbench`) открывает проект, решает
  в `export_results.py` и выходит **без сохранения** (`Save` только при `save_as`). Workbench при этом откатывает папки
  `Tank_model_files\dp0\SYS*\MECH` к сохранённому состоянию - `solve.out`, `file*.err`, `file.rst` удаляются. Все папки MECH пустые.
- Диагностические журналы (`FINISHED NOSAVE`) - то же самое; решение идёт в `model\_ProjectScratch\Scr*` и тоже удаляется.
- Исправлено: `export_results.py` после решения каждого случая копирует `solve.out` в данные отчёта как
  `_ansys_data\solve_<случай>.out`; `diag.bat` кладёт выжимку (ядра, время, лицензия) в `diag/diag.txt`.

## Сейчас расчёт не идёт: включено GPU-ускорение

`%APPDATA%\Ansys\v261\SolveHandlers.xml`, конфигурация **My Computer** (её использует `Solve()` по умолчанию):
`UseGPUAcceleration = 1`, `GPUAccelerationDevice = nvidia`. MAPDL делает пробный запуск (`dummy.dat`) и падает:

    *** FATAL ***  No recommended GPU devices have been detected on machine NOIROUT.
    (GPU: NVIDIA GeForce RTX 4060 Laptop GPU - не из списка рекомендованных) -> ANSYS run terminated

Вечером 26.10 (прогоны до 22:46) расчёт шёл - настройку включили позже, не из скриптов проекта (они её не трогают).
У конфигурации **My Computer, Background** GPU выключен - на ней и сняты цифры ниже. Выключить GPU (Ansys закрыт):
Mechanical -> Home -> Solve Process Settings -> My Computer -> Advanced -> GPU Acceleration: None.

## Цифры (solve.out, РВС-10000 с кольцами, 92 тыс. узлов, случай «Вакуум, снег и ветер», линейный)

| Показатель | Значение |
|---|---|
| Параллельность | Distributed Memory Parallel (DMP), Intel MPI: **4 процесса × 1 поток = 4 ядра** |
| Ядер на машине | 8 физических / 12 логических (Intel Core i5-12450H) |
| Настройки (SolveHandlers.xml) | `DistributeAnsysSolution = 1`, `NumberOfProcesses = 4`, `MaxNumberProcessors = 4`, `HybridParallel = 0` |
| GPU | Not Requested (конфигурация Background) |
| Решатель | Distributed Sparse (symmetric), 46,5 Гфлопс, in-core |
| **Elapsed Time** | **50,1 с** (CP Time 48,4 с) |
| из них /PREP7 (APDL: толщины, балки, нагрузки поэлементно) | 13,8 с |
| вычисление решения / эквейшн-солвер | 12,2 с / 3,5 с |
| получение лицензии | 0,5 с |
| Память / диск (сумма по процессам) | 2,6 ГБ / 1,6 ГБ |
| Продукт (заголовок solve.out) | **Ansys Mechanical Enterprise** |

Лицензии: в solve.out строк «license checked out» MAPDL не пишет, только продукт. Сервер лицензий локальный
(`ANSYSLMD_LICENSE_FILE = 1055@localhost`, ansyslmd v11.19.9 UP); `lmutil lmstat` показывает фичи `ansys`, `mech_*`,
`anshpc`, `anshpc_pack`, `anshpc_gpu` - в момент проверки занятых нет (0 in use). 4 ядра - базовый уровень Mechanical Enterprise
без HPC; больше 4 ядер берёт `anshpc`.

## Выводы

- Реально используются 4 ядра из 8 физических. Поднять до 8 можно в Solve Process Settings (Cores = 8), но выигрыш небольшой:
  собственно решатель - 3,5 с из 50 с; больше всего времени - /PREP7 (13,8 с) и сборка/вывод результатов. Время сквозного прогона
  (~21 мин для РВС-10000, ~41 мин для РВС-30000) в основном уходит на Workbench/Mechanical (открытие, сетка, картинки), а не на MAPDL.
- GPU на этой видеокарте MAPDL не принимает - его нужно выключить, иначе ни один расчёт не выполняется
  (после правки в `ansys_connect` такой прогон остановится с ошибкой «Расчёт в Ansys не выполнен ни для одного случая»).
