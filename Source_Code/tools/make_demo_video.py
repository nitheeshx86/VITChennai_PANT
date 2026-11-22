"""Assemble the demo video (1920x1080, 30 fps, H.264, no audio) from the demo frames.

    python tools/make_demo_video.py [--out demo/VITChennai_PANT_demo.mp4] [--preview SECONDS ...]

Needs the frames from tools/render_demo.py, the shipped renders / metadata / contact sheet,
the logs debug/final_render.log (real run_sequence output) and debug/demo_tests.log (a fresh
tests/run_all.py run), Pillow, numpy and ffmpeg on the PATH. --preview writes PNG stills at
the given times instead of the video, for checking the layout.
"""
import json
import math
import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FR = os.path.join(ROOT, "demo", "frames")
W, H, FPS = 1920, 1080, 30

BG = (14, 16, 21)
PANEL = (24, 27, 34)
TEXT = (236, 239, 243)
GREY = (150, 158, 170)
ACCENT = (53, 208, 186)       # teal
ORANGE = (255, 159, 67)
GREEN = (80, 230, 120)
RED = (255, 99, 99)

FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
_fonts = {}


def font(name, size):
    key = (name, size)
    if key not in _fonts:
        files = {"regular": "segoeui.ttf", "semibold": "seguisb.ttf", "bold": "segoeuib.ttf",
                 "light": "segoeuil.ttf", "mono": "consola.ttf", "monobold": "consolab.ttf"}
        try:
            _fonts[key] = ImageFont.truetype(os.path.join(FONT_DIR, files[name]), size)
        except OSError:
            _fonts[key] = ImageFont.load_default()
    return _fonts[key]


_images = {}


def img(path, size=None):
    key = (path, size)
    if key not in _images:
        im = Image.open(path).convert("RGB")
        if size:
            im = im.resize(size, Image.LANCZOS)
        if len(_images) > 600:
            _images.clear()
        _images[key] = im
    return _images[key]


def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def text(d, xy, s, size=28, kind="regular", fill=TEXT, anchor="la"):
    d.text(xy, s, font=font(kind, size), fill=fill, anchor=anchor)


def wrap(d, xy, s, width, size=28, kind="regular", fill=TEXT, spacing=1.35):
    words, line, y = s.split(), "", xy[1]
    f = font(kind, size)
    for w in words:
        trial = (line + " " + w).strip()
        if d.textlength(trial, font=f) > width and line:
            d.text((xy[0], y), line, font=f, fill=fill)
            y += int(size * spacing)
            line = w
        else:
            line = trial
    if line:
        d.text((xy[0], y), line, font=f, fill=fill)
        y += int(size * spacing)
    return y


def footer(d):
    text(d, (W - 40, H - 30), "Team PANT  ·  VIT Chennai  ·  Samsung XR Hackathon 2026  ·  Track 1",
         17, fill=(110, 118, 130), anchor="rs")


def header(d, x, title, subtitle=None):
    text(d, (x, 52), title, 44, "semibold")
    if subtitle:
        text(d, (x, 112), subtitle, 23, fill=GREY)


def faded(frames, n_in=9, n_out=9):
    """Fade a list of frames in from and out to black."""
    out = []
    total = len(frames)
    for i, f in enumerate(frames):
        a = min(1.0, (i + 1) / n_in if n_in else 1.0, (total - i) / n_out if n_out else 1.0)
        out.append(f if a >= 1.0 else Image.blend(Image.new("RGB", (W, H), (0, 0, 0)), f, a))
    return out


# --------------------------------------------------------------------------- shared data
META = json.load(open(os.path.join(ROOT, "metadata.json")))


def timeline(seg):
    with open(os.path.join(FR, seg, "timeline.json")) as f:
        return json.load(f)["frames"]


DIR_TL = timeline("directions")
RESET = {s: DIR_TL[0]["pupil_" + s] for s in "LR"}          # reset pupil centres, 1024 px
INSET_HALF = (124, 88)
INSET_SCALE = 1.5
SCALE_MAIN = H / 1024.0


