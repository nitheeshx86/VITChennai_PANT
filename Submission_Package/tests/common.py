"""Shared helpers for the Blender-side tests (only bpy + numpy needed)."""
import os
import sys
import traceback

import bpy
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper"))
import eyes  # noqa: E402

DEBUG = os.path.join(ROOT, "debug")
TEST_SAMPLES = int(os.environ.get("XR_TEST_SAMPLES", "24"))

DIRECTIONS = {"left": (-1.0, 0.0), "right": (1.0, 0.0), "up": (0.0, 1.0), "down": (0.0, -1.0)}


class Checker:
    def __init__(self, name):
        self.name = name
        self.failures = 0
        self.count = 0
        print("\n===== %s =====" % name)

    def check(self, ok, label, detail=""):
        ok = bool(ok)
        self.count += 1
        if not ok:
            self.failures += 1
        print("  [%s] %s %s" % ("PASS" if ok else "FAIL", label, detail))
        sys.stdout.flush()
        return ok

    def finish(self):
        status = "PASSED" if self.failures == 0 else "FAILED"
        print("RESULT %s: %s (%d checks, %d failed)" % (self.name, status, self.count, self.failures))
        sys.stdout.flush()
        sys.exit(0 if self.failures == 0 else 1)


def run_test(name, fn):
    c = Checker(name)
    try:
        fn(c)
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        c.check(False, "test raised an exception")
    c.finish()


def fast_render_settings(samples=None):
    bpy.context.scene.cycles.samples = samples or TEST_SAMPLES


def load_png(path):
    """Return float32 array (H, W, 3), top row first, values in [0, 1] (sRGB encoded)."""
    img = bpy.data.images.load(path, check_existing=False)
    img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[::-1, :, :3].copy()


