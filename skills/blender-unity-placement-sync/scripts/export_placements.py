"""Dump a Blender layout's placements to JSON, and apply a merge plan back to it.

Host: Blender 4.1+ (bpy), no add-ons. Pairs with placement_merge.py (plain Python) and PlacementSync.cs (Unity).

A placement is a collection instance: an empty with instance_type COLLECTION, of a KIT piece or an ASM assembly
(local collections in a single MASTER, blender-kit-library's default layout; linked from KIT and ASM files when
split). Its stable id lives in the custom property `placement_id` on that empty, so renames, re-parenting and moving
it between collections never lose it. Transforms are written in Unity space (left-handed, Y up, metres) relative to
the world origin, which is the scope root.

A scope covers the collection named like the scope when the file has one (in a single MASTER, scene["kit_layout"]
== "single": the MASTER collection for the MASTER scope and the ASM_<Name>_<Variant> collection under ASM for an
assembly scope; in a split ASM file its assembly collection), else the whole scene (a split MASTER); --collection
names another. A single MASTER must have the scope's collection, since its whole scene also holds every assembly's
insides. apply creates new placements inside that collection. Library overrides are not placements: dump skips them
and warns. --libraries is for split files: a single MASTER's assets are its own KIT and ASM collections.

Names and folders sync too. Each item carries "label", the empty's name without Blender's ".001" suffix, and
"group", the path of collections from the scope collection down to the one holding the empty ("Street/Shops"; ""
directly in the scope collection). apply renames an empty whose label changed and moves it to its group's
collection, creating missing collections under the scope collection; it never deletes a collection. "/" in a name
reads as "-" (Unity uses "/" as a path separator).

Command line (the usual way). One writer per .blend: not while the file is open in a live Blender session.
    blender -b --factory-startup --python-exit-code 1 MASTER.blend --python export_placements.py --
        dump  --dir <placements> --scope MASTER [--libraries "kits/*.blend" "asm/*.blend"] [--collection NAME]
    blender -b --factory-startup --python-exit-code 1 MASTER.blend --python export_placements.py --
        apply --dir <placements> --scope MASTER [--libraries ...] [--collection NAME] [--no-save]

From a live Blender (Blender MCP execute_blender_code):
    ns = {}; exec(open(r"<skill>/scripts/export_placements.py", encoding="utf-8").read(), ns)
    ns["dump"](r"F:/World/placements", "MASTER", libraries=[r"F:/World/blender/kits/*.blend"])
    ns["apply"](r"F:/World/placements", "MASTER", libraries=[...])        # then save the file yourself

dump deletes the old <dir>/<scope>.blender.json first (a failed dump leaves none, so a merge cannot read a stale one),
then writes every placement, "assets" (the collection names this file links or could link from --libraries, so the
merge knows which Unity-side additions Blender can take) and "warnings". apply reads <dir>/<scope>.plan.blender.json
and does assign, delete, update, create in that order; a deleted placement's children are moved to its parent with
their world pose kept, poses are set parents first, and a placement parented under a moved one keeps its world pose
unless the plan moves it too. Anything it cannot do (an asset it cannot find, an object that changed since the dump) is
printed as an ERROR and makes the exit code 1, so the commit step will refuse. The command line saves with
save_version 0 (no .blend1 backup). --libraries globs are relative to the .blend file's folder unless absolute.
"""

import glob
import json
import os
import re
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

PROP = "placement_id"

# Blender (right-handed, Z up) -> Unity (left-handed, Y up), matching the FBX exporter's -Z forward / Y up with
# Use Space Transform and Bake Space Transform on: Unity = (-x, z, -y). Verified by the round-trip test (SKILL.md).
C = Matrix(((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)))
CT = C.transposed()


def clean(name):
    """A name as both sides compare it: Blender's duplicate suffix (.001) dropped, "/" read as "-", ends trimmed."""
    return re.sub(r"\.\d{3,}$", "", name).replace("/", "-").strip()


def _tree(coll):
    """{collection: parent} for every local collection under `coll` (or the scene's), first parent found."""
    root = coll if coll is not None else bpy.context.scene.collection
    parents, todo = {root: None}, [root]
    while todo:
        c = todo.pop(0)
        for child in sorted(c.children, key=lambda x: x.name):
            if child not in parents and child.library is None:
                parents[child] = c
                todo.append(child)
    return root, parents