def eye_insets(src, pupils=None, ticks=True, size=None):
    """Two zoomed eye crops (image-left eye = R first) around the Reset pupil centres, with fixed
    ticks marking the Reset centre and optional gapped crosses at labelled pupil centres."""
    hx, hy = INSET_HALF
    k = INSET_SCALE
    tiles = []
    for s in ("R", "L"):
        cx, cy = RESET[s]
        tile = src.crop((int(cx - hx), int(cy - hy), int(cx + hx), int(cy + hy))).resize(
            (int(2 * hx * k), int(2 * hy * k)), Image.LANCZOS)
        d = ImageDraw.Draw(tile)
        tw, th = tile.size
        rx, ry = (cx - int(cx - hx)) * k, (cy - int(cy - hy)) * k
        if ticks:
            for (a, b) in (((rx, 0), (rx, 16)), ((rx, th - 16), (rx, th)),
                           ((0, ry), (16, ry)), ((tw - 16, ry), (tw, ry))):
                d.line([a, b], fill=(255, 255, 255), width=3)
        if pupils:
            px, py = pupils[s]
            px, py = (px - int(cx - hx)) * k, (py - int(cy - hy)) * k
            gap, arm = 38, 16
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                d.line([(px + dx * gap, py + dy * gap), (px + dx * (gap + arm), py + dy * (gap + arm))],
                       fill=GREEN, width=3)
        tiles.append(tile)
    return tiles


def paste_insets(canvas, d, tiles, x, y, labels=("eye R (avatar's right)", "eye L (avatar's left)")):
    for i, t in enumerate(tiles):
        tx = x + i * (t.size[0] + 18)
        canvas.paste(t, (tx, y))
        d.rectangle([tx - 1, y - 1, tx + t.size[0], y + t.size[1]], outline=(60, 66, 78), width=2)
        text(d, (tx, y + t.size[1] + 10), labels[i], 18, fill=GREY)
    return y + tiles[0].size[1] + 40


def target_plot(d, x, y, h, v, size=190):
    d.rectangle([x, y, x + size, y + size], outline=(70, 76, 88), width=2)
    c = size / 2
    d.line([(x + c, y), (x + c, y + size)], fill=(50, 55, 65), width=1)
    d.line([(x, y + c), (x + size, y + c)], fill=(50, 55, 65), width=1)
    px, py = x + c + h * (c - 10), y + c - v * (c - 10)
    d.ellipse([px - 9, py - 9, px + 9, py + 9], fill=ORANGE)
    text(d, (x + size + 18, y + 6), "fixation target", 20, "semibold")
    text(d, (x + size + 18, y + 34), "on the plane 35 cm ahead", 18, fill=GREY)
    text(d, (x + size + 18, y + 58), "square = ±5 cm", 18, fill=GREY)
    text(d, (x + size + 18, y + 96), "h = %+.3f" % h, 22, "mono")
    text(d, (x + size + 18, y + 126), "v = %+.3f" % v, 22, "mono")


def readout_block(d, x, y, fr):
    rows = [
        ("eye R", "yaw %+5.1f°  pitch %+5.1f°" % (fr["yaw_R"], fr["pitch_R"])),
        ("eye L", "yaw %+5.1f°  pitch %+5.1f°" % (fr["yaw_L"], fr["pitch_L"])),
        ("vergence", "%.2f°" % fr["vergence_deg"]),
        ("pupil shift", "R %+5.1f, %+5.1f px   L %+5.1f, %+5.1f px" % (
            fr["pupil_R"][0] - RESET["R"][0], fr["pupil_R"][1] - RESET["R"][1],
            fr["pupil_L"][0] - RESET["L"][0], fr["pupil_L"][1] - RESET["L"][1])),
    ]
    for i, (k, v) in enumerate(rows):
        text(d, (x, y + i * 36), k, 21, fill=GREY)
        text(d, (x + 150, y + i * 36), v, 21, "mono")
    text(d, (x, y + len(rows) * 36 + 4), "line of sight from straight ahead (yaw > 0 = image right, pitch > 0 = up); at Reset the eyes already converge ±5°",
         16, fill=(110, 118, 130))
    return y + len(rows) * 36 + 30


def live_frame(src_path, fr, title, subtitle, cmd, label_extra=None):
    canvas = Image.new("RGB", (W, H), BG)
    canvas.paste(img(src_path, (H, H)), (0, 0))
    d = ImageDraw.Draw(canvas)
    x = H + 40
    header(d, x, title, subtitle)
    d.rounded_rectangle([x, 160, W - 40, 236], 12, fill=PANEL)
    text(d, (x + 22, 198), cmd, 34, "monobold", fill=ACCENT, anchor="lm")
    if label_extra:
        text(d, (W - 62, 198), label_extra, 30, "bold", fill=ORANGE, anchor="rm")
    src = img(src_path)
    y = paste_insets(canvas, d, eye_insets(src), x, 262)
    y = readout_block(d, x, y + 4, fr)
    target_plot(d, x, y + 14, fr["h"], fr["v"])
    footer(d)
    return canvas


# --------------------------------------------------------------------------- segments
TITLE_IMAGE = os.path.join(ROOT, "first_image", "image.png")
TITLE_CROP = (60, 118, 1025, 835)      # the clean viewport area of the Blender screenshot


