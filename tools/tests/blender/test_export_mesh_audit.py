"""Blender-hosted tests for blender-to-unity's scripts/mesh_audit.py: loose geometry, n-gons, rotation in any rotation
mode, UV2 on every render mesh (LOD1 included, _COL exempt), collection instances counted into the render triangles
(LOD1+ and _COL left out), members of excluded or outside-scene collections and viewport-disabled objects evaluated
with their modifiers (state restored afterwards), a MASTER linking a KIT (instanced pieces flagged, instancers in an
excluded collection reported, a local object named like a linked one kept apart), sources of instances that are
hidden or excluded left out of the render count, hidden instancers, shared mesh datablocks, and that loading it with
MESH_AUDIT_NO_MAIN prints nothing.

Host: Blender 4.2+ (bpy; tested on 5.2.2), run from anywhere:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_export_mesh_audit.py
Prints PASS <case> / FAIL <case>: <why>, and raises if any case failed.
"""

import contextlib
import io
import math
import tempfile
import traceback
from pathlib import Path

import bmesh
import bpy

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "skills" / "blender-to-unity" / "scripts" / "mesh_audit.py"
RESULTS = []


def case(fn):
    try:
        fn()
        RESULTS.append(("PASS", fn.__name__))
        print("PASS", fn.__name__)
    except Exception as exc:  # noqa: BLE001
        RESULTS.append(("FAIL", fn.__name__))
        print("FAIL %s: %s" % (fn.__name__, exc))
        traceback.print_exc()


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def load():
    ns = {"MESH_AUDIT_NO_MAIN": True}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec"), ns)
    check(out.getvalue() == "", "loading printed output")
    return ns


def mesh_object(name, verts, edges, faces, coll, uv_layers=2):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, faces)
    for i in range(uv_layers):
        me.uv_layers.new(name="UV%d" % i)
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


CUBE_V = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
CUBE_F = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    root = scene.collection
    # a plain object with an n-gon, a loose vertex and a loose edge
    mesh_object("Messy", [(0, 0, 0), (1, 0, 0), (1.5, 1, 0), (0.5, 1.5, 0), (-0.5, 1, 0), (5, 5, 5), (6, 6, 6),
                          (7, 6, 6)], [(6, 7)], [(0, 1, 2, 3, 4)], root, uv_layers=1)
    rot = mesh_object("Rotated", CUBE_V, [], CUBE_F, root)
    rot.rotation_mode = "QUATERNION"
    rot.rotation_quaternion = (math.cos(0.25), 0.0, 0.0, math.sin(0.25))
    a = mesh_object("Shared_A", CUBE_V, [], CUBE_F, root)
    b = bpy.data.objects.new("Shared_B", a.data)
    root.objects.link(b)
    # a kit piece used only through collection instances, as in a MASTER file
    piece = bpy.data.collections.new("INT_Wall_2x3_A")
    piece.use_fake_user = True
    mesh_object("INT_Wall_2x3_A_LOD0", CUBE_V, [], CUBE_F, piece)                 # 12 tris
    lod1 = mesh_object("INT_Wall_2x3_A_LOD1", CUBE_V, [], CUBE_F, piece, uv_layers=1)   # LODs need a UV2 too
    lod1.modifiers.new("sub", "SUBSURF").levels = 1                               # 48, not rendered with LOD0
    mesh_object("INT_Wall_2x3_A_COL", CUBE_V, [], CUBE_F, piece, uv_layers=0)     # never rendered, needs no UVs
    for i in range(3):
        inst = bpy.data.objects.new("wall.%d" % i, None)
        inst.instance_type = "COLLECTION"
        inst.instance_collection = piece
        inst.location = (i * 2.0, 10.0, 0.0)
        root.objects.link(inst)
    # members the view layer does not evaluate: an excluded piece, and an object disabled in viewports
    excl = bpy.data.collections.new("PROP_Excl_Free_A")
    root.children.link(excl)
    mesh_object("PROP_Excl_Free_A", CUBE_V, [], CUBE_F, excl).modifiers.new("sub", "SUBSURF").levels = 1
    disabled = mesh_object("Disabled", CUBE_V, [], CUBE_F, root)
    disabled.modifiers.new("sub", "SUBSURF").levels = 1
    disabled.hide_viewport = True
    bpy.context.view_layer.layer_collection.children["PROP_Excl_Free_A"].exclude = True
    # a piece collection outside the scene that nothing instances
    orphan = bpy.data.collections.new("STR_Orphan_1x1_A")
    orphan.use_fake_user = True
    mesh_object("STR_Orphan_1x1_A", CUBE_V, [], CUBE_F, orphan).modifiers.new("sub", "SUBSURF").levels = 1
    bpy.context.view_layer.update()


