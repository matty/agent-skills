"""Repo-level cross-skill test: blender-mesh-topology's hard-surface hand-off (scripts/hard_surface.py:
apply_for_uv_work, then apply_before_layout) and uv-unwrapping's (scripts/uv_audit.py: apply_stack, then
apply_stack(keep_mirror=False)) must behave identically. Each stack is built twice side by side; one copy goes
through each skill's functions. Asserted per stack: both refuse (ValueError, nothing changed) or neither does, and
the results match: the same modifiers left (type, viewport toggle), the same mesh data, and the same corner normals
with the Triangulate back on (positions and normals within 1e-4).

Stacks: the 7 standard ones (route B, route A, Smooth by Angle first on each, a Mirror first on a half ridge, a
Mirror below the Bevel on route B, and Smooth by Angle > Bevel > Mirror on route A), plus a Mirror first on a half
panel, a Mirror appended at the bottom, an Array appended, a Mirror switched off in the viewport, a Decimate and a
Weld above the Triangulate, shape keys, and a mesh shared with another object.

Repo tooling, not a skill file: it loads both skills' scripts by path.
Host: Blender 5.2.2 (bpy, bmesh), headless:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_cross_hardsurface_handoff.py
Prints PASS <stack> / FAIL <stack>: <why>, and raises if any stack failed.
"""

import importlib.util
import math
import sys
import traceback
from pathlib import Path

import bmesh
import bpy
from mathutils.kdtree import KDTree

ROOT = Path(__file__).resolve().parents[3]
HS_PATH = ROOT / "skills" / "blender-mesh-topology" / "scripts" / "hard_surface.py"
UA_PATH = ROOT / "skills" / "uv-unwrapping" / "scripts" / "uv_audit.py"
TOL = 1e-4
RESULTS = []


def load_hs():
    ns = {}
    exec(compile(HS_PATH.read_text(encoding="utf-8"), str(HS_PATH), "exec"), ns)
    return ns


def load_ua():
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True                      # never leave a __pycache__ in a skill
    try:
        spec = importlib.util.spec_from_file_location("uv_audit_cross", UA_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = keep


HS, UA = load_hs(), load_ua()


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ----------------------------------------------------------------------------------------------- fixtures
def obj(name, bm):
    for f in bm.faces:
        f.smooth = True
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def panel(name, half=False):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(1.0, 0.08, 2.0), verts=bm.verts)
    if half:
        bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, 0, 0),
                               plane_no=(1, 0, 0), clear_inner=True)
    return obj(name, bm)


def half_ridge(name):
    h = 0.5 * math.tan(math.radians(13.0 / 2))
    bm = bmesh.new()
    f = [bm.verts.new(c) for c in ((0, -h, 0), (0.5, 0, 0), (0.5, 0, 2), (0, -h, 2))]
    b = [bm.verts.new(c) for c in ((0, 0.1, 0), (0.5, 0.1, 0), (0.5, 0.1, 2), (0, 0.1, 2))]
    for vs in ([f[0], f[1], f[2], f[3]], [b[0], b[3], b[2], b[1]], [f[1], b[1], b[2], f[2]], [f[0], b[0], b[1], f[1]],
               [f[3], f[2], b[2], b[3]]):
        bm.faces.new(vs)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return obj(name, bm)


def move(ob, name, index):
    with bpy.context.temp_override(object=ob, active_object=ob):
        bpy.ops.object.modifier_move_to_index(modifier=name, index=index)


def stack(ob, route, angle_limit=None):
    bev = ob.modifiers.new("Bevel", "BEVEL")
    bev.limit_method, bev.width, bev.segments = "ANGLE", 0.01, 2
    if angle_limit is not None:
        bev.angle_limit = math.radians(angle_limit)
    if route == "A":
        bev.harden_normals = True
    else:
        bev.face_strength_mode = "FSTR_AFFECTED"
    tri = ob.modifiers.new("Triangulate", "TRIANGULATE")
    tri.min_vertices, tri.keep_custom_normals = 4, True
    if route == "B":
        wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
        wn.mode, wn.keep_sharp, wn.use_face_influence = "FACE_AREA", True, True
    return ob


def mirror(ob, index=None):
    m = ob.modifiers.new("Mirror", "MIRROR")
    m.use_clip = True
    if index is not None:
        move(ob, m.name, index)
    return m


