"""Blender-hosted tests for blender-to-unity's scripts/batch_export_fbx.py: the kit export writes every mesh of a piece
collection (hidden LOD, collision shell disabled in viewports, an excluded piece, a piece outside the scene) with its
modifiers applied, restores the visibility it changed, writes no texture copies with Path Mode Strip, and the files
re-import at rotation 0 with the piece's size; --dir resolves against the current directory or, with //, the .blend's
folder, and a // folder in a file never saved is refused; --set-status saves kit_status without a .blend1; a selection export skips hidden objects and, with Copy,
writes the .fbm texture folder that Strip avoids; custom normals survive the export when the stack triangulates first
(hard-surface routes A and B), and an untriangulated weighted-normal panel gets the re-triangulation warning.

Host: Blender 4.2+ (bpy; tested on 5.2.2), run from anywhere:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_export_batch_fbx.py
Builds its fixtures in a temp folder, prints PASS <case> / FAIL <case>: <why>, and raises if any case failed.
"""

import contextlib
import io
import math
import os
import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path

import bmesh
import bpy

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "skills" / "blender-to-unity" / "scripts" / "batch_export_fbx.py"
TMP = Path(tempfile.mkdtemp(prefix="batch_export_test_"))
KIT = TMP / "blender" / "kits" / "KIT_Test.blend"
RESULTS = []


def case(fn):
    try:
        fn()
        RESULTS.append(("PASS", fn.__name__, ""))
        print("PASS", fn.__name__)
    except Exception as exc:  # noqa: BLE001 - every failure is reported, then the run fails
        RESULTS.append(("FAIL", fn.__name__, str(exc)))
        print("FAIL %s: %s" % (fn.__name__, exc))
        traceback.print_exc()


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def load():
    ns = {"BATCH_EXPORT_NO_MAIN": True}
    exec(compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec"), ns)
    return ns


def box(name, size, coll, subsurf=False):
    x, y, z = size
    me = bpy.data.meshes.new(name)
    v = [(0, 0, 0), (x, 0, 0), (x, y, 0), (0, y, 0), (0, 0, z), (x, 0, z), (x, y, z), (0, y, z)]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    me.from_pydata(v, [], f)
    me.uv_layers.new(name="UVMap")
    me.uv_layers.new(name="UV2")
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    if subsurf:
        ob.modifiers.new("subsurf", "SUBSURF").levels = 1          # 12 -> 48 triangles when applied
    return ob


def textured_material():
    tex_dir = TMP / "blender" / "textures"
    tex_dir.mkdir(parents=True, exist_ok=True)
    img = bpy.data.images.new("T_INT_Test_BaseColor", 8, 8)
    img.filepath_raw = str(tex_dir / "T_INT_Test_BaseColor.png")
    img.file_format = "PNG"
    img.save()
    mat = bpy.data.materials.new("M_INT_Test")
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def build_kit():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    wall = bpy.data.collections.new("INT_Wall_2x3_A")
    scene.collection.children.link(wall)
    lod0 = box("INT_Wall_2x3_A_LOD0", (2, 0.2, 3), wall)
    lod0.data.materials.append(textured_material())
    lod1 = box("INT_Wall_2x3_A_LOD1", (2, 0.2, 3), wall, subsurf=True)
    col = box("INT_Wall_2x3_A_COL", (2, 0.2, 3), wall, subsurf=True)
    prop = bpy.data.collections.new("PROP_Box_Free_A")
    scene.collection.children.link(prop)
    box("PROP_Box_Free_A", (0.5, 0.5, 0.5), prop, subsurf=True)
    floor = bpy.data.collections.new("STR_Floor_2x2_A")            # a piece outside the scene
    floor.use_fake_user = True
    box("STR_Floor_2x2_A", (2, 2, 0.1), floor, subsurf=True)
    ref = bpy.data.collections.new("REF")
    scene.collection.children.link(ref)
    box("REF_Figure", (0.4, 0.3, 1.6), ref)
    vl = bpy.context.view_layer
    vl.update()
    lod1.hide_set(True)                                              # H
    col.hide_viewport = True                                         # disabled in viewports
    vl.layer_collection.children["PROP_Box_Free_A"].exclude = True   # excluded from the view layer
    KIT.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(KIT))


def open_kit():
    bpy.ops.wm.open_mainfile(filepath=str(KIT))


