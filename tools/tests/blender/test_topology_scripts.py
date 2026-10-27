"""Blender-hosted tests for blender-mesh-topology's scripts: topology_audit (modifiers applied, slivers on flat faces,
poles of a reduction band and of a triangle fan, flipped faces, inverted islands on small shells far from the origin,
and a coarse-to-fine band built with its runs the wrong way round), the hard-surface checks against
references/hard-surface.md (the big-faces-flat figure per route and on wide chamfers, a column and an architrave,
hard_surface.py's Smooth by Angle and hand-off functions with their
refusals, audit_stack with the Triangulate live, off, applied or missing, routes from enabled modifiers only, a late
Smooth by Angle, flat shading, and normals_snapshot across UV work and scale), grid_topology in bmesh
(PointCache.weld, flat_fill, step_reduce), quad_remesh's patch_input, weld_layout and mirror_half (and a real engine
run when Quad Remesher is installed), review_render's headless wire over a mirrored mesh with the scene restored
afterwards, high_low_gap against a known sagitta, bake_skew with and without a bevel, and the high-poly routes the
high-and-low-poly reference calls verified headless (and brush sculpting, which is not).

Host: Blender 4.2+ (bpy, bmesh; tested on 5.2.2), run from anywhere:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_topology_scripts.py
Prints PASS <case> / SKIP <case>: <why> / FAIL <case>: <why>, and raises if any case failed.
"""

import math
import os
import re
import shutil
import tempfile
import traceback
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "skills" / "blender-mesh-topology" / "scripts"
TMP = Path(tempfile.mkdtemp(prefix="topology_test_"))
RESULTS = []


class Skip(Exception):
    pass


def case(fn):
    try:
        fn()
        RESULTS.append(("PASS", fn.__name__))
        print("PASS", fn.__name__)
    except Skip as exc:
        RESULTS.append(("SKIP", fn.__name__))
        print("SKIP %s: %s" % (fn.__name__, exc))
    except Exception as exc:  # noqa: BLE001
        RESULTS.append(("FAIL", fn.__name__))
        print("FAIL %s: %s" % (fn.__name__, exc))
        traceback.print_exc()


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def load(name):
    ns = {}
    path = SCRIPTS / name
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)
    return ns


AUDIT, GRID, QR, RR, HS = (load(n) for n in ("topology_audit.py", "grid_topology.py", "quad_remesh.py",
                                              "review_render.py", "hard_surface.py"))


def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def object_from_bmesh(name, bm):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def cube(name):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    return object_from_bmesh(name, bm)


def test_audit_applies_modifiers():
    fresh()
    ob = cube("Cube")
    ob.modifiers.new("sub", "SUBSURF").levels = 1
    bpy.context.view_layer.update()
    check(AUDIT["audit"](ob)["triangles"] == 48, "evaluated triangles")
    check(AUDIT["audit"](ob, evaluated=False)["triangles"] == 12, "mesh-data triangles")


def test_slivers_counted_on_flat_faces():
    fresh()
    bm = bmesh.new()
    vs = [bm.verts.new(co) for co in ((0, 0, 0), (1, 0, 0), (0.5, 0.004, 0))]
    f = bm.faces.new(vs)
    f.smooth = False
    ob = object_from_bmesh("Needle", bm)
    check(AUDIT["audit"](ob)["slivers"] == 1, "a flat-shaded needle is a sliver")


def band_object(n, groups):
    bm = bmesh.new()
    m = n + 2
    face = lambda vs: bm.faces.new(vs)                       # noqa: E731
    new_vert = lambda co: bm.verts.new(co)                   # noqa: E731
    up = [bm.verts.new((x, 2.0, 0.0)) for x in range(m * groups + 1)]
    top = [bm.verts.new((x, 1.0, 0.0)) for x in range(m * groups + 1)]
    bottom = [bm.verts.new((x * m / n, 0.0, 0.0)) for x in range(n * groups + 1)]
    down = [bm.verts.new((x * m / n, -1.0, 0.0)) for x in range(n * groups + 1)]
    GRID["ladder"](face, up, top)                              # same winding as the band's quads
    GRID["step_reduce"](face, new_vert, top, bottom, GRID["mid_along"](), n)
    GRID["ladder"](face, bottom, down)
    return object_from_bmesh("Band%d" % n, bm)


def test_reduction_bands_audit_clean_with_the_documented_poles():
    for n in (1, 2, 3):
        fresh()
        r = AUDIT["audit"](band_object(n, 2))
        check(AUDIT["problems"](r, allow_open=True) == [], "n=%d problems %s" % (n, AUDIT["problems"](r, True)))
        check(r["ngons"] == 0 and r["tri_faces_pct"] == 0, "n=%d not all quads" % n)
        check(r["poles"] == 5, "n=%d poles %d (want 4 valence-3 + 1 valence-6)" % (n, r["poles"]))
        check(r["fan_centres"] == 0, "n=%d fan centres" % n)


def test_flipped_faces_are_a_problem():
    fresh()
    good = cube("Good")
    bad = cube("OneFlipped")
    bad.data.polygons[0].flip()
    bad.data.update()
    r_good, r_bad = AUDIT["audit"](good), AUDIT["audit"](bad)
    check(r_good["flipped_edges"] == 0 and AUDIT["problems"](r_good) == [],
          "clean cube: %s" % AUDIT["problems"](r_good))
    check(r_bad["flipped_edges"] == 4, "one flipped quad: %d flipped edges, want 4" % r_bad["flipped_edges"])
    check("flipped_edges" in AUDIT["problems"](r_bad), "flipped face not in problems()")


def test_inverted_islands_on_small_shells_far_from_the_origin():
    """Thin closed tubes (2 cm long, 1 mm across) about 5 m from the mesh origin: summed in float32 about the origin
    their signed volumes were noise, and 7 of 280 good tubes read inverted (8 flipped ones did not)."""
    import random
    from mathutils import Matrix
    fresh()
    rng = random.Random(3)
    bm = bmesh.new()
    for _ in range(280):
        axis = Vector((rng.random(), rng.random(), rng.random())).normalized()
        at = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))).normalized() * rng.uniform(4.5, 5.5)
        m = Matrix.Translation(at) @ Matrix.Rotation(rng.uniform(0.0, 6.28), 4, axis)
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=True, segments=9, radius1=0.0005, radius2=0.0004,
                              depth=0.02, matrix=m)
    bmesh.ops.create_cube(bm, size=0.02, matrix=Matrix.Translation((5.0, -4.0, 3.0)))
    ob = object_from_bmesh("Petioles", bm)
    r = AUDIT["audit"](ob)
    check(r["islands"] == 281 and r["inverted_islands"] == 0,
          "%d of %d outward shells read inverted" % (r["inverted_islands"], r["islands"]))
    for p in ob.data.polygons:
        p.flip()
    ob.data.update()
    r = AUDIT["audit"](ob)
    check(r["inverted_islands"] == 281, "%d of 281 flipped shells read inverted" % r["inverted_islands"])
    check("inverted_islands" in AUDIT["problems"](r), "inverted shells not in problems()")


def test_second_band_on_a_ring_needs_its_runs_reversed():
    for reverse, want in ((False, True), (True, False)):
        fresh()
        bm = bmesh.new()
        face = lambda vs: bm.faces.new(vs)                       # noqa: E731
        new_vert = lambda co: bm.verts.new(co)                   # noqa: E731
        fine1 = [bm.verts.new((x, 2.0, 0.0)) for x in range(7)]
        coarse1 = [bm.verts.new((3.0 * x, 1.0, 0.0)) for x in range(3)]
        coarse2 = [bm.verts.new((3.0 * x, 0.0, 0.0)) for x in range(3)]
        fine2 = [bm.verts.new((x, -1.0, 0.0)) for x in range(7)]
        GRID["step_reduce"](face, new_vert, fine1, coarse1, GRID["mid_along"](), 1)
        GRID["ladder"](face, coarse1, coarse2)
        top, bottom = (fine2[::-1], coarse2[::-1]) if reverse else (fine2, coarse2)
        GRID["step_reduce"](face, new_vert, top, bottom, GRID["mid_along"](), 1)
        r = AUDIT["audit"](object_from_bmesh("Ring%d" % reverse, bm))
        check((r["flipped_edges"] > 0) == want, "reverse=%s: %d flipped edges" % (reverse, r["flipped_edges"]))


def test_poles_count_irregular_vertices_next_to_triangles():
    fresh()
    bm = bmesh.new()
    centre = bm.verts.new((0.0, 0.0, 0.0))
    ring = [bm.verts.new((math.cos(a * math.pi / 4), math.sin(a * math.pi / 4), 0.0)) for a in range(8)]
    for i in range(8):
        bm.faces.new((centre, ring[i], ring[(i + 1) % 8]))
    r = AUDIT["audit"](object_from_bmesh("Fan", bm))
    check(r["poles"] == 1 and r["fan_centres"] == 1, "a fan of 8 triangles: poles %d, fan centres %d"
          % (r["poles"], r["fan_centres"]))


def ridge(mark):
    """A 1 x 0.1 x 2 m panel whose front is two big flat faces meeting at a 13 deg fold, marked sharp or not."""
    h = 0.5 * math.tan(math.radians(13.0 / 2))
    bm = bmesh.new()
    f = [bm.verts.new(c) for c in ((0, 0, 0), (0.5, -h, 0), (1, 0, 0), (1, 0, 2), (0.5, -h, 2), (0, 0, 2))]
    b = [bm.verts.new(c) for c in ((0, 0.1, 0), (1, 0.1, 0), (1, 0.1, 2), (0, 0.1, 2))]
    for vs in ([f[0], f[1], f[4], f[5]], [f[1], f[2], f[3], f[4]], [b[0], b[3], b[2], b[1]], [f[0], f[5], b[3], b[0]],
               [f[2], b[1], b[2], f[3]], [f[0], b[0], b[1], f[2], f[1]], [f[5], f[4], f[3], b[2], b[3]]):
        bm.faces.new(vs)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for face in bm.faces:
        face.smooth = True
    bm.edges.ensure_lookup_table()
    if mark:
        for e in bm.edges:
            if set(e.verts) == {f[1], f[4]}:
                e.smooth = False                                 # Edge > Mark Sharp
    return object_from_bmesh("Ridge", bm)


