"""Render a close side view of the brow (a scratch camera; the scene file is not saved)."""
import bpy, sys, os, math
from mathutils import Vector, Matrix
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper"))
import eyes
name = sys.argv[sys.argv.index("--") + 1]
c = eyes.calibration()
M, F, U, R = eyes._axes(c)
eye = Vector(c["eye_center_R"])
target = eye + U * 0.013 + F * 0.010            # the brow above eye R
loc = target - R * 0.11 + F * 0.03 + U * 0.005  # from the temple side, slightly in front
cam_data = bpy.data.cameras.new("Side"); cam_data.lens = 85; cam_data.clip_start = 0.01
cam = bpy.data.objects.new("Side", cam_data); bpy.context.scene.collection.objects.link(cam)
z = (loc - target).normalized(); x = U.cross(z).normalized(); y = z.cross(x)
m = Matrix((x, y, z)).transposed().to_4x4(); m.translation = loc; cam.matrix_world = m
s = bpy.context.scene
s.camera = cam
s.cycles.samples = 48
s.render.resolution_percentage = 70
s.render.filepath = os.path.join(ROOT, "debug", name + ".png")
s.render.image_settings.file_format = "PNG"
bpy.ops.render.render(write_still=True)
print("SIDE wrote", s.render.filepath)
