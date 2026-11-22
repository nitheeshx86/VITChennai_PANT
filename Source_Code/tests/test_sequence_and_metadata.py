"""Checks the delivered renders/ and metadata.json.

    blender --background scene.blend --python tests/test_sequence_and_metadata.py

Set XR_BUNDLE=<dir> to check a bundle somewhere else (used by the clean-room test).
"""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, detect_pupil, eyes, iris_radius_px, load_png, png_size, run_test  # noqa: E402

BUNDLE = os.environ.get("XR_BUNDLE", ROOT)
REQUIRED = ("frame", "theta", "input", "eye_rotation_L", "eye_rotation_R",
            "pupil_center_2D_L", "pupil_center_2D_R", "camera_matrix")


def euler_xyz(e):
    """Rotation matrix for Blender/README 'XYZ' Euler angles: R = Rz @ Ry @ Rx."""
    x, y, z = e
    rx = np.array([[1, 0, 0], [0, math.cos(x), -math.sin(x)], [0, math.sin(x), math.cos(x)]])
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rz = np.array([[math.cos(z), -math.sin(z), 0], [math.sin(z), math.cos(z), 0], [0, 0, 1]])
    return rz @ ry @ rx


def numeric_list(x, n):
    return isinstance(x, list) and len(x) == n and all(isinstance(v, (int, float)) and math.isfinite(v) for v in x)


