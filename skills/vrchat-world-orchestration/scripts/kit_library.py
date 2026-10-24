"""Kit library helpers: KIT pieces as collections, placed as collection instances, in one MASTER file (the default)
or linked from separate KIT and ASM files.

Kit rules (naming, pivots, the single MASTER layout and the split KIT / ASM / MASTER files): the blender-kit-library
skill's SKILL.md, or world-spec.md in vrchat-world-orchestration. This file ships identically in both skills; keep the
copies the same (tools/check_conventions.py in the agent-skills repo checks it).

Host: Blender 4.1+ (bpy), no add-ons. Checked against the Blender 5.2 API (bpy.data.libraries.load, Library.reload,
Collection.instance_offset, PreferencesFilePaths.save_version, wm.read_homefile, BlendDataLibraries.write,
ID.user_remap), 2026-10-20.

Load in Blender:  ns = {}; exec(open(r"<skill>/scripts/kit_library.py", encoding="utf-8").read(), ns)

Single MASTER (the default layout: pieces under KIT, assemblies under ASM, the layout under the MASTER collection):
    ns["new_master"](r"F:/World/blender/MASTER.blend")       # Blender started with no file: organised, saved
    ns["new_piece"]("EXT_Wall_2x3_A")                         # lands in KIT/KIT_EXT, offset zero
    ns["place_piece"]("EXT_Wall_2x3_A", location=(4, 0, 0), rot_z=90)    # into the MASTER collection
    ns["changes_since"](r"//MASTER.snapshot.json")            # what changed since the agent's last save, by anyone
    ns["save_snapshot"](r"//MASTER.snapshot.json")            # right after each save the agent makes
    ns["checkout"](r"//work/KIT_EXT.blend", ["EXT_Wall_2x3_A"])   # copy pieces out to a work file (live session)
    ns["integrate"](r"//work/KIT_EXT.blend", ["EXT_Wall_2x3_A"])  # bring them back; refuses if they changed meanwhile

Split files (only when the user asked for them):
    ns["new_file"](r"F:/World/blender/kits/KIT_Arch_Exterior.blend")   # Blender started with no file: empty, saved
    ns["new_piece"]("EXT_Wall_2x3_A")                         # KIT file: the piece collection, offset zero
    ns["list_library"](r"//kits/KIT_Arch_Exterior.blend")     # piece and assembly collection names in another file
    inst = ns["link_piece"](r"//kits/KIT_Arch_Exterior.blend", "EXT_Wall_2x3_A", location=(4, 0, 0), rot_z=90)
    ns["reload_libraries"]()                                  # after KIT or ASM files changed on disk
    rep = ns["audit_kit"](module=0.5); ns["problems"](rep)    # KIT file, read-only; module = the grid module in m
    ns["save_file"]()                                         # headless save without a .blend1 backup
    ns["missing_libraries"](); ns["relink"]([r"F:/World/blender/kits", r"F:/World/blender/asm"])   # the live folders

The audit follows each piece's kit_status: UV2 is required from "uv" on, filled material slots from "textured" on;
a piece without kit_status gets every check. The Size token names grid axes only: an axis under one module is
thickness and is skipped (a 2.0 x 0.3 x 3.0 m wall at a 0.5 m module is 4x6). Materials match MAT_RE and the
family (or M_TRIM_) prefix. Missing linked libraries are reported.

From the command line (one line per piece; --json writes the full report; exit 1 on problems, 2 without --module):
    blender -b --factory-startup --python-exit-code 1 KIT_Arch_Exterior.blend --python kit_library.py --
        --audit --module 0.5 [--json report.json]
Repair links after files moved (any order: it repeats passes; saves each file that relinked cleanly, then reopens all
of them; exit 1 if anything is still missing). --renamed is for a renamed file whose collections kept their names
(a KIT file); a renamed assembly needs the rename procedure in SKILL.md instead:
    blender -b --factory-startup --python-exit-code 1 --python kit_library.py -- --relink F:/World/blender/kits
        F:/World/blender/asm --files F:/World/blender/asm/ASM_Stall_A.blend F:/World/blender/MASTER.blend
        [--renamed KIT_Old.blend=KIT_New.blend]
Snapshots and work files, headless on a file nobody has open (exit 1 when --changes finds changes, or --integrate
refuses; --integrate saves MASTER and its snapshot when it integrated):
    blender -b --factory-startup --python-exit-code 1 MASTER.blend --python kit_library.py --
        --changes MASTER.snapshot.json            # or --snapshot MASTER.snapshot.json
    blender -b --factory-startup --python-exit-code 1 MASTER.blend --python kit_library.py --
        --checkout work/KIT_EXT.blend --names EXT_Wall_2x3_A
    blender -b --factory-startup --python-exit-code 1 MASTER.blend --python kit_library.py --
        --integrate work/KIT_EXT.blend --names EXT_Wall_2x3_A [--materials work] [--force]

Paths starting with // are relative to the open .blend, as everywhere in Blender.
"""

import array
import contextlib
import datetime
import hashlib
import json
import math
import os
import re
import subprocess
import sys

import bpy
from mathutils import Matrix, Vector

NAME_RE = re.compile(r"^([A-Z]{2,5})_[A-Za-z0-9]+_(\d+(?:x\d+){0,2}|Free)_[A-Z]\d?$")
ASM_RE = re.compile(r"^ASM_[A-Za-z0-9]+_[A-Z]\d?$")
MAT_RE = re.compile(r"^M_[A-Z]{2,5}_[A-Za-z0-9][A-Za-z0-9_]*$")
EPS = 1e-4
GRID_TOL = 0.01      # modules: how far an extent may be from a whole number of modules (and from one module)
STATUS_ORDER = ("grey", "modelled", "uv", "textured", "exported")   # collection custom property kit_status

