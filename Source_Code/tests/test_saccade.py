"""Saccade dynamics (no rendering).  blender --background scene.blend --python tests/test_saccade.py

The gaze shift produced by eyes.saccade() must start at the current gaze, end exactly on the
target, never overshoot or reverse, and follow the human main sequence: duration ~ 2.2 ms/deg
* amplitude + 21 ms, bell-shaped speed, peak velocity within the measured 100-550 deg/s band.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import eyes, run_test  # noqa: E402


def test(c):
    cases = [((0, 0), (-1, 0)), ((-1, 0), (1, 0)), ((0, 0), (0, 1)), ((0.7, 0.7), (-0.7, -0.7)), ((0, 0), (0.1, 0))]
    for (h0, v0), (h1, v1) in cases:
        eyes.move(h0, v0)
        path = eyes.saccade(h1, v1, fps=1000.0)
        st = eyes.saccade_stats(h0, v0, h1, v1)
        label = "(%g,%g)->(%g,%g) %.1f deg" % (h0, v0, h1, v1, st["amplitude_deg"])
        c.check(abs(path[0]["h"] - h0) < 1e-12 and abs(path[0]["v"] - v0) < 1e-12, label + ": starts at the current gaze")
        c.check(path[-1]["h"] == h1 and path[-1]["v"] == v1, label + ": ends exactly on the target")
        c.check(abs(path[-1]["t_ms"] - st["duration_ms"]) < 1e-9, label + ": duration follows the main sequence",
                "%.1f ms" % st["duration_ms"])
        frac = [((p["h"] - h0) * (h1 - h0) + (p["v"] - v0) * (v1 - v0)) / max(1e-12, (h1 - h0) ** 2 + (v1 - v0) ** 2)
                for p in path]
        c.check(all(b >= a - 1e-12 for a, b in zip(frac, frac[1:])) and max(frac) <= 1 + 1e-12,
                label + ": monotonic, no overshoot")
        # numerical peak angular velocity from the actual gaze angles along the path
        peak = 0.0
        for a, b in zip(path, path[1:]):
            dt = (b["t_ms"] - a["t_ms"]) / 1000.0
            if dt > 0:
                peak = max(peak, eyes._gaze_angle_deg(a["h"], a["v"], b["h"], b["v"]) / dt)
        c.check(abs(peak - st["peak_velocity_deg_s"]) / st["peak_velocity_deg_s"] < 0.03,
                label + ": peak velocity matches 1.875 A / D", "%.0f vs %.0f deg/s" % (peak, st["peak_velocity_deg_s"]))
        if st["amplitude_deg"] >= 1.0:
            c.check(100.0 <= peak <= 550.0, label + ": peak velocity in the human range", "%.0f deg/s" % peak)
        # bell shape: speed at the middle exceeds speed in the first and last tenth
        n = len(path)
        sp = [eyes._gaze_angle_deg(a["h"], a["v"], b["h"], b["v"]) for a, b in zip(path, path[1:])]
        c.check(sp[len(sp) // 2] > 3 * max(sp[: max(1, n // 10)]) and sp[len(sp) // 2] > 3 * max(sp[-max(1, n // 10):]),
                label + ": bell-shaped velocity profile")
    eyes.reset()
    at60 = eyes.saccade(1, 0, fps=60.0)
    c.check(all(abs(b["t_ms"] - a["t_ms"] - 1000 / 60.0) < 1e-6 for a, b in zip(at60[:-2], at60[1:-1])),
            "samples are spaced at the requested frame rate")
    eyes.reset()


run_test("test_saccade", test)
