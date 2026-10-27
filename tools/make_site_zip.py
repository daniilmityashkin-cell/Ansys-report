"""Облегчённый архив «только сайт» для показа: сервер, пакет ansys_report (нужен сайту), запуск двойным щелчком и инструкция.
В архив НЕ входят: скрипты Ansys (ansys_scripts), тесты, документация, эталонные данные, инструменты разработки, отчёты.
Сборка расчёта в Ansys в этом режиме отключена (ASR_DEMO=1). Запуск: python tools/make_site_zip.py [выходной.zip]"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE_DIRS = ("server", "ansys_report")
INCLUDE_FILES = ("requirements-server.txt",)
SKIP_PARTS = {"__pycache__", ".pytest_cache", "server_data"}

README = """ANSYS REPORT: сайт для просмотра
=================================

ЗАПУСК (Windows)
1. Установите Python 3.12 или 3.13 с python.org (при установке поставьте галочку "Add python.exe to PATH").
2. Распакуйте архив в любую папку.
3. Дважды щёлкните start_site.bat. В первый раз 3-7 минут (скачиваются пакеты), потом несколько секунд.
4. Откроется браузер на http://127.0.0.1:8000 . Зарегистрируйтесь с любой почтой и паролем (данные остаются только на вашем компьютере).
   Закрывать чёрное окно нельзя, пока сайт нужен.

ЧТО ПОСМОТРЕТЬ
1. Кнопка "Геометрия" (студия): загрузите замеры (проект РВС Геометрия .json или нивелировку .xlsx), введите толщины поясов
   (вручную или документом), пройдите шаги 01-07, нажмите "Создать модель".
2. Страница расчёта: справа "Нагрузки на модели" (меняйте нагрузки слева, картина обновляется сразу).
3. "Изменить геометрию" возвращает в студию с теми же данными.
Сборка технического отчёта в Ansys в этой версии отключена: готовые отчёты присланы отдельными файлами.

Linux / macOS: chmod +x start_site.sh && ./start_site.sh
"""


def build(out: Path) -> Path:
    bat = (ROOT / "start_site.bat").read_text(encoding="utf-8").replace("set ASR_FIRST_FREE=1", "set ASR_DEMO=1\r\nset ASR_FIRST_FREE=1")
    sh = (ROOT / "start_site.sh").read_text(encoding="utf-8").replace("export ASR_FIRST_FREE=1", "export ASR_DEMO=1 ASR_FIRST_FREE=1")
    files = subprocess.run(["git", "ls-files", "-z", *INCLUDE_DIRS, *INCLUDE_FILES], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8").split("\0")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            if f and not (set(Path(f).parts) & SKIP_PARTS):
                z.write(ROOT / f, f)
        z.writestr("start_site.bat", bat)
        z.writestr("start_site.sh", sh)
        z.writestr("ЗАПУСК.txt", README.replace("\n", "\r\n"))
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "ansys-report-site.zip"
    print(build(target), round(target.stat().st_size / 1e6, 2), "МБ")
