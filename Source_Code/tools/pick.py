import bpy, sys, os
from mathutils import Vector
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper"))
import eyes
eyes.reset()
a = sys.argv[sys.argv.index("--") + 1:]
cam = bpy.context.scene.camera
K = eyes.camera_matrices()[0]
dg = bpy.context.evaluated_depsgraph_get()
for i in range(0, len(a), 2):
    u, v = float(a[i]), float(a[i + 1])
    d_cam = Vector(((u - K[0][2]) / K[0][0], -(v - K[1][2]) / K[1][1], -1.0))
    d = (cam.matrix_world.to_3x3() @ d_cam).normalized()
    o = cam.matrix_world.translation
    for n in range(4):
        hit, loc, nrm, idx, obj, mat = bpy.context.scene.ray_cast(dg, o, d)
        if not hit:
            print("PICK", (u, v), "miss"); break
        print("PICK", (u, v), "hit", obj.name, "face", idx, "at", tuple(round(c, 5) for c in loc), "normal.dir", round(nrm.dot(d), 3))
        o = loc + d * 1e-5
