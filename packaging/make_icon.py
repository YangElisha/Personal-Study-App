"""Draw the MonoSpace icon: assets/monospace.ico (16-256 px) and assets/monospace.png (256 px).

The app's logo mark (app/index.html, .brand i) is a rounded square with a 135deg gradient
ink -> live -> live/bg and a glow of the live colour. In the MonoSpace dark theme that is
silver #ECEDF3 -> indigo #A9B6F8 -> deep indigo, glowing on near-black #08080C. The icon puts
that mark on a near-black rounded tile.

Run: python packaging/make_icon.py   (needs Pillow; build.ps1 runs it)
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT_ICO = ROOT / "assets" / "monospace.ico"
OUT_PNG = ROOT / "assets" / "monospace.png"

BG_TOP, BG_BOTTOM = (0x16, 0x16, 0x1F), (0x08, 0x08, 0x0C)
INK, LIVE, BG = (0xEC, 0xED, 0xF3), (0xA9, 0xB6, 0xF8), (0x08, 0x08, 0x0C)
DEEP = tuple(round(l * .55 + b * .45) for l, b in zip(LIVE, BG))
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def rounded_mask(n, box, radius):
    m = Image.new("L", (n, n), 0)
    ImageDraw.Draw(m).rounded_rectangle(box, radius=radius, fill=255)
    return m


def diagonal_gradient(n, stops):
    """135deg gradient (top-left -> bottom-right) through (pos, colour) stops."""
    small = 256
    g = Image.new("RGB", (small, small))
    px = g.load()
    for y in range(small):
        for x in range(small):
            t = (x + y) / (2 * (small - 1))
            for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
                if t <= p1:
                    px[x, y] = lerp(c0, c1, (t - p0) / (p1 - p0) if p1 > p0 else 0)
                    break
    return g.resize((n, n), Image.BICUBIC)


def draw(n: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    # the near-black tile, a faint vertical gradient
    tile = Image.new("RGB", (n, n))
    td = ImageDraw.Draw(tile)
    for y in range(n):
        td.line([(0, y), (n, y)], fill=lerp(BG_TOP, BG_BOTTOM, y / (n - 1)))
    pad = round(n * .03)
    img.paste(tile, (0, 0), rounded_mask(n, (pad, pad, n - pad, n - pad), round(n * .22)))
    # indigo glow behind the mark
    m0, m1 = round(n * .25), round(n * .75)
    glow = Image.new("RGBA", (n, n), LIVE + (0,))
    gm = rounded_mask(n, (m0, m0, m1, m1), round(n * .12)).filter(
        ImageFilter.GaussianBlur(n * .07))
    glow.putalpha(gm.point(lambda v: round(v * .85)))
    tile_alpha = img.getchannel("A")
    glow.putalpha(ImageChops.multiply(glow.getchannel("A"), tile_alpha))
    img = Image.alpha_composite(img, glow)
    # the mark: silver -> indigo -> deep indigo
    mark = diagonal_gradient(n, [(0, INK), (.55, LIVE), (1, DEEP)])
    img.paste(mark, (0, 0), rounded_mask(n, (m0, m0, m1, m1), round(n * .11)))
    # a hairline highlight along the mark's top edge
    hl = Image.new("RGBA", (n, n), (255, 255, 255, 0))
    hm = ImageChops.subtract(rounded_mask(n, (m0, m0, m1, m1), round(n * .11)),
                             rounded_mask(n, (m0, m0 + round(n * .012), m1, m1), round(n * .11)))
    hl.putalpha(hm.point(lambda v: round(v * .5)))
    return Image.alpha_composite(img, hl)


def main() -> None:
    big = draw()
    OUT_ICO.parent.mkdir(parents=True, exist_ok=True)
    frames = [big.resize((s, s), Image.LANCZOS) for s in SIZES]
    frames[-1].save(OUT_ICO, format="ICO", sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1])
    frames[-1].save(OUT_PNG, format="PNG")
    print(f"wrote {OUT_ICO} ({OUT_ICO.stat().st_size} bytes, sizes {SIZES}) and {OUT_PNG}")


if __name__ == "__main__":
    main()