def panel(smooth=True, name="Panel"):
    """The 1 x 0.08 x 2 m panel of hard-surface.md, shaded smooth unless smooth=False (as primitives come)."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(1.0, 0.08, 2.0), verts=bm.verts)
    for face in bm.faces:
        face.smooth = smooth
    return object_from_bmesh(name, bm)


def column(segments=16):
    """A 2.5 m column of radius 0.15 m with flat caps, shaded smooth: a curved part."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments, radius1=0.15, radius2=0.15, depth=2.5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for face in bm.faces:
        face.smooth = True
    return object_from_bmesh("Column", bm)


def hard_surface_stack(ob, route, keep=True, angle_limit=None, smooth_by_angle=None, width=0.01, segments=2):
    """hard-surface.md's stacks: route A Bevel (Harden) -> Triangulate (Keep Normals); route B Bevel (Face Strength
    Affected) -> Triangulate -> Weighted Normal; optionally Smooth by Angle first, through hard_surface.py."""
    bev = ob.modifiers.new("Bevel", "BEVEL")
    bev.limit_method, bev.width, bev.segments = "ANGLE", width, segments
    if angle_limit is not None:
        bev.angle_limit = math.radians(angle_limit)
    if route == "A":
        bev.harden_normals = True
    else:
        bev.face_strength_mode = "FSTR_AFFECTED"
    tri = ob.modifiers.new("Triangulate", "TRIANGULATE")
    tri.min_vertices, tri.keep_custom_normals = 4, keep                   # Keep Normals on both routes
    if route == "B":
        wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
        wn.mode, wn.keep_sharp, wn.use_face_influence = "FACE_AREA", True, True
    if smooth_by_angle is not None:
        sba = HS["smooth_by_angle_first"](ob, smooth_by_angle)
        check(ob.modifiers[0] == sba and not sba.use_pin_to_last, "Smooth by Angle not unpinned and moved first")
    bpy.context.view_layer.update()
    return ob


def test_big_faces_flat_check_and_the_fold_rule_per_route():
    cases = (("route B, fold marked sharp", dict(route="B"), True, False),
             ("route A, fold marked sharp", dict(route="A"), True, True),
             ("route A, fold left smooth", dict(route="A"), False, False),
             ("route B, fold left smooth", dict(route="B"), False, False),
             ("route B, fold chamfered (angle limit 10)", dict(route="B", angle_limit=10), False, True),
             ("route B, Smooth by Angle 10 first", dict(route="B", smooth_by_angle=10), False, True),
             ("route B, Smooth by Angle 30 first", dict(route="B", smooth_by_angle=30), False, False))
    for label, kw, mark, flat_ok in cases:
        fresh()
        ob = hard_surface_stack(ridge(mark), **kw)
        r = AUDIT["audit"](ob)
        off = r["flat_faces_off_deg"]
        print("INFO %s: big faces %.2f deg off flat" % (label, off))
        check((off < 0.5) == flat_ok, "%s: big faces %.2f deg off flat" % (label, off))
        check(("flat_faces_off_deg" in AUDIT["problems"](r, flat_tol=0.5)) != flat_ok, "%s: problems()" % label)
        check("flat_faces_off_deg" not in AUDIT["problems"](r), "flat check failed without flat_tol")


def test_flat_check_passes_wide_single_segment_chamfers():
    """15 and 20 mm one-segment chamfers are 21-28 mm wide faces whose corners carry the big faces' normals: the
    5 cm floor leaves them out (a 2 cm floor failed them at 45-55 deg)."""
    for route in ("A", "B"):
        for width in (0.015, 0.02):
            fresh()
            ob = hard_surface_stack(panel(), route, width=width, segments=1)
            narrow = AUDIT["audit"](ob, min_flat_width=0.02)["flat_faces_off_deg"]
            s = AUDIT["audit_stack"](ob, flat_tol=0.5)
            print("INFO route %s, %d mm, 1 segment: %.2f deg with a 2 cm floor, %.2f with 5 cm, problems %s"
                  % (route, width * 1000, narrow, s["merged"]["flat_faces_off_deg"], s["problems"]))
            check(narrow > 40, "fixture: a 2 cm floor should judge the chamfer (%.2f)" % narrow)
            check(s["merged"]["flat_faces_off_deg"] < 0.5 and s["problems"] == [],
                  "route %s, %d mm: %s" % (route, width * 1000, s["problems"]))


def test_smooth_by_angle_function_touches_only_its_piece():
    """The page's smooth_by_angle_first(ob, angle) on a piece that is not selected while two other pieces are (one
    active): the others keep their stack, shading and selection, and a second run gives the same stack."""
    fresh()
    others = [panel(smooth=False, name="Other_%d" % i) for i in range(2)]
    ob = panel(smooth=False, name="Target")
    hard_surface_stack(ob, "B")
    for o in others:
        o.select_set(True)
    bpy.context.view_layer.objects.active = others[0]
    fn = HS["smooth_by_angle_first"]

    def stack():
        return [(m.type, m.name, m.use_pin_to_last,
                 round(math.degrees(m.properties.inputs.Input_1.value), 3) if m.type == "NODES" else None)
                for m in ob.modifiers]
    fn(ob, 10)
    first = stack()
    fn(ob, 10)
    check(stack() == first, "a rerun changed the stack: %s -> %s" % (first, stack()))
    check(first[0][0] == "NODES" and first[0][2] is False and first[0][3] == 10.0 and len(first) == 4,
          "stack %s" % first)
    check(all(p.use_smooth for p in ob.data.polygons), "the piece was not shaded smooth")
    for o in others:
        check(len(o.modifiers) == 0 and not any(p.use_smooth for p in o.data.polygons) and o.select_get(),
              "%s was touched: %s" % (o.name, [m.name for m in o.modifiers]))
    check(bpy.context.view_layer.objects.active == others[0] and not ob.select_get(), "selection changed")


def test_audit_stack_judges_a_stack_triangulated_piece():
    fresh()
    good = hard_surface_stack(panel(), "A")
    plain = AUDIT["audit"](good)
    check(plain["slivers"] > 0, "fixture: the triangulated chamfer strips should be slivers to a plain audit")
    s = AUDIT["audit_stack"](good, flat_tol=0.5)
    check(s["route"] == "A" and s["triangulate"] == "live" and s["problems"] == [] and s["normals_change_deg"] < 0.5,
          "route A with Keep Normals: %s, change %s" % (s["problems"], s["normals_change_deg"]))
    check(s["off"]["slivers"] == 0 and s["merged"]["slivers"] == 0, "slivers not judged before the Triangulate")
    check(all(m.show_viewport for m in good.modifiers), "a Triangulate was left switched off")
    fresh()
    slip = hard_surface_stack(panel(), "A", keep=False)
    s = AUDIT["audit_stack"](slip, flat_tol=0.5)
    check("triangulate_moves_normals" in s["problems"] and s["normals_change_deg"] > 5,
          "Keep Normals off not caught: %s, change %s" % (s["problems"], s["normals_change_deg"]))
    fresh()
    s = AUDIT["audit_stack"](hard_surface_stack(panel(), "B"), flat_tol=0.5)
    check(s["route"] == "B" and s["problems"] == [] and s["normals_change_deg"] is None,
          "route B: %s, route %s, change %s" % (s["problems"], s["route"], s["normals_change_deg"]))


def apply_modifiers(ob, names):
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
        for name in names:
            bpy.ops.object.modifier_apply(modifier=name)
    bpy.context.view_layer.update()


def test_audit_stack_without_a_live_triangulate():
    """The Triangulate switched off, set to n-gons only, or applied; and a piece with no stack (route None)."""
    for route in ("A", "B"):
        fresh()
        ob = hard_surface_stack(panel(), route)
        ob.modifiers["Triangulate"].show_viewport = False
        s = AUDIT["audit_stack"](ob, flat_tol=0.5)
        check(s["route"] == route and s["triangulate"] == "disabled" and "custom_normals_on_quads" in s["problems"]
              and not ob.modifiers["Triangulate"].show_viewport, "route %s, Triangulate off: %s %s"
              % (route, s["triangulate"], s["problems"]))
    fresh()
    ob = hard_surface_stack(panel(), "B")
    ob.modifiers["Triangulate"].min_vertices = 5
    s = AUDIT["audit_stack"](ob, flat_tol=0.5)
    check("custom_normals_on_quads" in s["problems"], "route B, n-gons only: %s" % s["problems"])
    for route in ("A", "B"):
        fresh()
        ob = hard_surface_stack(panel(), route)
        live = AUDIT["audit_stack"](ob)["off"]
        apply_modifiers(ob, ["Bevel", "Triangulate"])
        s = AUDIT["audit_stack"](ob, flat_tol=0.5)
        print("INFO route %s, Bevel and Triangulate applied: slivers %d as exported, %d with pairs joined, problems %s"
              % (route, s["on"]["slivers"], s["off"]["slivers"], s["problems"]))
        check(s["route"] == route and s["triangulate"] == "applied" and s["on"]["slivers"] > 0
              and s["problems"] == [], "route %s applied: %s %s" % (route, s["triangulate"], s["problems"]))
        same = [k for k in ("slivers", "poles", "fan_centres", "tri_faces_pct") if s["off"][k] != live[k]]
        check(not same, "route %s applied: %s differ from the live stack's untriangulated pass" % (route, same))
    fresh()
    s = AUDIT["audit_stack"](cube("Plain"), flat_tol=0.5)
    check(s["route"] is None and s["triangulate"] == "none" and s["problems"] == [], "plain cube: %s" % s)