# Single MASTER layout: scene["kit_layout"] = "single" (absent or "split": separate KIT and ASM files).
LAYOUT_PROP = "kit_layout"
KIT_ROOT, ASM_ROOT, LAYOUT_ROOT, REF_ROOT = "KIT", "ASM", "MASTER", "REF"
# Collections that only organise: KIT, KIT_<FAMILY>, ASM, MASTER, MASTER_<Zone>, REF, REF_<Name>.
ORGANISER_RE = re.compile(r"^(KIT(_[A-Z]{2,5})?|ASM|MASTER(_[A-Za-z0-9]+)?|REF(_[A-Za-z0-9]+)?)$")
OLD_SUFFIX = "~old"  # integrate() renames the current version of a piece while the new one comes in


def _resolve(path):
    """bpy.path.abspath, refusing "//..." in a file never saved: Blender would resolve it against its current
    directory (often C:\\Windows\\System32 or the install folder, so //../ paths land in C:\\)."""
    if path.startswith("//") and not bpy.data.filepath:
        raise ValueError("%r is relative to the .blend's folder, but this file has never been saved: save it first or "
                         "pass an absolute path" % path)
    return bpy.path.abspath(path)


def _abs(path):
    return _resolve(path).replace("\\", "/").lower()


def is_single(scene=None):
    """True when this file is a single MASTER (KIT and ASM collections inside it), from scene["kit_layout"]."""
    return (scene or bpy.context.scene).get(LAYOUT_PROP) == "single"


def _local(datas, name):
    """The local (not linked) data-block called `name` in `datas` (bpy.data.collections etc.), or None."""
    return next((d for d in datas if d.name == name and d.library is None), None)


def _local_collection(name):
    coll = _local(bpy.data.collections, name)
    if coll is None:
        raise KeyError("no local collection %r in this file" % name)
    return coll


def _child(parent, name):
    """The local collection `name` under `parent`, created if missing (linked under parent if it is elsewhere)."""
    coll = _local(bpy.data.collections, name)
    if coll is None:
        coll = bpy.data.collections.new(name)
    if coll.name not in parent.children:
        parent.children.link(coll)
    return coll


def _layer_collection(coll, lc=None):
    """The view layer's LayerCollection for `coll` (first match), or None."""
    lc = lc or bpy.context.view_layer.layer_collection
    if lc.collection == coll:
        return lc
    for child in lc.children:
        found = _layer_collection(coll, child)
        if found is not None:
            return found
    return None


def _layer_paths(lc, coll, path=()):
    path = path + (lc,)
    if lc.collection == coll:
        yield path
    for child in lc.children:
        yield from _layer_paths(child, coll, path)


@contextlib.contextmanager
def _evaluated(colls):
    """Make every object in colls evaluated by the view layer while it is audited, then restore everything (nothing
    is saved). An object in an excluded collection (a single MASTER's KIT), a collection or object disabled in
    viewports, or a collection outside the scene is not evaluated: its matrix_world is stale (identity after a load,
    measured on Blender 5.2.2) and its bounds leave out its modifiers. Hidden with H or the eye is evaluated anyway."""
    scene, vl = bpy.context.scene, bpy.context.view_layer
    undo = []
    try:
        for coll in colls:
            if coll not in scene.collection.children_recursive:
                scene.collection.children.link(coll)
                undo.append(lambda c=coll: scene.collection.children.unlink(c))
            for path in list(_layer_paths(vl.layer_collection, coll)):
                lcs, stack = list(path[1:]), [path[-1]]
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
        yield
    finally:
        for fn in reversed(undo):
            fn()
        vl.update()


def setup_single_master(scene=None):
    """Organise the open file as a single MASTER: KIT and ASM collections excluded from the view layer (the pieces
    all sit at the origin; instances of them still draw), MASTER for the layout, REF for review aids, and
    scene["kit_layout"] = "single". Safe to run again. Returns {name: collection}."""
    scene = scene or bpy.context.scene
    top = {n: _child(scene.collection, n) for n in (KIT_ROOT, ASM_ROOT, LAYOUT_ROOT, REF_ROOT)}
    for n in (KIT_ROOT, ASM_ROOT):
        lc = _layer_collection(top[n])
        if lc is not None and scene == bpy.context.scene:
            lc.exclude = True
    scene[LAYOUT_PROP] = "single"
    return top


def new_master(filepath):
    """Start a new, empty single MASTER .blend at `filepath` (Blender run with no file), organised and saved."""
    bpy.ops.wm.read_homefile(use_factory_startup=True, use_empty=True)
    setup_single_master()
    return save_file(filepath)


def _default_parent(name):
    """Where a new piece or assembly goes: KIT/KIT_<FAMILY> or ASM in a single MASTER, else the scene collection."""
    scene = bpy.context.scene
    if not is_single(scene):
        return scene.collection
    if ASM_RE.match(name):
        return _child(scene.collection, ASM_ROOT)
    return _child(_child(scene.collection, KIT_ROOT), "%s_%s" % (KIT_ROOT, NAME_RE.match(name).group(1)))


