"""Bake the skin UV textures for the MakeHuman base mesh.

    blender --background --python tools/bake_skin.py

Input : textures/skin_albedo_base_makehuman.png  (CC0 MakeHuman skin, 2048 px)
Output: textures/skin_albedo.png      4096 px sRGB   tone, redness, under-eye, freckles, mottle
        textures/skin_roughness.png   2048 px linear oilier T-zone, drier cheeks
        textures/skin_normal.png      4096 px tangent-space: crow's feet, under-eye and
                                      forehead lines, meso-scale unevenness

How: the detail is authored procedurally in 3D on the actual mesh (so it lands in the right
place on the face regardless of the UV layout), driven by per-vertex region masks computed
from the model's own landmarks (eye centres, nose tip), then baked with Cycles into the
model's UV layout. The resulting PNGs fit the standard MakeHuman UV map and can be wrapped
onto any MakeHuman/MPFB base mesh.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import build_scene as B  # noqa: E402

TEX = os.path.join(ROOT, "textures")
SKIN_TINT = (0.86, 0.74, 0.65)     # multiplies the (very pale) MakeHuman albedo -> light tan
LID_FIX_RGB = (0.68, 1.0, 1.05)    # linear-RGB multiplier at full lid mask (pulls the red lid back toward the face)
EYE_REDNESS = 0.20                 # redness around the eyes (lids are thin and translucent: keep it low)
ALBEDO_SIZE = int(os.environ.get("XR_BAKE_SIZE", "4096"))

# Natural imperfection and the eye area (face coordinates in metres from the eye midpoint,
# +x = image-right, +z = up)
UNDER_EYE_DARK = 0.18              # under-eye shadow tint (was 0.30: read as tired)
PIGMENT_PATCHES = 0.45             # strength of the soft, uneven pigmentation patches
CAPILLARIES = 0.35                 # faint broken capillaries on the nose wings
BEAUTY_MARK = (0.037, -0.032, 0.0007)   # x, z, radius: small mole on the cheek, image-right
BLEMISH = (-0.022, 0.036, 0.0013)       # x, z, radius: faint healed spot above the image-left brow
LID_CREASE = (0.0150, 0.0098, 0.06)     # upper-lid crease: ellipse semi-axes about the eye centre
                                        # (x, z) and line width (fraction of the radius)
LID_CREASE_SHADE = 0.80            # how much the fold line darkens the skin
LID_CREASE_DEPTH = 0.00020         # depth of the fold in the normal map (metres)


def crease_mask(N, ax, fz, half_ipd, shift=0.0, widen=1.0):
    """0..1 band along the upper-eyelid crease of each eye: an arc of an ellipse about the eye
    centre, only above the eye, fading out toward the corners. shift moves the band toward
    (negative) or away from the eye, in fractions of the radius; widen scales its width."""
    rx, rz, width = LID_CREASE
    width *= widen
    ex = N.math("SUBTRACT", ax, half_ipd + 0.0005)
    r = N.math("SQRT", N.math("ADD", N.math("POWER", N.math("DIVIDE", ex, rx), 2.0),
                              N.math("POWER", N.math("DIVIDE", fz, rz), 2.0)))
    line = N.math("EXPONENT", N.math("MULTIPLY", N.math("POWER", N.math("DIVIDE", N.math("SUBTRACT", r, 1.0 + shift), width), 2.0), -1.0))
    above = N.map_range(fz, 0.003, 0.007)                 # only the upper arc
    ends = N.map_range(N.math("ABSOLUTE", ex), 0.0135, 0.0095)   # fade toward the corners
    return N.math("MULTIPLY", line, N.math("MULTIPLY", above, ends))


def g2(dx, dz, sx, sz):
    return math.exp(-((dx / sx) ** 2 + (dz / sz) ** 2))


def smooth(e0, e1, x):
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


# --------------------------------------------------------------------------- #
# Per-vertex region masks
# --------------------------------------------------------------------------- #
def paint_masks(human, centres, forward, up):
    right = up.cross(forward).normalized()
    mid = (centres["L"] + centres["R"]) * 0.5
    half_ipd = (centres["L"] - centres["R"]).length * 0.5
    mw = human.matrix_world
    body = human.vertex_groups["body"].index

    def face_xyz(p):
        q = p - mid
        return q.dot(right), q.dot(up), q.dot(forward)

    # nose tip: most forward point on the midline below the eyes
    nose = None
    for v in human.data.vertices:
        if not any(g.group == body for g in v.groups):
            continue
        x, z, y = face_xyz(mw @ v.co)
        if abs(x) < 0.012 and -0.065 < z < -0.02 and (nose is None or y > nose[2]):
            nose = (x, z, y)
    B.log("nose tip (face coords, mm):", tuple(round(c * 1e3, 1) for c in nose))

    a = human.data.color_attributes.new("xr_maskA", "FLOAT_COLOR", "POINT")
    b = human.data.color_attributes.new("xr_maskB", "FLOAT_COLOR", "POINT")
    lidm = human.data.color_attributes.new("xr_maskC", "FLOAT_COLOR", "POINT")
    for v in human.data.vertices:
        x, z, y = face_xyz(mw @ v.co)
        ax = abs(x)
        face = smooth(-0.075, -0.035, y) * smooth(-0.15, -0.12, z)
        ex = ax - half_ipd                      # lateral offset from the nearer eye centre (+ = outward)
        # redness: lid margins / orbit, nose tip and wings, cheeks
        red = max(EYE_REDNESS * g2(ex, z, 0.019, 0.011),
                  0.90 * g2(x, z - nose[1], 0.017, 0.014),
                  0.45 * g2(ax - (half_ipd + 0.012), z + 0.045, 0.028, 0.022))
        under = g2(ex + 0.001, z + 0.0125, 0.013, 0.0055)
        freckle = max(g2(x, z + 0.028, 0.060, 0.022), 0.6 * g2(x, z - nose[1] - 0.012, 0.02, 0.03))
        oil = max(g2(x, z - 0.055, 0.045, 0.030),          # forehead
                  g2(x, z - 0.5 * nose[1], 0.011, 0.040),  # nose ridge
                  0.8 * g2(x, z + 0.105, 0.022, 0.016))    # chin
        crow = g2(ex - 0.021, z + 0.001, 0.010, 0.011) * smooth(0.012, 0.017, ex)
        forehead = g2(x, z - 0.050, 0.050, 0.020)
        a.data[v.index].color = (red * face, under * face, freckle * face, 1.0)
        b.data[v.index].color = (oil * face, crow * face, forehead * face, 1.0)
        # the MakeHuman source texture paints the upper lid strongly red (R/G ~1.42 vs 1.12 on
        # the forehead); this mask lets the bake pull it back toward the rest of the face
        lid_fix = g2(ex + 0.001, z - 0.0045, 0.0165, 0.0055) * face
        lidm.data[v.index].color = (lid_fix, 0.0, 0.0, 1.0)
    return mid, right, half_ipd, nose


# --------------------------------------------------------------------------- #
# Node helpers
# --------------------------------------------------------------------------- #
class Nodes:
    def __init__(self, nt):
        self.nt = nt

    def new(self, kind, **props):
        n = self.nt.nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def link(self, a, b):
        self.nt.links.new(a, b)

    def _feed(self, sock, value):
        if hasattr(value, "is_output") or hasattr(value, "links"):
            self.link(value, sock)
        else:
            sock.default_value = value

    def math(self, op, a, b=None, c=None, clamp=False):
        n = self.new("ShaderNodeMath", operation=op, use_clamp=clamp)
        self._feed(n.inputs[0], a)
        if b is not None:
            self._feed(n.inputs[1], b)
        if c is not None:
            self._feed(n.inputs[2], c)
        return n.outputs[0]

    def vmath(self, op, a, b=None):
        n = self.new("ShaderNodeVectorMath", operation=op)
        self._feed(n.inputs[0], a)
        if b is not None:
            self._feed(n.inputs[1], b)
        return n.outputs["Value"] if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else n.outputs[0]

    def mix_color(self, fac, a, b, blend="MIX"):
        n = self.new("ShaderNodeMix", data_type="RGBA", blend_type=blend, clamp_factor=True)
        self._feed(n.inputs[0], fac)
        self._feed(n.inputs[6], a)
        self._feed(n.inputs[7], b)
        return n.outputs[2]

    def tint(self, color, rgb, fac):
        """Mix `color` toward color*rgb by `fac`."""
        mul = self.mix_color(1.0, color, tuple(rgb) + (1.0,), "MULTIPLY")
        return self.mix_color(fac, color, mul)

    def map_range(self, value, a, b, c=0.0, d=1.0, smooth=True):
        n = self.new("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP" if smooth else "LINEAR")
        self._feed(n.inputs["Value"], value)
        n.inputs["From Min"].default_value = a
        n.inputs["From Max"].default_value = b
        n.inputs["To Min"].default_value = c
        n.inputs["To Max"].default_value = d
        return n.outputs["Result"]

    def noise(self, vector, scale, detail=2.0, rough=0.5):
        n = self.new("ShaderNodeTexNoise")
        self.link(vector, n.inputs["Vector"])
        n.inputs["Scale"].default_value = scale
        n.inputs["Detail"].default_value = detail
        n.inputs["Roughness"].default_value = rough
        return n.outputs["Fac"]

    def voronoi(self, vector, scale):
        n = self.new("ShaderNodeTexVoronoi", feature="F1")
        self.link(vector, n.inputs["Vector"])
        n.inputs["Scale"].default_value = scale
        n.inputs["Randomness"].default_value = 1.0
        return n.outputs["Distance"], n.outputs["Color"]

    def separate(self, color):
        n = self.new("ShaderNodeSeparateColor")
        self.link(color, n.inputs[0])
        return n.outputs[0], n.outputs[1], n.outputs[2]


def build_authoring_material(human, mid, right, up, forward, half_ipd):
    mat = bpy.data.materials.new("SkinAuthoring")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    N = Nodes(nt)
    out = N.new("ShaderNodeOutputMaterial")

    tc = N.new("ShaderNodeTexCoord")
    P = tc.outputs["Object"]
    base = N.new("ShaderNodeTexImage")
    base.image = B.image("skin_albedo_base_makehuman.png")
    base.interpolation = "Cubic"
    red, under, freckle = N.separate(N.new("ShaderNodeAttribute", attribute_name="xr_maskA").outputs["Color"])
    oil, crow, forehead = N.separate(N.new("ShaderNodeAttribute", attribute_name="xr_maskB").outputs["Color"])
    lid_fix, _u1, _u2 = N.separate(N.new("ShaderNodeAttribute", attribute_name="xr_maskC").outputs["Color"])

    # face coordinates (metres): fx = image-right, fz = up, relative to the eye midpoint
    rel = N.vmath("SUBTRACT", P, tuple(mid))
    fx = N.vmath("DOT_PRODUCT", rel, tuple(right))
    fz = N.vmath("DOT_PRODUCT", rel, tuple(up))
    ax = N.math("ABSOLUTE", fx)

    # ---------------- albedo ----------------
    c = N.mix_color(1.0, base.outputs["Color"], SKIN_TINT + (1.0,), "MULTIPLY")
    c = N.tint(c, LID_FIX_RGB, lid_fix)
    blotch = N.map_range(N.noise(P, 38.0, 3.0), 0.42, 0.68)
    c = N.tint(c, (1.07, 0.93, 0.91), N.math("MULTIPLY", blotch, 0.55))
    c = N.tint(c, (1.06, 0.72, 0.70), N.math("MULTIPLY", red, 0.62))
    c = N.tint(c, (0.86, 0.78, 0.82), N.math("MULTIPLY", under, UNDER_EYE_DARK))
    # uneven pigmentation: soft, slightly browner patches a few cm across (real skin is never
    # one even tone)
    patches = N.map_range(N.noise(P, 14.0, 3.0, 0.55), 0.46, 0.74)
    c = N.tint(c, (0.94, 0.88, 0.84), N.math("MULTIPLY", patches, PIGMENT_PATCHES))
    mottle = N.map_range(N.noise(P, 520.0, 5.0, 0.6), 0.3, 0.7, 0.93, 1.06, smooth=False)
    c = N.mix_color(1.0, c, N.new("ShaderNodeCombineColor").outputs[0], "MULTIPLY") if False else c
    comb = N.new("ShaderNodeCombineColor")
    for i in range(3):
        N.link(mottle, comb.inputs[i])
    c = N.mix_color(1.0, c, comb.outputs[0], "MULTIPLY")
    # freckles: small soft spots in Voronoi cells, densest over nose and cheeks. A slow noise
    # thins them out in places so they gather in irregular clusters instead of an even sprinkle;
    # the third, coarse scale adds a few larger, fainter sun spots.
    cluster = N.map_range(N.noise(P, 22.0, 2.0), 0.30, 0.62)
    # (strengths ~25 % above the earlier 0.75 / 0.85 so the freckles still read against the
    # stronger pores; capped by the clamp below)
    for scale, lo, hi, share, strength in ((430.0, 0.12, 0.36, 0.60, 0.95), (190.0, 0.07, 0.20, 0.82, 1.0),
                                           (85.0, 0.05, 0.16, 0.90, 0.55)):
        dist, col = N.voronoi(P, scale)
        r1, r2, _ = N.separate(col)
        spot = N.map_range(dist, lo, hi, 1.0, 0.0)
        chosen = N.math("GREATER_THAN", r1, share)
        amount = N.math("MULTIPLY", N.math("MULTIPLY", spot, chosen), N.math("MULTIPLY", freckle, N.math("MULTIPLY_ADD", r2, 0.6, 0.4)))
        amount = N.math("MULTIPLY", amount, N.math("MULTIPLY_ADD", cluster, 0.40, 0.60))
        c = N.tint(c, (0.66, 0.47, 0.36), N.math("MULTIPLY", amount, strength, clamp=True))
    # faint broken capillaries on the nose wings and inner cheeks: thin wandering red threads
    thread = N.noise(P, 160.0, 3.0, 0.6)
    vein = N.map_range(N.math("ABSOLUTE", N.math("SUBTRACT", thread, 0.5)), 0.0, 0.018, 1.0, 0.0)
    near_nose = N.math("MULTIPLY", red, N.map_range(ax, 0.040, 0.015))   # nose wings, not the lids
    c = N.tint(c, (1.0, 0.70, 0.68), N.math("MULTIPLY", N.math("MULTIPLY", vein, near_nose), CAPILLARIES, clamp=True))
    # placed details (face coordinates, metres from the eye midpoint; +x = image-right)
    def spot_at(x0, z0, radius):
        d2 = N.math("ADD", N.math("POWER", N.math("SUBTRACT", fx, x0), 2.0), N.math("POWER", N.math("SUBTRACT", fz, z0), 2.0))
        return N.math("EXPONENT", N.math("MULTIPLY", d2, -1.0 / (radius * radius)))
    # a small beauty mark on the cheek below the image-right eye
    c = N.tint(c, (0.50, 0.36, 0.30), N.math("MULTIPLY", N.map_range(spot_at(*BEAUTY_MARK), 0.35, 0.75), 0.85))
    # one faint healed blemish above the image-left brow
    c = N.tint(c, (1.04, 0.80, 0.78), N.math("MULTIPLY", spot_at(*BLEMISH), 0.45))
    # upper-eyelid crease: a soft shadowed fold above each eye gives the eye area depth
    if os.environ.get("XR_CREASE_DEBUG"):        # paint the crease bright green to check its placement
        c = N.mix_color(N.math("MULTIPLY", crease_mask(N, ax, fz, half_ipd), 1.0, clamp=True), c, (0.0, 1.0, 0.0, 1.0))
    else:
        c = N.tint(c, (0.74, 0.64, 0.62), N.math("MULTIPLY", crease_mask(N, ax, fz, half_ipd), LID_CREASE_SHADE))
        # the fold overhangs the lid: a broader soft shadow just below the crease line
        c = N.tint(c, (0.86, 0.78, 0.76), N.math("MULTIPLY", crease_mask(N, ax, fz, half_ipd, shift=-0.06, widen=2.5), 0.45))
    albedo = c

    # ---------------- roughness ----------------
    rough = N.math("MULTIPLY_ADD", oil, -0.17, 0.52)
    rough = N.math("ADD", rough, N.map_range(N.noise(P, 140.0, 3.0), 0.3, 0.7, -0.05, 0.05, smooth=False))
    rough = N.math("ADD", rough, N.math("MULTIPLY", under, -0.06), clamp=True)

    # ---------------- height (metres) for the normal map ----------------
    warp = N.noise(P, 90.0, 2.0)
    # crow's feet: grooves radiating from the outer corner of each eye
    cdx = N.math("SUBTRACT", ax, half_ipd + 0.0150)
    cdz = N.math("ADD", fz, 0.0010)
    theta = N.math("ARCTAN2", cdz, cdx)
    lines = N.math("SINE", N.math("ADD", N.math("MULTIPLY", theta, 17.0), N.math("MULTIPLY", warp, 6.0)))
    # the lines radiate from the corner but must not visibly converge on a point: fade them
    # in only 3-7 mm out from the centre of the fan
    rc = N.math("SQRT", N.math("ADD", N.math("POWER", cdx, 2.0), N.math("POWER", cdz, 2.0)))
    fan = N.map_range(rc, 0.003, 0.007)
    h_crow = N.math("MULTIPLY", N.math("MULTIPLY", N.map_range(lines, 0.62, 1.0), fan),
                    N.math("MULTIPLY", crow, -0.00009))
    # under-eye creases: arcs concentric with the eye
    edx = N.math("SUBTRACT", ax, half_ipd)
    rr = N.math("SQRT", N.math("ADD", N.math("POWER", edx, 2.0), N.math("POWER", N.math("ADD", fz, -0.004), 2.0)))
    arcs = N.math("SINE", N.math("ADD", N.math("MULTIPLY", rr, 2 * math.pi / 0.0021), N.math("MULTIPLY", warp, 9.0)))
    h_under = N.math("MULTIPLY", N.map_range(arcs, 0.60, 1.0), N.math("MULTIPLY", under, -0.000025))
    # faint horizontal forehead lines
    fl = N.math("SINE", N.math("ADD", N.math("MULTIPLY", fz, 2 * math.pi / 0.0075), N.math("MULTIPLY", warp, 7.0)))
    h_fore = N.math("MULTIPLY", N.map_range(fl, 0.70, 1.0), N.math("MULTIPLY", forehead, -0.00007))
    # meso-scale unevenness everywhere
    h_meso = N.math("MULTIPLY", N.noise(P, 330.0, 4.0, 0.55), 0.00010)
    height = N.math("ADD", N.math("ADD", h_crow, h_under), N.math("ADD", h_fore, h_meso))
    # upper-eyelid fold and the slightly raised healed blemish
    height = N.math("ADD", height, N.math("MULTIPLY", crease_mask(N, ax, fz, half_ipd), -LID_CREASE_DEPTH))
    bx, bz, brad = BLEMISH
    bd2 = N.math("ADD", N.math("POWER", N.math("SUBTRACT", fx, bx), 2.0), N.math("POWER", N.math("SUBTRACT", fz, bz), 2.0))
    height = N.math("ADD", height, N.math("MULTIPLY", N.math("EXPONENT", N.math("MULTIPLY", bd2, -1.0 / (brad * brad))), 0.00006))

    bump = N.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 1.0
    bump.inputs["Distance"].default_value = 1.0
    N.link(height, bump.inputs["Height"])
    bsdf = N.new("ShaderNodeBsdfDiffuse")
    N.link(bump.outputs["Normal"], bsdf.inputs["Normal"])
    emit = N.new("ShaderNodeEmission")

    human.data.materials.clear()
    human.data.materials.append(mat)
    return mat, {"albedo": albedo, "rough": rough, "bsdf": bsdf, "emit": emit, "out": out}


def sanitize_normal_map(img):
    """Replace invalid texels (the procedural height has a few singular points where the
    baked normal comes out flipped or non-unit) with the flat normal."""
    import numpy as np
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    v = px[..., :3] * 2.0 - 1.0
    length = np.linalg.norm(v, axis=2)
    bad = (v[..., 2] < 0.5) | (np.abs(length - 1.0) > 0.15) | ~np.isfinite(length)
    # also clear the 1-texel ring around each bad texel (filtered samples would bleed)
    grown = bad.copy()
    grown[1:, :] |= bad[:-1, :]
    grown[:-1, :] |= bad[1:, :]
    grown[:, 1:] |= bad[:, :-1]
    grown[:, :-1] |= bad[:, 1:]
    px[grown, 0] = 0.5
    px[grown, 1] = 0.5
    px[grown, 2] = 1.0
    img.pixels.foreach_set(px.ravel())
    B.log("normal map: reset %d invalid texels" % int(grown.sum()))


def bake(human, mat, sockets, kind, name, size, colorspace):
    nt = mat.node_tree
    img = bpy.data.images.new("bake_" + kind, size, size, alpha=False)
    img.colorspace_settings.name = colorspace
    node = nt.nodes.new("ShaderNodeTexImage")
    node.image = img
    for n in nt.nodes:
        n.select = False
    node.select = True
    nt.nodes.active = node

    for l in list(sockets["out"].inputs["Surface"].links):
        nt.links.remove(l)
    if kind == "normal":
        nt.links.new(sockets["bsdf"].outputs[0], sockets["out"].inputs["Surface"])
        bake_type = "NORMAL"
    else:
        for l in list(sockets["emit"].inputs["Color"].links):
            nt.links.remove(l)
        nt.links.new(sockets[kind], sockets["emit"].inputs["Color"])
        nt.links.new(sockets["emit"].outputs[0], sockets["out"].inputs["Surface"])
        bake_type = "EMIT"

    bpy.ops.object.select_all(action="DESELECT")
    human.select_set(True)
    bpy.context.view_layer.objects.active = human
    if bake_type == "NORMAL":
        bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", margin=24, use_clear=True)
    else:
        bpy.ops.object.bake(type="EMIT", margin=24, use_clear=True)
    if kind == "normal":
        sanitize_normal_map(img)
    path = os.path.join(TEX, name)
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    B.log("baked", path)
    nt.nodes.remove(node)
    bpy.data.images.remove(img)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    human, rig, meas, forward, up, centres, _apertures = B.build_human()
    for m in list(human.modifiers):
        if m.type in ("ARMATURE", "SUBSURF"):
            human.modifiers.remove(m)
    mid, right, half_ipd, _nose = paint_masks(human, centres, forward, up)
    mat, sockets = build_authoring_material(human, mid, right, up, forward, half_ipd)

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 4
    scene.cycles.use_denoising = False
    scene.render.bake.use_selected_to_active = False

    bake(human, mat, sockets, "albedo", "skin_albedo.png", ALBEDO_SIZE, "sRGB")
    bake(human, mat, sockets, "rough", "skin_roughness.png", ALBEDO_SIZE // 2, "Non-Color")
    bake(human, mat, sockets, "normal", "skin_normal.png", ALBEDO_SIZE, "Non-Color")


if __name__ == "__main__":
    main()
