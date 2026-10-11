"""Точка входа для упакованной программы (AnsysReport.exe): открывает главное окно."""
from ansys_report.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["wizard"]))
