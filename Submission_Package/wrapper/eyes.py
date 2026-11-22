"""Deterministic gaze control wrapper for scene.blend (Samsung XR Hackathon 2026, Track 1).

Run inside Blender with scene.blend loaded:

    blender --background scene.blend --python wrapper/eyes.py -- --h 1 --v 0 --out out.png

or from plain Python (Blender is then started headless automatically for each render;
set BLENDER=<path to blender> if it is not on PATH or in the default install folder):

    python wrapper/eyes.py --look left --out out.png

or from your own script (inside Blender, or plain Python as above):

    import sys; sys.path.insert(0, "wrapper")
    import eyes
    eyes.move(-1, 0)          # look toward image-left
    path, record = eyes.render()
    eyes.reset()

Conventions (see README.md for the full statement)
-------------------------------------------------
* h, v are normalised gaze inputs clamped to [-1, +1].
* The fixation target sits on a plane 0.35 m in front of the eye midpoint M:
      T = M + 0.35*F + (H_SIGN*h*0.05)*R + (V_SIGN*v*0.05)*U
  F = face forward, U = face up, R = the direction that appears as image-right.
* +h moves the pupils toward the RIGHT of the rendered image, +v moves them UP.
  Flip H_SIGN / V_SIGN below to change that in one line.
* Each eye bone rotates about its own eyeball centre (true 3D rotation) so that its
  line of sight (visual axis, KAPPA_DEG nasal of the optical axis) passes through T.
  Both eyes fixate the same T, so they converge (vergence) and their rotations differ.
  eye_rotation_L/R in the metadata are the line-of-sight rotations.
* "L" / "R" are the avatar's anatomical left / right eyes.
"""

import json
import math
import os
import sys

try:
    import bpy
    from mathutils import Matrix, Vector
    IN_BLENDER = True
except ImportError:          # plain Python: proxy mode (see the end of this file)
    IN_BLENDER = False

# --------------------------------------------------------------------------- #
# Convention constants (single place to flip a sign)
# --------------------------------------------------------------------------- #
H_SIGN = +1.0  # +1: eyes.move(+1, 0) moves pupils toward image-right
V_SIGN = +1.0  # +1: eyes.move(0, +1) moves pupils toward image-top

# Angle kappa: a human eye fixates with its VISUAL axis (the line to the fovea), which lies
# about 5 deg to the nasal side of the eye's optical (geometric) axis. Both visual axes pass
# through the fixation target; each optical axis points kappa degrees temporally of it. This
# is what makes the two eyes look like they move together (at 35 cm the optical axes are then
# almost parallel at reset). Set KAPPA_DEG = 0.0 to aim the optical axes at the target instead.
KAPPA_DEG = 5.0

FIXATION_DISTANCE_M = 0.35  # fixation plane, metres in front of the eye midpoint
MOTION_BOUND_M = 0.05       # |h| = 1 or |v| = 1 moves the target 5 cm on that plane
CAMERA_DISTANCE_M = 0.40    # render camera, metres in front of the eye midpoint

CALIB_KEY = "xr_calib"      # JSON string stored on the scene by build_scene.py

# Which point the required "pupil_center_2D_L/R" keys report (both are always in the record):
#   "apparent"  - centre of the pupil as seen through the cornea (refraction + perspective),
#                 i.e. what an image-based pupil detector measures in the PNG
#   "geometric" - straight projection of the 3D pupil centre
# The brief defines the 2D pupil centre as the camera projection of the 3D pupil centre, so the
# required keys use "geometric": pupil_center_2D == camera_matrix @ pupil_center_3D exactly.
# Corneal refraction moves the imaged pupil by 0.4-1.3 px; that point is always available as
# pupil_center_2D_apparent_L/R (it is what a detector finds in the PNG, to ~0.1 px).
PUPIL_LABEL = "geometric"
PUPIL_LABEL_DOC = {
    "apparent": "centre of the best-fit ellipse of the pupil rim as imaged through the cornea "
                "(exact Snell refraction at the corneal sphere + perspective)",
    "geometric": "camera_matrix @ pupil_center_3D: pinhole projection of the 3D centre of the "
                 "pupil disc (no corneal refraction; the refracted image centre is "
                 "pupil_center_2D_apparent, 0.4-1.3 px away)",
}

_WRAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLE_ROOT = os.path.dirname(_WRAPPER_DIR)

_state = {"h": 0.0, "v": 0.0, "posed": False, "blink": 0.0, "pupil": 0.0, "melanin": 0.0}


# --------------------------------------------------------------------------- #
# Calibration access
# --------------------------------------------------------------------------- #
def calibration():
    """Return the calibration dict that build_scene.py stored in the scene."""
    scene = bpy.context.scene
    if CALIB_KEY not in scene:
        # Started without the scene (e.g. "blender --background --python wrapper/eyes.py"):
        # load the bundle's own scene.blend instead of failing.
        blend = os.path.join(BUNDLE_ROOT, "scene.blend")
        if os.path.exists(blend) and os.path.abspath(bpy.data.filepath or "") != os.path.abspath(blend):
            print("[eyes] scene.blend was not loaded; opening", blend)
            bpy.ops.wm.open_mainfile(filepath=blend)
            _OCCLUDER_CACHE.clear()
            _state.update({"posed": False})
            scene = bpy.context.scene
    if CALIB_KEY not in scene:
        raise RuntimeError(
            "Scene has no '%s' property. Run inside scene.blend, e.g. "
            "blender --background scene.blend --python <script>" % CALIB_KEY
        )
    return json.loads(scene[CALIB_KEY])


def _axes(calib=None):
    """(M, F, U, R) in world space. R is the axis that appears as image-right."""
    c = calib or calibration()
    cl = Vector(c["eye_center_L"])
    cr = Vector(c["eye_center_R"])
    m = (cl + cr) * 0.5
    f = Vector(c["forward"]).normalized()
    u = Vector(c["up"]).normalized()
    u = (u - f * u.dot(f)).normalized()
    r = u.cross(f).normalized()  # camera looks along -F with up U, so image-right = U x F
    return m, f, u, r


def _clamp(x):
    x = float(x)
    if math.isnan(x):
        raise ValueError("gaze input is NaN")
    return max(-1.0, min(1.0, x))


def target_for(h, v, calib=None):
    """World-space fixation target for normalised inputs (h, v)."""
    m, f, u, r = _axes(calib)
    h = _clamp(h)
    v = _clamp(v)
    return (
        m
        + FIXATION_DISTANCE_M * f
        + (H_SIGN * h * MOTION_BOUND_M) * r
        + (V_SIGN * v * MOTION_BOUND_M) * u
    )


# --------------------------------------------------------------------------- #
# Eye posing
# --------------------------------------------------------------------------- #
def _rig(calib):
    return bpy.data.objects[calib["rig"]]


def _eye_world_rest(rig, bone_name):
    return rig.matrix_world @ rig.data.bones[bone_name].matrix_local


def _nasal(side, calib=None):
    """Unit vector pointing from this eye toward the nose, in the face's image-right axis."""
    c = calib or calibration()
    _m, _f, _u, r = _axes(c)
    centre = Vector(c["eye_center_" + side])
    mid = (Vector(c["eye_center_L"]) + Vector(c["eye_center_R"])) * 0.5
    return -r if (centre - mid).dot(r) > 0 else r


