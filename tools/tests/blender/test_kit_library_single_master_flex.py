"""Flexibility tests for blender-kit-library's single MASTER: the work-file route with other skills' scripts
(blender-to-unity, uv-unwrapping, vrchat-world-qa, blender-unity-placement-sync), parallel work files, the user
editing MASTER while a piece is checked out, assemblies (nested too), LODs and collision replacing a greybox,
placement ids, textures, stale and repeated integrates, unsaved live edits, snapshot noise and snapshot speed.

Host: Blender 5.2 (bpy), run from anywhere:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_kit_library_single_master_flex.py
Builds its fixtures in a temp folder, prints PASS <case> / FAIL <case>: <why>, and raises if any case failed.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[3]
SKILLS = ROOT / "skills"
KIT_LIBRARY = SKILLS / "blender-kit-library" / "scripts" / "kit_library.py"
QA = SKILLS / "vrchat-world-qa" / "scripts" / "qa_measure.py"
EXPORT = SKILLS / "blender-to-unity" / "scripts" / "batch_export_fbx.py"
UV_AUDIT = SKILLS / "uv-unwrapping" / "scripts" / "uv_audit.py"
PLACEMENTS = SKILLS / "blender-unity-placement-sync" / "scripts" / "export_placements.py"
TMP = Path(tempfile.mkdtemp(prefix="kit_single_flex_"))
MASTER = TMP / "blender" / "MASTER.blend"
WORK = TMP / "blender" / "work"
SNAP = TMP / "blender" / "MASTER.snapshot.json"


def load(path, **extra):
    ns = dict(extra, __file__=str(path))
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)
    return ns


def box(name, size, origin=(0.0, 0.0, 0.0), material=None):
    x0, y0, z0 = origin
    x1, y1, z1 = x0 + size[0], y0 + size[1], z0 + size[2]
    me = bpy.data.meshes.new(name)
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    me.from_pydata(v, [], [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)])
    me.uv_layers.new(name="UV0")
    if material is not None:
        me.materials.append(material)
    return bpy.data.objects.new(name, me)


def material(name, rgb):
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None:                # Blender 5 gives new materials a node tree already
        mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    return mat


def blender(*args):
    p = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1", *map(str, args)],
                       capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout + p.stderr


def run_in(blend, code):
    """Run `code` headless on `blend` (kit_library loaded as ns); returns (exit code, output)."""
    script = TMP / ("task_%d.py" % time.perf_counter_ns())
    script.write_text("import bpy\nns = {}\nexec(open(%r, encoding='utf-8').read(), ns)\n" % str(KIT_LIBRARY) + code,
                      encoding="utf-8")
    return blender(blend, "--python", script)


def build():
    """MASTER at a 1 m module: INT wall (2x3) and PROP desk, ASM_Room_A of two walls, a layout of a wall, a desk and
    the room, each placement with a placement_id."""
    if TMP.joinpath("blender").exists():
        shutil.rmtree(TMP / "blender")
    kit = load(KIT_LIBRARY)
    kit["new_master"](str(MASTER))
    wall = kit["new_piece"]("INT_Wall_2x3_A")
    wall.objects.link(box("INT_Wall_2x3_A", (2.0, 0.2, 3.0), material=material("M_INT_Plaster", (0.8, 0.8, 0.8))))
    wall["kit_status"] = "grey"
    desk = kit["new_piece"]("PROP_Desk_Free_A")
    desk.objects.link(box("PROP_Desk_Free_A", (1.4, 0.7, 0.78), (-0.7, -0.35, 0.0),
                          material=material("M_PROP_Wood", (0.4, 0.25, 0.1))))
    desk["kit_status"] = "grey"
    room = kit["new_piece"]("ASM_Room_A")
    kit["place_piece"]("INT_Wall_2x3_A", into=room).name = "RoomWall1"
    kit["place_piece"]("INT_Wall_2x3_A", location=(2, 0, 0), into=room).name = "RoomWall2"
    for name, piece, loc in (("LayWall", "INT_Wall_2x3_A", (10, 0, 0)), ("LayDesk", "PROP_Desk_Free_A", (5, 5, 0)),
                             ("LayRoom", "ASM_Room_A", (0, 10, 0))):
        inst = kit["place_piece"](piece, location=loc)
        inst.name = name
        inst["placement_id"] = "id-" + name
    kit["save_file"]()
    kit["save_snapshot"](str(SNAP))
    return kit


def instances_of(name):
    return sorted(o.name for o in bpy.data.objects if o.instance_type == "COLLECTION" and o.instance_collection
                  and o.instance_collection.name == name)


def test_work_file_runs_other_skills_scripts():
    kit = build()
    work = WORK / "T-UV-INT" / "KIT_INT.blend"
    kit["checkout"](str(work), ["INT_Wall_2x3_A"])
    code, out = blender(work, "--python", KIT_LIBRARY, "--", "--audit", "--module", "1.0")
    assert code == 0 and "1 piece(s), 0 problem(s)" in out, out[-1500:]
    # a UV task: operators need the objects in the view layer, which the work file gives them
    code, out = run_in(work, """
