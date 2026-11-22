"""Render the frames for the demo video (camera locked, as for the dataset).

    blender --background scene.blend --python tools/render_demo.py -- [--samples 32] [--segments a,b]

Segments (rendered in this order; each writes demo/frames/<segment>/ and a timeline.json that
lists, for every 30 fps video frame, the PNG to show plus the gaze state for the overlays):

  directions  Reset -> Left -> Reset -> Right -> Reset -> Up -> Reset -> Down -> Reset, with
              human saccade dynamics (eyes.saccade) between the holds
  closeup     two stills at 2x resolution for the realism close-up
  natural     free viewing: saccades to several points, blinks, lids following vertical gaze
  pursuit     the clockwise circle h = sin(t), v = cos(t) as a smooth pursuit, starting at the top
  xray        the same pursuit from an oblique camera with the face hidden and each eye's line
              of sight drawn, to show the globes turning about their centres

Unique poses are rendered once and reused for holds. The scene file is not modified.
"""
import json
import math
import os
import sys
import time

import bpy
from mathutils import Matrix, Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper"))
import eyes  # noqa: E402

FPS = 30
OUT = os.path.join(ROOT, "demo", "frames")
ALL = ["directions", "closeup", "natural", "pursuit", "xray"]

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SAMPLES = int(argv[argv.index("--samples") + 1]) if "--samples" in argv else 32
SEGMENTS = argv[argv.index("--segments") + 1].split(",") if "--segments" in argv else ALL

scene = bpy.context.scene
calib = eyes.calibration()
M, F, U, R = eyes._axes(calib)
T0 = eyes.target_for(0.0, 0.0, calib)
H_AXIS = (eyes.target_for(1.0, 0.0, calib) - T0).normalized()   # +h direction (image right)
V_AXIS = (eyes.target_for(0.0, 1.0, calib) - T0).normalized()   # +v direction (image up)
CMD = {"reset": "eyes.reset()", "left": "eyes.move(-1, 0)", "right": "eyes.move(+1, 0)",
       "up": "eyes.move(0, +1)", "down": "eyes.move(0, -1)"}


# --------------------------------------------------------------------------- timeline helpers
def pose(h, v, blink=0.0, **info):
    d = {"h": float(h), "v": float(v), "blink": float(blink)}
    d.update(info)
    return d


def hold(tl, seconds, h, v, blink=0.0, **info):
    for _ in range(max(1, int(round(seconds * FPS)))):
        tl.append(pose(h, v, blink, **info))


def saccade(tl, h1, v1, **info):
    """Main-sequence saccade from the last pose in tl to (h1, v1) (eyes.saccade)."""
    h0, v0 = (tl[-1]["h"], tl[-1]["v"]) if tl else (0.0, 0.0)
    eyes._state["h"], eyes._state["v"] = h0, v0
    for s in eyes.saccade(h1, v1, fps=FPS)[1:]:
        tl.append(pose(s["h"], s["v"], 0.0, **info))


BLINK = [0.35, 0.75, 1.0, 1.0, 0.85, 0.65, 0.45, 0.28, 0.14, 0.05]   # ~330 ms at 30 fps


def blink(tl, **info):
    h, v = tl[-1]["h"], tl[-1]["v"]
    for b in BLINK:
        tl.append(pose(h, v, b, **info))


def timeline_directions():
    tl = []
    hold(tl, 1.2, 0, 0, phase="reset", cmd=CMD["reset"])
    for name in ("left", "right", "up", "down"):
        h, v = eyes.DIRECTIONS[name]
        saccade(tl, h, v, phase=name, cmd=CMD[name])
        hold(tl, 1.6, h, v, phase=name, cmd=CMD[name])
        saccade(tl, 0, 0, phase="reset", cmd=CMD["reset"])
        hold(tl, 0.8, 0, 0, phase="reset", cmd=CMD["reset"])
    return tl