def visual_axis_rest(side, calib=None):
    """The visual axis in the rest pose: KAPPA_DEG to the nasal side of the optical axis F."""
    c = calib or calibration()
    _m, f, _u, _r = _axes(c)
    k = math.radians(KAPPA_DEG)
    return (f * math.cos(k) + _nasal(side, c) * math.sin(k)).normalized()


def optical_axis_for(side, target, calib=None):
    """Optical-axis direction that puts this eye's visual axis exactly through `target`.

    The eye rotation is the torsion-free (Listing's law) shortest arc from the primary
    direction F to the optical axis. The visual axis is fixed in the eye, so we iterate:
    rotate, see where the visual axis lands, correct the optical axis by the residual.
    Converges to float precision in a few steps for kappa ~ 5 deg."""
    c = calib or calibration()
    _m, f, _u, _r = _axes(c)
    centre = Vector(c["eye_center_" + side])
    d = (target - centre).normalized()
    if KAPPA_DEG == 0.0:
        return d
    # Solved in Python doubles: mathutils is single precision, and its rotation_difference()
    # cannot resolve angles below ~3.5e-4 rad (acos of a dot product that rounds to 1), which
    # stopped this loop early and left a 0.2 mm miss at the target on the diagonal frames.
    fd, dd, vd = _d3(f), _d3(d), _d3(visual_axis_rest(side, c))
    optical = _arc_apply(vd, fd, dd)                      # first guess
    for _ in range(50):
        vis = _arc_apply(fd, optical, vd)
        if _angle3(vis, dd) < 1e-13:
            break
        optical = _norm3(_arc_apply(vis, dd, optical))
    return Vector(optical)


# Small double-precision vector helpers (plain tuples of Python floats).
def _d3(v):
    return (float(v[0]), float(v[1]), float(v[2]))


