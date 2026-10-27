"""Blender-hosted tests for blender-kit-library's scripts/kit_library.py: the audit (Python and command line) at a
0.5 m grid module, save_file without .blend1 backups, and new_piece / list_library / link_piece / place /
reload_libraries with relative paths.

Host: Blender 5.2 (bpy), run from anywhere:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_kit_library_audit.py
Builds its fixtures in a temp folder, prints PASS <case> / FAIL <case>: <why>, and raises if any case failed.
"""

import json
import math
import os
import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path

import bpy
from mathutils import Matrix

ROOT = Path(__file__).resolve().parents[3]
KIT_LIBRARY = ROOT / "skills" / "blender-kit-library" / "scripts" / "kit_library.py"
TMP = Path(tempfile.mkdtemp(prefix="kit_library_test_"))
KIT = TMP / "blender" / "kits" / "KIT_Test.blend"
MASTER = TMP / "blender" / "MASTER.blend"


def load_ns():
    ns = {}
    exec(compile(KIT_LIBRARY.read_text(encoding="utf-8"), str(KIT_LIBRARY), "exec"), ns)
    return ns


def box(name, size, origin=(0.0, 0.0, 0.0), uv_layers=1):
    """A mesh box from `origin` to origin + size, object at identity."""
    x0, y0, z0 = origin
    x1, y1, z1 = x0 + size[0], y0 + size[1], z0 + size[2]
    me = bpy.data.meshes.new(name)
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    me.from_pydata(v, [], f)
    for i in range(uv_layers):
        me.uv_layers.new(name="UV%d" % i)
    return bpy.data.objects.new(name, me)


def blender(*args):
    """Run another headless Blender; returns (exit code, output)."""
    p = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1", *map(str, args)],
                       capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr


