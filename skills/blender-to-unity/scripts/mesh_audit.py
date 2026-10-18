"""Audit the meshes of a Blender scene before they go to Unity.

Host: Blender (bpy; tested on 5.2.2), live or headless. Run it from the Text Editor, through the Blender MCP
`execute_blender_code`, or headless:
    blender -b --factory-startup file.blend --python-exit-code 1 --python mesh_audit.py
(--factory-startup keeps your add-ons out of the run; --python-exit-code 1 makes a failure exit 1). It prints a table.
To get the numbers without printing: ns = {"MESH_AUDIT_NO_MAIN": True}; exec(open(path, encoding="utf-8").read(), ns);
ns["audit"]().

Per mesh object (modifiers applied, as batch_export_fbx.py --kit writes it), named by name_full so a local object
never hides a linked one of the same name. That includes meshes the view layer does not show (hidden with H or in a
collection hidden with the eye: flagged hidden; excluded or viewport-disabled collections and objects: flagged
not-in-view-layer), meshes in local collections outside the scene (flagged outside-scene), and in a MASTER or ASM file
the mesh objects inside instanced collections, linked or local (flagged instanced, with how many times they are
placed): all are measured with their modifiers, exactly as the export evaluates them, and the scene is restored
afterwards. Members a linked KIT disables in viewports are not instanced, so they are only listed (unseen): audit the
KIT itself for them.
  triangles, vertices, material slots, UV maps (no-uv / no-uv2 on every mesh except <Piece>_COL), n-gons, loose
  vertices and edges, custom normals on faces of 4+ corners (custom-normals-on-quads: the exporter's triangulation
  changes them), non-planar faces of 4+ corners, unapplied rotation (any rotation mode) or scale, negative scale,
  empty meshes, heavy meshes, many slots.
Scene-wide:
  render triangles = meshes the view layer shows plus collection instances (a MASTER or ASM file holds only
  instances), leaving out <Piece>_LOD1+ and <Piece>_COL meshes, which never render alongside LOD0, and the hidden or
  excluded source of an instanced collection; instanced meshes with their counts; collection instancers the view
  layer does not show (hidden, or in hidden, excluded or disabled collections: Blender shows nothing for them, so
  they are not in the total, but placement sync ships every instancer, so Unity renders them too);
  unique materials; and mesh datablocks shared by several objects.
In a kit, repeats are collection instances (MASTER) that become prefab instances of one FBX in Unity; objects that
share a mesh datablock matter only when a whole scene goes out as one FBX.
"""

import contextlib
import re

import bpy

TRI_WARN = 20000        # per-object triangle count worth a second look
SLOT_WARN = 3           # material slots per object
NOT_RENDERED = re.compile(r"_(LOD[1-9]\d*|COL)$")   # LOD1+ and collision shells: not part of the render count
COLLISION = re.compile(r"_COL$")                    # collision shells: no UVs needed


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


@contextlib.contextmanager
def _shown(obs):
    """Objects directly in the scene collection that are disabled in viewports: enable them for the measurement."""
    changed = [ob for ob in obs if ob.hide_viewport]
    for ob in changed:
        ob.hide_viewport = False
    bpy.context.view_layer.update()
    try:
        yield
    finally:
        for ob in changed:
            ob.hide_viewport = True
        bpy.context.view_layer.update()


def _nonplanar(me, poly, tol=1e-4):
    n, c = poly.normal, poly.center
    return any(abs((me.vertices[v].co - c).dot(n)) > tol for v in poly.vertices)


def mesh_stats(ob, depsgraph):
    """Counts for one mesh object, modifiers applied; evaluated is False when the depsgraph does not evaluate it (its
    counts are then the bare mesh's)."""
    eval_ob = ob.evaluated_get(depsgraph)
    mesh = eval_ob.to_mesh()
    try:
        face_edges = {ek for p in mesh.polygons for ek in p.edge_keys}
        edge_verts = {v for e in mesh.edges for v in e.vertices}
        big = [p for p in mesh.polygons if p.loop_total > 3]
        return dict(
            evaluated=bool(eval_ob.is_evaluated),
            tris=sum(max(len(p.vertices) - 2, 0) for p in mesh.polygons),
            verts=len(mesh.vertices),
            ngons=sum(1 for p in mesh.polygons if len(p.vertices) > 4),
            uvs=len(mesh.uv_layers),
            loose_verts=len(mesh.vertices) - len(edge_verts),
            loose_edges=sum(1 for e in mesh.edges if e.key not in face_edges),
            polys=len(mesh.polygons),
            cn_quads=len(big) if mesh.has_custom_normals else 0,
            nonplanar=sum(1 for p in big if _nonplanar(mesh, p)),
        )
    finally:
        eval_ob.to_mesh_clear()


