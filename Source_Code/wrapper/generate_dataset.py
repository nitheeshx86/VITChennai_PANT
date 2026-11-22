"""Generate a labelled synthetic gaze dataset (the purpose of this rig).

    blender --background scene.blend --python wrapper/generate_dataset.py -- --n 200 --out dataset
    python wrapper/generate_dataset.py --n 200 --out dataset        (starts Blender itself)

Each sample: a gaze (h, v) drawn uniformly over the unit disc of the +/-5 cm target range
(seeded, so the same command always gives the same dataset), optionally a partial blink.
Writes:
    <out>/images/sample_00000.png ...      renders (same camera and lighting as the sequence)
    <out>/labels.jsonl                     one JSON record per line, same schema as metadata.json
                                           (rotations, gaze vectors, pupil / iris ellipses, glints,
                                           eyelid landmarks, visibility, camera matrices)
    <out>/manifest.json                    generator settings + calibration

Options (after "--" when run inside Blender):
    --n N              number of samples (default 100)
    --seed S           random seed (default 0)
    --out DIR          output folder (default <bundle>/dataset)
    --blink-prob P     probability of a partial blink (default 0.15); closure drawn from 0.1..0.6
    --samples N        Cycles samples (default: the scene's)
    --percent P        resolution percentage (default 100)
    --start K          resume from sample K
    --vary-appearance  also draw a pupil diameter (2..7 mm) and iris colour (blue-grey..brown)
                       per sample, seeded like the gaze
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

try:
    import bpy
except ImportError:
    sys.path.insert(0, HERE)
    import eyes as _proxy
    _cmd = [_proxy.find_blender(), "--background", os.path.join(os.path.dirname(HERE), "scene.blend"),
            "--python-exit-code", "1", "--python", os.path.abspath(__file__), "--"] + sys.argv[1:]
    sys.exit(subprocess.call(_cmd, cwd=os.path.dirname(HERE)))

sys.path.insert(0, HERE)
import eyes  # noqa: E402


def sample_gazes(n, seed, blink_prob, vary_appearance=False):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        r = math.sqrt(rng.random())               # uniform over the disc
        a = rng.random() * 2.0 * math.pi
        blink = rng.uniform(0.1, 0.6) if rng.random() < blink_prob else 0.0
        pupil_mm = rng.uniform(2.0, 7.0)
        melanin = rng.random()
        if not vary_appearance:
            pupil_mm, melanin = 3.8, 0.0
        out.append((r * math.sin(a), r * math.cos(a), blink, pupil_mm, melanin))
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(eyes.BUNDLE_ROOT, "dataset"))
    ap.add_argument("--blink-prob", type=float, default=0.15)
    ap.add_argument("--samples", type=int, default=None)
    ap.add_argument("--percent", type=int, default=None)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--vary-appearance", action="store_true")
    a = ap.parse_args(argv)

    scene = bpy.context.scene
    if a.samples:
        scene.cycles.samples = a.samples
    if a.percent:
        scene.render.resolution_percentage = a.percent
    out = os.path.abspath(a.out)
    os.makedirs(os.path.join(out, "images"), exist_ok=True)
    gazes = sample_gazes(a.n, a.seed, a.blink_prob, a.vary_appearance)
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump({"n": a.n, "seed": a.seed, "blink_prob": a.blink_prob, "vary_appearance": a.vary_appearance,
                   "samples": scene.cycles.samples, "resolution_percentage": scene.render.resolution_percentage,
                   "gaze_distribution": "uniform over the unit disc of (h, v)",
                   "calibration": eyes.calibration()}, f, indent=2)
    mode = "a" if a.start else "w"
    with open(os.path.join(out, "labels.jsonl"), mode) as lab:
        for i in range(a.start, a.n):
            h, v, blink, pupil_mm, melanin = gazes[i]
            eyes.reset()
            eyes.set_appearance(pupil_mm, melanin)
            eyes.move(h, v)
            if blink:
                eyes.blink(blink)
            rel = "images/sample_%05d.png" % i
            _, rec = eyes.render(os.path.join(out, rel))
            rec = dict({"index": i, "image": rel}, **{k: val for k, val in rec.items() if k != "image"})
            lab.write(json.dumps(rec) + "\n")
            lab.flush()
            print("[generate_dataset] %d/%d h=%+.3f v=%+.3f blink=%.2f pupil=%.1fmm melanin=%.2f"
                  % (i + 1, a.n, h, v, blink, pupil_mm, melanin))
            sys.stdout.flush()
    eyes.set_appearance(3.8, 0.0)
    eyes.reset()


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
