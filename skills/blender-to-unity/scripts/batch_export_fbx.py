"""Batch-export Blender meshes to Unity-ready FBX files: one FBX per kit piece, per object or per collection.

Host: Blender 4.2+ (bpy; tested on 5.2.2), live or headless. Every exporter keyword it sets is in FBX_SETTINGS below,
and ../references/fbx-export.md has one row per keyword saying why.

Headless, a whole KIT file, one FBX per piece collection into <dir>/<FAMILY>/<Piece>.fbx:
    blender -b --factory-startup blender/kits/KIT_World.blend --python-exit-code 1 --python batch_export_fbx.py
            -- --kit --dir <dir> [--set-status]   # --set-status writes kit_status = "exported" and saves the KIT file
  --python-exit-code 1 makes a failed export exit 1 (without it Blender exits 0). <dir> is absolute, "//..." relative
  to the .blend's folder (//../../export/fbx from blender/kits/), or relative to the current directory; the absolute
  folder is printed. Every mesh in the piece collection is exported, hidden or not (LODs, <Piece>_COL), with its
  modifiers applied, Path Mode Strip, and the written object names are printed. A mesh that reaches the exporter with
  custom normals on faces of 4+ corners gets a warning: the exporter's own triangulation changes them.

Blender Text Editor: set EXPORT_DIR, MODE and PATH_MODE below, select mesh objects, press Run.
Blender MCP (execute_blender_code): run the file as is to export the selection, or load the functions only:
    ns = {"BATCH_EXPORT_NO_MAIN": True}; exec(open(path, encoding="utf-8").read(), ns)
    ns["export_kit"]("//../../export/fbx")       # returns {fbx path: [object names]}

MODE (interactive runs; only selectable objects are exported, hidden ones are reported and skipped):
    "object"     one FBX per selected mesh object, named after the object
    "collection" one FBX per collection holding a selected mesh, with the selected meshes of that collection
    "single"     one FBX with every selected mesh, named SINGLE_NAME
"""

import contextlib
import os
import re
import sys

import bpy

PIECE_RE = re.compile(r"^([A-Z]{2,5})_[A-Za-z0-9]+_(\d+(?:x\d+){0,2}|Free)_[A-Z]\d?$")

# --- configure (Text Editor and MCP runs) -------------------------------------------------------------------------
EXPORT_DIR = "//export/fbx"   # "//" = the open .blend's folder
MODE = "object"
SINGLE_NAME = "world_chunk"
PATH_MODE = "COPY"            # a one-off asset with its own textures; kit pieces (shared Unity materials): "STRIP"
VERTEX_COLORS = "NONE"        # "SRGB" or "LINEAR" only when the Unity shader reads vertex colours
# ------------------------------------------------------------------------------------------------------------------

# Every exporter keyword this script sets (path_mode and colors_type come from the call). One row each in
# ../references/fbx-export.md.
FBX_SETTINGS = dict(
    object_types={"MESH"},
    use_custom_props=False,
    global_scale=1.0,
    apply_unit_scale=True,
    apply_scale_options="FBX_SCALE_ALL",
    axis_forward="-Z",
    axis_up="Y",
    use_space_transform=True,
    bake_space_transform=True,  # the axis change goes into the vertices: roots arrive in Unity at rotation 0
    mesh_smooth_type="FACE",
    use_mesh_modifiers=True,
    use_subsurf=False,
    use_mesh_edges=False,
    use_triangles=True,
    use_tspace=False,           # Unity calculates MikkTSpace tangents on import
    colors_type="NONE",
    add_leaf_bones=False,
    bake_anim=False,
    embed_textures=False,
)
KIT_PATH_MODE = "STRIP"         # kit pieces use the family's shared Unity material: no texture copies


def resolve_dir(path):
    """Absolute folder for path: "//..." is relative to the open .blend's folder, anything else relative to the
    current directory (as for any command-line tool). "//..." in an unsaved file is refused: Blender would resolve
    it against its current directory (often C:\\Windows\\System32 or the install folder, so //../../ lands in C:\\)."""
    if path.startswith("//") and not bpy.data.filepath:
        raise ValueError("%r is relative to the .blend's folder, but this file has never been saved: save it first or "
                         "pass an absolute folder" % path)
    return os.path.normpath(os.path.abspath(bpy.path.abspath(path)))