def build_kit():
    """KIT_Test.blend at a 0.5 m module: one correct wall, one twice too big for its name, one free prop missing UV2."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ns = load_ns()
    good = ns["new_piece"]("INT_Wall_2x3_A")             # 2 x 3 modules at 0.5 m = 1.0 x 1.5 m, 0.1 m thick
    good.objects.link(box("INT_Wall_2x3_A", (1.0, 0.1, 1.5)))
    good["kit_status"] = "grey"
    big = ns["new_piece"]("INT_Wall_1x2_B")              # named 1 x 2 modules (0.5 x 1.0 m) but built 1.0 x 2.0 m
    big.objects.link(box("INT_Wall_1x2_B", (1.0, 0.1, 2.0)))
    big["kit_status"] = "grey"
    prop = ns["new_piece"]("PROP_Desk_Free_A")
    prop.objects.link(box("PROP_Desk_Free_A", (1.4, 0.7, 0.78), origin=(-0.7, -0.35, 0.0)))
    prop["kit_status"] = "uv"                            # UV2 is due from "uv" on; this one has only UV0
    KIT.parent.mkdir(parents=True, exist_ok=True)
    ns["save_file"](str(KIT))
    return ns


def test_new_piece_rules():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ns = load_ns()
    try:
        ns["new_piece"]("Wall_A")
    except ValueError:
        pass
    else:
        raise AssertionError("new_piece accepted a name outside the kit pattern")
    coll = bpy.data.collections.new("STR_Floor_2x2_A")
    bpy.context.scene.collection.children.link(coll)
    coll.instance_offset = (0.5, 0.0, 0.0)
    again = ns["new_piece"]("STR_Floor_2x2_A")
    assert again == coll, "new_piece did not return the existing collection"
    assert tuple(again.instance_offset) == (0.0, 0.0, 0.0), "new_piece left instance_offset at %s" % (
        tuple(again.instance_offset),)
    asm = ns["new_piece"]("ASM_ShopFront_A")
    assert asm.name == "ASM_ShopFront_A"


def test_save_file_writes_no_blend1():
    build_kit()
    ns = load_ns()
    before = bpy.context.preferences.filepaths.save_version
    ns["save_file"]()                                    # a second save of the same file
    assert KIT.exists(), "KIT file was not written"
    assert not Path(str(KIT) + "1").exists(), "save_file left a .blend1 backup"
    assert bpy.context.preferences.filepaths.save_version == before, "save_file did not restore save_version"
    # Control: a plain save with Blender's default (save_version 1) does write the backup the skill forbids.
    bpy.ops.wm.save_mainfile()
    assert Path(str(KIT) + "1").exists(), "control failed: the default save wrote no .blend1"
    os.remove(str(KIT) + "1")


def test_audit_python_needs_module():
    build_kit()
    ns = load_ns()
    try:
        ns["audit_kit"]()
    except TypeError:
        pass
    else:
        raise AssertionError("audit_kit() ran without a grid module")
    try:
        ns["audit_kit"](0)
    except ValueError:
        pass
    else:
        raise AssertionError("audit_kit(0) ran")
    rep = ns["audit_kit"](0.5)
    by = {r["piece"]: r for r in rep["pieces"]}
    assert by["INT_Wall_2x3_A"]["issues"] == [], by["INT_Wall_2x3_A"]
    assert any("do not match size 1x2" in i for i in by["INT_Wall_1x2_B"]["issues"]), by["INT_Wall_1x2_B"]
    assert any("no UV2" in i for i in by["PROP_Desk_Free_A"]["issues"]), by["PROP_Desk_Free_A"]
    # The trap the required module closes: audited at 1 m, the good wall fails and the oversized one passes.
    by1 = {r["piece"]: r for r in ns["audit_kit"](1.0)["pieces"]}
    assert by1["INT_Wall_2x3_A"]["issues"], "at 1 m the 0.5 m wall should fail"
    assert not by1["INT_Wall_1x2_B"]["issues"], by1["INT_Wall_1x2_B"]


def test_audit_cli_at_half_metre():
    build_kit()
    out = TMP / "audit.json"
    code, text = blender(KIT, "--python", KIT_LIBRARY, "--", "--audit", "--module", "0.5", "--json", out)
    assert code == 1, "audit CLI exit %s, expected 1 (one bad piece):\n%s" % (code, text)
    assert "at a 0.5 m module" in text, text
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["module"] == 0.5
    by = {r["piece"]: r for r in rep["pieces"]}
    assert by["INT_Wall_2x3_A"]["issues"] == [] and by["INT_Wall_2x3_A"]["extent_modules"] == [2.0, 0.2, 3.0], by
    assert by["INT_Wall_1x2_B"]["issues"], by["INT_Wall_1x2_B"]
    code, text = blender(KIT, "--python", KIT_LIBRARY, "--", "--audit")
    assert code == 2 and "--module" in text, "audit CLI without --module: exit %s\n%s" % (code, text)


def test_link_place_reload_relative():
    build_kit()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ns = load_ns()
    ns["save_file"](str(MASTER))                         # saved first, so links can be stored relative
    names = ns["list_library"]("//kits/KIT_Test.blend")
    assert sorted(names) == ["INT_Wall_1x2_B", "INT_Wall_2x3_A", "PROP_Desk_Free_A"], names
    room = bpy.data.collections.new("study")
    bpy.context.scene.collection.children.link(room)
    a = ns["link_piece"]("//kits/KIT_Test.blend", "INT_Wall_2x3_A", location=(2, 0, 0), rot_z=90, into=room)
    b = ns["link_piece"]("//kits/KIT_Test.blend", "INT_Wall_2x3_A", location=(0, 0, 0))
    assert a.instance_collection == b.instance_collection, "the second link_piece linked the collection again"
    assert len(bpy.data.libraries) == 1, [lib.filepath for lib in bpy.data.libraries]
    assert bpy.data.libraries[0].filepath.startswith("//"), "library path is not relative: %s" % (
        bpy.data.libraries[0].filepath,)
    want = Matrix.Translation((2, 0, 0)) @ Matrix.Rotation(math.radians(90), 4, "Z")
    assert all(abs(a.matrix_world[i][j] - want[i][j]) < 1e-5 for i in range(4) for j in range(4)), a.matrix_world
    assert a.name in room.objects and a.instance_type == "COLLECTION"
    ns["save_file"]()
    assert not Path(str(MASTER) + "1").exists(), "save_file left MASTER.blend1"
    bpy.ops.wm.open_mainfile(filepath=str(MASTER))
    ns = load_ns()
    inst = [o for o in bpy.data.objects if o.instance_type == "COLLECTION"]
    assert len(inst) == 2 and all(o.instance_collection.name == "INT_Wall_2x3_A" for o in inst), inst
    assert bpy.data.libraries[0].filepath.startswith("//")
    done = ns["reload_libraries"]()
    assert len(done) == 1, done


def test_size_skips_axes_under_one_module():
    """Canon (2026-10-17): any axis under one module is thickness. 0.3 m and 0.25 m walls pass as 4x6 at 0.5 m."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ns = load_ns()
    for name, size in (("EXT_Wall_4x6_A", (2.0, 0.3, 3.0)), ("EXT_Wall_4x6_B", (2.0, 0.25, 3.0)),
                       ("STR_Post_1x1x5_A", (0.5, 0.5, 2.5)), ("STR_Floor_4x4_A", (2.0, 2.0, 0.45))):
        coll = ns["new_piece"](name)
        coll.objects.link(box(name, size))
        coll["kit_status"] = "grey"
    rep = ns["audit_kit"](0.5)
    bad = {r["piece"]: r["issues"] for r in rep["pieces"] if r["issues"]}
    assert bad == {}, bad
    by = {r["piece"]: r for r in rep["pieces"]}
    assert by["EXT_Wall_4x6_A"]["extent_modules"] == [4.0, 0.6, 6.0], by["EXT_Wall_4x6_A"]


