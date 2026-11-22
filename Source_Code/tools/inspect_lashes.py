import bpy, json
from mathutils import Vector
o = bpy.data.objects["Human.eyelashes01"]
c = json.loads(bpy.context.scene["xr_calib"])
cl = Vector(c["eye_center_L"])
mw = o.matrix_world
vs = [mw @ v.co for v in o.data.vertices]
print("LASH verts", len(vs), "faces", len(o.data.polygons), "shape keys", [k.name for k in o.data.shape_keys.key_blocks] if o.data.shape_keys else None)
near = [v for v in vs if (v - cl).length < 0.03]
up = [v for v in near if v.z > cl.z]; lo = [v for v in near if v.z <= cl.z]
print("LASH L upper", len(up), "lower", len(lo))
print("LASH z range upper", round(min(v.z for v in up)-cl.z,4), round(max(v.z for v in up)-cl.z,4), "lower", round(min(v.z for v in lo)-cl.z,4), round(max(v.z for v in lo)-cl.z,4))
# connected components (cards)
import bmesh
bm = bmesh.new(); bm.from_mesh(o.data)
bm.verts.ensure_lookup_table()
seen=set(); comps=[]
for v in bm.verts:
    if v.index in seen: continue
    st=[v]; comp=[]
    seen.add(v.index)
    while st:
        x=st.pop(); comp.append(x.index)
        for e in x.link_edges:
            y=e.other_vert(x)
            if y.index not in seen: seen.add(y.index); st.append(y)
    comps.append(comp)
print("LASH components", len(comps), "sizes", sorted(len(c) for c in comps)[:10], "...")
uv = o.data.uv_layers[0]
m = o.active_material
print("LASH material", m.name, "blend", m.blend_method, [n.type for n in m.node_tree.nodes])
for n in m.node_tree.nodes:
    if n.type == "TEX_IMAGE": print("LASH tex", n.image.name, n.image.size, n.image.alpha_mode)
for comp in sorted(comps, key=len)[-4:]:
    pts=[vs[i] for i in comp]
    print("LASH comp", len(comp), "centre", tuple(round(x,4) for x in (sum(pts,Vector())/len(pts)-cl)))