def _warn_transform(ob, kit=False):
    m = ob.matrix_basis
    if any(abs(s - 1.0) > 1e-4 for s in m.to_scale()) or m.to_quaternion().angle > 1e-4:
        print("[warn] '%s' has unapplied rotation or scale (Ctrl+A > Rotation & Scale)" % ob.name)
    if kit and m.to_translation().length > 1e-4:
        # every object in a kit piece sits at identity with its origin at the piece pivot (blender-kit-library);
        # Unity's KitImport Check() flags an offset child
        print("[warn] '%s' is off the piece origin (location %s): apply location (Ctrl+A > All Transforms)"
              % (ob.name, tuple(round(v, 4) for v in m.to_translation())))


def _warn_retriangulation(objects):
    """use_triangles makes the exporter split every face of 4+ corners its own way. Measured on Blender 5.2.2: that
    changes custom normals (a weighted-normal panel went from 0.00 to 10.42 deg off flat, Harden Normals chamfers by up
    to 12.6 deg). A mesh that arrives already triangulated in its own stack exports unchanged. (Non-planar quads also
    get the exporter's diagonal: mesh_audit.py counts them.)"""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for ob in objects:
        if ob.type != "MESH":
            continue
        ev = ob.evaluated_get(depsgraph)
        me = ev.to_mesh()
        try:
            big = sum(1 for p in me.polygons if p.loop_total > 3)
            if big and me.has_custom_normals:
                print("[warn] '%s': custom normals on %d face(s) with 4+ corners, which the exporter's triangulation "
                      "changes: switch the stack's Triangulate back on if it is off in the viewport (UV work leaves "
                      "it off), or put a Triangulate modifier (Minimum Vertices 4, Keep Normals on) directly above "
                      "the Weighted Normal modifier, or after a Harden Normals bevel" % (ob.name, big))
        finally:
            ev.to_mesh_clear()


def _layer_paths(lc, coll, path=()):
    path = path + (lc,)
    if lc.collection == coll:
        yield path
    for child in lc.children:
        yield from _layer_paths(child, coll, path)


@contextlib.contextmanager
def _evaluated(coll):
    """Make every object in coll evaluated by the view layer while it is exported, then restore everything. The
    exporter applies modifiers only to evaluated objects: measured on Blender 5.2.2, objects or collections disabled
    in viewports, excluded collections and collections outside the scene export without their modifiers (objects
    hidden with H, or in a collection hidden with the eye, are fine)."""
    scene, vl = bpy.context.scene, bpy.context.view_layer
    undo = []
    if coll not in scene.collection.children_recursive:
        scene.collection.children.link(coll)
        undo.append(lambda: scene.collection.children.unlink(coll))
    for path in list(_layer_paths(vl.layer_collection, coll)):
        lcs = list(path[1:])
        stack = [path[-1]]
        while stack:
            lc = stack.pop()
            lcs.append(lc)
            stack.extend(lc.children)
        for lc in lcs:
            if lc.exclude:
                lc.exclude = False
                undo.append(lambda lc=lc: setattr(lc, "exclude", True))
            if lc.collection.hide_viewport:
                lc.collection.hide_viewport = False
                undo.append(lambda c=lc.collection: setattr(c, "hide_viewport", True))
    for ob in coll.all_objects:
        if ob.hide_viewport:
            ob.hide_viewport = False
            undo.append(lambda ob=ob: setattr(ob, "hide_viewport", True))
    vl.update()
    try:
        yield
    finally:
        for fn in reversed(undo):
            fn()
        vl.update()


