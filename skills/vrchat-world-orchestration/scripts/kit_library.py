"""Kit library helpers: KIT pieces as collections, linked and placed as collection instances.

Kit rules (naming, pivots, KIT / ASM / MASTER files): the blender-kit-library skill's SKILL.md, or world-spec.md in
vrchat-world-orchestration. This file ships identically in both skills; keep the copies the same
(tools/check_conventions.py in the agent-skills repo checks it).

Host: Blender 4.1+ (bpy), no add-ons. Checked against the Blender 5.2 API (bpy.data.libraries.load, Library.reload,
Collection.instance_offset, PreferencesFilePaths.save_version, wm.read_homefile), 2026-10-17.

Load in Blender:  ns = {}; exec(open(r"<skill>/scripts/kit_library.py", encoding="utf-8").read(), ns)

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

Paths starting with // are relative to the open .blend, as everywhere in Blender.
"""

import json
import math
import os
import re
import sys

import bpy
from mathutils import Matrix, Vector

NAME_RE = re.compile(r"^([A-Z]{2,5})_[A-Za-z0-9]+_(\d+(?:x\d+){0,2}|Free)_[A-Z]\d?$")
ASM_RE = re.compile(r"^ASM_[A-Za-z0-9]+_[A-Z]\d?$")
MAT_RE = re.compile(r"^M_[A-Z]{2,5}_[A-Za-z0-9][A-Za-z0-9_]*$")
EPS = 1e-4
GRID_TOL = 0.01      # modules: how far an extent may be from a whole number of modules (and from one module)
STATUS_ORDER = ("grey", "modelled", "uv", "textured", "exported")   # collection custom property kit_status


def _resolve(path):
    """bpy.path.abspath, refusing "//..." in a file never saved: Blender would resolve it against its current
    directory (often C:\\Windows\\System32 or the install folder, so //../ paths land in C:\\)."""
    if path.startswith("//") and not bpy.data.filepath:
        raise ValueError("%r is relative to the .blend's folder, but this file has never been saved: save it first or "
                         "pass an absolute path" % path)
    return bpy.path.abspath(path)


def _abs(path):
    return _resolve(path).replace("\\", "/").lower()


def new_piece(name, parent=None):
    """Create (or return) the collection for one kit piece, linked under `parent` (default the scene collection)."""
    if not (NAME_RE.match(name) or ASM_RE.match(name)):
        raise ValueError("%r does not follow <FAMILY>_<Type>_<Size>_<Variant> or ASM_<Name>_<Variant>" % name)
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(coll)
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
    """Add a collection instance of `coll` (an empty), rotated `rot_z` degrees about Z, into collection `into`."""
    inst = bpy.data.objects.new(name or coll.name, None)
    inst.instance_type = "COLLECTION"
    inst.instance_collection = coll
    inst.empty_display_size = 0.25
    inst.matrix_world = Matrix.Translation(Vector(location)) @ Matrix.Rotation(math.radians(rot_z), 4, "Z")
    (into or bpy.context.scene.collection).objects.link(inst)
    return inst


def link_piece(path, name, location=(0.0, 0.0, 0.0), rot_z=0.0, into=None, relative=True):
    """Link a piece from a KIT (or assembly from an ASM file) and place one instance of it."""
    return place(link_collection(path, name, relative), location, rot_z, into=into)


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
        issues.append("instance_offset is %s, not zero" % tuple(round(v, 4) for v in coll.instance_offset))

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
                          % tuple(round(v, 3) for v in lo))
        ext = [(hi[i] - lo[i]) / module for i in range(3)]
        grid = [e for e in ext if e > 1.0 - GRID_TOL]       # under one module is thickness: not in the Size token
        want = [int(t) for t in size.split("x")]
        rep["extent_modules"] = [round(e, 3) for e in ext]
        if [round(e) for e in grid] != want or any(abs(e - round(e)) > GRID_TOL for e in grid):
            issues.append("extents %s modules do not match size %s" % ([round(e, 3) for e in ext], size))
    return rep


def audit_kit(module, materials=None):
    """Audit every piece collection in this file at grid `module` metres (the world's grid module: no default, since
    a wrong module fails good pieces and passes mis-sized ones), plus mesh objects that sit outside any piece."""
    if not module or module <= 0:
        raise ValueError("audit_kit needs module=<the grid module in metres>, e.g. 0.5 or 1.0")
    pieces = [c for c in bpy.data.collections if c.library is None and NAME_RE.match(c.name)]
    reps = [audit_piece(c, module, materials) for c in sorted(pieces, key=lambda c: c.name)]
    owned = {o.name for c in pieces for o in c.all_objects}
    stray = [o.name for o in bpy.data.objects if o.library is None and o.type == "MESH" and o.name not in owned]
    odd = [c.name for c in bpy.data.collections
           if c.library is None and not NAME_RE.match(c.name) and not ASM_RE.match(c.name) and c.objects]
    return {"module": module, "pieces": reps, "stray_meshes": stray, "unnamed_collections": odd,
            "missing_libraries": missing_libraries(), "missing_data": missing_ids(found_files_only=True)}


def problems(report):
    """Flat list of readable failures from audit_kit() (empty when the kit passes)."""
    out = ["%s: %s" % (r["piece"], i) for r in report["pieces"] for i in r["issues"]]
    out += ["stray mesh outside any piece collection: %s" % n for n in report["stray_meshes"]]
    out += ["collection with objects but no kit name: %s" % n for n in report["unnamed_collections"]]
    out += ["linked library missing (moved or renamed? relink): %s" % n for n in report.get("missing_libraries", [])]
    out += ["linked data missing (renamed in its file, or moved to another KIT file? re-point the instances): %s" % n
            for n in report.get("missing_data", [])]
    return out


def _flag_values(argv, flag):
    """The values after `flag` up to the next --option."""
    rest = argv[argv.index(flag) + 1:]
    end = next((i for i, a in enumerate(rest) if a.startswith("--")), len(rest))
    return rest[:end]


def _main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
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
