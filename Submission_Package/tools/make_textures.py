"""Generate the eye UV textures (iris, sclera) deterministically.

Run with the project venv (numpy + opencv):

    .venv/Scripts/python tools/make_textures.py

Outputs (all in textures/):
    iris_color.png     1024x1024  disc layout: centre = pupil centre, edge = limbus
    sclera_color.png   2048x2048  azimuthal-equidistant layout: centre = front pole of the
                                  eye, distance from centre = angle from the optical axis
                                  (image radius 1.0 = 180 deg). +u = image-right of the face.

The skin maps are produced by tools/make_skin_textures.py.
"""
import math
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "textures")

# Geometry shared with build_scene.py (metres)
EYE_RADIUS = 0.0125
IRIS_RADIUS = 0.0059
PUPIL_RADIUS = 0.0019
LIMBUS_ANGLE = math.asin(IRIS_RADIUS / EYE_RADIUS)  # angle from the optical axis


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def polar_noise(rng, n_theta, n_r, sig_theta, sig_r):
    """Noise on a (theta, r) grid, blurred anisotropically; wraps around in theta."""
    a = rng.random((n_theta, n_r)).astype(np.float32)
    a = np.concatenate([a, a, a], axis=0)
    a = cv2.GaussianBlur(a, (0, 0), sigmaX=sig_r, sigmaY=sig_theta)
    a = a[n_theta:2 * n_theta]
    a = (a - a.min()) / (a.max() - a.min() + 1e-9)
    return a


