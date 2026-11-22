"""Clean-room test: simulate the evaluator on a fresh copy of the bundle (plain Python).

    python tests/test_clean_run.py                 # copies the bundle files from this folder
    python tests/test_clean_run.py --zip=X.zip     # unzips the given submission zip instead

Steps (exactly the README's commands):
  1. make a fresh temp directory containing only the bundle files
  2. check the required layout
  3. blender --background scene.blend --python wrapper/run_sequence.py      (regenerates all)
  4. blender --background scene.blend --python wrapper/eyes.py -- --look left --out ...
  5. run tests/test_sequence_and_metadata.py and tests/test_directions.py inside the copy
  6. compare the regenerated metadata with the shipped one (to 1e-9) and report how closely the
     regenerated frames match the shipped ones

Pixel identity is reported as information only: on the same machine the frames are identical,
but a different GPU, GPU vs CPU, or another OS changes the Cycles noise by a few grey levels
(measured: up to 9/255, mean 0.02/255, GPU vs CPU). That the regenerated frames are correct is
checked by step 5, which finds the pupils in the regenerated PNGs where the metadata says.

XR_CLEAN_SAMPLES=<n> lowers the sample count for a quicker (non byte-identical) pass.
"""
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE_ITEMS = ["scene.blend", "wrapper", "renders", "metadata.json", "README.md",
                "textures", "tests", "contact_sheet.png", "metadata_frames"]
REQUIRED = ["scene.blend", "wrapper/eyes.py", "renders", "metadata.json", "README.md"]

failures = 0


def check(ok, label, detail=""):
    global failures
    if not ok:
        failures += 1
    print("  [%s] %s %s" % ("PASS" if ok else "FAIL", label, detail))
    sys.stdout.flush()
    return ok


def find_blender():
    cand = [os.environ.get("BLENDER"), shutil.which("blender")]
    cand += sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender*\blender.exe"), reverse=True)
    cand += ["/Applications/Blender.app/Contents/MacOS/Blender", "/usr/bin/blender", "/snap/bin/blender"]
    for c in cand:
        if c and os.path.exists(c):
            return c
    sys.exit("Blender not found. Set the BLENDER environment variable.")


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


META_TOL = 1e-9


def _close(a, b, path="", tol=META_TOL):
    """Recursive comparison of two JSON values; numbers may differ by tol (absolute, or relative
    to the magnitude for values above 1). Returns None if equal, else the path of the first
    difference."""
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or a is None:
        return None if a == b else path
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return None if abs(a - b) <= tol * max(1.0, abs(a), abs(b)) else path
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return path
        for i, (x, y) in enumerate(zip(a, b)):
            bad = _close(x, y, "%s[%d]" % (path, i), tol)
            if bad:
                return bad
        return None
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return path + " (keys differ)"
        for k in a:
            bad = _close(a[k], b[k], "%s.%s" % (path, k), tol)
            if bad:
                return bad
        return None
    return path