for ob in bpy.data.collections["INT_Wall_2x3_A"].all_objects:
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")
    ob.data.uv_layers.new(name="UV1")
bpy.data.collections["INT_Wall_2x3_A"]["kit_status"] = "uv"
ns["save_file"]()
print("UV DONE")
""")
    assert code == 0 and "UV DONE" in out, out[-1500:]
    code, out = blender(work, "--python", UV_AUDIT, "--", "--objects", "INT_*", "--purpose", "tiling", "--map", "1024",
                        "--td", "512")
    assert code in (0, 1) and "INT_Wall_2x3_A" in out, out[-1500:]
    code, out = blender(work, "--python", QA, "--", "--module", "1.0", "--expect-status", "uv",
                        "--json", TMP / "qa.json")
    assert "[qa] role kit" in out, out[-1500:]
    rep = json.loads((TMP / "qa.json").read_text(encoding="utf-8"))
    assert [p["piece"] for p in rep["pieces"]] == ["INT_Wall_2x3_A"], rep["pieces"]
    fbx = TMP / "export" / "fbx"
    code, out = blender(work, "--python", EXPORT, "--", "--kit", "--dir", fbx)
    assert code == 0 and (fbx / "INT" / "INT_Wall_2x3_A.fbx").exists(), out[-1500:]
    assert not (fbx / "PROP").exists(), "the work file exported a piece it does not hold"
    rep = kit["integrate"](str(work), ["INT_Wall_2x3_A"])
    me = bpy.data.objects["INT_Wall_2x3_A"].data
    assert [uv.name for uv in me.uv_layers] == ["UV0", "UV1"], [uv.name for uv in me.uv_layers]
    assert bpy.data.collections["INT_Wall_2x3_A"]["kit_status"] == "uv"
    assert bpy.data.collections["PROP_Desk_Free_A"]["kit_status"] == "grey"
    assert kit["problems"](kit["audit_kit"](1.0)) == [], kit["problems"](kit["audit_kit"](1.0))


def test_parallel_work_files_integrate_in_any_order():
    kit = build()
    w_int, w_prop = WORK / "a" / "KIT_INT.blend", WORK / "b" / "KIT_PROP.blend"
    kit["checkout"](str(w_int), ["INT_Wall_2x3_A"])
    kit["checkout"](str(w_prop), ["PROP_Desk_Free_A"])
    for w, piece, z in ((w_int, "INT_Wall_2x3_A", 3.0), (w_prop, "PROP_Desk_Free_A", 0.78)):
        code, out = run_in(w, """
me = bpy.data.objects[%r].data
for v in me.vertices:
    if v.co.z > %r - 1e-4:
        v.co.z += 0.5
