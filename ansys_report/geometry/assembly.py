"""Достройка расчётной оболочечной модели: к стенке (12 граней-поясов, STEP) добавляются окрайка, днище и крыша.
Всё сшивается в одну связную оболочку с общими рёбрами (согласованная сетка в Ansys). Нужен Open CASCADE (пакет cadquery-ocp);
без него функция вызывает ImportError, и пакет собирается только со стенкой.

Упрощения: днище плоское (уклон не моделируется), окрайка и днище стыкуются по реальному контуру нижнего пояса,
крыша - гладкий купол (сфера или конус) по реальному верхнему контуру стенки, радиальные балки и кольца не моделируются."""
from __future__ import annotations

import math
from pathlib import Path


def _ocp():
    from OCP import STEPControl, IFSelect, TopExp, TopAbs, TopoDS, BRep, BRepBndLib, Bnd, gp, BRepBuilderAPI, BRepOffsetAPI, BRepCheck  # noqa: F401
    return True


def default_structure(D_m: float, H_m: float, roof_rise_m: float | None = None) -> dict:
    """Параметры по умолчанию, если заказчик не ввёл конструкцию (типовая окрайка, днище 8 мм, купол)."""
    R = D_m / 2
    rise = roof_rise_m if roof_rise_m else 0.1 * R
    return {"D": D_m, "H": H_m,
            "bottom": {"outside_mm": 200.0, "annular_width_mm": 1500.0, "overlap_mm": 100.0, "slope_denominator": 100.0,
                       "plate_thickness_mm": 8.0, "annular_thickness_mm": 12.0},
            "roof": {"shape": "Сферическая", "rise_m": rise, "deck_thickness_mm": 4.0, "central_radius_m": 1.3}}


def build_full_step(wall_step: str | Path, out_step: str | Path, structure: dict, log=lambda s: None) -> dict:
    """Читает STEP стенки, достраивает окрайку, днище, крышу, пишет единый STEP (мм). Возвращает сводку."""
    from OCP.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
    from OCP.TopoDS import TopoDS
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    from OCP.gp import gp_Pnt, gp_Ax2, gp_Dir, gp_Circ
    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeEdge,
                                    BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeVertex)
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.BRepCheck import BRepCheck_Analyzer

    rd = STEPControl_Reader()
    if rd.ReadFile(str(wall_step)) != IFSelect_RetDone:
        raise RuntimeError("не удалось прочитать STEP стенки")
    rd.TransferRoots()
    wall = rd.OneShape()

    def box(shape):
        b = Bnd_Box()
        BRepBndLib.Add_s(shape, b)
        lo, hi = b.CornerMin(), b.CornerMax()
        return lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z()

    H = box(wall)[5]
    D = 2 * max(abs(box(wall)[0]), box(wall)[3])
    R = D / 2
    ring_bottom, ring_top = None, None
    ex = TopExp_Explorer(wall, TopAbs_EDGE)
    while ex.More():
        e = (getattr(TopoDS, 'Edge_s', None) or TopoDS.Edge)(ex.Current())
        x0, y0, z0, x1, y1, z1 = box(e)
        if z1 - z0 < 1e-3 and max(x1 - x0, y1 - y0) > R:          # кольцевое ребро: плоское и крупное
            if abs(z0) < 1e-3 and ring_bottom is None:
                ring_bottom = e
            elif abs(z0 - H) < 1e-3 and ring_top is None:
                ring_top = e
        ex.Next()
    if ring_bottom is None or ring_top is None:
        raise RuntimeError("не найдены кольцевые рёбра стенки (низ/верх)")

    sew = BRepBuilderAPI_Sewing(0.05)
    ex = TopExp_Explorer(wall, TopAbs_FACE)
    while ex.More():
        sew.Add(ex.Current())
        ex.Next()

    # --- окрайка (кольцо снаружи) и днище (диск внутри) в плоскости z = 0
    b = structure.get("bottom") or {}
    out_r = R + float(b.get("outside_mm", 200.0))
    w_in = BRepBuilderAPI_MakeWire(ring_bottom).Wire()
    disc = BRepBuilderAPI_MakeFace(w_in, True).Face()
    circ = gp_Circ(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), out_r)
    w_out = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(circ).Edge()).Wire()
    ring_face = BRepBuilderAPI_MakeFace(w_out, True).Face()
    cast = lambda kind, sh: (getattr(TopoDS, kind + '_s', None) or getattr(TopoDS, kind))(sh)      # noqa: E731  (имена зависят от версии OCP)
    ring_face = BRepBuilderAPI_MakeFace(ring_face, cast('Wire', w_in.Reversed())).Face()                # отверстие по контуру стенки
    sew.Add(disc)
    sew.Add(ring_face)

    # --- крыша: купол по верхнему контуру стенки; сечения - окружности на сфере/конусе, вершина - апекс
    ro = structure.get("roof") or {}
    rise = float(ro.get("rise_m", 0.1 * R / 1000.0)) * 1000.0
    shape = ro.get("shape", "Сферическая")
    Rs = (R * R + rise * rise) / (2 * rise) if rise > 0 else 1e12
    ts = BRepOffsetAPI_ThruSections(False, False)
    ts.AddWire(BRepBuilderAPI_MakeWire(ring_top).Wire())
    n = 6
    for i in range(1, n):
        r = R * (1 - i / n)
        z = H + (rise * (1 - r / R) if shape != "Сферическая" else (math.sqrt(Rs * Rs - r * r) - math.sqrt(Rs * Rs - R * R)))
        c = gp_Circ(gp_Ax2(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1)), r)
        ts.AddWire(BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(c).Edge()).Wire())
    ts.AddVertex(BRepBuilderAPI_MakeVertex(gp_Pnt(0, 0, H + rise)).Vertex())
    ts.Build()
    roof = ts.Shape()
    sew.Add(roof)

    sew.Perform()
    shell = sew.SewedShape()
    free = sew.NbFreeEdges()
    multi = sew.NbMultipleEdges()
    ok = BRepCheck_Analyzer(shell).IsValid()
    log(f"сшивка: свободных рёбер {free}, рёбер с 3+ гранями {multi}, валидность {ok}")

    wr = STEPControl_Writer()
    wr.Transfer(shell, STEPControl_AsIs)
    wr.Write(str(out_step))
    nf = 0
    ex = TopExp_Explorer(shell, TopAbs_FACE)
    while ex.More():
        nf += 1
        ex.Next()
    return {"faces": nf, "free_edges": free, "multiple_edges": multi, "valid": bool(ok), "H_mm": H, "R_mm": R, "rise_mm": rise}
