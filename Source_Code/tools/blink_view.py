"""Close views of the blink (scratch cameras; the scene file is not saved).

blender -b scene.blend --python tools/blink_view.py -- NAME [amounts...]
Writes debug/NAME_front_<a>.png (front, eye R + brow) and debug/NAME_side_<a>.png (profile).
"""
import bpy, sys, os
from mathutils import Vector, Matrix
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper"))
import eyes
args = sys.argv[sys.argv.index("--") + 1:]
name = args[0]
amounts = [float(a) for a in args[1:]] or [0.0, 0.5, 1.0]
c = eyes.calibration()
M, F, U, R = eyes._axes(c)
eye = Vector(c["eye_center_R"])
s = bpy.context.scene
s.cycles.samples = int(os.environ.get("BV_SAMPLES", "48"))
s.render.resolution_percentage = 60
s.render.image_settings.file_format = "PNG"


def camera(nm, loc, target, lens):
    cd = bpy.data.cameras.new(nm); cd.lens = lens; cd.clip_start = 0.01
    cam = bpy.data.objects.new(nm, cd); s.collection.objects.link(cam)
    z = (loc - target).normalized(); x = U.cross(z).normalized(); y = z.cross(x)
    m = Matrix((x, y, z)).transposed().to_4x4(); m.translation = loc; cam.matrix_world = m
    return cam


ft = eye + U * 0.006 + F * 0.012
front = camera("BV_Front", ft + F * 0.30 + U * 0.01, ft, 200)
st = eye + U * 0.004 + F * 0.012
side = camera("BV_Side", st - R * 0.11 + F * 0.025 + U * 0.004, st, 105)
for a in amounts:
    eyes.blink(a)
    for cam, tag in ((front, "front"), (side, "side")):
        s.camera = cam
        s.render.filepath = os.path.join(ROOT, "debug", "%s_%s_%03d.png" % (name, tag, round(a * 100)))
        bpy.ops.render.render(write_still=True)
        print("BV wrote", s.render.filepath)