ns["save_file"]()
""" % (piece, z))
        assert code == 0, out[-1500:]
    kit["integrate"](str(w_prop), ["PROP_Desk_Free_A"])        # the second one checked out goes in first
    kit["integrate"](str(w_int), ["INT_Wall_2x3_A"])
    tops = {n: max(v.co.z for v in bpy.data.objects[n].data.vertices) for n in ("INT_Wall_2x3_A", "PROP_Desk_Free_A")}
    assert abs(tops["INT_Wall_2x3_A"] - 3.5) < 1e-5 and abs(tops["PROP_Desk_Free_A"] - 1.28) < 1e-5, tops
    assert len([c for c in bpy.data.collections if c.name.startswith(("INT_", "PROP_"))]) == 2


def test_user_edits_elsewhere_survive_an_integrate():
    kit = build()
    work = WORK / "KIT_INT.blend"
    kit["checkout"](str(work), ["INT_Wall_2x3_A"])
    # meanwhile the user moves a placement, edits the desk and adds a scale figure
    bpy.data.objects["LayDesk"].location.x = 6.0
    bpy.data.objects["PROP_Desk_Free_A"].data.vertices[0].co.x -= 0.1
    bpy.data.collections["REF"].objects.link(box("Figure_1m6", (0.4, 0.3, 1.6)))
    code, out = run_in(work, "bpy.data.collections['INT_Wall_2x3_A']['kit_status'] = 'modelled'\nns['save_file']()\n")
    assert code == 0, out[-1500:]
    kit["integrate"](str(work), ["INT_Wall_2x3_A"])
    assert abs(bpy.data.objects["LayDesk"].location.x - 6.0) < 1e-6
    assert abs(bpy.data.objects["PROP_Desk_Free_A"].data.vertices[0].co.x - (-0.8)) < 1e-6
    assert "Figure_1m6" in bpy.data.collections["REF"].objects
    lines = kit["describe"](kit["changes_since"](str(SNAP)))
    assert any(l.startswith("object LayDesk changed: matrix") for l in lines), lines
    assert any(l.startswith("object PROP_Desk_Free_A changed: mesh") for l in lines), lines
    assert any(l == "object Figure_1m6 added" for l in lines), lines
    assert kit["problems"](kit["audit_kit"](1.0)) == [], kit["problems"](kit["audit_kit"](1.0))   # REF is no stray


def test_integrate_refuses_a_piece_the_user_deleted_or_renamed():
    kit = build()
    work = WORK / "KIT_INT.blend"
    kit["checkout"](str(work), ["INT_Wall_2x3_A"])
    bpy.data.collections["INT_Wall_2x3_A"].name = "INT_Wall_2x3_B"           # the user renames it meanwhile
    try:
        kit["integrate"](str(work), ["INT_Wall_2x3_A"])
    except RuntimeError as exc:
        assert "INT_Wall_2x3_A removed" in str(exc), exc
    else:
        raise AssertionError("integrated over a piece the user renamed")


def test_assembly_round_trip_keeps_one_copy_of_each_piece():
    kit = build()
    work = WORK / "KIT_ASM.blend"
    kit["checkout"](str(work), ["ASM_Room_A"])
    code, out = run_in(work, """
room = bpy.data.collections["ASM_Room_A"]
bpy.data.objects["RoomWall2"].location.x = 2.5
ns["place_piece"]("INT_Wall_2x3_A", location=(0, 2, 0), rot_z=90, into=room).name = "RoomWall3"
ns["save_file"]()
""")
    assert code == 0, out[-1500:]
    rep = kit["integrate"](str(work), ["ASM_Room_A"])
    assert rep["replaced"] == ["ASM_Room_A"] and "INT_Wall_2x3_A" in rep["kept"], rep
    assert [c.name for c in bpy.data.collections if c.name.startswith("INT_")] == ["INT_Wall_2x3_A"]
    room = bpy.data.collections["ASM_Room_A"]
    assert sorted(o.name for o in room.objects) == ["RoomWall1", "RoomWall2", "RoomWall3"], list(room.objects)
    assert all(o.instance_collection == bpy.data.collections["INT_Wall_2x3_A"] for o in room.objects)
    assert abs(bpy.data.objects["RoomWall2"].location.x - 2.5) < 1e-6
    assert bpy.data.objects["LayRoom"].instance_collection == room
    assert room.name in bpy.data.collections["ASM"].children
    assert len([m for m in bpy.data.materials if m.name.startswith("M_INT_Plaster")]) == 1


def test_nested_assembly():
    kit = build()
    block = kit["new_piece"]("ASM_Block_A")
    kit["place_piece"]("ASM_Room_A", into=block).name = "BlockRoom"
    kit["place_piece"]("PROP_Desk_Free_A", location=(1, 1, 0), into=block).name = "BlockDesk"
    work = WORK / "KIT_BLOCK.blend"
    kit["checkout"](str(work), ["ASM_Block_A"])
    code, out = run_in(work, "bpy.data.objects['BlockDesk'].location.y = 1.5\nns['save_file']()\n")
    assert code == 0, out[-1500:]
    kit["integrate"](str(work), ["ASM_Block_A"])
    names = sorted(c.name for c in bpy.data.collections)
    assert names == sorted(["KIT", "KIT_INT", "KIT_PROP", "ASM", "MASTER", "REF", "INT_Wall_2x3_A",
                            "PROP_Desk_Free_A", "ASM_Room_A", "ASM_Block_A"]), names
    assert bpy.data.objects["BlockRoom"].instance_collection == bpy.data.collections["ASM_Room_A"]
    assert abs(bpy.data.objects["BlockDesk"].location.y - 1.5) < 1e-6


def test_lods_and_collision_replace_the_greybox():
    kit = build()
    work = WORK / "KIT_INT.blend"
    kit["checkout"](str(work), ["INT_Wall_2x3_A"])
    code, out = run_in(work, """
