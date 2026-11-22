"""Search key-light placements: both corneal glints fully unoccluded at every test gaze,
glints well clear of the pupil, glints on the cornea."""
import bpy, sys, os, math, json
from mathutils import Vector
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper"))
import eyes
c = eyes.calibration()
M, F, U, R = eyes._axes(c)
key = bpy.data.objects["Key"]
gazes = [(0, 0), (-1, 0), (1, 0), (0, 1), (0, -1), (0.7, 0.7), (-0.7, 0.7), (0.7, -0.7), (-0.7, -0.7)]
poses = {}
for g in gazes:
    eyes.move(*g)
    poses[g] = {s: eyes.eye_pose(s) for s in "LR"}
    eyes._occluders()           # build per pose
    poses[g]["bvh"] = eyes._OCCLUDER_CACHE["bvh"]
results = []
for polar in range(46, 72, 3):
    for az in range(95, 270, 10):           # 90 = straight up in the image, 180 = image-left
        th, ph = math.radians(polar), math.radians(az)
        dist = 1.0
        loc = M + dist * (F * math.cos(th) + (R * math.cos(ph) + U * math.sin(ph)) * math.sin(th))
        key.matrix_world = eyes_look = None or key.matrix_world
        # orient toward M
        z = (loc - M).normalized(); x = U.cross(z).normalized(); y = z.cross(x)
        from mathutils import Matrix
        mtx = Matrix((x, y, z)).transposed().to_4x4(); mtx.translation = loc
        key.matrix_world = mtx
        worst_frac, worst_clear, ok_cap = 1.0, 1e9, True
        for g in gazes:
            eyes._OCCLUDER_CACHE["key"] = (float(g[0]), float(g[1]), 0.0)
            eyes._OCCLUDER_CACHE["bvh"] = poses[g]["bvh"]
            eyes._state["h"], eyes._state["v"], eyes._state["blink"] = float(g[0]), float(g[1]), 0.0
            for s in "LR":
                gl = [x for x in eyes.corneal_reflections(s, poses[g][s], c) if x["light"] == "Key"]
                if not gl or gl[0]["surface"] != "cornea":
                    ok_cap = False; continue
                gl = gl[0]
                ap = eyes.apparent_pupil(s, poses[g][s], c)
                clear = math.hypot(gl["xy"][0] - ap["center"][0], gl["xy"][1] - ap["center"][1]) - ap["semi_axes"][0]
                worst_frac = min(worst_frac, gl["light_unoccluded_fraction"] if gl["visible"] else 0.0)
                worst_clear = min(worst_clear, clear)
        results.append((worst_frac, worst_clear, ok_cap, polar, az))
results.sort(key=lambda r: (-r[0], -(r[2]), -min(r[1], 25)))
for r in results[:25]:
    print("KEYSEARCH frac=%.2f clear=%.1fpx cap=%s polar=%d az=%d" % r)