def timeline_pursuit():
    tl = []
    hold(tl, 0.4, 0, 0, phase="reset", cmd="eyes.reset()")
    saccade(tl, 0, 1, phase="circle", cmd="eyes.move(sin t, cos t)")
    hold(tl, 0.3, 0, 1, phase="circle", cmd="eyes.move(sin t, cos t)")
    n = 3 * FPS                                     # one clockwise loop in 3 s
    for i in range(1, n + 1):
        t = 2 * math.pi * i / n
        tl.append(pose(math.sin(t), math.cos(t), phase="circle", cmd="eyes.move(sin t, cos t)", theta=t))
    hold(tl, 0.3, 0, 1, phase="circle", cmd="eyes.move(sin t, cos t)")
    saccade(tl, 0, 0, phase="reset", cmd="eyes.reset()")
    hold(tl, 0.4, 0, 0, phase="reset", cmd="eyes.reset()")
    return tl


def timeline_natural():
    tl = []
    info = dict(phase="natural", cmd="eyes.saccade(h, v)  +  eyes.blink(a)")
    hold(tl, 0.5, 0, 0, **info)
    for (h, v, dwell, blink_after) in ((0.6, 0.3, 0.55, False), (-0.7, 0.1, 0.45, True),
                                        (0.2, -0.8, 0.7, False), (0.9, 0.6, 0.45, False),
                                        (-0.3, 0.9, 0.6, False), (-0.8, -0.5, 0.5, False),
                                        (0.0, 0.0, 0.35, True)):
        saccade(tl, h, v, **info)
        hold(tl, dwell, h, v, **info)
        if blink_after:
            blink(tl, **info)
            hold(tl, 0.4, h, v, **info)
    return tl


# --------------------------------------------------------------------------- rendering
def readouts():
    """Gaze state of the posed scene for the overlays (cheap: no ray casts)."""
    out = {}
    vis = {}
    for s in "LR":
        p = eyes.eye_pose(s, calib)
        vis[s] = p["visual"]
        out["pupil_" + s] = eyes.project(p["pupil"])
        out["yaw_" + s] = math.degrees(math.atan2(p["visual"].dot(H_AXIS), p["visual"].dot(F)))
        out["pitch_" + s] = math.degrees(math.asin(max(-1.0, min(1.0, p["visual"].dot(V_AXIS)))))
    out["vergence_deg"] = math.degrees(vis["L"].angle(vis["R"]))
    out["target"] = list(eyes.target_for(eyes._state["h"], eyes._state["v"], calib))
    return out


def set_pose(h, v, b):
    eyes._state["blink"] = b
    eyes.move(h, v, record=False)


def render_to(path):
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def render_timeline(name, tl, before=None):
    d = os.path.join(OUT, name)
    os.makedirs(d, exist_ok=True)
    cache = {}
    keys = []
    for fr in tl:
        k = (round(fr["h"], 9), round(fr["v"], 9), round(fr["blink"], 6))
        keys.append(k)
        cache.setdefault(k, None)
    print("[demo] %s: %d video frames, %d unique poses" % (name, len(tl), len(cache)))
    t_start = time.time()
    limit = int(os.environ.get("DEMO_LIMIT", "0"))     # smoke test: render only the first N
    for i, k in enumerate(list(cache)):
        if limit and i >= limit:
            print("[demo] DEMO_LIMIT reached, timeline not written")
            return
        set_pose(*k)
        if before:
            before()
        png = "u_%04d.png" % i
        t = time.time()
        render_to(os.path.join(d, png))
        cache[k] = dict(png=png, **readouts())
        done = i + 1
        eta = (time.time() - t_start) / done * (len(cache) - done)
        print("[demo] %s %d/%d  %.1fs  eta %.0fs" % (name, done, len(cache), time.time() - t, eta))
        sys.stdout.flush()
    frames = []
    for fr, k in zip(tl, keys):
        rec = dict(fr)
        rec.update(cache[k])
        frames.append(rec)
    with open(os.path.join(d, "timeline.json"), "w") as f:
        json.dump({"fps": FPS, "samples": SAMPLES, "frames": frames}, f, indent=1)