def test_audit_stack_route_follows_the_enabled_modifiers():
    """Only Triangulates below the last enabled Weighted Normal are compared; a disabled Weighted Normal is no route
    B."""
    fresh()
    ob = hard_surface_stack(panel(), "B")
    extra = ob.modifiers.new("Triangulate.2", "TRIANGULATE")       # after the Weighted Normal, Keep Normals off
    extra.min_vertices = 4
    s = AUDIT["audit_stack"](ob, flat_tol=0.5)
    check(s["route"] == "B" and s["problems"] == [], "route B + a 2nd Triangulate: %s, change %s"
          % (s["problems"], s["normals_change_deg"]))
    fresh()
    ob = hard_surface_stack(panel(), "A", keep=False)
    wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
    wn.show_viewport = False
    s = AUDIT["audit_stack"](ob, flat_tol=0.5)
    check(s["route"] == "A" and "triangulate_moves_normals" in s["problems"], "disabled Weighted Normal: %s %s"
          % (s["route"], s["problems"]))
    fresh()
    ob = panel()
    bev = ob.modifiers.new("Bevel", "BEVEL")
    bev.limit_method, bev.width, bev.segments, bev.face_strength_mode = "ANGLE", 0.01, 2, "FSTR_AFFECTED"
    wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
    wn.mode, wn.keep_sharp, wn.use_face_influence = "FACE_AREA", True, True
    below = ob.modifiers.new("Triangulate", "TRIANGULATE")                 # below the Weighted Normal
    below.min_vertices = 4
    for keep, want in ((False, {"triangulate_moves_normals", "triangulate_below_weighted_normal"}),
                       (True, {"triangulate_below_weighted_normal"})):
        below.keep_custom_normals = keep
        bpy.context.view_layer.update()
        s = AUDIT["audit_stack"](ob)
        check(s["route"] == "B" and want <= set(s["problems"]) and (keep or s["normals_change_deg"] > 5)
              and not (keep and "triangulate_moves_normals" in s["problems"]),
              "Triangulate below the Weighted Normal, Keep Normals %s: %s, change %s"
              % (keep, s["problems"], s["normals_change_deg"]))


def test_audit_stack_names_a_late_smooth_by_angle_and_flat_shading():
    for route in ("A", "B"):
        fresh()
        ob = hard_surface_stack(panel(), route)
        before = AUDIT["normals_snapshot"](ob)
        with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob],
                                       selected_editable_objects=[ob]):
            bpy.ops.object.shade_auto_smooth()                         # pinned last: on top of the stack
        s = AUDIT["audit_stack"](ob, flat_tol=0.5, before=before)
        print("INFO route %s + Shade Auto Smooth on top: normals moved %.2f deg, problems %s"
              % (route, s["snapshot_change_deg"], s["problems"]))
        check("smooth_by_angle_late" in s["problems"] and "triangulate_moves_normals" not in s["problems"],
              "route %s: %s" % (route, s["problems"]))
    for route, flagged in (("A", False), ("B", True)):
        fresh()
        s = AUDIT["audit_stack"](hard_surface_stack(panel(smooth=False), route), flat_tol=0.5)
        check(("flat_shaded_faces" in s["problems"]) == flagged, "flat-shaded route %s: %s" % (route, s["problems"]))


def test_normals_snapshot_catches_uv_work_that_loses_the_normals():
    """UV work as hard-surface.md says (apply_for_uv_work, layout with the Triangulate off, then on again) keeps the
    normals, scale applied in between included; applying the Bevel alone, or shading by angle afterwards, does not."""
    def piece(route):
        fresh()
        ob = hard_surface_stack(ridge(False), route, smooth_by_angle=10)
        ob.scale = (2.0, 2.0, 2.0)
        bpy.context.view_layer.update()
        return ob, AUDIT["normals_snapshot"](ob)
    apply_for_uv_work = HS["apply_for_uv_work"]
    for route in ("A", "B"):
        ob, snap = piece(route)
        apply_for_uv_work(ob)
        with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob],
                                       selected_editable_objects=[ob]):
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        during = AUDIT["audit_stack"](ob, flat_tol=0.5, before=snap)
        check("custom_normals_on_quads" in during["problems"] and during["triangulate"] == "disabled",
              "route %s during layout: %s" % (route, during["problems"]))
        ob.modifiers["Triangulate"].show_viewport = True
        s = AUDIT["audit_stack"](ob, flat_tol=0.5, before=snap)
        check(s["problems"] == [] and s["snapshot_change_deg"] < 0.5 and s["snapshot_matched"] == 1.0,
              "route %s from the top: %s, change %s, matched %s" % (route, s["problems"], s["snapshot_change_deg"],
                                                                     s["snapshot_matched"]))
        check([m.type for m in ob.modifiers] == (["TRIANGULATE"] if route == "A" else ["TRIANGULATE",
                                                                                     "WEIGHTED_NORMAL"]),
              "stack left %s" % [m.type for m in ob.modifiers])

        ob, snap = piece(route)
        apply_modifiers(ob, ["Bevel"])                                  # the Bevel alone
        s = AUDIT["audit_stack"](ob, flat_tol=0.5, before=snap)
        print("INFO route %s, Bevel applied alone: normals moved %.2f deg, problems %s"
              % (route, s["snapshot_change_deg"], s["problems"]))
        check("normals_changed_since_snapshot" in s["problems"] and "smooth_by_angle_without_bevel" in s["problems"],
              "route %s, Bevel alone: %s" % (route, s["problems"]))
    ob, snap = piece("A")
    apply_for_uv_work(ob)
    ob.modifiers["Triangulate"].show_viewport = True
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(30))
    s = AUDIT["audit_stack"](ob, flat_tol=0.5, before=snap)
    print("INFO route A, shaded by angle after UV work: normals moved %.2f deg" % s["snapshot_change_deg"])
    check("normals_changed_since_snapshot" in s["problems"], "shading by angle afterwards: %s" % s["problems"])


def half_ridge():
    """The ridge's right half, cut at the 13 deg fold (x = 0), open there: a Mirror makes the whole ridge."""
    h = 0.5 * math.tan(math.radians(13.0 / 2))
    bm = bmesh.new()
    f = [bm.verts.new(c) for c in ((0, -h, 0), (0.5, 0, 0), (0.5, 0, 2), (0, -h, 2))]
    b = [bm.verts.new(c) for c in ((0, 0.1, 0), (0.5, 0.1, 0), (0.5, 0.1, 2), (0, 0.1, 2))]
    for vs in ([f[0], f[1], f[2], f[3]], [b[0], b[3], b[2], b[1]], [f[1], b[1], b[2], f[2]], [f[0], b[0], b[1], f[1]],
               [f[3], f[2], b[2], b[3]]):
        bm.faces.new(vs)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for face in bm.faces:
        face.smooth = True
    return object_from_bmesh("HalfRidge", bm)