def build(kind, name):
    sba = HS["smooth_by_angle_first"]
    if kind == "route B":
        return stack(panel(name), "B")
    if kind == "route A":
        return stack(panel(name), "A")
    if kind == "Smooth by Angle > route B":
        ob = stack(panel(name), "B")
        sba(ob, 10)
        return ob
    if kind == "Smooth by Angle > route A":
        ob = stack(panel(name), "A")
        sba(ob, 10)
        return ob
    if kind == "Mirror first > route B (half ridge)":
        ob = half_ridge(name)
        mirror(ob)
        return stack(ob, "B", angle_limit=10)
    if kind == "Bevel > Mirror > Tri > WN":
        ob = stack(panel(name, half=True), "B", angle_limit=10)
        mirror(ob, 1)
        return ob
    if kind == "Smooth by Angle > Bevel > Mirror > Tri (A)":
        ob = stack(panel(name, half=True), "A")
        mirror(ob, 1)
        sba(ob, 10)
        return ob
    if kind == "Mirror first > route B (half panel)":
        ob = panel(name, half=True)
        mirror(ob)
        return stack(ob, "B")
    if kind == "Mirror appended":
        ob = stack(panel(name, half=True), "B")
        mirror(ob)
        return ob
    if kind == "Array appended":
        ob = stack(panel(name), "B")
        ob.modifiers.new("Array", "ARRAY").count = 2
        return ob
    if kind == "Mirror off in the viewport":
        ob = panel(name, half=True)
        mirror(ob).show_viewport = False
        return stack(ob, "B")
    if kind in ("Decimate above the Triangulate", "Weld above the Triangulate"):
        ob = stack(panel(name), "B")
        m = ob.modifiers.new(kind.split()[0], kind.split()[0].upper())
        if m.type == "DECIMATE":
            m.ratio = 0.6
        move(ob, m.name, 1)
        return ob
    if kind == "shape keys":
        ob = stack(panel(name), "A")
        ob.shape_key_add(name="Basis")
        return ob
    if kind == "shared mesh":
        ob = stack(panel(name), "A")
        bpy.context.scene.collection.objects.link(bpy.data.objects.new(name + "_twin", ob.data))
        return ob
    raise KeyError(kind)


KINDS = ["route B", "route A", "Smooth by Angle > route B", "Smooth by Angle > route A",
         "Mirror first > route B (half ridge)", "Bevel > Mirror > Tri > WN",
         "Smooth by Angle > Bevel > Mirror > Tri (A)",
         "Mirror first > route B (half panel)", "Mirror appended", "Array appended", "Mirror off in the viewport",
         "Decimate above the Triangulate", "Weld above the Triangulate", "shape keys", "shared mesh"]


# ----------------------------------------------------------------------------------------------- comparison
def topology_side(ob):
    HS["apply_for_uv_work"](ob)
    HS["apply_before_layout"](ob)


def uv_side(ob):
    UA.apply_stack(ob)
    UA.apply_stack(ob, keep_mirror=False)


def run(fn, ob):
    before = [(m.type, m.name, m.show_viewport) for m in ob.modifiers], len(ob.data.polygons)
    try:
        fn(ob)
    except ValueError as exc:
        after = [(m.type, m.name, m.show_viewport) for m in ob.modifiers], len(ob.data.polygons)
        check(after == before, "%s refused but changed the piece: %s -> %s" % (ob.name, before, after))
        return str(exc)
    return None


def corners(ob):
    """[(position, normal)] of the evaluated mesh with every Triangulate on, in object space."""
    for m in ob.modifiers:
        if m.type == "TRIANGULATE":
            m.show_viewport = True
    bpy.context.view_layer.update()
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    try:
        cn = me.corner_normals
        return [(me.vertices[lp.vertex_index].co.copy(), cn[i].vector.copy()) for i, lp in enumerate(me.loops)]
    finally:
        ev.to_mesh_clear()


def worst_mismatch(a, b):
    """Largest distance from a point of a to the nearest point of b, and from a normal to the nearest normal at that
    point (both ways)."""
    worst_pos, worst_nor = 0.0, 0.0
    for x, y in ((a, b), (b, a)):
        kd = KDTree(len(y))
        for i, (co, _) in enumerate(y):
            kd.insert(co, i)
        kd.balance()
        for co, n in x:
            near = kd.find_range(co, TOL)
            if not near:
                worst_pos = max(worst_pos, kd.find(co)[2])
                continue
            worst_nor = max(worst_nor, min((n - y[i][1]).length for _, i, _ in near))
    return worst_pos, worst_nor


def compare(kind):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    a, b = build(kind, "Topology"), build(kind, "UV")
    b.location.x = 5.0                                    # side by side; comparisons are in object space
    bpy.context.view_layer.update()
    ra, rb = run(topology_side, a), run(uv_side, b)
    check((ra is None) == (rb is None), "one refused, the other did not:\n  topology: %s\n  uv: %s" % (ra, rb))
    if ra is not None:
        return "both refused (topology: %s | uv: %s)" % (ra.splitlines()[0][:90], rb.splitlines()[0][:90])
    sa = [(m.type, m.show_viewport) for m in a.modifiers]
    sb = [(m.type, m.show_viewport) for m in b.modifiers]
    check(sa == sb, "stacks differ: topology %s, uv %s" % (sa, sb))
    check(len(a.data.vertices) == len(b.data.vertices) and len(a.data.polygons) == len(b.data.polygons),
          "mesh data differs: %d/%d verts, %d/%d faces" % (len(a.data.vertices), len(b.data.vertices),
                                                          len(a.data.polygons), len(b.data.polygons)))
    pos, nor = worst_mismatch(corners(a), corners(b))
    check(pos <= TOL and nor <= TOL, "results differ: positions %.2g, normals %.2g" % (pos, nor))
    return "identical: stack %s, %d faces" % ([t for t, _ in sa], len(a.data.polygons))


for kind in KINDS:
    try:
        RESULTS.append(("PASS", kind))
        print("PASS %s: %s" % (kind, compare(kind)))
    except Exception as exc:  # noqa: BLE001
        RESULTS[-1] = ("FAIL", kind)
        print("FAIL %s: %s" % (kind, exc))
        traceback.print_exc()
failed = [r for r in RESULTS if r[0] == "FAIL"]
print("%d passed, %d failed" % (len(RESULTS) - len(failed), len(failed)))
if failed:
    raise SystemExit("FAILED: " + ", ".join(r[1] for r in failed))
