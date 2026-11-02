"""Blender-hosted tests for blender-to-unity's scripts/collision_shell.py: a pot on three thin legs (the generated
cauldron whose decimated hull floated 44 mm over the floor) gets a shell that stands on the leg tips, is closed, under
Unity's 255 triangles and max_points corners, close to the full hull, named <Piece>_COL beside its LOD0 with its
transform, wire and out of renders; a second run replaces the shell; the command line builds it for a piece.

Host: Blender 4.2+ (bpy, bmesh; tested on 5.2.2), run from anywhere:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_export_collision_shell.py
Prints PASS <case> / FAIL <case>: <why>, and raises if any case failed.
"""

import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "skills" / "blender-to-unity" / "scripts" / "collision_shell.py"
NS = {"COLLISION_SHELL_NO_MAIN": True}
exec(compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec"), NS)
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


def legged_pot():
    """A 0.4 m sphere standing on three 6 cm legs 1 cm thick: the floor is the leg tips at z = 0."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=0.2,
                              matrix=Matrix.Translation((0.0, 0.0, 0.25)))
    for k in range(3):
        import math
        a = 2 * math.pi * k / 3
        bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.005, radius2=0.01, depth=0.08,
                              matrix=Matrix.Translation((0.12 * math.cos(a), 0.12 * math.sin(a), 0.04)))
    me = bpy.data.meshes.new("PROP_Pot_Free_A_LOD0")
    bm.to_mesh(me)
    bm.free()
    coll = bpy.data.collections.new("PROP_Pot_Free_A")
    bpy.context.scene.collection.children.link(coll)
    ob = bpy.data.objects.new("PROP_Pot_Free_A_LOD0", me)
    coll.objects.link(ob)
    ob.location = (1.0, 2.0, 0.0)
    bpy.context.view_layer.update()
    return ob, coll


def test_shell_stands_on_the_leg_tips():
    ob, coll = legged_pot()
    col, rep = NS["shell"](ob, max_points=64)
    check(rep["floor_gap_m"] < 1e-4, "shell floats over the floor: %s" % rep)
    check(rep["closed"] and rep["triangles"] <= 255 and rep["points"] <= 64, rep)
    # 64 corners on a 0.2 m sphere sag about 10 mm between them: the limit is geometry, not the method
    check(rep["inside_m"] < 0.015 and rep["volume_share"] > 0.93, "shell cuts too much off: %s" % rep)
    check(col.name == "PROP_Pot_Free_A_COL" and col.name in coll.objects, "named and placed in the piece")
    check(col.matrix_world == ob.matrix_world and col.hide_render and col.display_type == "WIRE",
          "transform, wire, out of renders")
    check(not col.data.materials and not col.data.uv_layers, "no materials or UVs on a collision shell")
    again, _ = NS["shell"](ob, max_points=32)
    check(again.name == "PROP_Pot_Free_A_COL" and len(again.data.vertices) <= 32
          and sum(1 for o in bpy.data.objects if o.name.startswith("PROP_Pot_Free_A_COL")) == 1,
          "a second run replaces the shell")


def test_cli_builds_and_saves():
    legged_pot()
    d = Path(tempfile.mkdtemp(prefix="collision_shell_test_"))
    blend = d / "kit.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    r = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", str(blend), "--python-exit-code", "1",
                        "--python", str(SCRIPT), "--", "--piece", "PROP_Pot_Free_A", "--save"],
                       capture_output=True, text=True, timeout=300)
    check(r.returncode == 0 and "[shell]" in r.stdout, r.stdout[-800:] + r.stderr[-800:])
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    check("PROP_Pot_Free_A_COL" in bpy.data.objects and not (d / "kit.blend1").exists(), "saved, no .blend1")


for fn in (test_shell_stands_on_the_leg_tips, test_cli_builds_and_saves):
    case(fn)
failed = [r for r in RESULTS if r[0] == "FAIL"]
print("%d passed, %d failed" % (len(RESULTS) - len(failed), len(failed)))
if failed:
    raise SystemExit("FAILED: " + ", ".join(r[1] for r in failed))