def _dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross3(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm3(a):
    n = math.sqrt(_dot3(a, a))
    return (a[0] / n, a[1] / n, a[2] / n)


def _angle3(a, b):
    """Angle between two directions, accurate for tiny angles (atan2 of |a x b| and a.b)."""
    a, b = _norm3(a), _norm3(b)
    return math.atan2(math.sqrt(_dot3(*(_cross3(a, b),) * 2)), _dot3(a, b))


def _arc_apply(a, b, x):
    """Apply the shortest-arc rotation that turns direction a onto direction b to vector x
    (Rodrigues' formula)."""
    a, b = _norm3(a), _norm3(b)
    axis = _cross3(a, b)
    s = math.sqrt(_dot3(axis, axis))
    if s < 1e-300:
        return x
    k = (axis[0] / s, axis[1] / s, axis[2] / s)
    co = _dot3(a, b)
    kx = _cross3(k, x)
    kdx = _dot3(k, x)
    return tuple(x[i] * co + kx[i] * s + k[i] * kdx * (1.0 - co) for i in range(3))


def _pose_eye(rig, bone_name, centre, forward, optical):
    """Rotate one eye bone about `centre` so its optical axis points along `optical`.

    The rotation is the shortest arc from the rest axis F to the optical axis, which
    introduces no torsion about the line of sight (Listing's law).
    """
    q = forward.rotation_difference(optical.normalized())
    rot = q.to_matrix().to_4x4()
    world_rest = _eye_world_rest(rig, bone_name)
    world_pose = Matrix.Translation(centre) @ rot @ Matrix.Translation(-centre) @ world_rest
    pb = rig.pose.bones[bone_name]
    pb.rotation_mode = "QUATERNION"
    pb.matrix = rig.matrix_world.inverted() @ world_pose
    return pb


def _apply_lids(calib, h, v):
    """The lids follow vertical gaze, as real lids do (shape keys made by build_scene.py).

    Purely a function of the input, so it stays deterministic. The lids are skin, not part of
    the eyeball: the eyeball itself only ever rotates rigidly about its centre.
    """
    lids = calib.get("lid_follow")
    if not lids:
        return
    elevation = V_SIGN * v                       # +1 = gaze fully up, -1 = fully down
    values = {lids["up_key"]: max(elevation, 0.0), lids["down_key"]: max(-elevation, 0.0)}
    # blink: closure 0..1 is spread over the intermediate keys so the lid slides over the
    # globe along an arc instead of cutting straight through it
    keys = lids.get("blink_keys", [])
    stage = _state["blink"] * len(keys)
    for i, key in enumerate(keys):
        if i == len(keys) - 1:
            values[key] = max(0.0, min(1.0, stage - i))
        else:
            values[key] = max(0.0, 1.0 - abs(stage - (i + 1)))
    for name in lids["objects"]:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.data.shape_keys is None:
            continue
        if "blink" in obj.keys():
            obj["blink"] = float(_state["blink"])   # read by the skin shader (lid texture)
        blocks = obj.data.shape_keys.key_blocks
        for key, value in values.items():
            if key in blocks:
                blocks[key].value = max(0.0, min(1.0, value))


def move(h, v, record=True):
    """Set the gaze. h = horizontal, v = vertical, both clamped to [-1, +1].

    Returns the state dict (same content as `state()`); record=False skips computing it
    (for interactive use, e.g. the slider panel in tools/gaze_panel.py).
    """
    calib = calibration()
    h = _clamp(h)
    v = _clamp(v)
    m, f, u, r = _axes(calib)
    target = target_for(h, v, calib)
    rig = _rig(calib)
    for side in ("L", "R"):
        _pose_eye(rig, calib["bone_" + side], Vector(calib["eye_center_" + side]), f,
                  optical_axis_for(side, target, calib))
    tgt = bpy.data.objects.get(calib.get("target", ""))
    if tgt is not None:
        tgt.location = target
    _apply_lids(calib, h, v)
    _state["h"], _state["v"], _state["posed"] = h, v, True
    bpy.context.view_layer.update()
    return state() if record else None


def reset():
    """Centre the gaze (h = 0, v = 0): both eyes fixate the point 35 cm straight ahead.
    Also opens the lids fully if blink() was used."""
    _state["blink"] = 0.0
    return move(0.0, 0.0)


def set_appearance(pupil_diameter_mm=None, iris_melanin=None):
    """Optional appearance controls for dataset variation (the official sequence uses the
    defaults: 3.8 mm pupil, blue-grey iris).
    pupil_diameter_mm: 2*pupil_radius_min .. 2*pupil_radius_max of the calibration (2 .. 7 mm);
    iris_melanin: 0 = blue-grey iris, 1 = dark brown. Returns the metadata record."""
    calib = calibration()
    if pupil_diameter_mm is not None:
        r = 0.0005 * float(pupil_diameter_mm)
        r0, r1 = calib["pupil_radius"], calib.get("pupil_radius_max", calib["pupil_radius"])
        rmin = calib.get("pupil_radius_min", r0)
        r = max(rmin, min(r1, r))
        _state["pupil"] = 0.0 if r1 <= r0 else (r - r0) / (r1 - r0)
    if iris_melanin is not None:
        _state["melanin"] = max(0.0, min(1.0, float(iris_melanin)))
    _apply_appearance(calib)
    if not _state["posed"]:
        return reset()
    return move(_state["h"], _state["v"])


def _apply_appearance(calib):
    for side in "LR":
        ob = bpy.data.objects.get("Eyeball." + side)
        if ob is not None and ob.data.shape_keys and "pupil_dilate" in ob.data.shape_keys.key_blocks:
            ob.data.shape_keys.key_blocks["pupil_dilate"].value = _state["pupil"]
    for mat in bpy.data.materials:              # Eye_Iris and its per-eye copies
        if mat.name.startswith("Eye_Iris") and mat.node_tree and "IrisMelanin" in mat.node_tree.nodes:
            mat.node_tree.nodes["IrisMelanin"].outputs[0].default_value = _state["melanin"]


def pupil_radius(calib=None):
    """Current pupil radius in metres (follows set_appearance)."""
    calib = calib or calibration()
    r0 = calib["pupil_radius"]
    r1 = calib.get("pupil_radius_max", r0)
    return r0 + (r1 - r0) * _state["pupil"]


def blink(amount):
    """Close the lids by `amount` in [0, 1] (0 = open, 1 = closed). For animation only; the
    gaze, the eyeball rotation and the metadata are unaffected. reset() reopens the eyes."""
    _state["blink"] = max(0.0, min(1.0, float(amount)))
    if not _state["posed"]:
        return reset() if _state["blink"] == 0.0 else move(0.0, 0.0)
    return move(_state["h"], _state["v"])


# --------------------------------------------------------------------------- #
# Ground truth: rotations, pupil projection, camera matrices
# --------------------------------------------------------------------------- #
def camera_matrices(calib=None):
    """Return (K 3x3, RT 3x4 world->camera, P 3x4) as nested lists.

    Camera frame is the computer-vision convention: x right, y down, z forward.
    Pixels: origin at the top-left corner of the image, x right, y down.
    """
    calib = calib or calibration()
    scene = bpy.context.scene
    cam = bpy.data.objects[calib["camera"]]
    cd = cam.data
    rs = scene.render
    scale = rs.resolution_percentage / 100.0
    w = rs.resolution_x * scale
    h = rs.resolution_y * scale
    aspect = rs.pixel_aspect_y / rs.pixel_aspect_x  # pixel height / pixel width

    fit = cd.sensor_fit
    if fit == "AUTO":
        fit = "HORIZONTAL" if w * rs.pixel_aspect_x >= h * rs.pixel_aspect_y else "VERTICAL"
    if fit == "HORIZONTAL":
        fx = cd.lens / cd.sensor_width * w
        fy = fx / aspect
    else:
        sensor = cd.sensor_height if cd.sensor_fit == "VERTICAL" else cd.sensor_width
        fy = cd.lens / sensor * h
        fx = fy * aspect
    view = max(w * rs.pixel_aspect_x, h * rs.pixel_aspect_y)
    cx = w * 0.5 - cd.shift_x * view / rs.pixel_aspect_x
    cy = h * 0.5 + cd.shift_y * view / rs.pixel_aspect_y
    k = Matrix(((fx, 0.0, cx), (0.0, fy, cy), (0.0, 0.0, 1.0)))

    mw = cam.matrix_world.normalized()
    r_wc = mw.to_3x3().transposed()             # world -> Blender camera
    flip = Matrix(((1, 0, 0), (0, -1, 0), (0, 0, -1)))  # Blender cam -> CV cam
    r_cv = flip @ r_wc
    t_cv = -(r_cv @ mw.translation)
    rt = [[r_cv[i][0], r_cv[i][1], r_cv[i][2], t_cv[i]] for i in range(3)]
    p = [[sum(k[i][j] * rt[j][c] for j in range(3)) for c in range(4)] for i in range(3)]
    return [list(row) for row in k], rt, p


def project(point, p=None):
    """Project a world point to pixel coordinates [x, y] with the 3x4 matrix P."""
    if p is None:
        p = camera_matrices()[2]
    x, y, z = point
    u = p[0][0] * x + p[0][1] * y + p[0][2] * z + p[0][3]
    v = p[1][0] * x + p[1][1] * y + p[1][2] * z + p[1][3]
    w = p[2][0] * x + p[2][1] * y + p[2][2] * z + p[2][3]
    return [u / w, v / w]


def eye_pose(side, calib=None):
    """Evaluated pose of one eye, read back from the scene (not from the request).

    Returns dict with: centre (world), axis (unit optical axis, world), rotation matrix
    (world-frame rotation from the rest pose), euler XYZ (rad), quaternion wxyz, and the
    world position of the pupil centre.
    """
    calib = calib or calibration()
    rig = _rig(calib)
    name = calib["bone_" + side]
    bpy.context.view_layer.update()
    world_pose = rig.matrix_world @ rig.pose.bones[name].matrix
    world_rest = _eye_world_rest(rig, name)
    rot = (world_pose @ world_rest.inverted()).to_3x3().normalized()
    centre_rest = Vector(calib["eye_center_" + side])
    delta = world_pose @ world_rest.inverted()
    centre = delta @ centre_rest
    f = Vector(calib["forward"]).normalized()
    axis = (rot @ f).normalized()
    pupil = centre + axis * calib["pupil_offset_" + side]
    visual = (rot @ visual_axis_rest(side, calib)).normalized()
    e = rot.to_euler("XYZ")
    q = rot.to_quaternion()
    # Line-of-sight rotation: the torsion-free rotation that turns straight ahead (F) onto this
    # eye's line of sight (visual axis). This is the eye's GAZE rotation, the quantity eye
    # trackers report: R_los @ F passes through the fixation target, and the L/R difference is
    # the vergence angle. With KAPPA_DEG = 0 it equals the globe rotation `matrix`.
    los_q = f.rotation_difference(visual)
    los = los_q.to_matrix()
    le = los.to_euler("XYZ")
    return {
        "centre": centre,
        "axis": axis,
        "visual": visual,
        "matrix": rot,
        "euler": [e.x, e.y, e.z],
        "quat": [q.w, q.x, q.y, q.z],
        "los_matrix": los,
        "los_euler": [le.x, le.y, le.z],
        "los_quat": [los_q.w, los_q.x, los_q.y, los_q.z],
        "pupil": pupil,
    }


# --------------------------------------------------------------------------- #
# Eye optics: what the camera actually sees (refraction through the cornea, glints)
# --------------------------------------------------------------------------- #
# The visible pupil is seen THROUGH the cornea, which magnifies it and shifts it. The model
# below is the same geometry the renderer uses: the outer eye surface is a sphere of radius
# `shell_radius` about the eye centre with a corneal cap (sphere of radius `cornea_radius`,
# centre `cornea_center_offset` along the optical axis) and everything inside it has the
# refractive index `cornea_ior` (single-surface keratometric model). The pupil is a disc of
# radius `pupil_radius` on the plane `pupil_offset` along the optical axis.

_PUPIL_RIM_SAMPLES = 64


class _Camera:
    def __init__(self, calib):
        k, rt, p = camera_matrices(calib)
        self.p = p
        r = Matrix([row[:3] for row in rt])
        t = Vector([row[3] for row in rt])
        self.r_t = r.transposed()                 # camera -> world rotation
        self.origin = -(self.r_t @ t)              # camera centre in world space
        self.k_inv = Matrix(k).inverted()

    def ray(self, x, y):
        d = self.r_t @ (self.k_inv @ Vector((x, y, 1.0)))
        return self.origin, d.normalized()


def _optics_constants(calib):
    rs = calib.get("shell_radius", calib["eye_radius"] + 0.00006)
    rc = calib.get("cornea_radius", 0.0078)
    if "cornea_center_offset" in calib:
        zc = calib["cornea_center_offset"]
    else:
        limbus = math.asin(calib["iris_radius"] / rs)
        zc = rs * math.cos(limbus) - math.sqrt(rc * rc - calib["iris_radius"] ** 2)
    return rs, rc, zc, calib.get("cornea_ior", 1.3375)


def _ray_sphere(o, d, c, r):
    oc = o - c
    b = oc.dot(d)
    disc = b * b - (oc.dot(oc) - r * r)
    if disc < 0.0:
        return None
    sq = math.sqrt(disc)
    t = -b - sq
    if t <= 0.0:
        t = -b + sq
    return o + d * t if t > 0.0 else None


def _refract(d, n, eta):
    """Snell refraction of unit direction d at a surface with unit normal n (facing the ray)."""
    cos_i = -n.dot(d)
    k = 1.0 - eta * eta * (1.0 - cos_i * cos_i)
    if k < 0.0:
        return None
    return (d * eta + n * (eta * cos_i - math.sqrt(k))).normalized()


def _eye_surface_hit(o, d, centre, axis, rs, rc, zc):
    """First intersection of a ray with the outer eye surface (corneal cap or scleral shell)
    and the outward surface normal there."""
    cc = centre + axis * zc
    hit = _ray_sphere(o, d, cc, rc)
    if hit is not None and (hit - centre).normalized().dot(axis) >= _cap_cos(rs, rc, zc):
        return hit, (hit - cc).normalized()
    hit = _ray_sphere(o, d, centre, rs)
    if hit is None:
        return None
    return hit, (hit - centre).normalized()


def _cap_cos(rs, rc, zc):
    # cosine (seen from the eye centre) of the circle where the cornea meets the shell
    z = (rs * rs - rc * rc + zc * zc) / (2.0 * zc)
    return z / rs


def _apparent_point(cam, target, centre, axis, rs, rc, zc, ior, guess):
    """Pixel at which the refracted camera ray passes through the 3D point `target` (which lies
    inside the eye on the plane through `target` perpendicular to the optical axis).
    Newton iteration on the pixel coordinates; converges to ~1e-9 m in a few steps."""
    eta = 1.0 / ior
    e1 = axis.orthogonal().normalized()
    e2 = axis.cross(e1).normalized()

    def trace(x, y):
        o, d = cam.ray(x, y)
        hit = _eye_surface_hit(o, d, centre, axis, rs, rc, zc)
        if hit is None:
            return None
        s, n = hit
        t = _refract(d, n, eta)
        if t is None:
            return None
        lam = (target - s).dot(axis) / t.dot(axis)
        q = s + t * lam - target
        return q.dot(e1), q.dot(e2)

    x, y = guess
    for _ in range(12):
        f = trace(x, y)
        if f is None:
            return None
        if abs(f[0]) + abs(f[1]) < 1e-10:
            break
        h = 0.02
        fx, fy = trace(x + h, y), trace(x, y + h)
        if fx is None or fy is None:
            return None
        a11, a21 = (fx[0] - f[0]) / h, (fx[1] - f[1]) / h
        a12, a22 = (fy[0] - f[0]) / h, (fy[1] - f[1]) / h
        det = a11 * a22 - a12 * a21
        if abs(det) < 1e-30:
            return None
        x -= (a22 * f[0] - a12 * f[1]) / det
        y -= (-a21 * f[0] + a11 * f[1]) / det
    return [x, y]


def _fit_ellipse(points):
    """Least-squares conic fit -> (centre [x, y], semi-axes [major, minor], angle in degrees of
    the major axis from +x toward +y, i.e. clockwise on screen)."""
    import numpy as np
    pts = np.asarray(points, dtype=np.float64)
    m = pts.mean(axis=0)
    s = pts.std() or 1.0
    x, y = ((pts - m) / s).T
    design = np.column_stack([x * x, x * y, y * y, x, y, np.ones_like(x)])
    a, b, c, d, e, f = np.linalg.svd(design)[2][-1]
    den = 4 * a * c - b * b
    x0 = (b * e - 2 * c * d) / den
    y0 = (b * d - 2 * a * e) / den
    f0 = a * x0 * x0 + b * x0 * y0 + c * y0 * y0 + d * x0 + e * y0 + f
    w, vec = np.linalg.eigh(np.array([[a, b / 2], [b / 2, c]]))
    axes = np.sqrt(np.abs(f0 / w)) * s
    major = int(np.argmax(axes))
    ang = math.degrees(math.atan2(vec[1, major], vec[0, major])) % 180.0
    return [float(x0 * s + m[0]), float(y0 * s + m[1])], [float(axes.max()), float(axes.min())], ang


def apparent_pupil(side, pose=None, calib=None, cam=None):
    """The pupil as the camera sees it through the cornea: rim points in pixels and the
    best-fit ellipse (whose centre is what an image-based pupil detector measures)."""
    calib = calib or calibration()
    pose = pose or eye_pose(side, calib)
    cam = cam or _Camera(calib)
    rs, rc, zc, ior = _optics_constants(calib)
    centre, axis = pose["centre"], pose["axis"]
    p0 = centre + axis * calib["pupil_offset_" + side]
    e1 = axis.orthogonal().normalized()
    e2 = axis.cross(e1).normalized()
    rim = []
    guess = project(p0, cam.p)
    for k in range(_PUPIL_RIM_SAMPLES):
        phi = 2.0 * math.pi * k / _PUPIL_RIM_SAMPLES
        b = p0 + (e1 * math.cos(phi) + e2 * math.sin(phi)) * pupil_radius(calib)
        g = project(b, cam.p)
        px = _apparent_point(cam, b, centre, axis, rs, rc, zc, ior, g)
        if px is not None:
            rim.append(px)
    if len(rim) < 12:
        return None
    c, axes, ang = _fit_ellipse(rim)
    return {"center": c, "semi_axes": axes, "angle_deg": ang, "rim": rim}


def corneal_reflections(side, pose=None, calib=None, cam=None):
    """Glints: the image position of each light's specular reflection on the eye surface.
    Solved with the law of reflection (surface normal bisects the directions to the camera and
    to the light centre). `visible` = not hidden by the lids."""
    calib = calib or calibration()
    pose = pose or eye_pose(side, calib)
    cam = cam or _Camera(calib)
    rs, rc, zc, _ior = _optics_constants(calib)
    centre, axis = pose["centre"], pose["axis"]
    cos_cap = _cap_cos(rs, rc, zc)
    out = []
    for name in calib.get("lights", []):
        light = bpy.data.objects.get(name)
        if light is None:
            continue
        lp = light.matrix_world.translation.copy()
        result = None
        for surf, sc, sr in (("cornea", centre + axis * zc, rc), ("sclera", centre, rs)):
            n = ((cam.origin - sc).normalized() + (lp - sc).normalized()).normalized()
            for _ in range(30):
                g = sc + n * sr
                n_new = ((cam.origin - g).normalized() + (lp - g).normalized()).normalized()
                if (n_new - n).length < 1e-12:
                    break
                n = n_new
            g = sc + n * sr
            on_cap = (g - centre).normalized().dot(axis) >= cos_cap
            if (surf == "cornea") == on_cap and n.dot((cam.origin - g).normalized()) > 0.0:
                result = (surf, g)
                break
        if result is None:
            continue
        surf, g = result
        sc, sr = (centre + axis * zc, rc) if surf == "cornea" else (centre, rs)
        vis_xy, frac = _visible_glint_centroid(cam, sc, sr, light)
        out.append({"light": name,
                    "xy": vis_xy if vis_xy is not None else project(g, cam.p),
                    "xy_light_centre": project(g, cam.p),
                    "world": list(g), "surface": surf,
                    "visible": _visible_from_camera(cam.origin, g),
                    "light_unoccluded_fraction": frac,
                    "relative_radiance": _radiance(light) / max(_radiance(bpy.data.objects[n])
                                                                for n in calib["lights"] if n in bpy.data.objects)})
    return out


def _radiance(light):
    """Radiance of an area light (W / m^2 / sr), which sets how bright its glint is."""
    d = light.data
    area = d.size * (d.size_y if d.shape in ("RECTANGLE", "ELLIPSE") else d.size)
    return d.energy / (math.pi * max(area, 1e-9))


def _reflection_point(cam_origin, sc, sr, lp):
    """Point on the sphere (sc, sr) where light from lp reflects into the camera."""
    n = ((cam_origin - sc).normalized() + (lp - sc).normalized()).normalized()
    for _ in range(40):
        g = sc + n * sr
        n_new = ((cam_origin - g).normalized() + (lp - g).normalized()).normalized()
        if (n_new - n).length < 1e-13:
            break
        n = n_new
    return sc + n * sr


def _visible_glint_centroid(cam, sc, sr, light, n=17):
    """Centroid of the glint as it appears in the image when part of the light is hidden.

    The light's rectangle is divided into (n-1)^2 cells; each cell corner is reflected on the
    sphere into the image. A cell counts if its centre is visible from its reflection point.
    The centroid is the image-area-weighted mean of the visible cells' image quads (uniform
    radiance -> uniform image brightness), i.e. what a centroiding glint detector returns.
    Returns (xy or None, visible fraction of the light)."""
    d = light.data
    sy = d.size_y if d.shape in ("RECTANGLE", "ELLIPSE") else d.size
    mw = light.matrix_world

    def lpos(i, j):
        return mw @ Vector(((i / (n - 1) - 0.5) * d.size, (j / (n - 1) - 0.5) * sy, 0.0))

    img = {}
    for i in range(n):
        for j in range(n):
            img[i, j] = project(_reflection_point(cam.origin, sc, sr, lpos(i, j)), cam.p)
    ax = ay = area_sum = 0.0
    seen = 0
    for i in range(n - 1):
        for j in range(n - 1):
            lc = (lpos(i, j) + lpos(i + 1, j + 1)) * 0.5
            g = _reflection_point(cam.origin, sc, sr, lc)
            if _blocked(g, lc):
                continue
            seen += 1
            q = [img[i, j], img[i + 1, j], img[i + 1, j + 1], img[i, j + 1]]
            a = 0.0
            cx = cy = 0.0
            for k in range(4):
                x0, y0 = q[k]
                x1, y1 = q[(k + 1) % 4]
                cr = x0 * y1 - x1 * y0
                a += cr
                cx += (x0 + x1) * cr
                cy += (y0 + y1) * cr
            if abs(a) < 1e-12:
                continue
            ax += cx / 3.0
            ay += cy / 3.0
            area_sum += a
    frac = seen / float((n - 1) ** 2)
    if seen == 0 or abs(area_sum) < 1e-12:
        return None, frac
    return [ax / area_sum, ay / area_sum], frac


def _light_unoccluded_fraction(point, light, n=5):
    """Fraction of an area light's surface visible from `point` (5x5 samples). A partly hidden
    light makes a partly hidden glint whose centroid no longer marks the light centre."""
    d = light.data
    sy = d.size_y if d.shape in ("RECTANGLE", "ELLIPSE") else d.size
    seen = 0
    for i in range(n):
        for j in range(n):
            lp = light.matrix_world @ Vector(((i / (n - 1) - 0.5) * d.size, (j / (n - 1) - 0.5) * sy, 0.0))
            seen += 0 if _blocked(point, lp) else 1
    return seen / float(n * n)


_OCCLUDER_CACHE = {}


def _occluders(lashes=False):
    """BVH tree of the geometry that can hide a glint or a light: the head skin, brows and the
    inner-corner tissue, plus (lashes=True) the lash strands. Built once per pose because the
    lids and lashes move with the gaze. Semi-transparent lash *cards* are never included."""
    from mathutils.bvhtree import BVHTree
    key = (_state["h"], _state["v"], _state["blink"], lashes)
    if key in _OCCLUDER_CACHE:
        return _OCCLUDER_CACHE[key]
    if len(_OCCLUDER_CACHE) > 8:
        _OCCLUDER_CACHE.clear()
    dg = bpy.context.evaluated_depsgraph_get()
    verts, polys = [], []
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.hide_render:
            continue
        name = obj.name.lower()
        lash_strands = name.endswith("eyelashes_strands")
        strands = lash_strands or name == "browstrands"
        # brow hairs are opaque geometry that really cuts slices out of a light seen from the
        # cornea; lash strands are excluded from the cornea's reflection in the render, so they
        # only count when asked for
        if not (name == "human" or "eyebrow" in name or name.startswith(("caruncle", "plica"))
                or name == "browstrands" or (lashes and lash_strands)):
            continue
        if "eyebrow" in name and not strands and obj.hide_render:
            continue
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        mw = ev.matrix_world
        base = len(verts)
        verts.extend(mw @ v.co for v in me.vertices)
        polys.extend([base + i for i in p.vertices] for p in me.polygons)
        ev.to_mesh_clear()
    bvh = BVHTree.FromPolygons(verts, polys, all_triangles=False, epsilon=0.0)
    _OCCLUDER_CACHE[key] = bvh
    return bvh


def _blocked(a, b, lashes=False):
    """True if the segment a -> b passes through the occluding head geometry."""
    d = b - a
    dist = d.length
    d.normalize()
    hit = _occluders(lashes).ray_cast(a + d * 2e-5, d, dist - 4e-5)
    return hit[0] is not None


def _visible_from_camera(origin, point):
    return not _blocked(origin, point)



# --------------------------------------------------------------------------- #
# Extra eye-region labels: iris ellipse, eyelid landmarks, pupil visibility
# --------------------------------------------------------------------------- #
EYELID_LANDMARKS = 16          # points per lid margin


def apparent_iris(side, pose=None, calib=None, cam=None, samples=48):
    """The limbus (iris outline) as imaged through the cornea, as a best-fit ellipse."""
    calib = calib or calibration()
    pose = pose or eye_pose(side, calib)
    cam = cam or _Camera(calib)
    rs, rc, zc, ior = _optics_constants(calib)
    centre, axis = pose["centre"], pose["axis"]
    r_eye, r_iris = calib["eye_radius"], calib["iris_radius"]
    z_l = calib.get("limbus_offset", math.sqrt(r_eye * r_eye - r_iris * r_iris))
    p0 = centre + axis * z_l
    e1 = axis.orthogonal().normalized()
    e2 = axis.cross(e1).normalized()
    rim = []
    for k in range(samples):
        phi = 2.0 * math.pi * k / samples
        b = p0 + (e1 * math.cos(phi) + e2 * math.sin(phi)) * (r_iris * 0.999)
        px = _apparent_point(cam, b, centre, axis, rs, rc, zc, ior, project(b, cam.p))
        if px is not None:
            rim.append(px)
    if len(rim) < 12:
        return None
    c, axes, ang = _fit_ellipse(rim)
    return {"center": c, "semi_axes": axes, "angle_deg": ang}


def pupil_visible_fraction(side, app, pose=None, calib=None, cam=None):
    """Share of the imaged pupil rim that the lids do not cover."""
    if not app:
        return None
    calib = calib or calibration()
    pose = pose or eye_pose(side, calib)
    cam = cam or _Camera(calib)
    rs, rc, zc, _ior = _optics_constants(calib)
    seen = 0
    for px in app["rim"]:
        o, d = cam.ray(*px)
        hit = _eye_surface_hit(o, d, pose["centre"], pose["axis"], rs, rc, zc)
        if hit is not None and not _blocked(o, hit[0]):
            seen += 1
    return seen / float(len(app["rim"]))


def eyelid_landmarks(side, calib=None, cam=None):
    """Visible upper and lower lid edges in the image: EYELID_LANDMARKS points each, from the
    inner (nasal) to the outer (temporal) corner, plus the two corners.

    For each column across the eye opening the edge is found by bisection on the eye surface:
    the point where the camera's line of sight first becomes blocked by the lid. Its projection
    is exactly where skin meets eye in the image, for the current (gaze-dependent) lid pose."""
    calib = calib or calibration()
    ap = calib.get("aperture_" + side)
    if not ap:
        return None
    cam = cam or _Camera(calib)
    _m, f, u, r = _axes(calib)
    c = Vector(calib["eye_center_" + side])
    rs = calib.get("shell_radius", calib["eye_radius"])
    mid = Vector(calib["eye_midpoint"]) if "eye_midpoint" in calib else _m
    nasal_is_min = (c - mid).dot(r) > 0          # eye on image-right: its nose side is -x

    def surface(x, z):
        y2 = rs * rs - x * x - z * z
        if y2 <= 0:
            return None
        return c + r * x + u * z + f * math.sqrt(y2)

    def is_open(x, z):
        p = surface(x, z)
        return p is not None and not _blocked(cam.origin, p)

    xs, lo, hi = ap["x"], ap["lo"], ap["hi"]
    n_cols = EYELID_LANDMARKS
    upper, lower = [], []
    for i in range(n_cols):
        t = (i + 0.5) / n_cols
        x = xs[0] + (xs[-1] - xs[0]) * t
        j = min(int(t * (len(xs) - 1)), len(xs) - 2)
        w = t * (len(xs) - 1) - j
        z_mid = 0.5 * ((lo[j] + hi[j]) * (1 - w) + (lo[j + 1] + hi[j + 1]) * w)
        if not is_open(x, z_mid):
            continue
        for sign, store in ((1.0, upper), (-1.0, lower)):
            a, b = z_mid, z_mid + sign * 0.012
            if is_open(x, b):
                continue
            for _ in range(22):              # 0.012 / 2^22 ~ 3 nm
                m = 0.5 * (a + b)
                if is_open(x, m):
                    a = m
                else:
                    b = m
            store.append(project(surface(x, 0.5 * (a + b)), cam.p))
    if nasal_is_min:
        order = lambda pts: pts
    else:
        order = lambda pts: list(reversed(pts))
    upper, lower = order(upper), order(lower)
    corners = None
    if upper and lower:
        corners = {"inner": [0.5 * (upper[0][0] + lower[0][0]), 0.5 * (upper[0][1] + lower[0][1])],
                   "outer": [0.5 * (upper[-1][0] + lower[-1][0]), 0.5 * (upper[-1][1] + lower[-1][1])]}
    return {"upper": upper, "lower": lower, "approx_corners": corners}


def state():
    """Full ground-truth record for the current gaze (no rendering)."""
    if not _state["posed"]:
        return reset()                      # first use in this session: start from centre
    calib = calibration()
    _m, f, _u, _r = _axes(calib)
    k, rt, p = camera_matrices(calib)
    left = eye_pose("L", calib)
    right = eye_pose("R", calib)
    cam = _Camera(calib)
    app = {s: apparent_pupil(s, pose, calib, cam) for s, pose in (("L", left), ("R", right))}
    glints = {s: corneal_reflections(s, pose, calib, cam) for s, pose in (("L", left), ("R", right))}
    geo = {"L": project(left["pupil"], p), "R": project(right["pupil"], p)}
    label = {s: (app[s]["center"] if (PUPIL_LABEL == "apparent" and app[s]) else geo[s]) for s in "LR"}
    h, v = _state["h"], _state["v"]
    return {
        "input": {"h": h, "v": v},
        "eye_rotation_L": left["los_euler"],
        "eye_rotation_R": right["los_euler"],
        "pupil_center_2D_L": label["L"],
        "pupil_center_2D_R": label["R"],
        "camera_matrix": p,
        "camera_intrinsics_K": k,
        "camera_extrinsics_world_to_cam": rt,
        "eye_rotation_quat_L": left["los_quat"],
        "eye_rotation_quat_R": right["los_quat"],
        "eye_rotation_matrix_L": [list(row) for row in left["los_matrix"]],
        "eye_rotation_matrix_R": [list(row) for row in right["los_matrix"]],
        "vergence_angle_deg": math.degrees(left["visual"].angle(right["visual"])),
        "globe_rotation_L": left["euler"],
        "globe_rotation_R": right["euler"],
        "globe_rotation_quat_L": left["quat"],
        "globe_rotation_quat_R": right["quat"],
        "globe_rotation_matrix_L": [list(row) for row in left["matrix"]],
        "globe_rotation_matrix_R": [list(row) for row in right["matrix"]],
        "pupil_center_2D_geometric_L": geo["L"],
        "pupil_center_2D_geometric_R": geo["R"],
        "pupil_center_2D_apparent_L": app["L"]["center"] if app["L"] else None,
        "pupil_center_2D_apparent_R": app["R"]["center"] if app["R"] else None,
        "pupil_ellipse_2D_L": {k: app["L"][k] for k in ("center", "semi_axes", "angle_deg")} if app["L"] else None,
        "pupil_ellipse_2D_R": {k: app["R"][k] for k in ("center", "semi_axes", "angle_deg")} if app["R"] else None,
        "corneal_reflections_2D_L": glints["L"],
        "corneal_reflections_2D_R": glints["R"],
        "iris_ellipse_2D_L": apparent_iris("L", left, calib, cam),
        "iris_ellipse_2D_R": apparent_iris("R", right, calib, cam),
        "pupil_visible_fraction_L": pupil_visible_fraction("L", app["L"], left, calib, cam),
        "pupil_visible_fraction_R": pupil_visible_fraction("R", app["R"], right, calib, cam),
        "eyelid_landmarks_2D_L": eyelid_landmarks("L", calib, cam),
        "eyelid_landmarks_2D_R": eyelid_landmarks("R", calib, cam),
        "pupil_center_3D_L": list(left["pupil"]),
        "pupil_center_3D_R": list(right["pupil"]),
        "eye_center_world_L": list(left["centre"]),
        "eye_center_world_R": list(right["centre"]),
        "gaze_direction_world_L": list(left["visual"]),
        "gaze_direction_world_R": list(right["visual"]),
        "optical_axis_world_L": list(left["axis"]),
        "optical_axis_world_R": list(right["axis"]),
        "fixation_target_world": list(target_for(h, v, calib)),
        "eyelid_closure": _state["blink"],
        "pupil_diameter_mm": 2000.0 * pupil_radius(calib),
        "iris_melanin": _state["melanin"],
        "conventions": {
            "rotation": "eye_rotation_L/R (and _quat, _matrix): rotation of the eye's line of sight "
                        "from straight ahead (forward_world), world frame, XYZ Euler, radians, "
                        "torsion-free (Listing's law). eye_rotation_matrix @ forward_world = "
                        "gaze_direction_world, which passes through fixation_target_world",
            "globe_rotation": "globe_rotation_L/R: rigid rotation of the eyeball mesh about its centre "
                              "from the rest pose (what the renderer applies); differs from "
                              "eye_rotation by angle kappa",
            "forward_world": list(f),
            "gaze_direction": "visual axis (line to the fovea); both pass through fixation_target_world",
            "optical_axis": "geometric axis of the globe; kappa deg temporal of the visual axis",
            "angle_kappa_deg": KAPPA_DEG,
            "pixels": "origin top-left corner, x right, y down",
            "pupil_center_2D": PUPIL_LABEL_DOC[PUPIL_LABEL],
            "eyes": "L/R = avatar's anatomical left/right",
            "H_SIGN": H_SIGN,
            "V_SIGN": V_SIGN,
        },
    }


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _configure_device():
    """Pick the Cycles device. XR_DEVICE=CPU|GPU overrides; default uses GPU when present."""
    scene = bpy.context.scene
    if scene.render.engine != "CYCLES":
        return
    want = os.environ.get("XR_DEVICE", "AUTO").upper()
    if want == "CPU":
        scene.cycles.device = "CPU"
        return
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for kind in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
            try:
                prefs.compute_device_type = kind
            except TypeError:
                continue
            prefs.get_devices()
            gpus = [d for d in prefs.devices if d.type == kind]
            if gpus:
                for d in prefs.devices:
                    d.use = d.type == kind
                scene.cycles.device = "GPU"
                return
    except Exception:
        pass
    scene.cycles.device = "CPU"


_PNG_KEEP = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"sRGB", b"cHRM", b"pHYs"}


