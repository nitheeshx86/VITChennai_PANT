"""Render several poses in one Blender session: -- name:h:v[:blink] ... [samples=N]"""
import bpy, sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper"))
import eyes
a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
s = bpy.context.scene
s.cycles.samples = 48
for item in a:
    if item.startswith("samples="):
        s.cycles.samples = int(item.split("=")[1]); continue
    parts = item.split(":")
    eyes.reset()
    eyes.move(float(parts[1]), float(parts[2]))
    if len(parts) > 3:
        eyes.blink(float(parts[3]))
    eyes.render(os.path.join(ROOT, "debug", parts[0] + ".png"))
    print("RENDERED", parts[0])