def reimport(path):
    """{object name: (triangles, rotation, dimensions)} of an FBX imported into an empty scene."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(path), bake_space_transform=True)
    return {o.name: (sum(len(p.vertices) - 2 for p in o.data.polygons), tuple(o.rotation_euler), tuple(o.dimensions))
            for o in bpy.context.scene.objects if o.type == "MESH"}


EXPECT = {
    "INT/INT_Wall_2x3_A.fbx": {"INT_Wall_2x3_A_LOD0": 12, "INT_Wall_2x3_A_LOD1": 48, "INT_Wall_2x3_A_COL": 48},
    "PROP/PROP_Box_Free_A.fbx": {"PROP_Box_Free_A": 48},
    "STR/STR_Floor_2x2_A.fbx": {"STR_Floor_2x2_A": 48},
}


def check_export_dir(out):
    files = sorted(str(p.relative_to(out)).replace("\\", "/") for p in out.rglob("*") if p.is_file())
    check(files == sorted(EXPECT), "files written: %s" % files)
    check(not [p for p in out.rglob("*.fbm")], "a .fbm texture folder was written")
    for rel, want in EXPECT.items():
        got = reimport(out / rel)
        tris = {k: v[0] for k, v in got.items()}
        check(tris == want, "%s: %s, want %s (hidden members and their modifiers)" % (rel, tris, want))
        for name, (_, rot, _) in got.items():
            check(max(abs(r) for r in rot) < 1e-6, "%s re-imports rotated %s" % (name, rot))
    dims = reimport(out / "INT/INT_Wall_2x3_A.fbx")["INT_Wall_2x3_A_LOD0"][2]
    check(max(abs(a - b) for a, b in zip(dims, (2, 0.2, 3))) < 1e-4, "LOD0 dimensions %s" % (dims,))


def test_kit_export_writes_every_member_and_restores_visibility():
    open_kit()
    ns = load()
    out = TMP / "export_inprocess" / "fbx"
    written = ns["export_kit"](str(out))
    names = {Path(p).name: sorted(v) for p, v in written.items()}
    check(names["INT_Wall_2x3_A.fbx"] == ["INT_Wall_2x3_A_COL", "INT_Wall_2x3_A_LOD0", "INT_Wall_2x3_A_LOD1"],
          "returned names %s" % names)
    scene, vl = bpy.context.scene, bpy.context.view_layer
    check(bpy.data.objects["INT_Wall_2x3_A_LOD1"].hide_get(), "LOD1 no longer hidden")
    check(bpy.data.objects["INT_Wall_2x3_A_COL"].hide_viewport, "COL no longer disabled in viewports")
    check(vl.layer_collection.children["PROP_Box_Free_A"].exclude, "PROP collection no longer excluded")
    check(bpy.data.collections["STR_Floor_2x2_A"] not in scene.collection.children_recursive,
          "STR collection left linked into the scene")
    check_export_dir(out)


def run_cli(args, cwd):
    cmd = [bpy.app.binary_path, "-b", "--factory-startup", str(KIT), "--python-exit-code", "1",
           "--python", str(SCRIPT), "--"] + args
    res = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=300)
    check(res.returncode == 0, "exit %d: %s" % (res.returncode, (res.stdout + res.stderr)[-2000:]))
    return res.stdout


def test_cli_relative_dir_is_taken_from_the_current_directory():
    cwd = TMP / "cwd"
    cwd.mkdir(exist_ok=True)
    stdout = run_cli(["--kit", "--dir", "rel_out"], cwd)
    out = cwd / "rel_out"
    check(str(out.resolve()).lower() in stdout.replace("/", os.sep).lower(), "absolute folder not printed")
    check_export_dir(out)


def test_cli_blend_relative_dir_and_set_status():
    cwd = TMP / "cwd2"
    cwd.mkdir(exist_ok=True)
    run_cli(["--kit", "--dir", "//../../export/fbx", "--set-status", "--tangents"], cwd)
    out = TMP / "export" / "fbx"
    check_export_dir(out)
    check(not KIT.with_suffix(".blend1").exists(), "a .blend1 backup was written")
    open_kit()
    for name in ("INT_Wall_2x3_A", "PROP_Box_Free_A", "STR_Floor_2x2_A"):
        check(bpy.data.collections[name].get("kit_status") == "exported", "%s kit_status not saved" % name)
    check("kit_status" not in bpy.data.collections["REF"], "REF got a kit_status")
    check(bpy.data.objects["INT_Wall_2x3_A_LOD1"].hide_get(), "saved file lost LOD1's hidden state")
    check(bpy.context.view_layer.layer_collection.children["PROP_Box_Free_A"].exclude, "saved file lost the exclude")


def panel(name, steps):
    """A 1 x 0.08 x 2 m panel piece, shaded smooth, with a 10 mm 2-segment bevel stack (hard-surface.md's routes)."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(1.0, 0.08, 2.0), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(0.5, 0.04, 1.0), verts=bm.verts)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    for step in steps:
        if step.startswith("bevel"):
            m = ob.modifiers.new("Bevel", "BEVEL")
            m.width, m.segments = 0.01, 2
            if step == "bevel_harden":
                m.harden_normals = True
            else:
                m.face_strength_mode = "FSTR_AFFECTED"
        elif step.startswith("tri"):
            m = ob.modifiers.new("Triangulate", "TRIANGULATE")
            m.min_vertices = 4
            m.keep_custom_normals = step == "tri_keep"
        elif step == "wn":
            m = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
            m.mode, m.keep_sharp, m.use_face_influence = "FACE_AREA", True, True
    return ob


def corner_normals(me):
    """{rounded position: [corner normals]} and the worst big-face corner normal's angle off its face (deg)."""
    cn, out, flat = me.corner_normals, {}, 0.0
    for p in me.polygons:
        for li in p.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            out.setdefault(tuple(round(c, 4) for c in co), []).append(cn[li].vector.copy())
            if p.area >= 0.02:
                flat = max(flat, math.degrees(cn[li].vector.angle(p.normal, 0.0)))
    return out, flat


def max_change(a, b):
    """Largest angle from a normal in a to the nearest normal at the same position in b (deg)."""
    worst = 0.0
    for pos, normals in a.items():
        for n in normals:
            worst = max(worst, min(math.degrees(n.angle(r, 0.0)) for r in b.get(pos, [n])))
    return worst


def test_custom_normals_survive_when_triangulated_in_the_stack():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    stacks = {"INT_PanelA_1x2_A": ["bevel_affected", "tri", "wn"],        # route B as hard-surface.md gives it
              "INT_PanelB_1x2_A": ["bevel_affected", "wn"],               # no Triangulate: the exporter splits quads
              "INT_PanelC_1x2_A": ["bevel_harden", "tri_keep"]}           # route A
    obs = {name: panel(name, steps) for name, steps in stacks.items()}
    bpy.context.view_layer.update()
    blender = {}
    for name, ob in obs.items():
        ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
        blender[name] = corner_normals(ev.to_mesh())
        ev.to_mesh_clear()
    out = TMP / "export_normals"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        load()["export_kit"](str(out))
    log = buf.getvalue()
    print(log)
    check("'INT_PanelB_1x2_A': custom normals on" in log, "no warning for the untriangulated weighted-normal panel")
    check("[warn] 'INT_PanelA" not in log and "[warn] 'INT_PanelC" not in log, "warned about a triangulated panel")
    for name in stacks:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=str(out / "INT" / (name + ".fbx")), bake_space_transform=True)
        normals, flat = corner_normals(bpy.context.scene.objects[name].data)
        change = max_change(normals, blender[name][0])
        print("INFO %s: corner normals change %.2f deg through the export, big faces %.2f deg off flat"
              % (name, change, flat))
        if name != "INT_PanelB_1x2_A":
            check(change < 0.5 and flat < 0.5, "%s: normals changed %.2f deg, %.2f off flat" % (name, change, flat))