def sample_polar(grid, theta, r):
    """Sample grid[theta, r] for arrays theta in [0, 2pi), r in [0, 1]."""
    n_theta, n_r = grid.shape
    padded = np.concatenate([grid, grid[:1]], axis=0)
    mx = (np.clip(r, 0, 1) * (n_r - 1)).astype(np.float32)
    my = (theta / (2 * np.pi) * n_theta).astype(np.float32)
    return cv2.remap(padded, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


IRIS_PALETTES = {
    # (collarette, stroma, outer ring) in linear RGB
    "blue": ((0.42, 0.25, 0.09), (0.17, 0.27, 0.30), (0.06, 0.11, 0.16)),
    "brown": ((0.20, 0.10, 0.035), (0.13, 0.065, 0.025), (0.045, 0.025, 0.012)),
}


def make_iris(size=1024, seed=7, palette="blue"):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    cx = cy = (size - 1) / 2.0
    dx = (x - cx) / (size / 2.0)
    dy = (cy - y) / (size / 2.0)
    r = np.sqrt(dx * dx + dy * dy)
    theta = np.mod(np.arctan2(dy, dx), 2 * np.pi)

    p = PUPIL_RADIUS / IRIS_RADIUS
    t = np.clip((r - p) / (1.0 - p), 0.0, 1.0)  # 0 at the pupil edge, 1 at the limbus

    fine = sample_polar(polar_noise(rng, 2048, 256, 1.2, 40.0), theta, t)
    medium = sample_polar(polar_noise(rng, 1024, 256, 4.0, 60.0), theta, t)
    coarse = sample_polar(polar_noise(rng, 512, 128, 10.0, 12.0), theta, t)
    crypts = sample_polar(polar_noise(rng, 720, 128, 5.0, 5.0), theta, t)
    fibres = 0.55 * fine + 0.30 * medium + 0.15 * coarse

    # Colour zones: warm collarette near the pupil, cool grey-green stroma, dark limbal ring.
    inner, mid, outer = (np.array(c, np.float32) for c in IRIS_PALETTES[palette])
    # the collarette is a jagged zig-zag, not a circle: low-frequency wander + angular teeth
    wobble = 0.09 * (coarse - 0.5) + 0.035 * np.sin(theta * 23.0 + 7.0 * medium) + 0.02 * np.sin(theta * 57.0 + 3.0 * fine)
    w_inner = 1.0 - smoothstep(0.10 + wobble, 0.34 + wobble, t)
    w_outer = smoothstep(0.55, 0.95, t)
    col = mid[None, None, :] * (1 - w_inner - w_outer * (1 - w_inner))[..., None]
    col += inner[None, None, :] * w_inner[..., None]
    col += outer[None, None, :] * (w_outer * (1 - w_inner))[..., None]

    brightness = 0.35 + 1.3 * fibres ** 1.4
    brightness *= 1.0 - 0.35 * smoothstep(0.62, 0.80, crypts) * (1 - smoothstep(0.6, 0.9, t))
    col *= brightness[..., None]

    # Collarette ridge (slightly brighter zig-zag ring), dark limbal ring, pupillary ruff.
    ridge = np.exp(-((t - (0.30 + wobble)) / 0.045) ** 2)
    col *= (1.0 + 0.25 * ridge)[..., None]
    col *= (1.0 - 0.88 * smoothstep(0.66, 1.0, t))[..., None]
    col *= (0.55 + 0.45 * smoothstep(0.0, 0.07, t))[..., None]

    # Pupil (geometry also has a black pupil material; keep the texture consistent).
    pupil = 1.0 - smoothstep(p - 0.012, p + 0.004, r)
    col *= (1.0 - pupil)[..., None]
    col[r > 1.0] = np.array([0.05, 0.07, 0.08], np.float32)

    img = np.clip(col, 0, 1) ** (1 / 2.2)
    return (img[..., ::-1] * 255 + 0.5).astype(np.uint8)


def make_sclera(size=2048, seed=11):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    c = (size - 1) / 2.0
    dx = (x - c) / (size / 2.0)
    dy = (c - y) / (size / 2.0)
    r = np.sqrt(dx * dx + dy * dy)          # 1.0 == 180 degrees from the optical axis
    ang = r * np.pi

    base = np.array([0.63, 0.595, 0.56], np.float32)     # off-white (never pure white)
    far = np.array([0.66, 0.44, 0.39], np.float32)       # pinker towards the back/corners
    yellow = np.array([0.68, 0.60, 0.42], np.float32)
    w_far = smoothstep(math.radians(30), math.radians(72), ang)
    horiz = np.abs(dx) / (r + 1e-6)                        # 1 along the corner directions
    w_far = np.clip(w_far * (0.35 + 0.65 * horiz ** 1.5), 0, 1)   # conjunctiva pinker at the corners
    blotch = cv2.GaussianBlur(rng.random((size, size)).astype(np.float32), (0, 0), 60)
    blotch = (blotch - blotch.min()) / (blotch.max() - blotch.min())
    col = base[None, None] * (1 - w_far)[..., None] + far[None, None] * w_far[..., None]
    col = col * (1 - 0.18 * blotch[..., None]) + yellow[None, None] * (0.18 * blotch[..., None])

    # Veins: branching random walks from the periphery towards the limbus.
    veins = np.zeros((size, size), np.float32)
    fine_veins = np.zeros((size, size), np.float32)

    def to_px(a, phi):
        rr = a / np.pi * (size / 2.0)
        return c + rr * math.cos(phi), c - rr * math.sin(phi)

    def walk(a, phi, width, depth):
        pts = [to_px(a, phi)]
        a_stop = LIMBUS_ANGLE + math.radians(rng.uniform(6.0, 30.0))
        steps = 0
        while a > a_stop and steps < 400:
            a -= math.radians(rng.uniform(0.35, 0.9))
            phi += math.radians(rng.normal(0.0, 1.6)) / max(math.sin(a), 0.2)
            pts.append(to_px(a, phi))
            steps += 1
            if depth < 3 and rng.random() < 0.045:
                walk(a, phi + math.radians(rng.choice([-1, 1]) * rng.uniform(8, 25)),
                     max(1, width - 1), depth + 1)
        arr = np.array(pts, np.float32).reshape(-1, 1, 2)
        target = veins if width >= 2 else fine_veins
        cv2.polylines(target, [np.round(arr * 16).astype(np.int32)], False, 1.0,
                      thickness=width, lineType=cv2.LINE_AA, shift=4)

    for _ in range(46):
        # concentrate vein origins toward the nasal / temporal corners (phi near 0 or pi)
        side = rng.choice([0.0, math.pi])
        phi0 = side + rng.normal(0.0, math.radians(38))
        walk(math.radians(rng.uniform(75, 100)), phi0, int(rng.choice([1, 1, 1, 2])), 0)

    veins = cv2.GaussianBlur(veins, (0, 0), 1.3)
    fine_veins = cv2.GaussianBlur(fine_veins, (0, 0), 0.9)
    vein_mask = np.clip(0.45 * veins + 0.38 * fine_veins, 0, 1)
    vein_mask *= smoothstep(LIMBUS_ANGLE + math.radians(1.5), LIMBUS_ANGLE + math.radians(12), ang)
    vein_col = np.array([0.52, 0.13, 0.11], np.float32)
    col = col * (1 - vein_mask[..., None]) + vein_col[None, None] * vein_mask[..., None]
    halo = cv2.GaussianBlur(vein_mask, (0, 0), 7)
    col = col * (1 - 0.12 * halo[..., None]) + np.array([0.75, 0.50, 0.46], np.float32) * (0.12 * halo[..., None])

    # Limbal ring: soft blue-grey darkening where the sclera meets the cornea.
    limbus = 1.0 - smoothstep(LIMBUS_ANGLE - math.radians(1.0), LIMBUS_ANGLE + math.radians(5.5), ang)
    limb_col = np.array([0.16, 0.19, 0.22], np.float32)
    col = col * (1 - 0.85 * limbus[..., None]) + limb_col[None, None] * (0.85 * limbus[..., None])

    img = np.clip(col, 0, 1) ** (1 / 2.2)
    return (img[..., ::-1] * 255 + 0.5).astype(np.uint8)


def main():
    os.makedirs(OUT, exist_ok=True)
    cv2.imwrite(os.path.join(OUT, "iris_color.png"), make_iris())
    cv2.imwrite(os.path.join(OUT, "iris_color_brown.png"), make_iris(palette="brown"))
    cv2.imwrite(os.path.join(OUT, "sclera_color.png"), make_sclera())
    print("wrote", os.path.join(OUT, "iris_color.png"))
    print("wrote", os.path.join(OUT, "sclera_color.png"))


if __name__ == "__main__":
    sys.exit(main())
