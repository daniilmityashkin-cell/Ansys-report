"""Схемы нагрузок для отчёта по данным loads_data.py (нагрузки в модели заданы командами, в Ansys отдельных объектов для картинки нет)."""
from __future__ import annotations

from pathlib import Path


def mpa(v: float) -> str:
    """Давление в МПа с запятой и 3 значащими цифрами: 0,169; 0,00238; 0,000291 (ветер и снег на порядки меньше гидростатики)."""
    v = abs(float(v))
    if v == 0:
        return "0"
    from math import floor, log10
    digits = max(0, 2 - floor(log10(v)))
    return f"{v:.{digits}f}".replace(".", ",")


def _load(path) -> dict:
    ns: dict = {}
    exec(Path(path).read_text(encoding="utf-8"), ns)
    return ns["LOADS"]


def make_load_figures(loads_file, out_dir) -> list[Path]:
    """fig04_loads.png (схема всех нагрузок) и fig05_hydrostatic.png (эпюры гидростатики) в out_dir."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import cm

    L = _load(loads_file)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    H = L["geometry"]["wall_height_mm"] / 1000
    zb = [z[0] / 1000 for z in L["belt_z_mm"]] + [H]
    cases = {c["id"]: c for c in L["cases"]}
    op = cases.get("op") or L["cases"][0]
    wind_case = cases.get("op_wind") or cases.get("vacuum")
    hyd = cases.get("hydrotest")
    paths = []

    # --- рисунок 5: эпюры гидростатического давления по высоте стенки
    fig, ax = plt.subplots(figsize=(6.4, 5.2))
    for case, color, label in ((op, "#1f77b4", "Эксплуатация"), (hyd, "#d62728", "Гидроиспытания")):
        if not case or not case.get("hydro"):
            continue
        g, hs = case["hydro"]["gradient_mpa_mm"], case["hydro"]["free_surface_mm"] / 1000
        zs = [0, hs]
        ps = [g * hs * 1000, 0]                               # МПа/мм * мм = МПа
        ax.fill_betweenx(zs, 0, ps, alpha=0.25, color=color)
        ax.plot(ps, zs, color=color, lw=2, label=f"{label}: уровень {hs:g} м, p_max = {mpa(ps[0])} МПа")
    for z in zb:
        ax.axhline(z, color="#999", lw=0.5, ls=":")
    ax.set_xlabel("Гидростатическое давление, МПа")
    ax.set_ylabel("Высота от днища, м")
    ax.set_ylim(0, H)
    ax.set_xlim(left=0)
    ax.grid(alpha=0.25)
    ax.legend(loc="upper right", fontsize=8)
    ax.set_title("Эпюры гидростатического давления (пунктир - границы поясов)", fontsize=9)
    fig.tight_layout()
    p5 = out / "fig05_hydrostatic.png"
    fig.savefig(p5, dpi=150)
    plt.close(fig)
    paths.append(p5)

    # --- рисунок 4: схема нагрузок на резервуар (боковой вид)
    fig, ax = plt.subplots(figsize=(7.2, 5.4))
    D = L["geometry"]["diameter_mm"] / 1000
    ax.plot([0, 0, D, D], [H, 0, 0, H], color="k", lw=2)                 # стенка и днище
    ax.plot([0, D / 2, D], [H, H * 1.06, H], color="k", lw=2)             # крыша (схематично)
    for z in zb[1:-1]:
        ax.plot([0, D], [z, z], color="#bbb", lw=0.4)
    if op.get("hydro"):
        g, hs = op["hydro"]["gradient_mpa_mm"], op["hydro"]["free_surface_mm"] / 1000
        pm = g * hs * 1000                                    # МПа
        w_ = D * 0.16
        ax.fill([0, 0, -w_], [hs, 0, 0], color="#4a90d9", alpha=0.55, lw=0)
        for k in range(1, 6):
            z = hs * k / 6
            ln = w_ * (1 - z / hs)
            ax.annotate("", xy=(0, z), xytext=(-ln, z), arrowprops=dict(arrowstyle="->", color="#1f4e8c"))
        ax.text(-w_ * 1.05, hs * 0.5, f"гидростатика\n{mpa(pm)} МПа у днища", fontsize=8, color="#1f4e8c", ha="right", va="center")
        ax.plot([0, D], [hs, hs], color="#1f77b4", ls="--", lw=1)
        ax.text(D * 0.5, hs, f"уровень налива {hs:g} м", ha="center", va="bottom", fontsize=8, color="#1f77b4")
    if wind_case and wind_case.get("wind"):
        wmax = max(abs(w["p_mpa"]) for w in wind_case["wind"]) or 1
        for w in wind_case["wind"]:
            zc = (w["z_lo_mm"] + w["z_hi_mm"]) / 2000
            ln = D * 0.18 * abs(w["p_mpa"]) / wmax
            ax.annotate("", xy=(D, zc), xytext=(D + ln, zc), arrowprops=dict(arrowstyle="->", color="#2ca02c"))
        ax.text(D * 1.02, H * 1.02, f"ветер, до {mpa(wmax)} МПа", fontsize=8, color="#2ca02c")
    roof = (op.get("roof_extra_mpa") or 0) + (op.get("uniform_mpa") or 0)
    for k in range(1, 6):
        x = D * k / 6
        ax.annotate("", xy=(x, H * 1.03), xytext=(x, H * 1.16), arrowprops=dict(arrowstyle="->", color="#7f3fbf"))
    ax.text(D / 2, H * 1.18, f"крыша: снег {mpa(op.get('roof_extra_mpa') or 0)} МПа, избыточное давление {mpa(op.get('uniform_mpa') or 0)} МПа",
            ha="center", fontsize=8, color="#7f3fbf")
    ax.annotate("опора (заделка по контуру днища)", xy=(0, 0), xytext=(D * 0.05, -H * 0.1), fontsize=8, color="#c00",
                arrowprops=dict(arrowstyle="->", color="#c00"))
    ax.set_xlim(-D * 0.45, D * 1.25)
    ax.set_ylim(-H * 0.18, H * 1.28)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("Схема нагрузок: гидростатика, ветер, снег и давление на крыше", fontsize=9)
    fig.tight_layout()
    p4 = out / "fig04_loads.png"
    fig.savefig(p4, dpi=150)
    plt.close(fig)
    paths.append(p4)
    return paths
