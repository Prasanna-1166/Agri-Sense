#!/usr/bin/env python3
"""
Generate AgriSense AI's brand images into static/img/:

    favicon.svg, favicon.ico, apple-touch-icon.png,
    icon-192.png, icon-512.png, og-image.png (1200x630 social-share card)

The images are drawn from a few lines of geometry (a sprout on the app's
canopy-green), so they can be regenerated at any time after a branding change:

    python scripts/generate_brand_assets.py

Requires Pillow (already a project dependency). Fonts are optional: DejaVu is
used if present, otherwise Pillow's built-in font (the text just looks plainer).
"""
import os

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "img")
CANOPY, CANOPY_LIGHT = (31, 61, 43), (46, 85, 64)      # --color-canopy / -light
WHEAT, CREAM = (201, 162, 39), (241, 244, 238)          # --color-wheat / --color-sage-bg

# Sprout geometry in a 512x512 box: stem + two leaves. A leaf is (start, end, bulge).
STEM = ((256, 438), (256, 236))
LEAVES = [((256, 336), (84, 168), 46, WHEAT), ((256, 296), (428, 124), 46, CREAM)]


def _lens(a, b, bulge):
    """Control points of the two curved sides of a leaf from a to b."""
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = (dx * dx + dy * dy) ** 0.5
    nx, ny = -dy / length, dx / length
    return (mx + nx * bulge * 2, my + ny * bulge * 2), (mx - nx * bulge * 2, my - ny * bulge * 2)


def _bezier(p0, c, p2, steps=24):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p2[1])
            for t in (i / steps for i in range(steps + 1))]


def draw_sprout(draw, scale, ox, oy, supersample=1):
    k = scale * supersample
    P = lambda p: (ox * supersample + p[0] * k, oy * supersample + p[1] * k)
    draw.line([P(STEM[0]), P(STEM[1])], fill=CREAM, width=max(2, int(30 * k)))
    for a, b, bulge, color in LEAVES:
        c1, c2 = _lens(a, b, bulge)
        pts = _bezier(a, c1, b) + _bezier(b, c2, a)[1:]
        draw.polygon([P(p) for p in pts], fill=color)


def icon(size, outline=False):
    s = 4  # supersample for smooth edges
    img = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size * s - 1, size * s - 1], radius=int(size * s * 0.22), fill=CANOPY,
                        outline=WHEAT if outline else None, width=int(size * s * 0.025) if outline else 0)
    draw_sprout(d, size / 512, 0, 0, supersample=s)
    return img.resize((size, size), Image.LANCZOS)


def font(names, size):
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def og_image():
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), CANOPY)
    d = ImageDraw.Draw(img)
    for x in range(W):                       # soft left-to-right lightening
        t = x / W
        col = tuple(int(CANOPY[i] + (CANOPY_LIGHT[i] - CANOPY[i]) * t) for i in range(3))
        d.line([(x, 0), (x, H)], fill=col)
    tile = icon(230, outline=True)
    img.paste(tile, (90, 150), tile)

    serif = ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", "DejaVuSerif-Bold.ttf"]
    sans = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"]
    d.text((360, 140), "AgriSense AI", font=font(serif, 92), fill=CREAM)
    d.rectangle([362, 262, 362 + 150, 268], fill=WHEAT)
    f = font(sans, 38)
    d.text((360, 296), "Smart crop recommendation, yield and", font=f, fill=CREAM)
    d.text((360, 346), "cost planning for farms in", font=f, fill=CREAM)
    d.text((360, 396), "Andhra Pradesh & Telangana", font=f, fill=WHEAT)
    d.text((90, 548), "Sourced data  ·  Honest estimates  ·  Free to use", font=font(sans, 28),
           fill=(200, 212, 196))
    return img


def svg_icon():
    parts = []
    for a, b, bulge, color in LEAVES:
        c1, c2 = _lens(a, b, bulge)
        hexcol = "#%02X%02X%02X" % color
        parts.append(f'<path d="M{a[0]} {a[1]} Q{c1[0]:.1f} {c1[1]:.1f} {b[0]} {b[1]} '
                     f'Q{c2[0]:.1f} {c2[1]:.1f} {a[0]} {a[1]}Z" fill="{hexcol}"/>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="AgriSense AI">'
            '<rect width="512" height="512" rx="113" fill="#1F3D2B"/>'
            f'<line x1="{STEM[0][0]}" y1="{STEM[0][1]}" x2="{STEM[1][0]}" y2="{STEM[1][1]}" '
            'stroke="#F1F4EE" stroke-width="30" stroke-linecap="butt"/>' + "".join(parts) + "</svg>\n")


def main():
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "favicon.svg"), "w").write(svg_icon())
    icon(512).save(os.path.join(OUT, "icon-512.png"))
    icon(192).save(os.path.join(OUT, "icon-192.png"))
    icon(180).save(os.path.join(OUT, "apple-touch-icon.png"))
    icon(64).save(os.path.join(OUT, "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    og_image().save(os.path.join(OUT, "og-image.png"), optimize=True)
    for name in sorted(os.listdir(OUT)):
        print(f"  {name:22s} {os.path.getsize(os.path.join(OUT, name)):>8,} bytes")


if __name__ == "__main__":
    main()
