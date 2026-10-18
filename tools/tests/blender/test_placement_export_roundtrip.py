"""Blender-hosted tests for blender-unity-placement-sync's scripts/export_placements.py: dump values in Unity space
(a 90 deg turn, a two-axis rotation with non-uniform scale), apply (assigns with expectations, update, delete, create)
and re-dump, no .blend1 from the command-line save, an ASM scope limited to its collection, the instance_offset and
library-override warnings, and a full loop through placement_merge.py (run with Blender's own Python).

Host: Blender 5.2 (bpy), run from anywhere:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_placement_export_roundtrip.py
Builds its fixtures in a temp folder, prints PASS <case> / FAIL <case>: <why>, and raises if any case failed.
"""

import argparse
import contextlib
import importlib.util
import io
import json
import math
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import bpy
from mathutils import Matrix

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "skills" / "blender-unity-placement-sync" / "scripts"
EXPORT = SCRIPTS / "export_placements.py"
MERGE = SCRIPTS / "placement_merge.py"
TMP = Path(tempfile.mkdtemp(prefix="placement_export_test_"))
KIT = TMP / "blender" / "kits" / "KIT_Test.blend"
ASM = TMP / "blender" / "asm" / "ASM_Shop_A.blend"
MASTER = TMP / "blender" / "MASTER.blend"
PL = TMP / "placements"
H = math.sqrt(0.5)


def save_as(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(path))


def box(name, size, origin=(0.0, 0.0, 0.0)):
    x0, y0, z0 = origin
    x1, y1, z1 = x0 + size[0], y0 + size[1], z0 + size[2]
    me = bpy.data.meshes.new(name)
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    me.from_pydata(v, [], [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)])
    return bpy.data.objects.new(name, me)


def blender(*args):
    p = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1", *map(str, args)],
                       capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr


def run_export(blend, *args):
    return blender(blend, "--python", EXPORT, "--", *args)


def run_merge(cmd, folder, scope):
    """placement_merge.py run in this process (it is plain Python): returns (exit code, printed text)."""
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("placement_merge_under_test", str(MERGE))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    args = argparse.Namespace(dir=str(folder), scope=scope, take=None, take_id=[], allow_deletes=False,
                              accept_source=False)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = mod.merge(args) if cmd == "merge" else mod.commit(args)
    return code, out.getvalue()


def build_kit():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for name, size, origin in (("INT_Wall_2x3_A", (2, 0.2, 3), (0, 0, 0)),
                               ("PROP_Desk_Free_A", (1.4, 0.7, 0.78), (-0.7, -0.35, 0)),
                               ("INT_Off_2x3_A", (2, 0.2, 3), (0, 0, 0))):
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)
        coll.objects.link(box(name, size, origin))
    bpy.data.collections["INT_Off_2x3_A"].instance_offset = (0.5, 0.0, 0.0)
    save_as(KIT)


def link(path, names):
    with bpy.data.libraries.load(str(path), link=True, relative=True) as (src, dst):
        dst.collections = list(names)
    return {c.name: c for c in dst.collections}


def instance(coll, matrix, into, name=None, pid=None):
    ob = bpy.data.objects.new(name or coll.name, None)
    ob.instance_type = "COLLECTION"
    ob.instance_collection = coll
    into.objects.link(ob)
    ob.matrix_world = matrix
    if pid is not None:
        ob["placement_id"] = pid
    return ob


