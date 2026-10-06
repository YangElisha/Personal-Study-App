"""Build the MonoSpace icon, logo and README cover from Elisha's logo artwork.

Source: assets/monospace-logo-source.png (1024x1024: a purple nebula orb, a thin silver orbit
ring and a small silver moon on the ring, on black).

Writes:
  assets/monospace.ico          16-256 px (exe, installer, app window, favicon)
  assets/monospace.png          512 px, same artwork as the icon
  app/vendor/brand/logo-128.png the orb + ring on a transparent background (served by the app)
  app/vendor/brand/logo-512.png
  assets/cover.png              1600x800 README cover (notebooks, wordmark, tagline)

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


def notebook(w: int, h: int, cloth, label: str, ribbon: float) -> Image.Image:
    """One notebook cover: cloth, a dark spine, a paper label, and the bookmark ribbon."""
    im = Image.new("RGB", (w, h), cloth)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, int(w * .085), h), fill=tuple(max(0, c - 26) for c in cloth))
    d.line((int(w * .085), 0, int(w * .085), h), fill=tuple(min(255, c + 24) for c in cloth), width=2)
    # the bookmark ribbon, as long as the deck is known
    rx = int(w * .035)
    d.rectangle((rx, 0, rx + int(w * .022), int(h * ribbon)), fill=(214, 160, 60))
    # the paper label: the type is fitted to it, never spilling over the edge
    m = int(w * .11)
    lx0, ly0, lx1 = int(w * .17), m, w - m
    pad = int(w * .055)
    lines = label.split(chr(10))
    size = max(11, int(h * .055))
    while size > 9:
        fl = font("schibstedgrotesk-400-800-n-latin.woff2", size, 700)
        if max(fl.getlength(t) for t in lines) <= (lx1 - lx0) - 2 * pad:
            break
        size -= 1
    step = int(size * 1.18)
    ly1 = ly0 + int(pad * .7) + step * len(lines) + int(pad * .5)
    d.rounded_rectangle((lx0, ly0, lx1, ly1), radius=4, fill=(243, 239, 228))
    for i, t in enumerate(lines):
        d.text((lx0 + pad, ly0 + int(pad * .55) + i * step), t, font=fl, fill=(22, 23, 26))
    fm = font("ibmplexmono-400-latin.woff2", max(8, int(h * .030)))
    d.text((lx0, ly1 + int(h * .035)), "25 CONCEPTS", font=fm, fill=(206, 202, 193))
    # the progress rule near the foot
    d.rectangle((int(w * .17), int(h * .80), w - m, int(h * .80) + 3), fill=(0, 0, 0))
    d.rectangle((int(w * .17), int(h * .80), int(w * .17) + int((w - m - w * .17) * ribbon),
                 int(h * .80) + 3), fill=(236, 233, 224))
    return im


def cover(src: Image.Image) -> Image.Image:
    """The README cover: the MonoSpace look itself — ink, paper, notebooks on a shelf.

    Rewritten 2026-10-06 for 2.0. It used to be the purple orb from the first branding; the app
    has been the M-and-cursor wordmark on ink since the redesign, and the cover said otherwise.
    """
    W, H, S = 1600, 800, 2                               # drawn at 2x, downscaled
    w, h = W * S, H * S
    INK, PAPER, ACCENT, MUTED = (16, 16, 18), (244, 241, 232), (196, 118, 55), (122, 120, 116)
    bg = Image.new("RGB", (w, h), INK)
    d = ImageDraw.Draw(bg)
    # faint ruled paper, the app's own background
    for y in range(0, h, 26 * S):
        d.line((0, y, w, y), fill=(24, 24, 27), width=1)
    # a warm pool of light behind the notebooks
    glow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(glow).ellipse((int(w * .04), int(h * .10), int(w * .62), int(h * 1.05)), fill=255)
    bg = Image.composite(Image.new("RGB", (w, h), (34, 30, 27)), bg,
                         glow.filter(ImageFilter.GaussianBlur(170)))
    d = ImageDraw.Draw(bg)

    # three notebooks standing on a shelf, the way the Library draws them
    cloths = [(31, 58, 95), (122, 46, 44), (46, 82, 62)]
    labels = ["Information\nAssurance", "Software\nProcesses", "Discrete\nMaths"]
    ribbons = [.78, .46, .95]
    nw, nh = int(w * .125), int(h * .56)
    x, base = int(w * .075), int(h * .80)
    for i, (cloth, label, rb) in enumerate(zip(cloths, labels, ribbons)):
        nb = notebook(nw, nh, cloth, label, rb)
        tilt = (-2.5, 1.5, -1.0)[i]
        nb = nb.rotate(tilt, Image.BICUBIC, expand=True, fillcolor=INK)
        sh = Image.new("L", (nb.width + 40 * S, nb.height + 40 * S), 0)
        ImageDraw.Draw(sh).rectangle((20 * S, 24 * S, nb.width + 10 * S, nb.height + 30 * S), fill=150)
        sh = sh.filter(ImageFilter.GaussianBlur(14 * S))
        bg.paste(Image.new("RGB", sh.size, (0, 0, 0)), (x - 20 * S, base - nb.height - 20 * S), sh)
        bg.paste(nb, (x, base - nb.height))
        x += int(nw * 1.22)
    d = ImageDraw.Draw(bg)
    d.line((int(w * .06), base + 4 * S, int(w * .56), base + 4 * S), fill=(60, 58, 55), width=3 * S)

    # the wordmark: MonoSpace and the accent cursor, as the app's header draws it.
    # Sized to the column it has, so neither the word nor the cursor can run off the edge.
    tx = int(w * .60)
    room = int(w * .93) - tx
    size = int(h * .135)
    while size > 20:
        ft = font("schibstedgrotesk-400-800-n-latin.woff2", size, 800)
        if ft.getlength("MonoSpace") + size * .30 <= room:
            break
        size -= 2
    ty = int(h * .38)
    d.text((tx, ty), "MonoSpace", font=ft, fill=PAPER)
    tw = ft.getlength("MonoSpace")
    cw, ch = int(size * .20), int(size * .66)
    d.rectangle((tx + tw + int(size * .10), ty + int(size * .32),
                 tx + tw + int(size * .10) + cw, ty + int(size * .32) + ch), fill=ACCENT)

    line = "A STUDY APP THAT RUNS ON YOUR OWN PC"
    fsize = int(17 * S)
    while fsize > 9 and sum(font("ibmplexmono-400-latin.woff2", fsize).getlength(c) for c in line) > tw:
        fsize -= 1
    fs = font("ibmplexmono-400-latin.woff2", fsize)
    track_s = max(0.0, (tw - sum(fs.getlength(c) for c in line)) / (len(line) - 1))
    base_y = ty + int(size * 1.30)
    tracked(d, tx, base_y, line, fs, track_s, (176, 171, 163))
    d.line((tx, base_y + int(size * .52), tx + 56 * S, base_y + int(size * .52)), fill=ACCENT, width=3 * S)
    foot = "OFFLINE  ·  NO ACCOUNT  ·  WINDOWS"
    fl = font("ibmplexmono-400-latin.woff2", int(14 * S))
    while sum(fl.getlength(c) for c in foot) + 2.6 * S * (len(foot) - 1) > tw and fl.size > 8:
        fl = font("ibmplexmono-400-latin.woff2", fl.size - 1)
    tracked(d, tx, base_y + int(size * .78), foot, fl, 2.6 * S, MUTED)
    return bg.resize((W, H), Image.LANCZOS)


# ---- the app icon (2026-10-06): "M" and the accent cursor, matching the header logo ----------
# Drawn as shapes on a 32-unit grid (the header's wordmark + caret, as a monogram), supersampled,
# so every size is crisp. The orb artwork still makes logo-*.png (the loading screen).
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
