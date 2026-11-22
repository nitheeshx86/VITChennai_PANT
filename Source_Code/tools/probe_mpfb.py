import bpy, sys, importlib
from mathutils import Vector
mod = None
for name in ("bl_ext.user_default.mpfb", "mpfb"):
    try:
        mod = importlib.import_module(name); break
    except Exception as e:
        print("import fail", name, e)
print("MPFB module:", mod)
base = mod.__name__
HumanService = importlib.import_module(base + ".services.humanservice").HumanService
LocationService = importlib.import_module(base + ".services.locationservice").LocationService
print("user_home", LocationService.get_user_home())
print("user_data", LocationService.get_user_data())
bpy.ops.wm.read_factory_settings(use_empty=True)
import addon_utils
bm = HumanService.create_human(scale=0.1)
print("basemesh", bm.name, "dims", tuple(round(d,4) for d in bm.dimensions), "scale", tuple(bm.scale), "nverts", len(bm.data.vertices))
print("uv layers", [u.name for u in bm.data.uv_layers])
for vg in bm.vertex_groups:
    n = vg.name.lower()
    if "eye" in n or "head" in n:
        idx = vg.index
        vs = [bm.matrix_world @ v.co for v in bm.data.vertices if any(g.group == idx for g in v.groups)]
        if vs:
            c = sum(vs, Vector()) / len(vs)
            mn = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
            mx = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
            print(f"{vg.name:32s} n={len(vs):5d} c=({c.x:.4f},{c.y:.4f},{c.z:.4f}) size=({mx.x-mn.x:.4f},{mx.y-mn.y:.4f},{mx.z-mn.z:.4f})")
rig = HumanService.add_builtin_rig(bm, "default", import_weights=True)
rig = rig or next(o for o in bpy.data.objects if o.type == "ARMATURE")
print("rig", rig.name, len(rig.data.bones))
for b in rig.data.bones:
    if "eye" in b.name.lower() or b.name.lower() in ("head", "neck", "jaw"):
        h = rig.matrix_world @ b.head_local; t = rig.matrix_world @ b.tail_local
        print(f"bone {b.name:20s} head=({h.x:.4f},{h.y:.4f},{h.z:.4f}) tail=({t.x:.4f},{t.y:.4f},{t.z:.4f}) parent={b.parent.name if b.parent else None}")
