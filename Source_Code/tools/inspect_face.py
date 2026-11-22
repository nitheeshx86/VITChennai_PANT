import bpy, sys
import numpy as np
h = bpy.data.objects["Human"]
dg = bpy.context.evaluated_depsgraph_get()
ev = h.evaluated_get(dg)
me = ev.data
for fi in (18187, 18188):
    poly = me.polygons[fi]
    uvs = [tuple(round(c, 5) for c in me.uv_layers[0].data[li].uv) for li in poly.loop_indices]
    print("FACE", fi, "uvs", uvs, "verts", list(poly.vertices))
img = bpy.data.images["skin_albedo.png"]
w, hh = img.size
px = np.empty(w * hh * 4, np.float32); img.pixels.foreach_get(px); px = px.reshape(hh, w, 4)
poly = me.polygons[18187]
uv = np.mean([me.uv_layers[0].data[li].uv[:] for li in poly.loop_indices], axis=0)
x, y = int(uv[0] * w), int(uv[1] * hh)
print("FACE centre texel", x, y)
win = px[y - 40:y + 40, x - 40:x + 40, :3]
dark = np.argwhere(win.max(axis=2) < 0.05)
print("FACE dark texels in 80x80 window:", len(dark), dark[:10].tolist())
print("FACE whole-image dark fraction", float((px[..., :3].max(axis=2) < 0.02).mean()))