def half_panel():
    """The panel's x >= 0 half, open at x = 0: a Mirror makes the whole panel."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(1.0, 0.08, 2.0), verts=bm.verts)
    bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, 0, 0), plane_no=(1, 0, 0),
                           clear_inner=True)
    for face in bm.faces:
        face.smooth = True
    return object_from_bmesh("HalfPanel", bm)


def test_uv_work_keeps_a_trailing_mirror_live_and_applies_one_above_a_bevel():
    """Route B. Mirror below the Bevel (a half panel): apply_for_uv_work leaves the Mirror live and first,
    apply_before_layout applies it, normals kept. Mirror above the Bevel (a half ridge, its fold on the mirror plane,
    chamfered at a 10 deg limit): applied in the top-down run, normals kept; applying the Bevel alone under the Mirror
    loses the chamfer on the mirror plane."""
    apply_for_uv_work, apply_before_layout = HS["apply_for_uv_work"], HS["apply_before_layout"]

    def piece(mirror_first):
        fresh()
        ob = half_ridge() if mirror_first else half_panel()
        if mirror_first:
            ob.modifiers.new("Mirror", "MIRROR").use_clip = True
        hard_surface_stack(ob, "B", angle_limit=10)
        if not mirror_first:
            m = ob.modifiers.new("Mirror", "MIRROR")
            m.use_clip = True
            with bpy.context.temp_override(object=ob, active_object=ob):
                bpy.ops.object.modifier_move_to_index(modifier="Mirror", index=1)    # Bevel > Mirror > Tri > WN
        bpy.context.view_layer.update()
        return ob, AUDIT["normals_snapshot"](ob)

    ob, snap = piece(mirror_first=False)
    apply_for_uv_work(ob)
    check([m.type for m in ob.modifiers] == ["MIRROR", "TRIANGULATE", "WEIGHTED_NORMAL"],
          "a trailing Mirror was not left live: %s" % [m.type for m in ob.modifiers])
    apply_before_layout(ob)
    ob.modifiers["Triangulate"].show_viewport = True
    s = AUDIT["audit_stack"](ob, flat_tol=0.5, before=snap)
    check([m.type for m in ob.modifiers] == ["TRIANGULATE", "WEIGHTED_NORMAL"] and s["problems"] == [],
          "Bevel > Mirror: %s, %s" % ([m.type for m in ob.modifiers], s["problems"]))

    ob, snap = piece(mirror_first=True)
    apply_for_uv_work(ob)
    ob.modifiers["Triangulate"].show_viewport = True
    s = AUDIT["audit_stack"](ob, flat_tol=0.5, before=snap)
    check([m.type for m in ob.modifiers] == ["TRIANGULATE", "WEIGHTED_NORMAL"] and s["problems"] == [],
          "Mirror > Bevel, top-down: %s, %s" % ([m.type for m in ob.modifiers], s["problems"]))

    ob, snap = piece(mirror_first=True)
    faces = AUDIT["audit"](ob)["faces"]
    apply_modifiers(ob, ["Bevel"])                                     # the Bevel alone, under the live Mirror
    s = AUDIT["audit_stack"](ob, flat_tol=0.5, before=snap)
    print("INFO Mirror > Bevel, Bevel applied alone: faces %d -> %d, positions matched %.3f, problems %s"
          % (faces, s["on"]["faces"], s["snapshot_matched"], s["problems"]))
    check(s["on"]["faces"] < faces and "snapshot_geometry_changed" in s["problems"],
          "Bevel alone under a Mirror: %s" % s["problems"])


def test_flat_faces_list_curved_parts_by_mesh_face():
    """A smooth column is over the flat tolerance by design: every such face is listed by the mesh data's face index
    with its centre, all on the curved side, none on the flat caps."""
    for route in ("A", "B"):
        fresh()
        ob = hard_surface_stack(column(), route)
        r = AUDIT["audit_stack"](ob, flat_tol=0.5)["merged"]
        faces = ob.data.polygons
        print("INFO 16-segment column, route %s: %.2f deg, %d faces listed" % (route, r["flat_faces_off_deg"],
                                                                             len(r["flat_faces"])))
        check(r["flat_faces_off_deg"] > 5 and r["flat_faces"], "column route %s: %s" % (route, r["flat_faces_off_deg"]))
        check(r["flat_worst_face"] == r["flat_faces"][0]["face"], "worst face %s" % r["flat_worst_face"])
        for f in r["flat_faces"]:
            check(0 <= f["face"] < len(faces) and abs(faces[f["face"]].normal.z) < 0.1,
                  "listed face %s is not a side face of the mesh data" % f)
            check(0.14 < math.hypot(f["centre"][0], f["centre"][1]) < 0.151, "centre off the side: %s" % (f,))


def architrave(mark_folds):
    """A 1 m run of a 70 x 20 mm architrave: faces 5-30 mm wide, folds of 12 and 10 deg (marked sharp when asked)."""
    pts = [(0.070, 0.0), (0.070, 0.008)]
    x, y = 0.070, 0.008
    x, y = x - 0.030 * math.cos(math.radians(12)), y + 0.030 * math.sin(math.radians(12))
    pts.append((x, y))
    y += 0.005
    pts.append((x, y))
    x -= 0.025
    pts.append((x, y))
    x, y = x - 0.015 * math.cos(math.radians(10)), y - 0.015 * math.sin(math.radians(10))
    pts += [(x, y), (x, 0.0)]
    bm = bmesh.new()
    lo = [bm.verts.new((px, py, 0.0)) for px, py in pts]
    hi = [bm.verts.new((px, py, 1.0)) for px, py in pts]
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        bm.faces.new([lo[i], lo[j], hi[j], hi[i]])
    bm.faces.new(list(reversed(lo)))
    bm.faces.new(hi)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for face in bm.faces:
        face.smooth = True
    if mark_folds:
        for e in bm.edges:
            if len(e.link_faces) == 2 and 1 < math.degrees(e.link_faces[0].normal.angle(e.link_faces[1].normal)) < 30:
                e.smooth = False
    return object_from_bmesh("Architrave", bm)


def test_flat_floor_follows_the_live_bevel():
    """The floor is 2.1 x the largest live Bevel amount (5 cm without one): an architrave's narrow faces are judged
    (a route B fold marked sharp is caught, route A passes), and wide chamfers still pass."""
    results = {}
    for route in ("A", "B"):
        fresh()
        ob = hard_surface_stack(architrave(True), route, width=0.002, segments=1)
        s = AUDIT["audit_stack"](ob, flat_tol=0.5)
        results[route] = s
        print("INFO architrave route %s, folds marked: %.2f deg (floor %.4f m; a 5 cm floor reads %.2f), problems %s"
              % (route, s["merged"]["flat_faces_off_deg"], s["merged"]["flat_min_width"],
                 AUDIT["audit"](ob, min_flat_width=0.05)["flat_faces_off_deg"], s["problems"]))
        check(abs(s["merged"]["flat_min_width"] - 0.005) < 1e-9, "floor %s (2.1 x 2 mm under the 5 mm minimum)"
              % s["merged"]["flat_min_width"])
    check(results["A"]["problems"] == [], "architrave route A: %s" % results["A"]["problems"])
    check("flat_faces_off_deg" in results["B"]["problems"] and results["B"]["merged"]["flat_faces_off_deg"] > 5,
          "architrave route B with marked folds was not caught: %s" % results["B"]["problems"])
    fresh()
    ob = hard_surface_stack(panel(), "B", width=0.02, segments=1)
    r = AUDIT["audit"](ob)
    check(abs(r["flat_min_width"] - 0.042) < 1e-9 and r["flat_faces_off_deg"] < 0.5, "20 mm panel: floor %s, %.2f"
          % (r["flat_min_width"], r["flat_faces_off_deg"]))
    ob.modifiers["Bevel"].show_viewport = False
    check(AUDIT["audit"](ob)["flat_min_width"] == 0.05, "no live Bevel: 5 cm")


def half_column():
    """The x >= 0 half of a 16-segment column, open at x = 0, shaded smooth."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=16, radius1=0.15, radius2=0.15, depth=2.5)
    bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, 0, 0), plane_no=(1, 0, 0),
                           clear_inner=True)
    for face in bm.faces:
        face.smooth = True
    return object_from_bmesh("HalfColumn", bm)


def test_flat_faces_list_each_mesh_face_once():
    """A mirrored half column with a live Triangulate: both halves and both triangles of a quad fold into one entry
    per face of the mesh data."""
    fresh()
    ob = half_column()
    m = ob.modifiers.new("Mirror", "MIRROR")
    m.use_clip = True
    hard_surface_stack(ob, "A")
    r = AUDIT["audit_stack"](ob, flat_tol=0.5)["merged"]
    faces = [f["face"] for f in r["flat_faces"]]
    sides = sum(1 for p in ob.data.polygons if abs(p.normal.z) < 0.1)
    print("INFO mirrored half column: %d entries for %d side faces of the mesh data" % (len(faces), sides))
    check(faces and len(faces) == len(set(faces)) and len(faces) <= sides, "flat_faces %s" % faces)


def test_smooth_by_angle_function_placement_and_edit_mode():
    """Below a leading Mirror (where it sees a fold on the mirror plane); refused, with nothing changed, outside
    Object Mode."""
    fresh()
    ob = half_ridge()
    ob.modifiers.new("Mirror", "MIRROR").use_clip = True
    hard_surface_stack(ob, "B")
    HS["smooth_by_angle_first"](ob, 10)
    check([m.type for m in ob.modifiers] == ["MIRROR", "NODES", "BEVEL", "TRIANGULATE", "WEIGHTED_NORMAL"],
          "stack %s" % [m.type for m in ob.modifiers])
    s = AUDIT["audit_stack"](ob, flat_tol=0.5)
    check(s["problems"] == [], "fold on the mirror plane: %s" % s["problems"])
    fresh()
    ob = hard_surface_stack(panel(), "B")
    other = cube("Other")
    bpy.context.view_layer.objects.active = other
    other.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        HS["smooth_by_angle_first"](ob, 10)
    except RuntimeError as exc:
        check("Object Mode" in str(exc), "unclear message: %s" % exc)
    else:
        raise AssertionError("ran in Edit Mode")
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    check([m.type for m in ob.modifiers] == ["BEVEL", "TRIANGULATE", "WEIGHTED_NORMAL"], "the stack changed")


def test_hand_off_refusals_and_topology_types():
    """apply_for_uv_work refuses a topology change below the Triangulate, a modifier to apply that is off in the
    viewport (Blender would apply it), shape keys and a shared mesh, changing nothing; it applies a Decimate or Weld
    above the Triangulate with the Bevel. audit_stack names a Mirror or Array under the stack."""
    afu = HS["apply_for_uv_work"]

    def refused(ob, words):
        before = [(m.type, m.show_viewport) for m in ob.modifiers]
        faces = len(ob.data.polygons)
        try:
            afu(ob)
        except ValueError as exc:
            check(words in str(exc), "message %r lacks %r" % (str(exc), words))
        else:
            raise AssertionError("not refused: %s" % words)
        check([(m.type, m.show_viewport) for m in ob.modifiers] == before and len(ob.data.polygons) == faces,
              "a refused hand-off changed the piece")

    for kind in ("MIRROR", "ARRAY"):
        fresh()
        ob = hard_surface_stack(half_panel() if kind == "MIRROR" else panel(), "B")
        ob.modifiers.new(kind.title(), kind)                      # appended: below the Weighted Normal
        s = AUDIT["audit_stack"](ob, flat_tol=0.5)
        print("INFO %s appended under route B: flat %.2f, problems %s"
              % (kind.title(), s["merged"]["flat_faces_off_deg"], s["problems"]))
        check("topology_below_triangulate" in s["problems"], "%s appended not named: %s" % (kind, s["problems"]))
        refused(ob, "below the Triangulate")
    fresh()
    ob = half_panel()
    mirror = ob.modifiers.new("Mirror", "MIRROR")
    hard_surface_stack(ob, "B")
    mirror.show_viewport = False
    refused(ob, "off in the viewport")
    with bpy.context.temp_override(object=ob, active_object=ob):
        bpy.ops.object.modifier_apply(modifier="Mirror")               # what Blender does without the refusal
    check(len(ob.data.polygons) == 10, "fixture: a disabled Mirror applied gives %d faces" % len(ob.data.polygons))
    fresh()
    ob = hard_surface_stack(panel(), "A")
    ob.shape_key_add(name="Basis")
    refused(ob, "shape keys")
    fresh()
    ob = hard_surface_stack(panel(), "A")
    twin = bpy.data.objects.new("Twin", ob.data)
    bpy.context.scene.collection.objects.link(twin)
    refused(ob, "shares its mesh")
    for kind in ("DECIMATE", "WELD"):
        fresh()
        ob = hard_surface_stack(panel(), "B")
        m = ob.modifiers.new(kind.title(), kind)
        with bpy.context.temp_override(object=ob, active_object=ob):
            bpy.ops.object.modifier_move_to_index(modifier=m.name, index=1)
        out = afu(ob)
        check(out["applied"] == ["Bevel", m.name] and [x.type for x in ob.modifiers] == ["TRIANGULATE",
                                                                                         "WEIGHTED_NORMAL"],
              "%s above the Triangulate: %s, %s" % (kind, out, [x.type for x in ob.modifiers]))


