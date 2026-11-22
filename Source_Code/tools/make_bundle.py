"""Build the submission zip with the exact layout the evaluators expect (plain Python).

    python tools/make_bundle.py                  # -> VITChennai_PANT.zip in this folder
    python tools/make_bundle.py --out X.zip

The files sit at the root of the zip (scene.blend, wrapper/, renders/, metadata.json,
README.md) plus the extras: textures, tests, per-frame metadata, the direction check, the
contact sheet, and the scripts that rebuild the scene and its textures.
Development material (debug renders, downloaded assets, the virtual environment, git) is
left out.
"""
import argparse
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "VITChennai_PANT.zip"

FILES = ["scene.blend", "README.md", "metadata.json", "contact_sheet.png", "build_scene.py"]
DIRS = {                                   # folder -> allowed extensions
    "wrapper": (".py",),
    "renders": (".png",),
    "metadata_frames": (".json",),
    "direction_check": (".png", ".json", ".gif"),
    "textures": (".png",),
    "tests": (".py",),
}
TOOLS = ["make_textures.py", "bake_skin.py", "make_contact_sheet.py", "make_direction_sheet.py",
         "make_direction_gif.py", "gaze_panel.py", "make_bundle.py"]
REQUIRED = ["scene.blend", "wrapper/eyes.py", "metadata.json", "README.md"] + \
           ["renders/frame_%02d.png" % k for k in range(10)]


def collect():
    items = list(FILES)
    for d, exts in DIRS.items():
        for name in sorted(os.listdir(os.path.join(ROOT, d))):
            if name.lower().endswith(exts) and os.path.isfile(os.path.join(ROOT, d, name)):
                items.append(d + "/" + name)
    items += ["tools/" + t for t in TOOLS]
    missing = [i for i in items + REQUIRED if not os.path.isfile(os.path.join(ROOT, i))]
    if missing:
        sys.exit("missing files: " + ", ".join(sorted(set(missing))))
    return sorted(set(items))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, NAME))
    out = os.path.abspath(ap.parse_args().out)
    items = collect()
    renders = [i for i in items if i.startswith("renders/")]
    if renders != ["renders/frame_%02d.png" % k for k in range(10)]:
        sys.exit("renders/ must hold exactly frame_00..frame_09.png, found: %s" % renders)
    if os.path.exists(out):
        os.remove(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in items:
            z.write(os.path.join(ROOT, rel), rel)
    size = os.path.getsize(out) / 1e6
    print("wrote %s (%d files, %.1f MB)" % (out, len(items), size))


if __name__ == "__main__":
    main()