def _strip_png_metadata(path):
    """Remove Blender's text/EXIF chunks (render date, render time, the .blend's file path) so
    that identical renders give identical files and no local paths leak into the output."""
    import struct
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return
    out = [data[:8]]
    pos = 8
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos:pos + 12 + length]
        if kind in _PNG_KEEP:
            out.append(chunk)
        pos += 12 + length
    with open(path, "wb") as f:
        f.write(b"".join(out))


def render(path=None):
    """Render the current gaze to a PNG.

    Returns (absolute_path, record) where record is the frame's metadata (see `state()`).
    Render settings (resolution, samples, seed, denoiser, lighting, camera) come from
    scene.blend and are never changed here, so identical inputs give identical images.
    """
    scene = bpy.context.scene
    calib = calibration()
    if path is None:
        name = "gaze_h%+.3f_v%+.3f.png" % (_state["h"], _state["v"])
        path = os.path.join(BUNDLE_ROOT, "output", name)
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    scene.camera = bpy.data.objects[calib["camera"]]
    scene.render.image_settings.file_format = "PNG"
    scene.render.use_file_extension = False
    scene.render.filepath = path
    if not _state["posed"]:
        reset()
    _configure_device()
    bpy.context.view_layer.update()
    if os.path.exists(path):
        os.remove(path)
    try:
        bpy.ops.render.render(write_still=True)
    except RuntimeError:
        pass
    if not os.path.exists(path) and scene.render.engine == "CYCLES" and scene.cycles.device != "CPU":
        # GPU failed on this machine (driver / memory): fall back to the CPU once.
        print("[eyes] GPU render failed, retrying on the CPU")
        scene.cycles.device = "CPU"
        os.environ["XR_DEVICE"] = "CPU"
        bpy.ops.render.render(write_still=True)
    if not os.path.exists(path):
        raise RuntimeError("render did not produce %s" % path)
    _strip_png_metadata(path)

    record = state()
    record["image"] = path
    return path, record


