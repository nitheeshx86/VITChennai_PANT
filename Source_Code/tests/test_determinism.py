"""Same input twice -> same image and same metadata.

    blender --background scene.blend --python tests/test_determinism.py

Renders (h, v) = (0.6, -0.35) twice with a different pose in between, at the scene's real
settings unless XR_TEST_SAMPLES is set.
"""
import hashlib
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DEBUG, eyes, load_png, run_test  # noqa: E402


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test(c):
    scene = bpy.context.scene
    if os.environ.get("XR_TEST_SAMPLES"):
        scene.cycles.samples = int(os.environ["XR_TEST_SAMPLES"])
    c.check(scene.cycles.seed == 0 and not scene.cycles.use_animated_seed, "render seed fixed")
    c.check(not scene.cycles.use_adaptive_sampling, "fixed sample count (no adaptive sampling)")
    c.check(scene.render.dither_intensity == 0.0, "no dithering noise")

    eyes.move(0.6, -0.35)
    p1, r1 = eyes.render(os.path.join(DEBUG, "determinism_a.png"))
    eyes.move(-1.0, 1.0)
    eyes.reset()
    eyes.move(0.6, -0.35)
    p2, r2 = eyes.render(os.path.join(DEBUG, "determinism_b.png"))

    for key in ("eye_rotation_L", "eye_rotation_R", "pupil_center_2D_L", "pupil_center_2D_R", "camera_matrix"):
        c.check(r1[key] == r2[key], "metadata %s identical" % key)
    a, b = load_png(p1), load_png(p2)
    diff = np.abs(a - b) * 255.0
    identical = sha(p1) == sha(p2)
    print("  info: byte-identical=%s max diff=%.3f/255 mean diff=%.5f/255 pixels differing=%d"
          % (identical, diff.max(), diff.mean(), int((diff.max(axis=2) > 0.5).sum())))
    flips = int((diff.max(axis=2) > 0.5).sum())
    c.check(identical or (diff.max() <= 1.01 and flips <= 0.0005 * diff.shape[0] * diff.shape[1]),
            "two renders of the same input are identical (or differ by 1/255 in < 0.05% of pixels)",
            "byte-identical" if identical else "max %.2f/255, %d pixels" % (diff.max(), flips))
    with open(p1, "rb") as f:
        head = f.read()
    c.check(b"tEXt" not in head and b"eXIf" not in head and b"scene.blend" not in head,
            "PNG carries no date / render-time / file-path metadata")
    eyes.reset()


run_test("test_determinism", test)
