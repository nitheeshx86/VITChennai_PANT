"""Checks the eye-optics model behind the pupil and glint labels (no rendering needed).

    blender --background scene.blend --python tests/test_optics.py

1. Round trip: every apparent pupil-rim pixel, traced forward through the cornea with Snell's
   law, lands on the real 3D pupil rim.
2. Null case: with refractive index 1 the apparent pupil centre equals the plain projection
   (up to the small perspective offset of an ellipse centre).
3. Law of reflection at each glint: the surface normal bisects the directions to the camera (to
   float32 precision: mathutils works in single precision)
   and to the light.
4. Physical sanity: the cornea magnifies the pupil; the glint moves less than the pupil when
   the eye turns (the basis of pupil-centre / corneal-reflection eye tracking).
"""
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import eyes, run_test  # noqa: E402


def test(c):
    calib = eyes.calibration()
    cam = eyes._Camera(calib)
    rs, rc, zc, ior = eyes._optics_constants(calib)
    c.check(abs(ior - 1.3375) < 1e-9, "cornea index is the keratometric 1.3375", str(ior))
    shell = bpy.data.objects["Cornea.L"].active_material.node_tree.nodes
    bsdf = next(n for n in shell if n.type == "BSDF_PRINCIPLED")
    c.check(abs(bsdf.inputs["IOR"].default_value - ior) < 1e-6, "renderer uses the same index as the model")

    gazes = [(0, 0), (-1, 0), (1, 0), (0, 1), (0, -1), (0.6, -0.8)]
    for g in gazes:
        eyes.move(*g)
        for side in "LR":
            pose = eyes.eye_pose(side, calib)
            centre, axis = pose["centre"], pose["axis"]
            p0 = centre + axis * calib["pupil_offset_" + side]
            app = eyes.apparent_pupil(side, pose, calib, cam)
            worst = 0.0
            for px in app["rim"]:
                o, d = cam.ray(*px)
                s, n = eyes._eye_surface_hit(o, d, centre, axis, rs, rc, zc)
                t = eyes._refract(d, n, 1.0 / ior)
                lam = (p0 - s).dot(axis) / t.dot(axis)
                q = s + t * lam
                worst = max(worst, abs((q - p0).length - eyes.pupil_radius(calib)))
            c.check(worst < 1e-6, "%s eye %s: refracted rim rays land on the 3D pupil rim" % (g, side),
                    "worst %.2e m" % worst)

            geo = eyes.project(p0, cam.p)
            r_geo = eyes.project(p0 + axis.orthogonal().normalized() * eyes.pupil_radius(calib), cam.p)
            r_geo = math.hypot(r_geo[0] - geo[0], r_geo[1] - geo[1])
            c.check(app["semi_axes"][1] > r_geo * 1.05, "%s eye %s: cornea magnifies the pupil" % (g, side),
                    "apparent minor %.2f px vs plain %.2f px" % (app["semi_axes"][1], r_geo))

            calib1 = dict(calib, cornea_ior=1.0)
            flat = eyes.apparent_pupil(side, pose, calib1, cam)
            off = math.hypot(flat["center"][0] - geo[0], flat["center"][1] - geo[1])
            c.check(off < 0.05, "%s eye %s: with index 1 the apparent centre is the plain projection" % (g, side),
                    "%.4f px" % off)

            for gl in eyes.corneal_reflections(side, pose, calib, cam):
                gp = Vector(gl["world"])
                sc = centre + axis * zc if gl["surface"] == "cornea" else centre
                n = (gp - sc).normalized()
                light = bpy.data.objects[gl["light"]].matrix_world.translation
                bis = ((cam.origin - gp).normalized() + (light - gp).normalized()).normalized()
                c.check((n - bis).length < 1e-5, "%s eye %s %s glint obeys the law of reflection" % (g, side, gl["light"]),
                        "%.1e" % (n - bis).length)

    # no light's whole reflection (not just its centre) may overlap the pupil in the five test
    # poses: a reflection over the black pupil lowers its contrast for image-based detectors
    for g in [(0, 0), (-1, 0), (1, 0), (0, 1), (0, -1)]:
        eyes.move(*g)
        for side in "LR":
            pose = eyes.eye_pose(side, calib)
            app = eyes.apparent_pupil(side, pose, calib, cam)
            sc = pose["centre"] + pose["axis"] * zc
            for name in calib["lights"]:
                light = bpy.data.objects[name]
                d = light.data
                corners = []
                for u, v in ((-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)):
                    lp = light.matrix_world @ Vector((u * d.size, v * d.size_y, 0))
                    gp = eyes._reflection_point(cam.origin, sc, rc, lp)
                    if (gp - pose["centre"]).normalized().dot(pose["axis"]) < eyes._cap_cos(rs, rc, zc):
                        corners = None
                        break
                    corners.append(eyes.project(gp, cam.p))
                if not corners:
                    continue          # reflection not on the cornea (e.g. the rim light behind)
                cx, cy = app["center"]
                # distance from the pupil centre to the reflection quad (0 if inside)
                def seg_dist(a, b):
                    ax, ay = a; bx, by = b
                    vx, vy = bx - ax, by - ay
                    t = max(0.0, min(1.0, ((cx - ax) * vx + (cy - ay) * vy) / (vx * vx + vy * vy)))
                    return math.hypot(ax + t * vx - cx, ay + t * vy - cy)
                inside = all(((corners[(k + 1) % 4][0] - corners[k][0]) * (cy - corners[k][1])
                              - (corners[(k + 1) % 4][1] - corners[k][1]) * (cx - corners[k][0])) > 0 for k in range(4)) or                     all(((corners[(k + 1) % 4][0] - corners[k][0]) * (cy - corners[k][1])
                         - (corners[(k + 1) % 4][1] - corners[k][1]) * (cx - corners[k][0])) < 0 for k in range(4))
                dist = 0.0 if inside else min(seg_dist(corners[k], corners[(k + 1) % 4]) for k in range(4))
                c.check(dist > app["semi_axes"][0] + 1.0, "%s eye %s: %s reflection stays off the pupil" % (g, side, name),
                        "gap %.1f px" % (dist - app["semi_axes"][0]))

    # differential motion: pupil vs glint, left -> right gaze
    eyes.move(-1, 0)
    a = {s: (eyes.apparent_pupil(s)["center"], [x for x in eyes.corneal_reflections(s) if x["light"] == "Key"][0]["xy_light_centre"]) for s in "LR"}
    eyes.move(1, 0)
    b = {s: (eyes.apparent_pupil(s)["center"], [x for x in eyes.corneal_reflections(s) if x["light"] == "Key"][0]["xy_light_centre"]) for s in "LR"}
    for s in "LR":
        dp = b[s][0][0] - a[s][0][0]
        dg = b[s][1][0] - a[s][1][0]
        c.check(0 < dg < dp, "eye %s: glint moves less than the pupil (PCCR principle)" % s,
                "pupil %.1f px, glint %.1f px" % (dp, dg))
    eyes.reset()


run_test("test_optics", test)