def build_master(path=MASTER, extra=()):
    """MASTER: W1 at (2, 3, 0) turned +90 deg about Z, W2 at the origin, D1 at (2, 3, 1) turned Rz90 Rx30, scale 1 2 3."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    save_as(path)
    colls = link(KIT, ["INT_Wall_2x3_A", "PROP_Desk_Free_A", *extra])
    study = bpy.data.collections.new("study")
    bpy.context.scene.collection.children.link(study)
    rz = lambda d: Matrix.Rotation(math.radians(d), 4, "Z")
    rx = lambda d: Matrix.Rotation(math.radians(d), 4, "X")
    instance(colls["INT_Wall_2x3_A"], Matrix.Translation((2, 3, 0)) @ rz(90), study, "W1")
    instance(colls["INT_Wall_2x3_A"], Matrix(), study, "W2")
    scale = Matrix.Diagonal((1, 2, 3, 1))
    instance(colls["PROP_Desk_Free_A"], Matrix.Translation((2, 3, 1)) @ rz(90) @ rx(30) @ scale, study, "D1")
    for name in extra:
        instance(colls[name], Matrix.Translation((6, 0, 0)), study, "X_" + name)
    save_as(path)


def dump(blend, scope, *extra, folder=PL):
    code, text = run_export(blend, "dump", "--dir", folder, "--scope", scope, *extra)
    assert code == 0, "dump exit %s:\n%s" % (code, text)
    return json.loads((folder / ("%s.blender.json" % scope)).read_text(encoding="utf-8")), text


def write_plan(scope, folder=PL, **kinds):
    plan = {"scope": scope, "side": "blender", "assign": [], "delete": [], "update": [], "create": []}
    plan.update(kinds)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ("%s.plan.blender.json" % scope)).write_text(json.dumps(plan), encoding="utf-8")


def close(a, b, tol=1e-4):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def same_rot(a, b, tol=1e-4):
    return abs(abs(sum(x * y for x, y in zip(a, b))) - 1.0) < tol


def by_key(d):
    return {i["key"]: i for i in d["items"]}


def test_dump_in_unity_space():
    build_kit()
    build_master()
    d, _ = dump(MASTER, "MASTER", "--libraries", "kits/*.blend")
    items = by_key(d)
    assert sorted(items) == ["D1", "W1", "W2"], sorted(items)
    assert d["collection"] is None and d["warnings"] == [], (d["collection"], d["warnings"])
    assert {"INT_Wall_2x3_A", "PROP_Desk_Free_A", "INT_Off_2x3_A"} <= set(d["assets"]), d["assets"]
    w1, w2, d1 = items["W1"], items["W2"], items["D1"]
    assert close(w1["pos"], (-2, 0, -3)) and same_rot(w1["rot"], (0, -H, 0, H)), w1      # -90 deg about Unity Y
    assert close(w2["pos"], (0, 0, 0)) and same_rot(w2["rot"], (0, 0, 0, 1)), w2
    assert close(d1["pos"], (-2, 1, -3)), d1
    assert same_rot(d1["rot"], (0.1830127, -0.6830127, 0.1830127, 0.6830127)), d1          # Unity Euler (30, -90, 0)
    assert close(d1["scl"], (1, 3, 2)), d1                                                  # Blender (1, 2, 3) -> (x, z, y)


def test_apply_round_trip_without_blend1():
    build_kit()
    build_master()
    dump(MASTER, "MASTER", "--libraries", "kits/*.blend")
    write_plan("MASTER", assign=[{"key": k, "id": "id_" + k, "was": "", "asset": a}
                                 for k, a in (("W1", "INT_Wall_2x3_A"), ("W2", "INT_Wall_2x3_A"),
                                              ("D1", "PROP_Desk_Free_A"))])
    code, text = run_export(MASTER, "apply", "--dir", PL, "--scope", "MASTER", "--libraries", "kits/*.blend")
    assert code == 0 and "3 assign" in text, text
    assert not Path(str(MASTER) + "1").exists(), "the command-line apply left MASTER.blend1"
    write_plan("MASTER", delete=["id_W2"],
               update=[{"id": "id_D1", "asset": "PROP_Desk_Free_A", "pos": [-1, 0, -1], "rot": [0, 0, 0, 1],
                        "scl": [1, 1, 1], "key": "x"}],
               create=[{"id": "n1", "asset": "INT_Wall_2x3_A", "pos": [-4, 0, -2], "rot": [0, H, 0, H],
                        "scl": [1, 1, 1], "key": "y"}])
    code, text = run_export(MASTER, "apply", "--dir", PL, "--scope", "MASTER", "--libraries", "kits/*.blend")
    assert code == 0 and "1 delete, 1 update, 1 create" in text, text
    assert not Path(str(MASTER) + "1").exists(), "the second apply left MASTER.blend1"
    d, _ = dump(MASTER, "MASTER", "--libraries", "kits/*.blend")
    items = {i["id"]: i for i in d["items"]}
    assert sorted(items) == ["id_D1", "id_W1", "n1"], sorted(items)
    assert close(items["id_D1"]["pos"], (-1, 0, -1)) and close(items["id_D1"]["scl"], (1, 1, 1)), items["id_D1"]
    assert close(items["n1"]["pos"], (-4, 0, -2)) and same_rot(items["n1"]["rot"], (0, H, 0, H)), items["n1"]
    bpy.ops.wm.open_mainfile(filepath=str(MASTER))
    n1 = next(o for o in bpy.data.objects if o.get("placement_id") == "n1")
    want = Matrix.Translation((4, 2, 0)) @ Matrix.Rotation(math.radians(-90), 4, "Z")     # Unity +90 Y = Blender -90 Z
    assert all(abs(n1.matrix_world[i][j] - want[i][j]) < 1e-4 for i in range(4) for j in range(4)), n1.matrix_world
    assert n1.name in bpy.context.scene.collection.objects, "MASTER creates should land in the scene collection"


def test_assign_refuses_a_changed_object():
    build_kit()
    build_master()
    write_plan("MASTER", assign=[{"key": "W1", "id": "x1", "was": "zzz", "asset": "INT_Wall_2x3_A"},
                                 {"key": "W2", "id": "x2", "was": "", "asset": "PROP_Desk_Free_A"}])
    code, text = run_export(MASTER, "apply", "--dir", PL, "--scope", "MASTER")
    assert code == 1, "apply exit %s:\n%s" % (code, text)
    assert "has id ''" in text and "instances INT_Wall_2x3_A" in text, text
    bpy.ops.wm.open_mainfile(filepath=str(MASTER))
    assert all(o.get("placement_id") is None for o in bpy.data.objects), "an assign went through"


def test_asm_scope_is_its_collection():
    build_kit()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    save_as(ASM)
    walls = link(KIT, ["INT_Wall_2x3_A"])["INT_Wall_2x3_A"]
    asm = bpy.data.collections.new("ASM_Shop_A")
    bpy.context.scene.collection.children.link(asm)
    instance(walls, Matrix(), asm, "A0", pid="a0")
    instance(walls, Matrix.Translation((2, 0, 0)), asm, "A1", pid="a1")
    instance(walls, Matrix.Translation((0, 5, 0)), bpy.context.scene.collection, "Context")    # not in the assembly
    save_as(ASM)
    d, _ = dump(ASM, "ASM_Shop_A", "--libraries", "../kits/*.blend")
    assert d["collection"] == "ASM_Shop_A" and sorted(by_key(d)) == ["A0", "A1"], (d["collection"], by_key(d).keys())
    code, text = run_export(ASM, "dump", "--dir", PL, "--scope", "ASM_Shop_A", "--collection", "Nope")
    assert code == 1 and "no local collection 'Nope'" in text, text
    write_plan("ASM_Shop_A", create=[{"id": "n2", "asset": "INT_Wall_2x3_A", "pos": [-4, 0, 0], "rot": [0, 0, 0, 1],
                                      "scl": [1, 1, 1], "key": "z"}])
    code, text = run_export(ASM, "apply", "--dir", PL, "--scope", "ASM_Shop_A", "--libraries", "../kits/*.blend")
    assert code == 0, text
    bpy.ops.wm.open_mainfile(filepath=str(ASM))
    n2 = next(o for o in bpy.data.objects if o.get("placement_id") == "n2")
    assert [c.name for c in n2.users_collection] == ["ASM_Shop_A"], [c.name for c in n2.users_collection]


def test_instance_offset_warning():
    build_kit()
    build_master(extra=("INT_Off_2x3_A",))
    d, text = dump(MASTER, "MASTER", "--libraries", "kits/*.blend")
    assert any("INT_Off_2x3_A has instance_offset (0.5, 0.0, 0.0)" in w for w in d["warnings"]), d["warnings"]
    assert "WARNING collection INT_Off_2x3_A" in text, text


def test_library_override_is_skipped_and_named():
    """The UI's Make Library Override (Object menu) on a placed assembly: the instancing empty and its id go, the
    overridden pieces arrive as override objects. The dump skips them, warns, and the placement reads as deleted."""
    test_asm_scope_is_its_collection()                  # builds the ASM file
    bpy.ops.wm.read_factory_settings(use_empty=True)
    save_as(MASTER)
    asm = link(ASM, ["ASM_Shop_A"])["ASM_Shop_A"]
    inst = instance(asm, Matrix.Translation((5, 5, 0)), bpy.context.scene.collection, "Shop", pid="m1")
    keep = instance(asm, Matrix.Translation((9, 5, 0)), bpy.context.scene.collection, "Shop2", pid="m2")
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    inst.select_set(True)
    bpy.context.view_layer.objects.active = inst
    assert bpy.ops.object.make_override_library() == {"FINISHED"}
    assert "Shop" not in bpy.data.objects, "fixture: the operator kept the instancing empty"
    over = [o.name for o in bpy.context.scene.objects if o.override_library is not None]
    assert len(over) >= 2, "fixture: no override objects were made (%s)" % over
    save_as(MASTER)
    d, text = dump(MASTER, "MASTER")
    assert [i["key"] for i in d["items"]] == [keep.name], [i["key"] for i in d["items"]]
    assert any("library-override" in w for w in d["warnings"]), d["warnings"]


def test_deleting_a_parent_keeps_its_children_in_place():
    """Unity deleted a placement that another one is parented under in Blender: the child must not move."""
    build_kit()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    save_as(MASTER)
    colls = link(KIT, ["INT_Wall_2x3_A", "PROP_Desk_Free_A"])
    folder = bpy.data.objects.new("Folder", None)                  # a turned, moved folder empty above the parent
    bpy.context.scene.collection.objects.link(folder)
    folder.matrix_world = Matrix.Translation((1, 2, 0)) @ Matrix.Rotation(math.radians(30), 4, "Z")
    parent = instance(colls["INT_Wall_2x3_A"], Matrix.Translation((5, 0, 0)) @ Matrix.Rotation(math.radians(90), 4, "Z"),
                      bpy.context.scene.collection, "Parent", pid="p")
    child = instance(colls["PROP_Desk_Free_A"], Matrix.Translation((6, 1, 0)), bpy.context.scene.collection, "Child",
                     pid="c")
    lone = instance(colls["PROP_Desk_Free_A"], Matrix.Translation((8, 1, 0)), bpy.context.scene.collection, "Lone",
                    pid="l")
    # Parent the way scripts usually do (no parent inverse), keeping each world pose: then a bare objects.remove()
    # would make every child jump to its parent-relative transform.
    for ob, new_parent in ((parent, folder), (child, parent), (lone, parent)):
        mw = ob.matrix_world.copy()
        ob.parent = new_parent
        bpy.context.view_layer.update()
        ob.matrix_world = mw
    bpy.context.view_layer.update()
    assert child.matrix_parent_inverse == Matrix.Identity(4)
    want = {o.name: o.matrix_world.copy() for o in (child, lone)}
    assert (want["Child"].translation - Matrix.Translation((6, 1, 0)).translation).length < 1e-5
    save_as(MASTER)
    write_plan("MASTER", delete=["p"])
    code, text = run_export(MASTER, "apply", "--dir", PL, "--scope", "MASTER")
    assert code == 0 and "1 delete" in text, text
    bpy.ops.wm.open_mainfile(filepath=str(MASTER))
    for name, mw in want.items():
        ob = bpy.data.objects[name]
        assert ob.parent and ob.parent.name == "Folder", (name, ob.parent)
        assert all(abs(ob.matrix_world[i][j] - mw[i][j]) < 1e-4 for i in range(4) for j in range(4)), (
            name, ob.matrix_world, mw)
    assert "Parent" not in bpy.data.objects


def build_parented(folder_between=False):
    """MASTER with a table placement (id bbbb_table) and a crate (aaaa_crate, whose id sorts first) parented under it,
    optionally through a plain empty, the way scripts parent (no parent inverse). Returns the dump's items by id."""
    build_kit()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    save_as(MASTER)
    colls = link(KIT, ["PROP_Desk_Free_A", "INT_Wall_2x3_A"])
    scene = bpy.context.scene.collection
    table = instance(colls["PROP_Desk_Free_A"], Matrix.Translation((2, 2, 0)) @ Matrix.Rotation(math.radians(30), 4, "Z"),
                     scene, "Table", pid="bbbb_table")
    crate = instance(colls["INT_Wall_2x3_A"], Matrix.Translation((2.3, 2.1, 0.8)), scene, "Crate", pid="aaaa_crate")
    chain = [(crate, table)]
    if folder_between:
        top = bpy.data.objects.new("TableTop", None)
        scene.objects.link(top)
        top.matrix_world = Matrix.Translation((2, 2, 0.75))
        chain = [(top, table), (crate, top)]
    for ob, parent in chain:
        mw = ob.matrix_world.copy()
        ob.parent = parent
        bpy.context.view_layer.update()
        ob.matrix_world = mw
    bpy.context.view_layer.update()
    save_as(MASTER)
    d, _ = dump(MASTER, "MASTER")
    return {i["id"]: i for i in d["items"]}


