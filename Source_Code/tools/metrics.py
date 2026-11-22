"""Print calibration numbers and pupil pixel shifts (no rendering)."""
import bpy, sys, os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper"))
import eyes
a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if a:
    bpy.context.scene.camera.data.lens = float(a[0])
c = eyes.calibration()
print("METRIC lens", bpy.context.scene.camera.data.lens, "ipd", round(c["ipd"], 5))
r0 = eyes.reset()
for name, (h, v) in [("left", (-1, 0)), ("right", (1, 0)), ("up", (0, 1)), ("down", (0, -1))]:
    r = eyes.move(h, v)
    for s in "LR":
        dx = r["pupil_center_2D_" + s][0] - r0["pupil_center_2D_" + s][0]
        dy = r["pupil_center_2D_" + s][1] - r0["pupil_center_2D_" + s][1]
        print("METRIC %-5s %s dx=%+7.2f dy=%+7.2f euler=%s" % (name, s, dx, dy, [round(e, 4) for e in r["eye_rotation_" + s]]))
