"""Render one gaze and overlay every label (pupil/iris ellipses, glints, lid landmarks).
blender -b scene.blend --python tools/draw_labels.py -- h v name [samples]"""
import bpy, sys, os, math
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper")); sys.path.insert(0, os.path.join(ROOT, "tests"))
import eyes
from common import load_png, save_png
a = sys.argv[sys.argv.index("--") + 1:]
h, v, name = float(a[0]), float(a[1]), a[2]
bpy.context.scene.cycles.samples = int(a[3]) if len(a) > 3 else 64
eyes.move(h, v)
path, rec = eyes.render(os.path.join(ROOT, "debug", name + ".png"))
img = load_png(path)

def dot(x, y, col, r=1):
    xi, yi = int(round(x - 0.5)), int(round(y - 0.5))
    img[max(0, yi - r):yi + r + 1, max(0, xi - r):xi + r + 1] = col

def ellipse(e, col):
    if not e: return
    cx, cy = e["center"]; A, B = e["semi_axes"]; t = math.radians(e["angle_deg"])
    for k in range(360):
        p = math.radians(k)
        x = cx + A * math.cos(p) * math.cos(t) - B * math.sin(p) * math.sin(t)
        y = cy + A * math.cos(p) * math.sin(t) + B * math.sin(p) * math.cos(t)
        dot(x, y, col, 0)

for s in "LR":
    ellipse(rec["pupil_ellipse_2D_" + s], (0, 1, 0))
    ellipse(rec["iris_ellipse_2D_" + s], (0, 0.8, 1))
    lm = rec["eyelid_landmarks_2D_" + s]
    if lm:
        for p in lm["upper"]: dot(p[0], p[1], (1, 0.2, 0.2), 1)
        for p in lm["lower"]: dot(p[0], p[1], (1, 1, 0), 1)
    for g in rec["corneal_reflections_2D_" + s]:
        if g["visible"] and g["surface"] == "cornea":
            dot(g["xy"][0], g["xy"][1], (1, 0, 1), 1)
    print("LBL", s, "pupil visible %.2f" % rec["pupil_visible_fraction_" + s], "landmarks", None if not lm else (len(lm["upper"]), len(lm["lower"])))
save_png(img, os.path.join(ROOT, "debug", name + "_labels.png"))
crop = np.concatenate([img[440:590, 40:370], img[440:590, 654:984]], axis=1)
save_png(np.kron(crop, np.ones((2, 2, 1))), os.path.join(ROOT, "debug", name + "_labels_eyes.png"))
