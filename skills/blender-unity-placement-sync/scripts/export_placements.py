"""Dump a Blender layout's placements to JSON, and apply a merge plan back to it.

Host: Blender 4.1+ (bpy), no add-ons. Pairs with placement_merge.py (plain Python) and PlacementSync.cs (Unity).

A placement is a collection instance: an empty with instance_type COLLECTION, usually a linked KIT piece or ASM
assembly. Its stable id lives in the custom property `placement_id` on that empty, so renames, re-parenting and moving
it between collections never lose it. Transforms are written in Unity space (left-handed, Y up, metres) relative to
the world origin, which is the scope root.

Command line (the usual way; one writer per .blend, so not while someone has the file open and unsaved):
    blender -b MASTER.blend --python export_placements.py -- dump  --dir placements --scope MASTER
                                                         [--libraries "kits/*.blend" "asm/*.blend"]
    blender -b MASTER.blend --python export_placements.py -- apply --dir placements --scope MASTER
                                                         [--libraries ...] [--no-save]

From a live Blender (Blender MCP execute_blender_code):
    ns = {}; exec(open(r"<skill>/scripts/export_placements.py", encoding="utf-8").read(), ns)
    ns["dump"](r"F:/World/placements", "MASTER", libraries=[r"F:/World/blender/kits/*.blend"])
    ns["apply"](r"F:/World/placements", "MASTER", libraries=[...])        # then save the file yourself

dump writes <dir>/<scope>.blender.json: every placement, plus "assets", the collection names this file links or
could link from --libraries (so the merge knows which Unity-side additions Blender can take). apply reads
<dir>/<scope>.plan.blender.json and does assign, delete, update, create in that order; anything it cannot do
(an asset it cannot find) is printed and makes the exit code 1, so the commit step will refuse.
--libraries globs are relative to the .blend file's folder unless absolute.
"""

import glob
import json
import os
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

PROP = "placement_id"

# Blender (right-handed, Z up) -> Unity (left-handed, Y up), matching the FBX exporter's -Z forward / Y up with
# Use Space Transform on: Unity = (-x, z, -y). Verified by the round-trip test in ../SKILL.md.
C = Matrix(((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)))
CT = C.transposed()


def to_unity(mw):
    loc, rot, scl = mw.decompose()
    pos = C @ loc
    q = (C @ rot.to_matrix() @ CT).to_quaternion()
    return [pos.x, pos.y, pos.z], [q.x, q.y, q.z, q.w], [scl.x, scl.z, scl.y]


def from_unity(pos, rot, scl):
    loc = CT @ Vector(pos)
    r = CT @ Quaternion((rot[3], rot[0], rot[1], rot[2])).normalized().to_matrix() @ C
    s = Vector((scl[0], scl[2], scl[1]))
    return Matrix.LocRotScale(loc, r.to_quaternion(), s)


def placements(scene=None):
    """Local collection-instance empties in the scene (instances inside linked data are not placements here)."""
    scene = scene or bpy.context.scene
    return [o for o in scene.objects
            if o.library is None and o.instance_type == "COLLECTION" and o.instance_collection is not None]


def _lib_files(libraries):
    base = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.getcwd()
    out = []
    for pattern in libraries or []:
        pattern = bpy.path.abspath(pattern)
        if not os.path.isabs(pattern):
            pattern = os.path.join(base, pattern)
        out += sorted(glob.glob(pattern))
    return [p for p in out if os.path.abspath(p) != os.path.abspath(bpy.data.filepath or "")]


def _library_index(libraries):
    """collection name -> .blend path, from the --libraries files."""
    index = {}
    for path in _lib_files(libraries):
        with bpy.data.libraries.load(path, link=True) as (src, _dst):
            for name in src.collections:
                index.setdefault(name, path)
    return index


