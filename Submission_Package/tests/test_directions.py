"""Direction check: Left / Right / Up / Down / Reset on both eyes.

    blender --background scene.blend --python tests/test_directions.py

Uses the projected 2D pupil centres (tests/test_pupil_projection_matches_image.py proves
independently that those projections match the rendered pixels).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DIRECTIONS, eyes, run_test  # noqa: E402

MIN_SHIFT_PX = 12.0
MAX_DRIFT_PX = 2.0


def test(c):
    r0 = eyes.reset()
    base = {s: r0["pupil_center_2D_" + s] for s in "LR"}
    # expected image-space direction of the pupil shift (x right, y down)
    expect = {
        "left": (-eyes.H_SIGN, 0.0), "right": (eyes.H_SIGN, 0.0),
        "up": (0.0, -eyes.V_SIGN), "down": (0.0, eyes.V_SIGN),
    }
    for name, (h, v) in DIRECTIONS.items():
        r = eyes.move(h, v)
        ex, ey = expect[name]
        for s in "LR":
            dx = r["pupil_center_2D_" + s][0] - base[s][0]
            dy = r["pupil_center_2D_" + s][1] - base[s][1]
            primary = dx * ex + dy * ey
            drift = abs(dx * ey) + abs(dy * ex)
            c.check(primary >= MIN_SHIFT_PX, "%-5s eye %s shifts the right way by >= %g px" % (name, s, MIN_SHIFT_PX),
                    "dx=%+.2f dy=%+.2f" % (dx, dy))
            c.check(drift <= MAX_DRIFT_PX, "%-5s eye %s off-axis drift small" % (name, s), "%.3f px" % drift)
        c.check(eyes.look(name)["pupil_center_2D_L"] == r["pupil_center_2D_L"], 'eyes.look("%s") == eyes.move(%g, %g)' % (name, h, v))

    # reset returns exactly to the initial centre
    eyes.move(0.83, -0.41)
    r = eyes.reset()
    for s in "LR":
        d = max(abs(r["pupil_center_2D_" + s][0] - base[s][0]), abs(r["pupil_center_2D_" + s][1] - base[s][1]))
        c.check(d <= 0.5, "reset returns eye %s to centre" % s, "%.6f px" % d)
        c.check(max(abs(a - b) for a, b in zip(r["eye_rotation_" + s], r0["eye_rotation_" + s])) < 1e-9,
                "reset rotation of eye %s identical" % s)

    # clamping + determinism of the pose
    a = eyes.move(3.0, -9.0)
    b = eyes.move(1.0, -1.0)
    c.check(a["input"] == {"h": 1.0, "v": -1.0}, "inputs are clamped to [-1, +1]", str(a["input"]))
    c.check(a["pupil_center_2D_L"] == b["pupil_center_2D_L"] and a["eye_rotation_R"] == b["eye_rotation_R"],
            "same input -> identical pose")
    eyes.reset()


run_test("test_directions", test)