def _flags(ob, st, where):
    m = ob.matrix_basis
    scale = [a * b for a, b in zip(ob.scale, ob.delta_scale)]
    flags = [where] if where else []
    if any(abs(abs(s) - 1.0) > 1e-4 for s in scale):
        flags.append("scale(%s)" % ", ".join("%.3g" % s for s in scale))
    if m.to_quaternion().angle > 1e-4:
        flags.append("rotation")
    if scale[0] * scale[1] * scale[2] < 0:
        flags.append("NEGATIVE-SCALE")
    if not COLLISION.search(ob.name):
        if st["uvs"] == 0:
            flags.append("no-uv")
        elif st["uvs"] == 1:
            flags.append("no-uv2")
    if st["ngons"]:
        flags.append("ngons:%d" % st["ngons"])
    if st["loose_verts"] or st["loose_edges"]:
        flags.append("loose:%dv/%de" % (st["loose_verts"], st["loose_edges"]))
    if st["cn_quads"]:
        flags.append("custom-normals-on-quads:%d" % st["cn_quads"])
    if st["nonplanar"]:
        flags.append("nonplanar:%d" % st["nonplanar"])
    if st["tris"] > TRI_WARN:
        flags.append("heavy")
    if len(ob.material_slots) > SLOT_WARN:
        flags.append("slots:%d" % len(ob.material_slots))
    if not st["polys"]:
        flags.append("EMPTY-MESH")
    return flags


def audit(scene=None):
    """Return {"objects": [row dict per mesh object], "render_tris": int, "instances": {mesh object: {count, tris}},
    "skipped_instancers": [names], "unseen": [names], "materials": [names], "shared": {mesh datablock: [object
    names]}}. Objects are named by name_full ("<name> [<library>.blend]" for linked ones), so a local object never
    hides a linked one of the same name. Rows carry "where": "" (shown), "hidden" (hidden with H or in a collection
    hidden with the eye), "instanced" (only inside an instanced collection; "count" placements), "not-in-view-layer"
    or "outside-scene". Render triangles count shown rows and placements, never a hidden or excluded source.
    "skipped_instancers" are collection instancers the view layer does not show (hidden, or in a hidden, excluded
    or disabled collection): Blender shows nothing for them and they are not in render_tris, but placement sync
    ships every instancer, so Unity renders them. "unseen" lists mesh objects inside instanced collections that no
    shown instance measures (disabled in viewports in a linked KIT, or placed only by instancers Blender does not
    show): audit their KIT for them."""
    scene = scene or bpy.context.scene
    vl = bpy.context.view_layer
    depsgraph = bpy.context.evaluated_depsgraph_get()
    in_layer = set(vl.objects)
    rows, materials, shared, cache = [], set(), {}, {}
    pending = {}

    def add(ob, st, where, **extra):
        cache[ob.name_full] = st
        for slot in ob.material_slots:
            if slot.material:
                materials.add(slot.material.name_full)
        if where != "instanced":
            shared.setdefault(ob.data.name_full, []).append(ob.name_full)
        rows.append(dict(name=ob.name_full, slots=len(ob.material_slots), where=where,
                         rendered=not NOT_RENDERED.search(ob.name), flags=_flags(ob, st, where), **extra, **st))

    for ob in scene.objects:
        if ob.type != "MESH":
            continue
        st = mesh_stats(ob, depsgraph)
        if not st["evaluated"]:
            pending.setdefault(ob.users_collection[0], []).append(ob)
        elif ob.visible_get():
            add(ob, st, "")
        else:              # evaluated but not drawn: hidden, or excluded and evaluated only for an instance of it
            add(ob, st, "hidden" if ob in in_layer else "not-in-view-layer")

    render_tris = sum(r["tris"] for r in rows if r["where"] == "" and r["rendered"])
    placed, originals = {}, {}
    for inst in depsgraph.object_instances:
        if not inst.is_instance or inst.object.type != "MESH":
            continue
        if inst.parent is not None and not inst.parent.original.visible_get():
            continue                 # an instancer in a collection hidden with the eye: evaluated, not shown
        orig = inst.object.original
        key = orig.name_full
        if key not in cache:
            cache[key] = mesh_stats(orig, depsgraph)
        placed[key] = placed.get(key, 0) + 1
        originals[key] = orig
        if not NOT_RENDERED.search(orig.name):
            render_tris += cache[key]["tris"]
        for slot in orig.material_slots:
            if slot.material:
                materials.add(slot.material.name_full)
    instances = {k: dict(count=n, tris=cache[k]["tris"]) for k, n in sorted(placed.items())
                 if not NOT_RENDERED.search(originals[k].name)}
    own = {r["name"] for r in rows} | {ob.name_full for obs in pending.values() for ob in obs}
    for key, orig in sorted(originals.items()):
        if key not in own:           # flagged like this file's own meshes (UV2 on LODs, a crate without UV2 ...)
            add(orig, cache[key], "instanced", count=placed[key])
    skipped_instancers = sorted(ob.name_full for ob in scene.objects
                                if ob.instance_type == "COLLECTION" and ob.instance_collection is not None
                                and not ob.visible_get())

    for coll, obs in pending.items():
        with (_shown(obs) if coll == scene.collection else _evaluated(coll)):
            dg = bpy.context.evaluated_depsgraph_get()
            for ob in obs:
                add(ob, mesh_stats(ob, dg), "not-in-view-layer")
    in_scene = set(scene.collection.children_recursive)
    seen = {r["name"] for r in rows}
    for coll in sorted(bpy.data.collections, key=lambda c: c.name_full):
        if coll.library is not None or coll in in_scene:
            continue
        obs = [o for o in coll.all_objects if o.type == "MESH" and o.name_full not in seen]
        if not obs:
            continue
        with _evaluated(coll):
            dg = bpy.context.evaluated_depsgraph_get()
            for ob in obs:
                add(ob, mesh_stats(ob, dg), "outside-scene")
                seen.add(ob.name_full)
    # members no shown instance measures (disabled in viewports in a linked KIT, or placed only by instancers Blender
    # does not show, which placement sync still ships): not measured here
    todo = [ob.instance_collection for ob in scene.objects if ob.instance_type == "COLLECTION"
            and ob.instance_collection is not None]
    members, walked = set(), set()
    while todo:
        coll = todo.pop()
        if coll.name_full in walked:
            continue
        walked.add(coll.name_full)
        for o in coll.all_objects:
            if o.type == "MESH":
                members.add(o.name_full)
            elif o.instance_type == "COLLECTION" and o.instance_collection is not None:
                todo.append(o.instance_collection)
    unseen = sorted(members - seen)

    rows.sort(key=lambda r: (-r["tris"], r["name"]))
    return dict(objects=rows, render_tris=render_tris, materials=sorted(materials), instances=instances,
                skipped_instancers=skipped_instancers, unseen=unseen,
                shared={k: v for k, v in shared.items() if len(v) > 1})


