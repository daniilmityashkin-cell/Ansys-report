"""Таблица времени прогона по этапам из timing.log (метки ставят помощник, журналы Workbench и скрипты Mechanical).
Запуск: python tools/timing_report.py [C:\\ansys_report_work\\timing.log]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ansys_report.timing import read, table_md  # noqa: E402

if __name__ == "__main__":
    print(table_md(read(sys.argv[1] if len(sys.argv) > 1 else None)))