def test_scale_goes_before_the_stack_or_after_the_hand_off():
    """Scale applied under a live Bevel resizes the chamfers (snapshot_geometry_changed); after the hand-off it is
    harmless."""
    for scale_first in (True, False):
        fresh()
        ob = hard_surface_stack(panel(), "A")
        ob.scale = (2.0, 2.0, 2.0)
        bpy.context.view_layer.update()
        snap = AUDIT["normals_snapshot"](ob)
        steps = ["scale", "hand-off"] if scale_first else ["hand-off", "scale"]
        for step in steps:
            if step == "scale":
                with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob],
                                               selected_editable_objects=[ob]):
                    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            else:
                HS["apply_for_uv_work"](ob)
        ob.modifiers["Triangulate"].show_viewport = True
        s = AUDIT["audit_stack"](ob, before=snap)
        check(("snapshot_geometry_changed" in s["problems"]) == scale_first,
              "%s: %s (matched %s)" % (" then ".join(steps), s["problems"], s["snapshot_matched"]))


def test_point_cache_weld_points_at_survivors():
    fresh()
    bm = bmesh.new()
    cache = GRID["PointCache"](bm, digits=6)
    a = cache.get((4e-7, 0.0, 0.0))                            # rounds to 0.0
    b = cache.get((6e-7, 0.0, 0.0))                            # rounds to 1e-06: a second vertex 2e-7 away
    check(a is not b and len(bm.verts) == 2, "fixture: two cached verts")
    merged = cache.weld(1e-5)
    check(merged == 1 and len(bm.verts) == 1, "merged %d, verts %d" % (merged, len(bm.verts)))
    for co in ((4e-7, 0.0, 0.0), (6e-7, 0.0, 0.0)):
        v = cache.get(co)
        check(v.is_valid and len(bm.verts) == 1, "cache returned a removed or new vertex for %s" % (co,))
    bm.free()


def test_flat_fill_returns_live_faces_covering_the_region():
    fresh()
    bm = bmesh.new()
    loop = [bm.verts.new((math.cos(a * math.pi / 4), math.sin(a * math.pi / 4), 0.0)) for a in range(8)]
    faces = GRID["flat_fill"](bm, loop)                         # a regular octagon: 6 triangles pair into quads
    check(faces and all(f.is_valid for f in faces), "returned removed faces")
    check(len(faces) == len(bm.faces), "returned %d of %d faces" % (len(faces), len(bm.faces)))
    check(abs(sum(f.calc_area() for f in faces) - 2 * math.sqrt(2)) < 1e-5, "faces do not cover the octagon")
    check(sum(len(f.verts) == 4 for f in faces) >= 2, "triangles were not joined into quads")
    bm.free()


def grid_patch():
    """A 1 x 1 patch on x 0..1 as an engine-like result: 3 x 3 quads, border loop of 12 points, 4 interior points."""
    pts = [(x / 3.0, y / 3.0, 0.0) for y in range(4) for x in range(4)]
    faces = [(y * 4 + x, y * 4 + x + 1, (y + 1) * 4 + x + 1, (y + 1) * 4 + x) for y in range(3) for x in range(3)]
    ring = [(x, 0) for x in range(4)] + [(3, y) for y in range(1, 4)] + [(x, 3) for x in range(2, -1, -1)] + \
           [(0, y) for y in range(2, 0, -1)]
    loop = [Vector((x / 3.0, y / 3.0, 0.0)) for x, y in ring]
    return [Vector(p) for p in pts], faces, loop


def test_weld_layout_and_mirror_half():
    fresh()
    qp, qf, loop = grid_patch()
    lay = QR["weld_layout"](qp, qf, loop)
    check(lay is not None, "a clean patch was rejected")
    faces, npos = lay
    check(len(faces) == 9 and len(npos) == 4, "faces %d, new points %d" % (len(faces), len(npos)))
    bad = QR["weld_layout"](qp, qf[:-1], loop)                  # a hole: border no longer the loop
    check(bad is None, "a patch with a hole was accepted")
    bm = bmesh.new()
    cache = GRID["PointCache"](bm)
    loop_verts = [cache.get(p) for p in loop]
    face = lambda vs: bm.faces.new(vs)                       # noqa: E731
    for sign in (1, -1):
        QR["mirror_half"](faces, npos, loop_verts, lambda lv: cache.get((-lv.co.x, lv.co.y, lv.co.z)),
                          lambda co: cache.get(co), face, sign)
    bm.normal_update()
    check(len(bm.faces) == 18, "faces %d" % len(bm.faces))
    check(all(f.normal.z > 0.99 for f in bm.faces), "mirrored half faces the other way")
    check(all(len(e.link_faces) <= 2 for e in bm.edges), "overfull edges at the mirror line")
    bm.free()


def test_patch_input_walks_the_border():
    """patch_input: a 4 x 3 quad patch gives its 20 points, 24 triangles and the 14-point border in order; a patch
    with a hole (two borders) is refused."""
    def grid(hole):
        bm = bmesh.new()
        vs = [[bm.verts.new((x / 4.0, y / 3.0, 0.0)) for x in range(5)] for y in range(4)]
        for y in range(3):
            for x in range(4):
                if not (hole and (x, y) == (1, 1)):
                    bm.faces.new((vs[y][x], vs[y][x + 1], vs[y + 1][x + 1], vs[y + 1][x]))
        return object_from_bmesh("Patch", bm)
    fresh()
    pts, tris, loop = QR["patch_input"](grid(False))
    check(len(pts) == 20 and len(tris) == 24 and all(len(t) == 3 for t in tris), "pts %d, tris %d"
          % (len(pts), len(tris)))
    check(len(loop) == 14 and len({tuple(round(c, 6) for c in p) for p in loop}) == 14, "loop %d points" % len(loop))
    check(all(min(p.x, 1 - p.x, p.y, 1 - p.y) < 1e-6 for p in loop), "a loop point off the border")
    for i in range(len(loop)):
        d = (loop[i] - loop[i - 1]).length
        check(abs(d - 0.25) < 1e-6 or abs(d - 1 / 3.0) < 1e-6, "loop step %d is %.4f: not along the border" % (i, d))
    try:
        QR["patch_input"](grid(True))
    except ValueError:
        pass
    else:
        raise AssertionError("a patch with a hole was accepted")


def test_quad_remesh_engine_round_trip():
    engine = QR["find_engine"]()
    if not os.path.exists(engine):
        raise Skip("Quad Remesher engine not installed (%s)" % engine)
    fresh()
    n = 8                                                      # border points per side: 32 in the loop (even)
    loop = [Vector((i / n, 0, 0)) for i in range(n)] + [Vector((1, i / n, 0)) for i in range(n)] + \
           [Vector((1 - i / n, 1, 0)) for i in range(n)] + [Vector((0, 1 - i / n, 0)) for i in range(n)]
    pts = [Vector((x / n, y / n, 0)) for y in range(n + 1) for x in range(n + 1)]
    tris = []
    for y in range(n):
        for x in range(n):
            a, b, c, d = y * (n + 1) + x, y * (n + 1) + x + 1, (y + 1) * (n + 1) + x + 1, (y + 1) * (n + 1) + x
            tris += [(a, b, c), (a, c, d)]
    before = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials))
    try:
        faces, npos, raw = QR["remesh_patch"](pts, tris, loop, target=16, mats=[0] * len(tris), timeout=120)
    except RuntimeError as exc:
        text = str(exc)
        if "progress" in text.lower() or "licen" in text.lower() or "failed" in text.lower():
            raise Skip("engine did not run here: %s" % text[:200])
        raise
    check(len(faces) >= 4, "too few faces: %d" % len(faces))
    after = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials))
    check(after == before, "left data behind: objects/meshes/materials %s -> %s" % (before, after))
    check(not [m for m in bpy.data.materials if m.name.startswith("_qr_")], "temporary materials leaked")


def test_quad_remesher_page_recipe_runs():
    """quad-remesher.md's worked call, run as written on half of a domed patch cut at its mirror line x = 0: one
    welded, mirrored mesh comes out, open only at the outer border."""
    if not os.path.exists(QR["find_engine"]()):
        raise Skip("Quad Remesher engine not installed")
    fresh()
    n = 12                                                     # 48 border points; square corners need the density
    bm = bmesh.new()
    vs = [[bm.verts.new((x / n, y / n - 0.5, 0.1 * math.cos(x / n * 1.5) * math.cos((y / n - 0.5) * 3)))
           for x in range(n + 1)] for y in range(n + 1)]
    for y in range(n):
        for x in range(n):
            bm.faces.new((vs[y][x], vs[y][x + 1], vs[y + 1][x + 1], vs[y + 1][x]))
    patch = object_from_bmesh("Patch", bm)
    page = (ROOT / "skills" / "blender-mesh-topology" / "references" / "quad-remesher.md").read_text(encoding="utf-8")
    block = next(b for b in re.findall(r"```python\n(.*?)```", page, re.S) if "patch_input" in b)
    block = block.replace("<skill>", str(ROOT / "skills" / "blender-mesh-topology").replace("\\", "/"))
    block = block.replace("target=400", "target=60")                    # a small patch
    ns = {"bpy": bpy, "bmesh": bmesh, "patch": patch}
    try:
        exec(block, ns)
    except RuntimeError as exc:
        text = str(exc)
        if "progress" in text.lower() or "licen" in text.lower() or "failed" in text.lower():
            raise Skip("engine did not run here: %s" % text[:200])
        raise
    ob = bpy.data.objects.new("Remeshed", ns["me"])
    bpy.context.scene.collection.objects.link(ob)
    r = AUDIT["audit"](ob)
    check(AUDIT["problems"](r, allow_open=True) == [] and r["islands"] == 1, "remeshed: %s, islands %d"
          % (AUDIT["problems"](r, allow_open=True), r["islands"]))
    xs = [v.co.x for v in ob.data.vertices]
    check(min(xs) < -0.99 and max(xs) > 0.99, "not mirrored: x %.2f..%.2f" % (min(xs), max(xs)))


