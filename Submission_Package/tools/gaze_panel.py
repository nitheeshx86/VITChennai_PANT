r"""Play with the eyes interactively in Blender.

    "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe" scene.blend --python tools/gaze_panel.py

Opens the scene looking through the render camera with a "Gaze" tab in the 3D view's
sidebar (press N if the sidebar is hidden): sliders for h / v, blink, pupil size and iris
colour, buttons for Left / Right / Up / Down / Reset, a "Saccade" button that animates a
realistic eye movement to a random point, and "Render" (saves a 1024x1024 PNG + its labels
to output/).
"""
import json
import os
import random
import sys
import time

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper"))
import eyes  # noqa: E402

_busy = {"on": False}


def _apply(scene):
    if _busy["on"]:
        return
    eyes._state["blink"] = scene.xr_blink
    eyes._state["melanin"] = scene.xr_melanin
    calib = eyes.calibration()
    r = 0.0005 * scene.xr_pupil
    r0, r1 = calib["pupil_radius"], calib.get("pupil_radius_max", calib["pupil_radius"])
    rmin = calib.get("pupil_radius_min", r0)
    eyes._state["pupil"] = (max(rmin, min(r1, r)) - r0) / (r1 - r0)
    eyes._apply_appearance(calib)
    eyes.move(scene.xr_h, scene.xr_v, record=False)


def _update(self, context):
    _apply(context.scene)


def _set_hv(scene, h, v):
    _busy["on"] = True
    scene.xr_h, scene.xr_v = h, v
    _busy["on"] = False
    _apply(scene)


class XR_OT_look(bpy.types.Operator):
    bl_idname = "xr.look"
    bl_label = "Look"
    direction: bpy.props.StringProperty()

    def execute(self, context):
        h, v = eyes.DIRECTIONS[self.direction]
        _set_hv(context.scene, h, v)
        return {"FINISHED"}


class XR_OT_saccade(bpy.types.Operator):
    """Animate a realistic saccade (human main-sequence timing) to a random point"""
    bl_idname = "xr.saccade"
    bl_label = "Saccade to a random point"

    def execute(self, context):
        s = context.scene
        h1, v1 = random.uniform(-1, 1), random.uniform(-1, 1)
        path = eyes.saccade(h1, v1, fps=240.0)
        t0 = time.perf_counter()
        for p in path:                       # real-time playback, slowed 6x so it is visible
            while time.perf_counter() - t0 < 6 * p["t_ms"] / 1000.0:
                pass
            _set_hv(s, p["h"], p["v"])
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
        self.report({"INFO"}, "saccade %.1f deg in %.0f ms (shown 6x slower)"
                    % (eyes.saccade_stats(path[0]["h"], path[0]["v"], h1, v1)["amplitude_deg"], path[-1]["t_ms"]))
        return {"FINISHED"}


class XR_OT_render(bpy.types.Operator):
    """Render the current gaze to output/ (PNG + JSON labels)"""
    bl_idname = "xr.render"
    bl_label = "Render this gaze"

    def execute(self, context):
        s = context.scene
        name = "play_h%+.2f_v%+.2f" % (s.xr_h, s.xr_v)
        path, rec = eyes.render(os.path.join(ROOT, "output", name + ".png"))
        with open(os.path.join(ROOT, "output", name + ".json"), "w") as f:
            json.dump(rec, f, indent=2)
        self.report({"INFO"}, "saved " + path)
        return {"FINISHED"}


class XR_PT_gaze(bpy.types.Panel):
    bl_label = "Gaze"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Gaze"

    def draw(self, context):
        s = context.scene
        col = self.layout.column(align=True)
        col.prop(s, "xr_h", slider=True)
        col.prop(s, "xr_v", slider=True)
        row = self.layout.row(align=True)
        for d in ("left", "up", "down", "right"):
            row.operator("xr.look", text=d.capitalize()).direction = d
        self.layout.operator("xr.look", text="Reset").direction = "reset"
        self.layout.operator("xr.saccade", icon="PLAY")
        col = self.layout.column(align=True)
        col.label(text="Appearance")
        col.prop(s, "xr_blink", slider=True)
        col.prop(s, "xr_pupil", slider=True)
        col.prop(s, "xr_melanin", slider=True)
        self.layout.operator("xr.render", icon="RENDER_STILL")


def register():
    S = bpy.types.Scene
    S.xr_h = bpy.props.FloatProperty(name="h (left / right)", min=-1, max=1, default=0, update=_update)
    S.xr_v = bpy.props.FloatProperty(name="v (down / up)", min=-1, max=1, default=0, update=_update)
    S.xr_blink = bpy.props.FloatProperty(name="Blink", min=0, max=1, default=0, update=_update)
    S.xr_pupil = bpy.props.FloatProperty(name="Pupil (mm)", min=2.0, max=7.0, default=3.8, update=_update)
    S.xr_melanin = bpy.props.FloatProperty(name="Iris: blue -> brown", min=0, max=1, default=0, update=_update)
    for c in (XR_OT_look, XR_OT_saccade, XR_OT_render, XR_PT_gaze):
        bpy.utils.register_class(c)


def setup_view():
    if bpy.app.background:
        return
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.shading.type = "MATERIAL"
                space.region_3d.view_perspective = "CAMERA"
                space.show_region_ui = True
                space.overlay.show_overlays = False


register()
eyes.reset()
setup_view()
print("[gaze_panel] ready: 3D view sidebar -> 'Gaze' tab")