def _pixel_diff(work, shipped_dir):
    """(max abs difference in grey levels, mean abs difference, worst fraction of differing
    pixels) over the 10 frames. Uses Pillow + numpy when available; returns None otherwise."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None
    worst_max, worst_mean, worst_frac = 0, 0.0, 0.0
    for k in range(10):
        a = np.asarray(Image.open(os.path.join(work, "renders", "frame_%02d.png" % k))).astype(int)
        b = np.asarray(Image.open(os.path.join(shipped_dir, "frame_%02d.png" % k))).astype(int)
        d = np.abs(a - b)
        worst_max = max(worst_max, int(d.max()))
        worst_mean = max(worst_mean, float(d.mean()))
        worst_frac = max(worst_frac, float((d.max(axis=2) > 0).mean()))
    return worst_max, worst_mean, worst_frac


def blender(exe, cwd, *args):
    proc = subprocess.run([exe, "--background", "scene.blend", "--python-exit-code", "1"] + list(args),
                          cwd=cwd, capture_output=True, text=True, errors="replace")
    return proc.returncode, proc.stdout + proc.stderr


def main():
    print("\n===== test_clean_run =====")
    exe = find_blender()
    zip_arg = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--zip=")]
    tmp = tempfile.mkdtemp(prefix="xr_clean_")
    work = os.path.join(tmp, "bundle")
    try:
        if zip_arg:
            with zipfile.ZipFile(zip_arg[0]) as z:
                z.extractall(work)
            # the zip may contain the files directly or inside one top-level folder
            if not os.path.exists(os.path.join(work, "scene.blend")):
                subs = [d for d in os.listdir(work) if os.path.isdir(os.path.join(work, d))]
                if len(subs) == 1 and os.path.exists(os.path.join(work, subs[0], "scene.blend")):
                    work = os.path.join(work, subs[0])
            print("  unzipped", zip_arg[0], "->", work)
        else:
            os.makedirs(work)
            for item in BUNDLE_ITEMS:
                src = os.path.join(ROOT, item)
                if os.path.isdir(src):
                    shutil.copytree(src, os.path.join(work, item), ignore=shutil.ignore_patterns("__pycache__"))
                elif os.path.exists(src):
                    shutil.copy2(src, os.path.join(work, item))
            print("  copied bundle ->", work)

        for item in REQUIRED:
            check(os.path.exists(os.path.join(work, item)), "bundle contains " + item)
        shipped = {}
        for k in range(10):
            p = os.path.join(work, "renders", "frame_%02d.png" % k)
            if os.path.exists(p):
                shipped[k] = sha(p)
        check(len(shipped) == 10, "bundle ships 10 renders")
        shipped_dir = os.path.join(tmp, "shipped_renders")
        shutil.copytree(os.path.join(work, "renders"), shipped_dir)
        with open(os.path.join(work, "metadata.json")) as f:
            shipped_meta = json.load(f)

        # wipe the outputs so we know the run really regenerates them
        shutil.rmtree(os.path.join(work, "renders"))
        os.remove(os.path.join(work, "metadata.json"))

        extra = []
        if os.environ.get("XR_CLEAN_SAMPLES"):
            extra = ["--", "--samples", os.environ["XR_CLEAN_SAMPLES"]]
        code, out = blender(exe, work, "--python", "wrapper/run_sequence.py", *extra)
        check(code == 0, "README command: run_sequence.py exits cleanly", "" if code == 0 else out[-1500:])
        regenerated = sorted(os.listdir(os.path.join(work, "renders"))) if os.path.isdir(os.path.join(work, "renders")) else []
        check(regenerated == ["frame_%02d.png" % k for k in range(10)], "10 renders regenerated", str(regenerated))
        check(os.path.exists(os.path.join(work, "metadata.json")), "metadata.json regenerated")

        if os.path.exists(os.path.join(work, "metadata.json")):
            with open(os.path.join(work, "metadata.json")) as f:
                new_meta = json.load(f)
            required = ("frame", "theta", "input", "eye_rotation_L", "eye_rotation_R",
                        "pupil_center_2D_L", "pupil_center_2D_R", "camera_matrix")
            bad = None if len(new_meta) == len(shipped_meta) else "(record count)"
            for a, b in zip(new_meta, shipped_meta):
                if bad:
                    break
                bad = _close({k: a.get(k) for k in required}, {k: b.get(k) for k in required},
                             "frame %s" % a.get("frame"))
            check(bad is None, "regenerated metadata (required keys) matches the shipped metadata "
                  "(tolerance %g)" % META_TOL, "" if bad is None else "first difference at " + bad)
            # The extra labels (eyelid landmarks, glints, ...) come partly from ray casts, so they
            # are compared as information only.
            extra_bad = None
            for a, b in zip(new_meta, shipped_meta):
                extra_bad = _close({k: v for k, v in a.items() if k not in required and k != "image"},
                                   {k: v for k, v in b.items() if k not in required and k != "image"},
                                   "frame %s" % a.get("frame"))
                if extra_bad:
                    break
            print("  info: extra metadata keys %s" % ("match to %g" % META_TOL if extra_bad is None
                                                     else "first differ at " + extra_bad))
        if not extra:
            identical = sum(1 for k in shipped if os.path.exists(os.path.join(work, "renders", "frame_%02d.png" % k))
                            and sha(os.path.join(work, "renders", "frame_%02d.png" % k)) == shipped[k])
            print("  info: %d/10 regenerated frames are byte-identical to the shipped ones" % identical)
            worst = _pixel_diff(work, shipped_dir)
            if worst:
                print("  info: regenerated vs shipped frames: max %d/255, mean %.3f/255, worst frame %.2f%% "
                      "of pixels differ (render noise: within 1/255 on the machine that made the shipped "
                      "frames, a few grey levels on other hardware)" % (worst[0], worst[1], worst[2] * 100))
            else:
                print("  info: Pillow/numpy not available, pixel comparison skipped")

        single = os.path.join(work, "output", "look_left.png")
        code, out = blender(exe, work, "--python", "wrapper/eyes.py", "--", "--look", "left", "--out", single,
                            *(["--no-render"] if False else []))
        check(code == 0 and os.path.exists(single), "README command: eyes.py --look left renders a frame",
              "" if code == 0 else out[-1500:])

        for name in ("test_sequence_and_metadata", "test_directions"):
            code, out = blender(exe, work, "--python", os.path.join("tests", name + ".py"))
            fails = [l for l in out.splitlines() if "[FAIL]" in l]
            check(code == 0, name + " passes inside the clean copy", "; ".join(fails[:5]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("RESULT test_clean_run: %s (%d failed)" % ("PASSED" if failures == 0 else "FAILED", failures))
    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
