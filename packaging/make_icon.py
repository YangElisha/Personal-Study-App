"""Build the MonoSpace icon, logo and README cover from Elisha's logo artwork.

Source: assets/monospace-logo-source.png (1024x1024: a purple nebula orb, a thin silver orbit
ring and a small silver moon on the ring, on black).

Writes:
  assets/monospace.ico          16-256 px (exe, installer, app window, favicon)
  assets/monospace.png          512 px, same artwork as the icon
  app/vendor/brand/logo-128.png the orb + ring on a transparent background (served by the app)
  app/vendor/brand/logo-512.png
  assets/cover.png              1600x800 README cover (orb, wordmark, tagline; splash style)

Sizes up to 64 px are not plain downscales: the source ring is ~4 px wide at 1024, which vanishes
when shrunk. They use a tighter crop (16-32 px), a slightly brightened orb, and a ring and moon
redrawn at a stroke that survives the size.

Run: python packaging/make_icon.py   (needs Pillow; build.ps1 runs it)
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "monospace-logo-source.png"
OUT_ICO = ROOT / "assets" / "monospace.ico"
OUT_PNG = ROOT / "assets" / "monospace.png"
OUT_COVER = ROOT / "assets" / "cover.png"
BRAND = ROOT / "app" / "vendor" / "brand"
FONTS = ROOT / "app" / "vendor" / "fonts"
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]

# Geometry of the source artwork (measured on the 1024 px original).
CX = CY = 511.5
RING_R = 245.5                 # centre line of the ring stroke
MOON_ANGLE = math.radians(-44.8)
TILE = (7, 7, 11)
SILVER = (206, 208, 217)


def crop(src: Image.Image, frac: float) -> Image.Image:
    side = 1024 * frac
    x0 = CX - side / 2
    return src.crop((round(x0), round(x0), round(x0 + side), round(x0 + side)))


def rounded_mask(n: int, radius: float) -> Image.Image:
    m = Image.new("L", (n, n), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, n - 1, n - 1), radius=radius, fill=255)
    return m


def icon_frame(src: Image.Image, size: int) -> Image.Image:
    """One icon size: the artwork on a near-black rounded tile."""
    ss = 8 if size <= 64 else 2                          # supersample, then downscale
    n = size * ss
    frac = 0.52 if size <= 32 else 0.70                  # tighter crop for the tiny sizes
    art = crop(src, frac).resize((n, n), Image.LANCZOS)
    k = n / (1024 * frac)                                # source px -> supersampled px
    if size <= 64:
        art = ImageEnhance.Brightness(art).enhance(1.25 if size <= 32 else 1.12)
        art = ImageEnhance.Color(art).enhance(1.15)
        d = ImageDraw.Draw(art)
        c = n / 2
        r = RING_R * k
        w = (1.15 if size <= 24 else 1.3 if size <= 32 else 1.25) * ss
        d.ellipse((c - r - w / 2, c - r - w / 2, c + r + w / 2, c + r + w / 2),
                  outline=SILVER, width=round(w))
        mx, my = c + r * math.cos(MOON_ANGLE), c + r * math.sin(MOON_ANGLE)
        mr = max(20 * k, (1.9 if size <= 24 else 2.4) * ss)
        gap = mr + 0.9 * ss                               # a black gap so the moon reads
        d.ellipse((mx - gap, my - gap, mx + gap, my + gap), fill=(0, 0, 0))
        d.ellipse((mx - mr, my - mr, mx + mr, my + mr), fill=SILVER)
        hr = mr * 0.55
        d.ellipse((mx - mr * .35 - hr, my - mr * .35 - hr, mx - mr * .35 + hr, my - mr * .35 + hr),
                  fill=(236, 237, 243))
    tile = Image.new("RGBA", (n, n), TILE + (255,))
    tile.paste(art, (0, 0))                              # corners are cut by putalpha below
    # hairline edge so the tile does not disappear on a dark taskbar
    edge = Image.new("RGBA", (n, n), (255, 255, 255, 0))
    em = ImageChops.subtract(rounded_mask(n, n * .2),
                             rounded_mask(n - 2 * ss, n * .2 - ss).crop((-ss, -ss, n - ss, n - ss)))
    edge.putalpha(em.point(lambda v: v * 22 // 255))
    tile = Image.alpha_composite(tile, edge)
    tile.putalpha(rounded_mask(n, n * .2))
    return tile.resize((size, size), Image.LANCZOS)


def unmultiply(img: Image.Image) -> Image.Image:
    """Artwork on black -> the same artwork on transparency (alpha = brightest channel)."""
    img = img.convert("RGB")
    r, g, b = img.split()
    a = ImageChops.lighter(ImageChops.lighter(r, g), b)
    a = a.point(lambda v: 0 if v < 6 else min(255, round((v - 6) * 255 / 249)))
    px, ap = img.load(), a.load()
    out = Image.new("RGBA", img.size)
    op = out.load()
    for y in range(img.height):
        for x in range(img.width):
            al = ap[x, y]
            if al:
                cr, cg, cb = px[x, y]
                op[x, y] = (min(255, cr * 255 // al), min(255, cg * 255 // al),
                            min(255, cb * 255 // al), al)
    return out


def font(name: str, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONTS / name), size)
    if weight is not None:
        try:
            f.set_variation_by_axes([weight])
        except OSError:
            pass
    return f


def tracked(d: ImageDraw.ImageDraw, x: float, y: float, text: str, f, track: float, fill) -> float:
    """Draw text with letter-spacing; returns the drawn width (without the trailing track)."""
    start = x
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill)
        x += f.getlength(ch) + track
    return x - track - start


def tracked_width(text: str, f, track: float) -> float:
    return sum(f.getlength(ch) for ch in text) + track * (len(text) - 1)


def cover(src: Image.Image) -> Image.Image:
    W, H, S = 1600, 800, 2                               # drawn at 2x, downscaled
    w, h = W * S, H * S
    bg = Image.new("RGB", (w, h), (3, 3, 6))
    # soft indigo glow behind the orb, and a vignette
    glow = Image.new("L", (w, h), 0)
    ox, oy = int(w * .29), int(h * .5)
    ImageDraw.Draw(glow).ellipse((ox - 700, oy - 700, ox + 700, oy + 700), fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(320))
    bg = Image.composite(Image.new("RGB", (w, h), (22, 18, 48)), bg, glow)
    d = ImageDraw.Draw(bg)
    rnd = random.Random(7)
    for _ in range(300):                                 # starfield
        x, y = rnd.random() * w, rnd.random() * h
        r = rnd.choice([1, 1, 1, 1.5, 2, 2.5])
        v = rnd.randint(60, 190)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(v, v, min(255, v + 18)))
    # the faint horizon arc
    arc = Image.new("L", (w, h), 0)
    R = w * .62
    acx, acy = w * .5, R + h * .06
    ImageDraw.Draw(arc).ellipse((acx - R, acy - R, acx + R, acy + R), outline=255, width=3 * S)
    arc_glow = arc.filter(ImageFilter.GaussianBlur(10 * S))
    bg = Image.composite(Image.new("RGB", (w, h), (150, 150, 200)), bg,
                         ImageChops.add(arc.point(lambda v: v * 70 // 255),
                                        arc_glow.point(lambda v: v * 60 // 255)))
    # the orb (screen-blended so the stars stay visible around it)
    orb = crop(src, 0.70).resize((int(h * .92), int(h * .92)), Image.LANCZOS)
    layer = Image.new("RGB", (w, h), (0, 0, 0))
    layer.paste(orb, (ox - orb.width // 2, oy - orb.height // 2))
    bg = ImageChops.screen(bg, layer)
    # wordmark + tagline
    d = ImageDraw.Draw(bg)
    title = "MONOSPACE"
    tx = int(w * .55)
    probe = font("spacegrotesk-var-latin.woff2", 100, 400)       # fit the wordmark to 38% of W
    size = round(100 * (w * .38) / tracked_width(title, probe, 42))
    ft = font("spacegrotesk-var-latin.woff2", size, 400)
    tw = tracked_width(title, ft, .42 * size)
    ty = h * .40
    tracked(d, tx, ty, title, ft, .42 * size, (246, 246, 250))
    sub = "SPATIAL STUDY & CONCEPT HORIZONS"
    fs = font("ibmplexmono-400-latin.woff2", 17 * S)
    track_s = (tw - sum(fs.getlength(c) for c in sub)) / (len(sub) - 1)   # same width as title
    tracked(d, tx, ty + size * 1.45, sub, fs, track_s, (160, 162, 190))
    d.line((tx, ty + size * 1.45 + 62 * S, tx + 56 * S, ty + size * 1.45 + 62 * S),
           fill=(120, 118, 190), width=2 * S)
    fl = font("ibmplexmono-400-latin.woff2", 14 * S)
    tracked(d, tx, ty + size * 1.45 + 86 * S, "OFFLINE  ·  LOCAL-FIRST  ·  WINDOWS", fl,
            2.6 * S, (112, 114, 138))
    return bg.resize((W, H), Image.LANCZOS)


# ---- the app icon (2026-10-06): "M" and the accent cursor, matching the header logo ----------
# Drawn as shapes on a 32-unit grid (the header's wordmark + caret, as a monogram), supersampled,
# so every size is crisp. The orb artwork above still makes the README cover and logo-*.png.
ICON_TILE = (27, 25, 22)          # warm near-black (the paper theme's ink)
ICON_M = (244, 239, 230)          # paper
ICON_CARET = (196, 118, 55)       # the accent, a touch lighter so it reads on the dark tile
M_SHAPE = [(6.5, 22.5), (6.5, 9.5), (9.4, 9.5), (13.25, 16.4), (17.1, 9.5), (20.0, 9.5), (20.0, 22.5),
           (17.3, 22.5), (17.3, 14.6), (14.05, 20.1), (12.45, 20.1), (9.2, 14.6), (9.2, 22.5)]
CARET_BOX = (21.6, 12.4, 25.6, 22.5)


def caret_icon(size: int) -> Image.Image:
    ss = 16 if size <= 64 else 4
    n = size * ss
    k = n / 32
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, n - 1, n - 1), radius=7.5 * k, fill=ICON_TILE)
    d.polygon([(x * k, y * k) for x, y in M_SHAPE], fill=ICON_M)
    x0, y0, x1, y1 = CARET_BOX
    d.rounded_rectangle((x0 * k, y0 * k, x1 * k, y1 * k), radius=0.6 * k, fill=ICON_CARET)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    src = Image.open(SRC).convert("RGB")
    frames = {s: caret_icon(s) for s in SIZES}
    OUT_ICO.parent.mkdir(parents=True, exist_ok=True)
    # Pillow writes one ICO frame per requested size, each from the matching appended image
    frames[256].save(OUT_ICO, format="ICO", sizes=[(s, s) for s in SIZES],
                     append_images=[frames[s] for s in SIZES if s != 256])
    caret_icon(512).save(OUT_PNG, format="PNG", optimize=True)
    BRAND.mkdir(parents=True, exist_ok=True)
    big = unmultiply(crop(src, 0.70).resize((512, 512), Image.LANCZOS))
    big.save(BRAND / "logo-512.png", optimize=True)
    unmultiply(crop(src, 0.70).resize((128, 128), Image.LANCZOS)).save(BRAND / "logo-128.png",
                                                                      optimize=True)
    cover(src).save(OUT_COVER, optimize=True)
    for p in (OUT_ICO, OUT_PNG, BRAND / "logo-128.png", BRAND / "logo-512.png", OUT_COVER):
        print(f"wrote {p.relative_to(ROOT)} ({p.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
