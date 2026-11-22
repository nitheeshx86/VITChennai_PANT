"""Animated flip between Reset and each direction: direction_check/directions.gif (needs Pillow).

    python tools/make_direction_gif.py [bundle_dir]

The eye region of the five direction renders (unmodified pixels, no markers) cycles
Reset -> Left -> Reset -> Right -> Reset -> Up -> Reset -> Down, with a caption. Flipping between
frames is how a person sees a ~15 px pupil shift most easily. A thin fixed white tick above and
below/beside each eye marks the Reset pupil centre, so the movement can be judged against it.
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "direction_check")
SEQUENCE = ["reset", "left", "reset", "right", "reset", "up", "reset", "down"]
CAPTION = {"reset": "RESET  eyes.reset()", "left": "LEFT  eyes.move(-1, 0)", "right": "RIGHT  eyes.move(+1, 0)",
           "up": "UP  eyes.move(0, +1)", "down": "DOWN  eyes.move(0, -1)"}
MARGIN_X, HALF_H = 120, 105        # crop: both eyes plus this margin, source pixels
SCALE = 1.0
HOLD_MS = 700


def font(size):
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    with open(os.path.join(DIR, "metadata.json")) as f:
        recs = {r["pose"]: r for r in json.load(f)}
    ref = recs["reset"]
    xs = [ref["pupil_center_2D_" + s][0] for s in "LR"]
    yc = 0.5 * sum(ref["pupil_center_2D_" + s][1] for s in "LR")
    box = (int(min(xs) - MARGIN_X), int(yc - HALF_H), int(max(xs) + MARGIN_X), int(yc + HALF_H))
    cap_h = 44
    f_big = font(26)
    frames = []
    for pose in SEQUENCE:
        crop = Image.open(os.path.join(DIR, pose + ".png")).convert("RGB").crop(box)
        if SCALE != 1.0:
            crop = crop.resize((int(crop.width * SCALE), int(crop.height * SCALE)), Image.LANCZOS)
        canvas = Image.new("RGB", (crop.width, crop.height + cap_h), (16, 16, 20))
        canvas.paste(crop, (0, cap_h))
        d = ImageDraw.Draw(canvas)
        d.text((14, 8), CAPTION[pose], fill=(255, 255, 255), font=f_big)
        # fixed reference ticks at the Reset pupil centre (outside the iris, so nothing is hidden)
        for s in "LR":
            x = (ref["pupil_center_2D_" + s][0] - box[0]) * SCALE
            y = (ref["pupil_center_2D_" + s][1] - box[1]) * SCALE + cap_h
            r0, r1 = 70 * SCALE, 86 * SCALE
            d.line([(x, y - r1), (x, y - r0)], fill=(255, 255, 255), width=2)
            d.line([(x, y + r0), (x, y + r1)], fill=(255, 255, 255), width=2)
            d.line([(x - r1, y), (x - r0, y)], fill=(255, 255, 255), width=2)
            d.line([(x + r0, y), (x + r1, y)], fill=(255, 255, 255), width=2)
        frames.append(canvas.quantize(colors=255, method=Image.MEDIANCUT, dither=Image.NONE))
    out = os.path.join(DIR, "directions.gif")
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=HOLD_MS, loop=0, optimize=True)
    print("wrote", out, "(%dx%d, %d frames)" % (frames[0].width, frames[0].height, len(frames)))


if __name__ == "__main__":
    main()
