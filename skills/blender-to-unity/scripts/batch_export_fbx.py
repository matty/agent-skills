"""Batch-export Blender objects to Unity-ready FBX files.

Usage
-----
Blender Text Editor: set EXPORT_DIR and MODE below, select objects, press Run.
Blender MCP:         paste through `execute_blender_code` after `get_scene_info()`.
Headless, a whole kit file, one FBX per piece collection into <dir>/<FAMILY>/<Piece>.fbx:
    blender -b --factory-startup KIT_World.blend --python batch_export_fbx.py -- --kit --dir export/fbx
            [--tangents] [--set-status]     # --set-status writes kit_status = "exported" and saves the KIT file

MODE:
    "object"     one FBX per selected object, named after the object
    "collection" one FBX per collection that contains a selected object
    "single"     one FBX containing everything selected, named SINGLE_NAME

Settings match ../references/fbx-export.md: FBX All scaling, -Z forward / Y up,
face smoothing, modifiers applied, triangulated, meshes only.
"""

import os
import re
import sys

import bpy

PIECE_RE = re.compile(r"^([A-Z]{2,5})_[A-Za-z0-9]+_(\d+(?:x\d+){0,2}|Free)_[A-Z]\d?$")

# --- configure -------------------------------------------------------------
EXPORT_DIR = "//export/fbx"   # // = next to the open .blend; forward slashes are fine on Windows
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
        bake_space_transform=True,  # axis change into the vertices: root arrives at rotation 0
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


def export_kit(out_dir, set_status=False):
    """One FBX per kit piece collection (local, named <FAMILY>_<Type>_<Size>_<Variant>) with every mesh in it (LODs
    and _COL included), into out_dir/<FAMILY>/<Piece>.fbx. Returns the files written."""
    out_dir = bpy.path.abspath(out_dir)
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    written = []
    for coll in sorted(bpy.data.collections, key=lambda c: c.name):
        m = PIECE_RE.match(coll.name)
        if coll.library is not None or not m:
            continue
        obs = [o for o in coll.all_objects if o.type == "MESH"]
        if not obs:
            print("[export] %s: no meshes, skipped" % coll.name)
            continue
        for ob in obs:
            if tuple(round(v, 4) for v in ob.scale) != (1.0, 1.0, 1.0):
                print("[warn] '%s' has unapplied scale %s" % (ob.name, tuple(ob.scale)))
        folder = os.path.join(out_dir, m.group(1))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, coll.name + ".fbx")
        _export(path, obs)
        written.append(path)
        if set_status:
            coll["kit_status"] = "exported"
    if set_status and written:
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_mainfile()
    print("[export] kit: %d piece(s) into %s" % (len(written), out_dir))
    return written


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--kit" in argv:
        global USE_TANGENTS
        USE_TANGENTS = "--tangents" in argv
        out = argv[argv.index("--dir") + 1] if "--dir" in argv else EXPORT_DIR
        export_kit(out, set_status="--set-status" in argv)
        return
    os.makedirs(bpy.path.abspath(EXPORT_DIR), exist_ok=True)

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
        _export(os.path.join(bpy.path.abspath(EXPORT_DIR), SINGLE_NAME + ".fbx"), original)

    elif MODE == "collection":
        groups = {}
        for ob in original:
            for coll in ob.users_collection:
                groups.setdefault(coll.name, []).append(ob)
        for name, obs in groups.items():
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
            _export(os.path.join(bpy.path.abspath(EXPORT_DIR), safe + ".fbx"), obs)

    else:  # "object"
        for ob in original:
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in ob.name)
            _export(os.path.join(bpy.path.abspath(EXPORT_DIR), safe + ".fbx"), [ob])

    # restore selection
    bpy.ops.object.select_all(action="DESELECT")
    for ob in original:
        ob.select_set(True)
    print("[export] done:", len(original), "object(s), mode =", MODE)


main()
