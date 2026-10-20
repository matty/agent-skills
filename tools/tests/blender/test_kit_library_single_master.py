"""Blender-hosted tests for blender-kit-library's single MASTER helpers in scripts/kit_library.py: new_master and the
organising collections, new_piece / place_piece defaults, the audit's layout checks, snapshot / diff_snapshots /
changes_since, and checkout / integrate (instances follow, names stay clean, materials kept or replaced, refusal when
the piece changed after checkout), plus the command line.

Host: Blender 5.2 (bpy), run from anywhere:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_kit_library_single_master.py
Builds its fixtures in a temp folder, prints PASS <case> / FAIL <case>: <why>, and raises if any case failed.
"""

import os
import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[3]
KIT_LIBRARY = ROOT / "skills" / "blender-kit-library" / "scripts" / "kit_library.py"
TMP = Path(tempfile.mkdtemp(prefix="kit_single_test_"))
MASTER = TMP / "blender" / "MASTER.blend"
WORK = TMP / "blender" / "work" / "KIT_INT.blend"
SNAP = TMP / "blender" / "MASTER.snapshot.json"


def load_ns():
    ns = {}
    exec(compile(KIT_LIBRARY.read_text(encoding="utf-8"), str(KIT_LIBRARY), "exec"), ns)
    return ns


def box(name, size, material=None):
    """A mesh box from the origin to `size`, object at identity, two UV layers."""
    x1, y1, z1 = size
    me = bpy.data.meshes.new(name)
    v = [(0, 0, 0), (x1, 0, 0), (x1, y1, 0), (0, y1, 0), (0, 0, z1), (x1, 0, z1), (x1, y1, z1), (0, y1, z1)]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    me.from_pydata(v, [], f)
    me.uv_layers.new(name="UV0")
    me.uv_layers.new(name="UV1")
    if material is not None:
        me.materials.append(material)
    return bpy.data.objects.new(name, me)


def blender(*args):
    p = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1", *map(str, args)],
                       capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr


def material(name, rgb):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    return mat


def build_master():
    """MASTER.blend at a 0.5 m module: one wall piece, one assembly of two walls, two layout placements."""
    ns = load_ns()
    ns["new_master"](str(MASTER))
    wall = ns["new_piece"]("INT_Wall_2x3_A")
    wall.objects.link(box("INT_Wall_2x3_A", (1.0, 0.1, 1.5), material("M_INT_Plaster", (0.8, 0.8, 0.8))))
    wall["kit_status"] = "grey"
    asm = ns["new_piece"]("ASM_Room_A")
    ns["place_piece"]("INT_Wall_2x3_A", into=asm)
    ns["place_piece"]("INT_Wall_2x3_A", location=(1.0, 0, 0), into=asm)
    ns["place_piece"]("INT_Wall_2x3_A", location=(2.0, 0, 0))
    ns["place_piece"]("ASM_Room_A", location=(0, 4.0, 0))
    ns["save_file"]()
    ns["save_snapshot"](str(SNAP))
    return ns


def test_new_master_organises():
    ns = build_master()
    names = {c.name for c in bpy.context.scene.collection.children}
    assert {"KIT", "ASM", "MASTER", "REF"} <= names, names
    assert bpy.context.scene["kit_layout"] == "single"
    vl = bpy.context.view_layer.layer_collection
    assert vl.children["KIT"].exclude and vl.children["ASM"].exclude and not vl.children["MASTER"].exclude
    assert "INT_Wall_2x3_A" in bpy.data.collections["KIT_INT"].children
    assert "ASM_Room_A" in bpy.data.collections["ASM"].children
    layout = bpy.data.collections["MASTER"].objects
    assert len(layout) == 2 and {o.instance_collection.name for o in layout} == {"INT_Wall_2x3_A", "ASM_Room_A"}
    rep = ns["audit_kit"](0.5)
    assert ns["problems"](rep) == [], ns["problems"](rep)