def test_material_names():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ns = load_ns()
    for piece, mat in (("INT_Wall_2x3_A", "M_INT_Paper"), ("INT_Wall_2x3_B", "M_INT_Paper.001"),
                       ("INT_Wall_2x3_C", "M_TRIM_Sheet01"), ("INT_Wall_2x3_D", "M_EXT_Brick")):
        ob = box(piece, (2, 0.1, 3))
        ob.data.materials.append(bpy.data.materials.get(mat) or bpy.data.materials.new(mat))
        coll = ns["new_piece"](piece)
        coll.objects.link(ob)
        coll["kit_status"] = "grey"                                # materials are checked from greybox on
    by = {r["piece"]: r["issues"] for r in ns["audit_kit"](1.0)["pieces"]}
    assert by["INT_Wall_2x3_A"] == [] and by["INT_Wall_2x3_C"] == [], by
    assert any("M_INT_Paper.001 is not named M_<FAMILY>_<Name>" in i for i in by["INT_Wall_2x3_B"]), by
    assert any("outside M_INT_/M_TRIM_" in i for i in by["INT_Wall_2x3_D"]), by
    path = TMP / "materials.blend"                               # the command line takes another set of prefixes
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    out = TMP / "materials.json"
    code, text = blender(path, "--python", KIT_LIBRARY, "--", "--audit", "--module", "1.0", "--json", out,
                         "--materials", "M_INT_,M_EXT_,M_TRIM_")
    by = {r["piece"]: r["issues"] for r in json.loads(out.read_text(encoding="utf-8"))["pieces"]}
    assert by["INT_Wall_2x3_D"] == [] and by["INT_Wall_2x3_B"], (code, by)


def test_new_file_starts_empty_and_saved():
    path = TMP / "blender" / "asm" / "deeper" / "ASM_Test_A.blend"
    bpy.ops.wm.read_factory_settings(use_empty=False)              # a default scene with a cube and a Collection
    bpy.context.preferences.filepaths.save_version = 3             # stands in for a user's preference
    ns = load_ns()
    saved = ns["new_file"](str(path))
    assert Path(saved) == path and path.exists(), saved
    assert len(bpy.data.objects) == 0 and len(bpy.data.collections) == 0, (list(bpy.data.objects),
                                                                          list(bpy.data.collections))
    assert bpy.context.preferences.filepaths.save_version == 3, "new_file changed the preferences"
    assert not Path(str(path) + "1").exists()
    asm = ns["new_piece"]("ASM_Test_A")
    rep = ns["audit_kit"](1.0)
    assert ns["problems"](rep) == [], ns["problems"](rep)
    assert asm.name == "ASM_Test_A"