# --------------------------------------------------------------------------- #
# Realistic gaze shifts: saccades with human "main sequence" dynamics
# --------------------------------------------------------------------------- #
# A saccade's duration grows linearly with its amplitude (D ~ 2.2 ms/deg * A + 21 ms) and its
# position follows a smooth bell-shaped velocity profile; the minimum-jerk profile
# s(t) = 10 t^3 - 15 t^4 + 6 t^5 is the standard model. Peak velocity then comes out at
# 1.875 * A / D, which for 1-20 deg saccades lands in the measured 100-500 deg/s range.
SACCADE_MS_PER_DEG = 2.2
SACCADE_MS_OFFSET = 21.0


def _gaze_angle_deg(h0, v0, h1, v1, calib=None):
    """Angle between the cyclopean gaze directions (from the eye midpoint) for two inputs."""
    m, _f, _u, _r = _axes(calib)
    a = (target_for(h0, v0, calib) - m).normalized()
    b = (target_for(h1, v1, calib) - m).normalized()
    return math.degrees(a.angle(b)) if (a - b).length > 1e-12 else 0.0


def saccade_profile(t):
    """Minimum-jerk position fraction for normalised time t in [0, 1]."""
    t = max(0.0, min(1.0, t))
    return t * t * t * (10.0 + t * (-15.0 + 6.0 * t))