def render_closeup():
    d = os.path.join(OUT, "closeup")
    os.makedirs(d, exist_ok=True)
    pct, smp = scene.render.resolution_percentage, scene.cycles.samples
    scene.render.resolution_percentage = 200
    scene.cycles.samples = 64
    stills = {"reset": (0.0, 0.0), "look_down_right": (0.6, -0.7)}
    info = {}
    for name, (h, v) in stills.items():
        set_pose(h, v, 0.0)
        t = time.time()
        render_to(os.path.join(d, name + ".png"))
        r = readouts()
        info[name] = dict(h=h, v=v, scale=2.0, **r)
        print("[demo] closeup %s %.1fs" % (name, time.time() - t))
    scene.render.resolution_percentage, scene.cycles.samples = pct, smp
    with open(os.path.join(d, "closeup.json"), "w") as f:
        json.dump(info, f, indent=1)


def setup_xray():
    """Hide the face, add an oblique camera and one thin emissive rod per eye along its line
    of sight (from the cornea towards the fixation target, 35 cm away)."""
    keep = {"Eyeball.L", "Eyeball.R", "Cornea.L", "Cornea.R"}
    for ob in bpy.data.objects:
        if ob.type == "MESH" and ob.name not in keep:
            ob.hide_render = True
    cam_data = bpy.data.cameras.new("XrayCam")
    cam_data.lens = 40.0
    cam_data.clip_start = 0.005
    cam = bpy.data.objects.new("XrayCam", cam_data)
    scene.collection.objects.link(cam)
    look_at = M + F * 0.012
    loc = M + F * 0.095 + V_AXIS * 0.055 - H_AXIS * 0.075
    z = (loc - look_at).normalized()
    x = V_AXIS.cross(z).normalized()
    y = z.cross(x)
    m = Matrix((x, y, z)).transposed().to_4x4()
    m.translation = loc
    cam.matrix_world = m
    scene.camera = cam
    scene.render.resolution_percentage = 80
    rods = {}
    for side, colour in (("L", (0.15, 1.0, 0.45)), ("R", (1.0, 0.55, 0.1))):
        mat = bpy.data.materials.new("Ray." + side)
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = colour + (1.0,)
        em.inputs["Strength"].default_value = 1.6
        outn = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(em.outputs[0], outn.inputs[0])
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.00035, depth=1.0)
        rod = bpy.context.active_object
        rod.name = "Ray." + side
        rod.data.materials.append(mat)
        rods[side] = rod

    def place_rods():
        for side, rod in rods.items():
            p = eyes.eye_pose(side, calib)
            start = p["centre"] + p["visual"] * 0.0138
            end = Vector(eyes.target_for(eyes._state["h"], eyes._state["v"], calib))
            length = (end - start).length
            zdir = (end - start).normalized()
            q = Vector((0, 0, 1)).rotation_difference(zdir)
            rod.matrix_world = Matrix.Translation((start + end) / 2) @ q.to_matrix().to_4x4() @ \
                Matrix.Diagonal((1.0, 1.0, length, 1.0))
        bpy.context.view_layer.update()
    return place_rods


def main():
    eyes._configure_device()
    scene.render.use_persistent_data = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.use_file_extension = False
    scene.camera = bpy.data.objects[calib["camera"]]
    scene.cycles.samples = SAMPLES
    print("[demo] device %s, %d samples, segments %s" % (scene.cycles.device, SAMPLES, SEGMENTS))
    t0 = time.time()
    for seg in ALL:
        if seg not in SEGMENTS:
            continue
        if seg == "directions":
            render_timeline(seg, timeline_directions())
        elif seg == "closeup":
            render_closeup()
        elif seg == "natural":
            render_timeline(seg, timeline_natural())
        elif seg == "pursuit":
            render_timeline(seg, timeline_pursuit())
        elif seg == "xray":
            place = setup_xray()
            render_timeline(seg, timeline_pursuit(), before=place)
    eyes._state["blink"] = 0.0
    print("[demo] done in %.1f min" % ((time.time() - t0) / 60))


main()
