"""Compose direction_check/sheet.png from the five direction renders (needs Pillow).

    python tools/make_direction_sheet.py [bundle_dir]

Each row is one pose; each row shows both eyes zoomed 3x. A fixed white crosshair marks where
the pupil centre is at Reset; a coloured arrow goes from there to the pupil centre in this pose
(values from the metadata, which the tests verify against the pixels), with the shift in px.
"""
import json
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "direction_check")
ZOOM = 2.4
HALF_W, HALF_H = 112, 58          # crop half-size around each eye's reset pupil, source pixels
ORDER = ["reset", "left", "right", "up", "down"]
COLOURS = {"reset": (255, 255, 255), "left": (80, 200, 255), "right": (255, 170, 60),
           "up": (120, 255, 120), "down": (255, 110, 200)}
EXPECT = {"reset": "centre", "left": "pupils move to image-left", "right": "pupils move to image-right",
          "up": "pupils move up", "down": "pupils move down"}


def font(size):
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def arrow(draw, x0, y0, x1, y1, col, w=3):
    draw.line([(x0, y0), (x1, y1)], fill=col, width=w)
    ang = math.atan2(y1 - y0, x1 - x0)
    for s in (-1, 1):
        a = ang + math.pi + s * math.radians(28)
        draw.line([(x1, y1), (x1 + 14 * math.cos(a), y1 + 14 * math.sin(a))], fill=col, width=w)


def main():
    with open(os.path.join(DIR, "metadata.json")) as f:
        recs = {r["pose"]: r for r in json.load(f)}
    base = {s: recs["reset"]["pupil_center_2D_" + s] for s in "LR"}
    tile_w, tile_h = int(2 * HALF_W * ZOOM), int(2 * HALF_H * ZOOM)
    label_w = 300
    sheet = Image.new("RGB", (label_w + 2 * tile_w + 12, len(ORDER) * (tile_h + 8) + 70), (16, 16, 18))
    d = ImageDraw.Draw(sheet)
    f_big, f_mid, f_small = font(30), font(20), font(17)
    d.text((14, 16), "Direction check: pupil centre vs Reset (white crosshair)", fill=(255, 255, 255), font=f_mid)
    d.text((label_w, 44), "avatar's right eye (R)", fill=(170, 170, 180), font=f_small)
    d.text((label_w + tile_w + 12, 44), "avatar's left eye (L)", fill=(170, 170, 180), font=f_small)
    for row, pose in enumerate(ORDER):
        rec = recs[pose]
        img = Image.open(os.path.join(DIR, pose + ".png")).convert("RGB")
        y = 70 + row * (tile_h + 8)
        col = COLOURS[pose]
        d.text((14, y + 14), pose.upper(), fill=col, font=f_big)
        d.text((14, y + 54), "h=%+.0f  v=%+.0f" % (rec["input"]["h"], rec["input"]["v"]), fill=(200, 200, 205), font=f_small)
        d.text((14, y + 78), EXPECT[pose], fill=(150, 150, 160), font=f_small)
        for k, s in enumerate("RL"):
            bx, by = base[s]
            crop = img.crop((int(bx) - HALF_W, int(by) - HALF_H, int(bx) + HALF_W, int(by) + HALF_H))
            crop = crop.resize((tile_w, tile_h), Image.LANCZOS)
            cd = ImageDraw.Draw(crop)
            ox, oy = (bx - (int(bx) - HALF_W)) * ZOOM, (by - (int(by) - HALF_H)) * ZOOM
            cd.line([(ox - 26, oy), (ox + 26, oy)], fill=(255, 255, 255), width=1)
            cd.line([(ox, oy - 26), (ox, oy + 26)], fill=(255, 255, 255), width=1)
            px, py = rec["pupil_center_2D_" + s]
            dx, dy = px - bx, py - by
            tx, ty = ox + dx * ZOOM, oy + dy * ZOOM
            if pose != "reset":
                arrow(cd, ox, oy, tx, ty, col)
            cd.ellipse([tx - 4, ty - 4, tx + 4, ty + 4], outline=col, width=2)
            cd.text((8, tile_h - 26), "dx=%+.1f px  dy=%+.1f px" % (dx, dy), fill=col, font=f_small)
            sheet.paste(crop, (label_w + k * (tile_w + 12), y))
    out = os.path.join(DIR, "sheet.png")
    sheet.save(out, optimize=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