def moved(item, dx):
    return dict(item, pos=[item["pos"][0] + dx, item["pos"][1], item["pos"][2]], key="u")


def apply_and_dump(**plan):
    write_plan("MASTER", **plan)
    code, text = run_export(MASTER, "apply", "--dir", PL, "--scope", "MASTER")
    assert code == 0, text
    d, _ = dump(MASTER, "MASTER")
    return {i["id"]: i for i in d["items"]}


def test_moving_a_parent_leaves_its_child_placements():
    """Unity moved only the table: the crate parented under it in Blender stays where it is."""
    for folder_between in (False, True):
        was = build_parented(folder_between)
        now = apply_and_dump(update=[moved(was["bbbb_table"], 1.0)])
        assert close(now["bbbb_table"]["pos"], moved(was["bbbb_table"], 1.0)["pos"]), (folder_between, now)
        assert close(now["aaaa_crate"]["pos"], was["aaaa_crate"]["pos"]), (folder_between, now["aaaa_crate"], was)
        assert same_rot(now["aaaa_crate"]["rot"], was["aaaa_crate"]["rot"]), (folder_between, now["aaaa_crate"])


def test_parent_and_child_both_moved_land_where_planned():
    """Unity moved table and crate together; the crate's id sorts first, so a naive apply sets it, then drags it."""
    was = build_parented()
    now = apply_and_dump(update=[moved(was["aaaa_crate"], 1.0), moved(was["bbbb_table"], 1.0)])
    for pid in ("aaaa_crate", "bbbb_table"):
        assert close(now[pid]["pos"], moved(was[pid], 1.0)["pos"]), (pid, now[pid], was[pid])


