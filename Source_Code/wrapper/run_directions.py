"""Render the five direction-check poses (Reset, Left, Right, Up, Down).

    blender --background scene.blend --python wrapper/run_directions.py
    python wrapper/run_directions.py                (starts Blender itself)

Writes direction_check/<name>.png and direction_check/metadata.json (same record schema as
metadata.json). tools/make_direction_sheet.py turns them into direction_check/sheet.png.
renders/ is not touched (it holds exactly the 10 sequence frames).
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

try:
    import bpy  # noqa: F401
except ImportError:
    sys.path.insert(0, HERE)
    import eyes as _proxy
    _cmd = [_proxy.find_blender(), "--background", os.path.join(os.path.dirname(HERE), "scene.blend"),
            "--python-exit-code", "1", "--python", os.path.abspath(__file__), "--"] + sys.argv[1:]
    sys.exit(subprocess.call(_cmd, cwd=os.path.dirname(HERE)))

sys.path.insert(0, HERE)
import eyes  # noqa: E402

POSES = [("reset", 0.0, 0.0), ("left", -1.0, 0.0), ("right", 1.0, 0.0), ("up", 0.0, 1.0), ("down", 0.0, -1.0)]


def main():
    out = os.path.join(eyes.BUNDLE_ROOT, "direction_check")
    os.makedirs(out, exist_ok=True)
    records = []
    for name, h, v in POSES:
        eyes.move(h, v)
        _, rec = eyes.render(os.path.join(out, name + ".png"))
        rec = dict({"pose": name, "image": "direction_check/%s.png" % name}, **{k: x for k, x in rec.items() if k != "image"})
        records.append(rec)
        print("[run_directions] %-5s L=%s R=%s" % (name, [round(c, 2) for c in rec["pupil_center_2D_L"]],
                                                   [round(c, 2) for c in rec["pupil_center_2D_R"]]))
    with open(os.path.join(out, "metadata.json"), "w") as f:
        json.dump(records, f, indent=2)
    eyes.reset()


if __name__ == "__main__":
    main()