def break_master_link():
    """MASTER links KIT_Test.blend, then its library path is pointed where the file no longer is (a moved folder)."""
    build_kit()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ns = load_ns()
    ns["save_file"](str(MASTER))
    ns["link_piece"]("//kits/KIT_Test.blend", "INT_Wall_2x3_A", location=(2, 0, 0))
    bpy.data.libraries[0].filepath = "//kits_old/KIT_Test.blend"
    ns["save_file"]()


def test_relink_repairs_moved_libraries():
    break_master_link()
    bpy.ops.wm.open_mainfile(filepath=str(MASTER))
    ns = load_ns()
    missing = [m.replace("\\", "/") for m in ns["missing_libraries"]()]
    assert missing == ["//kits_old/KIT_Test.blend"], missing
    rep = ns["audit_kit"](1.0)
    assert any("linked library missing" in p for p in ns["problems"](rep)), ns["problems"](rep)
    result = ns["relink"]([str(TMP / "blender")])
    assert len(result) == 1, result
    new = next(iter(result.values()))
    assert new and new.startswith("//") and new.replace("\\", "/").endswith("kits/KIT_Test.blend"), result
    inst = next(o for o in bpy.data.objects if o.instance_type == "COLLECTION")
    assert len(inst.instance_collection.all_objects) == 1, "the instance did not get its piece back"
    ns["save_file"]()
    bpy.ops.wm.open_mainfile(filepath=str(MASTER))
    assert load_ns()["missing_libraries"]() == []


def test_relink_command_line():
    break_master_link()
    code, text = blender(MASTER, "--python", KIT_LIBRARY, "--", "--relink", TMP / "blender")
    assert code == 0 and "1 file(s) checked after relinking, 0 with something still missing" in text, text
    assert not Path(str(MASTER) + "1").exists(), "the relink save left a .blend1"
    bpy.ops.wm.open_mainfile(filepath=str(MASTER))
    assert load_ns()["missing_libraries"]() == []
    code, text = blender(MASTER, "--python", KIT_LIBRARY, "--", "--relink", TMP / "nowhere")
    assert code == 0, text                                         # nothing missing any more: nothing to do


ASM = TMP / "blender" / "asm" / "ASM_Shop_A.blend"


def break_nested_project():
    """MASTER links a KIT piece directly and an assembly whose own KIT link is broken (the ASM file moved one folder
    deeper, say); MASTER's link to the ASM is broken too. This is the case that crashed the round-2 relink: the ASM's
    reload brings an indirect KIT library that the direct one then swallows."""
    build_kit()
    ns = load_ns()
    ns["new_file"](str(ASM))
    asm = ns["new_piece"]("ASM_Shop_A")
    ns["link_piece"]("//../kits/KIT_Test.blend", "INT_Wall_2x3_A", into=asm)
    bpy.data.libraries[0].filepath = "//../kits_old/KIT_Test.blend"            # the ASM's own KIT link
    ns["save_file"]()
    ns["new_file"](str(MASTER))
    ns["link_piece"]("//kits/KIT_Test.blend", "INT_Wall_2x3_A", location=(9, 0, 0))   # MASTER's direct piece
    with bpy.data.libraries.load(str(ASM), link=True, relative=True) as (src, dst):
        dst.collections = ["ASM_Shop_A"]
    ns["place"](dst.collections[0], location=(5, 5, 0))
    for lib in bpy.data.libraries:
        if lib.filepath.replace("\\", "/").endswith("ASM_Shop_A.blend"):
            lib.filepath = "//asm_old/ASM_Shop_A.blend"                       # and MASTER's link to the ASM
    ns["save_file"]()