def test_audit_flags_misplaced_piece_and_visible_kit():
    ns = build_master()
    stray = ns["new_piece"]("INT_Wall_2x3_B", parent=bpy.data.collections["MASTER"])
    stray.objects.link(box("INT_Wall_2x3_B", (1.0, 0.1, 1.5)))
    bpy.context.view_layer.layer_collection.children["KIT"].exclude = False
    probs = ns["problems"](ns["audit_kit"](0.5))
    assert any("INT_Wall_2x3_B is not inside KIT" in p for p in probs), probs
    assert any("KIT is not excluded" in p for p in probs), probs
    assert not any("kit name" in p for p in probs), probs          # MASTER holds empties: an organiser, not odd


def test_snapshot_round_trip_and_diff():
    ns = build_master()
    assert ns["changes_since"](str(SNAP)) == [], ns["describe"](ns["changes_since"](str(SNAP)))
    inst = next(o for o in bpy.data.collections["MASTER"].objects if o.instance_collection.name == "INT_Wall_2x3_A")
    inst.location.x += 1.0
    bpy.data.objects["INT_Wall_2x3_A"].data.vertices[0].co.z -= 0.05
    ns["place_piece"]("INT_Wall_2x3_A", location=(6.0, 0, 0), into=None).name = "Extra"
    bpy.context.view_layer.update()
    lines = ns["describe"](ns["changes_since"](str(SNAP)))
    assert any(l.startswith("object %s changed: matrix" % inst.name) for l in lines), lines
    assert any(l.startswith("object INT_Wall_2x3_A changed: mesh") for l in lines), lines
    assert any(l == "object Extra added" for l in lines), lines
    assert ns["changes_since"](str(TMP / "none.json")) is None


def test_checkout_integrate_replaces_in_place():
    ns = build_master()
    ns["checkout"](str(WORK), ["INT_Wall_2x3_A"])
    assert WORK.exists() and WORK.with_suffix(".checkout.json").exists()
    assert len(bpy.data.scenes) == 1                                  # the scratch scene is gone
    bpy.ops.wm.open_mainfile(filepath=str(WORK))                      # the work file reads like a KIT file
    assert "INT_Wall_2x3_A" in bpy.context.scene.collection.children
    assert "INT_Wall_2x3_A" in bpy.context.view_layer.objects
    ob = bpy.data.objects["INT_Wall_2x3_A"]
    ob.data.vertices[0].co.z = 0.0                                    # unchanged corner, moved top
    for v in ob.data.vertices:
        if v.co.z > 1.0:
            v.co.z = 2.0
    bpy.data.collections["INT_Wall_2x3_A"]["kit_status"] = "modelled"
    bpy.data.materials["M_INT_Plaster"].diffuse_color = (1, 0, 0, 1)
    ns = load_ns()
    ns["save_file"]()
    bpy.ops.wm.open_mainfile(filepath=str(MASTER))
    ns = load_ns()
    rep = ns["integrate"](str(WORK), ["INT_Wall_2x3_A"])
    assert rep["replaced"] == ["INT_Wall_2x3_A"], rep
    coll = bpy.data.collections["INT_Wall_2x3_A"]
    assert coll["kit_status"] == "modelled"
    assert coll.name in bpy.data.collections["KIT_INT"].children
    users = [o for o in bpy.data.objects if o.instance_type == "COLLECTION" and o.instance_collection]
    assert all(o.instance_collection == coll for o in users if o.instance_collection.name.startswith("INT_")), users
    assert sum(1 for o in users if o.instance_collection == coll) == 3     # two in the assembly, one in the layout
    top = max(v.co.z for v in bpy.data.objects["INT_Wall_2x3_A"].data.vertices)
    assert abs(top - 2.0) < 1e-6, top
    names = [d.name for t in ("collections", "meshes", "materials") for d in getattr(bpy.data, t)]
    names += [o.name for o in coll.all_objects] + [o.name for o in bpy.data.objects if "~old" in o.name]
    assert not [n for n in names if "~old" in n or n.endswith(".001")], names     # placements are named .00n
    assert tuple(bpy.data.materials["M_INT_Plaster"].diffuse_color)[:3] != (1, 0, 0)   # MASTER's material kept
    assert len(bpy.data.scenes) == 1