def _path(c, parents):
    parts = []
    while parents.get(c) is not None:
        parts.append(clean(c.name))
        c = parents[c]
    return "/".join(reversed(parts))


def groups_of(ob, tree):
    """The group paths of every collection under the scope that holds `ob`, sorted (the first is its group)."""
    _root, parents = tree
    return sorted(_path(c, parents) for c in ob.users_collection if c in parents)


def ensure_group(group, tree):
    """The collection for `group` under the scope collection, creating the missing ones."""
    cur, parents = tree
    for part in [p for p in group.split("/") if p]:
        nxt = next((c for c in sorted(cur.children, key=lambda x: x.name)
                    if c.library is None and clean(c.name) == part), None)
        if nxt is None:
            nxt = bpy.data.collections.new(part)
            cur.children.link(nxt)
            parents[nxt] = cur
        cur = nxt
    return cur


def move_to_group(ob, group, tree):
    """Link `ob` into its group's collection and out of every other collection under the scope; collections outside
    the scope (a REF collection, say) keep it."""
    target = ensure_group(group, tree)
    _root, parents = tree
    if target not in ob.users_collection:
        target.objects.link(ob)
    for c in list(ob.users_collection):
        if c is not target and c in parents:
            c.objects.unlink(ob)


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


def is_single(scene=None):
    """A single MASTER (blender-kit-library): pieces, assemblies and layout as collections in this one file."""
    return (scene or bpy.context.scene).get("kit_layout") == "single"


def scope_collection(scope, name=None):
    """The local collection a scope covers: `name`, else the one named like the scope, else None (the whole scene;
    refused in a single MASTER, where the scene also holds every assembly's insides)."""
    for want in ([name] if name else [scope]):
        for coll in bpy.data.collections:
            if coll.name == want and coll.library is None:
                return coll
    if name or is_single():
        raise KeyError("no local collection %r in %s%s" % (name or scope, bpy.data.filepath or "this file",
                                                           " (a single MASTER: the scope's collection is required)"
                                                           if not name else ""))
    return None


def local_assets():
    """A single MASTER's own piece and assembly collections (everything under KIT and ASM)."""
    out = set()
    for root in ("KIT", "ASM"):
        coll = next((c for c in bpy.data.collections if c.name == root and c.library is None), None)
        if coll is not None:
            out |= {c.name for c in coll.children_recursive if not c.children and c.library is None}
    return out


def _instances(scene=None, coll=None):
    objs = coll.all_objects if coll is not None else (scene or bpy.context.scene).objects
    return [o for o in objs
            if o.library is None and o.instance_type == "COLLECTION" and o.instance_collection is not None]


def placements(scene=None, coll=None):
    """Local collection-instance empties in `coll` (or the scene), library overrides excluded."""
    return [o for o in _instances(scene, coll) if o.override_library is None]


def scope_warnings(scene=None, coll=None, items=None):
    """Problems that make the dump disagree with what Blender draws or with the merge's view of the file."""
    out = []
    over = [o.name for o in _instances(scene, coll) if o.override_library is not None]
    if over:
        out.append("skipped %d library-override instance(s), which are not placements: %s. An instance that was "
                   "overridden reads as deleted; make a variant piece instead" % (len(over), ", ".join(sorted(over))))
    offsets = {}
    for o in placements(scene, coll):
        off = tuple(round(v, 4) for v in o.instance_collection.instance_offset)
        if any(off):
            offsets.setdefault((o.instance_collection.name, off), []).append(o.name)
    for (name, off), obs in sorted(offsets.items()):
        out.append("collection %s has instance_offset %s: the engine places %s that far from where Blender draws "
                   "them; zero it on the piece or assembly collection (in its KIT or ASM file when split)"
                   % (name, off, ", ".join(sorted(obs))))
    if coll is not None and any(abs(v) > 1e-4 for v in coll.instance_offset):
        out.append("scope collection %s has instance_offset %s: where MASTER instances it, Blender draws it shifted "
                   "from the Unity prefab; zero it" % (coll.name, tuple(round(v, 4) for v in coll.instance_offset)))
    tree = _tree(coll)
    multi = sorted(o.name for o in placements(scene, coll) if len(groups_of(o, tree)) > 1)
    if multi:
        out.append("placement(s) in more than one collection under the scope: %s. Each syncs as being in the first "
                   "(by path), and a folder change from Unity moves it out of the others" % ", ".join(multi))
    cons = sorted(o.name for o in placements(scene, coll) if len(o.constraints))
    if cons:
        out.append("placement(s) with constraints: %s. The sync reads and writes world poses and cannot see "
                   "constraints, so these drift or fight it; remove the constraints (parent the empty instead)"
                   % ", ".join(cons))
    unit = (scene or bpy.context.scene).unit_settings.scale_length
    if abs(unit - 1.0) > 1e-6:
        out.append("scene unit scale is %g: placements assume 1 Blender unit = 1 m" % unit)
    return out


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