def saccade(h, v, fps=60.0, calib=None):
    """Trajectory of a realistic gaze shift from the current gaze to (h, v).

    Returns a list of {"t_ms", "h", "v"} samples at `fps`, starting at the current gaze (t=0)
    and ending exactly at the (clamped) target. Pure function: it does not move the eyes, so a
    caller can render each sample with move(). Duration follows the main sequence."""
    calib = calib or calibration()
    h0, v0 = _state["h"], _state["v"]
    h1, v1 = _clamp(h), _clamp(v)
    amp = _gaze_angle_deg(h0, v0, h1, v1, calib)
    dur = SACCADE_MS_OFFSET + SACCADE_MS_PER_DEG * amp if amp > 0 else 0.0
    n = max(1, int(math.ceil(dur * fps / 1000.0)))
    out = []
    for i in range(n + 1):
        t_ms = min(dur, i * 1000.0 / fps)
        s = saccade_profile(t_ms / dur) if dur > 0 else 1.0
        out.append({"t_ms": t_ms, "h": h0 + (h1 - h0) * s, "v": v0 + (v1 - v0) * s})
    out[-1].update({"h": h1, "v": v1})
    return out


def saccade_stats(h0, v0, h1, v1, calib=None):
    """Amplitude (deg), duration (ms) and peak angular velocity (deg/s) of a saccade."""
    amp = _gaze_angle_deg(h0, v0, h1, v1, calib)
    dur = SACCADE_MS_OFFSET + SACCADE_MS_PER_DEG * amp
    return {"amplitude_deg": amp, "duration_ms": dur, "peak_velocity_deg_s": 1.875 * amp / (dur / 1000.0)}