def seg_title():
    """Image on the left (fading into the background), all the text on the right."""
    src = Image.open(TITLE_IMAGE).convert("RGB").crop(TITLE_CROP)
    iw = 1180
    ih = int(src.size[1] * iw / src.size[0])
    pic = src.resize((iw, ih), Image.LANCZOS)
    base = Image.new("RGB", (W, H), BG)
    y0 = (H - ih) // 2
    base.paste(pic, (0, y0))
    # soft fade of the picture's right, top and bottom edges into the background
    import numpy as np
    xs = np.arange(W, dtype=float)[None, :]
    ys = np.arange(H, dtype=float)[:, None]
    right = np.clip((xs - (iw - 220)) / 220.0, 0, 1) ** 1.4
    top = np.clip(1 - (ys - y0) / 80.0, 0, 1) ** 1.4
    bottom = np.clip(1 - (y0 + ih - 1 - ys) / 80.0, 0, 1) ** 1.4
    alpha = np.maximum(right, np.maximum(top, bottom))
    mask = Image.fromarray((alpha * 255).astype("uint8"), "L")
    base.paste(Image.new("RGB", (W, H), BG), (0, 0), mask)
    d = ImageDraw.Draw(base)
    x = 1200
    y = 300
    y = wrap(d, (x, y), "SAMSUNG R&D INSTITUTE INDIA · XR HACKATHON 2026 · TRACK 1", 660, 19, "semibold", fill=ACCENT)
    y += 18
    for line in ("Synthetic Eye Movement", "& Virtual Camera", "Rendering"):
        text(d, (x, y), line, 56, "bold")
        y += 68
    y += 14
    y = wrap(d, (x, y), "A calibrated, photoreal gaze-data generator in Blender", 640, 26, fill=GREY)
    y += 46
    text(d, (x, y), "Team PANT  ·  VIT Chennai", 32, "semibold")
    y += 52
    text(d, (x, y), "Nitheesh K.  ·  Adithya K.", 24, fill=GREY)
    text(d, (x, y + 34), "Pariksith S.S.  ·  Tarun Ashwat M.", 24, fill=GREY)
    return faded([base] * int(4.5 * FPS), 12, 10)


def seg_problem():
    bullets = [
        ("XR headsets estimate gaze with learned models.", 0.3),
        ("Those models need huge, precisely labelled eye datasets.", 1.6),
        ("Real eye capture is slow, costly and privacy-restricted.", 2.9),
        ("Our rig renders a photoreal face whose eyes are driven by code,", 4.4),
        ("with exact ground truth for every image.", 4.4),
    ]
    sheet = img(os.path.join(ROOT, "contact_sheet.png"), (880, 396))
    frames = []
    for i in range(int(9 * FPS)):
        t = i / FPS
        c = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(c)
        header(d, 110, "The problem", "why synthetic eye data")
        y = 260
        for j, (s, t0) in enumerate(bullets):
            a = ease((t - t0) / 0.5)
            if a <= 0:
                continue
            col = tuple(int(BG[k] + (TEXT[k] - BG[k]) * a) for k in range(3))
            if j < 3:
                d.ellipse([110, y + 14, 122, y + 26], fill=tuple(int(BG[k] + (GREY[k] - BG[k]) * a) for k in range(3)))
                text(d, (145, y), s, 34, fill=col)
                y += 70
            else:
                if j == 3:
                    y += 40
                acc = tuple(int(BG[k] + (ACCENT[k] - BG[k]) * a) for k in range(3))
                text(d, (110, y), s, 36, "semibold", fill=acc)
                y += 54
        a = ease((t - 4.6) / 0.8)
        if a > 0:
            c.paste(Image.blend(Image.new("RGB", sheet.size, BG), sheet, a), (950, 640))
            text(d, (950, 1050), "the official 10-frame output, with metadata", 18, fill=GREY, anchor="ls")
        footer(d)
        frames.append(c)
    return faded(frames)


