"""Independent check: do the projected pupil centres match the pixels actually rendered?

    blender --background scene.blend --python tests/test_pupil_projection_matches_image.py

Renders Reset / Left / Right / Up / Down at 1024x1024 (reduced samples), finds the dark
pupil blob in each PNG by thresholding, and compares with the metadata projection.
Marked-up copies go to debug/ (never into renders/). It also checks, from the pixels alone,
that each direction moved the detected pupil the right way and that the lids do not cover
the pupil centre.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (DEBUG, DIRECTIONS, detect_glint, detect_pupil, draw_cross, eyes,  # noqa: E402
                    fast_render_settings, iris_radius_px, load_png, pupil_radius_px, run_test, save_png)

TOL_PX = 3.0          # required label = camera projection of the 3D pupil centre (brief: ~3 px);
                      # corneal refraction moves the imaged pupil 0.4-1.3 px. The refracted
                      # pupil_center_2D_apparent is checked to 1 px below.
GLINT_TOL_PX = 1.5
MIN_IMAGE_SHIFT_PX = 10.0


def test(c):
    fast_render_settings()
    win = iris_radius_px() * 0.85
    expected_area = np.pi * pupil_radius_px() ** 2
    poses = {"reset": (0.0, 0.0)}
    poses.update(DIRECTIONS)
    poses["dilated_brown_diag"] = (0.7, -0.7)       # 6 mm pupil, brown iris (dataset variation)
    poses["constricted_diag"] = (-0.6, 0.6)         # 2.2 mm pupil
    found = {}
    for name, (h, v) in poses.items():
        eyes.set_appearance(6.0 if name.startswith("dilated") else (2.2 if name.startswith("constricted") else 3.8),
                            1.0 if "brown" in name else 0.0)
        eyes.move(h, v)
        path, rec = eyes.render(os.path.join(DEBUG, "dir_%s.png" % name))
        img = load_png(path)
        c.check(img.shape[:2] == (1024, 1024), "%s render is 1024x1024" % name)
        marked = img.copy()
        for s in "LR":
            pred = rec["pupil_center_2D_" + s]
            det = detect_pupil(img, pred, win)
            if det is None:
                c.check(False, "%s eye %s: pupil found in the image" % (name, s))
                continue
            err = float(np.hypot(det[0] - pred[0], det[1] - pred[1]))
            found[(name, s)] = det
            c.check(err <= TOL_PX, "%-5s eye %s labelled vs detected pupil centre" % (name, s),
                    "err %.2f px (pred %.2f,%.2f det %.2f,%.2f)" % (err, pred[0], pred[1], det[0], det[1]))
            app = rec.get("pupil_center_2D_apparent_" + s)
            if app:
                err_app = float(np.hypot(det[0] - app[0], det[1] - app[1]))
                c.check(err_app <= 1.0, "%-5s eye %s refracted (apparent) centre vs detected" % (name, s),
                        "err %.2f px" % err_app)
            checked = 0
            for g in rec.get("corneal_reflections_2D_" + s, []):
                if not g["visible"] or g["surface"] != "cornea" or g.get("light_unoccluded_fraction", 1) < 0.25                         or g.get("relative_radiance", 1) < 0.5:
                    continue
                checked += 1
                dg = detect_glint(img, g["xy"], 14)
                gerr = float(np.hypot(dg[0] - g["xy"][0], dg[1] - g["xy"][1])) if dg else float("inf")
                c.check(gerr <= GLINT_TOL_PX, "%-5s eye %s %s glint labelled vs detected" % (name, s, g["light"]),
                        "err %.2f px" % gerr)
                pc = det
                c.check(np.hypot(g["xy"][0] - pc[0], g["xy"][1] - pc[1]) > pupil_radius_px() * 1.15 + 3,
                        "%-5s eye %s %s glint stays off the pupil" % (name, s, g["light"]))
                draw_cross(marked, g["xy"][0], g["xy"][1], (1.0, 0.6, 0.0), size=5)
            c.check(checked >= 1, "%-5s eye %s has at least one clean, labelled glint" % (name, s),
                    str([(g["light"], g["visible"], g.get("light_unoccluded_fraction"), round(g.get("relative_radiance", 1), 2))
                         for g in rec.get("corneal_reflections_2D_" + s, [])]))
            area = expected_area * (eyes.pupil_radius() / eyes.calibration()["pupil_radius"]) ** 2
            c.check(det[2] >= 0.6 * area, "%-5s eye %s pupil not occluded" % (name, s),
                    "%d dark px, unobstructed disc ~%.0f px" % (det[2], area))
            draw_cross(marked, pred[0], pred[1], (0.0, 1.0, 0.0))        # green = projection
            draw_cross(marked, det[0], det[1], (1.0, 0.0, 1.0), size=4)  # magenta = detected
        save_png(marked, os.path.join(DEBUG, "dir_%s_marked.png" % name))

    eyes.set_appearance(3.8, 0.0)
    expect = {"left": (-eyes.H_SIGN, 0.0), "right": (eyes.H_SIGN, 0.0), "up": (0.0, -eyes.V_SIGN), "down": (0.0, eyes.V_SIGN)}
    for name, (ex, ey) in expect.items():
        for s in "LR":
            if (name, s) in found and ("reset", s) in found:
                dx = found[(name, s)][0] - found[("reset", s)][0]
                dy = found[(name, s)][1] - found[("reset", s)][1]
                c.check(dx * ex + dy * ey >= MIN_IMAGE_SHIFT_PX, "%-5s eye %s: pupil in the PIXELS moved the right way" % (name, s),
                        "dx=%+.1f dy=%+.1f" % (dx, dy))
    eyes.reset()


run_test("test_pupil_projection_matches_image", test)