def test_flags_and_counts():
    build()
    r = load()["audit"]()
    rows = {row["name"]: row for row in r["objects"]}
    messy = rows["Messy"]
    check(messy["ngons"] == 1, "ngons %d" % messy["ngons"])
    check(messy["loose_verts"] == 1 and messy["loose_edges"] == 1, "loose %d/%d" % (messy["loose_verts"],
                                                                                   messy["loose_edges"]))
    check("no-uv2" in messy["flags"] and any(f.startswith("loose:") for f in messy["flags"]), messy["flags"])
    check("rotation" in rows["Rotated"]["flags"], "quaternion rotation not flagged: %s" % rows["Rotated"]["flags"])
    check("rotation" not in rows["Shared_A"]["flags"], "identity flagged")
    shared_mesh = bpy.data.objects["Shared_A"].data.name
    check(sorted(r["shared"].get(shared_mesh, [])) == ["Shared_A", "Shared_B"], "shared datablocks %s" % r["shared"])


def test_instances_count_into_render_triangles():
    build()
    r = load()["audit"]()
    check(r["instances"] == {"INT_Wall_2x3_A_LOD0": {"count": 3, "tris": 12}},
          "instances %s (LOD1 and _COL must be left out)" % r["instances"])
    shown = sum(row["tris"] for row in r["objects"] if row["where"] == "")
    check(r["render_tris"] == shown + 3 * 12, "render tris %d, want %d" % (r["render_tris"], shown + 36))


def test_members_the_view_layer_skips_are_evaluated_and_restored():
    build()
    r = load()["audit"]()
    rows = {row["name"]: row for row in r["objects"]}
    for name, where in (("PROP_Excl_Free_A", "not-in-view-layer"), ("Disabled", "not-in-view-layer"),
                        ("STR_Orphan_1x1_A", "outside-scene"), ("INT_Wall_2x3_A_LOD1", "instanced")):
        row = rows.get(name)
        check(row is not None, "%s not listed" % name)
        check(row["tris"] == 48 and row["where"] == where and where in row["flags"],
              "%s: %d tris, where %r (want 48 with modifiers, %r)" % (name, row["tris"], row["where"], where))
    check(rows["INT_Wall_2x3_A_LOD1"]["count"] == 3, "instanced LOD1 placements %s" % rows["INT_Wall_2x3_A_LOD1"])
    scene, vl = bpy.context.scene, bpy.context.view_layer
    check(vl.layer_collection.children["PROP_Excl_Free_A"].exclude, "exclude not restored")
    check(bpy.data.objects["Disabled"].hide_viewport, "viewport disable not restored")
    check(bpy.data.collections["STR_Orphan_1x1_A"] not in scene.collection.children_recursive,
          "outside-scene collection left linked")


