"""Batch-export Blender objects to Unity-ready FBX files.

Usage
-----
Blender Text Editor: set EXPORT_DIR and MODE below, select objects, press Run.
Blender MCP:         paste through `execute_blender_code` after `get_scene_info()`.

MODE:
    "object"     one FBX per selected object, named after the object
    "collection" one FBX per collection that contains a selected object
    "single"     one FBX containing everything selected, named SINGLE_NAME

Settings match ../references/fbx-export.md: FBX All scaling, -Z forward / Y up,
face smoothing, modifiers applied, triangulated, meshes only.
"""

import os
import bpy

# --- configure -------------------------------------------------------------
EXPORT_DIR = r"C:/Users/matty/Documents/Unity/Exports"   # forward slashes are fine on Windows
MODE = "object"
SINGLE_NAME = "world_chunk"
USE_TANGENTS = False        # True only if the meshes use normal maps
APPLY_MODIFIERS = True
# ---------------------------------------------------------------------------


def _export(filepath, objects):
    bpy.ops.object.select_all(action="DESELECT")
    for ob in objects:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]

    kwargs = dict(
        filepath=filepath,
        use_selection=True,
        object_types={"MESH"},
        global_scale=1.0,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_ALL",
        use_space_transform=True,
        bake_space_transform=False,
        axis_forward="-Z",
        axis_up="Y",
        mesh_smooth_type="FACE",
        use_mesh_modifiers=APPLY_MODIFIERS,
        use_triangles=True,
        use_tspace=USE_TANGENTS,
        use_custom_props=False,
        add_leaf_bones=False,
        bake_anim=False,
        path_mode="COPY",
        embed_textures=False,
    )
    # Tolerate keyword changes between Blender versions.
    try:
        bpy.ops.export_scene.fbx(**kwargs)
    except TypeError as exc:
        print("[export] retrying with reduced kwargs:", exc)
        for key in ("use_triangles", "add_leaf_bones", "embed_textures"):
            kwargs.pop(key, None)
        bpy.ops.export_scene.fbx(**kwargs)
    print("[export] wrote", filepath)


def main():
    os.makedirs(EXPORT_DIR, exist_ok=True)

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    selected = [ob for ob in bpy.context.selected_objects if ob.type == "MESH"]
    if not selected:
        print("[export] nothing selected (mesh objects only) - aborting")
        return

    original = list(selected)
    warned = False
    for ob in original:
        if tuple(round(v, 4) for v in ob.scale) != (1.0, 1.0, 1.0):
            print("[warn] '%s' has unapplied scale %s - Ctrl+A > Scale first" % (ob.name, tuple(ob.scale)))
            warned = True
    if warned:
        print("[warn] exporting anyway; fix the transforms if Unity shows odd sizes")

    if MODE == "single":
        _export(os.path.join(EXPORT_DIR, SINGLE_NAME + ".fbx"), original)

    elif MODE == "collection":
        groups = {}
        for ob in original:
            for coll in ob.users_collection:
                groups.setdefault(coll.name, []).append(ob)
        for name, obs in groups.items():
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
            _export(os.path.join(EXPORT_DIR, safe + ".fbx"), obs)

    else:  # "object"
        for ob in original:
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in ob.name)
            _export(os.path.join(EXPORT_DIR, safe + ".fbx"), [ob])

    # restore selection
    bpy.ops.object.select_all(action="DESELECT")
    for ob in original:
        ob.select_set(True)
    print("[export] done:", len(original), "object(s), mode =", MODE)


main()