# --------------------------------------------------------------------------- #
# Named directions ("look left") and CLI
# --------------------------------------------------------------------------- #
DIRECTIONS = {
    "reset": (0.0, 0.0),
    "center": (0.0, 0.0),
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
    "up": (0.0, 1.0),
    "down": (0.0, -1.0),
}


def look(direction):
    """eyes.look("left") etc. Directions are in image space (see H_SIGN)."""
    h, v = DIRECTIONS[direction.strip().lower()]
    return move(h, v)


FAST_SAMPLES = 16


def set_samples(n):
    """Override the Cycles sample count for this session (e.g. FAST_SAMPLES for a quick check).
    The metadata does not depend on it; the official renders use the scene's 128."""
    if IN_BLENDER:
        bpy.context.scene.cycles.samples = int(n)
    _state["samples"] = int(n)


def _main(argv):
    import argparse

    ap = argparse.ArgumentParser(description="Set the gaze and render one frame.")
    ap.add_argument("--h", type=float, default=0.0)
    ap.add_argument("--v", type=float, default=0.0)
    ap.add_argument("--look", choices=sorted(DIRECTIONS), default=None)
    ap.add_argument("--out", default=None, help="output PNG path")
    ap.add_argument("--no-render", action="store_true", help="only print the metadata")
    ap.add_argument("--blink", type=float, default=0.0, help="eyelid closure 0..1 (animation only)")
    ap.add_argument("--json", default=None, help="also write the metadata record to this file")
    ap.add_argument("--pupil-mm", type=float, default=None, help="pupil diameter in mm (dataset variation)")
    ap.add_argument("--melanin", type=float, default=None, help="iris colour 0 = blue-grey .. 1 = brown")
    ap.add_argument("--fast", action="store_true", help="quick check: %d samples instead of the "
                    "scene's 128 (same image size and metadata, noisier glints)" % FAST_SAMPLES)
    ap.add_argument("--samples", type=int, default=None, help="override the Cycles sample count")
    args = ap.parse_args(argv)
    if args.samples or args.fast:
        set_samples(args.samples or FAST_SAMPLES)
    if args.look:
        look(args.look)
    else:
        move(args.h, args.v)
    if args.blink:
        blink(args.blink)
    if args.pupil_mm is not None or args.melanin is not None:
        set_appearance(args.pupil_mm, args.melanin)
    if args.no_render:
        rec = state()
    else:
        _, rec = render(args.out)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(rec, f, indent=2)
    print(json.dumps(rec, indent=2))