def seg_calibration():
    meta0 = META[0]
    ipd_mm = 61.94
    frames = []
    view = img(os.path.join(ROOT, "direction_check", "reset.png"), (620, 620))
    for i in range(int(11.5 * FPS)):
        t = i / FPS
        c = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(c)
        header(d, 80, "Calibrated scene", "real-world metric scale · top view, to scale (1 cm = 21 px)")
        k = 21.0
        mx, my = 200, 560
        h = math.sin(2 * math.pi * max(0.0, t - 1.0) / 4.0)
        # head outline and eyes
        d.arc([mx - 230, my - 160, mx + 70, my + 160], -70, 70, fill=(90, 96, 110), width=3)
        eyes_y = {"L": my - ipd_mm / 20 * k, "R": my + ipd_mm / 20 * k}
        tx, ty = mx + 35 * k, my - h * 5 * k          # +h = toward the avatar's left = up here
        cx = mx + 40 * k
        for s, ey in eyes_y.items():
            d.line([(mx, ey), (tx, ty)], fill=GREEN if s == "L" else ORANGE, width=2)
        for s, ey in eyes_y.items():
            r = 1.25 * k
            d.ellipse([mx - r, ey - r, mx + r, ey + r], fill=(235, 230, 226), outline=(120, 120, 120))
            d.ellipse([mx + r - 9, ey - 6, mx + r + 1, ey + 6], fill=(40, 70, 110))
            text(d, (mx - 52, ey), s, 24, "bold", fill=GREY, anchor="mm")
        d.ellipse([mx - 4, my - 4, mx + 4, my + 4], fill=TEXT)
        text(d, (mx + 12, my + 8), "M", 22, "semibold")
        # target plane and range
        d.line([(tx, my - 5 * k - 40), (tx, my + 5 * k + 40)], fill=(70, 76, 88), width=2)
        d.line([(tx, my - 5 * k), (tx, my + 5 * k)], fill=ORANGE, width=5)
        d.ellipse([tx - 10, ty - 10, tx + 10, ty + 10], fill=ORANGE)
        text(d, (tx - 14, my - 5 * k - 52), "fixation plane", 20, fill=GREY, anchor="rs")
        text(d, (tx + 18, my - 5 * k), "+5 cm", 18, fill=ORANGE, anchor="lm")
        text(d, (tx + 18, my + 5 * k), "−5 cm", 18, fill=ORANGE, anchor="lm")
        # camera (looks back at M)
        d.polygon([(cx, my), (cx + 46, my - 26), (cx + 46, my + 26)], fill=(80, 140, 255))
        d.rectangle([cx + 46, my - 20, cx + 86, my + 20], fill=(80, 140, 255))
        text(d, (cx + 4, my + 50), "camera", 20, "semibold", anchor="mt")
        text(d, (cx + 4, my + 76), "locked", 18, fill=GREY, anchor="mt")
        # dimensions
        for dist, yy, lab in ((35, my + 190, "35 cm  fixation target"), (40, my + 250, "40 cm  render camera")):
            x1 = mx + dist * k
            d.line([(mx, yy), (x1, yy)], fill=GREY, width=2)
            d.line([(mx, yy - 10), (mx, yy + 10)], fill=GREY, width=2)
            d.line([(x1, yy - 10), (x1, yy + 10)], fill=GREY, width=2)
            text(d, ((mx + x1) / 2, yy - 10), lab, 21, "semibold", anchor="ms")
        facts = ["inter-pupillary distance 61.9 mm", "eyeball diameter 25.0 mm",
                 "140 mm lens · 1024 × 1024 px", "vergence at Reset %.1f°" % meta0.get("vergence_angle_deg", 10.0)]
        for j, f in enumerate(facts):
            a = ease((t - 0.6 - 0.5 * j) / 0.5)
            if a > 0:
                text(d, (80, 200 + j * 38), "·  " + f, 25,
                     fill=tuple(int(BG[q] + (TEXT[q] - BG[q]) * a) for q in range(3)))
        c.paste(view, (1240, 230))
        d.rectangle([1239, 229, 1860, 850], outline=(60, 66, 78), width=2)
        text(d, (1240, 878), "what the locked camera sees (Reset)", 20, fill=GREY)
        footer(d)
        frames.append(c)
    return faded(frames)


def seg_directions():
    out = []
    for fr in DIR_TL:
        p = os.path.join(FR, "directions", fr["png"])
        out.append(live_frame(p, fr, "Direction check", "Left · Right · Up · Down · Reset  —  camera locked at 40 cm",
                              fr["cmd"], fr["phase"].upper()))
    return faded(out)


def seg_rotation():
    main = timeline("pursuit")
    xray = timeline("xray")
    out = []
    for loop in range(2):
        for fr, xr in zip(main, xray):
            c = Image.new("RGB", (W, H), BG)
            c.paste(img(os.path.join(FR, "pursuit", fr["png"]), (H, H)), (0, 0))
            d = ImageDraw.Draw(c)
            x = H + 40
            header(d, x, "True 3D eyeball rotation", "same motion with the face hidden")
            c.paste(img(os.path.join(FR, "xray", xr["png"]), (760, 760)), (x, 160))
            d.rectangle([x - 1, 159, x + 760, 920], outline=(60, 66, 78), width=2)
            d.line([(x, 945), (x + 40, 945)], fill=(140, 235, 200), width=5)
            text(d, (x + 52, 945), "eye L line of sight", 20, anchor="lm")
            d.line([(x + 300, 945), (x + 340, 945)], fill=(240, 215, 110), width=5)
            text(d, (x + 352, 945), "eye R line of sight", 20, anchor="lm")
            text(d, (x, 972), "Rigid spheres turning about their centres; both lines meet at the target",
                 19, fill=GREY)
            text(d, (x, 998), "35 cm ahead.  h = %+.2f   v = %+.2f   vergence %.2f°" % (fr["h"], fr["v"], fr["vergence_deg"]),
                 19, "mono", fill=GREY)
            footer(d)
            out.append(c)
    return faded(out)