def dump(directory, scope, libraries=None, collection=None):
    out = os.path.join(directory, "%s.blender.json" % scope)
    if os.path.exists(out):
        os.remove(out)          # a dump that fails below leaves no stale file for the merge to read
    coll = scope_collection(scope, collection)
    tree = _tree(coll)
    items = []
    for ob in placements(coll=coll):
        pos, rot, scl = to_unity(ob.matrix_world)
        items.append({"id": str(ob.get(PROP, "")), "asset": ob.instance_collection.name,
                      "pos": pos, "rot": rot, "scl": scl, "label": clean(ob.name) or ob.instance_collection.name,
                      "group": (groups_of(ob, tree) or [""])[0], "key": ob.name})
    assets = {c.name for c in bpy.data.collections if c.library is not None and not c.is_missing}
    assets |= set(_library_index(libraries))
    if is_single():
        assets |= local_assets()
    assets |= {i["asset"] for i in items}
    warnings = scope_warnings(coll=coll)
    os.makedirs(directory, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"scope": scope, "side": "blender", "file": bpy.data.filepath,
                   "collection": coll.name if coll else None, "items": items, "assets": sorted(assets),
                   "warnings": warnings}, f, indent=2)
    print("[placements] dumped %d placement(s) from %s to %s"
          % (len(items), "collection " + coll.name if coll else "scene " + bpy.context.scene.name, out))
    for w in warnings:
        print("[placements] WARNING " + w)
    return out


def keep_children(ob):
    """Before `ob` is deleted, move its children (often placements parented under it) to its parent, keeping their
    world pose; a bare objects.remove() would leave them at their parent-relative transform."""
    for child in list(ob.children):
        mw = child.matrix_world.copy()
        child.parent = ob.parent
        child.matrix_parent_inverse = Matrix.Identity(4)
        child.matrix_world = mw


def same_pose(a, b, tol=1e-5):
    """Two world matrices equal within `tol` (the tolerance PlacementSync.cs's SamePose uses)."""
    return all(abs(a[i][j] - b[i][j]) <= tol for i in range(4) for j in range(4))


def set_world_poses(poses, before):
    """Set the planned {object name: world matrix} parents first, evaluating the scene between levels, so moving a
    placement never drags one parented under it that was already set. A placement the plan does not move gets its
    `before` matrix back only when an ancestor moved and dragged it; every other object is left alone (setting
    matrix_world ignores constraints, so re-setting it would shift a constrained placement on every apply)."""
    def depth(ob):
        d, p = 0, ob.parent
        while p is not None:
            d, p = d + 1, p.parent
        return d

    def under_moved(ob):
        p = ob.parent
        while p is not None:
            if p.name in poses:
                return True
            p = p.parent
        return False

    kept = {n: mw for n, mw in before.items() if n not in poses and under_moved(bpy.data.objects[n])}
    levels = {}
    for n in list(poses) + list(kept):
        levels.setdefault(depth(bpy.data.objects[n]), []).append(n)
    for d in sorted(levels):
        bpy.context.view_layer.update()            # this level's parents are where the previous levels put them
        for n in levels[d]:
            ob = bpy.data.objects[n]
            if n in poses:
                ob.matrix_world = poses[n]
            elif not same_pose(ob.matrix_world, kept[n]):
                ob.matrix_world = kept[n]
    bpy.context.view_layer.update()