def test_selection_export_skips_hidden_and_copy_writes_fbm():
    open_kit()
    ns = load()
    out = TMP / "export_selection"
    out.mkdir(exist_ok=True)
    path = str(out / "wall.fbx")
    names = ns["_export"](path, objects=[bpy.data.objects["INT_Wall_2x3_A_LOD0"],
                                         bpy.data.objects["INT_Wall_2x3_A_LOD1"]], path_mode="COPY")
    check(names == ["INT_Wall_2x3_A_LOD0"], "selection export wrote %s" % names)
    check([p for p in out.rglob("*.fbm")], "Copy wrote no .fbm folder (the fixture's material is textured)")


def test_unsaved_file_refuses_blend_relative_dir():
    # bpy.path.abspath("//x") in a file never saved is "x", relative to Blender's current directory: from
    # C:\Windows\System32, //../../export/fbx wrote into C:\export\fbx
    bpy.ops.wm.read_homefile(use_empty=True)
    ns = load()
    for fn in (lambda: ns["export_kit"]("//../../export/fbx"), lambda: ns["export_selected"]("//export/fbx")):
        try:
            fn()
        except ValueError as exc:
            check("never been saved" in str(exc), "wrong refusal: %s" % exc)
        else:
            raise AssertionError("a // folder was accepted in an unsaved file")
    check(ns["resolve_dir"](str(TMP)) == os.path.normpath(str(TMP)), "an absolute folder no longer resolves")


build_kit()
for fn in (test_kit_export_writes_every_member_and_restores_visibility,
           test_cli_relative_dir_is_taken_from_the_current_directory,
           test_cli_blend_relative_dir_and_set_status,
           test_selection_export_skips_hidden_and_copy_writes_fbm,
           test_custom_normals_survive_when_triangulated_in_the_stack,
           test_unsaved_file_refuses_blend_relative_dir):
    case(fn)
failed = [r for r in RESULTS if r[0] == "FAIL"]
if not failed:
    shutil.rmtree(TMP, ignore_errors=True)                     # keep the fixtures only when a case failed
print("%d passed, %d failed%s" % (len(RESULTS) - len(failed), len(failed),
                                  " (fixtures kept in %s)" % TMP if failed else ""))
if failed:
    raise SystemExit("FAILED: " + ", ".join(r[1] for r in failed))