def seg_sequence():
    reset_L = RESET["L"]
    out = []
    hold = int(1.1 * FPS)
    for k, rec in enumerate(META):
        path = os.path.join(ROOT, "renders", "frame_%02d.png" % k)
        for i in range(hold):
            c = Image.new("RGB", (W, H), BG)
            c.paste(img(path, (H, H)), (0, 0))
            d = ImageDraw.Draw(c)
            x = H + 40
            header(d, x, "Official 10-frame sequence", "θk = 2πk/10,  h = sin θk,  v = cos θk  ·  clockwise from the top")
            d.rounded_rectangle([x, 160, W - 40, 236], 12, fill=PANEL)
            text(d, (x + 22, 198), "frame_%02d.png" % k, 32, "monobold", fill=ACCENT, anchor="lm")
            text(d, (W - 62, 198), "θ %.3f   h %+.3f   v %+.3f" % (rec["theta"], rec["input"]["h"], rec["input"]["v"]),
                 24, "mono", anchor="rm")
            pupils = {s: rec["pupil_center_2D_" + s] for s in "LR"}
            y = paste_insets(c, d, eye_insets(img(path), pupils), x, 262)
            text(d, (x, y - 6), "green = metadata pupil_center_2D (camera_matrix · pupil 3D)", 17, fill=GREEN)
            # pupil path of eye L (offsets from Reset, x5)
            bx, by, bs = x, y + 30, 230
            d.rectangle([bx, by, bx + bs, by + bs], outline=(70, 76, 88), width=2)
            cxp, cyp = bx + bs / 2, by + bs / 2
            d.line([(cxp - 6, cyp), (cxp + 6, cyp)], fill=GREY, width=1)
            d.line([(cxp, cyp - 6), (cxp, cyp + 6)], fill=GREY, width=1)
            pts = [(cxp + (META[j]["pupil_center_2D_L"][0] - reset_L[0]) * 5.5,
                    cyp + (META[j]["pupil_center_2D_L"][1] - reset_L[1]) * 5.5) for j in range(k + 1)]
            if len(pts) > 1:
                d.line(pts, fill=ACCENT, width=2)
            for j, (px, py) in enumerate(pts):
                r = 8 if j == k else 5
                d.ellipse([px - r, py - r, px + r, py + r], fill=ORANGE if j == k else ACCENT)
                text(d, (px + (px - cxp) * 0.22, py + (py - cyp) * 0.22), str(j), 15, "semibold", fill=GREY, anchor="mm")
            text(d, (bx, by + bs + 12), "eye L pupil path (×5.5)", 17, fill=GREY)
            # JSON excerpt
            jx = bx + bs + 30
            lines = ['{ "frame": %d,' % rec["frame"],
                     '  "theta": %.7f,' % rec["theta"],
                     '  "input": {"h": %.4f, "v": %.4f},' % (rec["input"]["h"], rec["input"]["v"]),
                     '  "eye_rotation_L": [%.4f, %.4f, %.4f],' % tuple(rec["eye_rotation_L"]),
                     '  "eye_rotation_R": [%.4f, %.4f, %.4f],' % tuple(rec["eye_rotation_R"]),
                     '  "pupil_center_2D_L": [%.2f, %.2f],' % tuple(rec["pupil_center_2D_L"]),
                     '  "pupil_center_2D_R": [%.2f, %.2f],' % tuple(rec["pupil_center_2D_R"]),
                     '  "camera_matrix": [[%.1f, ...], ...],' % rec["camera_matrix"][0][0],
                     '  ... + 40 extra keys }']
            d.rounded_rectangle([jx, by, W - 40, by + bs + 40], 10, fill=PANEL)
            for j, s in enumerate(lines):
                text(d, (jx + 16, by + 14 + j * 28), s, 17, "mono", fill=TEXT if j < 8 else GREY)
            footer(d)
            out.append(c)
    sheet = img(os.path.join(ROOT, "contact_sheet.png"), (1840, 828))
    for i in range(int(3.2 * FPS)):
        c = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(c)
        header(d, 40, "contact_sheet.png", "all 10 frames with frame number, θ, h and v")
        c.paste(sheet, (40, 170))
        footer(d)
        out.append(c)
    return faded(out)


