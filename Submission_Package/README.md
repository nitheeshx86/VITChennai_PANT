# Synthetic Eye Movement & Virtual Camera Rendering

Samsung R&D Institute India (Bangalore) XR Hackathon 2026 — **Track 1**

**Team PANT — VIT Chennai** (`VITChennai_PANT`)

| Name | Register No. | Email | Affiliation |
| --- | --- | --- | --- |
| Nitheesh K. | 24BEC1459 | nitheesh.k2024@vitstudent.ac.in | VIT Chennai |
| Adithya K. | 24BEC1304 | adithya.k2024@vitstudent.ac.in | VIT Chennai |
| Pariksith S.S. | 24BEC1454 | pariksith.ss2024@vitstudent.ac.in | VIT Chennai |
| Tarun Ashwat M. | 24BEC1435 | tarun.ashwat2024@vitstudent.ac.in | VIT Chennai |

PANT stands for **P**ariksith, **A**dithya, **N**itheesh and **T**arun.

**Demo video (1:55):** https://www.youtube.com/watch?v=YICEQyBMeDM

A textured MakeHuman face in Blender whose two eyeballs rotate as rigid 3D spheres about
their own centres. A small deterministic Python wrapper sets the gaze, renders
1024 × 1024 PNGs from a camera locked 40 cm in front of the face, and writes exact
ground truth for every frame (eye rotations, projected 2D pupil centres, camera matrix).

```
scene.blend              textured mesh, eye bones, materials (all textures packed)
wrapper/eyes.py          eyes.move(h, v) / eyes.reset() / eyes.render()
wrapper/run_sequence.py  one command: regenerates the 10 renders + metadata
renders/                 frame_00.png … frame_09.png  (θk = 2πk/10, from the top, clockwise)
metadata.json            10 per-frame records
README.md                this file
textures/                the UV texture maps (skin, iris, sclera)
metadata_frames/         the same 10 records, one JSON per frame
direction_check/         Reset / Left / Right / Up / Down renders, their metadata, a zoomed
                         sheet and an animated flip (directions.gif)
tests/                   verification suite
contact_sheet.png        all 10 frames, labelled
build_scene.py, tools/   rebuild the scene and its textures from scratch (section 9), the
                         interactive gaze panel (tools/gaze_panel.py) and the bundler
```

**At a glance**

* The ten frames: [`contact_sheet.png`](contact_sheet.png). The five test directions against
  Reset: [`direction_check/directions.gif`](direction_check/directions.gif) (unmodified pixels,
  flipping) and [`direction_check/sheet.png`](direction_check/sheet.png) (zoomed, with the
  measured shifts of 15.1–15.4 px per pupil).
* Quick checks (minutes, see section 2 for timings):

  ```
  blender --background scene.blend --python wrapper/eyes.py -- --look left --fast --out output/left.png
  blender --background scene.blend --python wrapper/run_sequence.py -- --fast --out output/fast_check
  python tests/run_all.py test_scale_and_calibration test_directions test_sequence_and_metadata
  ```

* Conventions in one line: +h = pupils toward image-right, +v = up; `L`/`R` = the avatar's
  own eyes; rotations are world-frame XYZ Euler radians of each eye's line of sight; pixels
  from the top-left, y down. Details in section 3.

## 1. Requirements

* **Blender 4.2 LTS** (developed and verified on 4.2.3 LTS, Windows 11; later 4.x releases
  are expected to work but were not tested).
  Nothing else: the wrapper uses only Blender's bundled Python (`bpy`, `mathutils`).
* No add-ons are needed to *use* `scene.blend`. (MPFB is only needed to rebuild the scene
  from scratch, see section 9.)
* A GPU is used automatically if Cycles finds one, otherwise the CPU. Force the CPU with the
  environment variable `XR_DEVICE=CPU`.

If `blender` is not on your PATH, use the full path to the executable, e.g.
`"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"` on Windows or
`/Applications/Blender.app/Contents/MacOS/Blender` on macOS.

## 2. Run it

All commands are run from this folder (the one containing `scene.blend`).

**Regenerate everything (10 renders + metadata) with one command:**

```
blender --background scene.blend --python wrapper/run_sequence.py
```

**How long it takes.** Final quality is Cycles at 128 samples, which is slow on a CPU. Each
frame prints its time and the time left. Measured on a laptop (RTX 3050 Laptop GPU / its CPU),
including Blender start-up:

| Command | What you get | NVIDIA GPU | CPU only |
| --- | --- | --- | --- |
| `... run_sequence.py` | the official renders + metadata | ~5 min (30 s / frame) | ~60 min (6 min / frame) |
| `... run_sequence.py -- --fast` | same 10 frames at 16 samples (slightly softer, dimmer glints) + identical metadata | 1.5 min | ~9 min |
| `... run_sequence.py -- --no-render` | metadata only | 7 s | 7 s |

The metadata is computed from the scene geometry, not from the pixels, so it is identical in
all three modes. Add `--out DIR` to write somewhere other than this folder (useful for
`--fast`, so the shipped renders are not overwritten). The GPU is used automatically when
Cycles finds one; `XR_DEVICE=CPU` forces the CPU.

**Render one gaze direction:**

```
blender --background scene.blend --python wrapper/eyes.py -- --look left --out output/left.png
blender --background scene.blend --python wrapper/eyes.py -- --h 0.5 --v -0.25 --out output/custom.png
blender --background scene.blend --python wrapper/eyes.py -- --look up --fast --out output/up.png
```

`--look` accepts `left`, `right`, `up`, `down`, `reset`. The frame's metadata record is
printed as JSON. `--fast` renders at 16 samples (~10 s on a GPU, ~50 s on a CPU, instead of
30 s / 6 min); `--no-render` prints only the metadata.

**Use the API from your own script** (`blender --background scene.blend --python my_script.py`):

```python
import sys
sys.path.insert(0, "wrapper")
import eyes

eyes.move(-1, 0)                 # look fully left  (h, v are clamped to [-1, +1])
path, record = eyes.render("output/left.png")
print(record["pupil_center_2D_L"], record["eye_rotation_L"])

eyes.reset()                     # back to centre
path, record = eyes.render()     # default path: output/gaze_h+0.000_v+0.000.png
```

| Call | Effect |
| --- | --- |
| `eyes.move(h, v)` | Set the gaze. Returns the metadata record for the new pose. |
| `eyes.reset()` | Centre the gaze (`h = 0, v = 0`). |
| `eyes.render(path=None)` | Render the current pose to a PNG. Returns `(absolute_path, record)`. |
| `eyes.look("left")` | Convenience for the five named directions. |
| `eyes.state()` | The metadata record for the current pose, without rendering. |

## 3. Conventions