# --------------------------------------------------------------------------- #
# Proxy mode: the same API from plain Python (no bpy). Each call that needs the scene runs
# Blender headless on scene.blend with this very file, so results are identical.
# --------------------------------------------------------------------------- #
def find_blender():
    import glob
    import shutil
    cand = [os.environ.get("BLENDER"), shutil.which("blender")]
    cand += sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender*\blender.exe"), reverse=True)
    cand += ["/Applications/Blender.app/Contents/MacOS/Blender", "/usr/bin/blender",
             "/usr/local/bin/blender", "/snap/bin/blender", "/opt/blender/blender"]
    for c in cand:
        if c and os.path.exists(c):
            return c
    raise RuntimeError("Blender not found. Set the BLENDER environment variable to the blender executable.")


def _proxy_call(extra):
    import subprocess
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        cmd = [find_blender(), "--background", os.path.join(BUNDLE_ROOT, "scene.blend"),
               "--python-exit-code", "1", "--python", os.path.abspath(__file__), "--",
               "--h", repr(_state["h"]), "--v", repr(_state["v"]), "--blink", repr(_state["blink"]),
               "--pupil-mm", repr(_state.get("pupil_mm", 3.8)), "--melanin", repr(_state["melanin"]),
               "--json", tmp] + extra
        if _state.get("samples") and "--no-render" not in extra:
            cmd += ["--samples", str(_state["samples"])]
        proc = subprocess.run(cmd, cwd=BUNDLE_ROOT, capture_output=True, text=True, errors="replace")
        if proc.returncode != 0:
            raise RuntimeError("Blender failed:\n" + (proc.stdout + proc.stderr)[-3000:])
        with open(tmp) as f:
            return json.load(f)
    finally:
        os.remove(tmp)


if not IN_BLENDER:
    def move(h, v):  # noqa: F811
        """Set the gaze (proxy mode). Returns the full metadata record for the new pose."""
        _state["h"], _state["v"], _state["posed"] = _clamp(h), _clamp(v), True
        return state()

    def reset():  # noqa: F811
        _state["blink"] = 0.0
        return move(0.0, 0.0)

    def blink(amount):  # noqa: F811
        _state["blink"] = max(0.0, min(1.0, float(amount)))
        return state()

    def set_appearance(pupil_diameter_mm=None, iris_melanin=None):  # noqa: F811
        if pupil_diameter_mm is not None:
            _state["pupil_mm"] = float(pupil_diameter_mm)
        if iris_melanin is not None:
            _state["melanin"] = max(0.0, min(1.0, float(iris_melanin)))
        return state()

    def state():  # noqa: F811
        return _proxy_call(["--no-render"])

    def render(path=None):  # noqa: F811
        if path is None:
            path = os.path.join(BUNDLE_ROOT, "output", "gaze_h%+.3f_v%+.3f.png" % (_state["h"], _state["v"]))
        path = os.path.abspath(path)
        rec = _proxy_call(["--out", path])
        return path, rec

    def look(direction):  # noqa: F811
        h, v = DIRECTIONS[direction.strip().lower()]
        return move(h, v)


if __name__ == "__main__":
    if "--" in sys.argv:
        _main(sys.argv[sys.argv.index("--") + 1:])
    elif IN_BLENDER:
        _main([])                   # blender ... --python eyes.py   -> renders the reset pose
    else:
        _main(sys.argv[1:])         # python eyes.py --look left ...
