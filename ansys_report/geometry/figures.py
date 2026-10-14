"""Рисунки для отчёта по замерам: развёртка, 3D, допуски по высоте, карта точек, вмятины (matplotlib, без окна)."""
from __future__ import annotations
from pathlib import Path

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
from matplotlib.colors import ListedColormap, TwoSlopeNorm   # noqa: E402
from matplotlib.patches import Patch    # noqa: E402

CMAP = "RdYlBu_r"      # красный - наружу, синий - внутрь
DPI = 170


def _norm(vmin, vmax):
    lo, hi = min(vmin, -1e-6), max(vmax, 1e-6)
    return TwoSlopeNorm(vmin=lo, vcenter=0.0, vmax=hi)


def _save(fig, path: Path):
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def unfold(res: dict, path: Path) -> Path:
    """Развёртка стенки: цвет - радиальное отклонение Δr, мм; нулевая линия; образующие; метки вмятин."""
    m = res["model"]
    theta = np.linspace(0, 2 * np.pi, 361)
    z = np.linspace(0, m.H, 145)
    f = m.field(theta, z)
    s = theta * m.R
    fig, ax = plt.subplots(figsize=(11, 3.8))
    norm = _norm(float(f.min()), float(f.max()))
    cs = ax.contourf(s, z, f, levels=40, cmap=CMAP, norm=norm)
    ax.contour(s, z, f, levels=[0], colors="k", linewidths=0.9)
    for g, a in enumerate(res["angles"]):
        sg = np.radians(a) * m.R
        ax.axvline(sg, color="k", lw=0.4, ls=":")
        ax.text(sg, m.H * 1.01, f"{g + 1}", ha="center", va="bottom", fontsize=7)
    for d in res["dents"]:
        ax.plot([d["s_m"]], [d["z_m"]], marker="x", color="k", ms=7)
        ax.annotate(f"P{d['id']}", (d["s_m"], d["z_m"]), xytext=(4, 4), textcoords="offset points", fontsize=9, weight="bold")
    ax.set_xlabel("s от образующей №1, м")
    ax.set_ylabel("Z, м")
    ax.set_title("Развёртка стенки: радиальное отклонение Δr, мм (+ наружу, − внутрь); цифры сверху – номера образующих", fontsize=9)
    fig.colorbar(cs, ax=ax, pad=0.01, label="Δr, мм")
    return _save(fig, path)


def surface3d(res: dict, path: Path, amp: float = 20.0) -> Path:
    """Объёмный вид: отклонения увеличены в amp раз (только для наглядности)."""
    m = res["model"]
    theta = np.linspace(0, 2 * np.pi, 181)
    z = np.linspace(0, m.H, 73)
    f = m.field(theta, z)
    r = m.R + f * amp / 1000.0
    T, Z = np.meshgrid(theta, z)
    X, Y = r * np.cos(T), r * np.sin(T)
    norm = _norm(float(f.min()), float(f.max()))
    cmap = plt.get_cmap(CMAP)
    fig = plt.figure(figsize=(7.2, 6.2))
    ax = fig.add_subplot(111, projection="3d")
    ax.plot_surface(X, Y, Z, facecolors=cmap(norm(f)), rstride=1, cstride=1, linewidth=0, antialiased=False, shade=False)
    ax.set_box_aspect((1, 1, m.H / (2 * m.R) * 1.0 if m.H < 2 * m.R else 1))
    ax.view_init(elev=22, azim=-60)
    ax.set_xlabel("X, м"); ax.set_ylabel("Y, м"); ax.set_zlabel("Z, м")
    ax.set_title(f"Восстановленная поверхность стенки (отклонения увеличены в {amp:g} раз)", fontsize=9)
    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    fig.colorbar(sm, ax=ax, shrink=0.6, pad=0.08, label="Δr, мм")
    return _save(fig, path)