coll = bpy.data.collections["INT_Wall_2x3_A"]
mat = bpy.data.materials["M_INT_Plaster"]
bpy.data.objects.remove(bpy.data.objects["INT_Wall_2x3_A"])
for suffix in ("_LOD0", "_LOD1", "_COL"):
    me = bpy.data.meshes.new("INT_Wall_2x3_A" + suffix)
    me.from_pydata([(0,0,0),(2,0,0),(2,0.2,0),(0,0.2,0),(0,0,3),(2,0,3),(2,0.2,3),(0,0.2,3)], [],
                   [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)])
    me.uv_layers.new(name="UV0"); me.uv_layers.new(name="UV1")
    if suffix != "_COL":
        me.materials.append(mat)
    coll.objects.link(bpy.data.objects.new("INT_Wall_2x3_A" + suffix, me))
coll["kit_status"] = "modelled"
ns["save_file"]()
""")
    assert code == 0, out[-1500:]
    kit["integrate"](str(work), ["INT_Wall_2x3_A"])
    coll = bpy.data.collections["INT_Wall_2x3_A"]
    assert sorted(o.name for o in coll.objects) == ["INT_Wall_2x3_A_COL", "INT_Wall_2x3_A_LOD0",
                                                     "INT_Wall_2x3_A_LOD1"], list(coll.objects)
    assert "INT_Wall_2x3_A" not in bpy.data.objects or bpy.data.objects["INT_Wall_2x3_A"].instance_type == "COLLECTION"
    assert not [m.name for m in bpy.data.meshes if m.users == 0], [m.name for m in bpy.data.meshes if m.users == 0]
    assert len(instances_of("INT_Wall_2x3_A")) == 3
    assert kit["problems"](kit["audit_kit"](1.0)) == [], kit["problems"](kit["audit_kit"](1.0))


def test_placement_ids_and_placement_sync_scopes():
    kit = build()
    work = WORK / "KIT_INT.blend"
    kit["checkout"](str(work), ["INT_Wall_2x3_A"])
    kit["integrate"](str(work), ["INT_Wall_2x3_A"])
    assert bpy.data.objects["LayWall"]["placement_id"] == "id-LayWall"
    assert bpy.data.objects["LayWall"].instance_collection == bpy.data.collections["INT_Wall_2x3_A"]
    kit["save_file"]()
    sync = load(PLACEMENTS)
    out = TMP / "placements"
    data = json.loads(Path(sync["dump"](str(out), "MASTER")).read_text(encoding="utf-8"))
    assert sorted(i["key"] for i in data["items"]) == ["LayDesk", "LayRoom", "LayWall"], data["items"]
    assert {"INT_Wall_2x3_A", "PROP_Desk_Free_A", "ASM_Room_A"} <= set(data["assets"]), data["assets"]
    data = json.loads(Path(sync["dump"](str(out), "ASM_Room_A")).read_text(encoding="utf-8"))
    assert sorted(i["key"] for i in data["items"]) == ["RoomWall1", "RoomWall2"], data["items"]
    try:
        sync["dump"](str(out), "ASM_Missing_A")
    except KeyError:
        pass
    else:
        raise AssertionError("a single MASTER dumped its whole scene for a scope it has no collection for")


def test_textures_resolve_after_integrate():
    kit = build()
    tex = TMP / "blender" / "textures" / "INT" / "T_INT_Plaster_BaseColor.png"
    tex.parent.mkdir(parents=True, exist_ok=True)
    img = bpy.data.images.new("tmp", 4, 4)
    img.filepath_raw = str(tex)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    work = WORK / "T-TEX-INT" / "KIT_INT.blend"
    kit["checkout"](str(work), ["INT_Wall_2x3_A"])
    code, out = run_in(work, """
