import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper")); sys.path.insert(0, os.path.join(ROOT, "tests"))
import eyes
from common import load_png, detect_glint
img = load_png(os.path.join(ROOT, "debug", "dir_left.png"))
r = eyes.move(-1, 0)
for s in "LR":
    for g in r["corneal_reflections_2D_" + s]:
        if g["light"] != "Key":
            continue
        d = detect_glint(img, g["xy"], 9)
        print("GD", s, "label", [round(x, 2) for x in g["xy"]], "centre", [round(x, 2) for x in g["xy_light_centre"]],
              "frac", g["light_unoccluded_fraction"], "det", [round(x, 2) for x in d[:2]], "npx", d[2])
        x0, y0 = int(g["xy"][0]) - 8, int(g["xy"][1]) - 8
        win = img[y0:y0 + 17, x0:x0 + 17].mean(axis=2)
        for row in win:
            print("GD  " + "".join("#" if v > 0.85 * win.max() else ("+" if v > 0.6 * win.max() else ".") for v in row))