| Item | Convention |
| --- | --- |
| Units | Metres (Blender unit scale 1.0). |
| World axes | +X = avatar's left, −Y = face forward **F**, +Z = up **U**. Detected from the model at build time and stored in the scene, not hard-coded in the wrapper. |
| Eye midpoint **M** | Midpoint of the two eyeball centres. |
| `h` | Horizontal gaze, [−1, +1]. **+h moves the pupils toward the right side of the rendered image.** |
| `v` | Vertical gaze, [−1, +1]. **+v moves the pupils up in the image.** |
| Left / Right | Image space: `eyes.move(-1, 0)` = pupils toward the image's left edge. One constant, `H_SIGN` in `wrapper/eyes.py`, flips this (`V_SIGN` for vertical). |
| `L` / `R` | The avatar's anatomical left / right eye (bones `eye.L` / `eye.R`). The avatar faces the camera, so **eye L is on the right side of the image**. |
| Fixation target | `T = M + 0.35·F + (h·0.05)·R + (v·0.05)·U` metres, where **R** is the direction that appears as image-right. This is our reading of "35 cm forward, motion bounds ±5 cm": the target moves ±5 cm on the plane 35 cm in front of the eyes. |
| Vergence | Each eye rotates independently so that its **line of sight** (visual axis) passes through `T`. The two rotations therefore differ: at reset the left eye turns 5.06° nasally, the right eye 5.06° nasally the other way, and the lines of sight converge by 10.11° (2·atan(IPD/2 / 0.35 m)). `vergence_angle_deg` is stored in every record. |
| Rotation | `eye_rotation_L/R`: rotation of the eye's **line of sight from straight ahead, in the world frame**, as XYZ Euler angles in radians (Blender "XYZ" order, `R = Rz·Ry·Rx`). Check: `R · F` (F = face forward, `conventions.forward_world`) is `gaze_direction_world`, and the line from `eye_center_world` along it passes through `fixation_target_world` (within 0.001 mm). Quaternions (w, x, y, z) and 3×3 matrices of the same rotation are in `eye_rotation_quat_L/R` and `eye_rotation_matrix_L/R`. Sign example: looking up gives a negative `rx`, because F is −Y. |
| Globe rotation | `globe_rotation_L/R` (+ `_quat`, `_matrix`): the rigid rotation actually applied to the eyeball mesh about its centre. It differs from `eye_rotation` by angle kappa (next row). |
| Angle kappa | A real eye looks along its visual axis, the line to the fovea, which lies about 5° nasal of the eyeball's geometric (optical) axis. We model this (`KAPPA_DEG = 5.0` in `wrapper/eyes.py`), so at 35 cm the irises look naturally centred instead of crossed. `optical_axis_world_L/R` gives the geometric axis. Set `KAPPA_DEG = 0.0` to make the globe and line-of-sight rotations identical. |
| Torsion | Both rotations are the shortest arc from straight ahead, so there is no roll about the line of sight (Listing's law). |
| Pixels | Origin at the top-left corner of the image, x to the right, y down, in pixels of the 1024 × 1024 render. |
| 2D pupil centre | `pupil_center_2D_L/R` = `camera_matrix · pupil_center_3D_L/R` exactly: the projection of the 3D centre of the pupil disc (on the iris plane inside the eye). The cornea refracts the pupil's image by 0.4–1.3 px; that refracted centre, which is what a detector finds in the PNG (to ~0.1 px), is given separately as `pupil_center_2D_apparent_L/R`. |
| `camera_matrix` | 3×4 `P = K·[R|t]`, mapping homogeneous world points (metres) to homogeneous pixels. `camera_intrinsics_K` (3×3) and `camera_extrinsics_world_to_cam` (3×4, OpenCV camera frame: x right, y down, z forward) are included so it can be checked. |
| Sequence | Frame k = 0…9: θk = 2πk/10, h = sin θk, v = cos θk. Frame 0 looks straight up, then the gaze moves clockwise as seen in the renders. |

## 4. Calibration

| Quantity | Value | Where it is checked |
| --- | --- | --- |
| Inter-pupillary distance | 61.9 mm | `tests/test_scale_and_calibration.py` |
| Eyeball diameter | 25.0 mm (iris 11.8 mm, pupil 3.8 mm) | same |
| Body height | 1.77 m | same |
| Vergence at reset | 10.11° between the lines of sight (5.06° per eye) | same, and every frame in `tests/test_sequence_and_metadata.py` |
| Fixation plane | 0.350 m in front of M | same |
| Motion bounds | ±0.050 m on that plane | same |
| Camera | 0.400 m in front of M, on the forward axis, looking at M, upright, locked | same |
| Lens | 140 mm on a 36 mm sensor (fx = fy = 3982.2 px, cx = cy = 512) | metadata |
| Render | 1024 × 1024 PNG, Cycles, 128 samples, seed 0, OpenImageDenoise | `tests/test_determinism.py` |

**Why 140 mm.** With ±5 cm at 35 cm the eye only rotates atan(5/35) ≈ 8.1°, which moves the
pupil about 1.75 mm. The camera position is fixed at 40 cm, as advised by the SRIB mentors,
so the focal length decides how many pixels that is. 140 mm frames the eye region and gives a
clear shift:

| Direction | Call | Eye L shift (px) | Eye R shift (px) |
| --- | --- | --- | --- |
| Left | `eyes.move(-1, 0)` | Δx = −15.14 | Δx = −15.34 |
| Right | `eyes.move(+1, 0)` | Δx = +15.34 | Δx = +15.14 |
| Up | `eyes.move(0, +1)` | Δy = −15.36 | Δy = −15.36 |
| Down | `eyes.move(0, -1)` | Δy = +15.35 | Δy = +15.35 |
| Reset | `eyes.reset()` | 0.00 | 0.00 |

(Image y points down, so "up" is negative Δy. Left and right differ slightly between the
eyes because of vergence.)

To see the shift: [`direction_check/directions.gif`](direction_check/directions.gif) flips
the unmodified eye region between Reset and each direction, with fixed ticks at the Reset
pupil centre. [`direction_check/sheet.png`](direction_check/sheet.png) shows all five poses
zoomed, with the measured shift of each pupil.

## 5. Metadata

`metadata.json` is a JSON array of 10 records in frame order. Required keys:

```json
{
  "frame": 3,
  "theta": 1.8849555921538759,
  "input": { "h": 0.9510565162951536, "v": -0.30901699437494734 },
  "eye_rotation_L": [rx, ry, rz],
  "eye_rotation_R": [rx, ry, rz],
  "pupil_center_2D_L": [x, y],
  "pupil_center_2D_R": [x, y],
  "camera_matrix": [[...4], [...4], [...4]]
}
```

Extra keys in every record: `image`, `camera_intrinsics_K`,
`camera_extrinsics_world_to_cam`, `eye_rotation_quat_L/R`, `eye_rotation_matrix_L/R`,
`vergence_angle_deg`, `globe_rotation_L/R` (+ `_quat`, `_matrix`),
`gaze_direction_world_L/R`, `optical_axis_world_L/R`, `eye_center_world_L/R`,
`pupil_center_3D_L/R`, `fixation_target_world`, `conventions`, plus optical labels
(pupil/iris ellipses, corneal reflections, eyelid landmarks).

Note: the example record on the SRIB mentors' slides shows `v = +0.309` for frame 3. By the
stated formula `v = cos(2π·3/10) = −0.309`; we follow the formula.

## 6. How the eyes move (and why it is true 3D rotation)

* Each eye is its own rigid object set — sclera, iris, pupil and a refractive cornea shell —
  parented to its own bone (`eye.L`, `eye.R`). The bone's head sits exactly at the geometric
  centre of the 25 mm globe.
* `eyes.move` computes the target `T`, then for each eye the shortest rotation of the globe
  that puts that eye's line of sight (5° nasal of the globe's axis, angle kappa) exactly
  through `T`, and applies it to the bone about the eye centre. Nothing is ever translated and
  no texture is ever slid.
