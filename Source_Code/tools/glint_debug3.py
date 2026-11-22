import sys, os
import numpy as np
from mathutils import Vector
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper")); sys.path.insert(0, os.path.join(ROOT, "tests"))
import bpy, eyes
from common import load_png, detect_glint
pose_name, h, v, side = sys.argv[sys.argv.index("--") + 1:]
h, v = float(h), float(v)
img = load_png(os.path.join(ROOT, "debug", "dir_%s.png" % pose_name))
r = eyes.move(h, v)
c = eyes.calibration(); cam = eyes._Camera(c)
rs, rc, zc, ior = eyes._optics_constants(c)
pose = eyes.eye_pose(side, c)
sc = pose["centre"] + pose["axis"] * zc
L = bpy.data.objects["Key"]; d = L.data
corners = []
for (u, w) in ((-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)):
    lp = L.matrix_world @ Vector((u * d.size, w * d.size_y, 0))
    corners.append([round(x, 1) for x in eyes.project(eyes._reflection_point(cam.origin, sc, rc, lp), cam.p)])
g = [x for x in r["corneal_reflections_2D_" + side] if x["light"] == "Key"][0]
det = detect_glint(img, g["xy"], 14)
print("GD3 label", [round(x, 2) for x in g["xy"]], "centre-of-light", [round(x, 2) for x in g["xy_light_centre"]], "frac", g["light_unoccluded_fraction"], "det", [round(x, 2) for x in det[:2]])
print("GD3 predicted quad", corners)
x0, y0 = int(g["xy"][0]) - 16, int(g["xy"][1]) - 14
win = img[y0:y0 + 28, x0:x0 + 32].mean(axis=2)
for i, row in enumerate(win):
    print("GD3 %3d " % (i + y0) + "".join("#" if q > 0.6 * win.max() else ("+" if q > 0.4 * win.max() else ".") for q in row))
print("GD3 x0", x0)
