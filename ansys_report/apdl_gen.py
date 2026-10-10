"""Форма «полного» резервуара без перестроения геометрии.

Геометрия проекта Ansys построена по замеру «пустого» резервуара. Для режима «полный» узлы стенки
сдвигаются по радиусу на разность замеров (полный − пустой) — APDL-макрос вставляется в Mechanical как
Commands в анализ. Билинейная интерполяция по высоте и углу, нулевое отклонение на днище (x = 0).
Оси как в Excel/Ansys: X — вертикаль, Y = R·cos(a), Z = R·sin(a), a = start − step·j."""
from __future__ import annotations
import math
from pathlib import Path
from .project import Project


def delta_table(p: Project, frm: str = "empty", to: str = "full") -> list[list[float]]:
    """Строки: высоты 0..N поясов (0 — днище, нули); столбцы: точки 0..n (n = замыкающая = 0). Мм."""
    a = p.survey_empty if frm == "empty" else p.survey_full
    b = p.survey_full if to == "full" else p.survey_empty
    n = len(a[0])
    rows = [[0.0] * (n + 1)]
    for k in range(len(a)):
        d = [b[k][j] - a[k][j] for j in range(n)]
        rows.append(d + [d[0]])
    return rows


def radial_shift_mm(p: Project, tbl: list[list[float]], x_m: float, y_m: float, z_m: float) -> float:
    """Python-зеркало APDL-цикла: сдвиг (мм) для узла в координатах модели (м)."""
    s, step_h = p.raw["survey"], p.tank["belt_height"] / 1000
    n = s["points_per_belt"]
    step = 360 / n
    a = math.degrees(math.atan2(z_m, y_m))
    t = ((s["start_angle"] - a + 720) % 360) / step
    j0 = min(int(t), n - 1); f = t - j0
    u = x_m / step_h
    i0 = min(int(u), len(tbl) - 2); g = min(u - i0, 1.0)
    d00, d01 = tbl[i0][j0], tbl[i0][j0 + 1]
    d10, d11 = tbl[i0 + 1][j0], tbl[i0 + 1][j0 + 1]
    return (d00 * (1 - f) + d01 * f) * (1 - g) + (d10 * (1 - f) + d11 * f) * g


def build_apdl(p: Project, frm: str = "empty", to: str = "full") -> str:
    """APDL-макрос (только ASCII: солвер Ansys не любит кириллицу в Commands)."""
    t, s = p.tank, p.raw["survey"]
    tbl = delta_table(p, frm, to)
    nr, nc = len(tbl), len(tbl[0])
    L = [
        f"! Wall shape of tank {t['tag'].replace(chr(1058), 'T')}: radial node shift = survey '{to}' minus survey '{frm}'",
        "! Paste into Mechanical: right click on the analysis -> Insert -> Commands. Model units: meters.",
        "/PREP7",
        "CSYS,0",
        "ALLSEL,ALL",
        f"R0 = {t['diameter'] / 2000}        ! wall radius, m",
        f"HSTEP = {t['belt_height'] / 1000}      ! belt height, m",
        f"NPT = {nc - 1}          ! points per ring",
        f"NR_ = {nr}          ! rows in table (0..{nr - 1} belts)",
        f"ASTART = {s['start_angle']}       ! angle of point 0, deg",
        f"ASTEP = {360 / (nc - 1)}",
        "SCL = 0.001            ! mm -> m (set 1 if the model is in mm)",
        "TOL = 0.25             ! radial tolerance for selecting wall nodes, m",
        f"*DIM,DLT,ARRAY,{nr},{nc}   ! rows: height 0..{nr - 1} belts; columns: points 0..{nc - 1}; values in mm",
    ]
    for i, row in enumerate(tbl, 1):
        for j, v in enumerate(row, 1):
            if v != 0:
                L.append(f"DLT({i},{j}) = {v:g}")
    L += [
        "*GET,NMX,NODE,0,NUM,MAX",
        "NMOVED = 0",
        "*DO,I,1,NMX",
        "  *IF,NSEL(I),EQ,0,CYCLE",
        "  XX = NX(I)",
        "  YY = NY(I)",
        "  ZZ = NZ(I)",
        "  RR = SQRT(YY*YY+ZZ*ZZ)",
        "  *IF,ABS(RR-R0),GT,TOL,CYCLE",
        "  *IF,XX,LT,0.001,CYCLE",
        "  AA = ATAN2(ZZ,YY)*180/ACOS(-1)",
        "  TT = MOD(ASTART-AA+720,360)/ASTEP",
        "  J0 = MIN(NINT(TT-0.4999999),NPT-1)",       # NINT(x-0.5) = floor(x); APDL has no INT()
        "  FJ = TT-J0",
        "  UU = XX/HSTEP",
        "  I0 = MIN(NINT(UU-0.4999999),NR_-2)",
        "  GG = MIN(UU-I0,1)",
        "  D0 = DLT(I0+1,J0+1)*(1-FJ)+DLT(I0+1,J0+2)*FJ",
        "  D1 = DLT(I0+2,J0+1)*(1-FJ)+DLT(I0+2,J0+2)*FJ",
        "  DD = (D0*(1-GG)+D1*GG)*SCL",
        "  RN = RR+DD",
        "  NMODIF,I,XX,YY*RN/RR,ZZ*RN/RR",
        "  NMOVED = NMOVED+1",
        "*ENDDO",
        "*MSG,INFO,NMOVED",
        "Nodes moved: %I",
        "FINISH",
        "/SOLU",
    ]
    return "\n".join(L) + "\n"


def write_apdl(p: Project, out: Path, frm: str = "empty", to: str = "full") -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_apdl(p, frm, to), encoding="utf-8")
    return out