def test_master_flags_linked_instanced_pieces_and_reports_skipped_instancers():
    """A MASTER that links pieces from a KIT file: the instanced meshes are flagged like the KIT's own (a crate and a
    LOD1 without UV2), the _COL is exempt, instancers in an excluded collection are reported, not counted, and a
    member the KIT disables in viewports (so never instanced) is listed as unseen."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    kit_root = bpy.context.scene.collection
    crate = bpy.data.collections.new("PROP_Crate_Free_A")
    kit_root.children.link(crate)
    mesh_object("PROP_Crate_Free_A", CUBE_V, [], CUBE_F, crate, uv_layers=1)            # no UV2
    mesh_object("PROP_Crate_Free_A_COL", CUBE_V, [], CUBE_F, crate, uv_layers=0).hide_viewport = True
    column = bpy.data.collections.new("STR_Column_1x1x3_A")
    kit_root.children.link(column)
    mesh_object("STR_Column_1x1x3_A_LOD0", CUBE_V, [], CUBE_F, column)
    mesh_object("STR_Column_1x1x3_A_LOD1", CUBE_V, [], CUBE_F, column, uv_layers=1)     # no UV2
    mesh_object("STR_Column_1x1x3_A_COL", CUBE_V, [], CUBE_F, column, uv_layers=0)      # exempt
    kit = Path(tempfile.mkdtemp(prefix="mesh_audit_master_")) / "KIT_Test.blend"
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(kit))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    with bpy.data.libraries.load(str(kit), link=True, relative=False) as (src, dst):
        dst.collections = ["PROP_Crate_Free_A", "STR_Column_1x1x3_A"]
    root = bpy.context.scene.collection
    # a local object with the same name as the linked crate must not hide it
    mesh_object("PROP_Crate_Free_A", CUBE_V, [], CUBE_F, root).location = (0.0, 20.0, 0.0)
    zone_b = bpy.data.collections.new("Zone_B")
    root.children.link(zone_b)

    def place(name, coll, x):
        inst = bpy.data.objects.new(name, None)
        inst.instance_type = "COLLECTION"
        inst.instance_collection = bpy.data.collections[coll]
        inst.location = (x, 0.0, 0.0)
        (root if name.startswith("A") else zone_b).objects.link(inst)
    place("A_crate.0", "PROP_Crate_Free_A", 0.0)
    place("A_crate.1", "PROP_Crate_Free_A", 2.0)
    place("A_column.0", "STR_Column_1x1x3_A", 4.0)
    place("B_crate.0", "PROP_Crate_Free_A", 6.0)
    place("B_crate.1", "PROP_Crate_Free_A", 8.0)
    bpy.context.view_layer.layer_collection.children["Zone_B"].exclude = True
    bpy.context.view_layer.update()

    r = load()["audit"]()
    rows = {row["name"]: row for row in r["objects"]}

    def linked(name):
        return next(o for o in bpy.data.objects if o.library is not None and o.name == name).name_full
    for name in ("PROP_Crate_Free_A", "STR_Column_1x1x3_A_LOD1"):
        row = rows.get(linked(name))
        check(row is not None and row["where"] == "instanced" and "no-uv2" in row["flags"],
              "%s not flagged: %s" % (name, row))
    check(rows[linked("PROP_Crate_Free_A")]["count"] == 2, "crate placements %s" % rows[linked("PROP_Crate_Free_A")])
    local = rows.get("PROP_Crate_Free_A")
    check(local is not None and local["where"] == "" and "no-uv2" not in local["flags"], "local crate row %s" % local)
    col_flags = rows[linked("STR_Column_1x1x3_A_COL")]["flags"]
    check("no-uv" not in col_flags and "no-uv2" not in col_flags, "collision flagged: %s" % col_flags)
    check(r["skipped_instancers"] == ["B_crate.0", "B_crate.1"], "skipped instancers %s" % r["skipped_instancers"])
    check(r["unseen"] == [linked("PROP_Crate_Free_A_COL")], "unseen %s" % r["unseen"])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        load()["main"]()
    text = out.getvalue()
    check("Not counted: 2 collection instance(s)" in text and "Not audited: 1 mesh object(s)" in text, text[-900:])
    check(r["render_tris"] == 2 * 12 + 12 + 12, "render tris %d (2 crates + column LOD0 + the local crate)"
          % r["render_tris"])


def test_hidden_or_excluded_sources_and_instancers_count_only_what_shows():
    """A local piece collection in the scene that is also instanced twice: its own objects count only while they
    show (excluded: not-in-view-layer, eye-hidden: hidden), and an instancer hidden with H places nothing and is
    listed as not counted."""
    for mode, where, want in (("visible", "", 3 * 12), ("eye", "hidden", 2 * 12), ("exclude", "not-in-view-layer",
                                                                                   2 * 12)):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        root = bpy.context.scene.collection
        src = bpy.data.collections.new("PROP_Crate_Free_A")
        root.children.link(src)
        mesh_object("PROP_Crate_Free_A", CUBE_V, [], CUBE_F, src)
        for i, hide in enumerate((False, False, True)):
            inst = bpy.data.objects.new("crate.%d" % i, None)
            inst.instance_type, inst.instance_collection = "COLLECTION", src
            inst.location = (2.0 * (i + 1), 0.0, 0.0)
            root.objects.link(inst)
            inst.hide_set(hide)
        lc = bpy.context.view_layer.layer_collection.children["PROP_Crate_Free_A"]
        lc.exclude = mode == "exclude"
        if mode == "eye":
            lc.hide_viewport = True
        bpy.context.view_layer.update()
        r = load()["audit"]()
        row = {x["name"]: x for x in r["objects"]}["PROP_Crate_Free_A"]
        check(r["render_tris"] == want and row["where"] == where,
              "%s: render tris %d (want %d), where %r (want %r)" % (mode, r["render_tris"], want, row["where"], where))
        check(r["skipped_instancers"] == ["crate.2"], "%s: skipped %s" % (mode, r["skipped_instancers"]))
        check(r["instances"]["PROP_Crate_Free_A"]["count"] == 2, "%s: instances %s" % (mode, r["instances"]))


def test_master_with_hidden_zones_counts_what_blender_shows():
    """A MASTER linking a KIT, with an instancer hidden with H, one in a collection hidden with the eye, one in an
    excluded collection, an excluded local set-dressing collection and an eye-hidden local props collection, both
    instanced: the total is what Blender shows (216), each hidden instancer is listed, none counted."""
    def solid(name, kind, coll, uvs=2, subdiv=0, segs=16):
        bm = bmesh.new()
        if kind == "cube":
            bmesh.ops.create_cube(bm, size=1.0)
            if subdiv:
                bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=subdiv, use_grid_fill=True)
        else:
            bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=True, segments=segs, radius1=0.2, radius2=0.2,
                                  depth=1.0)
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        for i in range(uvs):
            me.uv_layers.new(name="UV%d" % i)
        ob = bpy.data.objects.new(name, me)
        coll.objects.link(ob)
        return ob

    bpy.ops.wm.read_factory_settings(use_empty=True)
    root = bpy.context.scene.collection
    crate, lamp = bpy.data.collections.new("INT_Crate_Free_A"), bpy.data.collections.new("INT_Lamp_Free_A")
    for c in (crate, lamp):
        root.children.link(c)
    solid("INT_Crate_Free_A", "cube", crate)                                   # 12
    solid("INT_Crate_Free_A_COL", "cube", crate, uvs=0)
    solid("INT_Lamp_Free_A_LOD0", "cyl", lamp, segs=16)                        # 64
    solid("INT_Lamp_Free_A_LOD1", "cyl", lamp, segs=8)
    kit = Path(tempfile.mkdtemp(prefix="mesh_audit_zones_")) / "KIT_Test.blend"
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(kit))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    with bpy.data.libraries.load(str(kit), link=True, relative=False) as (src, dst):
        dst.collections = ["INT_Crate_Free_A", "INT_Lamp_Free_A"]
    lcrate, llamp = dst.collections
    root = bpy.context.scene.collection

    def place(name, coll_src, coll=None, x=0.0):
        e = bpy.data.objects.new(name, None)
        e.instance_type, e.instance_collection, e.location = "COLLECTION", coll_src, (x, 0.0, 0.0)
        (coll or root).objects.link(e)
        return e

    def child(name):
        c = bpy.data.collections.new(name)
        root.children.link(c)
        return c
    place("Crate_1", lcrate)
    place("Crate_2", lcrate, x=2.0)
    hidden = place("Crate_3_H", lcrate, x=4.0)
    place("Crate_4_inEye", lcrate, coll=child("EyeHidden"), x=6.0)
    place("Lamp_1_inExcluded", llamp, coll=child("Excluded"))
    place("Lamp_2", llamp, x=2.0)
    dress = child("SetDressing")
    solid("INT_Crate_Free_A", "cube", dress, uvs=1, subdiv=1)                  # 48, named like the linked crate
    place("Dress_1", dress)
    props = child("PropsEye")
    solid("Vase", "cyl", props, segs=10)                                       # 40
    place("Vase_1", props, x=2.0)
    place("Vase_2", props, x=3.0)
    lcs = bpy.context.view_layer.layer_collection.children
    lcs["EyeHidden"].hide_viewport = True
    lcs["Excluded"].exclude = True
    lcs["SetDressing"].exclude = True
    lcs["PropsEye"].hide_viewport = True
    hidden.hide_set(True)
    bpy.context.view_layer.update()

    r = load()["audit"]()
    linked_crate = next(o for o in bpy.data.objects if o.library is not None and o.name == "INT_Crate_Free_A")
    check(r["render_tris"] == 2 * 12 + 64 + 48 + 2 * 40, "render tris %d, want 216" % r["render_tris"])
    check(r["instances"][linked_crate.name_full]["count"] == 2, "crate placements %s" % r["instances"])
    check(r["skipped_instancers"] == ["Crate_3_H", "Crate_4_inEye", "Lamp_1_inExcluded"],
          "skipped %s" % r["skipped_instancers"])


def test_uv2_on_every_render_mesh_but_collision():
    build()
    rows = {row["name"]: row for row in load()["audit"]()["objects"]}
    check("no-uv2" in rows["INT_Wall_2x3_A_LOD1"]["flags"], "LOD1 without UV2 not flagged")
    col = rows["INT_Wall_2x3_A_COL"]["flags"]
    check("no-uv" not in col and "no-uv2" not in col, "collision shell flagged for UVs: %s" % col)


def test_main_prints_a_table():
    build()
    ns = load()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        ns["main"]()
    text = out.getvalue()
    check("render triangles" in text and "INT_Wall_2x3_A_LOD0" in text and "x3" in text, text[-600:])


for fn in (test_flags_and_counts, test_instances_count_into_render_triangles,
           test_members_the_view_layer_skips_are_evaluated_and_restored, test_uv2_on_every_render_mesh_but_collision,
           test_master_flags_linked_instanced_pieces_and_reports_skipped_instancers,
           test_hidden_or_excluded_sources_and_instancers_count_only_what_shows,
           test_master_with_hidden_zones_counts_what_blender_shows, test_main_prints_a_table):
    case(fn)
failed = [r for r in RESULTS if r[0] == "FAIL"]
print("%d passed, %d failed" % (len(RESULTS) - len(failed), len(failed)))
if failed:
    raise SystemExit("FAILED: " + ", ".join(r[1] for r in failed))
