"""Quick look: blender -b scene.blend --python tools/preview.py -- [h v] [name] [lens_mm] [samples] [pct]"""
import bpy, sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper"))
import eyes
a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
h = float(a[0]) if len(a) > 0 else 0.0
v = float(a[1]) if len(a) > 1 else 0.0
name = a[2] if len(a) > 2 else "preview"
s = bpy.context.scene
if len(a) > 3 and float(a[3]) > 0:
    s.camera.data.lens = float(a[3])
s.cycles.samples = int(a[4]) if len(a) > 4 else 32
s.render.resolution_percentage = int(a[5]) if len(a) > 5 else 50
eyes.move(h, v)
p, rec = eyes.render(os.path.join(ROOT, "debug", name + ".png"))
print("PUPILS", rec["pupil_center_2D_L"], rec["pupil_center_2D_R"], "device", s.cycles.device)