def new_piece(name, parent=None):
    """Create (or return) the collection for one kit piece or assembly, linked under `parent` (default: its family
    collection KIT/KIT_<FAMILY>, or ASM, in a single MASTER; the scene collection in a KIT or ASM file)."""
    if not (NAME_RE.match(name) or ASM_RE.match(name)):
        raise ValueError("%r does not follow <FAMILY>_<Type>_<Size>_<Variant> or ASM_<Name>_<Variant>" % name)
    coll = _local(bpy.data.collections, name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        (parent or _default_parent(name)).children.link(coll)
    coll.instance_offset = (0.0, 0.0, 0.0)
    return coll


def list_library(path):
    """Names of the collections in another .blend that look like kit pieces or assemblies."""
    with bpy.data.libraries.load(path, link=True) as (src, _dst):
        names = list(src.collections)
    return [n for n in names if NAME_RE.match(n) or ASM_RE.match(n)]


def link_collection(path, name, relative=True):
    """Link collection `name` from `path`, reusing it if this file already links it from there."""
    want = _abs(path)
    for coll in bpy.data.collections:
        if coll.name == name and coll.library and _abs(coll.library.filepath) == want:
            return coll
    with bpy.data.libraries.load(path, link=True, relative=relative) as (src, dst):
        if name not in src.collections:
            raise KeyError("no collection %r in %s" % (name, path))
        dst.collections = [name]
    return dst.collections[0]


def place(coll, location=(0.0, 0.0, 0.0), rot_z=0.0, name=None, into=None):
    """Add a collection instance of `coll` (an empty), rotated `rot_z` degrees about Z, into collection `into`
    (default: the MASTER collection in a single MASTER, else the scene collection)."""
    inst = bpy.data.objects.new(name or coll.name, None)
    inst.instance_type = "COLLECTION"
    inst.instance_collection = coll
    inst.empty_display_size = 0.25
    inst.matrix_world = Matrix.Translation(Vector(location)) @ Matrix.Rotation(math.radians(rot_z), 4, "Z")
    scene = bpy.context.scene
    (into or (_child(scene.collection, LAYOUT_ROOT) if is_single(scene) else scene.collection)).objects.link(inst)
    return inst


def link_piece(path, name, location=(0.0, 0.0, 0.0), rot_z=0.0, into=None, relative=True):
    """Link a piece from a KIT (or assembly from an ASM file) and place one instance of it."""
    return place(link_collection(path, name, relative), location, rot_z, into=into)


def place_piece(name, location=(0.0, 0.0, 0.0), rot_z=0.0, into=None):
    """Single MASTER: place one instance of the local piece or assembly `name` (into the MASTER collection, or into
    `into`, such as an assembly's collection)."""
    return place(_local_collection(name), location, rot_z, into=into)


def reload_libraries(paths=None):
    """Reload linked libraries (all, or those whose file is in `paths`). Returns the reloaded file paths."""
    want = {_abs(p) for p in paths} if paths else None
    done = []
    for lib in bpy.data.libraries:
        if want is None or _abs(lib.filepath) in want:
            lib.reload()
            done.append(lib.filepath)
    return done


def missing_libraries():
    """Stored paths of the linked libraries whose file is not on disk (Blender shows placeholders for their data)."""
    return [lib.filepath for lib in bpy.data.libraries if not os.path.exists(bpy.path.abspath(lib.filepath))]


ID_TYPES = ("collections", "objects", "meshes", "materials", "node_groups", "images")


def missing_ids(found_files_only=False):
    """Linked data Blender could not find ("Collection ASM_Stall_A from //asm/ASM_Booth_A.blend"). With
    `found_files_only`, only data missing from library files that exist: data renamed inside its file, such as an
    assembly renamed together with its file, which re-pointing the library cannot bring back."""
    out = []
    for attr in ID_TYPES:
        for data in getattr(bpy.data, attr):
            lib = data.library
            if lib is not None and data.is_missing and not (
                    found_files_only and not os.path.exists(bpy.path.abspath(lib.filepath))):
                out.append("%s %s from %s" % (type(data).__name__, data.name, lib.filepath))
    return out


def _repaired(status):
    return bool(status) and not status.startswith(("fix ", "ambiguous"))


def relink(search_dirs, relative=True, renamed=None):
    """Repair links broken by moved or renamed files, in the open file: point every direct library whose file is
    missing at the .blend of the same file name (or its new name in `renamed`, {"KIT_Old.blend": "KIT_New.blend"},
    for a file whose collections kept their names) found under `search_dirs`, stored relative, and reload it.
    Several files of that name: the one in a folder named like the old one, else the link is left alone. An indirect
    library (linked through an ASM file) is fixed by relinking that ASM file. Save afterwards, unless
    missing_ids(True) lists data still missing (renamed inside its file too: use the rename procedure instead).
    Returns {old stored path: new stored path, None (no file found), "ambiguous: ..." or "fix <ASM file> first"}."""
    found = {}
    for top in search_dirs:
        for base, _dirs, files in os.walk(_resolve(top)):
            for f in files:
                if f.lower().endswith(".blend"):
                    path = os.path.join(base, f)          # one entry per real file, however often it is reached
                    found.setdefault(f.lower(), {}).setdefault(os.path.normcase(os.path.realpath(path)), path)
    renamed = {k.lower(): v.lower() for k, v in (renamed or {}).items()}
    folders = lambda p: [x.lower() for x in os.path.normpath(p).replace("\\", "/").split("/")[-3:-1]]
    out, todo = {}, []
    for lib in list(bpy.data.libraries):
        if lib.parent is not None or os.path.exists(bpy.path.abspath(lib.filepath)):
            continue
        old = lib.filepath
        name = old.replace("\\", "/").split("/")[-1].lower()
        matches = sorted(found.get(renamed.get(name, name), {}).values())
        if len(matches) > 1:                             # keep only one whose parent and grandparent folders match
            same = [m for m in matches if folders(m) == folders(bpy.path.abspath(old))]
            matches = same if len(same) == 1 else matches
        if not matches:
            out[old] = None
        elif len(matches) > 1:
            out[old] = "ambiguous: %s (left alone; point --relink at the folder of the live file)" % ", ".join(matches)
        else:
            path, note = matches[0], ""
            if relative and bpy.data.filepath:
                try:
                    path = bpy.path.relpath(path)
                except ValueError:                       # on another drive: a relative path cannot reach it
                    note = " (stored absolute: on another drive)"
            out[old] = path + note
            todo.append((lib, path))
    for lib, path in todo:              # all paths first: a reload can merge and remove other Library structs
        lib.filepath = path
    for lib, _path in todo:
        try:
            lib.reload()
        except ReferenceError:          # merged into a library an earlier reload brought in
            pass
    for lib in list(bpy.data.libraries):
        if lib.parent is not None and not os.path.exists(bpy.path.abspath(lib.filepath)):
            out[lib.filepath] = "fix %s first" % lib.parent.filepath
    return out


def relink_files(blend_files, search_dirs, renamed=None):
    """Relink several files (Blender run with no file), in passes until a pass repairs nothing, so the order of the
    files does not matter (an assembly placed by another file may be fixed in either pass). A file is saved only
    when it relinked with no data left missing. Finally reopens every file. Returns ({file: [what is still missing]},
    [(file, relink() result, data missing after its reload)] for every pass)."""
    log = []
    for _pass in range(len(blend_files) + 1):
        changed = False
        for path in blend_files:
            bpy.ops.wm.open_mainfile(filepath=path)
            result = relink(search_dirs, renamed=renamed)
            lost = missing_ids(found_files_only=True)
            log.append((path, result, lost))
            if any(_repaired(v) for v in result.values()) and not lost:
                save_file()
                changed = True
        if not changed:
            break
    still = {}
    for path in blend_files:
        bpy.ops.wm.open_mainfile(filepath=path)
        still[path] = missing_libraries() + missing_ids()
    return still, log


def save_file(filepath=None):
    """Save the open file (or save it as `filepath`, creating its folder) without a .blend1 backup: save_version 0 for
    the save only."""
    prefs = bpy.context.preferences.filepaths
    old = prefs.save_version
    prefs.save_version = 0
    try:
        if filepath:
            os.makedirs(os.path.dirname(os.path.abspath(_resolve(filepath))), exist_ok=True)
            bpy.ops.wm.save_as_mainfile(filepath=filepath)
        else:
            bpy.ops.wm.save_mainfile()
    finally:
        prefs.save_version = old
    return bpy.data.filepath


def new_file(filepath):
    """Start a new, empty .blend and save it at `filepath` (folders created), so later links can be stored relative
    to it. Loads the factory startup file emptied (no cube, camera, light or Collection); preferences are untouched."""
    bpy.ops.wm.read_homefile(use_factory_startup=True, use_empty=True)
    return save_file(filepath)


# --- Snapshots: what the file held when the agent last saved it, to find what anyone changed since ---------------

SNAPSHOT_VERSION = 1
UI_PROPS = {"rna_type", "name", "location", "location_absolute", "width", "height", "dimensions", "select",
            "show_options", "show_preview", "show_texture", "hide", "color", "use_custom_color", "label", "parent",
            "warning_propagation", "color_tag", "is_active_output", "is_override_data_editable", "show_expanded",
            "show_in_editmode", "show_on_cage", "show_viewport", "show_render", "is_active", "persistent_uid",
            "is_override_data", "use_pin_to_last", "execution_time", "show_group_selector"}


ID_PROPS = {p.identifier for p in bpy.types.ID.bl_rna.properties}


def _plain(value):
    """A JSON-safe, comparable form of a property value: numbers rounded to 0.1 mm, ID data by name."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return round(value, 4) + 0.0
    if isinstance(value, bpy.types.ID):
        return value.name
    if isinstance(value, (set, frozenset)):
        return sorted(str(v) for v in value)
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    elif hasattr(value, "to_list"):
        value = value.to_list()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    try:
        return [_plain(v) for v in value]
    except TypeError:
        return str(value)


def _custom(owner):
    """An ID's or modifier's own custom properties, without the property groups add-ons register on the type (Cycles
    and the like appear there once the UI touches them, which is not an edit)."""
    registered = owner.bl_rna.properties
    return _plain({k: v for k, v in owner.items() if k not in registered})


def _rna(struct):
    """The settings of a material, modifier or node: every plain property, ID pointers by name, UI state and the
    session bookkeeping every ID has (session_uid, users, tags) left out."""
    out = {}
    skip = ID_PROPS if isinstance(struct, bpy.types.ID) else ()
    for p in struct.bl_rna.properties:
        ident = p.identifier
        if ident in UI_PROPS or ident in skip or ident.startswith("bl_") or p.type == "COLLECTION":
            continue
        try:
            v = getattr(struct, ident)
        except (AttributeError, RuntimeError):
            continue
        if p.type == "POINTER" and not isinstance(v, bpy.types.ID):
            continue
        out[ident] = _plain(v)
    if hasattr(struct, "items"):
        out["[custom]"] = _custom(struct)
    return out


def _digest(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _floats_digest(seq, attr, width, scale):
    """Digest of a foreach_get float attribute, quantised to 1/scale (0.1 mm for positions)."""
    buf = array.array("f", [0.0]) * (len(seq) * width)
    if len(seq):
        seq.foreach_get(attr, buf)
    return hashlib.sha1(array.array("q", (int(round(v * scale)) for v in buf)).tobytes()).hexdigest()[:16]


def _mesh_print(me):
    """Counts and digests of a mesh's shape, faces and UV layers: any edit to them changes this."""
    loops = array.array("i", [0]) * len(me.loops)
    if len(me.loops):
        me.loops.foreach_get("vertex_index", loops)
    sizes = array.array("i", [0]) * len(me.polygons)
    if len(me.polygons):
        me.polygons.foreach_get("loop_total", sizes)
    return {"verts": len(me.vertices), "edges": len(me.edges), "faces": len(me.polygons),
            "co": _floats_digest(me.vertices, "co", 3, 1e4),
            "topology": hashlib.sha1(loops.tobytes() + sizes.tobytes()).hexdigest()[:16],
            "uv": {uv.name: _floats_digest(uv.uv, "vector", 2, 1e5) for uv in me.uv_layers},
            "attributes": sorted(a.name for a in me.attributes if not a.name.startswith(".")),   # .select_vert...
            "materials": [m.name if m else None for m in me.materials]}


def _material_print(mat):
    nodes = []
    if mat.node_tree is not None:
        for n in sorted(mat.node_tree.nodes, key=lambda n: n.name):
            nodes.append([n.name, n.bl_idname, _rna(n),
                          [[s.identifier, _plain(getattr(s, "default_value", None))] for s in n.inputs
                           if not s.is_linked]])
        nodes.append(sorted([l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier]
                            for l in mat.node_tree.links))
    return {"settings": _digest(_rna(mat)), "nodes": _digest(nodes)}


def _trees(names):
    """The local collections named in `names` and every collection inside them."""
    out = []
    for n in names:
        coll = _local_collection(n)
        for c in [coll] + list(coll.children_recursive):
            if c not in out:
                out.append(c)
    return out


def snapshot(collections=None):
    """What the file holds now, as plain JSON-safe data: every local collection (parents, children, objects, custom
    properties), object (its own transform and parent, instanced collection, mesh digest, materials, modifiers) and
    material (settings and node digests), plus each scene's top level. With `collections` (names, possibly none),
    only those collections, everything inside them and the materials they use. Compare two with diff_snapshots().
    View-layer state (excluded, hidden in the view layer, selection) is left out: it is how the user looks, not what
    is there."""
    if collections is not None:
        colls = _trees(collections)
        objs = {o for c in colls for o in c.objects if o.library is None}
        scenes = []
    else:
        colls = [c for c in bpy.data.collections if c.library is None]
        objs = {o for o in bpy.data.objects if o.library is None and o.users}
        scenes = list(bpy.data.scenes)
    parents = {}
    for c in bpy.data.collections:
        for child in c.children:
            parents.setdefault(child.name, []).append(c.name)
    for sc in bpy.data.scenes:
        for child in sc.collection.children:
            parents.setdefault(child.name, []).append("<scene %s>" % sc.name)
    snap = {"version": SNAPSHOT_VERSION, "file": bpy.data.filepath, "collections": {}, "objects": {},
            "materials": {}, "scenes": {}}
    for c in colls:
        snap["collections"][c.name] = {
            "parents": sorted(parents.get(c.name, [])), "children": sorted(x.name for x in c.children),
            "objects": sorted(o.name for o in c.objects), "props": _custom(c),
            "instance_offset": _plain(c.instance_offset), "hidden": [c.hide_viewport, c.hide_render]}
    mats = set()
    for o in objs:
        rec = {"type": o.type, "parent": o.parent.name if o.parent else None,
               # matrix_basis and the parent inverse are current at once; matrix_world waits for an evaluation
               "matrix": _plain([list(r) for r in o.matrix_basis] + [list(r) for r in o.matrix_parent_inverse]),
               "props": _custom(o),
               "instance": o.instance_collection.name if o.instance_type == "COLLECTION" and o.instance_collection
               else None,
               "data": o.data.name if o.data is not None else None,
               "materials": [s.material.name if s.material else None for s in o.material_slots],
               "modifiers": [[m.name, m.type, _digest(_rna(m))] for m in o.modifiers],
               "hidden": [o.hide_viewport, o.hide_render]}
        if o.type == "MESH":
            rec["mesh"] = _mesh_print(o.data)
        snap["objects"][o.name] = rec
        mats.update(s.material for s in o.material_slots if s.material is not None)
    if collections is None:
        mats.update(m for m in bpy.data.materials if m.library is None and m.users)
    for m in mats:
        if m.library is None:
            snap["materials"][m.name] = _material_print(m)
    for sc in scenes:
        snap["scenes"][sc.name] = {"children": sorted(c.name for c in sc.collection.children),
                                   "objects": sorted(o.name for o in sc.collection.objects),
                                   "props": _custom(sc)}
    return json.loads(json.dumps(snap, sort_keys=True))      # tuples to lists, as a saved snapshot reads back


def diff_snapshots(old, new):
    """What changed from `old` to `new` (snapshot() results or saved snapshots): a list of {kind, name, change
    ("added", "removed" or "changed"), fields}. A renamed thing shows as one removed and one added."""
    out = []
    for kind in ("scenes", "collections", "objects", "materials"):
        a, b = old.get(kind, {}), new.get(kind, {})
        for name in sorted(set(a) | set(b)):
            if name not in a:
                out.append({"kind": kind[:-1], "name": name, "change": "added", "fields": []})
            elif name not in b:
                out.append({"kind": kind[:-1], "name": name, "change": "removed", "fields": []})
            else:
                fields = sorted(k for k in set(a[name]) | set(b[name]) if a[name].get(k) != b[name].get(k))
                if fields:
                    out.append({"kind": kind[:-1], "name": name, "change": "changed", "fields": fields})
    return out


def describe(diff):
    """Readable lines for a diff_snapshots() result."""
    return ["%s %s %s%s" % (d["kind"], d["name"], d["change"], (": " + ", ".join(d["fields"])) if d["fields"] else "")
            for d in diff]


def save_snapshot(path, snap=None):
    """Write snapshot() (or `snap`) to `path` as JSON, creating its folder. Call it right after each save the agent
    makes, so the next changes_since() shows only what happened after."""
    path = _resolve(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    snap = snap if snap is not None else snapshot()
    snap["at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=1, sort_keys=True)
    return path


def load_snapshot(path):
    with open(_resolve(path), encoding="utf-8") as f:
        return json.load(f)


def changes_since(path):
    """diff_snapshots(saved snapshot at `path`, the file now): what changed since the agent's last save (by the user,
    another agent or an unsaved session). No snapshot yet: None, so the caller records a baseline first."""
    if not os.path.exists(_resolve(path)):
        return None
    return diff_snapshots(load_snapshot(path), snapshot())


# --- Work files: copy pieces out of a single MASTER, work on them anywhere, bring them back -------------------------

def _checkout_record(work_path):
    return os.path.splitext(_resolve(work_path))[0] + ".checkout.json"


# Run on the freshly written work file by checkout(): link its root collections into the one scene, drop the fake
# users the write needed, save without a .blend1 backup.
_ADOPT = """import bpy
roots = [c for c in bpy.data.collections if c.library is None and c.use_fake_user]
inner = {x for c in roots for x in c.children_recursive}
for c in roots:
    c.use_fake_user = False
    if c not in inner:
        bpy.context.scene.collection.children.link(c)
bpy.context.scene.name = "Scene"
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_mainfile()
"""


def checkout(work_path, names, blender=None):
    """Write the named local piece or assembly collections (with everything they use) to `work_path`, a .blend with
    them linked into its one scene and in its view layer, so any script that works on a KIT file works on it. Also
    writes <work>.checkout.json with a snapshot of those collections, which integrate() compares against. The open
    file is neither changed nor saved. A short headless Blender (`blender`, default this one) links the collections
    into the work file's scene: Blender 5.2.2 crashes writing a scene with BlendDataLibraries.write. Name the work
    file KIT_<label>.blend so tools that read the role from the file name treat it as a kit file."""
    colls = [_local_collection(n) for n in names]
    path = _resolve(work_path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    bpy.data.libraries.write(path, set(colls), path_remap="RELATIVE_ALL", fake_user=True)
    run = subprocess.run([blender or bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1", path,
                          "--python-expr", _ADOPT], capture_output=True, text=True, timeout=600)
    if run.returncode != 0:
        raise RuntimeError("could not set up the work file %s: %s" % (path, (run.stdout + run.stderr)[-2000:]))
    with open(_checkout_record(work_path), "w", encoding="utf-8") as f:
        json.dump({"source": bpy.data.filepath, "names": list(names), "snapshot": snapshot(names),
                   "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, f, indent=1)
    return path


def _base(name):
    m = re.match(r"^(.*)\.\d{3,}$", name)
    return m.group(1) if m else name


def _remove_tree(coll):
    """Delete a local collection, the collections inside it and the objects only they hold."""
    tree = [coll] + list(coll.children_recursive)
    for ob in {o for c in tree for o in c.objects}:
        if all(c in tree for c in ob.users_collection):
            bpy.data.objects.remove(ob)
    for c in reversed(tree):
        bpy.data.collections.remove(c)


def integrate(work_path, names, materials="master", force=False):
    """Bring the named collections back from a work file into this single MASTER, in place: every instance of the
    old version (in MASTER and in assemblies) now shows the new one, and its parent collection keeps it. A name not
    in this file yet is added under its family collection (or ASM). Refuses (RuntimeError) when those collections
    changed here since checkout() wrote <work>.checkout.json, unless force=True: someone edited them meanwhile.
    materials: "master" keeps this file's materials, node groups and images of the same name (the work file's are
    dropped), "work" replaces them with the work file's (a texturing task). Other data the work file carried along
    (pieces an assembly uses) is mapped back to this file's own copy, or added when this file has none. Save
    afterwards. Returns {replaced, added, kept, dropped, materials}."""
    if materials not in ("master", "work"):
        raise ValueError("materials must be 'master' or 'work'")
    path = _resolve(work_path)
    record = _checkout_record(work_path)
    present = [n for n in names if _local(bpy.data.collections, n) is not None]
    if os.path.exists(record) and not force:
        with open(record, encoding="utf-8") as f:
            checked = json.load(f)
        base = checked["snapshot"]
        still = [n for n in checked["names"] if _local(bpy.data.collections, n) is not None]
        moved = describe(diff_snapshots(base, snapshot(still)))
        if moved:
            raise RuntimeError("changed in this file since checkout, so integrating would overwrite it: %s. Check "
                               "it out again and redo the work on it, or ask whoever changed it (force=True "
                               "overwrites)" % "; ".join(moved))
    with bpy.data.libraries.load(path, link=False) as (src, _dst):
        lacking = [n for n in names if n not in src.collections]
    if lacking:
        raise KeyError("not in %s: %s" % (path, ", ".join(lacking)))
    types = ("collections", "objects", "meshes", "materials", "node_groups", "images")
    before = {t: {d.as_pointer() for d in getattr(bpy.data, t)} for t in types}
    olds = {}
    for n in present:                     # out of the way, so the new versions arrive under their own names
        old = _local_collection(n)
        tree = [old] + list(old.children_recursive)
        for ob in {o for c in tree for o in c.objects}:
            if all(c in tree for c in ob.users_collection):
                if ob.data is not None and ob.data.users == 1 and ob.data.library is None:
                    ob.data.name += OLD_SUFFIX
                ob.name += OLD_SUFFIX
        for c in tree:
            c.name += OLD_SUFFIX
        olds[n] = old
    with bpy.data.libraries.load(path, link=False) as (_src, dst):
        dst.collections = list(names)
    new = {n: c for n, c in zip(names, dst.collections)}
    added = {t: [d for d in getattr(bpy.data, t) if d.as_pointer() not in before[t]] for t in types}
    fresh = {t: {d.as_pointer() for d in added[t]} for t in types}     # pointers stay valid after a removal
    rep = {"replaced": [], "added": [], "kept": [], "dropped": [], "materials": []}
    for n, coll in new.items():
        if coll.name != n:
            coll.name = n
        if n in olds:
            olds[n].user_remap(coll)      # parents' children and every instance now point at the new version
            _remove_tree(olds[n])
            rep["replaced"].append(n)
        else:
            _default_parent(n).children.link(coll)
            rep["added"].append(n)
    keep = set()
    for coll in new.values():
        for c in [coll] + list(coll.children_recursive):
            keep.add(c.as_pointer())
            for ob in c.objects:
                keep.add(ob.as_pointer())
                if ob.data is not None:
                    keep.add(ob.data.as_pointer())
    for coll in [c for c in added["collections"] if c.as_pointer() not in keep]:
        try:
            mine = _local(bpy.data.collections, _base(coll.name))
        except ReferenceError:            # inside a copy removed just before
            continue
        if mine is not None and mine != coll:     # a piece an assembly uses: this file's own copy wins
            coll.user_remap(mine)
            rep["kept"].append(mine.name)
            _remove_tree(coll)
        elif NAME_RE.match(_base(coll.name)) or ASM_RE.match(_base(coll.name)):
            coll.name = _base(coll.name)  # a new piece only the work file has, used by an assembly from it
            if not any(coll in list(p.children) for p in list(bpy.data.collections) +
                       [sc.collection for sc in bpy.data.scenes]):
                _default_parent(coll.name).children.link(coll)
            rep["added"].append(coll.name)
    for t in ("materials", "node_groups", "images"):
        for d in added[t]:
            name = d.name
            mine = next((x for x in getattr(bpy.data, t) if x.name == _base(name) and x.library is None
                         and x.as_pointer() not in fresh[t]), None)
            if mine is None:
                continue
            if materials == "work":
                mine.user_remap(d)
                getattr(bpy.data, t).remove(mine)
                d.name = _base(name)
                if t == "materials":
                    rep["materials"].append("%s replaced from the work file" % d.name)
            else:
                d.user_remap(mine)
                getattr(bpy.data, t).remove(d)
                if t == "materials":
                    rep["materials"].append("%s kept (this file's)" % mine.name)
    for t in ("meshes", "materials", "node_groups", "images"):    # left behind by removed objects and copies
        for d in list(getattr(bpy.data, t)):
            if d.library is None and d.users == 0 and (d.name.endswith(OLD_SUFFIX) or d.as_pointer() in fresh[t]):
                rep["dropped"].append("%s %s" % (t[:-1], d.name))
                getattr(bpy.data, t).remove(d)
    if os.path.exists(record):            # integrated: the record now guards this version, so a second integrate of
        with open(record, encoding="utf-8") as f:     # the same file, or of a later edit of it, still refuses only
            checked = json.load(f)                    # when someone changed these collections here in between
        names_now = [n for n in dict.fromkeys(list(checked["names"]) + list(names))
                     if _local(bpy.data.collections, n) is not None]
        checked.update(names=names_now, snapshot=snapshot(names_now))
        with open(record, "w", encoding="utf-8") as f:
            json.dump(checked, f, indent=1)
    return rep


def _is_identity(mw):
    return all(abs(mw[i][j] - (1.0 if i == j else 0.0)) < EPS for i in range(4) for j in range(4))


def _bounds(objs):
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for ob in objs:
        for corner in ob.bound_box:
            p = ob.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
    return lo, hi


def audit_piece(coll, module, materials=None):
    """Report for one piece collection at grid `module` metres. materials: allowed name prefixes (default
    M_<FAMILY>_ and M_TRIM_)."""
    rep = {"piece": coll.name, "issues": []}
    issues = rep["issues"]
    m = NAME_RE.match(coll.name)
    if not m:
        issues.append("name does not match <FAMILY>_<Type>_<Size>_<Variant>")
        return rep
    family, size = m.group(1), m.group(2)
    prefixes = tuple(materials or ("M_%s_" % family, "M_TRIM_"))
    if Vector(coll.instance_offset).length > EPS:
        issues.append("instance_offset is %s, not zero" % (tuple(round(v, 4) for v in coll.instance_offset),))

    objs = list(coll.all_objects)
    meshes = [o for o in objs if o.type == "MESH"]
    render = [o for o in meshes if not o.name.endswith("_COL")]
    if not render:
        issues.append("no render mesh")
        return rep
    for ob in objs:
        if not _is_identity(ob.matrix_world):
            issues.append("%s: transform is not identity (origin must be the piece pivot, rotation/scale applied)"
                          % ob.name)
    # Pipeline stages add UV2 (kit_status "uv") and family materials ("textured"); before that, a greybox or freshly
    # modelled piece is not expected to have them. Pieces without kit_status get every check.
    status = coll.get("kit_status")
    rep["kit_status"] = status
    stage = STATUS_ORDER.index(status) if status in STATUS_ORDER else len(STATUS_ORDER)
    for ob in render:
        if stage >= STATUS_ORDER.index("uv") and len(ob.data.uv_layers) < 2:
            issues.append("%s: no UV2 (lightmap) layer" % ob.name)
        for slot in ob.material_slots:
            if slot.material is None:
                if stage >= STATUS_ORDER.index("textured"):
                    issues.append("%s: empty material slot" % ob.name)
            elif not MAT_RE.match(slot.material.name):
                issues.append("%s: material %s is not named M_<FAMILY>_<Name> (letters, digits, underscores; a .001 "
                              "suffix is a duplicate to merge)" % (ob.name, slot.material.name))
            elif not slot.material.name.startswith(prefixes):
                issues.append("%s: material %s outside %s" % (ob.name, slot.material.name, "/".join(prefixes)))

    lo, hi = _bounds(render)
    rep["bounds_m"] = [round(v, 4) for v in (*lo, *hi)]
    if size != "Free":
        if any(abs(v) > 0.01 for v in lo):
            issues.append("min corner %s is not at the origin (pivot must be bottom-left)"
                          % (tuple(round(v, 3) for v in lo),))
        ext = [(hi[i] - lo[i]) / module for i in range(3)]
        grid = [e for e in ext if e > 1.0 - GRID_TOL]       # under one module is thickness: not in the Size token
        want = [int(t) for t in size.split("x")]
        rep["extent_modules"] = [round(e, 3) for e in ext]
        if [round(e) for e in grid] != want or any(abs(e - round(e)) > GRID_TOL for e in grid):
            issues.append("extents %s modules do not match size %s" % ([round(e, 3) for e in ext], size))
    return rep


def _single_layout_problems(pieces):
    """Single MASTER: pieces under KIT, assemblies under ASM, KIT and ASM excluded from the view layer."""
    out = []
    roots = {n: _local(bpy.data.collections, n) for n in (KIT_ROOT, ASM_ROOT, LAYOUT_ROOT)}
    for n, coll in roots.items():
        if coll is None:
            out.append("no %s collection (setup_single_master() makes it)" % n)
    under = {n: set(c.children_recursive) if c else set() for n, c in roots.items()}
    out += ["%s is not inside KIT" % c.name for c in pieces if c not in under[KIT_ROOT]]
    out += ["%s is not inside ASM" % c.name for c in bpy.data.collections
            if c.library is None and ASM_RE.match(c.name) and c not in under[ASM_ROOT]]
    for n in (KIT_ROOT, ASM_ROOT):
        lc = _layer_collection(roots[n]) if roots[n] else None
        if lc is not None and not lc.exclude:
            out.append("%s is not excluded from the view layer, so its pieces show at the origin in the layout" % n)
    return out


def audit_kit(module, materials=None):
    """Audit every piece collection in this file at grid `module` metres (the world's grid module: no default, since
    a wrong module fails good pieces and passes mis-sized ones), plus mesh objects that sit outside any piece (REF
    review aids aside). In a single MASTER, also where pieces and assemblies sit (`layout`)."""
    if not module or module <= 0:
        raise ValueError("audit_kit needs module=<the grid module in metres>, e.g. 0.5 or 1.0")
    pieces = [c for c in bpy.data.collections if c.library is None and NAME_RE.match(c.name)]
    with _evaluated(pieces):                  # excluded or disabled pieces audited as they export
        reps = [audit_piece(c, module, materials) for c in sorted(pieces, key=lambda c: c.name)]
    owned = {o.name for c in pieces for o in c.all_objects}
    refs = [c for c in bpy.data.collections if c.library is None and re.match(r"^REF(_|$)", c.name)]
    owned |= {o.name for c in refs for o in c.all_objects}
    stray = [o.name for o in bpy.data.objects if o.library is None and o.type == "MESH" and o.name not in owned]
    odd = [c.name for c in bpy.data.collections
           if c.library is None and not NAME_RE.match(c.name) and not ASM_RE.match(c.name)
           and not ORGANISER_RE.match(c.name) and c not in {x for r in refs for x in r.children_recursive}
           and c.objects]
    rep = {"module": module, "pieces": reps, "stray_meshes": stray, "unnamed_collections": odd,
           "missing_libraries": missing_libraries(), "missing_data": missing_ids(found_files_only=True)}
    if is_single():
        rep["layout"] = _single_layout_problems(pieces)
    return rep


def problems(report):
    """Flat list of readable failures from audit_kit() (empty when the kit passes)."""
    out = ["%s: %s" % (r["piece"], i) for r in report["pieces"] for i in r["issues"]]
    out += ["stray mesh outside any piece collection: %s" % n for n in report["stray_meshes"]]
    out += ["collection with objects but no kit name: %s" % n for n in report["unnamed_collections"]]
    out += ["single MASTER: %s" % n for n in report.get("layout", [])]
    out += ["linked library missing (moved or renamed? relink): %s" % n for n in report.get("missing_libraries", [])]
    out += ["linked data missing (renamed in its file, or moved to another KIT file? re-point the instances): %s" % n
            for n in report.get("missing_data", [])]
    return out


def _flag_values(argv, flag):
    """The values after `flag` up to the next --option."""
    rest = argv[argv.index(flag) + 1:]
    end = next((i for i, a in enumerate(rest) if a.startswith("--")), len(rest))
    return rest[:end]


def _work_cli(argv):
    """--snapshot, --changes, --checkout and --integrate on the open file. Returns an exit code, or None."""
    if "--snapshot" in argv:
        print("[kit_library] snapshot written: %s" % save_snapshot(argv[argv.index("--snapshot") + 1]))
        return 0
    if "--changes" in argv:
        diff = changes_since(argv[argv.index("--changes") + 1])
        if diff is None:
            print("[kit_library] no snapshot at %s: nothing to compare with (write one with --snapshot)"
                  % argv[argv.index("--changes") + 1])
            return 1
        for line in describe(diff):
            print("[kit_library] changed since the snapshot: %s" % line)
        print("[kit_library] %d change(s) since the snapshot" % len(diff))
        return 1 if diff else 0
    names = _flag_values(argv, "--names") if "--names" in argv else []
    if "--checkout" in argv:
        print("[kit_library] checked out %s to %s" % (", ".join(names),
                                                     checkout(argv[argv.index("--checkout") + 1], names)))
        return 0
    if "--integrate" in argv:
        work = argv[argv.index("--integrate") + 1]
        how = argv[argv.index("--materials") + 1] if "--materials" in argv else "master"
        try:
            rep = integrate(work, names, materials=how, force="--force" in argv)
        except (RuntimeError, KeyError) as exc:
            print("[kit_library] NOT INTEGRATED: %s" % exc)
            return 1
        for k in ("replaced", "added", "kept", "materials", "dropped"):
            if rep[k]:
                print("[kit_library] %s: %s" % (k, ", ".join(rep[k])))
        save_file()
        snap = os.path.splitext(bpy.data.filepath)[0] + ".snapshot.json"
        print("[kit_library] saved %s and %s" % (bpy.data.filepath, save_snapshot(snap)))
        return 0
    return None


def _main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    code = _work_cli(argv)
    if code is not None:
        if bpy.app.background:
            sys.exit(code)
        return
    if "--relink" in argv:
        dirs = _flag_values(argv, "--relink")
        renamed = dict(v.split("=", 1) for v in _flag_values(argv, "--renamed")) if "--renamed" in argv else None
        if "--files" in argv:
            still, log = relink_files(_flag_values(argv, "--files"), dirs, renamed)
        else:                                   # the open file only
            result = relink(dirs, renamed=renamed)
            lost = missing_ids(found_files_only=True)
            log = [(bpy.data.filepath, result, lost)]
            if any(_repaired(v) for v in result.values()) and not lost:
                save_file()
            still = {bpy.data.filepath: missing_libraries() + missing_ids()}
        for path, result, lost in log:
            for old, new in sorted(result.items()):
                print("[kit_library] %s: relink %s -> %s" % (os.path.basename(path), old,
                                                             new or "NOT FOUND under " + ", ".join(dirs)))
            for item in lost:
                print("[kit_library] %s: NOT SAVED, %s is still missing: its file was found but the data is not in "
                      "it (renamed, or moved to another file: an assembly renamed with its file, a piece moved to "
                      "another KIT file?). Use the rename procedure: link the collection from its new file and "
                      "re-point the instances" % (os.path.basename(path), item))
        for path, missing in still.items():
            for item in missing:
                print("[kit_library] %s still missing: %s" % (os.path.basename(path), item))
        print("[kit_library] %d file(s) checked after relinking, %d with something still missing"
              % (len(still), sum(1 for m in still.values() if m)))
        if bpy.app.background and "--audit" not in argv:
            sys.exit(1 if any(still.values()) else 0)
    if "--audit" not in argv:
        return
    if "--module" not in argv:
        print("[kit_library] --module <grid module in metres> is required (the world's grid, e.g. 0.5 or 1.0)")
        if bpy.app.background:
            sys.exit(2)
        return
    module = float(argv[argv.index("--module") + 1])
    rep = audit_kit(module)
    for r in rep["pieces"]:
        print("%-32s %s" % (r["piece"], "ok" if not r["issues"] else "; ".join(r["issues"])))
    probs = problems(rep)
    for p in probs[len([i for r in rep["pieces"] for i in r["issues"]]):]:
        print(p)
    if "--json" in argv:
        with open(argv[argv.index("--json") + 1], "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)
    print("[kit_library] %d piece(s), %d problem(s) at a %g m module" % (len(rep["pieces"]), len(probs), module))
    if bpy.app.background:
        sys.exit(1 if probs else 0)


if __name__ == "__main__":
    _main()
