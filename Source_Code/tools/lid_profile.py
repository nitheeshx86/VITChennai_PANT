"""Print the upper-lid profile of eye R: skin depth (mm in front of the globe centre) vs height
above the lid margin, at several columns; marks where the brow card starts.
blender -b scene.blend --python tools/lid_profile.py"""
import bpy, sys, os
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper"))
import eyes
c = eyes.calibration()
eyes.reset()
M, F, U, R = eyes._axes(c)
dg = bpy.context.evaluated_depsgraph_get()


def bvh(name):
    ob = bpy.data.objects[name].evaluated_get(dg)
    me = ob.to_mesh()
    vs = [ob.matrix_world @ v.co for v in me.vertices]
    me.calc_loop_triangles()
    t = BVHTree.FromPolygons(vs, [tuple(x.vertices) for x in me.loop_triangles])
    ob.to_mesh_clear()
    return t


skin = bvh("Human")
card = next(o.name for o in bpy.data.objects if o.type == "MESH" and "eyebrow" in o.name.lower() and "strand" not in o.name.lower())
brow = bvh(card)
for side in ("R", "L"):
    e = Vector(c["eye_center_" + side])
    for xo in (-6, -3, 0, 3, 6):
        x = xo * 1e-3
        # margin: march up from the centre until the front ray hits skin
        zm = None
        rows = []
        for i in range(0, 120):
            z = -0.002 + i * 0.00025
            p = e + R * x + U * z
            hit = skin.ray_cast(p + F * 0.05, -F, 0.1)
            d = (hit[0] - e).dot(F) if hit[0] is not None else None
            bh = brow.ray_cast(p + F * 0.05, -F, 0.1)
            if zm is None and d is not None and d > 0.004:
                zm = z
            if zm is not None and i % 4 == 0:
                rows.append("%5.1f:%5.1f%s" % ((z - zm) * 1e3, d * 1e3 if d else -1, "B" if bh[0] is not None else ""))
        print("PROFILE %s x=%+d margin z=%.1f | %s" % (side, xo, (zm or 0) * 1e3, " ".join(rows)))