def save_png(arr, path):
    """Save float array (H, W, 3) in [0, 1] as an 8-bit PNG (values written unchanged)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    h, w = arr.shape[:2]
    img = bpy.data.images.new("dbg", w, h, alpha=False)
    img.colorspace_settings.name = "Non-Color"
    rgba = np.ones((h, w, 4), np.float32)
    rgba[..., :3] = arr[::-1]
    img.pixels.foreach_set(rgba.ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def detect_pupil(img, predicted, radius_px):
    """Find the dark pupil blob near `predicted` (x, y in pixels, origin top-left).

    Returns (cx, cy, n_pixels) in continuous pixel coordinates, or None.
    Independent of the projection maths: threshold + connected component. The centre is
    the middle of the blob's extents, which a catch-light inside the pupil cannot bias.
    """
    h, w = img.shape[:2]
    px, py = predicted
    x0, x1 = max(0, int(px - radius_px)), min(w, int(px + radius_px) + 1)
    y0, y1 = max(0, int(py - radius_px)), min(h, int(py + radius_px) + 1)
    lum = img[y0:y1, x0:x1].max(axis=2)
    thr = min(0.16, float(np.percentile(lum, 2)) + 0.08)
    mask = lum < thr
    if not mask.any():
        return None
    ys, xs = np.nonzero(mask)
    cy0, cx0 = (y1 - y0) / 2.0, (x1 - x0) / 2.0
    seed = int(np.argmin((ys - cy0) ** 2 + (xs - cx0) ** 2))
    comp = np.zeros_like(mask)
    stack = [(int(ys[seed]), int(xs[seed]))]
    comp[stack[0]] = True
    while stack:
        y, x = stack.pop()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yy, xx = y + dy, x + dx
            if 0 <= yy < mask.shape[0] and 0 <= xx < mask.shape[1] and mask[yy, xx] and not comp[yy, xx]:
                comp[yy, xx] = True
                stack.append((yy, xx))
    # Boundary pixels of the blob, then a least-squares circle with outlier rejection: a
    # catch-light or lash that bites into the pupil leaves boundary points INSIDE the true
    # circle, and those are dropped before the final fit.
    pad = np.pad(comp, 1)
    interior = pad[:-2, 1:-1] & pad[2:, 1:-1] & pad[1:-1, :-2] & pad[1:-1, 2:]
    by, bx = np.nonzero(comp & ~interior)
    bx = bx.astype(np.float64)
    by = by.astype(np.float64)
    keep = np.ones(len(bx), bool)
    cx, cy, rad = float(bx.mean()), float(by.mean()), 0.0
    for _ in range(8):
        if keep.sum() < 8:
            break
        a = np.column_stack([2 * bx[keep], 2 * by[keep], np.ones(int(keep.sum()))])
        sol, *_ = np.linalg.lstsq(a, bx[keep] ** 2 + by[keep] ** 2, rcond=None)
        cx, cy = float(sol[0]), float(sol[1])
        rad = float(np.sqrt(max(sol[2] + cx * cx + cy * cy, 0.0)))
        res = np.hypot(bx - cx, by - cy) - rad
        new_keep = res > -max(0.75, 0.04 * rad)
        if (new_keep == keep).all():
            break
        keep = new_keep
    # +0.5 converts pixel index -> pixel centre in continuous image coordinates
    return cx + x0 + 0.5, cy + y0 + 0.5, int(comp.sum())


def detect_glint(img, predicted, radius_px):
    """Specular glint near `predicted`, measured from the pixels only.

    Seed: the brightest pixel within 6 px of the prediction. Region: the 8-connected set of
    pixels at >= 80 % of that peak (the white sclera next to a glint is darker than the glint
    and separated from it by the iris rim, so it does not join). Centre: brightness-weighted
    centroid above the threshold. Returns (x, y, n) or None."""
    h, w = img.shape[:2]
    px, py = predicted
    x0, x1 = max(0, int(px - radius_px)), min(w, int(px + radius_px) + 1)
    y0, y1 = max(0, int(py - radius_px)), min(h, int(py + radius_px) + 1)
    lum = img[y0:y1, x0:x1].mean(axis=2)
    yy, xx = np.mgrid[0:y1 - y0, 0:x1 - x0]
    near = (xx + x0 + 0.5 - px) ** 2 + (yy + y0 + 0.5 - py) ** 2 <= 36.0
    if not near.any():
        return None
    k = int(np.argmax(np.where(near, lum, -1.0)))
    sy, sx = divmod(k, lum.shape[1])
    peak = float(lum[sy, sx])
    if peak < 0.75:
        return None
    level = 0.8 * peak
    mask = lum >= level
    comp = np.zeros_like(mask)
    comp[sy, sx] = True
    stack = [(sy, sx)]
    while stack:
        y, x = stack.pop()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                yy2, xx2 = y + dy, x + dx
                if 0 <= yy2 < mask.shape[0] and 0 <= xx2 < mask.shape[1] and mask[yy2, xx2] and not comp[yy2, xx2]:
                    comp[yy2, xx2] = True
                    stack.append((yy2, xx2))
    ys, xs = np.nonzero(comp)
    wts = lum[ys, xs] - level + 1e-6
    return float((xs * wts).sum() / wts.sum()) + x0 + 0.5, float((ys * wts).sum() / wts.sum()) + y0 + 0.5, int(comp.sum())


def draw_cross(img, x, y, color, size=7):
    h, w = img.shape[:2]
    xi, yi = int(round(x - 0.5)), int(round(y - 0.5))
    for d in range(-size, size + 1):
        if 0 <= yi < h and 0 <= xi + d < w:
            img[yi, xi + d] = color
        if 0 <= yi + d < h and 0 <= xi < w:
            img[yi + d, xi] = color


def _px_per_metre_at_pupil():
    c = eyes.calibration()
    k = eyes.camera_matrices(c)[0]
    pct = bpy.context.scene.render.resolution_percentage / 100.0
    return k[0][0] / (c["camera_distance"] - c["pupil_offset_L"]), c, pct


def iris_radius_px():
    s, c, _ = _px_per_metre_at_pupil()
    return s * c["iris_radius"]


def pupil_radius_px():
    s, c, _ = _px_per_metre_at_pupil()
    return s * c["pupil_radius"]