def _collection(name, index):
    for coll in bpy.data.collections:
        if coll.name == name and coll.library is not None:
            return coll
    if name in index:
        with bpy.data.libraries.load(index[name], link=True, relative=True) as (src, dst):
            dst.collections = [name]
        return dst.collections[0]
    coll = bpy.data.collections.get(name)       # a local collection (e.g. in an ASM file under construction)
    return coll


def dump(directory, scope, libraries=None):
    items = []
    for ob in placements():
        pos, rot, scl = to_unity(ob.matrix_world)
        items.append({"id": str(ob.get(PROP, "")), "asset": ob.instance_collection.name,
                      "pos": pos, "rot": rot, "scl": scl, "key": ob.name})
    assets = {c.name for c in bpy.data.collections if c.library is not None}
    assets |= set(_library_index(libraries))
    assets |= {i["asset"] for i in items}
    os.makedirs(directory, exist_ok=True)
    out = os.path.join(directory, "%s.blender.json" % scope)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"scope": scope, "side": "blender", "file": bpy.data.filepath,
                   "items": items, "assets": sorted(assets)}, f, indent=2)
    print("[placements] dumped %d placement(s) to %s" % (len(items), out))
    return out


def apply(directory, scope, libraries=None):
    """Apply <scope>.plan.blender.json. Returns a list of errors (empty = everything applied)."""
    with open(os.path.join(directory, "%s.plan.blender.json" % scope), encoding="utf-8-sig") as f:
        plan = json.load(f)
    by_name = {o.name: o for o in placements()}
    errors, done = [], {"assign": 0, "delete": 0, "update": 0, "create": 0}

    for a in plan.get("assign", []):
        ob = by_name.get(a["key"])
        if ob is None:
            errors.append("assign: no placement called %s" % a["key"])
            continue
        ob[PROP] = a["id"]
        done["assign"] += 1

    by_id = {}
    for o in placements():
        by_id.setdefault(str(o.get(PROP, "")), o)
    index = None

    for pid in plan.get("delete", []):
        ob = by_id.pop(pid, None)
        if ob is None:
            errors.append("delete: no placement with id %s" % pid)
            continue
        bpy.data.objects.remove(ob)
        done["delete"] += 1

    for kind in ("update", "create"):
        for it in plan.get(kind, []):
            ob = by_id.get(it["id"])
            coll = ob.instance_collection if ob is not None else None
            if coll is None or coll.name != it["asset"]:
                if index is None:
                    index = _library_index(libraries)
                coll = _collection(it["asset"], index)
                if coll is None:
                    errors.append("%s %s: no collection %s in this file or --libraries" % (kind, it["id"], it["asset"]))
                    continue
            if ob is None:
                if kind == "update":
                    errors.append("update: no placement with id %s (creating it)" % it["id"])
                ob = bpy.data.objects.new(it["asset"], None)
                ob.instance_type = "COLLECTION"
                ob.empty_display_size = 0.25
                bpy.context.scene.collection.objects.link(ob)
                ob[PROP] = it["id"]
                by_id[it["id"]] = ob
            ob.instance_collection = coll
            ob.matrix_world = from_unity(it["pos"], it["rot"], it["scl"])
            done[kind] += 1

    print("[placements] applied to %s: %s" % (scope, ", ".join("%d %s" % (n, k) for k, n in done.items())))
    for e in errors:
        print("[placements] ERROR " + e)
    return errors


def _main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv or argv[0] not in ("dump", "apply"):
        return
    import argparse
    ap = argparse.ArgumentParser(prog="export_placements.py")
    ap.add_argument("cmd")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--scope", required=True)
    ap.add_argument("--libraries", nargs="*", default=[])
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "dump":
        dump(a.dir, a.scope, a.libraries)
        return
    errors = apply(a.dir, a.scope, a.libraries)
    if not a.no_save:
        bpy.ops.wm.save_mainfile()
        print("[placements] saved %s" % bpy.data.filepath)
    if bpy.app.background:
        sys.exit(1 if errors else 0)


if __name__ == "__main__":
    _main()