def test(c):
    renders = os.path.join(BUNDLE, "renders")
    pngs = sorted(f for f in os.listdir(renders) if f.lower().endswith(".png"))
    want = ["frame_%02d.png" % k for k in range(10)]
    c.check(pngs == want, "renders/ holds exactly frame_00..frame_09.png", str(pngs if pngs != want else ""))
    for f in want:
        p = os.path.join(renders, f)
        if os.path.exists(p):
            c.check(png_size(p) == (1024, 1024), "%s is a 1024x1024 PNG" % f, str(png_size(p)))

    with open(os.path.join(BUNDLE, "metadata.json")) as fh:
        meta = json.load(fh)
    c.check(isinstance(meta, list) and len(meta) == 10, "metadata.json is an array of 10 records")
    cam0 = meta[0]["camera_matrix"]
    for k, rec in enumerate(meta):
        missing = [key for key in REQUIRED if key not in rec]
        c.check(not missing, "frame %d has all required keys" % k, str(missing))
        if missing:
            continue
        theta = 2 * math.pi * k / 10
        c.check(rec["frame"] == k and isinstance(rec["frame"], int), "frame %d index in order" % k)
        c.check(abs(rec["theta"] - theta) < 1e-6, "frame %d theta = 2*pi*k/10" % k, "%.7f" % rec["theta"])
        c.check(abs(rec["input"]["h"] - math.sin(theta)) < 1e-6 and abs(rec["input"]["v"] - math.cos(theta)) < 1e-6,
                "frame %d h = sin(theta), v = cos(theta)" % k, "h=%+.6f v=%+.6f" % (rec["input"]["h"], rec["input"]["v"]))
        shapes = (numeric_list(rec["eye_rotation_L"], 3) and numeric_list(rec["eye_rotation_R"], 3)
                  and numeric_list(rec["pupil_center_2D_L"], 2) and numeric_list(rec["pupil_center_2D_R"], 2)
                  and isinstance(rec["camera_matrix"], list) and len(rec["camera_matrix"]) == 3
                  and all(numeric_list(row, 4) for row in rec["camera_matrix"]))
        c.check(shapes, "frame %d value shapes/types" % k)
        c.check(rec["camera_matrix"] == cam0, "frame %d camera matrix identical to frame 0 (locked camera)" % k)
        inside = all(0 <= rec["pupil_center_2D_" + s][i] <= 1024 for s in "LR" for i in (0, 1))
        c.check(inside, "frame %d pupil centres inside the image" % k)
        # P must equal K [R|t] and reproduce the stored 2D centres from the stored 3D centres
        if "camera_intrinsics_K" in rec and "camera_extrinsics_world_to_cam" in rec:
            p = np.array(rec["camera_intrinsics_K"]) @ np.array(rec["camera_extrinsics_world_to_cam"])
            c.check(np.allclose(p, np.array(rec["camera_matrix"]), atol=1e-6), "frame %d camera_matrix == K [R|t]" % k)
        if "pupil_center_3D_L" in rec:
            for s in "LR":
                x = np.array(rec["camera_matrix"]) @ np.array(rec["pupil_center_3D_" + s] + [1.0])
                for key in ("pupil_center_2D_" + s, "pupil_center_2D_geometric_" + s):
                    if key in rec:
                        err = np.abs(x[:2] / x[2] - np.array(rec[key])).max()
                        c.check(err < 1e-4, "frame %d: camera_matrix * pupil_center_3D_%s == %s" % (k, s, key),
                                "%.2e px" % err)
        # Vergence as an outside evaluator would check it: rebuild each eye's gaze from the
        # REQUIRED Euler angles alone (R = Rz Ry Rx), apply it to the face-forward axis (taken
        # from the camera, which looks back at the face), and require both gazes to pass
        # through the fixation target and to converge by the geometric vergence angle.
        if "fixation_target_world" in rec and "eye_center_world_L" in rec:
            fwd = -np.array(rec["camera_extrinsics_world_to_cam"])[2, :3]
            tgt = np.array(rec["fixation_target_world"])
            gaze, expect = {}, {}
            for s in "LR":
                g = euler_xyz(rec["eye_rotation_" + s]) @ fwd
                ctr = np.array(rec["eye_center_world_" + s])
                to_t = tgt - ctr
                miss = np.linalg.norm(to_t - g * (to_t @ g)) * 1000.0
                c.check(miss < 1.0 and to_t @ g > 0,
                        "frame %d eye %s: eye_rotation applied to forward passes through the target" % (k, s),
                        "miss %.4f mm" % miss)
                gaze[s], expect[s] = g, to_t / np.linalg.norm(to_t)
            got = math.degrees(math.acos(np.clip(gaze["L"] @ gaze["R"], -1, 1)))
            want_v = math.degrees(math.acos(np.clip(expect["L"] @ expect["R"], -1, 1)))
            c.check(abs(got - want_v) < 0.01 and got > 5.0,
                    "frame %d vergence from eye_rotation_L/R matches the 35 cm geometry" % k,
                    "%.3f deg (expected %.3f)" % (got, want_v))

    # The metadata must describe THIS scene: recompute from the live scene and compare.
    for k, rec in enumerate(meta):
        live = eyes.move(rec["input"]["h"], rec["input"]["v"])
        for key in ("eye_rotation_L", "eye_rotation_R", "pupil_center_2D_L", "pupil_center_2D_R"):
            err = max(abs(a - b) for a, b in zip(live[key], rec[key]))
            c.check(err < 1e-4, "frame %d %s matches the live scene" % (k, key), "%.2e" % err)
        err = np.abs(np.array(live["camera_matrix"]) - np.array(rec["camera_matrix"])).max()
        c.check(err < 1e-6, "frame %d camera_matrix matches the live scene" % k, "%.2e" % err)
    r0 = eyes.reset()

    # Clockwise loop starting at the top (image coords: x right, y down).
    for s in "LR":
        centre = r0["pupil_center_2D_" + s]
        prev = None
        total = 0.0
        ok = True
        for k, rec in enumerate(meta):
            dx = rec["pupil_center_2D_" + s][0] - centre[0]
            dy = rec["pupil_center_2D_" + s][1] - centre[1]
            # angle measured clockwise from "up" on the screen
            ang = math.atan2(dx, -dy) % (2 * math.pi)
            expect = 2 * math.pi * k / 10
            diff = (ang - expect + math.pi) % (2 * math.pi) - math.pi
            if abs(diff) > math.radians(6):
                ok = False
            if prev is not None:
                step = (ang - prev) % (2 * math.pi)
                total += step
                if not (math.radians(20) < step < math.radians(52)):
                    ok = False
            prev = ang
            if k == 0:
                c.check(abs(dx) < 2.0 and dy < -10, "eye %s frame 0 is straight up" % s, "dx=%+.2f dy=%+.2f" % (dx, dy))
            c.check(math.hypot(dx, dy) >= 12.0, "eye %s frame %d pupil displaced >= 12 px from centre" % (s, k), "%.2f px" % math.hypot(dx, dy))
        c.check(ok, "eye %s pupil path is a clockwise loop from the top" % s, "swept %.1f deg over 9 steps" % math.degrees(total))

    # The rendered pixels agree with the metadata on every delivered frame.
    win = iris_radius_px() * 0.85
    for k, rec in enumerate(meta):
        p = os.path.join(renders, "frame_%02d.png" % k)
        if not os.path.exists(p):
            continue
        img = load_png(p)
        for s in "LR":
            det = detect_pupil(img, rec["pupil_center_2D_" + s], win)
            err = math.hypot(det[0] - rec["pupil_center_2D_" + s][0], det[1] - rec["pupil_center_2D_" + s][1]) if det else float("inf")
            c.check(err <= 3.0, "frame %d eye %s: pupil_center_2D matches the PNG (<= 3 px)" % (k, s), "%.2f px" % err)
            app = rec.get("pupil_center_2D_apparent_" + s)
            if app and det:
                err = math.hypot(det[0] - app[0], det[1] - app[1])
                c.check(err <= 1.0, "frame %d eye %s: refracted pupil_center_2D_apparent matches the PNG (<= 1 px)" % (k, s),
                        "%.2f px" % err)


run_test("test_sequence_and_metadata", test)