def main():
    r = audit()
    w = 110
    print("=" * w)
    print("%-44s %9s %9s %6s %5s  %s" % ("OBJECT", "TRIS", "VERTS", "SLOTS", "UVs", "FLAGS"))
    print("-" * w)
    for row in r["objects"]:
        print("%-44s %9d %9d %6d %5d  %s" % (row["name"][:44], row["tris"], row["verts"], row["slots"], row["uvs"],
                                             " ".join(row["flags"])))
    if r["instances"]:
        print("-" * w)
        print("Collection instances (mesh objects inside instanced collections):")
        for name, d in r["instances"].items():
            print("  %-44s x%-5d %9d tris each" % (name[:44], d["count"], d["tris"]))
    if r["skipped_instancers"]:
        print("Not counted: %d collection instance(s) Blender does not show (hidden, or in hidden, excluded or "
              "disabled collections); placement sync still ships them to Unity: %s"
              % (len(r["skipped_instancers"]), ", ".join(r["skipped_instancers"][:8])
                 + (" ..." if len(r["skipped_instancers"]) > 8 else "")))
    if r["unseen"]:
        print("Not audited: %d mesh object(s) no shown instance measures (audit their KIT): %s"
              % (len(r["unseen"]), ", ".join(r["unseen"][:8]) + (" ..." if len(r["unseen"]) > 8 else "")))
    print("-" * w)
    print("mesh objects: %d   render triangles (shown meshes and instances, without LOD1+ and _COL): %d   "
          "unique materials: %d" % (len(r["objects"]), r["render_tris"], len(r["materials"])))
    if r["shared"]:
        print("\nObjects sharing one mesh datablock (one mesh asset in a single-FBX export):")
        for mesh, names in sorted(r["shared"].items(), key=lambda kv: -len(kv[1])):
            print("  %-28s x%-4d  %s" % (mesh, len(names), ", ".join(names[:6]) + (" ..." if len(names) > 6 else "")))
    print("\nBudget reference: Quest world ~250k triangles in total, PC 500k-1M (vrchat-world-optimization).")
    print("=" * w)
    return r


if not globals().get("MESH_AUDIT_NO_MAIN"):
    main()