def test_unmoved_and_constrained_placements_stay_put():
    """Only placements under a moved ancestor are touched. A Copy Location placement (it ignores matrix_world writes
    in part, so re-setting it every apply would creep 3 m each time) stays where it is through three empty plans and
    a plan that moves another placement; the dump warns about it."""
    build_kit()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    save_as(MASTER)
    colls = link(KIT, ["INT_Wall_2x3_A", "PROP_Desk_Free_A"])
    scene = bpy.context.scene.collection
    base_ = instance(colls["INT_Wall_2x3_A"], Matrix(), scene, "Base", pid="base")
    mover = instance(colls["PROP_Desk_Free_A"], Matrix.Translation((6, 0, 0)), scene, "Mover", pid="mover")
    con = instance(colls["PROP_Desk_Free_A"], Matrix.Translation((2, 0, 0)), scene, "Con", pid="con")
    target = bpy.data.objects.new("Target", None)
    scene.objects.link(target)
    target.location = (0, 3, 0)
    c = con.constraints.new("COPY_LOCATION")
    c.target = target
    c.use_offset = True
    con.parent = base_
    bpy.context.view_layer.update()
    save_as(MASTER)
    was, text = dump(MASTER, "MASTER")
    assert any("constraints: Con" in w for w in was["warnings"]), was["warnings"]
    was = {i["id"]: i for i in was["items"]}
    for _ in range(3):
        now = apply_and_dump()
        assert close(now["con"]["pos"], was["con"]["pos"]), ("empty plan moved it", now["con"], was["con"])
    now = apply_and_dump(update=[moved(was["mover"], 1.0)])
    assert close(now["mover"]["pos"], moved(was["mover"], 1.0)["pos"]), now["mover"]
    assert close(now["con"]["pos"], was["con"]["pos"]) and close(now["base"]["pos"], was["base"]["pos"]), now