def assembly_draws_its_wall():
    """Whether the instance inside MASTER's linked assembly reaches a real wall mesh (not a missing placeholder)."""
    asm = next((c for c in bpy.data.collections if c.name == "ASM_Shop_A" and c.library), None)
    if asm is None:
        return False
    inner = [o.instance_collection for o in asm.all_objects if o.instance_type == "COLLECTION"]
    return bool(inner) and all(c is not None and not c.is_missing and
                               any(o.type == "MESH" for o in c.all_objects) for c in inner)


def test_relink_master_before_its_asm_is_refused_safely():
    """The wrong order must not crash and must not claim success: the indirect KIT link is left for the ASM file."""
    break_nested_project()
    bpy.ops.wm.open_mainfile(filepath=str(MASTER))
    ns = load_ns()
    result = ns["relink"]([str(TMP / "blender")])
    fix_first = [v for v in result.values() if v and v.startswith("fix ")]
    assert fix_first and "ASM_Shop_A.blend" in fix_first[0], result
    assert ns["missing_libraries"](), "an indirect link counted as repaired"


def test_relink_asm_files_then_master():
    break_nested_project()
    code, text = blender("--python", KIT_LIBRARY, "--", "--relink", TMP / "blender", "--files", ASM, MASTER)
    assert code == 0 and "2 file(s) checked after relinking, 0 with something still missing" in text, text
    bpy.ops.wm.open_mainfile(filepath=str(MASTER))
    assert load_ns()["missing_libraries"]() == [], load_ns()["missing_libraries"]()
    assert assembly_draws_its_wall(), "the assembly instance does not draw its wall after reopening"


def test_relink_a_renamed_file():
    break_master_link()                                    # MASTER links the KIT through a broken path
    bpy.ops.wm.open_mainfile(filepath=str(KIT))
    load_ns()["save_file"](str(KIT.with_name("KIT_Renamed.blend")))            # the KIT file under its new name ...
    bpy.ops.wm.open_mainfile(filepath=str(MASTER))
    ns = load_ns()
    bpy.data.libraries[0].filepath = "//kits/KIT_Gone.blend"                   # ... and MASTER still on an old one
    result = ns["relink"]([str(TMP / "blender")], renamed={"KIT_Gone.blend": "KIT_Renamed.blend"})
    new = next(iter(result.values()))
    assert new and new.replace("\\", "/").endswith("kits/KIT_Renamed.blend"), result
    inst = next(o for o in bpy.data.objects if o.instance_type == "COLLECTION")
    assert len(inst.instance_collection.all_objects) == 1


def build_project(root, stall_in_market=False):
    """KIT_Test.blend, ASM_Stall_A.blend (one wall) and, optionally, ASM_Market_A.blend placing the stall, then
    MASTER.blend placing the outermost assembly; every link relative and working. Returns {name: path}."""
    ns = load_ns()
    files = {"kit": root / "blender" / "kits" / "KIT_Test.blend", "stall": root / "blender" / "asm" / "ASM_Stall_A.blend",
             "market": root / "blender" / "asm" / "ASM_Market_A.blend", "master": root / "blender" / "MASTER.blend"}
    ns["new_file"](str(files["kit"]))
    ns["new_piece"]("INT_Wall_2x3_A").objects.link(box("INT_Wall_2x3_A", (2, 0.2, 3)))
    ns["save_file"]()
    ns["new_file"](str(files["stall"]))
    ns["link_piece"]("//../kits/KIT_Test.blend", "INT_Wall_2x3_A", into=ns["new_piece"]("ASM_Stall_A"))
    ns["save_file"]()
    top = "ASM_Stall_A"
    if stall_in_market:
        ns["new_file"](str(files["market"]))
        ns["link_piece"]("//ASM_Stall_A.blend", "ASM_Stall_A", into=ns["new_piece"]("ASM_Market_A"))
        ns["save_file"]()
        top = "ASM_Market_A"
    ns["new_file"](str(files["master"]))
    ns["link_piece"]("//asm/%s.blend" % top, top, location=(5, 5, 0))
    ns["save_file"]()
    return files