def test_review_render_headless_wire_follows_modifiers():
    fresh()
    scene = bpy.context.scene
    scene.world = bpy.data.worlds.new("White")
    scene.world.color = (1.0, 1.0, 1.0)                           # a light background, so only wire is dark
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=2, y_segments=2, size=0.4)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(0.5, 0.0, 0.0))   # the half at x > 0
    ob = object_from_bmesh("Half", bm)
    ob.modifiers.new("mirror", "MIRROR")                          # the other half at x < 0
    keep = (scene.render.engine, scene.camera, scene.render.resolution_x, scene.render.filepath)
    n_obj = len(bpy.data.objects)
    path = str(TMP / "wire.png")
    # a long lens from far away makes the wire (0.12% of the distance thick) several pixels wide
    RR["render"](path, eye=(0, 0, 7), target=(0, 0, 0), lens=100, w=1200, h=600, light="FLAT", wire=True)
    check(os.path.exists(path), "no image written")
    check((scene.render.engine, scene.camera, scene.render.resolution_x, scene.render.filepath) == keep,
          "scene render settings not restored")
    check(len(bpy.data.objects) == n_obj, "temporary objects left behind")
    img = bpy.data.images.load(path)
    w, h = img.size
    px = list(img.pixels[:])
    dark = [0, 0]
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            if px[i] < 0.2 and px[i + 3] > 0.5:
                dark[0 if x < w // 2 else 1] += 1
    check(min(dark) > 50, "wire pixels left/right %s: the mirrored half has no wire" % dark)


def test_review_compare_frames_each_object_alone():
    """#12: compare() renders an offset copy from the same eye relative to its own centre, so an identical copy
    matches its original (one wide frame would shear it); a squashed copy does not. The sheet is before | after |
    silhouette, one row per view and wire value, and visibility comes back as it was."""
    fresh()
    scene = bpy.context.scene
    scene.world = bpy.data.worlds.new("White")
    scene.world.color = (1.0, 1.0, 1.0)
    src = cube("Dense")
    same = cube("Low")
    same.location = (3.0, 0.0, 0.0)                               # placed beside the source, as the issue's lows
    squashed = cube("Squashed")
    squashed.location, squashed.scale = (-3.0, 0.0, 0.0), (1.0, 1.0, 0.7)
    bystander = cube("Bystander")
    bystander.location = (0.0, 2.0, 0.0)                          # in the frame unless compare() hides it
    bystander.hide_set(False)
    kw = dict(views=[(2.0, -3.0, 1.5), ((0.0, -4.0, 0.0), (0.0, 0.0, 0.0))], lens=35, w=200, h=150, light="FLAT")
    out = str(TMP / "compare.png")
    res = RR["compare"]("Dense", "Low", out=out, **kw)
    check(os.path.exists(out), "no sheet written")
    img = bpy.data.images.load(out)
    check(tuple(img.size) == (600, 600), "sheet %s, expected 3 columns x 4 rows of 200x150" % (tuple(img.size),))
    check(len(res["mismatch"]) == 2 and max(res["mismatch"]) < 0.01, "identical copy mismatch %s" % res["mismatch"])
    bad = RR["compare"]("Dense", "Squashed", out=str(TMP / "compare_bad.png"), wire=(False,), **kw)
    check(min(bad["mismatch"]) > 0.05, "squashed copy mismatch %s" % bad["mismatch"])
    check(not any(o.hide_get() for o in (src, same, squashed, bystander)), "visibility not restored")
    check(len(bpy.data.objects) == 4, "temporary objects left behind")


def test_small_pieces_and_cards():
    """Props sweep: a 5 mm screw's 0.5 mm edges are not short for its size (2% of its smallest side over 1 mm), a
    50 cm piece's are; leaf cards with custom normals on planar quads and no hard-surface stack are not flagged,
    a bent quad is."""
    fresh()
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(0.005, 0.005, 0.0005), verts=bm.verts)              # a 5 x 5 x 0.5 mm head
    small = object_from_bmesh("Screw", bm)
    r = AUDIT["audit"](small)
    check(r["short_edges"] == 0 and r["short_edge_m"] == 0.0001, "small piece: %s %s" % (r["short_edges"],
                                                                                    r["short_edge_m"]))
    check(AUDIT["audit"](small, short_edge=0.001)["short_edges"] > 0, "an explicit 1 mm still counts them")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(0.5, 0.5, 0.0005), verts=bm.verts)                 # 0.5 mm thick, 50 cm wide
    check(AUDIT["audit"](object_from_bmesh("Board", bm))["short_edges"] > 0, "a 0.5 mm edge on a 50 cm piece")
    bm = bmesh.new()
    for x in (0.0, 1.5):                                                         # two cards, the second bent
        vs = [bm.verts.new(co) for co in ((x, 0, 0), (x + 1, 0, 0), (x + 1, 0, 1), (x, 0.3 if x else 0.0, 1))]
        bm.faces.new(vs)
    cards = object_from_bmesh("Cards", bm)
    cards.data.shade_smooth()
    bpy.ops.mesh.primitive_ico_sphere_add(radius=2.0, location=(1.25, 0.0, 0.5))     # the hull the normals come from
    hull = bpy.context.active_object
    dt = cards.modifiers.new("Normals", "DATA_TRANSFER")
    dt.object, dt.use_loop_data, dt.data_types_loops = hull, True, {"CUSTOM_NORMAL"}
    bpy.context.view_layer.update()
    s = AUDIT["audit_stack"](cards, allow_open=True)
    check(s["on"]["cn_quads"] == 2 and s["on"]["cn_quads_bent"] == 1 and "custom_normals_on_quads" in s["problems"],
          "cards: %s" % {k: s["on"][k] for k in ("cn_quads", "cn_quads_bent")})
    for v in cards.data.vertices:
        v.co.y = 0.0                                                             # flatten the bent card
    cards.data.update()
    bpy.context.view_layer.update()
    s = AUDIT["audit_stack"](cards, allow_open=True)
    check("custom_normals_on_quads" not in s["problems"], "planar cards flagged: %s" % s["problems"])


def test_review_render_culls_back_faces_like_the_engine():
    """A single-sided plate wound inside out (its normal away from the eye) passes every audit; the engine's stock
    shaders cull it. review_render culls by default, so it vanishes there too; cull=False draws it."""
    fresh()
    scene = bpy.context.scene
    scene.world = bpy.data.worlds.new("White")
    scene.world.color = (1.0, 1.0, 1.0)
    bm = bmesh.new()
    bm.faces.new([bm.verts.new(c) for c in ((-0.5, -0.5, 0), (-0.5, 0.5, 0), (0.5, 0.5, 0), (0.5, -0.5, 0))])
    ob = object_from_bmesh("inside_out", bm)                     # wound clockwise from above: normal -Z
    check(ob.data.polygons[0].normal.z < 0, "fixture should face down")

    def covered(**kw):
        path = str(TMP / ("cull_%s.png" % kw.get("cull", True)))
        RR["render"](path, eye=(0, 0, 3), target=(0, 0, 0), w=200, h=100, light="FLAT", **kw)
        return float(RR["_silhouette"](RR["_load"](path)).mean())     # pixels unlike the background corners
    shown, culled = covered(cull=False), covered()
    check(shown > 0.05 and culled < 0.001, "coverage drawn %.3f, culled %.3f" % (shown, culled))
    check(not scene.display.shading.show_backface_culling, "the scene's culling setting was not restored")

def test_high_low_gap_reads_the_sagitta_and_a_fat_low():
    """A 16-sided low cylinder against a 128-sided high of the same radius: the high stands out by the low's sagitta,
    r (1 - cos(pi / 16)) = 1.92 mm, and the low nowhere outside it; the high shrunk 2% (2 mm) puts the low 2 mm out."""
    fresh()
    ns = AUDIT
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.1, depth=0.3, end_fill_type="NGON")
    low = bpy.context.active_object
    bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=0.1, depth=0.3, end_fill_type="NGON")
    high = bpy.context.active_object
    r = ns["high_low_gap"](low, [high], samples=8000)
    sag = 0.1 * (1 - math.cos(math.pi / 16))
    check(abs(r["high_outside_max"] - sag) < 2e-4 and r["low_outside_max"] < 1e-4, (r, sag))
    high.scale = (0.98, 0.98, 1.0)
    bpy.context.view_layer.update()
    r = ns["high_low_gap"](low, [high], samples=8000)
    check(abs(r["low_outside_max"] - 0.002) < 2e-4 and r["high_outside_max"] < 1e-4, r)
    for ob in (low, high):                                      # a mirrored pair (negative scale) reads the same
        ob.scale.x = -ob.scale.x
    bpy.context.view_layer.update()
    m = ns["high_low_gap"](low, [high], samples=8000)
    check(abs(m["low_outside_max"] - r["low_outside_max"]) < 2e-4 and m["high_outside_max"] < 1e-4, (m, r))