def test_failed_dump_leaves_no_stale_file():
    build_kit()
    build_master()
    dump(MASTER, "MASTER")
    out = PL / "MASTER.blender.json"
    assert out.exists()
    code, text = run_export(MASTER, "dump", "--dir", PL, "--scope", "MASTER", "--collection", "Nope")
    assert code == 1 and "no local collection 'Nope'" in text, text
    assert not out.exists(), "a failed dump left the previous MASTER.blender.json for the merge to read"


def test_full_loop_with_merge():
    """First sync from Blender into an empty Unity side, then a Unity-side move synced back, then a clean re-merge."""
    build_kit()
    build_master()
    loop = TMP / "placements_loop"                      # a fresh folder: no snapshot yet
    unity = {"scope": "MASTER", "side": "unity", "target": "scene:MASTER", "items": [],
             "assets": ["INT_Wall_2x3_A", "PROP_Desk_Free_A"]}

    def write_unity():
        loop.mkdir(parents=True, exist_ok=True)
        (loop / "MASTER.unity.json").write_text(json.dumps(unity), encoding="utf-8")

    def blender_side():
        code, text = run_export(MASTER, "apply", "--dir", loop, "--scope", "MASTER", "--libraries", "kits/*.blend")
        assert code == 0, text
        dump(MASTER, "MASTER", "--libraries", "kits/*.blend", folder=loop)

    dump(MASTER, "MASTER", "--libraries", "kits/*.blend", folder=loop)
    write_unity()
    code, text = run_merge("merge", loop, "MASTER")
    assert code == 0, text
    plan_u = json.loads((loop / "MASTER.plan.unity.json").read_text(encoding="utf-8"))
    assert len(plan_u["create"]) == 3, plan_u
    unity["items"] = [dict(c, key=str(n), name=c["asset"]) for n, c in enumerate(plan_u["create"])]   # Unity applied
    write_unity()
    blender_side()
    code, text = run_merge("commit", loop, "MASTER")
    assert code == 0, text
    desk = next(i for i in unity["items"] if i["asset"] == "PROP_Desk_Free_A")
    desk["pos"] = [-2.5, 1.0, -3.0]                       # someone moves the desk in Unity
    write_unity()
    dump(MASTER, "MASTER", "--libraries", "kits/*.blend", folder=loop)
    code, text = run_merge("merge", loop, "MASTER")
    assert code == 0 and "unity   -> blender update" in text, text
    blender_side()
    code, text = run_merge("commit", loop, "MASTER")
    assert code == 0, text
    code, text = run_merge("merge", loop, "MASTER")
    assert code == 0 and "unchanged 3" in text, text
    snap = json.loads((loop / "MASTER.synced.json").read_text(encoding="utf-8"))
    assert snap["source"] == {"blender_file": "master.blend", "blender_collection": None,
                              "unity_target": "scene:MASTER"}, snap["source"]


CASES = [test_dump_in_unity_space, test_apply_round_trip_without_blend1, test_assign_refuses_a_changed_object,
         test_asm_scope_is_its_collection, test_instance_offset_warning, test_library_override_is_skipped_and_named,
         test_deleting_a_parent_keeps_its_children_in_place, test_moving_a_parent_leaves_its_child_placements,
         test_parent_and_child_both_moved_land_where_planned, test_unmoved_and_constrained_placements_stay_put,
         test_failed_dump_leaves_no_stale_file,
         test_full_loop_with_merge]


def main():
    failed = []
    for fn in CASES:
        try:
            fn()
            print("PASS %s" % fn.__name__)
        except Exception as e:
            failed.append(fn.__name__)
            print("FAIL %s: %s" % (fn.__name__, e))
            traceback.print_exc()
    shutil.rmtree(TMP, ignore_errors=True)
    print("%d case(s), %d failed" % (len(CASES), len(failed)))
    if failed:
        raise RuntimeError("failed: " + ", ".join(failed))


main()
