"""Blender test of local-3d-generation's scripts/glb_intake.py on GLBs built here, in a temp folder.

Fixture: a 2 x 1 x 0.5 unit box (subdivided, 108 triangles), UV-unwrapped with seams (Smart UV Project), plus a small separate cube floating
beside it, offset and parented under an empty, exported to GLB. glTF splits vertices at every UV seam, so the raw
import has many 'loose parts' and open edges; the bug this guards (found on a TRELLIS.2 GLB, 2026-11-02: 335 parts
and 66k open edges that were all UV islands) is reporting those instead of the two real shells.

Asserted: the import is welded (welded_vertices > 0); the report sees exactly 2 loose parts, no boundary and no
non-manifold edges; UVs survive welding; --height scales uniformly to the given Z extent with the bottom centre at
the origin; --longest uses the largest extent; upright finds a 22 degree tilt about X and levels the box, and
leaves a level model at 0, and leaves a sphere (no base) alone; a single closed skin shows no thin gaps (verdict clean), a double skin hides
half its surface (verdict double sheets) and an open cup with 4 mm walls crosses thin gaps but hides little (thin walls); drop_floaters removes the small cube only past its fraction.

Repo tooling, not a skill file: it loads the skill's script by path.
Host: Blender 4.2+ (bpy, bmesh), headless:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_local_3d_generation_intake.py
"""