def _grid_box(name, sx, sy, sz, step, lift=None):
    """A closed box x 0..sx, y 0..sy, z 0..sz, each side a grid of `step` quads; lift(x, y) raises top vertices."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(sx / 2, sy / 2, sz / 2), verts=bm.verts)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=int(round(max(sx, sy, sz) / step)) - 1, use_grid_fill=True)
    if lift:
        for v in bm.verts:
            if abs(v.co.z - sz) < 1e-6:
                v.co.z += lift(v.co.x, v.co.y)
    return object_from_bmesh(name, bm)


def _blocks(name, parts):
    """One object of closed boxes given as (size, centre)."""
    bm = bmesh.new()
    for size, centre in parts:
        geom = bmesh.ops.create_cube(bm, size=1.0)["verts"]
        bmesh.ops.scale(bm, vec=size, verts=geom)
        bmesh.ops.translate(bm, vec=centre, verts=geom)
    return object_from_bmesh(name, bm)


def test_high_low_gap_sees_a_small_bump_and_ignores_how_the_high_is_split():
    """A 2 x 1 x 1 m low with a 25 cm patch of its top raised 4 cm (0.6% of its area) against the flat high: the old
    p99 read 0 (a bump the player sees at 23 px from 2 m); low_outside_max reads 4 cm. A 3 cm boss on the high
    reads the same whether it is part of the body's object or its own, and nine rivets do not dilute a 2 cm panel."""
    fresh()
    ns = AUDIT

    def bump(x, y):
        d = max(abs(x - 1.0), abs(y - 0.5))
        return 0.04 if d <= 0.125 else 0.04 * max(0.0, 1 - (d - 0.125) / 0.05)
    low = _grid_box("low_bump", 2, 1, 1, 0.025, bump)
    high = _blocks("box_high", [((2, 1, 1), (1, 0.5, 0.5))])
    r = ns["high_low_gap"](low, [high], samples=8000)
    check(abs(r["low_outside_max"] - 0.04) < 1e-3 and r["low_outside_p99"] < 0.04, r)
    flat = _blocks("box_low", [((2, 1, 1), (1, 0.5, 0.5))])
    boss = ((0.3, 0.03, 0.2), (1.0, -0.015 + 1e-4, 0.5))
    merged = _blocks("merged_high", [((2, 1, 1), (1, 0.5, 0.5)), boss])
    body, own = _blocks("body_high", [((2, 1, 1), (1, 0.5, 0.5))]), _blocks("boss_high", [boss])
    a = ns["high_low_gap"](flat, [merged], samples=8000)
    b = ns["high_low_gap"](flat, [body, own], samples=8000)
    check(abs(a["high_outside_p99"] - b["high_outside_p99"]) < 2e-3 and abs(a["high_outside_max"] - 0.03) < 1e-3, (a, b))
    panel = _blocks("panel_high", [((2, 1, 1), (1, 0.5, 0.5)), ((0.55, 0.55, 0.02), (1.0, 0.5, 1.01 - 1e-4))])
    rivets = [_blocks("rivet_high_%d" % i, [((0.02, 0.02, 0.003), (0.2 + 0.2 * i, 0.1, 1.0015 - 1e-5))])
              for i in range(9)]
    c = ns["high_low_gap"](flat, [panel], samples=8000)
    d = ns["high_low_gap"](flat, [panel] + rivets, samples=8000)
    check(abs(c["high_outside_p99"] - 0.02) < 1e-3 and abs(d["high_outside_p99"] - 0.02) < 1e-3, (c, d))
    # a correct low over a high with a panel line: a 3 mm groove 1.5 mm deep in the top is a recess the bake carries,
    # not a bulge of the low (it read as one, failing a crate lid with more panel lines)
    grooved = _blocks("grooved_high", [((2, 1, 0.9985), (1, 0.5, 0.49925)),
                                       ((0.9985, 1, 0.0015), (0.49925, 0.5, 0.99925)),
                                       ((0.9985, 1, 0.0015), (1.50075, 0.5, 0.99925))])
    g = ns["high_low_gap"](flat, [grooved], samples=60000)           # enough to land in a 3 mm groove
    check(g["low_outside_max"] < 2e-4 and 0.0008 < g["recess_max"] <= 0.0015 + 1e-5,    # samples near the walls
          "a groove is a recess, not a bulge: %s" % g)                                     # read under its 1.5 mm
    r = ns["high_low_gap"](low, [high], samples=8000)
    check(abs(r["low_outside_max"] - 0.04) < 1e-3, "the bump is still a bulge: %s" % r)
    try:
        ns["high_low_gap"](flat, [object_from_bmesh("faceless", bmesh.new())])
        raise AssertionError("a high with no faces must be refused")
    except ValueError:
        pass

def test_bake_skew_falls_with_a_bevel():
    """A hard box's averaged normals lean up to 54.7 deg off its faces (most of its area over 15 deg); a 5 cm bevel
    of three segments on a 1 m box brings that under 5%; a 16-sided cylinder leans at most half its facet angle."""
    fresh()
    ns = AUDIT
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    box = bpy.context.active_object
    r = ns["bake_skew"](box)
    check(r["over_share"] > 0.9 and abs(r["p95_deg"] - 54.74) < 0.1 and r["worst"] and r["shift_m"] is None, r)
    r = ns["bake_skew"](box, relief_m=0.0007)                  # props sweep: 0.7 mm of relief moves ~1 mm here
    check(abs(r["shift_m"] - 0.0007 * math.tan(math.radians(r["p95_deg"]))) < 1e-6, r)
    bev = box.modifiers.new("Bevel", "BEVEL")
    bev.width, bev.segments = 0.05, 3
    r = ns["bake_skew"](box)
    check(r["over_share"] < 0.05, r)
    box.scale.x = -1.0                                          # mirrored: the winding is reversed, same skew
    bpy.context.view_layer.update()
    m = ns["bake_skew"](box)
    check(abs(m["over_share"] - r["over_share"]) < 1e-4 and abs(m["p95_deg"] - r["p95_deg"]) < 0.01, (m, r))
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.1, depth=0.3, end_fill_type="NOTHING")
    r = ns["bake_skew"](bpy.context.active_object)
    check(r["over_share"] == 0.0 and abs(r["p95_deg"] - 11.25) < 0.05, r)
    # an 8-sided handle built to the chord rule: against its own faces its rays lean 22.5 deg, but they leave it
    # radially onto a round high, so against the high it is clean; a hard box still skews onto a box high
    bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=0.1, depth=0.3, end_fill_type="NOTHING")
    handle = bpy.context.active_object
    handle.data.shade_smooth()
    bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=0.1, depth=0.3, end_fill_type="NOTHING")
    round_high = bpy.context.active_object
    own, onto = ns["bake_skew"](handle), ns["bake_skew"](handle, highs=[round_high])
    check(own["over_share"] > 0.3 and onto["over_share"] < 0.05 and onto["against"] == "high", (own, onto))
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(5, 0, 0))
    hard = bpy.context.active_object
    bpy.ops.mesh.primitive_cube_add(size=1.002, location=(5, 0, 0))
    box_high = bpy.context.active_object
    check(ns["bake_skew"](hard, highs=[box_high])["over_share"] > 0.5, "a hard box still skews onto a box high")
    top = [p.index for p in hard.data.polygons if p.normal.z > 0.9]
    part = ns["bake_skew"](hard, faces=top)
    check(0.5 < part["over_share"] <= 1.0, "the faces mask judges the top face alone: %s" % part)


def test_high_poly_routes_run_headless():
    """What references/high-and-low-poly.md calls verified on 5.2.2 under blender -b: the crease_edge attribute drives
    a Subdivision Surface, voxel remesh (operator and modifier), Multires subdivision, QuadriFlow on a closed mesh,
    Decimate, and a cloth simulation stepped frame by frame and applied; sculpt brush strokes need a 3D viewport and
    refuse to run headless (the headless sculpt is modifiers: Displace on Multires or a subdivided mesh)."""
    fresh()
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    ob = bpy.context.active_object
    sub = ob.modifiers.new("Sub", "SUBSURF")
    sub.levels = 3

    def half_width():
        ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
        me = ev.to_mesh()
        w = max(abs(v.co.x) for v in me.vertices if abs(v.co.z) < 1e-4)
        ev.to_mesh_clear()
        return w
    soft = half_width()
    att = ob.data.attributes.new("crease_edge", "FLOAT", "EDGE")
    att.data.foreach_set("value", [1.0] * len(ob.data.edges))
    ob.data.update()
    check(soft < 0.43 and abs(half_width() - 0.5) < 1e-4, "crease_edge 1 keeps the subdivided corners square")
    fresh()
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    ob = bpy.context.active_object
    ob.data.remesh_voxel_size = 0.05
    check(bpy.ops.object.voxel_remesh() == {"FINISHED"} and len(ob.data.polygons) > 2000, "voxel remesh headless")
    mr = ob.modifiers.new("Multires", "MULTIRES")
    check(bpy.ops.object.multires_subdivide(modifier="Multires", mode="CATMULL_CLARK") == {"FINISHED"}
          and mr.total_levels == 1, "multires subdivide headless")
    try:
        bpy.ops.object.mode_set(mode="SCULPT")
        bpy.ops.sculpt.brush_stroke(stroke=[{"name": "s", "location": (0, 0, 0.5), "mouse": (0, 0),
                                             "mouse_event": (0, 0), "pen_flip": False, "is_start": True,
                                             "pressure": 1.0, "size": 50, "time": 0, "x_tilt": 0, "y_tilt": 0}])
        stroked = True
    except RuntimeError:
        stroked = False
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    check(not stroked, "a sculpt brush stroke ran headless: references/high-and-low-poly.md says it cannot")
    fresh()
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=4)
    ob = bpy.context.active_object
    check(bpy.ops.object.quadriflow_remesh(target_faces=400, seed=0) == {"FINISHED"}
          and all(len(p.vertices) == 4 for p in ob.data.polygons) and 300 < len(ob.data.polygons) < 500,
          "QuadriFlow on a closed mesh")
    dec = ob.modifiers.new("D", "DECIMATE")
    dec.ratio = 0.25
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    check(len(ev.data.polygons) < 0.6 * len(ob.data.polygons), "Decimate collapse")
    fresh()
    bpy.ops.mesh.primitive_plane_add(size=2, location=(0, 0, 1.0))
    cloth = bpy.context.active_object
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.subdivide(number_cuts=20)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.4))
    bpy.context.active_object.modifiers.new("Collision", "COLLISION")
    cm = cloth.modifiers.new("Cloth", "CLOTH")
    cm.point_cache.frame_end = 40
    for f in range(1, 41):
        bpy.context.scene.frame_set(f)
    bpy.context.view_layer.objects.active = cloth
    check(bpy.ops.object.modifier_apply(modifier="Cloth") == {"FINISHED"}, "cloth applied at the last frame")
    zmin = min((cloth.matrix_world @ v.co).z for v in cloth.data.vertices)
    check(zmin < 0.8, "the cloth should drape below the table top (0.9): lowest %.3f" % zmin)


