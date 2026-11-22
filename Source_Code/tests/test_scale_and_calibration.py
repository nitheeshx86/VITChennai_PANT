"""Scale + calibration checks.  blender --background scene.blend --python tests/test_scale_and_calibration.py"""
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import eyes, run_test  # noqa: E402

MM = 1e-3


def sclera_points(obj):
    """World positions of the eyeball's sclera vertices (they lie on the globe sphere)."""
    idx = [i for i, m in enumerate(obj.data.materials) if m and "Sclera" in m.name][0]
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    mw = ev.matrix_world.copy()
    vids = set()
    for p in obj.data.polygons:
        if p.material_index == idx:
            vids.update(p.vertices)
    return [mw @ obj.data.vertices[i].co for i in vids]


def sphere_fit(points):
    """Least-squares sphere through points -> (centre, radius, max residual)."""
    import numpy as np
    p = np.array([tuple(q) for q in points], dtype=np.float64)
    a = np.hstack([2 * p, np.ones((len(p), 1))])
    b = (p ** 2).sum(axis=1)
    sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    c = sol[:3]
    r = math.sqrt(sol[3] + (c ** 2).sum())
    res = np.abs(np.linalg.norm(p - c, axis=1) - r).max()
    return Vector(c), r, float(res)


def test(c):
    calib = eyes.calibration()
    scene = bpy.context.scene
    f = Vector(calib["forward"]).normalized()
    u = Vector(calib["up"]).normalized()
    cl, cr = Vector(calib["eye_center_L"]), Vector(calib["eye_center_R"])
    m = (cl + cr) / 2
    eyes.reset()

    # ---- real-world scale ----
    c.check(scene.unit_settings.system == "METRIC" and abs(scene.unit_settings.scale_length - 1.0) < 1e-9,
            "scene units are metres")
    fits = {}
    for side in "LR":
        centre, radius, res = sphere_fit(sclera_points(bpy.data.objects["Eyeball." + side]))
        fits[side] = centre
        c.check(0.022 <= 2 * radius <= 0.026, "eyeball %s diameter realistic" % side, "%.2f mm (fit residual %.4f mm)" % (2 * radius / MM, res / MM))
        c.check((centre - Vector(calib["eye_center_" + side])).length < 0.05 * MM,
                "eyeball %s geometric centre == calibrated centre" % side,
                "%.4f mm apart" % ((centre - Vector(calib["eye_center_" + side])).length / MM))
    ipd = (fits["L"] - fits["R"]).length
    c.check(0.060 <= ipd <= 0.066, "inter-pupillary distance realistic", "%.2f mm" % (ipd / MM))
    human = bpy.data.objects["Human"]
    height = max((human.matrix_world @ Vector(b)).z for b in human.bound_box) - min((human.matrix_world @ Vector(b)).z for b in human.bound_box)
    c.check(1.5 <= height <= 2.0, "body height plausible", "%.3f m" % height)

    # ---- the iris sits near the middle of the lid opening (what makes gaze read naturally:
    #      viewers judge gaze by the white visible on each side of the iris) ----
    mid_pt = (Vector(calib["eye_center_L"]) + Vector(calib["eye_center_R"])) / 2
    right_axis = Vector(calib["image_right"])
    for side in "LR":
        ap = calib.get("aperture_" + side)
        if not ap:
            continue
        width = ap["x"][-1] - ap["x"][0]
        on_right = (Vector(calib["eye_center_" + side]) - mid_pt).dot(right_axis) > 0
        nasal = -ap["x"][0] if on_right else ap["x"][-1]
        frac = nasal / width
        c.check(0.46 <= frac <= 0.54, "eye %s iris is centred in the lid opening" % side,
                "%.3f of the width from the inner corner" % frac)
        c.check(0.024 <= width <= 0.031, "eye %s lid opening length realistic" % side, "%.1f mm" % (width / MM))
        white_nasal = nasal - calib["iris_radius"]
        white_temporal = (width - nasal) - calib["iris_radius"]
        c.check(min(white_nasal, white_temporal) / max(white_nasal, white_temporal) > 0.8,
                "eye %s has similar room on both sides of the iris" % side,
                "nasal %.1f mm, temporal %.1f mm" % (white_nasal / MM, white_temporal / MM))

    # ---- hair and the brow card sit ON the skin (seen from any side, nothing floats) ----
    import numpy as np
    from mathutils.bvhtree import BVHTree
    dg = bpy.context.evaluated_depsgraph_get()
    hv = bpy.data.objects["Human"].evaluated_get(dg)
    hm = hv.to_mesh()
    skin = BVHTree.FromPolygons([hv.matrix_world @ v.co for v in hm.vertices], [list(f.vertices) for f in hm.polygons])
    hv.to_mesh_clear()
    for name, med_max, top_max in (("BrowStrands", 0.0008, 0.0020), ("Human.eyebrow001", 0.0003, 0.0006)):
        o = bpy.data.objects.get(name)
        if o is None or o.hide_render:
            continue
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        d = []
        for v in me.vertices:
            q = ev.matrix_world @ v.co
            loc, nrm, _i, dist = skin.find_nearest(q)
            if loc is not None:
                d.append(dist if (q - loc).dot(nrm) >= 0 else 0.0)
        ev.to_mesh_clear()
        d = np.array(d)
        c.check(np.median(d) <= med_max and np.percentile(d, 99.5) <= top_max, "%s lies on the skin" % name,
                "median %.2f mm, 99.5%% %.2f mm above it" % (np.median(d) / MM, np.percentile(d, 99.5) / MM))

    # ---- blink: thin lid skin slides over the globe, the brow stays where it is ----
    def evaluated_points(name):
        ev = bpy.data.objects[name].evaluated_get(bpy.context.evaluated_depsgraph_get())
        me = ev.to_mesh()
        pts = np.array([tuple(ev.matrix_world @ v.co) for v in me.vertices])
        ev.to_mesh_clear()
        return pts

    def skin_bvh():
        hv = bpy.data.objects["Human"].evaluated_get(bpy.context.evaluated_depsgraph_get())
        hm = hv.to_mesh()
        t = BVHTree.FromPolygons([hv.matrix_world @ v.co for v in hm.vertices], [list(f.vertices) for f in hm.polygons])
        hv.to_mesh_clear()
        return t

    if calib.get("lid_follow", {}).get("blink_keys"):
        eyes.reset()
        brow_names = [n for n in ("BrowStrands", "Human.eyebrow001") if bpy.data.objects.get(n) is not None]
        rest = {n: evaluated_points(n) for n in brow_names}
        cam_pos = bpy.data.objects[calib["camera"]].matrix_world.translation.copy()
        for amount in (0.5, 1.0):
            eyes.blink(amount)
            for n in brow_names:
                moved = np.linalg.norm(evaluated_points(n) - rest[n], axis=1)
                lim = 0.0003 if n == "BrowStrands" else 0.0005    # the card is shrinkwrapped: slides on the skin
                c.check(np.percentile(moved, 99) <= lim, "blink %.1f: %s stays put" % (amount, n),
                        "99%% of vertices move <= %.3f mm (max %.3f)" % (np.percentile(moved, 99) / MM, moved.max() / MM))
        # closed: no part of either eyeball is visible from the camera, and the lid is a thin
        # drape over the cornea (not a thick block standing off the eye)
        skin = skin_bvh()
        for side in "LR":
            centre = Vector(calib["eye_center_" + side])
            seen = total = 0
            for p in evaluated_points("Eyeball." + side)[::7]:
                p = Vector(tuple(p))
                if (p - centre).dot(cam_pos - centre) <= 0.0:
                    continue
                total += 1
                d = (p - cam_pos)
                hit = skin.ray_cast(cam_pos, d.normalized(), d.length - 0.00005)
                if hit[0] is None:
                    seen += 1
            c.check(total > 50 and seen == 0, "blink 1.0: eye %s fully covered by the lids" % side,
                    "%d of %d front eyeball points visible" % (seen, total))
            axis = eyes.eye_pose(side)["axis"]
            hit = skin.ray_cast(centre + axis * 0.03, -axis, 0.03)
            gap = (hit[0] - centre).length - calib["cornea_apex_offset"] if hit[0] is not None else None
            c.check(gap is not None and 0.0003 <= gap <= 0.0035, "blink 1.0: eye %s closed lid is a thin drape over the cornea" % side,
                    "lid surface %.2f mm in front of the cornea apex" % (gap / MM if gap is not None else -1))
        eyes.blink(0.0)
        eyes.reset()

    # ---- eye bones pivot at the eyeball centres ----
    rig = bpy.data.objects[calib["rig"]]
    for side in "LR":
        head = rig.matrix_world @ rig.data.bones[calib["bone_" + side]].head_local
        c.check((head - fits[side]).length < 0.05 * MM, "bone %s head at eyeball centre" % calib["bone_" + side],
                "%.4f mm" % ((head - fits[side]).length / MM))
    c.check(calib["bone_L"] != calib["bone_R"], "separate left and right eye bones")

    # ---- camera ----
    cam = bpy.data.objects[calib["camera"]]
    cp = cam.matrix_world.translation
    d = (cp - m).dot(f)
    lateral = ((cp - m) - f * d).length
    c.check(abs(d - 0.40) < 1 * MM, "camera 0.40 m in front of the eye midpoint", "%.5f m" % d)
    c.check(lateral < 1 * MM, "camera on the forward axis", "off-axis %.4f mm" % (lateral / MM))
    view = -(cam.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
    ang = math.degrees(view.angle((m - cp).normalized()))
    c.check(ang < 0.05, "camera looks at the eye midpoint", "%.4f deg off" % ang)
    cam_up = (cam.matrix_world.to_3x3() @ Vector((0, 1, 0))).normalized()
    c.check(cam_up.dot(u) > 0.9999, "camera upright")
    rs = scene.render
    c.check((rs.resolution_x, rs.resolution_y, rs.resolution_percentage) == (1024, 1024, 100), "render is 1024x1024")
    p_mid = eyes.project(m)
    c.check(abs(p_mid[0] - 512) < 0.01 and abs(p_mid[1] - 512) < 0.01, "eye midpoint projects to the image centre", str([round(x, 3) for x in p_mid]))

    # ---- fixation target ----
    t0 = eyes.target_for(0, 0)
    c.check(abs((t0 - m).dot(f) - 0.35) < 1 * MM and ((t0 - m) - f * (t0 - m).dot(f)).length < 1 * MM,
            "reset target 0.35 m straight ahead of the eye midpoint", "%.5f m" % (t0 - m).dot(f))
    for h, v in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (5, -7)):
        t = eyes.target_for(h, v)
        off = t - t0
        c.check(abs(off.dot(f)) < 1e-6 and abs(off.dot(Vector(calib["image_right"]))) <= 0.05 + 1e-6 and abs(off.dot(u)) <= 0.05 + 1e-6,
                "target for (%g, %g) stays on the 35 cm plane within +/-5 cm" % (h, v),
                "offset %s mm" % [round(x / MM, 2) for x in off])

    # ---- vergence: each eye's line of sight (visual axis) passes through the shared target;
    #      the optical axis sits KAPPA_DEG temporally of it (angle kappa) ----
    for h, v in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (0.7, -0.7), (-0.3, 0.9)):
        eyes.move(h, v)
        t = eyes.target_for(h, v)
        worst = 0.0
        for side in "LR":
            pose = eyes.eye_pose(side)
            miss = ((t - pose["centre"]) - pose["visual"] * (t - pose["centre"]).dot(pose["visual"])).length
            worst = max(worst, miss)
            kappa = math.degrees(pose["visual"].angle(pose["axis"]))
            c.check(abs(kappa - eyes.KAPPA_DEG) < 1e-3, "eye %s optical axis is kappa from the visual axis at (%g, %g)" % (side, h, v),
                    "%.4f deg" % kappa)
            nasal = eyes._nasal(side)
            c.check(eyes.KAPPA_DEG == 0 or (pose["visual"] - pose["axis"]).dot(nasal) > 0,
                    "eye %s visual axis lies nasal of the optical axis" % side)
            c.check((pose["centre"] - Vector(calib["eye_center_" + side])).length < 1e-6,
                    "eye %s centre fixed at (%g, %g)" % (side, h, v))
        c.check(worst < 1 * MM, "both lines of sight (visual axes) hit the target at (%g, %g)" % (h, v), "miss %.5f mm" % (worst / MM))
    # ---- Listing's law: every rotation axis lies in the plane perpendicular to the primary
    #      (straight-ahead) direction F, i.e. no torsion about the line of sight ----
    for h, v in ((1, 0), (0, 1), (0.7, 0.7), (-0.7, 0.7), (-1, -0.3)):
        eyes.move(h, v)
        for side in "LR":
            q = eyes.eye_pose(side)["matrix"].to_quaternion()
            ax = Vector((q.x, q.y, q.z))
            off = abs(ax.normalized().dot(f)) if ax.length > 1e-9 else 0.0
            c.check(off < 1e-5, "Listing's law: eye %s rotation axis in Listing's plane at (%g, %g)" % (side, h, v),
                    "|axis . F| = %.1e" % off)
    eyes.reset()
    rl, rr = eyes.eye_pose("L"), eyes.eye_pose("R")
    verg = math.degrees(rl["visual"].angle(rr["visual"]))
    expect = math.degrees(2 * math.atan((ipd / 2) / 0.35))
    c.check(abs(verg - expect) < 0.05, "vergence angle (between the lines of sight) at reset matches geometry",
            "%.3f deg (expected %.3f)" % (verg, expect))
    # symmetry: the two eyes turn by matching amounts for a sideways gaze (what makes them
    # look like they move together)
    for h in (1.0, -1.0, 0.951):
        eyes.move(h, 0)
        a = [math.degrees(math.atan2(eyes.eye_pose(s)["axis"].dot(Vector(calib["image_right"])),
                                     eyes.eye_pose(s)["axis"].dot(f))) for s in "LR"]
        c.check(abs(a[0] - a[1]) < 2.0 or eyes.KAPPA_DEG == 0, "eyes turn by similar amounts at h=%g" % h,
                "L %.1f deg, R %.1f deg" % (a[0], a[1]))
    eyes.reset()

    # ---- pivot: a 90 degree rotation leaves the globe centre where it is ----
    for side in "LR":
        name = calib["bone_" + side]
        pb = rig.pose.bones[name]
        saved = pb.matrix.copy()
        centre = Vector(calib["eye_center_" + side])
        for axis in (u, Vector(calib["image_right"])):
            rot = Matrix.Rotation(math.radians(90), 4, axis)
            world_rest = rig.matrix_world @ rig.data.bones[name].matrix_local
            pb.matrix = rig.matrix_world.inverted() @ (Matrix.Translation(centre) @ rot @ Matrix.Translation(-centre) @ world_rest)
            bpy.context.view_layer.update()
            c2, r2, res2 = sphere_fit(sclera_points(bpy.data.objects["Eyeball." + side]))
            c.check((c2 - centre).length < 0.05 * MM, "eye %s centre unmoved by a 90 deg rotation" % side,
                    "moved %.5f mm" % ((c2 - centre).length / MM))
            pose = eyes.eye_pose(side)
            c.check(abs(math.degrees(pose["axis"].angle(f)) - 90) < 0.01, "eye %s optical axis really rotated 90 deg" % side)
        pb.matrix = saved
        bpy.context.view_layer.update()
    eyes.reset()


run_test("test_scale_and_calibration", test)
