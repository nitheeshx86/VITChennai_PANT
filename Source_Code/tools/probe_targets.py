import bpy, sys, os, importlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_scene as B
base = B.mpfb_module()
HS = importlib.import_module(base + ".services.humanservice").HumanService
TS = importlib.import_module(base + ".services.targetservice").TargetService
TDIR = os.path.join(os.path.dirname(importlib.import_module(base).__file__), "data", "targets", "eyes")
def trial(label, targets):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bm = HS.create_human(scale=B.HUMAN_SCALE)
    for name, w in targets.items():
        for side in "lr":
            TS.load_target(bm, os.path.join(TDIR, "%s-eye-%s.target.gz" % (side, name)), weight=w, name="%s-eye-%s" % (side, name))
    TS.bake_targets(bm)
    j = B.bbox_centre(B.group_points(bm, "joint-l-eye")); jr = B.bbox_centre(B.group_points(bm, "joint-r-eye"))
    h = B.group_points(bm, "helper-l-eye")
    rx = (max(p.x for p in h) - min(p.x for p in h)) / 2; rz = (max(p.z for p in h) - min(p.z for p in h)) / 2
    apex = max(j.y - p.y for p in h)
    from mathutils import Vector
    dg = bpy.context.evaluated_depsgraph_get(); ev = bm.evaluated_get(dg)
    openpts = []
    rows = []
    for iz in range(-14, 15):
        row = ""
        for ix in range(-22, 23):
            o = Vector((j.x + ix * 0.001, j.y - 0.06, j.z + iz * 0.001))
            hit, loc, n, fi = ev.ray_cast(o, Vector((0, 1, 0)))
            is_open = (not hit) or loc.y > j.y - 0.002
            row += "." if is_open else "#"
            if is_open: openpts.append((ix, iz))
        rows.append(row)
    if openpts:
        xs = [p[0] for p in openpts]; zs = [p[1] for p in openpts]
        mid = [p[1] for p in openpts if p[0] == 0]
        print("TRIAL   aperture x[%d..%d] z[%d..%d] mm rel joint; at x=0 z[%s..%s]" % (min(xs), max(xs), min(zs), max(zs), min(mid) if mid else None, max(mid) if mid else None))
    if label in ("none", "scale-decr 1.0"):
        for r in reversed(rows): print("TRIAL   " + r)
    print("TRIAL %-34s ipd=%.2f mm  helper rx=%.2f rz=%.2f apex=%.2f  joint z=%.4f y=%.4f" % (label, (j - jr).length * 1e3, rx * 1e3, rz * 1e3, apex * 1e3, j.z, j.y))
trial("none", {})
trial("scale-decr 0.5", {"scale-decr": 0.5})
trial("scale-decr 1.0", {"scale-decr": 1.0})
trial("trans-out 1.0", {"trans-out": 1.0})
trial("height2-incr 1.0", {"height2-incr": 1.0})
