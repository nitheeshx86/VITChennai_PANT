import bpy, sys, os
from mathutils import Vector
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper"))
import eyes
eyes.reset()
dg = bpy.context.evaluated_depsgraph_get()
pts = {"dark": Vector((-0.04215, -0.13799, 1.67791)), "dark2": Vector((-0.04238, -0.13764, 1.67731)), "lit": Vector((-0.04052, -0.14037, 1.67692))}
for lname in ("Key", "Fill", "Rim"):
    L = bpy.data.objects[lname]
    for pname, p in pts.items():
        blockers = {}
        n = 0
        for i in range(-2, 3):
            for j in range(-2, 3):
                lp = L.matrix_world @ Vector((i * L.data.size / 5.0, j * L.data.size_y / 5.0, 0))
                d = (lp - p).normalized()
                o = p + d * 2e-4
                dist = (lp - p).length
                names = []
                for k in range(6):
                    hit, loc, nrm, idx, obj, mat = bpy.context.scene.ray_cast(dg, o, d, distance=dist)
                    if not hit: break
                    names.append(obj.name)
                    o = loc + d * 1e-5
                    dist = (lp - o).length
                solid = [x for x in names if not x.startswith("Cornea") and not x.startswith("TearLine")]
                n += 1
                key = ",".join(sorted(set(solid))) or "clear"
                blockers[key] = blockers.get(key, 0) + 1
        print("SHADOW", lname, pname, blockers)
