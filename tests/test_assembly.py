"""Достройка днища, окрайки и крыши: одна связная оболочка из 12 + 3 граней (нужен Open CASCADE)."""
import re

import pytest

pytest.importorskip("OCP")

from server.tableinput import build_project  # noqa: E402
from ansys_report.geometry import check  # noqa: E402
from ansys_report.geometry.assembly import build_full_step, default_structure  # noqa: E402


def test_full_model_is_single_shell(tmp_path):
    rows = "\n".join("\t".join(str(((i * 7 + j * 3) % 11) - 5) for j in range(12)) for i in range(15))   # 15 образующих x 12 поясов, гладкие отклонения
    proj = build_project("28.5", "17.88", rows, "16 14 13 12 12 12 12 12 12 12 12 12", "gens")
    bm = check.export_belt_model(proj, tmp_path / "w")
    info = build_full_step(bm["step"], tmp_path / "full.step", default_structure(28.5, 17.88, 2.07))
    assert info["faces"] == 15 and info["valid"]
    text = (tmp_path / "full.step").read_text(errors="ignore")
    assert len(re.findall(r"OPEN_SHELL\(", text)) == 1                      # одна оболочка: в Ansys одно тело, согласованная сетка
    assert len(re.findall(r"ADVANCED_FACE\(", text)) == 15
    assert abs(info["rise_mm"] - 2070) < 1
