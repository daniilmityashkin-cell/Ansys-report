import math

import pytest

from ansys_report.loads import profiles as pr
from ansys_report.loads.beams import _sec


def test_catalog_matches_dimensions():
    """Каталожные значения не должны расходиться с расчётом по габаритам больше, чем галтели (защита от опечаток в таблице)."""
    for k, (h, b, s, t, A, Ix, Iy) in pr.I_BEAMS.items():
        a, ix, iy = pr.i_from_dims(h, b, s, t)
        assert abs(a - A) / A < 0.03, f"двутавр {k}: A {A} vs {a:.2f}"
        assert abs(ix - Ix) / Ix < 0.03, f"двутавр {k}: Ix {Ix} vs {ix:.1f}"
        assert 0 < (iy - Iy) / Iy < 0.28, f"двутавр {k}: Iy {Iy} vs {iy:.1f}"
    for k, (h, b, s, t, A, Ix, Iy) in pr.CHANNELS.items():
        a, ix, iy = pr.channel_from_dims(h, b, s, t)
        assert abs(a - A) / A < 0.03, f"швеллер {k}: A {A} vs {a:.2f}"
        assert abs(ix - Ix) / Ix < 0.03, f"швеллер {k}: Ix {Ix} vs {ix:.1f}"
        assert 0 < (iy - Iy) / Iy < 0.28, f"швеллер {k}: Iy {Iy} vs {iy:.1f}"
    for (b, t), (A, I) in pr.ANGLES.items():
        a, ix, _ = pr.angle_from_dims(b, t)
        assert abs(a - A) / A < 0.08, f"уголок {b}x{t}: A {A} vs {a:.2f}"
        assert abs(ix - I) / I < 0.10, f"уголок {b}x{t}: I {I} vs {ix:.1f}"


def test_parse_known_labels():
    p = pr.parse_profile("Двутавр 24")
    assert (p["area_cm2"], p["Ix_cm4"], p["Iy_cm4"]) == (34.8, 3460, 198)
    p = pr.parse_profile("швеллер 24п")
    assert p["name"] == "Швеллер 24П" and p["area_cm2"] == 30.6 and p["Ix_cm4"] == 2900
    p = pr.parse_profile("Уголок L90×90×6")
    assert p["area_cm2"] == 10.61 and p["Ix_cm4"] == p["Iy_cm4"] == 82.1
    assert pr.parse_profile("Уголок 90x6")["name"] == "Уголок L90×90×6"
    assert pr.parse_profile("Швеллер 6,5")["Ix_cm4"] == 48.6


def test_parse_by_dimensions_and_custom():
    p = pr.parse_profile("Двутавр 250×125×6×9")
    assert abs(p["area_cm2"] - (2 * 12.5 * 0.9 + 23.2 * 0.6)) < 1e-6 and p["source"].startswith("по габаритам")
    p = pr.parse_profile("Труба 108×4")
    assert abs(p["area_cm2"] - math.pi * (10.8 ** 2 - 10.0 ** 2) / 4) < 1e-3
    p = pr.parse_profile("Труба 100×50×4")
    assert abs(p["area_cm2"] - (100 * 50 - 92 * 42) / 100) < 1e-6
    p = pr.parse_profile("Полоса 200×10")
    assert p["area_cm2"] == 20 and abs(p["Ix_cm4"] - 10 * 200 ** 3 / 12 / 1e4) < 0.01
    p = pr.parse_profile("Свои A=34,8 Ix=3460 Iy=198")
    assert (p["area_cm2"], p["Ix_cm4"], p["Iy_cm4"]) == (34.8, 3460, 198)


@pytest.mark.parametrize("bad", ["", "Двутавр 25Б2", "Двутавр 99", "Швеллер 99П", "Уголок L90×60×6", "Уголок L90", "Балка 20", "Труба 10×6", "Свои A=10"])
def test_parse_errors_are_readable(bad):
    with pytest.raises(ValueError):
        pr.parse_profile(bad)


def test_every_catalog_name_resolves_and_feeds_beams():
    for name in pr.catalog_names():
        s = pr.section_props(name)
        assert s["computed"]["area_cm2"] > 0
        out = _sec(s, True)
        assert out["A"] > 0 and out["Iyy"] > 0 and out["J"] >= 1
    assert abs(_sec(pr.section_props("Двутавр 24"), True)["Iyy"] - 3460e4) < 1e3


def test_structure_sections_complete_project_for_beams():
    from ansys_report.loads.beams import beams_package, with_structure_sections
    from server.structinput import beam_sections
    f = {"s_beam_radial": "Двутавр 24", "s_beam_central": "Швеллер 24П", "s_beam_rings": "Уголок L90×90×6", "s_beam_edge": "Швеллер 24П"}
    st = {"roof": {"radial_count": 24, "ring_count": 3, "central_radius_m": 1.3, "first_angle_deg": 7.5}, "beam_sections": beam_sections(f)}
    p = beams_package(with_structure_sections({"diameter": "34.2", "height": "12"}, st), 17100.0)
    assert p["radial_count"] == 24 and len(p["rings"]) == 3 and p["radial"]["A"] == 3480.0 and p["edge"]["A"] == 3060.0
    # профиль из файла проекта (его нет в каталоге) принимается как есть, а у колец с разными профилями они сохраняются
    own = lambda n, a: {"name": n, "computed": {"area_cm2": a, "Ix_cm4": 4000, "Iy_cm4": 300}, "dimensions_m": {"D": .25, "Base": .125, "TW": .006, "TF": .009}}
    proj = {"diameter": "34.2", "height": "12", "roof": {"enabled": True, "radial_count": 24, "ring_count": 2, "central_radius_m": 1.3},
            "beam_sections": {"radial": own("25Б2", 37.7), "central_ring": own("Швеллер 24П", 30.6), "channel": own("Швеллер 24П", 30.6), "hoop_1": own("Уголок L90×90×6", 10.61), "hoop_2": own("Уголок L100×100×8", 15.6)}}
    f["s_beam_radial"] = "25Б2"
    known = __import__("server.structinput", fromlist=["x"]).project_sections(proj)
    st2 = {"roof": {"radial_count": 24, "ring_count": 2, "central_radius_m": 1.3}, "beam_sections": beam_sections({**f, "s_beam_rings": "Уголок L90×90×6"}, known)}
    p2 = beams_package(with_structure_sections(proj, st2), 17100.0)
    assert p2["radial"]["A"] == 3770.0 and [r["A"] for r in p2["rings"]] == [1061.0, 1560.0]
    st3 = {"roof": st2["roof"], "beam_sections": beam_sections({**f, "s_beam_rings": "Уголок L125×125×8"}, known)}      # кольца заменены пользователем
    p3 = beams_package(with_structure_sections(proj, st3), 17100.0)
    assert [r["A"] for r in p3["rings"]] == [1970.0, 1970.0]
    with pytest.raises(ValueError):
        beam_sections({**f, "s_beam_radial": "Двутавр 25Б2"})                    # нет в каталоге и в проекте: понятная ошибка