def test_joint_normals_finds_the_crease_where_a_curve_meets_a_straight():
    """A straight wall front meeting a quarter-circle wall of 16 segments, both smooth: the curve's end vertices lean
    half a facet angle (2.81 deg) off the straight's normal; custom normals on them set to the straight's (-Y) put
    the shading right (0 deg)."""
    fresh()
    ns = AUDIT
    bm = bmesh.new()
    vs = [bm.verts.new(c) for c in ((-1, 0, 0), (0, 0, 0), (0, 0, 3), (-1, 0, 3))]
    bm.faces.new(vs)
    straight = object_from_bmesh("straight", bm)
    bm = bmesh.new()
    cols = []
    for i in range(17):
        a = (math.pi / 2) * i / 16
        cols.append((bm.verts.new((math.sin(a), 1 - math.cos(a), 0)), bm.verts.new((math.sin(a), 1 - math.cos(a), 3))))
    for (a0, a1), (b0, b1) in zip(cols, cols[1:]):
        bm.faces.new((a0, b0, b1, a1))
    curved = object_from_bmesh("curved", bm)
    for ob in (straight, curved):
        ob.data.shade_smooth()
    at_joint = lambda co: abs(co.x) < 1e-4 and abs(co.y) < 1e-4
    r = ns["joint_normals"](straight, curved, at_joint)
    check(r["positions"] == 2 and abs(r["max_deg"] - 90.0 / 16 / 2) < 0.01, r)
    vn = [tuple(v.normal) for v in curved.data.vertices]
    for v in curved.data.vertices:
        if at_joint(v.co):
            vn[v.index] = (0.0, -1.0, 0.0)
    curved.data.normals_split_custom_set_from_vertices(vn)
    r = ns["joint_normals"](straight, curved, at_joint)
    check(r["max_deg"] < 0.01, r)



def test_joint_normals_on_closed_pieces_skips_the_caps_and_sees_the_front():
    """Closed pieces: a straight slab and a 16-segment quarter-circle wall, 0.2 m thick, folds sharp by angle. At each
    joint corner the bottom and top match exactly and the end caps face each other; only the front and back lean
    (half a facet angle). Taking the best pair per position would report 0 deg; each corner matched to its own face,
    caps left out, gives 2.81 deg both ways round."""
    fresh()
    ns = AUDIT
    bpy.ops.mesh.primitive_cube_add(size=1)
    straight = bpy.context.active_object
    straight.scale = (1.0, 0.2, 3.0)
    straight.location = (-0.5, 0.1, 1.5)
    bpy.ops.object.transform_apply(location=True, scale=True)
    bm = bmesh.new()
    cols = []
    for i in range(17):
        a = (math.pi / 2) * i / 16
        ring = []
        for r in (1.0, 0.8):                                    # front (radius 1), back (0.8): both centred on (0, 1)
            for z in (0.0, 3.0):
                ring.append(bm.verts.new((r * math.sin(a), 1 - r * math.cos(a), z)))
        cols.append(ring)                                       # front bottom, front top, back bottom, back top
    for p, q in zip(cols, cols[1:]):
        bm.faces.new((p[0], q[0], q[1], p[1]))                  # front
        bm.faces.new((p[2], p[3], q[3], q[2]))                  # back
        bm.faces.new((p[0], p[2], q[2], q[0]))                  # bottom
        bm.faces.new((p[1], q[1], q[3], p[3]))                  # top
    bm.faces.new((cols[0][0], cols[0][1], cols[0][3], cols[0][2]))
    bm.faces.new((cols[-1][0], cols[-1][2], cols[-1][3], cols[-1][1]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    curved = object_from_bmesh("curved_closed", bm)
    for ob in (straight, curved):
        ob.data.set_sharp_from_angle(angle=math.radians(30))
        ob.data.shade_smooth()
    at_joint = lambda co: abs(co.x) < 1e-4
    for pair in ((straight, curved), (curved, straight)):
        r = ns["joint_normals"](*pair, at_joint)
        check(r["positions"] == 4 and abs(r["max_deg"] - 90.0 / 16 / 2) < 0.01, r)


def test_joint_normals_counts_creases_of_any_angle():
    """Two flat plates meeting along a 60 deg bend read 60 (a skip by angle read 0); a box shaded smooth across its
    folds against a hard-shaded one reads 54.7 at the joint; two hard boxes read 0."""
    fresh()
    ns = AUDIT
    bm = bmesh.new()
    bm.faces.new([bm.verts.new(c) for c in ((-1, 0, 0), (0, 0, 0), (0, 1, 0), (-1, 1, 0))])
    a = object_from_bmesh("plate_a", bm)
    bm = bmesh.new()
    c, s = math.cos(math.radians(60)), math.sin(math.radians(60))
    bm.faces.new([bm.verts.new(p) for p in ((0, 0, 0), (c, 0, s), (c, 1, s), (0, 1, 0))])
    b = object_from_bmesh("plate_b", bm)
    at_joint = lambda co: abs(co.x) < 1e-4 and abs(co.z) < 1e-4
    r = ns["joint_normals"](a, b, at_joint)
    check(r["positions"] == 2 and abs(r["max_deg"] - 60.0) < 0.01, r)
    hard = _blocks("hard_beam", [((1, 0.2, 0.2), (-0.5, 0.1, 0.1))])
    soft = _blocks("soft_beam", [((1, 0.2, 0.2), (0.5, 0.1, 0.1))])
    hard.data.set_sharp_from_angle(angle=math.radians(30))
    hard.data.shade_smooth()
    soft.data.shade_smooth()
    at_end = lambda co: abs(co.x) < 1e-4
    r = ns["joint_normals"](hard, soft, at_end)
    check(r["positions"] == 4 and abs(r["max_deg"] - 54.74) < 0.05, r)
    soft.data.set_sharp_from_angle(angle=math.radians(30))
    r = ns["joint_normals"](hard, soft, at_end)
    check(r["max_deg"] < 0.01, r)

for fn in (test_audit_applies_modifiers, test_slivers_counted_on_flat_faces,
           test_reduction_bands_audit_clean_with_the_documented_poles, test_flipped_faces_are_a_problem,
           test_inverted_islands_on_small_shells_far_from_the_origin, test_second_band_on_a_ring_needs_its_runs_reversed,
           test_poles_count_irregular_vertices_next_to_triangles,
           test_big_faces_flat_check_and_the_fold_rule_per_route, test_flat_check_passes_wide_single_segment_chamfers,
           test_smooth_by_angle_function_touches_only_its_piece, test_audit_stack_judges_a_stack_triangulated_piece,
           test_audit_stack_without_a_live_triangulate, test_audit_stack_route_follows_the_enabled_modifiers,
           test_audit_stack_names_a_late_smooth_by_angle_and_flat_shading,
           test_normals_snapshot_catches_uv_work_that_loses_the_normals,
           test_uv_work_keeps_a_trailing_mirror_live_and_applies_one_above_a_bevel,
           test_flat_faces_list_curved_parts_by_mesh_face, test_flat_floor_follows_the_live_bevel,
           test_flat_faces_list_each_mesh_face_once, test_smooth_by_angle_function_placement_and_edit_mode,
           test_hand_off_refusals_and_topology_types, test_scale_goes_before_the_stack_or_after_the_hand_off,
           test_point_cache_weld_points_at_survivors,
           test_flat_fill_returns_live_faces_covering_the_region, test_weld_layout_and_mirror_half,
           test_patch_input_walks_the_border, test_quad_remesh_engine_round_trip, test_quad_remesher_page_recipe_runs,
           test_review_render_headless_wire_follows_modifiers, test_review_compare_frames_each_object_alone,
           test_high_low_gap_reads_the_sagitta_and_a_fat_low, test_bake_skew_falls_with_a_bevel,
           test_high_poly_routes_run_headless, test_joint_normals_finds_the_crease_where_a_curve_meets_a_straight,
           test_joint_normals_on_closed_pieces_skips_the_caps_and_sees_the_front,
           test_high_low_gap_sees_a_small_bump_and_ignores_how_the_high_is_split,
           test_joint_normals_counts_creases_of_any_angle, test_review_render_culls_back_faces_like_the_engine,
           test_small_pieces_and_cards):
    case(fn)
failed = [r for r in RESULTS if r[0] == "FAIL"]
if not failed:
    shutil.rmtree(TMP, ignore_errors=True)                     # keep the fixtures only when a case failed
print("%d passed, %d skipped, %d failed%s" % (sum(r[0] == "PASS" for r in RESULTS),
                                              sum(r[0] == "SKIP" for r in RESULTS), len(failed),
                                              " (fixtures kept in %s)" % TMP if failed else ""))
if failed:
    raise SystemExit("FAILED: " + ", ".join(r[1] for r in failed))