import math
import sys
import tempfile
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "skills" / "local-3d-generation" / "scripts" / "glb_intake.py"
NS = {"__name__": "glb_intake_test"}
exec(compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec"), NS)
FAILS = []
LEVEL_SIZE = None


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def build_fixture(path: Path, tilt_deg: float = 0.0):
    reset()
    bpy.ops.mesh.primitive_cube_add(size=1)
    box = bpy.context.active_object
    box.scale = (2, 1, 0.5)
    bpy.ops.object.transform_apply(scale=True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.subdivide(number_cuts=2)                 # 54 quads, so the nail is clearly the small part
    bpy.ops.uv.smart_project(angle_limit=1.15)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.mesh.primitive_cube_add(size=0.1, location=(1.6, 0, 0.3))
    nail = bpy.context.active_object
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=1.15)
    bpy.ops.object.mode_set(mode="OBJECT")
    empty = bpy.data.objects.new("root", None)
    bpy.context.scene.collection.objects.link(empty)
    empty.location = (5, 3, 2)
    empty.rotation_euler = (math.radians(tilt_deg), 0, 0)   # a camera-aligned (Pixal3D-like) tilt
    box.parent = nail.parent = empty
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB")


def main():
    with tempfile.TemporaryDirectory() as td:
        glb = Path(td) / "fixture.glb"
        build_fixture(glb)

        reset()
        r = NS["intake"](str(glb), height=0.9, name="FIX_high")
        ob = bpy.data.objects["FIX_high"]
        a = r["arrived"]
        check(r["welded_vertices"] > 0, f"import welded ({r['welded_vertices']} merged)")
        check(a["loose_parts"] == 2, f"two real shells, not UV islands (got {a['loose_parts']})")
        check(a["boundary_edges"] == 0, f"no open edges after welding (got {a['boundary_edges']})")
        check(a["nonmanifold_edges"] == 0, "no non-manifold edges")
        check(len(ob.data.uv_layers) == 1, "UV layer kept")
        uvs = {tuple(round(c, 4) for c in d.uv) for d in ob.data.uv_layers[0].data}
        check(len(uvs) > 8, f"UV seams kept on face corners ({len(uvs)} distinct UVs)")
        lo, hi = NS["_bounds"](ob)
        global LEVEL_SIZE
        LEVEL_SIZE = list(hi - lo)
        check(abs((hi.z - lo.z) - 0.9) < 1e-4, f"height 0.9 (got {hi.z - lo.z:.5f})")
        check(abs(lo.z) < 1e-6, "stands on Z=0")
        check(abs(lo.x + hi.x) < 1e-4 and abs(lo.y + hi.y) < 1e-4, "bottom centre at the origin")
        ratio = (hi.x - lo.x) / (hi.z - lo.z)
        before = a["size_m"]
        check(abs(ratio - before[0] / before[2]) < 1e-3, "scaled uniformly")
        check(ob.location.length < 1e-9 and tuple(ob.scale) == (1, 1, 1), "transforms applied")

        reset()
        r = NS["intake"](str(glb), longest=1.0, name="FIX_long")
        ob = bpy.data.objects["FIX_long"]
        lo, hi = NS["_bounds"](ob)
        check(abs(max(hi - lo) - 1.0) < 1e-4, "--longest sets the largest extent")

        reset()
        r = NS["intake"](str(glb), height=1.0, name="FIX_drop", drop=0.01)
        check(r["dropped_faces"] == 0, "nail (12 of 120 tris) kept at 1%")
        reset()
        r = NS["intake"](str(glb), height=1.0, name="FIX_drop2", drop=0.2)
        check(r["dropped_faces"] == 12 and r["final"]["loose_parts"] == 1    # GLB faces are triangles
              and r["final"]["triangles"] == r["arrived"]["triangles"] - 12,
              f"small part dropped past its fraction (dropped {r['dropped_faces']} faces)")

        # upright: the GLB is Y-up, Blender's importer makes it Z-up, so a tilt about X stays about X
        tilted = Path(td) / "tilted.glb"
        build_fixture(tilted, tilt_deg=22.0)
        reset()
        r = NS["intake"](str(tilted), height=0.5, name="FIX_tilt", stand="X")
        ob = bpy.data.objects["FIX_tilt"]
        u = r["upright"]
        check(abs(abs(u["degrees"]) - 22.0) <= 0.2, f"tilt of 22 degrees found ({u['degrees']})")
        lo, hi = NS["_bounds"](ob)
        size = hi - lo
        level = [round(v * 0.5 / 0.9, 4) for v in LEVEL_SIZE]     # the level run, rescaled to 0.5 high
        check(all(abs(x - y) < 2e-3 for x, y in zip(size, level)),
              f"box level again: size {[round(v, 4) for v in size]} vs level {level}")
        check(u["base_fraction"] > 0.1, f"base found ({u['base_fraction']})")
        reset()
        r = NS["intake"](str(glb), height=0.5, name="FIX_level", stand="X")
        check(abs(r["upright"]["degrees"]) <= 0.1, f"level model left level ({r['upright']['degrees']})")

        # no flat base (a sphere): left alone, reported as not rotated
        reset()
        bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=0.5)
        ball = Path(td) / "ball.glb"
        bpy.ops.export_scene.gltf(filepath=str(ball), export_format="GLB")
        reset()
        r = NS["intake"](str(ball), height=1.0, name="FIX_ball", stand="X")
        check(r["upright"]["rotated"] is False and r["upright"]["degrees"] == 0.0,
              f"sphere not rotated (base {r['upright']['base_fraction']})")

        # sheet check: one closed skin has no thin gaps
        check(r["final"]["sheets"]["thin_gap_fraction"] == 0.0
              and abs(r["final"]["sheets"]["mean_crossings"] - 2.0) < 0.05,
              f"single skin reads as one sheet ({r['final']['sheets']})")
        check(r["final"]["sheets"]["verdict"] == "clean", f"sphere verdict ({r['final']['sheets']})")

        # a double skin (a sphere inside a sphere 1% larger: the udf remesh's two sheets) against an open cup with
        # 4 mm walls: both cross thin gaps, only the double skin hides half its surface
        reset()
        bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=0.5)
        outer = bpy.context.active_object
        bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=0.495)
        outer.select_set(True)
        bpy.context.view_layer.objects.active = outer
        bpy.ops.object.join()
        sh = NS["sheet_check"](outer)
        check(sh["thin_gap_fraction"] > 0.3 and sh["hidden_fraction"] > 0.4
              and sh["verdict"] == "double sheets or hidden walls", f"double skin ({sh})")
        reset()
        bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.3, depth=0.5)
        cup = bpy.context.active_object
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        top = max(cup.data.polygons, key=lambda f: f.center.z)
        top.select = True
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.delete(type="FACE")
        bpy.ops.object.mode_set(mode="OBJECT")
        sol = cup.modifiers.new("wall", "SOLIDIFY")
        sol.thickness = 0.004
        bpy.ops.object.modifier_apply(modifier="wall")
        sh = NS["sheet_check"](cup)
        check(sh["thin_gap_fraction"] > 0.1 and sh["hidden_fraction"] < 0.1 and sh["verdict"] == "thin walls",
              f"open cup with 4 mm walls ({sh})")

        # manual rotation: the tilted box levelled by hand
        reset()
        r = NS["intake"](str(tilted), height=0.5, name="FIX_turn", turn=(-22.0, 0.0, 0.0))
        lo, hi = NS["_bounds"](bpy.data.objects["FIX_turn"])
        check(all(abs(x - y) < 2e-3 for x, y in zip(hi - lo, [v * 0.5 / 0.9 for v in LEVEL_SIZE])),
              "--rotate -22,0,0 levels the tilted box")

    if FAILS:
        raise SystemExit(f"{len(FAILS)} check(s) failed")


try:
    main()
except SystemExit:
    raise
except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)