def seg_natural():
    out = []
    for fr in timeline("natural"):
        p = os.path.join(FR, "natural", fr["png"])
        tag = "BLINK" if fr["blink"] > 0 else "SACCADES"
        out.append(live_frame(p, fr, "Natural eye behaviour",
                              "human saccade timing · blinks · upper lid follows vertical gaze",
                              "eyes.saccade(h, v)", tag))
    return faded(out)


def seg_closeup():
    info = json.load(open(os.path.join(FR, "closeup", "closeup.json")))
    big = img(os.path.join(FR, "closeup", "reset.png"))
    s2 = big.size[0] / 1024.0
    px, py = info["reset"]["pupil_R"]   # eyes.project() is in render pixels (already 2x here)
    r_iris = 0.0059 * 1000 * 9.94 * s2 / 1.0   # ~iris radius in px
    callouts = [  # (label, (dx, dy) from the pupil in big-image px, side), top to bottom per side
        ("Eyelashes & brow hair strands", (-0.9 * r_iris, -1.15 * r_iris), "L"),
        ("Cornea: refractive bulge + catchlight", (-0.56 * r_iris, -0.33 * r_iris), "L"),
        ("Sclera: off-white, fine red veins", (-1.75 * r_iris, 0.05 * r_iris), "L"),
        ("Skin: SSS, pores, freckles, fine lines", (-2.6 * r_iris, 1.75 * r_iris), "L"),
        ("Pink, wet caruncle (inner corner)", (2.07 * r_iris, 0.36 * r_iris), "R"),
        ("Iris: radial fibres, dark limbal ring", (0.72 * r_iris, 0.55 * r_iris), "R"),
        ("Tear line on the lower lid", (0.25 * r_iris, 0.98 * r_iris), "R"),
    ]
    out = []
    n_zoom, n_hold = int(4.0 * FPS), int(3.6 * FPS)
    s_end = 2.2
    s_start = H / big.size[1]
    full_c = (big.size[0] / 2, big.size[1] / 2)
    for i in range(n_zoom + n_hold):
        t = ease(i / n_zoom) if i < n_zoom else 1.0
        s = math.exp(math.log(s_start) + (math.log(s_end) - math.log(s_start)) * t)
        cx = full_c[0] + (px - full_c[0]) * t
        cy = full_c[1] + (py - full_c[1]) * t
        c = Image.new("RGB", (W, H), BG)
        bw, bh = W / s, H / s
        x0 = min(max(cx - bw / 2, 0), big.size[0] - bw) if bw < big.size[0] else (big.size[0] - bw) / 2
        y0 = min(max(cy - bh / 2, 0), big.size[1] - bh) if bh < big.size[1] else (big.size[1] - bh) / 2
        box = (x0, y0, x0 + bw, y0 + bh)
        crop = big.crop(tuple(int(round(v)) for v in box)).resize((W, H), Image.LANCZOS)
        c.paste(crop, (0, 0))
        d = ImageDraw.Draw(c)
        if i >= n_zoom:
            tt = (i - n_zoom) / FPS
            ly = {"L": 215, "R": 215}
            for j, (lab, (dx, dy), side) in enumerate(callouts):
                a = ease((tt - 0.25 * j) / 0.35)
                if a <= 0:
                    continue
                sx, sy = (px + dx - x0) * s, (py + dy - y0) * s
                f = font("semibold", 24)
                tw = d.textlength(lab, font=f)
                lx = 40 if side == "L" else W - 40 - tw - 24
                y = ly[side]
                ly[side] += 120
                col = tuple(int(v * a) for v in (255, 255, 255))
                d.rounded_rectangle([lx, y - 22, lx + tw + 24, y + 22], 10, fill=(14, 16, 21))
                d.text((lx + 12, y), lab, font=f, fill=col, anchor="lm")
                ax = lx + tw + 24 if side == "L" else lx
                d.line([(ax, y), (sx, sy)], fill=col, width=2)
                d.ellipse([sx - 5, sy - 5, sx + 5, sy + 5], outline=col, width=2)
        d.rounded_rectangle([24, 40, 640, 150], 12, fill=(14, 16, 21))
        text(d, (44, 52), "Photorealism", 40, "semibold")
        text(d, (44, 108), "Cycles path tracing · close-up of the same locked camera", 20, fill=GREY)
        footer(d)
        out.append(c)
    big2 = img(os.path.join(FR, "closeup", "look_down_right.png"))
    mx = (info["reset"]["pupil_L"][0] + info["reset"]["pupil_R"][0]) / 2
    my = info["reset"]["pupil_L"][1]
    s = 1.0
    x0 = min(max(mx - W / 2 / s, 0), big2.size[0] - W / s)
    y0 = min(max(my - H / 2 / s, 0), big2.size[1] - H / s)
    crop2 = big2.crop((int(x0), int(y0), int(x0 + W / s), int(y0 + H / s))).resize((W, H), Image.LANCZOS)
    for i in range(int(2.8 * FPS)):
        c = crop2.copy()
        d = ImageDraw.Draw(c)
        d.rounded_rectangle([40, H - 140, 1060, H - 70], 12, fill=(14, 16, 21))
        text(d, (62, H - 105), "Looking down-right: the upper lid follows the gaze, pupil stays clear",
             24, "semibold", anchor="lm")
        footer(d)
        out.append(c)
    return faded(out)


