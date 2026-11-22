"""Run the whole verification suite with one command (plain Python, no packages needed).

    python tests/run_all.py                 # everything except the slow clean-room test
    python tests/run_all.py --clean-run     # also the clean-room test
    python tests/run_all.py test_directions # a subset

Blender is located via the BLENDER environment variable, PATH, or the default install dirs.
"""
import glob
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLENDER_TESTS = [
    "test_scale_and_calibration",
    "test_directions",
    "test_pupil_projection_matches_image",
    "test_sequence_and_metadata",
    "test_determinism",
    "test_optics",
    "test_saccade",
]


def find_blender():
    cand = [os.environ.get("BLENDER"), shutil.which("blender")]
    cand += sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender*\blender.exe"), reverse=True)
    cand += ["/Applications/Blender.app/Contents/MacOS/Blender", "/usr/bin/blender", "/snap/bin/blender"]
    for c in cand:
        if c and os.path.exists(c):
            return c
    sys.exit("Blender not found. Set the BLENDER environment variable to the blender executable.")


def run_blender_test(blender, name, bundle=ROOT):
    cmd = [blender, "--background", os.path.join(bundle, "scene.blend"), "--python-exit-code", "1",
           "--python", os.path.join(bundle, "tests", name + ".py")]
    proc = subprocess.run(cmd, cwd=bundle, capture_output=True, text=True, errors="replace")
    out = proc.stdout + proc.stderr
    lines = [l for l in out.splitlines() if l.startswith("  [") or l.startswith("RESULT") or l.startswith("=====") or l.startswith("  info")]
    passed = proc.returncode == 0 and any(l.startswith("RESULT") and "PASSED" in l for l in lines)
    return passed, lines, out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    verbose = "--quiet" not in sys.argv
    blender = find_blender()
    names = args or BLENDER_TESTS
    results = {}
    for name in names:
        if name == "test_clean_run":
            continue
        ok, lines, out = run_blender_test(blender, name)
        results[name] = ok
        for l in lines:
            if verbose or "FAIL" in l or l.startswith("RESULT") or l.startswith("====="):
                print(l)
        if not lines:
            print(out[-3000:])
    if "--clean-run" in sys.argv or "test_clean_run" in args:
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "test_clean_run.py")] +
                              [a for a in sys.argv[1:] if a.startswith("--zip=")], cwd=ROOT)
        results["test_clean_run"] = proc.returncode == 0
    print("\n================ SUMMARY ================")
    for name, ok in results.items():
        print("%-40s %s" % (name, "PASSED" if ok else "FAILED"))
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
