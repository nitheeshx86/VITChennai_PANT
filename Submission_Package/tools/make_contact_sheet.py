"""Build contact_sheet.png from renders/ + metadata.json (needs Pillow).

    python tools/make_contact_sheet.py [bundle_dir]

Layout: 5 x 2 grid, frame order left-to-right, top-to-bottom. Each tile is labelled with the
frame number, theta, h and v. The submitted renders themselves are never modified.
"""
import json
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TILE = 512
COLS, ROWS = 5, 2
LABEL_H = 64


def font(size):
    for name in ("arial.ttf", "DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    with open(os.path.join(ROOT, "metadata.json")) as f:
        meta = json.load(f)
    sheet = Image.new("RGB", (COLS * TILE, ROWS * (TILE + LABEL_H)), (18, 18, 20))
    draw = ImageDraw.Draw(sheet)
    f_big, f_small = font(24), font(19)
    for rec in meta:
        k = rec["frame"]
        img = Image.open(os.path.join(ROOT, "renders", "frame_%02d.png" % k)).convert("RGB")
        img = img.resize((TILE, TILE), Image.LANCZOS)
        x, y = (k % COLS) * TILE, (k // COLS) * (TILE + LABEL_H)
        sheet.paste(img, (x, y + LABEL_H))
        draw.text((x + 10, y + 6), "frame %02d" % k, fill=(255, 255, 255), font=f_big)
        draw.text((x + 10, y + 36), "theta = %.4f rad (%d deg)   h = %+.3f   v = %+.3f" % (
            rec["theta"], round(math.degrees(rec["theta"])), rec["input"]["h"], rec["input"]["v"]),
            fill=(190, 200, 210), font=f_small)
        draw.rectangle([x, y, x + TILE - 1, y + TILE + LABEL_H - 1], outline=(60, 60, 66))
    out = os.path.join(ROOT, "contact_sheet.png")
    sheet.save(out, optimize=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