def _render_log():
    path = os.path.join(ROOT, "debug", "final_render.log")
    lines = []
    for ln in open(path, encoding="utf-8", errors="replace"):
        if ln.startswith("[run_sequence]"):
            ln = re.sub(r"wrote \S*metadata\.json", "wrote metadata.json", ln.rstrip())
            lines.append(ln.replace("[run_sequence] ", ""))
        if ln.startswith("seq exit"):
            break
    return lines


def seg_automation():
    log = _render_log()
    cmd = "blender --background scene.blend --python wrapper/run_sequence.py"
    out = []
    for i in range(int(12 * FPS)):
        t = i / FPS
        c = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(c)
        header(d, 60, "One command regenerates everything", "headless, deterministic, CPU or GPU")
        d.rounded_rectangle([60, 160, 1300, 860], 14, fill=(8, 9, 12))
        d.rounded_rectangle([60, 160, 1300, 200], 14, fill=(36, 40, 48))
        for j, col in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
            d.ellipse([84 + j * 26, 172, 100 + j * 26, 188], fill=col)
        text(d, (680, 180), "real output of the final run (RTX 3050 laptop GPU)", 16, fill=GREY, anchor="mm")
        typed = cmd[:int(len(cmd) * ease(t / 1.2))]
        text(d, (84, 222), "$ " + typed, 20, "mono", fill=GREEN)
        shown = int(max(0, (t - 1.4)) / 0.42)
        for j, ln in enumerate(log[:shown]):
            ln = ln if len(ln) < 112 else ln[:111] + "…"
            text(d, (84, 262 + j * 34), ln, 17, "mono", fill=TEXT)
        x = 1350
        items = ["eyes.move(h, v)   eyes.reset()   eyes.render()",
                 "fixed seed, sample count and denoiser",
                 "GPU used if present, CPU fallback",
                 "metadata.json: 10 records with eye rotations, 2D pupil centres, camera matrix P = K[R|t]",
                 "plus quaternions, gaze vectors, glints, eyelid landmarks, iris and pupil ellipses",
                 "one JSON per frame as well"]
        y = 190
        for j, s in enumerate(items):
            a = ease((t - 0.8 - 0.6 * j) / 0.4)
            if a <= 0:
                continue
            col = tuple(int(BG[q] + ((ACCENT if j == 0 else TEXT)[q] - BG[q]) * a) for q in range(3))
            y = wrap(d, (x, y), s, 520, 23 if j else 21, "mono" if j == 0 else "regular", fill=col) + 18
        footer(d)
        out.append(c)
    return faded(out)


def _test_results():
    path = os.path.join(ROOT, "debug", "demo_tests.log")
    res, maxerr, maxapp, shifts = [], 0.0, 0.0, []
    for ln in open(path, encoding="utf-8", errors="replace"):
        m = re.match(r"RESULT (\S+): (PASSED|FAILED) \((\d+) checks, (\d+) failed\)", ln)
        if m:
            res.append((m.group(1), m.group(2), int(m.group(3)), int(m.group(4))))
        m = re.search(r"labelled vs detected pupil centre\s+err ([\d.]+) px", ln)
        if m:
            maxerr = max(maxerr, float(m.group(1)))
        m = re.search(r"refracted \(apparent\) centre vs detected\s+err ([\d.]+) px", ln)
        if m:
            maxapp = max(maxapp, float(m.group(1)))
        m = re.search(r"shifts the right way by >= 12 px dx=([-+\d.]+) dy=([-+\d.]+)", ln)
        if m:
            shifts.append(max(abs(float(m.group(1))), abs(float(m.group(2)))))
    return res, maxerr, maxapp, shifts


