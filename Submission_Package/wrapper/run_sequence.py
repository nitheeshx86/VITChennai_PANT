"""Regenerate the 10-frame clockwise gaze sequence and its metadata.

    blender --background scene.blend --python wrapper/run_sequence.py
    python wrapper/run_sequence.py          (same thing; starts Blender headless itself)

Frame k (k = 0..9):  theta_k = 2*pi*k/10,  h = sin(theta_k),  v = cos(theta_k)
Frame 0 looks straight up; the gaze then travels clockwise as seen in the renders.

Writes (relative to the bundle root, i.e. the folder that contains scene.blend):
    renders/frame_00.png ... renders/frame_09.png     1024x1024 PNG
    metadata.json                                     array of 10 records, frame order
    metadata_frames/frame_00.json ...                 the same records, one file per frame

Optional arguments after "--":
    --fast           quick check: 16 samples instead of 128 (same 1024x1024 frames, same
                     metadata; only the render noise/glint quality differs). About 7x faster
                     on a CPU, 3x on a GPU.
    --out DIR        write into DIR instead of the bundle root
    --samples N      override the Cycles sample count (testing only)
    --percent P      override the resolution percentage (testing only)
    --no-render      only write the metadata (a few seconds; the labels are computed from the
                     scene geometry, not from the pixels, so they are identical either way)

Typical time for the 10 frames at full quality: ~5 min with an NVIDIA GPU, ~1 h on a laptop
CPU (set XR_DEVICE=CPU to force the CPU). See README section 2.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

try:
    import bpy
except ImportError:
    # Plain Python: relaunch this script inside headless Blender with the bundle's scene.
    sys.path.insert(0, HERE)
    import eyes as _eyes_proxy
    _cmd = [_eyes_proxy.find_blender(), "--background", os.path.join(os.path.dirname(HERE), "scene.blend"),
            "--python-exit-code", "1", "--python", os.path.abspath(__file__), "--"] + sys.argv[1:]
    sys.exit(subprocess.call(_cmd, cwd=os.path.dirname(HERE)))

sys.path.insert(0, HERE)
import eyes  # noqa: E402

N_FRAMES = 10
FAST_SAMPLES = 16
REQUIRED_KEYS = ("frame", "theta", "input", "eye_rotation_L", "eye_rotation_R",
                 "pupil_center_2D_L", "pupil_center_2D_R", "camera_matrix")


def sequence_inputs(n=N_FRAMES):
    out = []
    for k in range(n):
        theta = 2.0 * math.pi * k / n
        out.append((k, theta, math.sin(theta), math.cos(theta)))
    return out


def run(out_root=None, samples=None, percent=None, render=True):
    out_root = os.path.abspath(out_root or eyes.BUNDLE_ROOT)
    scene = bpy.context.scene
    if samples:
        scene.cycles.samples = int(samples)
    if percent:
        scene.render.resolution_percentage = int(percent)
    renders = os.path.join(out_root, "renders")
    per_frame = os.path.join(out_root, "metadata_frames")
    os.makedirs(renders, exist_ok=True)
    os.makedirs(per_frame, exist_ok=True)

    if render:
        eyes._configure_device()
        print("[run_sequence] rendering %d frames at %dx%d, %d samples on %s" % (
            N_FRAMES, scene.render.resolution_x * scene.render.resolution_percentage // 100,
            scene.render.resolution_y * scene.render.resolution_percentage // 100,
            scene.cycles.samples, scene.cycles.device))
        sys.stdout.flush()
    t_start = time.time()
    records = []
    for k, theta, h, v in sequence_inputs():
        t_frame = time.time()
        eyes.move(h, v)
        rel = "renders/frame_%02d.png" % k
        if render:
            _, rec = eyes.render(os.path.join(out_root, rel))
        else:
            rec = eyes.state()
        ordered = {"frame": k, "theta": theta}
        ordered.update(rec)
        ordered["input"] = {"h": h, "v": v}   # exact formula values
        ordered["image"] = rel
        records.append(ordered)
        with open(os.path.join(per_frame, "frame_%02d.json" % k), "w") as f:
            json.dump(ordered, f, indent=2)
        done = time.time() - t_start
        eta = done / (k + 1) * (N_FRAMES - k - 1)
        print("[run_sequence] frame %d theta=%.4f h=%+.4f v=%+.4f  L=%s R=%s  (%.0f s, ~%.0f s left)" % (
            k, theta, h, v,
            [round(x, 2) for x in ordered["pupil_center_2D_L"]],
            [round(x, 2) for x in ordered["pupil_center_2D_R"]],
            time.time() - t_frame, eta))
        sys.stdout.flush()

    with open(os.path.join(out_root, "metadata.json"), "w") as f:
        json.dump(records, f, indent=2)
    eyes.reset()
    print("[run_sequence] wrote", os.path.join(out_root, "metadata.json"),
          "(total %.0f s)" % (time.time() - t_start))
    return records


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--fast", action="store_true", help="16 samples instead of 128 (quick check)")
    ap.add_argument("--samples", type=int, default=None)
    ap.add_argument("--percent", type=int, default=None)
    ap.add_argument("--no-render", action="store_true")
    a = ap.parse_args(argv)
    run(a.out, a.samples or (FAST_SAMPLES if a.fast else None), a.percent, render=not a.no_render)