def repoint(blend, ending, new_path):
    """Store `new_path` for the library of `blend` whose path ends with `ending` (a file that was moved away)."""
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    for lib in bpy.data.libraries:
        if lib.parent is None and lib.filepath.replace("\\", "/").endswith(ending):
            lib.filepath = new_path
    load_ns()["save_file"]()


def draws_wall_through(top):
    """Whether MASTER's instance of assembly `top` reaches a real wall mesh through every nested level."""
    def reaches(coll, depth=0):
        if coll is None or coll.is_missing or depth > 5:
            return False
        if any(o.type == "MESH" for o in coll.all_objects):
            return True
        inner = [o.instance_collection for o in coll.all_objects if o.instance_type == "COLLECTION"]
        return bool(inner) and all(reaches(c, depth + 1) for c in inner)
    return reaches(next((c for c in bpy.data.collections if c.name == top and c.library), None))


def test_relink_renamed_assembly_saves_nothing():
    """An assembly renamed with its file: --renamed finds the file but not the collection, so nothing is saved and the
    run fails; the rename procedure (link the renamed collection, re-point the instances) is the route that works."""
    files = build_project(TMP / "rename_asm")
    bpy.ops.wm.open_mainfile(filepath=str(files["stall"]))
    bpy.data.collections["ASM_Stall_A"].name = "ASM_Booth_A"
    booth = files["stall"].with_name("ASM_Booth_A.blend")
    load_ns()["save_file"](str(booth))
    repoint(files["master"], "ASM_Stall_A.blend", "//asm/ASM_Gone_A.blend")   # MASTER still names the old file
    code, text = blender("--python", KIT_LIBRARY, "--", "--relink", TMP / "rename_asm" / "blender", "--files",
                         files["master"], "--renamed", "ASM_Gone_A.blend=ASM_Booth_A.blend")
    assert code == 1 and "NOT SAVED" in text and "rename procedure" in text, text
    bpy.ops.wm.open_mainfile(filepath=str(files["master"]))
    ns = load_ns()
    assert any(p.replace("\\", "/").endswith("ASM_Gone_A.blend") for p in ns["missing_libraries"]()), "MASTER was saved"
    new = ns["link_collection"]("//asm/ASM_Booth_A.blend", "ASM_Booth_A")
    for ob in bpy.data.objects:
        if ob.instance_type == "COLLECTION" and ob.instance_collection and ob.instance_collection.name == "ASM_Stall_A":
            ob.instance_collection = new
    ns["save_file"]()
    bpy.ops.wm.open_mainfile(filepath=str(files["master"]))
    ns = load_ns()
    assert ns["missing_libraries"]() == [] and ns["missing_ids"]() == [], (ns["missing_libraries"](), ns["missing_ids"]())
    assert draws_wall_through("ASM_Booth_A")


def test_relink_nested_assemblies_in_any_order():
    """KIT -> ASM_Stall_A -> ASM_Market_A -> MASTER, every link broken, files listed outer before inner."""
    files = build_project(TMP / "nested", stall_in_market=True)
    repoint(files["stall"], "KIT_Test.blend", "//../kits_old/KIT_Test.blend")
    repoint(files["market"], "ASM_Stall_A.blend", "//old/ASM_Stall_A.blend")
    repoint(files["master"], "ASM_Market_A.blend", "//asm_old/ASM_Market_A.blend")
    code, text = blender("--python", KIT_LIBRARY, "--", "--relink", TMP / "nested" / "blender", "--files",
                         files["market"], files["stall"], files["master"])
    assert code == 0 and "3 file(s) checked after relinking, 0 with something still missing" in text, text
    bpy.ops.wm.open_mainfile(filepath=str(files["master"]))
    ns = load_ns()
    assert ns["missing_libraries"]() == [] and ns["missing_ids"]() == [], (ns["missing_libraries"](), ns["missing_ids"]())
    assert draws_wall_through("ASM_Market_A"), "MASTER does not draw the wall through both assemblies"