def seg_results():
    res, maxerr, maxapp, shifts = _test_results()
    sheet = img(os.path.join(ROOT, "direction_check", "sheet.png"), (785, 850))
    total = sum(r[2] for r in res)
    failed = sum(r[3] for r in res)
    out = []
    for i in range(int(10.5 * FPS)):
        t = i / FPS
        c = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(c)
        header(d, 60, "Verified, not assumed", "automated tests, rerun on the final scene")
        c.paste(sheet, (60, 170))
        x, y = 930, 190
        for j, (name, status, n, nf) in enumerate(res):
            a = ease((t - 0.3 - 0.25 * j) / 0.3)
            if a <= 0:
                continue
            col = GREEN if status == "PASSED" else RED
            fade = lambda cc: tuple(int(BG[q] + (cc[q] - BG[q]) * a) for q in range(3))
            text(d, (x, y + j * 44), name, 23, "mono", fill=fade(TEXT))
            text(d, (x + 640, y + j * 44), "%d checks" % n, 21, fill=fade(GREY), anchor="ra")
            text(d, (x + 780, y + j * 44), status, 23, "bold", fill=fade(col), anchor="ra")
        y2 = y + len(res) * 44 + 30
        a = ease((t - 2.5) / 0.5)
        if a > 0:
            fade = lambda cc: tuple(int(BG[q] + (cc[q] - BG[q]) * a) for q in range(3))
            d.line([(x, y2), (x + 780, y2)], fill=fade((60, 66, 78)), width=2)
            text(d, (x, y2 + 18), "%d checks, %d failed" % (total, failed), 30, "bold", fill=fade(GREEN if not failed else RED))
            facts = ["pupil shift Left / Right / Up / Down: %.1f–%.1f px (needs ≥ 12)" % (min(shifts), max(shifts)) if shifts else "",
                     "labelled vs detected pupil in the PNG: ≤ %.2f px (spec ~3 px)" % maxerr,
                     "refracted pupil label vs detected: ≤ %.2f px" % maxapp,
                     "same input → identical image; clean run from the zip passes"]
            for j, f in enumerate(f for f in facts if f):
                text(d, (x, y2 + 80 + j * 40), "·  " + f, 23, fill=fade(TEXT))
        footer(d)
        out.append(c)
    return faded(out)


def seg_closing():
    out = []
    for i in range(int(5 * FPS)):
        c = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(c)
        text(d, (W / 2, 380), "Thank you", 80, "bold", anchor="mm")
        text(d, (W / 2, 480), "Team PANT  ·  VIT Chennai", 36, "semibold", fill=ACCENT, anchor="mm")
        text(d, (W / 2, 540), "Nitheesh K.  ·  Adithya K.  ·  Pariksith S.S.  ·  Tarun Ashwat M.", 26, fill=GREY, anchor="mm")
        text(d, (W / 2, 660), "Synthetic Eye Movement & Virtual Camera Rendering  ·  Samsung XR Hackathon 2026, Track 1",
             22, fill=GREY, anchor="mm")
        out.append(c)
    return faded(out, 10, 20)


SEGMENTS = [seg_title, seg_problem, seg_calibration, seg_directions, seg_rotation, seg_sequence,
            seg_natural, seg_closeup, seg_automation, seg_results, seg_closing]


def main():
    args = sys.argv[1:]
    out_path = os.path.join(ROOT, "demo", "VITChennai_PANT_demo.mp4")
    if "--out" in args:
        out_path = os.path.abspath(args[args.index("--out") + 1])
    only = args[args.index("--only") + 1].split(",") if "--only" in args else None
    preview = "--preview" in args
    segs = [s for s in SEGMENTS if not only or s.__name__[4:] in only]
    if preview:
        d = os.path.join(ROOT, "demo", "preview")
        os.makedirs(d, exist_ok=True)
        for s in segs:
            frames = s()
            for frac in (0.15, 0.55, 0.9):
                frames[int(frac * (len(frames) - 1))].save(os.path.join(d, "%s_%02d.png" % (s.__name__, int(frac * 100))))
            print("%s: %d frames (%.1f s)" % (s.__name__, len(frames), len(frames) / FPS))
        return
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", "%dx%d" % (W, H), "-r", str(FPS), "-i", "-", "-c:v", "libx264",
                           "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                           out_path], stdin=subprocess.PIPE)
    total = 0
    marks = []
    for s in segs:
        frames = s()
        marks.append((s.__name__[4:], total / FPS, len(frames) / FPS))
        for f in frames:
            ff.stdin.write(f.tobytes())
        total += len(frames)
        print("%-12s starts %6.1f s, lasts %5.1f s" % (s.__name__[4:], marks[-1][1], marks[-1][2]))
        sys.stdout.flush()
    ff.stdin.close()
    ff.wait()
    print("wrote %s (%.1f s, %d frames)" % (out_path, total / FPS, total))
    with open(os.path.join(ROOT, "demo", "timing.json"), "w") as f:
        json.dump([{"segment": n, "start_s": round(a, 2), "duration_s": round(b, 2)} for n, a, b in marks], f, indent=1)


if __name__ == "__main__":
    main()
