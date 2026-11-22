# Source Code

All the code of the project. The runnable copy lives in
[`../Submission_Package`](../Submission_Package), next to `scene.blend`, because the Track 1
layout requires `wrapper/eyes.py` beside the scene. **Run everything from there.** This
folder is the same code, gathered in one place for reading and reviewing.

## Map

| Area | Files | What it does |
| --- | --- | --- |
| **Gaze control** | `wrapper/eyes.py` | `eyes.move(h, v)`, `eyes.reset()`, `eyes.render()`: calibration, per-eye aiming (vergence, angle kappa, Listing's law), lid follow, blinks, saccades, camera matrices, the metadata record |
| | `wrapper/run_sequence.py` | One command: the 10-frame clockwise sequence + `metadata.json` |
| | `wrapper/run_directions.py` | The five direction-check poses (Reset, Left, Right, Up, Down) |
| | `wrapper/generate_dataset.py` | Many random gazes with labels: the purpose of the rig |
| **Scene build** | `build_scene.py` | Rebuilds `scene.blend` from scratch: MPFB human, metric scale, eyeballs + cornea, eye bones at the globe centres, lid shape keys, materials, camera, lights, render settings |
| | `tools/make_textures.py`, `tools/bake_skin.py` | Iris / sclera textures and the baked skin maps on the MakeHuman UV layout |
| **Verification** | `tests/run_all.py` + 7 `test_*.py` | 651 checks: scale and calibration, directions, pupil found in the rendered pixels, sequence and metadata, determinism, optics, saccades |
| | `tests/test_clean_run.py` | Simulates the evaluator: unzips the bundle and reruns the README commands |
| **Outputs** | `tools/make_contact_sheet.py`, `make_direction_sheet.py`, `make_direction_gif.py`, `make_bundle.py` | Contact sheet, direction-check sheet and GIF, the submission zip |
| **Interactive** | `tools/gaze_panel.py` | A "Gaze" tab in Blender with sliders for h / v, blink, pupil and iris |
| **Demo video** | `tools/render_demo.py`, `tools/make_demo_video.py` | Renders the video frames (camera locked) and assembles the 1920 × 1080 video |
| **Development probes** | the remaining `tools/*.py` | One-off inspection scripts used while tuning lids, glints, lighting and skin |

## Run (from `Submission_Package/`)

```
blender --background scene.blend --python wrapper/run_sequence.py
blender --background scene.blend --python wrapper/eyes.py -- --look left --out output/left.png
python tests/run_all.py
```

Requirements: Blender 4.2 LTS only (the wrapper uses Blender's bundled Python). The tests'
image checks use NumPy, which Blender also bundles.