def test_relink_leaves_ambiguous_copies_alone():
    """kits/ and an archive copy both hold KIT_Test.blend: the link is left alone unless one sits in a folder named
    like the old one."""
    root = TMP / "archive"
    files = build_project(root)
    bpy.ops.wm.open_mainfile(filepath=str(files["kit"]))
    load_ns()["save_file"](str(root / "blender" / "archive" / "2026-09" / "KIT_Test.blend"))
    repoint(files["stall"], "KIT_Test.blend", "//../kits_old/KIT_Test.blend")
    code, text = blender("--python", KIT_LIBRARY, "--", "--relink", root / "blender", "--files", files["stall"])
    assert code == 1 and "ambiguous" in text, text
    bpy.ops.wm.open_mainfile(filepath=str(files["stall"]))
    paths = [lib.filepath.replace("\\", "/") for lib in bpy.data.libraries]
    assert paths == ["//../kits_old/KIT_Test.blend"], paths
    # The whole project moved: the old path's parent and grandparent folders (blender/kits) still match the live file.
    repoint(files["stall"], "kits_old/KIT_Test.blend", "//../../old_root/blender/kits/KIT_Test.blend")
    code, text = blender("--python", KIT_LIBRARY, "--", "--relink", root / "blender", "--files", files["stall"])
    assert code == 0, text
    bpy.ops.wm.open_mainfile(filepath=str(files["stall"]))
    paths = [lib.filepath.replace("\\", "/") for lib in bpy.data.libraries]
    assert paths == ["//../kits/KIT_Test.blend"], paths


def test_relink_dedupes_and_refuses_a_backup_in_an_old_folder_name():
    """(1) Overlapping search folders reach one file twice: still one candidate. (2) kits/ renamed kit_lib/ with a
    backup in _backup/kits/: the backup's parent matches the old name but its grandparent does not, so the link is
    left alone (the live folder named on the command line fixes it)."""
    root = TMP / "backup"
    ns = load_ns()
    ns["new_file"](str(root / "blender" / "kit_lib" / "KIT_Test.blend"))
    ns["new_piece"]("INT_Wall_2x3_A").objects.link(box("INT_Wall_2x3_A", (2, 0.2, 3)))
    ns["save_file"]()
    ns["save_file"](str(root / "blender" / "_backup" / "kits" / "KIT_Test.blend"))
    stall = root / "blender" / "asm" / "ASM_Stall_A.blend"
    ns["new_file"](str(stall))
    ns["link_piece"]("//../kit_lib/KIT_Test.blend", "INT_Wall_2x3_A", into=ns["new_piece"]("ASM_Stall_A"))
    bpy.data.libraries[0].filepath = "//../kits/KIT_Test.blend"            # where it was before kits/ was renamed
    ns["save_file"]()
    code, text = blender("--python", KIT_LIBRARY, "--", "--relink", root / "blender", "--files", stall)
    assert code == 1 and "ambiguous" in text, text
    code, text = blender("--python", KIT_LIBRARY, "--", "--relink", root / "blender" / "kit_lib",
                         root / "blender" / "kit_lib", "--files", stall)                # the same folder twice
    assert code == 0 and "ambiguous" not in text, text
    bpy.ops.wm.open_mainfile(filepath=str(stall))
    paths = [lib.filepath.replace("\\", "/") for lib in bpy.data.libraries]
    assert paths == ["//../kit_lib/KIT_Test.blend"], paths


CASES = [test_new_piece_rules, test_save_file_writes_no_blend1, test_audit_python_needs_module,
         test_audit_cli_at_half_metre, test_link_place_reload_relative, test_size_skips_axes_under_one_module,
         test_material_names, test_new_file_starts_empty_and_saved, test_relink_repairs_moved_libraries,
         test_relink_command_line, test_relink_master_before_its_asm_is_refused_safely,
         test_relink_asm_files_then_master, test_relink_a_renamed_file, test_relink_renamed_assembly_saves_nothing,
         test_relink_nested_assemblies_in_any_order, test_relink_leaves_ambiguous_copies_alone,
         test_relink_dedupes_and_refuses_a_backup_in_an_old_folder_name]


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
