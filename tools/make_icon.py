"""Рисует значок программы (PNG + ICO). Запуск: python tools/make_icon.py"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter
import math

S = 2048                       # рисуем крупно, потом уменьшаем (сглаживание)
GOLD, INK, GREY = (255, 183, 27), (15, 16, 18), (70, 72, 78)


def rr(d, box, r, fill=None, outline=None, width=0):
    d.rounded_rectangle(box, r, fill=fill, outline=outline, width=width)


def make() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # мягкое золотое свечение
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    x0, y0, x1, y1 = 330, 210, 1718, 1838
    rr(gd, (x0, y0, x1, y1), 230, outline=GOLD + (255,), width=40)
    glow = glow.filter(ImageFilter.GaussianBlur(40))
    img.alpha_composite(glow)
    d = ImageDraw.Draw(img)
    rr(d, (x0, y0, x1, y1), 230, fill=INK + (255,))
    rr(d, (x0, y0, x1, y1), 230, outline=GOLD + (255,), width=14)
    # загнутый угол: срезаем угол документа и рисуем загиб
    fold = 400
    d.polygon([(x1 - fold - 80, y0 - 80), (x1 + 80, y0 - 80), (x1 + 80, y0 + fold + 80)], fill=(0, 0, 0, 0))
    d.line([(x1 - fold, y0 - 4), (x1 + 4, y0 + fold)], fill=GOLD + (255,), width=14)
    d.polygon([(x1 - fold + 8, y0 + 6), (x1 - fold + 8, y0 + fold), (x1 - 6, y0 + fold)], fill=(255, 196, 60, 255))
    # знак: золотой ромб
    cx, cy, r = 1024, 640, 150
    d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=GOLD + (255,))
    d.polygon([(cx, cy - r * .55), (cx + r * .55, cy), (cx, cy + r * .55), (cx - r * .55, cy)], fill=INK + (255,))
    # строки текста
    rr(d, (560, 930, 900, 962), 16, fill=GOLD + (255,))
    for i, w in enumerate((1020, 940, 860, 700)):
        rr(d, (560, 1020 + i * 66, 560 + w - 200, 1048 + i * 66), 14, fill=GREY + (255,))
    # гистограмма
    for i, h in enumerate((150, 210, 270, 380)):
        col = GOLD if i == 3 else (62, 64, 70)
        rr(d, (580 + i * 88, 1790 - h - 90, 640 + i * 88, 1700), 10, fill=col + (255,))
    # рамка с расчётной сеткой
    bx0, by0, bx1, by1 = 1010, 1360, 1590, 1720
    rr(d, (bx0, by0, bx1, by1), 26, fill=(8, 9, 11, 255), outline=(60, 62, 68, 255), width=6)
    tile = Image.new("RGBA", (bx1 - bx0 - 30, by1 - by0 - 30), (0, 0, 0, 0))
    w, h = tile.size
    px = tile.load()
    stops = [(0, (30, 60, 190)), (.3, (0, 160, 230)), (.5, (40, 200, 90)), (.72, (250, 220, 40)), (1, (230, 40, 30))]

    def color(t):
        t = max(0, min(1, t))
        for (a, ca), (b, cb) in zip(stops, stops[1:]):
            if a <= t <= b:
                k = (t - a) / (b - a)
                return tuple(int(ca[i] + (cb[i] - ca[i]) * k) for i in range(3))
        return stops[-1][1]

    for yy in range(h):
        for xx in range(w):
            u, v = xx / w, yy / h
            val = math.exp(-(((u - .5) / .26) ** 2 + ((v - .52 - .05 * math.sin(u * 5)) / .28) ** 2))
            val = val * .95 + .08 * (1 - v)
            px[xx, yy] = color(val) + (255,)
    td = ImageDraw.Draw(tile)
    for i in range(0, w, 34):                               # сетка конечных элементов
        td.line([(i, 0), (i, h)], fill=(0, 0, 0, 90), width=2)
    for j in range(0, h, 34):
        td.line([(0, j), (w, j)], fill=(0, 0, 0, 90), width=2)
    mask = Image.new("L", tile.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), 14, fill=255)
    img.paste(tile, (bx0 + 15, by0 + 15), mask)
    return img.resize((1024, 1024), Image.LANCZOS)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    big = make()
    (root / "installer").mkdir(exist_ok=True)
    big.resize((256, 256), Image.LANCZOS).save(root / "ansys_report" / "web" / "icon.png")
    big.save(root / "installer" / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save("/tmp/icon_preview.png")
    print("ok")
