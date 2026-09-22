"""Create and pack a second UV channel (Unity's UV2) for lightmapping.

For each selected mesh: ensure a second UV map exists, unwrap it with Smart UV
Project, equalize island scale, and pack with a fixed margin. UV0 is never touched.

Unity: leave "Generate Lightmap UVs" OFF for meshes processed here.

Usage: select objects in Object Mode, run from the Text Editor, or paste through
the Blender MCP `execute_blender_code`.
"""

import math
import bpy

# --- configure -------------------------------------------------------------
UV2_NAME = "Lightmap"
ANGLE_LIMIT_DEG = 66.0      # higher = fewer, larger islands
ISLAND_MARGIN = 0.03        # ~2 texels at 512-1024; raise for low lightmap resolution
PACK_MARGIN = 0.03
# ---------------------------------------------------------------------------


def view3d_override():
    """Find a VIEW_3D context so uv operators work from a script."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        return dict(window=window, area=area, region=region,
                                    screen=window.screen)
    return None


def ensure_uv2(mesh):
    """Return the UV layer that Unity will read as UV2 (the second slot)."""
    layers = mesh.uv_layers
    if len(layers) == 0:
        layers.new(name="UVMap")
    if len(layers) == 1:
        layers.new(name=UV2_NAME)
    return layers[1]


def process(ob, override):
    mesh = ob.data
    uv2 = ensure_uv2(mesh)
    mesh.uv_layers.active = uv2
    for i, layer in enumerate(mesh.uv_layers):
        layer.active_render = (i == 0)      # keep UV0 as the render channel

    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")

    ctx = bpy.context.temp_override(**override) if override else None
    if ctx:
        with ctx:
            _unwrap()
    else:
        _unwrap()

    bpy.ops.object.mode_set(mode="OBJECT")
    print("[uv2] %-30s islands packed into '%s'" % (ob.name, uv2.name))


def _unwrap():
    try:
        bpy.ops.uv.smart_project(angle_limit=math.radians(ANGLE_LIMIT_DEG),
                                 island_margin=ISLAND_MARGIN,
                                 correct_aspect=True,
                                 scale_to_bounds=False)
    except TypeError:
        # older/newer signature: angle_limit in degrees
        bpy.ops.uv.smart_project(angle_limit=ANGLE_LIMIT_DEG,
                                 island_margin=ISLAND_MARGIN)
    bpy.ops.uv.select_all(action="SELECT")
    try:
        bpy.ops.uv.average_islands_scale()
    except RuntimeError as exc:
        print("[uv2] average_islands_scale skipped:", exc)
    try:
        bpy.ops.uv.pack_islands(margin=PACK_MARGIN, rotate=True)
    except TypeError:
        bpy.ops.uv.pack_islands(margin=PACK_MARGIN)


def main():
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    targets = [ob for ob in bpy.context.selected_objects if ob.type == "MESH"]
    if not targets:
        print("[uv2] no mesh objects selected")
        return

    override = view3d_override()
    active = bpy.context.view_layer.objects.active
    for ob in targets:
        try:
            process(ob, override)
        except Exception as exc:                      # keep going through a batch
            print("[uv2] FAILED on %s: %s" % (ob.name, exc))
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")

    bpy.context.view_layer.objects.active = active
    print("[uv2] done:", len(targets), "object(s)")


main()