mat = bpy.data.materials["M_INT_Plaster"]
nt = mat.node_tree
node = nt.nodes.new("ShaderNodeTexImage")
node.image = bpy.data.images.load(%r)
node.image.filepath = bpy.path.relpath(node.image.filepath)
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
nt.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
bpy.data.collections["INT_Wall_2x3_A"]["kit_status"] = "textured"
ns["save_file"]()
print("REL", node.image.filepath)
""" % str(tex))
    assert code == 0 and "REL //" in out, out[-1500:]
    kit["integrate"](str(work), ["INT_Wall_2x3_A"], materials="work")
    imgs = [i for i in bpy.data.images if i.source == "FILE"]
    assert len(imgs) == 1 and os.path.exists(bpy.path.abspath(imgs[0].filepath)), [(i.name, i.filepath) for i in imgs]
    nt = bpy.data.materials["M_INT_Plaster"].node_tree
    assert any(n.type == "TEX_IMAGE" for n in nt.nodes)


def test_repeat_and_stale_integrates():
    kit = build()
    work = WORK / "KIT_INT.blend"
    kit["checkout"](str(work), ["INT_Wall_2x3_A"])
    kit["integrate"](str(work), ["INT_Wall_2x3_A"])
    kit["integrate"](str(work), ["INT_Wall_2x3_A"])                 # the same file again: nothing changed here
    assert len([c for c in bpy.data.collections if c.name.startswith("INT_")]) == 1
    bpy.data.objects["INT_Wall_2x3_A"].data.vertices[0].co.y += 0.01  # the user edits it after the integrate
    try:
        kit["integrate"](str(work), ["INT_Wall_2x3_A"])
    except RuntimeError:
        pass
    else:
        raise AssertionError("a stale work file overwrote the user's later edit")


def test_checkout_takes_unsaved_live_edits():
    kit = build()
    bpy.data.objects["INT_Wall_2x3_A"].data.vertices[0].co.z = -0.25        # unsaved, as in a live session
    work = WORK / "KIT_INT.blend"
    kit["checkout"](str(work), ["INT_Wall_2x3_A"])
    code, out = run_in(work, "print('LOWEST', min(v.co.z for v in bpy.data.objects['INT_Wall_2x3_A'].data.vertices))")
    assert "LOWEST -0.25" in out, out[-1500:]
    assert len(bpy.data.scenes) == 1                       # (is_dirty stays False for script edits in background)


def test_snapshot_ignores_ui_noise_but_not_edits():
    kit = build()
    ob = bpy.data.objects["INT_Wall_2x3_A"]
    lc = bpy.context.view_layer.layer_collection.children["KIT"]
    lc.exclude = False                                       # the user ticks KIT on to look at the piece
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    nt = bpy.data.materials["M_INT_Plaster"].node_tree
    for n in nt.nodes:
        n.location.x += 50                                    # nodes dragged in the shader editor
        n.select = True
    lines = kit["describe"](kit["changes_since"](str(SNAP)))
    assert lines == [], lines
    next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED").inputs["Roughness"].default_value = 0.2
    lines = kit["describe"](kit["changes_since"](str(SNAP)))
    assert "material M_INT_Plaster changed: nodes" in lines, lines


def test_snapshot_speed():
    kit = build()
    for i in range(30):
        c = kit["new_piece"]("INT_Bay%d_2x3_A" % i)
        c.objects.link(box("INT_Bay%d_2x3_A" % i, (2.0, 0.2, 3.0)))
    t0 = time.perf_counter()
    for i in range(2000):
        kit["place_piece"]("INT_Bay%d_2x3_A" % (i % 30), location=(2 * (i % 50), 2 * (i // 50), 0))
    t1 = time.perf_counter()
    snap = kit["snapshot"]()
    t2 = time.perf_counter()
    kit["save_snapshot"](str(SNAP), snap)
    diff = kit["changes_since"](str(SNAP))
    t3 = time.perf_counter()
    print("[speed] 2000 placements: place %.2f s, snapshot %.2f s, save + changes_since %.2f s"
          % (t1 - t0, t2 - t1, t3 - t2))
    assert diff == [] and t2 - t1 < 10, (len(diff), t2 - t1)


CASES = [test_work_file_runs_other_skills_scripts, test_parallel_work_files_integrate_in_any_order,
         test_user_edits_elsewhere_survive_an_integrate, test_integrate_refuses_a_piece_the_user_deleted_or_renamed,
         test_assembly_round_trip_keeps_one_copy_of_each_piece, test_nested_assembly,
         test_lods_and_collision_replace_the_greybox, test_placement_ids_and_placement_sync_scopes,
         test_textures_resolve_after_integrate, test_repeat_and_stale_integrates,
         test_checkout_takes_unsaved_live_edits, test_snapshot_ignores_ui_noise_but_not_edits, test_snapshot_speed]


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