def test_integrate_work_materials_replace():
    ns = build_master()
    ns["checkout"](str(WORK), ["INT_Wall_2x3_A"])
    bpy.ops.wm.open_mainfile(filepath=str(WORK))
    bpy.data.materials["M_INT_Plaster"].diffuse_color = (1, 0, 0, 1)
    load_ns()["save_file"]()
    bpy.ops.wm.open_mainfile(filepath=str(MASTER))
    ns = load_ns()
    ns["integrate"](str(WORK), ["INT_Wall_2x3_A"], materials="work")
    mats = [m.name for m in bpy.data.materials]
    assert mats.count("M_INT_Plaster") == 1 and not [m for m in mats if m.startswith("M_INT_Plaster.")], mats
    assert tuple(bpy.data.materials["M_INT_Plaster"].diffuse_color)[:3] == (1, 0, 0)


def test_integrate_refuses_after_master_changed():
    ns = build_master()
    ns["checkout"](str(WORK), ["INT_Wall_2x3_A"])
    bpy.data.objects["INT_Wall_2x3_A"].data.vertices[0].co.x -= 0.01          # the user edits the piece meanwhile
    try:
        ns["integrate"](str(WORK), ["INT_Wall_2x3_A"])
    except RuntimeError as exc:
        assert "INT_Wall_2x3_A" in str(exc), exc
    else:
        raise AssertionError("integrate overwrote a piece changed after checkout")
    assert "INT_Wall_2x3_A" in bpy.data.collections and "INT_Wall_2x3_A~old" not in bpy.data.collections
    rep = ns["integrate"](str(WORK), ["INT_Wall_2x3_A"], force=True)
    assert rep["replaced"] == ["INT_Wall_2x3_A"], rep


def test_integrate_adds_a_new_piece():
    ns = build_master()
    ns["checkout"](str(WORK), ["INT_Wall_2x3_A"])
    bpy.ops.wm.open_mainfile(filepath=str(WORK))
    ns = load_ns()
    new = ns["new_piece"]("INT_Floor_2x2_A")
    new.objects.link(box("INT_Floor_2x2_A", (1.0, 1.0, 0.1)))
    ns["save_file"]()
    bpy.ops.wm.open_mainfile(filepath=str(MASTER))
    ns = load_ns()
    rep = ns["integrate"](str(WORK), ["INT_Floor_2x2_A"])
    assert rep["added"] == ["INT_Floor_2x2_A"], rep
    assert "INT_Floor_2x2_A" in bpy.data.collections["KIT_INT"].children
    assert ns["problems"](ns["audit_kit"](0.5)) == []


def test_command_line_changes_and_integrate():
    build_master()
    code, text = blender(MASTER, "--python", KIT_LIBRARY, "--", "--changes", SNAP)
    assert code == 0 and "0 change(s)" in text, text
    code, text = blender(MASTER, "--python", KIT_LIBRARY, "--", "--checkout", WORK, "--names", "INT_Wall_2x3_A")
    assert code == 0 and WORK.exists(), text
    code, text = blender(MASTER, "--python", KIT_LIBRARY, "--", "--integrate", WORK, "--names", "INT_Wall_2x3_A")
    assert code == 0 and "replaced: INT_Wall_2x3_A" in text, text
    code, text = blender(MASTER, "--python", KIT_LIBRARY, "--", "--changes", SNAP)
    assert code == 0, text                                         # --integrate saved a fresh snapshot
    assert not os.path.exists(str(MASTER) + "1")                   # no .blend1 backup


CASES = [test_new_master_organises, test_audit_flags_misplaced_piece_and_visible_kit, test_snapshot_round_trip_and_diff,
         test_checkout_integrate_replaces_in_place, test_integrate_work_materials_replace,
         test_integrate_refuses_after_master_changed, test_integrate_adds_a_new_piece,
         test_command_line_changes_and_integrate]


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
