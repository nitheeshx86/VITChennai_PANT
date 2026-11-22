import bpy, sys, os
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper"))
import eyes
eyes.reset()
cam = eyes._Camera(eyes.calibration())
h = bpy.data.objects["Human"]
dg = bpy.context.evaluated_depsgraph_get(); ev = h.evaluated_get(dg); me = ev.to_mesh(); mw = ev.matrix_world
me.calc_loop_triangles()
verts = [mw @ v.co for v in me.vertices]
tris = [list(t.vertices) for t in me.loop_triangles]
bvh = BVHTree.FromPolygons(verts, tris)
uv = me.uv_layers.active.data
img = bpy.data.images["skin_albedo.png"]; W, H = img.size
px = np.empty(W * H * 4, np.float32); img.pixels.foreach_get(px); px = px.reshape(H, W, 4)
base = bpy.data.images.load(os.path.join(ROOT, "textures", "skin_albedo_base_makehuman.png")); bw, bh = base.size
bp = np.empty(bw * bh * 4, np.float32); base.pixels.foreach_get(bp); bp = bp.reshape(bh, bw, 4)
for name, (x, y) in {"upper_lid": (190, 468), "upper_lid2": (230, 470), "lower_lid": (190, 600), "forehead": (510, 140), "cheek": (830, 760)}.items():
    o, d = cam.ray(x, y)
    loc, n, ti, dist = bvh.ray_cast(o, d)
    t = me.loop_triangles[ti]
    a, b, c = (verts[i] for i in t.vertices)
    from mathutils.geometry import barycentric_transform
    uvs = [Vector((*uv[l].uv, 0)) for l in t.loops]
    q = barycentric_transform(loc, a, b, c, *uvs)
    col = px[int(q.y * H) % H, int(q.x * W) % W, :3]; bcol = bp[int(q.y * bh) % bh, int(q.x * bw) % bw, :3]
    srgb = lambda c: np.where(c <= 0.0031308, 12.92 * c, 1.055 * c ** (1 / 2.4) - 0.055)
    s = srgb(col) * 255; sb = srgb(bcol) * 255
    print("ALB %-10s baked sRGB=(%3.0f,%3.0f,%3.0f) R/G=%.2f   makehuman base sRGB=(%3.0f,%3.0f,%3.0f) R/G=%.2f" % (name, *s, s[0] / s[1], *sb, sb[0] / sb[1]))