def _export(filepath, objects=None, collection=None, path_mode=PATH_MODE, colors=VERTEX_COLORS):
    """Write one FBX and return the mesh object names in it. collection: every mesh in that collection and its child
    collections, visible or not, with no selection involved. objects: exactly these, which must be selectable
    (visible and in the view layer); the others are reported and skipped."""
    kw = dict(FBX_SETTINGS, filepath=filepath, path_mode=path_mode, colors_type=colors)
    if collection is not None:
        names = sorted(o.name for o in collection.all_objects if o.type == "MESH")
        kw.update(collection=collection.name, use_selection=False, use_visible=False)
        with _evaluated(collection):
            if kw["use_triangles"]:
                _warn_retriangulation(collection.all_objects)
            bpy.ops.export_scene.fbx(**kw)
    else:
        bpy.ops.object.select_all(action="DESELECT")
        for ob in objects:
            if ob.name in bpy.context.view_layer.objects:
                ob.select_set(True)
        names = sorted(o.name for o in bpy.context.selected_objects if o.type == "MESH")
        skipped = sorted({o.name for o in objects} - set(names))
        if skipped:
            print("[warn] not selectable (hidden or outside the view layer), not exported: " + ", ".join(skipped))
        if not names:
            print("[export] nothing to write for", filepath)
            return []
        bpy.context.view_layer.objects.active = bpy.data.objects[names[0]]
        kw.update(use_selection=True)
        if kw["use_triangles"]:
            _warn_retriangulation([bpy.data.objects[n] for n in names])
        bpy.ops.export_scene.fbx(**kw)
    print("[export] wrote %s: %s" % (filepath, ", ".join(names)))
    return names


def export_kit(out_dir, set_status=False):
    """One FBX per local kit piece collection (named <FAMILY>_<Type>_<Size>_<Variant>) with every mesh in it, hidden
    or not (LODs and <Piece>_COL included), into <out_dir>/<FAMILY>/<Piece>.fbx with Path Mode Strip. Returns
    {fbx path: [object names]}."""
    out_dir = resolve_dir(out_dir)
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    written = {}
    for coll in sorted(bpy.data.collections, key=lambda c: c.name):
        m = PIECE_RE.match(coll.name)
        if coll.library is not None or not m:
            continue
        obs = [o for o in coll.all_objects if o.type == "MESH"]
        if not obs:
            print("[export] %s: no meshes, skipped" % coll.name)
            continue
        for ob in obs:
            _warn_transform(ob, kit=True)
        folder = os.path.join(out_dir, m.group(1))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, coll.name + ".fbx")
        written[path] = _export(path, collection=coll, path_mode=KIT_PATH_MODE)
        if set_status:
            coll["kit_status"] = "exported"
    if set_status and written:
        bpy.context.preferences.filepaths.save_version = 0   # no .blend1 backup beside the KIT file
        bpy.ops.wm.save_mainfile()
    print("[export] kit: %d piece(s) into %s" % (len(written), out_dir))
    return written


def export_selected(export_dir=EXPORT_DIR, mode=MODE, path_mode=PATH_MODE):
    """The interactive modes (see MODE above) on the current selection. Returns {fbx path: [object names]}."""
    out_dir = resolve_dir(export_dir)
    os.makedirs(out_dir, exist_ok=True)
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    selected = [ob for ob in bpy.context.selected_objects if ob.type == "MESH"]
    if not selected:
        print("[export] nothing selected (mesh objects only): nothing written")
        return {}
    for ob in selected:
        _warn_transform(ob)

    def safe(name):
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)

    written = {}
    if mode == "single":
        path = os.path.join(out_dir, SINGLE_NAME + ".fbx")
        written[path] = _export(path, objects=selected, path_mode=path_mode)
    elif mode == "collection":
        groups = {}
        for ob in selected:
            for coll in ob.users_collection:
                groups.setdefault(coll.name, []).append(ob)
        for name, obs in groups.items():
            path = os.path.join(out_dir, safe(name) + ".fbx")
            written[path] = _export(path, objects=obs, path_mode=path_mode)
    else:
        for ob in selected:
            path = os.path.join(out_dir, safe(ob.name) + ".fbx")
            written[path] = _export(path, objects=[ob], path_mode=path_mode)
    bpy.ops.object.select_all(action="DESELECT")
    for ob in selected:
        ob.select_set(True)
    print("[export] done: %d file(s), mode %s, into %s" % (len(written), mode, out_dir))
    return written


def main(argv=None):
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--kit" in argv:
        if "--tangents" in argv:
            print("[export] --tangents is ignored: Unity calculates MikkTSpace tangents (references/fbx-export.md)")
        out = argv[argv.index("--dir") + 1] if "--dir" in argv else EXPORT_DIR
        return export_kit(out, set_status="--set-status" in argv)
    return export_selected()


if not globals().get("BATCH_EXPORT_NO_MAIN"):
    main()