* The metadata is read **back from the evaluated scene** after posing (not copied from the
  request), so it describes what was actually rendered.
* The lids follow vertical gaze slightly, as real lids do. They are skin, not part of the
  eyeball, and they never cover the pupil.

## 7. Verification

```
python tests/run_all.py              # the seven Blender-side tests (~4 min with a GPU)
python tests/run_all.py --clean-run  # plus the clean-room test (re-renders everything)
```

`run_all.py` needs only a standard Python 3 and finds Blender through the `BLENDER`
environment variable, PATH, or the default install location. Each test can also be run
directly, e.g. `blender --background scene.blend --python tests/test_directions.py`.

| Test | What it proves |
| --- | --- |
| `test_scale_and_calibration.py` | Metric scale (IPD, eyeball size), camera at 40 cm looking at M, target at 35 cm ± 5 cm, both lines of sight pass through the target (vergence), Listing's law, bones pivot at the eyeball centres, a 90° rotation does not move the globe centre, lids and brows behave. |
| `test_directions.py` | Left / Right / Up / Down move both pupils the correct way by ≥ 12 px with negligible off-axis drift; Reset returns exactly to centre; inputs are clamped; same input → same pose. |
| `test_pupil_projection_matches_image.py` | Independent of the projection maths: finds the dark pupil in fresh renders by thresholding and checks it against the metadata (≤ 3 px; the refracted `pupil_center_2D_apparent` ≤ 1 px), checks the glints, that the pixels moved the right way and that the lids do not cover the pupil. Marked-up copies go to `debug/`. |
| `test_sequence_and_metadata.py` | Exactly 10 PNGs of 1024 × 1024, valid metadata with all required keys, θ/h/v match the formula to 1e-6, `P = K[R|t]`, `pupil_center_2D = P · pupil_center_3D`, each eye's gaze rebuilt from the required Euler angles alone hits the target with the geometric vergence, the metadata matches the live scene, the pupil path is a clockwise loop from the top, and the pupils in the shipped PNGs are where the metadata says. |
| `test_determinism.py` | The same input rendered twice gives identical metadata and the same image (to within 1/255 in fewer than 0.05 % of pixels; measured: 112 pixels differ by 1/255). |
| `test_optics.py` | The refraction and glint labels obey Snell's law and the law of reflection; glints stay off the pupil. |
| `test_saccade.py` | `eyes.saccade()` trajectories follow the human main sequence (duration, peak velocity, bell-shaped profile). |
| `test_clean_run.py` | Copies (or unzips) the bundle into an empty folder, deletes the outputs, runs the commands in section 2 and checks that the renders and metadata are regenerated (required metadata keys equal to the shipped ones within 1e-9) and that the sequence and direction tests pass inside the copy. Pixel identity with the shipped frames is reported as information: within 1/255 on the same machine, a few grey levels of render noise on other hardware. |