def apply(directory, scope, libraries=None, collection=None):
    """Apply <scope>.plan.blender.json. Returns a list of errors (empty = everything applied)."""
    with open(os.path.join(directory, "%s.plan.blender.json" % scope), encoding="utf-8-sig") as f:
        plan = json.load(f)
    coll = scope_collection(scope, collection)
    by_name = {o.name: o for o in placements(coll=coll)}
    errors, done = [], {"assign": 0, "delete": 0, "update": 0, "create": 0}

    for a in plan.get("assign", []):
        ob = by_name.get(a["key"])
        if ob is None:
            errors.append("assign %s: no placement called %s (renamed since the dump? run the loop again)"
                          % (a["id"], a["key"]))
            continue
        have = str(ob.get(PROP, ""))
        if have == a["id"]:                     # done by an earlier run of this plan
            continue
        if "was" in a and have != a["was"]:
            errors.append("assign %s: %s has id '%s', the merge saw '%s' (changed since the dump: run the loop again)"
                          % (a["id"], ob.name, have, a["was"]))
            continue
        if a.get("asset") and ob.instance_collection.name != a["asset"]:
            errors.append("assign %s: %s instances %s, the merge saw %s (changed since the dump: run the loop again)"
                          % (a["id"], ob.name, ob.instance_collection.name, a["asset"]))
            continue
        ob[PROP] = a["id"]
        done["assign"] += 1

    by_id = {}
    for o in placements(coll=coll):
        by_id.setdefault(str(o.get(PROP, "")), o)
    index = None

    for pid in plan.get("delete", []):
        ob = by_id.pop(pid, None)
        if ob is None:                          # already gone (an earlier run of this plan): nothing to do
            continue
        keep_children(ob)
        bpy.data.objects.remove(ob)
        done["delete"] += 1

    # Every placement's world pose before anything moves: those the plan does not move keep it, even when a placement
    # they are parented under moves (the update-path twin of keep_children).
    before = {o.name: o.matrix_world.copy() for o in placements(coll=coll)}
    poses, named = {}, []
    for kind in ("update", "create"):
        for it in plan.get(kind, []):
            ob = by_id.get(it["id"])
            target = ob.instance_collection if ob is not None else None
            if target is None or target.name != it["asset"]:
                if index is None:
                    index = _library_index(libraries)
                target = _collection(it["asset"], index)
                if target is None:
                    errors.append("%s %s: no collection %s in this file or --libraries" % (kind, it["id"], it["asset"]))
                    continue
            if ob is None:
                if kind == "update":
                    errors.append("update: no placement with id %s (creating it)" % it["id"])
                ob = bpy.data.objects.new(it.get("label") or it["asset"], None)
                ob.instance_type = "COLLECTION"
                ob.empty_display_size = 0.25
                (coll or bpy.context.scene.collection).objects.link(ob)
                ob[PROP] = it["id"]
                by_id[it["id"]] = ob
            ob.instance_collection = target
            poses[ob.name] = from_unity(it["pos"], it["rot"], it["scl"])
            named.append((ob, it))
            done[kind] += 1
    set_world_poses(poses, before)
    # Names and folders last: poses are keyed by object name.
    tree = _tree(coll)
    for ob, it in named:
        if it.get("group") is not None and (groups_of(ob, tree) or [""])[0] != it["group"]:
            move_to_group(ob, it["group"], tree)
        if it.get("label") and clean(ob.name) != it["label"]:
            ob.name = it["label"]

    print("[placements] applied to %s: %s" % (scope, ", ".join("%d %s" % (n, k) for k, n in done.items())))
    for e in errors:
        print("[placements] ERROR " + e)
    return errors


def save_mainfile():
    """Save the open file without a .blend1 backup (save_version 0 for the save, restored afterwards)."""
    prefs = bpy.context.preferences.filepaths
    old = prefs.save_version
    prefs.save_version = 0
    try:
        bpy.ops.wm.save_mainfile()
    finally:
        prefs.save_version = old


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
    ap.add_argument("--collection", help="the collection the scope covers (default: the one named like the scope)")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "dump":
            dump(a.dir, a.scope, a.libraries, a.collection)
            return
        errors = apply(a.dir, a.scope, a.libraries, a.collection)
    except KeyError as e:
        print("[placements] ERROR %s" % e.args[0])
        if bpy.app.background:
            sys.exit(1)
        return
    if not a.no_save:
        save_mainfile()
        print("[placements] saved %s" % bpy.data.filepath)
    if bpy.app.background:
        sys.exit(1 if errors else 0)


if __name__ == "__main__":
    _main()
