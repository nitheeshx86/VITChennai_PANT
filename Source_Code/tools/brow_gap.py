import bpy, sys, os
import numpy as np
from mathutils.bvhtree import BVHTree
dg = bpy.context.evaluated_depsgraph_get()
def bvh(obj):
    ev = obj.evaluated_get(dg); me = ev.to_mesh(); mw = ev.matrix_world
    v = [mw @ x.co for x in me.vertices]; p = [list(f.vertices) for f in me.polygons]
    ev.to_mesh_clear(); return BVHTree.FromPolygons(v, p)
human = bpy.data.objects["Human"]
skin = bvh(human)
mods = [(m.name, m.type, getattr(m, "levels", None), getattr(m, "render_levels", None)) for m in human.modifiers]
print("GAP human modifiers", mods)
for name in ("Human.eyebrow001", "BrowStrands", "Human.eyelashes_strands"):
    o = bpy.data.objects.get(name)
    if o is None: continue
    ev = o.evaluated_get(dg); me = ev.to_mesh(); mw = ev.matrix_world
    pts = [mw @ x.co for x in me.vertices]
    ev.to_mesh_clear()
    # all vertices (roots, shafts and tips)
    d = []
    for q in pts:
        loc, nrm, idx, dist = skin.find_nearest(q)
        if loc is None: continue
        s = 1.0 if (q - loc).dot(nrm) >= 0 else -1.0
        d.append(s * dist)
    d = np.array(d) * 1000
    print("GAP %-24s n=%5d distance to skin (mm): median %.2f  p90 %.2f  max %.2f  min %.2f" % (name, len(d), np.median(d), np.percentile(d, 90), d.max(), d.min()))