## 8. Realism

* **Eyes.** Separate sclera, iris and pupil surfaces inside a clear cornea/tear-film shell
  with real refraction (keratometric index 1.3375) and a corneal bulge (7.8 mm radius of curvature), so the
  iris has depth and the catch-lights slide over the cornea as the eye turns. Iris texture
  with radial fibres, collarette and a dark limbal ring; off-white sclera with fine veins
  that gather toward the corners; subsurface scattering in the sclera.
* **Skin.** The CC0 MakeHuman skin is the base. `tools/bake_skin.py` authors tone,
  redness around the eyes and nose, under-eye colour, freckles in irregular clusters with a
  few larger sun spots, uneven pigmentation, faint broken capillaries on the nose wings, a
  small mole and a healed blemish, the upper-eyelid crease, crow's feet, under-eye and
  forehead lines and an oilier T-zone procedurally in 3D on the mesh and bakes them into the
  model's own UV layout (`textures/skin_*.png`). The material adds subsurface scattering and
  pore-level micro-bump, with larger pores on the oily nose and forehead.
* **Lighting.** A fixed three-light studio setup (soft key, fill, rim) and a neutral
  backdrop; identical in every frame.

## 9. Rebuilding from scratch (optional)

Everything is scripted; nothing in `scene.blend` was made by hand.

1. Install the **MPFB** add-on (Blender: Edit → Preferences → Get Extensions → "MPFB").
2. Download the CC0 **MakeHuman system assets** pack
   (`makehuman_system_assets_cc0.zip` from files.makehumancommunity.org) and unzip it into
   `assets/mh_assets/`.
3. From the repository root:

```
python tools/make_textures.py                          # iris + sclera maps (numpy, opencv-python)
blender --background --python tools/bake_skin.py       # skin albedo / roughness / normal maps
blender --background --python build_scene.py           # writes scene.blend (textures packed)
blender --background scene.blend --python wrapper/run_sequence.py
python tools/make_contact_sheet.py                     # contact_sheet.png (Pillow)
```

## 10. Assets and licences

| Asset | Source | Licence |
| --- | --- | --- |
| Base mesh, rig, skin texture, eyebrows, eyelashes | MakeHuman community assets, via MPFB | CC0 1.0 |
| Clothing (`male_elegantsuit01`, `shoes04`): shown in the viewport only, disabled in renders, so the official frames are exactly what they are without it | MakeHuman community assets, via MPFB | CC0 1.0 |
| MPFB add-on (build-time tool only, not distributed) | extensions.blender.org | GPL-3.0-or-later |
| Eyeball geometry, iris / sclera textures, baked skin maps, all scripts | this project | made for this submission |

## 11. Limitations

* The gaze range is ±5 cm at 35 cm (≈ ±8°), as advised by the SRIB mentors. The rig itself is
  not limited to that; only `MOTION_BOUND_M` would change.
* The official sequence uses one pupil size (3.8 mm). `eyes.set_appearance()` changes the
  pupil (2–7 mm) and iris colour for dataset variation, but there is no automatic light
  reflex or accommodation.
* The required 2D pupil centre is the geometric projection of the pupil centre, as advised by
  the SRIB mentors. Corneal refraction moves the imaged pupil by 0.4–1.3 px at these angles,
  inside the 3 px tolerance of the image-based test; the exact refracted centre is provided
  as `pupil_center_2D_apparent_L/R`.
* MakeHuman's eye sockets are sculpted for an oversized eye. `build_scene.py` re-seats a
  realistic 25 mm globe in the lid opening and moves the surrounding lid skin back to meet
  it; the face is therefore slightly different from the stock MakeHuman face.
* One identity, one lighting setup. For a real training set the same scripts would be run
  over many identities, textures and lights.
* Images rendered on different hardware (GPU vs CPU, different GPU vendors) can differ by a
  few grey levels in noise; on one machine repeated renders agree to within 1/255 (the
  metadata is identical everywhere: it does not depend on the pixels).