def tolerance_profiles(res: dict, path: Path) -> Path:
    """Отклонения образующих по высоте на фоне допусков H/200 и H/200 + 30 мм."""
    z = np.asarray(res["heights"])
    field = res["field"]
    fig, ax = plt.subplots(figsize=(7.2, 6.0))
    for g in range(field.shape[1]):
        ax.plot(field[:, g], z, lw=1.1, label=f"{g + 1}")
    za = np.linspace(0, z[-1], 50)
    la = za * 1000 / 200.0
    ax.plot(la, za, "k--", lw=1.4, label="допуск H/200")
    ax.plot(-la, za, "k--", lw=1.4)
    ax.plot(la + 30, za, "r:", lw=1.4, label="допуск H/200 + 30 мм")
    ax.plot(-(la + 30), za, "r:", lw=1.4)
    ax.axvline(0, color="gray", lw=0.6)
    ax.set_xlabel("Отклонение Δr, мм (+ наружу, − внутрь)")
    ax.set_ylabel("Высота Z, м")
    ax.set_title("Отклонения образующих от вертикали и допуски по ГОСТ 31385-2016", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=7, ncol=2, loc="lower right", title="Образующие", title_fontsize=7)
    return _save(fig, path)


def point_map(res: dict, path: Path) -> Path:
    """Карта оценки каждой точки: зелёный - в допуске H/200, жёлтый - в пределах H/200+30, красный - выше."""
    field, cell = res["field"], res["cell"]
    z = res["heights"]
    nz, ng = field.shape
    colors = ListedColormap(["#c8e6c9", "#fff59d", "#ef9a9a"])
    fig, ax = plt.subplots(figsize=(max(7.0, ng * 0.8), max(4.0, nz * 0.42)))
    ax.imshow(cell[1:][::-1], cmap=colors, vmin=0, vmax=2, aspect="auto")
    for j in range(1, nz):
        for g in range(ng):
            ax.text(g, (nz - 2) - (j - 1), f"{field[j, g]:.0f}", ha="center", va="center", fontsize=8)
    ax.set_xticks(range(ng)); ax.set_xticklabels([str(i + 1) for i in range(ng)], fontsize=8)
    ax.set_yticks(range(nz - 1)); ax.set_yticklabels([f"{z[j]:.1f}" for j in range(nz - 1, 0, -1)], fontsize=8)
    ax.set_xlabel("Образующая №"); ax.set_ylabel("Высота Z, м")
    ax.set_title("Оценка точек: число в ячейке – Δr, мм", fontsize=9)
    ax.legend(handles=[Patch(color="#c8e6c9", label="в допуске H/200"), Patch(color="#fff59d", label="выше H/200, в пределах H/200+30 мм"),
                       Patch(color="#ef9a9a", label="выше H/200+30 мм")], loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, fontsize=7)
    return _save(fig, path)


def dent_plot(res: dict, d, info: dict, path: Path) -> Path:
    """Участок вмятины: поле суммарного Δr и контур выделенной области."""
    m = res["model"]
    s = np.linspace(d.sc + d.xx[0] - d.xp, d.sc + d.xx[-1] - d.xp, 81)
    zz = np.linspace(max(0, d.zc + d.yy[0] - d.yp), min(m.H, d.zc + d.yy[-1] - d.yp), 81)
    total = m.field(s / m.R, zz)
    fig, ax = plt.subplots(figsize=(5.4, 4.2))
    cs = ax.contourf(s, zz, total, levels=30, cmap=CMAP, norm=_norm(float(total.min()), float(total.max())))
    ax.contour(s, zz, total, levels=[0], colors="k", linewidths=0.8)
    ax.plot([d.sc], [d.zc], "kx", ms=8)
    ax.annotate(f"P{info['id']}", (d.sc, d.zc), xytext=(5, 5), textcoords="offset points", weight="bold")
    ax.set_xlabel("s от образующей №1, м"); ax.set_ylabel("Z, м")
    ax.set_title(f"{info['name']}: глубина {info['depth_mm']:.1f} мм", fontsize=9)
    fig.colorbar(cs, ax=ax, label="Δr, мм")
    ax.set_aspect("equal", adjustable="box")
    return _save(fig, path)


def make_all(res: dict, img_dir: Path) -> dict:
    """Создаёт все рисунки; возвращает {ключ: путь}."""
    img_dir = Path(img_dir)
    img_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "geo_unfold": unfold(res, img_dir / "geo_unfold.png"),
        "geo_surface3d": surface3d(res, img_dir / "geo_surface3d.png"),
        "geo_tolerance": tolerance_profiles(res, img_dir / "geo_tolerance.png"),
        "geo_pointmap": point_map(res, img_dir / "geo_pointmap.png"),
    }
    for d, info in zip(res["model"].defects, res["dents"]):
        out[f"geo_dent{info['id']}"] = dent_plot(res, d, info, img_dir / f"geo_dent{info['id']}.png")
    return out
