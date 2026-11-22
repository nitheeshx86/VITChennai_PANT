import sys, os
import numpy as np
from mathutils import Vector
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper")); sys.path.insert(0, os.path.join(ROOT, "tests"))
import bpy, eyes
from common import load_png, save_png
img = load_png(os.path.join(ROOT, "debug", "dir_left.png"))
r = eyes.move(-1, 0)
c = eyes.calibration(); cam = eyes._Camera(c)
rs, rc, zc, ior = eyes._optics_constants(c)
pose = eyes.eye_pose("R", c)
sc = pose["centre"] + pose["axis"] * zc
L = bpy.data.objects["Key"]; d = L.data
corners = []
for (u, v) in ((-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)):
    lp = L.matrix_world @ Vector((u * d.size, v * d.size_y, 0))
    corners.append(eyes.project(eyes._reflection_point(cam.origin, sc, rc, lp), cam.p))
print("GD2 predicted quad", [[round(x, 1) for x in q] for q in corners])
x0, y0 = 140, 470
win = img[y0:y0 + 40, x0:x0 + 40].mean(axis=2)
ys, xs = np.nonzero(win >= 0.85 * win.max())
print("GD2 detected extents x", xs.min() + x0, xs.max() + x0, "y", ys.min() + y0, ys.max() + y0)
for row_i, row in enumerate(win):
    print("GD2 %3d " % (row_i + y0) + "".join("#" if v > 0.85 * win.max() else ("+" if v > 0.5 * win.max() else ".") for v in row))
