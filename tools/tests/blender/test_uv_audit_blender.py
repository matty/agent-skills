"""Blender-hosted tests for the uv-unwrapping skill's scripts/uv_audit.py: what real bpy does with pack, stacks,
density, the layout call, the active UV layer, modifiers and Edit Mode.

Host: Blender 5.2.2 (4.1+), headless. Builds its fixtures in memory (temp files only for the CLI case), prints
PASS <case> / FAIL <case>: <why> per case and raises when any case failed:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_uv_audit_blender.py
"""

import importlib.util
import math
import os
import sys
import tempfile
import traceback
from pathlib import Path

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "skills" / "uv-unwrapping" / "scripts" / "uv_audit.py"


def load():
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True            # never leave a __pycache__ in the skill
    try:
        spec = importlib.util.spec_from_file_location("uv_audit_under_test", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = keep


ua = load()


# ----------------------------------------------------------------------------------------------- fixtures
def reset():
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for me in list(bpy.data.meshes):
        bpy.data.meshes.remove(me)


def quad(x0, y0, x1, y1, z=0.0):
    return [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]


def sq(u0, v0, du, dv=None):
    dv = du if dv is None else dv
    return [(u0, v0), (u0 + du, v0), (u0 + du, v0 + dv), (u0, v0 + dv)]


def make(name, quads3d, uvs, layers=("UVMap",), low=None):
    """One object of separate quads (one island each unless their UVs say otherwise)."""
    verts, faces = [], []
    for q in quads3d:
        faces.append(list(range(len(verts), len(verts) + 4)))
        verts += q
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    flat = [c for f in uvs for p in f for c in p]
    for ln in layers:
        lay = me.uv_layers.new(name=ln)
        lay.uv.foreach_set("vector", flat)
    if low is not None:
        at = me.attributes.new(ua.LOW_DENSITY_ATTR, "BOOLEAN", "FACE")
        at.data.foreach_set("value", [bool(x) for x in low])
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    me.uv_layers.active_index = 0
    return ob


def face_uvs(ob, layer=0):
    me = ob.data
    lay = me.uv_layers[layer]
    uv = np.empty(len(me.loops) * 2)
    lay.uv.foreach_get("vector", uv)
    uv = uv.reshape(-1, 2)
    return [uv[p.loop_start:p.loop_start + p.loop_total] for p in me.polygons]


def check(cond, why):
    if not cond:
        raise AssertionError(why)


# ----------------------------------------------------------------------------------------------- cases
def boards():
    """Five boards with the grain along U and five with it along V (each board's first UV edge runs along its
    length): the layout where Blender 5.2.2's CARDINAL packing turned the U boards by 90 deg."""
    q3, uvs = [], []
    for i in range(5):
        q3.append(quad(0, 3 * i, 1.0, 3 * i + 0.1))
        uvs.append([(0, 0.05 * i), (0.5, 0.05 * i), (0.5, 0.05 * i + 0.05), (0, 0.05 * i + 0.05)])
    for i in range(5):
        q3.append(quad(10 + 3 * i, 0, 10 + 3 * i + 1.0, 0.1))
        u = 0.6 + 0.05 * i
        uvs.append([(u, 0), (u, 0.5), (u - 0.05, 0.5), (u - 0.05, 0)])
    return q3, uvs


def directions(ob):
    return [round(math.degrees(math.atan2(*(f[1] - f[0])[::-1]))) for f in face_uvs(ob)]


def pack_rotation_off_keeps_grain():
    """rotate=False keeps every island's direction; CARDINAL and AXIS_ALIGNED turn grain (reported as INFO)."""
    q3, uvs = boards()
    ob = make("BOARDS", q3, uvs)
    before = directions(ob)
    ua.pack([ob], map_px=1024, rotate=False)
    after = directions(ob)
    check(after == before, "rotate=False turned islands: %s -> %s" % (before, after))
    for method in ("CARDINAL", "AXIS_ALIGNED"):
        reset()
        ob = make("BOARDS", q3, uvs)
        ua.pack([ob], map_px=1024, rotate=True, rotate_method=method)
        turned = sum(a != b for a, b in zip(before, directions(ob)))
        print("INFO pack_rotation_off_keeps_grain: %s turned %d of %d boards" % (method, turned, len(before)))


def keep_stacks_keeps_stacks():
    q3 = [quad(2 * i, 0, 2 * i + 0.5, 0.5) for i in range(5)]
    uvs = [sq(0.1, 0.1, 0.2)] * 3 + [sq(0.5, 0.5, 0.2), sq(0.75, 0.1, 0.1)]
    ob = make("STACK", q3, uvs)
    ua.pack([ob], map_px=1024, keep_stacks=True)
    f = face_uvs(ob)
    diff = max(float(np.abs(f[i] - f[0]).max()) for i in (1, 2))
    check(diff < 1e-5, "keep_stacks=True separated the stack (max diff %.4f)" % diff)
    reset()
    ob = make("STACK", q3, uvs)
    ua.pack([ob], map_px=1024, keep_stacks=False)
    f = face_uvs(ob)
    diff = min(float(np.abs(f[i] - f[0]).max()) for i in (1, 2))
    check(diff > 0.01, "keep_stacks=False kept the stack: Blender's behaviour changed (max diff %.4f)" % diff)


def scale_false_keeps_density():
    q3 = [quad(2 * i, 0, 2 * i + 1, 1) for i in range(3)]
    ob = make("DENSITY", q3, [sq(0.05, 0.05, 0.1), sq(0.3, 0.05, 0.2), sq(0.6, 0.05, 0.3)])
    ua.set_texel_density([ob], px_per_m=256, map_px=1024)    # density, then pack(scale=False)
    r = ua.audit(ob, layer=0, map_px=1024, px_per_m=256)
    check(abs(r["texel_px_per_m"] / 256 - 1) < 0.01, "density %.1f px/m after the pack" % r["texel_px_per_m"])
    check(r["texel_cv"] < 0.01 and not r["issues"], "issues: %s" % r["issues"])


def layout_end_to_end():
    """Stack (two copies and a mirrored one), two unique parts, a hidden part lowered and marked: one layout call."""
    q3 = [quad(0, 0, 0.5, 0.5), quad(1, 0, 1.5, 0.5), quad(2, 0, 2.5, 0.5),       # the stack
          quad(3, 0, 4, 0.5), quad(5, 0, 5.5, 0.25),                               # unique
          quad(6, 0, 6.5, 0.5)]                                                    # hidden, lowered
    s = sq(0.1, 0.1, 0.2)
    mirrored = [s[1], s[0], s[3], s[2]]                       # same square, U flipped
    uvs = [s, s, mirrored, sq(0.4, 0.1, 0.4, 0.2), sq(0.4, 0.5, 0.2, 0.1), sq(0.7, 0.7, 0.1)]
    ob = make("LAYOUT", q3, uvs, low=[0, 0, 0, 0, 0, 1])
    res = ua.layout([ob], map_px=1024, px_per_m=256, bake=True)[ob.name]
    check(res["fits"], "does not fit: %s" % res)
    check(res["stacks"] == 1 and res["copies_moved"] == 2, "stacks/copies: %s" % res)
    f = face_uvs(ob)
    home = [i for i in range(3) if f[i][:, 0].max() <= 1.0]
    check(len(home) == 1, "expected one stack copy inside 0-1, got %s" % home)
    check(np.linalg.det(np.c_[f[home[0]][1] - f[home[0]][0], f[home[0]][3] - f[home[0]][0]]) > 0,
          "the copy kept inside 0-1 is the mirrored one")
    for i in range(3):
        if i != home[0]:
            lo_i, lo_h = f[i].min(0), f[home[0]].min(0)
            check(np.allclose(lo_i - lo_h, (1.0, 0.0), atol=1e-5), "copy %d is not exactly +1 U" % i)
    r = ua.audit(ob, layer=0, map_px=1024, px_per_m=256)
    check(not r["issues"], "audit after layout: %s" % r["issues"])
    check(abs(r["low_density_px_per_m"] / 128 - 1) < 0.05, "marked island at %s px/m, expected about 128 (half)"
          % r["low_density_px_per_m"])


def layout_atlas_together():
    """Two objects sharing one atlas, 18 islands each, overlapping at the start: one layout call, no overlaps."""
    obs = []
    for k in range(2):
        widths = [0.3 + 0.05 * (i % 4) for i in range(18)]
        q3 = [quad(3 * i, 3 * k, 3 * i + wd, 3 * k + 0.2) for i, wd in enumerate(widths)]
        obs.append(make("ATLAS_%d" % k, q3, [sq(0.1 + 0.01 * i, 0.1, 0.5 * wd, 0.1) for i, wd in enumerate(widths)]))
    res = ua.layout(obs, map_px=1024, together=True)
    check(all(r["fits"] for r in res.values()), "does not fit: %s" % res)
    sh = ua.audit_shared(obs, layer=0, map_px=1024)
    check(not sh["issues"], "shared audit: %s" % sh["issues"])
    for ob in obs:
        r = ua.audit(ob, layer=0, map_px=1024)
        check(not r["issues"], "%s: %s" % (ob.name, r["issues"]))


def off_tile_island_is_reported():
    q3 = [quad(2 * i, 0, 2 * i + 1, 1) for i in range(4)]
    ob = make("SPILL", q3, [sq(0.05 + 0.24 * i, 0.05, 0.2) for i in range(4)])
    res = ua.layout([ob], map_px=512, px_per_m=512)[ob.name]          # four 1 m2 islands at a whole tile each
    check(res["fits"] is False, "layout says it fits: %s" % res)
    r = ua.audit(ob, layer=0, map_px=512, px_per_m=512)
    check(r["islands_off_tile"] > 0 and any("leave the 0-1 tile" in i for i in r["issues"]),
          "spill not reported: %s" % r["issues"])


def active_layer_restored():
    q3 = [quad(2 * i, 0, 2 * i + 1, 1) for i in range(3)]
    ob = make("LAYERS", q3, [sq(0.05, 0.05, 0.1), sq(0.3, 0.05, 0.2), sq(0.6, 0.05, 0.3)], layers=("UVMap", "UV2"))
    before0 = np.concatenate(face_uvs(ob, 0))
    for call in (lambda: ua.pack([ob], map_px=128, pad_px=4, layer=1, rotate=True),
                 lambda: ua.set_texel_density([ob], 20, 128, layer=1),
                 lambda: ua.layout([ob], map_px=128, px_per_m=20, layer=1, directional=False)):
        ob.data.uv_layers.active_index = 0
        call()
        check(ob.data.uv_layers.active_index == 0, "active UV map left at %d" % ob.data.uv_layers.active_index)
    check(np.allclose(np.concatenate(face_uvs(ob, 0)), before0), "UV0 changed although layer=1 was asked")
    check(not np.allclose(np.concatenate(face_uvs(ob, 1)), before0), "UV2 did not change")


def seams_see_smooth_by_angle_modifier():
    bpy.ops.mesh.primitive_cube_add(size=2)
    ob = bpy.context.active_object
    bpy.ops.object.shade_auto_smooth(angle=math.radians(30))   # smooth faces + a Smooth by Angle modifier
    check(len(ob.modifiers) == 1, "Shade Auto Smooth added no modifier")
    base = ua._edges(ua._arrays(ob, None, evaluated=False, need_uv=False))[3]
    check(int(base.sum()) == 0, "the base mesh already has %d hard edges" % int(base.sum()))
    for e in ob.data.edges:
        e.use_seam = False
    found = ua.seams_from_hard_edges([ob])[ob.name]
    seams = sum(e.use_seam for e in ob.data.edges)
    check(found == 12 and seams == 12, "found %d hard edges, %d seams (expected 12)" % (found, seams))


def mirror_modifier_halves():
    """A half strip on +X with a Mirror modifier at its defaults: the halves stack, nothing is folded."""
    q3 = [quad(0, 0, 1, 1), quad(1, 0, 2, 1)]
    ob = make("MIRROR", q3, [[(0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3)],
                             [(0.3, 0.1), (0.5, 0.1), (0.5, 0.3), (0.3, 0.3)]])
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles()                               # one connected strip
    bpy.ops.object.mode_set(mode="OBJECT")
    mod = ob.modifiers.new("Mirror", "MIRROR")
    r = ua.audit(ob, layer=0, map_px=1024)
    check(r["folded_faces"] == 0 and r["mirror_stacks"] == 1 and not r["issues"],
          "defaults: folded %s, mirror stacks %s, issues %s" % (r["folded_faces"], r["mirror_stacks"], r["issues"]))
    mod.offset_u = 1.0
    r = ua.audit(ob, layer=0, map_px=1024)
    check(r["islands"] == 2 and r["mirrored_islands"] == 1 and r["mirror_stacks"] == 0 and r["outside_0_1"] > 0
          and not r["issues"], "offset_u=1: islands %s, mirrored %s, mirror stacks %s, outside %s, issues %s"
          % (r["islands"], r["mirrored_islands"], r["mirror_stacks"], r["outside_0_1"], r["issues"]))


def low_marks_survive_modifiers():
    q3 = [quad(0, 0, 1, 1), quad(1, 0, 2, 1)]
    ob = make("MARKS", q3, [sq(0.1, 0.1, 0.2), sq(0.5, 0.1, 0.1)], low=[0, 1])    # face 1 lowered and marked
    ob.modifiers.new("Mirror", "MIRROR")
    r = ua.audit(ob, layer=0, map_px=1024)
    check(r["faces"] == 4 and r["low_density_faces"] == 2, "faces %s, marked %s" % (r["faces"], r["low_density_faces"]))
    check(not any("varies" in i for i in r["issues"]), "marks ignored: %s" % r["issues"])


def set_density_in_edit_mode():
    q3 = [quad(2 * i, 0, 2 * i + 1, 1) for i in range(2)]
    ob = make("EDITMODE", q3, [sq(0.05, 0.05, 0.1), sq(0.5, 0.05, 0.2)])
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    ua.set_texel_density([ob], px_per_m=300, map_px=1024, pack_after=False)
    check(bpy.context.mode == "EDIT_MESH", "left in %s" % bpy.context.mode)
    bpy.ops.object.mode_set(mode="OBJECT")
    r = ua.audit(ob, layer=0, map_px=1024, px_per_m=300)
    check(abs(r["texel_px_per_m"] / 300 - 1) < 0.01, "density %.1f px/m (the edit-mode write was lost)"
          % r["texel_px_per_m"])


def footprint_helper():
    bpy.ops.mesh.primitive_cube_add(size=1)
    ob = bpy.context.active_object
    ob.scale = (2, 3, 0.2)                                    # 14 m2: the measured Unity case, 243 px at 60 texels/m
    bpy.context.view_layer.update()
    fp = ua.lightmap_footprint(ob, 60)
    check(abs(fp - 243.5) <= 1, "footprint %d px" % fp)


def command_line_exit_code():
    ok_ob = make("CLEAN", [quad(0, 0, 1, 1)], [sq(0.25, 0.25, 0.5)])
    make("SPILL", [quad(3, 0, 4, 1)], [sq(0.6, 0.1, 0.7)])
    with tempfile.TemporaryDirectory() as tmp:
        js = os.path.join(tmp, "r.json")
        check(ua._main(["--objects", "CLEAN", "--layer", "0", "--map", "1024", "--td", "512", "--json", js]) == 0,
              "clean object failed")
        check(os.path.getsize(js) > 0, "no JSON written")
        check(ua._main(["--objects", "SPILL", "--layer", "0", "--map", "1024"]) == 1, "spill passed")
        check(ua._main(["--objects", "SPILL", "--layer", "0", "--map", "1024", "--purpose", "tiling"]) == 0,
              "a tiling layer may leave the tile")
    del ok_ob


# ----------------------------------------------------------------------------------------------- round 2 cases
BOX = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (0, 4, 7, 3), (1, 2, 6, 5)]


def box(x0, y0, z0, x1, y1, z1):
    return [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]


def boxes_object(name, corner_lists):
    verts, faces = [], []
    for c in corner_lists:
        faces += [[len(verts) + i for i in f] for f in BOX]
        verts += c
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    me.uv_layers.new(name="UVMap")
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    return ob


def select_faces(ob, idx):
    """Select exactly these faces in the mesh, in face select mode, after deselecting everything (with UV Sync
    Selection on, that is the UV selection too). Writing face flags without clearing the old vertex selection let
    neighbouring faces join the group."""
    import bmesh
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(ob.data)
    keep = set(idx)
    for f in bm.faces:
        if f.index in keep:
            f.select_set(True)
    bmesh.update_edit_mesh(ob.data)


def recipe_until_unwrap(ob, margin=ua.UNWRAP_MARGIN):
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(30))
    ua.seams_from_hard_edges([ob])
    ob.data.uv_layers.active_index = 0
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")


def crate_grain_by_axis_across():
    """H1: GEOMETRY turns the given axis to +V. Z everywhere puts a vertical batten's grain on V; passing each face's
    short in-plane axis (across the grain), one face group at a time, puts every long island along U."""
    parts = [box(0, 0, 0, 0.6, 0.02, 0.18),          # a side board, grain along X
             box(0, 0.1, 0.6, 0.6, 0.29, 0.62),       # a lid board, grain along X
             box(0.7, 0, 0, 0.74, 0.04, 0.6)]         # a vertical batten, grain along Z
    ob = boxes_object("CRATE", parts)
    recipe_until_unwrap(ob)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.align_rotation(method="GEOMETRY", axis="Z")       # the old one-call recipe
    bpy.ops.object.mode_set(mode="OBJECT")
    r = ua.audit(ob, map_px=1024, pad_px=0, directional=True)
    check(r["elongated_along_v"] > 0, "Z everywhere left no long island along V: %s" % r["issues"])
    across = {}
    for p in ob.data.polygons:
        pts = np.array([ob.data.vertices[v].co for v in p.vertices])
        ext = pts.max(0) - pts.min(0)
        normal = int(np.argmax(np.abs(np.array(p.normal))))
        inplane = [k for k in range(3) if k != normal]
        across.setdefault("XYZ"[min(inplane, key=lambda k: ext[k])], []).append(p.index)
    for axis, idx in sorted(across.items()):
        select_faces(ob, idx)                                        # this group only, not uv.select_all
        bpy.ops.uv.align_rotation(method="GEOMETRY", axis=axis)
        bpy.ops.object.mode_set(mode="OBJECT")
    r = ua.audit(ob, map_px=1024, pad_px=0, directional=True)
    check(r["elongated_islands"] >= 12 and r["elongated_along_v"] == 0,
          "per group: %d long islands, %d along V" % (r["elongated_islands"], r["elongated_along_v"]))


def merged_mirror_halves_bake():
    """H2: a Mirror modifier applied with Merge on leaves each island folded onto itself; layout(bake=True) moves the
    flipped half +1 U, and audit(baking=True) flags a stack left inside 0-1."""
    q3 = [quad(0, 0, 0.6, 0.4)]
    ob = make("BRACKET", q3, [sq(0.1, 0.1, 0.3, 0.2)])
    ob.modifiers.new("Mirror", "MIRROR").use_clip = True
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.modifier_apply(modifier="Mirror")
    check(len(ob.data.polygons) == 2, "Mirror did not double the faces")
    r = ua.audit(ob, map_px=1024, baking=True)
    check(any("bake time" in i for i in r["issues"]), "merged halves inside 0-1 not flagged: %s" % r["issues"])
    res = ua.layout([ob], 1024, px_per_m=512, bake=True)[ob.name]
    check(res["mirror_halves_moved"] == 1, "layout: %s" % res)
    f = face_uvs(ob)
    out_ = [i for i in range(2) if f[i][:, 0].min() >= 1 - 1e-6]
    check(len(out_) == 1, "expected one half wholly at +1 U, got %s" % out_)
    r = ua.audit(ob, map_px=1024, px_per_m=512, baking=True)
    check(not r["issues"], "audit after layout: %s" % r["issues"])
    reset()
    ob = make("PAIR", [quad(0, 0, 1, 1), quad(3, 0, 4, 1)], [sq(0.1, 0.1, 0.3)] * 2)
    ua.layout([ob], 1024, px_per_m=256, bake=False)
    r = ua.audit(ob, map_px=1024, px_per_m=256, baking=True)
    check(any("bake time" in i for i in r["issues"]), "a stack laid out without bake passed: %s" % r["issues"])


def unwrap_margin_keeps_seams():
    """H3: unwrapping with margin 0 can fuse islands that land touching along a seam; 0.001 keeps them apart."""
    import random
    fused = {0.0: 0, ua.UNWRAP_MARGIN: 0}
    for margin in fused:
        for seed in (0, 2, 3):
            reset()
            rnd = random.Random(seed)
            parts = []
            for i in range(12):
                sx, sy, sz = rnd.uniform(0.05, 0.6), rnd.uniform(0.02, 0.3), rnd.uniform(0.05, 0.6)
                parts.append(box(2 * i, 0, 0, 2 * i + sx, sy, sz))
            ob = boxes_object("BOXES", parts)
            recipe_until_unwrap(ob, margin)
            r = ua.audit(ob, map_px=1024, pad_px=0, baking=True)
            fused[margin] += r["hard_edges_not_seams"]
    print("INFO unwrap_margin_keeps_seams: hard edges fused off their seams, margin 0: %d, margin %g: %d"
          % (fused[0.0], ua.UNWRAP_MARGIN, fused[ua.UNWRAP_MARGIN]))
    check(fused[ua.UNWRAP_MARGIN] == 0, "margin %g still fused islands" % ua.UNWRAP_MARGIN)


def lightmap_charts_cut_at_corners():
    """H3, lightmap: Smart UV Project with island_margin 0 joined two faces across a 90 deg corner of a wall; the
    lightmap audit reports it, and island_margin 0.001 keeps six charts."""
    for margin, want in ((0.0, True), (ua.UNWRAP_MARGIN, False)):
        reset()
        bpy.ops.mesh.primitive_cube_add(size=1)
        ob = bpy.context.active_object
        ob.scale = (2, 0.2, 3)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        me = ob.data
        me.uv_layers.new(name="UV2")
        me.uv_layers.active_index = 1
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=margin)
        bpy.ops.object.mode_set(mode="OBJECT")
        me.uv_layers.active_index = 0
        ua.pack_lightmap([ob], texels_per_m=20)
        r = ua.audit(ob, layer=1, purpose="lightmap", texels_per_m=20)
        flagged = any("cut the charts" in i for i in r["issues"])
        print("INFO lightmap_charts_cut_at_corners: island_margin %g -> %d charts, chart bends %d"
              % (margin, r["islands"], r["chart_bends"]))
        if want:
            check(flagged or r["islands"] == 6, "a chart across a corner passed: %s" % r["issues"])
        else:
            check(not flagged and r["islands"] == 6, "island_margin %g: %s charts, %s" % (margin, r["islands"],
                                                                                         r["issues"]))


def uv0_is_the_default_layer():
    """M1: with the lightmap map active, pack, layout and audit still work on UV0 unless told otherwise."""
    q3 = [quad(2 * i, 0, 2 * i + 1, 1) for i in range(3)]
    ob = make("DEFAULTS", q3, [sq(0.05, 0.05, 0.1), sq(0.3, 0.05, 0.2), sq(0.6, 0.05, 0.3)], layers=("UVMap", "UV2"))
    ob.data.uv_layers.active_index = 1
    uv2 = np.concatenate(face_uvs(ob, 1))
    ua.layout([ob], 1024, px_per_m=256)
    ua.pack([ob], 1024)
    check(np.allclose(np.concatenate(face_uvs(ob, 1)), uv2), "UV2 changed although no layer was given")
    check(ob.data.uv_layers.active_index == 1, "the active map was not restored")
    r = ua.audit(ob, px_per_m=256)
    check(r["layer"] == "UVMap", "the audit read %s" % r["layer"])


def trim_strip_band_and_rows():
    """M2: a trim strip at 1.15x that spills into the next row passes the mean but not the per-island band or rows."""
    ob = make("CASING", [quad(0, 0, 1, 0.25), quad(0, 1, 1, 1.25)],
              [[(0.0, 0.0), (0.25, 0.0), (0.25, 0.125), (0.0, 0.125)],
               [(0.3, 0.0), (0.5875, 0.0), (0.5875, 0.14375), (0.3, 0.14375)]])
    r = ua.audit(ob, map_px="2048x1024", px_per_m=512, purpose="trim", rows="0-128,128-192")
    check(r["islands_off_density"] == 1 and r["islands_across_rows"] == 1, "trim audit: %s" % r["issues"])
    check(ua._main(["--objects", "CASING", "--purpose", "trim", "--map", "2048x1024", "--td", "512",
                    "--rows", "0-128,128-192"]) == 1, "the CLI passed it")


def stacking_tools():
    """M3: stack_faces copies UVs by face correspondence; uv.copy / uv.paste one island at a time stacks too."""
    q3 = [quad(0, 0, 1, 0.5), quad(3, 0, 4, 0.5), quad(6, 0, 7, 0.5)]
    ob = make("STACKS", q3, [sq(0.1, 0.1, 0.4, 0.2), sq(0.1, 0.5, 0.4, 0.2), sq(0.6, 0.5, 0.2, 0.1)])
    ua.stack_faces(ob, [0], [1])
    f = face_uvs(ob)
    check(np.allclose(f[1], f[0]), "stack_faces did not stack")
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    select_faces(ob, [0])
    bpy.ops.uv.copy()
    select_faces(ob, [2])
    bpy.ops.uv.paste()
    bpy.ops.object.mode_set(mode="OBJECT")
    f = face_uvs(ob)
    check(np.allclose(np.sort(f[2], 0), np.sort(f[0], 0), atol=1e-6), "uv.paste did not stack one island")


def lightmap_pack_and_measured_footprint():
    """Footprint refinement: pack_lightmap keeps 2 texels at b = 1; the audit then checks the measured-b footprint."""
    bpy.ops.mesh.primitive_cube_add(size=1)
    ob = bpy.context.active_object
    ob.scale = (2, 0.2, 3)                                      # 14 m2
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    me = ob.data
    me.uv_layers.new(name="UV2")
    me.uv_layers.active_index = 1
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=ua.UNWRAP_MARGIN)
    bpy.ops.object.mode_set(mode="OBJECT")
    me.uv_layers.active_index = 0
    size = ua.pack_lightmap([ob], texels_per_m=20)[ob.name]
    check(size == int(20 * math.sqrt(14)), "packed for %s px" % size)
    r = ua.audit(ob, layer=1, purpose="lightmap", map_px=size)              # b = 1: the worst case
    check(r["padding_ok"] and r["margin_px"] >= 0.9 and not r["issues"], "at b = 1: %s, margin %s" % (r["issues"],
                                                                                                      r["margin_px"]))
    r = ua.audit(ob, layer=1, purpose="lightmap", texels_per_m=20)          # measured b
    b = r["uv2_box_share"]
    check(0.5 < b <= 1.0 and not r["issues"], "measured b %s: %s" % (b, r["issues"]))
    fpm = ua.lightmap_footprint(ob, 20, measured=True)
    check(abs(fpm - 20 * math.sqrt(14 / b)) <= 1 and fpm >= size, "measured footprint %s px (b %s)" % (fpm, b))
    with tempfile.TemporaryDirectory() as tmp:
        js = os.path.join(tmp, "r.json")
        code = ua._main(["--objects", ob.name, "--layer", "1", "--purpose", "lightmap", "--map", "165.2",
                         "--json", js])
        import json
        with open(js, encoding="utf-8") as fh:
            rep = json.load(fh)[0]
        check(rep["map_px"] == [165, 165] and code in (0, 1), "--map 165.2 read as %s" % rep["map_px"])


# ----------------------------------------------------------------------------------------------- round 3 cases
def door_wall(name):
    """A 2 x 0.2 x 3 m wall with a 0.9 x 2.1 m door, built from 22 quads, flat-shaded, with UVMap and UV2."""
    import bmesh
    quads = []
    for y, flip in ((0.0, False), (0.2, True)):
        for (x0, x1, z0, z1) in ((0, 0.55, 0, 2.1), (1.45, 2, 0, 2.1), (0, 0.55, 2.1, 3), (0.55, 1.45, 2.1, 3),
                                 (1.45, 2, 2.1, 3)):
            q = [(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)]
            quads.append(q[::-1] if flip else q)
    quads += [[(0.55, 0, 0), (0.55, 0, 2.1), (0.55, 0.2, 2.1), (0.55, 0.2, 0)],
              [(1.45, 0.2, 0), (1.45, 0.2, 2.1), (1.45, 0, 2.1), (1.45, 0, 0)],
              [(0.55, 0, 2.1), (1.45, 0, 2.1), (1.45, 0.2, 2.1), (0.55, 0.2, 2.1)]]
    for x, flip in ((0, False), (2, True)):
        for z0, z1 in ((0, 2.1), (2.1, 3)):
            q = [(x, 0.2, z0), (x, 0.2, z1), (x, 0, z1), (x, 0, z0)]
            quads.append(q[::-1] if flip else q)
    for x0, x1 in ((0, 0.55), (0.55, 1.45), (1.45, 2)):
        quads.append([(x0, 0, 3), (x1, 0, 3), (x1, 0.2, 3), (x0, 0.2, 3)])
    for x0, x1 in ((0, 0.55), (1.45, 2)):
        quads.append([(x0, 0.2, 0), (x1, 0.2, 0), (x1, 0, 0), (x0, 0, 0)])
    bm = bmesh.new()
    vmap = {}
    for q in quads:
        vs = []
        for p in q:
            key = tuple(round(c, 6) for c in p)
            if key not in vmap:
                vmap[key] = bm.verts.new(key)
            vs.append(vmap[key])
        bm.faces.new(vs)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.uv_layers.new(name="UVMap")
    me.uv_layers.new(name="UV2")
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.shade_flat()
    return ob


def unwrap_active(ob, layer, how):
    ob.data.uv_layers.active_index = layer
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    if how == "seams":
        ua.seams_from_hard_edges([ob])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    if how == "smart":
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=ua.UNWRAP_MARGIN)
    else:
        bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=ua.UNWRAP_MARGIN)
    bpy.ops.object.mode_set(mode="OBJECT")
    ob.data.uv_layers.active_index = 0


def lightmap_uv2_seams_not_smart_project():
    """M1: on a wall with a door, Smart UV Project at island_margin 0.001 still joins charts across 90 deg corners
    (the audit flags them); seams on the hard edges and an unwrap at margin 0.001 give clean charts."""
    smart = door_wall("WALL_SMART")
    unwrap_active(smart, 1, "smart")
    ua.pack_lightmap([smart], texels_per_m=20)
    r = ua.audit(smart, texels_per_m=20)
    print("INFO lightmap_uv2_seams_not_smart_project: Smart UV Project %d charts, %d bends" % (r["islands"],
                                                                                            r["chart_bends"]))
    check(r["layer"] == "UV2" and r["purpose"] == "lightmap", "texels_per_m audited %s as %s" % (r["layer"],
                                                                                                r["purpose"]))
    check(r["chart_bends"] > 0 and any("cut the charts" in i for i in r["issues"]),
          "Smart UV Project at 0.001 joined no charts here, or the audit missed it: %s" % r["issues"])
    seams = door_wall("WALL_SEAMS")
    unwrap_active(seams, 1, "seams")
    ua.pack_lightmap([seams], texels_per_m=20)
    r2 = ua.audit(seams, texels_per_m=20)
    check(r2["chart_bends"] == 0 and not r2["issues"], "seam-based UV2: %d bends, %s" % (r2["chart_bends"],
                                                                                        r2["issues"]))


def lightmap_flags_on_the_command_line():
    """H1, M3: --lightmap-texels alone is a lightmap audit of the second map; with another purpose, or a lightmap
    without a footprint or texels, the command exits 2."""
    ob = door_wall("WALL_CLI")
    unwrap_active(ob, 1, "seams")
    ua.pack_lightmap([ob], texels_per_m=20)
    import json
    with tempfile.TemporaryDirectory() as tmp:
        js = os.path.join(tmp, "r.json")
        code = ua._main(["--objects", "WALL_CLI", "--lightmap-texels", "20", "--json", js])
        with open(js, encoding="utf-8") as fh:
            rep = json.load(fh)[0]
    check(code == 0 and rep["purpose"] == "lightmap" and rep["layer"] == "UV2" and rep.get("uv2_box_share"),
          "--lightmap-texels alone: exit %s, %s %s" % (code, rep["purpose"], rep["layer"]))
    check(ua._main(["--objects", "WALL_CLI", "--purpose", "unique", "--lightmap-texels", "20"]) == 2,
          "--purpose unique with --lightmap-texels did not exit 2")
    check(ua._main(["--objects", "WALL_CLI", "--lightmap"]) == 2, "--lightmap without a footprint did not exit 2")
    # the documented command itself, in a second Blender: the process exit codes
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        blend = os.path.join(tmp, "wall.blend")
        bpy.ops.wm.save_as_mainfile(filepath=blend, copy=True)

        def run(*args):
            cmd = [bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1", blend,
                   "--python", str(SCRIPT), "--", "--objects", "WALL_CLI"] + list(args)
            return subprocess.run(cmd, capture_output=True, text=True, timeout=300).returncode
        codes = (run("--lightmap-texels", "20"), run("--purpose", "unique", "--lightmap-texels", "20"))
    check(codes == (0, 2), "documented command exit codes %s, expected (0, 2)" % (codes,))


def bevel_stack_order_of_work():
    """H2, M5: a live Bevel -> Triangulate -> Weighted Normal stack. layout refuses it; applying the Bevel, keeping
    Triangulate off until after layout, keeping the stack's normals and seaming by angle passes the bake audit."""
    def build():
        reset()
        bpy.ops.mesh.primitive_cube_add(size=1)
        ob = bpy.context.active_object
        ob.scale = (0.6, 0.05, 0.9)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        bpy.ops.object.shade_smooth()
        bev = ob.modifiers.new("Bevel", "BEVEL")
        bev.width, bev.segments, bev.limit_method = 0.004, 2, "ANGLE"
        bev.face_strength_mode = "FSTR_AFFECTED"
        ob.modifiers.new("Triangulate", "TRIANGULATE")
        wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
        wn.keep_sharp, wn.use_face_influence = True, True
        return ob
    ob = build()
    unwrap_active(ob, 0, "plain")
    try:
        ua.layout([ob], 1024, px_per_m=512)
        check(False, "layout accepted a live Bevel")
    except ValueError:
        pass
    ob = build()
    bpy.ops.object.modifier_apply(modifier="Bevel")                  # topology-changing: apply before seams
    ob.modifiers["Triangulate"].show_viewport = False                # back on after layout
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="EDGE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.mesh.edges_select_sharp(sharpness=math.radians(30))     # seams by angle; the stack keeps its normals
    bpy.ops.mesh.mark_seam()
    bpy.ops.object.mode_set(mode="OBJECT")
    unwrap_active(ob, 0, "plain")
    res = ua.layout([ob], 1024, px_per_m=512)[ob.name]
    check(res["fits"], "layout: %s" % res)
    ob.modifiers["Triangulate"].show_viewport = True
    r = ua.audit(ob, map_px=1024, px_per_m=512, baking=True)
    check(not r["issues"] and r["hard_edges_not_seams"] == 0, "after the fixed order: %s" % r["issues"])


def stack_faces_checks_corner_order():
    """H3: stack_faces stacks a moved and turned copy, and refuses (writing nothing) a copy whose corners run in
    another order, as a triangulated duplicate's do."""
    def rotz(p, k):
        c, s = round(math.cos(k * math.pi / 2)), round(math.sin(k * math.pi / 2))
        return (p[0] * c - p[1] * s, p[0] * s + p[1] * c, p[2])
    a = box(0, 0, 0, 0.4, 0.1, 0.2)
    b = [tuple(x + y for x, y in zip(rotz(p, 1), (2, 0, 0))) for p in a]      # turned 90 deg and moved
    c = [tuple(x + y for x, y in zip(p, (4, 0, 0))) for p in a]               # moved, faces start elsewhere
    verts, faces = a + b + c, []
    for k, part in enumerate((BOX, BOX, [f[1:] + f[:1] for f in BOX])):
        faces += [[8 * k + i for i in f] for f in part]
    me = bpy.data.meshes.new("PARTS")
    me.from_pydata(verts, [], faces)
    me.uv_layers.new(name="UVMap")
    ob = bpy.data.objects.new("PARTS", me)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    unwrap_active(ob, 0, "plain")
    ua.stack_faces(ob, list(range(6)), list(range(6, 12)))
    f = face_uvs(ob)
    check(all(np.allclose(f[i], f[i + 6]) for i in range(6)), "the turned copy is not stacked")
    before = np.concatenate(face_uvs(ob))
    try:
        ua.stack_faces(ob, list(range(6)), list(range(12, 18)))
        check(False, "a copy in another corner order was stacked")
    except ValueError:
        pass
    check(np.allclose(np.concatenate(face_uvs(ob)), before), "a refused stack still wrote UVs")


def text_check_follows_align_rotation():
    """M2: a sign aligned with align_rotation(GEOMETRY, Z) passes audit(text=True); turned 180 deg or mirrored in U
    it is reported. Without text=True neither is an issue."""
    reset()
    bpy.ops.mesh.primitive_plane_add(size=1, rotation=(math.radians(90), 0, math.radians(30)))
    ob = bpy.context.active_object
    ob.scale = (1.0, 0.5, 1.0)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    ob.data.attributes.new(ua.TEXT_ATTR, "BOOLEAN", "FACE").data.foreach_set("value", [True])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.001)
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.transform.rotate(value=math.radians(137), orient_axis="Z")    # any start rotation
    bpy.ops.uv.align_rotation(method="GEOMETRY", axis="Z")
    bpy.ops.uv.pack_islands(rotate=False, margin=0.05)                    # back inside the tile, still upright
    bpy.ops.object.mode_set(mode="OBJECT")
    r = ua.audit(ob, map_px=1024, pad_px=0, text=True)
    check(not r["issues"], "aligned sign: %s" % r["issues"])
    lay = ob.data.uv_layers[0]
    uv = _uv(lay)
    c = (uv.min(0) + uv.max(0)) / 2
    lay.uv.foreach_set("vector", (2 * c - uv).ravel())                     # 180 deg
    ob.data.update()
    r = ua.audit(ob, map_px=1024, pad_px=0, text=True)
    check(r["text_islands_not_upright"] == 1, "turned sign not reported: %s" % r["issues"])
    check(not ua.audit(ob, map_px=1024, pad_px=0)["issues"], "turned sign reported without text=True")
    m = uv.copy()
    m[:, 0] = 2 * c[0] - m[:, 0]                                            # mirrored in U
    lay.uv.foreach_set("vector", m.ravel())
    ob.data.update()
    r = ua.audit(ob, map_px=1024, pad_px=0, text=True)
    check(any("reads backwards" in i for i in r["issues"]), "mirrored sign not reported: %s" % r["issues"])


def _uv(lay):
    a = np.empty(len(lay.uv) * 2)
    lay.uv.foreach_get("vector", a)
    return a.reshape(-1, 2)


# ----------------------------------------------------------------------------------------------- round 4 cases
def _finish(bm, name):
    import bmesh
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for f in bm.faces:
        f.smooth = True
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.uv_layers.new(name="UVMap")
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    return ob


def hs_panel(name="PANEL"):
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(1.0, 0.08, 2.0), verts=bm.verts)
    return _finish(bm, name)


def hs_ridge(name="RIDGE"):
    """A 1 x 0.1 x 2 m block whose front folds 13 deg along a vertical ridge (blender-mesh-topology's test shape)."""
    import bmesh
    h = 0.5 * math.tan(math.radians(13.0 / 2))
    bm = bmesh.new()
    f = [bm.verts.new(c) for c in ((0, 0, 0), (0.5, -h, 0), (1, 0, 0), (1, 0, 2), (0.5, -h, 2), (0, 0, 2))]
    b = [bm.verts.new(c) for c in ((0, 0.1, 0), (1, 0.1, 0), (1, 0.1, 2), (0, 0.1, 2))]
    for vs in ([f[0], f[1], f[4], f[5]], [f[1], f[2], f[3], f[4]], [b[0], b[3], b[2], b[1]], [f[0], f[5], b[3], b[0]],
               [f[2], b[1], b[2], f[3]], [f[0], b[0], b[1], f[2], f[1]], [f[5], f[4], f[3], b[2], b[3]]):
        bm.faces.new(vs)
    return _finish(bm, name)


def hs_half_cover(name="COVER"):
    """Half of a ridged cover, x 0..0.3, open on the mirror plane x = 0 where its 53 deg ridge lies."""
    import bmesh
    bm = bmesh.new()
    v = [bm.verts.new(c) for c in ((0, -0.2, 0), (0.3, -0.2, 0), (0.3, 0.2, 0), (0, 0.2, 0),
                                   (0, -0.2, 0.35), (0.3, -0.2, 0.2), (0.3, 0.2, 0.2), (0, 0.2, 0.35))]
    for fi in ((0, 3, 2, 1), (4, 5, 6, 7), (1, 2, 6, 5), (0, 1, 5, 4), (2, 3, 7, 6)):
        bm.faces.new([v[i] for i in fi])
    return _finish(bm, name)


def add_stack(ob, route, mirror=None, triangulate=True, sba=None, segments=2):
    """blender-mesh-topology's stacks: route A = Bevel (Harden Normals) -> Triangulate (Keep Normals); route B =
    Bevel (Face Strength Affected) -> Triangulate -> Weighted Normal. mirror: "above" or "below" the Bevel.
    sba: a Smooth by Angle (Shade Auto Smooth) at this angle moved to the top."""
    if mirror == "above":
        ob.modifiers.new("Mirror", "MIRROR").use_clip = True
    bev = ob.modifiers.new("Bevel", "BEVEL")
    bev.limit_method, bev.width, bev.segments = "ANGLE", 0.01, segments
    if route == "A":
        bev.harden_normals = True
    else:
        bev.face_strength_mode = "FSTR_AFFECTED"
    if mirror == "below":
        ob.modifiers.new("Mirror", "MIRROR").use_clip = True
    if triangulate:
        tri = ob.modifiers.new("Triangulate", "TRIANGULATE")
        tri.min_vertices, tri.keep_custom_normals = 4, True
    if route == "B":
        wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
        wn.mode, wn.keep_sharp, wn.use_face_influence = "FACE_AREA", True, True
    if sba:
        with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob],
                                       selected_editable_objects=[ob]):
            bpy.ops.object.shade_auto_smooth(angle=math.radians(sba))
            s = ob.modifiers[-1]
            s.use_pin_to_last = False
            bpy.ops.object.modifier_move_to_index(modifier=s.name, index=0)
    bpy.context.view_layer.update()


def tri_on(ob, on=True):
    for m in ob.modifiers:
        if m.type == "TRIANGULATE":
            m.show_viewport = on
    bpy.context.view_layer.update()


def normals_by_position(ob, digits=5):
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    try:
        out, cn = {}, me.corner_normals
        for li, loop in enumerate(me.loops):
            key = tuple(round(c, digits) for c in me.vertices[loop.vertex_index].co)
            out.setdefault(key, []).append(cn[li].vector.copy())
        return out
    finally:
        ev.to_mesh_clear()


def normals_change(a, b):
    """The largest angle from a corner normal to the nearest one at the same position in the other set (degrees),
    and whether both sets have the same positions (no geometry lost or moved)."""
    worst = 0.0
    for x, y in ((a, b), (b, a)):
        for pos, ns in x.items():
            ref = y.get(pos)
            if ref:
                worst = max(worst, max(min(math.degrees(n.angle(m, 0.0)) for m in ref) for n in ns))
    return round(worst, 3), set(a) == set(b)


def seam_and_unwrap(ob, st):
    """The recipe after apply_stack: seams (by angle on a hard-surface stack, else shade by angle), unwrap UV0."""
    if st["hard_surface"]:
        ua.seams_by_angle([ob])
    elif not st["shading_designed"]:
        ob.data.set_sharp_from_angle(angle=math.radians(30))     # this mesh only, like the recipe
        ob.data.shade_smooth()
    ua.seams_from_hard_edges([ob])
    ob.data.uv_layers.active_index = 0
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=ua.UNWRAP_MARGIN)
    bpy.ops.object.mode_set(mode="OBJECT")


def stack_smooth_by_angle_first():
    """H1: a Smooth by Angle above a Bevel (routes A and B). apply_stack applies both from the top; the normals and
    the geometry match the live stack (applying the Bevel alone had moved them 39.14 and 34.33 deg)."""
    for route in ("A", "B"):
        reset()
        ob = hs_ridge()
        add_stack(ob, route, sba=10)
        before = normals_by_position(ob)
        st = ua.apply_stack(ob)
        check(st["hard_surface"] and len(st["applied"]) == 2 and st["triangulate"],
              "route %s: apply_stack %s" % (route, st))
        seam_and_unwrap(ob, st)
        tri_on(ob)
        moved, same = normals_change(before, normals_by_position(ob))
        check(moved < 0.01 and same, "route %s: normals moved %.3f deg, same geometry %s" % (route, moved, same))


def stack_route_a_never_reshaded():
    """H1: a route-A piece (Harden Normals, no Weighted Normal) is a hard-surface stack: the recipe seams it by angle
    and never shades it by angle, so its normals and sharp edges stay as designed."""
    ob = hs_panel()
    add_stack(ob, "A", segments=2)
    before = normals_by_position(ob)
    st = ua.apply_stack(ob)
    check(st["hard_surface"] and st["applied"] == ["Bevel"], "apply_stack %s" % st)
    sharp = ob.data.attributes.get("sharp_edge")
    n_sharp = sum(1 for v in sharp.data if v.value) if sharp else 0
    seam_and_unwrap(ob, st)
    sharp = ob.data.attributes.get("sharp_edge")
    check((sum(1 for v in sharp.data if v.value) if sharp else 0) == n_sharp, "the recipe changed the sharp edges")
    check(sum(e.use_seam for e in ob.data.edges) > 0, "no seams placed")
    tri_on(ob)
    moved, same = normals_change(before, normals_by_position(ob))
    check(moved < 0.01 and same, "normals moved %.3f deg" % moved)
    r = ua.audit(ob, map_px=1024, pad_px=0, baking=True)
    check(r["hard_edges_not_seams"] == 0, "hard edges off seams: %s" % r["issues"])
    # for the record: what shading by angle would have done to it
    tri_on(ob, False)
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(30))
    tri_on(ob)
    print("INFO stack_route_a_never_reshaded: shade_smooth_by_angle would move the normals %.2f deg"
          % normals_change(before, normals_by_position(ob))[0])


def stack_mirror_above_bevel():
    """H1: Mirror -> Bevel -> Triangulate -> Weighted Normal. The Mirror has a Bevel below it, so apply_stack applies
    both from the top: the chamfers on the mirror plane survive (the Bevel applied alone lost all 8)."""
    ob = hs_half_cover()
    add_stack(ob, "B", mirror="above")
    before = normals_by_position(ob)
    tri_on(ob, False)
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    nf = len(ev.to_mesh().polygons)
    ev.to_mesh_clear()
    st = ua.apply_stack(ob)
    check(st["applied"] == ["Mirror", "Bevel"] and not st["mirrors_live"], "apply_stack %s" % st)
    check(len(ob.data.polygons) == nf, "faces %d, the live stack had %d" % (len(ob.data.polygons), nf))
    seam_and_unwrap(ob, st)
    tri_on(ob)
    moved, same = normals_change(before, normals_by_position(ob))
    check(moved < 0.01 and same, "normals moved %.3f deg, same geometry %s" % (moved, same))


def stack_bevel_then_mirror():
    """H1: Bevel -> Mirror -> Triangulate -> Weighted Normal. The Mirror stays live through seams and unwrap (the
    halves share UVs), is applied just before layout, and layout(bake=True) moves the flipped half +1 U."""
    ob = hs_half_cover()
    add_stack(ob, "B", mirror="below")
    before = normals_by_position(ob)
    st = ua.apply_stack(ob)
    check(st["applied"] == ["Bevel"] and st["mirrors_live"] == ["Mirror"], "apply_stack %s" % st)
    seam_and_unwrap(ob, st)
    try:
        ua.layout([ob], 1024, px_per_m=256)
        check(False, "layout accepted the live Mirror")
    except ValueError:
        pass
    st2 = ua.apply_stack(ob, keep_mirror=False)
    check(st2["applied"] == ["Mirror"], "second apply_stack %s" % st2)
    res = ua.layout([ob], 1024, px_per_m=256, bake=True)[ob.name]
    check(res["fits"] and res["mirror_halves_moved"] >= 1, "layout %s" % res)
    tri_on(ob)
    r = ua.audit(ob, map_px=1024, px_per_m=256, baking=True)
    check(not r["issues"], "after layout: %s" % r["issues"])
    moved, same = normals_change(before, normals_by_position(ob))
    check(moved < 0.01 and same, "normals moved %.3f deg, same geometry %s" % (moved, same))


def stack_added_triangulate():
    """H1: a piece without a Triangulate gets one from apply_stack(add_triangulate=True): Minimum Vertices 4, Keep
    Normals, directly above the Weighted Normal. The normals match the stack as designed (route A: the live stack;
    route B: Bevel -> Triangulate -> Weighted Normal)."""
    ob = hs_panel("PANEL_A")
    add_stack(ob, "A", triangulate=False)
    before = normals_by_position(ob)
    st = ua.apply_stack(ob, add_triangulate=True)
    tri = ob.modifiers.get(st["triangulate"] or "")
    check(tri is not None and tri.keep_custom_normals and tri.min_vertices == 4 and not tri.show_viewport,
          "route A Triangulate %s" % st)
    tri_on(ob)
    moved, same = normals_change(before, normals_by_position(ob))
    check(moved < 0.01 and same, "route A: normals moved %.3f deg" % moved)
    ref = hs_panel("PANEL_REF")
    add_stack(ref, "B")                                           # the stack as designed
    designed = normals_by_position(ref)
    bpy.data.objects.remove(ref, do_unlink=True)
    ob = hs_panel("PANEL_B")
    add_stack(ob, "B", triangulate=False)
    st = ua.apply_stack(ob, add_triangulate=True)
    order = [m.type for m in ob.modifiers]
    check(order == ["TRIANGULATE", "WEIGHTED_NORMAL"], "route B stack after apply_stack: %s" % order)
    tri_on(ob)
    moved, same = normals_change(designed, normals_by_position(ob))
    check(moved < 0.01 and same, "route B: normals %.3f deg off the designed stack" % moved)


def seams_by_angle_matches_select_sharp():
    """seams_by_angle marks the edges mesh.edges_select_sharp(30 deg) selects, and leaves normals and selection."""
    ob = hs_panel()
    add_stack(ob, "A", segments=2, triangulate=False)
    ua.apply_stack(ob)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="EDGE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.mesh.edges_select_sharp(sharpness=math.radians(30))
    bpy.ops.object.mode_set(mode="OBJECT")
    want = {e.index for e in ob.data.edges if e.select}
    for e in ob.data.edges:
        e.select = False
    n = ua.seams_by_angle([ob])[ob.name]
    got = {e.index for e in ob.data.edges if e.use_seam}
    check(got == want and n == len(want) and want, "seams %d, edges_select_sharp %d" % (len(got), len(want)))


def text_up_attribute_in_world_space():
    """M1: uv_text_up is read per face in object space and turned into world space: letters running up a pillar
    (their tops along the object's -X) pass with the object rotated 90 deg about Z; the default +Z up fails them."""
    q = [(0, 0, 0), (0.3, 0, 0), (0.3, 0, 2.0), (0, 0, 2.0)]
    ob = make("PILLAR", [q], [[(0.1, 0.2), (0.1, 0.11), (0.7, 0.11), (0.7, 0.2)]])
    ob.data.attributes.new(ua.TEXT_ATTR, "BOOLEAN", "FACE").data.foreach_set("value", [True])
    ob.rotation_euler = (0, 0, math.radians(90))
    bpy.context.view_layer.update()
    r = ua.audit(ob, map_px=1024, pad_px=0, text=True)
    check(r["text_islands_not_upright"] == 1, "default up should fail turned letters: %s" % r["issues"])
    ob.data.attributes.new(ua.TEXT_UP_ATTR, "FLOAT_VECTOR", "FACE").data.foreach_set("vector", [-1.0, 0.0, 0.0])
    r = ua.audit(ob, map_px=1024, pad_px=0, text=True)
    check(not r["issues"], "letters up the pillar with uv_text_up: %s" % r["issues"])
    try:
        ua._main(["--objects", "PILLAR", "--map", "1024", "--pad", "0", "--text"])
    except Exception as e:                                        # the command line must not raise
        check(False, "--text raised %s" % e)
    ob.data.attributes.remove(ob.data.attributes[ua.TEXT_ATTR])
    check(ua._main(["--objects", "PILLAR", "--map", "1024", "--text"]) == 2, "--text with no uv_text faces")


def trim_sheet_2048x1024():
    """M2: a beam on a 2048x1024 trim sheet. The unwrap is in square pixels only with the sheet image as the
    material's active Image Texture node; turn_islands lays the strips along U without distortion;
    set_texel_density(pack_after=False) sets 512 px/m on the non-square sheet."""
    results = {}
    for with_image in (False, True):
        reset()
        ob = boxes_object("BEAM", [box(0, 0, 0, 1.0, 0.08, 0.08)])
        mat = bpy.data.materials.new("M_Trim_%d" % with_image)
        mat.use_nodes = True
        if with_image:
            node = mat.node_tree.nodes.new("ShaderNodeTexImage")
            node.image = bpy.data.images.new("Sheet", 2048, 1024)
            mat.node_tree.nodes.active = node
        ob.data.materials.append(mat)
        ua.seams_from_hard_edges([ob])                            # flat-shaded box: every edge a seam, 6 islands
        recipe_until_unwrap(ob)
        results[with_image] = ua.audit(ob, purpose="trim", map_px="2048x1024", pad_px=0)
    print("INFO trim_sheet_2048x1024: angular p95 without the image node %.2f, with it %.3f"
          % (results[False]["angular_p95"], results[True]["angular_p95"]))
    check(results[False]["angular_p95"] > 1.5 and results[True]["angular_p95"] < 1.02, "aspect %s" % results)
    turned = ua.turn_islands([ob], map_px="2048x1024")[ob.name]
    r = ua.audit(ob, purpose="trim", map_px="2048x1024", pad_px=0)
    check(r["elongated_along_v"] == 0 and r["angular_p95"] < 1.02,
          "after turning %d: along V %d, p95 %.3f" % (turned, r["elongated_along_v"], r["angular_p95"]))
    ua.set_texel_density([ob], 512, "2048x1024", pack_after=False)
    r = ua.audit(ob, purpose="trim", map_px="2048x1024", pad_px=0, px_per_m=512)
    check(abs(r["texel_px_per_m"] - 512) < 2 and r["islands_off_density"] == 0 and r["angular_p95"] < 1.02,
          "density %s, issues %s" % (r["texel_px_per_m"], r["issues"]))


def material_filter_and_command_line():
    """M3, M5, L2: one mesh with a tiling plate (M_Wall, 1 UV tile = 2 m on a 1024 map: 512 px/m) and a trim strip
    (M_Trim_A, 512 px/m on a 2048x1024 sheet). Audited whole, each purpose flags the other part; per material both
    pass. The command line: --material, no mesh matched, --lightmap with another purpose."""
    ob = make("MIXED", [quad(0, 0, 2, 2), quad(3, 0, 4, 0.1)],
              [sq(0.0, 0.0, 1.0), [(0.1, 0.1), (0.35, 0.1), (0.35, 0.15), (0.1, 0.15)]])
    for name in ("M_Wall", "M_Trim_A"):
        ob.data.materials.append(bpy.data.materials.new(name))
    ob.data.polygons[1].material_index = 1
    whole = ua.audit(ob, purpose="trim", map_px="2048x1024", px_per_m=512)
    trim = ua.audit(ob, purpose="trim", material="M_Trim*", map_px="2048x1024", px_per_m=512)
    wall = ua.audit(ob, purpose="tiling", material="M_Wall", map_px=1024, px_per_m=512)
    check(whole["issues"] and not trim["issues"] and not wall["issues"] and trim["faces"] == wall["faces"] == 1,
          "whole %s / trim %s / wall %s" % (whole["issues"], trim["issues"], wall["issues"]))
    try:
        ua.audit(ob, material="M_None")
        check(False, "a material with no faces was audited")
    except ValueError:
        pass
    base = ["--objects", "MIXED"]
    codes = (ua._main(base + ["--purpose", "trim", "--material", "M_Trim*", "--map", "2048x1024", "--td", "512"]),
             ua._main(base + ["--purpose", "trim", "--map", "2048x1024", "--td", "512"]),
             ua._main(base + ["--material", "M_None"]),
             ua._main(["--objects", "mixed*"]),
             ua._main(base + ["--purpose", "unique", "--lightmap", "--map", "128"]))
    check(codes == (0, 1, 2, 2, 2), "exit codes %s, expected (0, 1, 2, 2, 2)" % (codes,))


def lightmap_lods_at_their_own_footprint():
    """Each LOD gets its own lightmap space at 0.5^n texel scale (Unity, measured 2026-10-17): pack_lightmap and the
    audit read n from the <Piece>_LOD<n> name, so each LOD packs its 2-texel gaps for its own footprint; --lod
    overrides the name."""
    import json
    sizes, foot = {}, {}
    for n in (0, 1, 2):
        name = "PROP_LOD%d" % n
        ob = door_wall(name)
        unwrap_active(ob, 1, "seams")
        sizes[n] = ua.pack_lightmap([ob], texels_per_m=20)[name]
        r = ua.audit(ob, texels_per_m=20)
        check(r["lod"] == n and not r["issues"], "%s: lod %s, issues %s" % (name, r["lod"], r["issues"]))
        foot[n] = r["footprint_px"] * math.sqrt(r["uv2_box_share"])     # each LOD's own b taken out
    check(abs(sizes[1] - sizes[0] / 2) <= 1 and abs(sizes[2] - sizes[0] / 4) <= 1, "packed sizes %s" % sizes)
    check(abs(foot[1] / foot[0] - 0.5) < 0.01 and abs(foot[2] / foot[0] - 0.25) < 0.01, "footprints %s" % foot)
    with tempfile.TemporaryDirectory() as tmp:
        js = os.path.join(tmp, "r.json")
        ua._main(["--objects", "PROP_LOD1", "--lightmap-texels", "20", "--json", js])
        with open(js, encoding="utf-8") as fh:
            by_name = json.load(fh)[0]
        ua._main(["--objects", "PROP_LOD1", "--lightmap-texels", "20", "--lod", "2", "--json", js])
        with open(js, encoding="utf-8") as fh:
            forced = json.load(fh)[0]
    check(by_name["lod"] == 1 and forced["lod"] == 2 and abs(forced["footprint_px"] / by_name["footprint_px"] - 0.5)
          < 0.01, "CLI lod %s / %s" % (by_name["lod"], forced["lod"]))


# ----------------------------------------------------------------------------------------------- round 5 cases
def _cutter(name="CUT"):
    import bmesh
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.4)
    bm.to_mesh(me)
    bm.free()
    c = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(c)
    c.display_type = "WIRE"
    return c


def hard_edges_route_a_boolean():
    """H1: a route-A piece with a Boolean (Boolean -> Bevel with Harden Normals -> Triangulate with Keep Normals).
    With the Triangulate back on, its re-encoded custom normals split by a few hundredths of a degree on smooth edges:
    not hard edges (over 0.5 deg only), so the bake audit and the UV2 bend check stay clean."""
    cut = _cutter()
    ob = hs_panel("PANEL_BOOL")
    mod = ob.modifiers.new("Boolean", "BOOLEAN")
    mod.object = cut
    bev = ob.modifiers.new("Bevel", "BEVEL")
    bev.limit_method, bev.width, bev.segments, bev.harden_normals = "ANGLE", 0.005, 2, True
    tri = ob.modifiers.new("Triangulate", "TRIANGULATE")
    tri.min_vertices, tri.keep_custom_normals = 4, True
    st = ua.apply_stack(ob)
    check(st["applied"] == ["Boolean", "Bevel"] and st["hard_surface"], "apply_stack %s" % st)
    seam_and_unwrap(ob, st)
    ob.data.uv_layers.new(name="UV2")
    unwrap_active(ob, 1, "plain")
    ua.pack_lightmap([ob], texels_per_m=20)
    res = ua.layout([ob], 1024, px_per_m=256, bake=True)[ob.name]
    check(res["fits"], "layout %s" % res)
    tri_on(ob)
    _pa, _pb, _uv_split, hard, _key = ua._edges(ua._arrays(ob, 0, True))
    r = ua.audit(ob, map_px=1024, px_per_m=256, baking=True)
    r2 = ua.audit(ob, texels_per_m=20)
    print("INFO hard_edges_route_a_boolean: hard edges %d, all on seams %s; UV2 chart bends %d"
          % (int(hard.sum()), r["hard_edges_not_seams"] == 0, r2["chart_bends"]))
    check(r["hard_edges_not_seams"] == 0 and not any("hard edges" in i for i in r["issues"]),
          "phantom hard edges: %s" % r["issues"])
    check(r2["chart_bends"] == 0, "UV2 chart bends %d: %s" % (r2["chart_bends"], r2["issues"]))


def modular_wall_mixed_materials():
    """M1: one mesh with a cube-projected tiling wall (M_Wall) and trims on a 2048x1024 sheet (M_Trim): turn_islands
    and set_texel_density with material= leave the wall's UVs alone; both audits pass per material."""
    import bmesh
    from mathutils import Matrix
    bm = bmesh.new()
    r = bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(2, 0.2, 3), verts=r["verts"])
    bmesh.ops.translate(bm, vec=(0, 0, 1.5), verts=r["verts"])
    nwall = len(bm.faces)
    r = bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(2, 0.03, 0.12), verts=r["verts"])
    bmesh.ops.translate(bm, vec=(0, -0.115, 0.06), verts=r["verts"])
    r = bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.03, radius2=0.03, depth=2.0)
    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, "Y"), verts=r["verts"])
    bmesh.ops.translate(bm, vec=(0, -0.14, 2.8), verts=r["verts"])
    me = bpy.data.meshes.new("KIT_WallTrim")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("KIT_WallTrim", me)
    bpy.context.scene.collection.objects.link(ob)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    mw, mt = bpy.data.materials.new("M_Wall"), bpy.data.materials.new("M_Trim_A")
    me.materials.append(mw)
    me.materials.append(mt)
    for p in me.polygons:
        p.material_index = 0 if p.index < nwall else 1
    me.uv_layers.new(name="UVMap")
    mt.use_nodes = True
    node = mt.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.new("TrimSheet", 2048, 1024)
    mt.node_tree.nodes.active = node

    def select_material(idx):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        ob.active_material_index = idx
        bpy.ops.object.material_slot_select()
    ua.apply_stack(ob)
    select_material(0)
    bpy.ops.uv.cube_project(cube_size=1024 / 512, correct_aspect=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    ob.data.set_sharp_from_angle(angle=math.radians(30))
    ob.data.shade_smooth()
    ua.seams_from_hard_edges([ob])
    for e in me.edges:                                            # one seam down the pipe
        a, b = (me.vertices[i].co for i in e.vertices)
        if abs(a.z - b.z) < 1e-6 and abs(a.y - b.y) < 1e-6 and abs(a.z - 2.83) < 1e-3 and abs(a.y + 0.14) < 1e-3:
            e.use_seam = True
    select_material(1)
    bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.001)
    bpy.ops.object.mode_set(mode="OBJECT")
    wall_loops = np.concatenate([np.arange(p.loop_start, p.loop_start + p.loop_total)
                                 for p in me.polygons if p.material_index == 0])
    before = _uv(me.uv_layers[0])[wall_loops].copy()
    tm = mt.name                                                  # "M_Trim_A" (or .001 if an earlier case made one)
    turned = ua.turn_islands([ob], map_px="2048x1024", material=tm)[ob.name]
    ua.set_texel_density([ob], 512, "2048x1024", pack_after=False, material=tm)
    after = _uv(me.uv_layers[0])[wall_loops]
    check(np.abs(after - before).max() < 1e-6, "the wall's UVs moved %.3f" % np.abs(after - before).max())
    wall = ua.audit(ob, purpose="tiling", material=mw.name, map_px=1024, px_per_m=512)
    trim = ua.audit(ob, purpose="trim", material=tm, map_px="2048x1024", px_per_m=512)
    print("INFO modular_wall_mixed_materials: %d trim islands turned; trim %.0f px/m" % (turned,
                                                                                      trim["texel_px_per_m"]))
    check(not wall["issues"], "tiling audit: %s" % wall["issues"])
    check(trim["islands_off_density"] == 0 and trim["elongated_along_v"] == 0
          and not any("texel density" in i for i in trim["issues"]), "trim audit: %s" % trim["issues"])
    try:
        ua.set_texel_density([ob], 512, 1024, material=tm)
        check(False, "set_texel_density(material=...) packed the whole object")
    except ValueError:
        pass


def small_lightmaps_packed_for_64():
    """M2: a 0.5 m crate's LOD2 at 15 texels/m has a 4 px b = 1 footprint, too small for 2-texel gaps between 6
    charts: pack_lightmap packs it for 64 px with the note instead of letting the pack spill; the audit checks it as
    packed for 64 px and notes it (a LOD follows its piece)."""
    for n, want64 in ((0, False), (2, True)):
        reset()
        ob = boxes_object("KIT_Crate_LOD%d" % n, [box(0, 0, 0, 0.5, 0.5, 0.5)])
        ob.data.uv_layers.new(name="UV2")
        ua.seams_from_hard_edges([ob])
        unwrap_active(ob, 1, "plain")
        notes = {}
        size = ua.pack_lightmap([ob], texels_per_m=15, notes=notes)[ob.name]
        uv = _uv(ob.data.uv_layers[1])
        r = ua.audit(ob, texels_per_m=15)
        check((size == 64) == want64 and (ob.name in notes) == want64, "LOD%d: packed for %d, notes %s"
              % (n, size, notes))
        check(uv.min() >= 0 and uv.max() <= 1 and not r["issues"], "LOD%d: UV %.3f-%.3f, issues %s"
              % (n, uv.min(), uv.max(), r["issues"]))
        check(r["graded_at_px"] == 64 and any("under 64" in x for x in r["notes"]), "LOD%d notes %s" % (n, r["notes"]))
        if n:
            check("LOD2 follows its piece" in notes[ob.name] and "follows its piece" in r["notes"][0],
                  "LOD note: %s" % notes[ob.name])


def plain_shading_leaves_other_pieces():
    """M3: the recipe shades a plain piece through its mesh (set_sharp_from_angle, shade_smooth), so an applied
    route-A piece that is also selected keeps its normals (the operator moved them 33.84 deg)."""
    hs = hs_panel("KIT_PanelA")
    check(hasattr(hs.data, "set_sharp_from_angle") and hasattr(hs.data, "shade_smooth"),
          "Blender %s has no Mesh.set_sharp_from_angle / shade_smooth" % bpy.app.version_string)
    add_stack(hs, "A")
    ua.apply_stack(hs)
    tri_on(hs)
    before = normals_by_position(hs)
    tri_on(hs, False)
    plain = boxes_object("KIT_Crate", [box(3, 0, 0, 3.5, 0.5, 0.5)])
    hs.select_set(True)                                           # both selected, the plain one active
    st = ua.apply_stack(plain)
    check(not st["hard_surface"] and not st["shading_designed"], "plain piece %s" % st)
    plain.data.set_sharp_from_angle(angle=math.radians(30))
    plain.data.shade_smooth()
    check(all(p.use_smooth for p in plain.data.polygons), "the plain piece was not shaded smooth")
    tri_on(hs)
    moved, same = normals_change(before, normals_by_position(hs))
    check(moved < 0.01 and same, "the selected route-A piece's normals moved %.2f deg" % moved)


def chamfer_panel_lightmap_not_collapsed():
    """M4: a 1 x 0.1 x 2 m panel with a 5 mm, 2-segment bevel (route B), its UV2 at 10 texels/m: the chamfer's
    triangles cover under 1/1000 px^2 each but are mapped at the layout's density, so none is a zero-area face."""
    ob = hs_panel("KIT_Panel")
    ob.scale = (1.0, 0.1 / 0.08, 1.0)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bev = ob.modifiers.new("Bevel", "BEVEL")
    bev.limit_method, bev.width, bev.segments, bev.face_strength_mode = "ANGLE", 0.005, 2, "FSTR_AFFECTED"
    tri = ob.modifiers.new("Triangulate", "TRIANGULATE")
    tri.min_vertices, tri.keep_custom_normals = 4, True
    wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
    wn.mode, wn.keep_sharp, wn.use_face_influence = "FACE_AREA", True, True
    st = ua.apply_stack(ob)
    ua.seams_by_angle([ob])
    ua.seams_from_hard_edges([ob])
    ob.data.uv_layers.new(name="UV2")
    unwrap_active(ob, 1, "plain")
    tri_on(ob)
    ua.pack_lightmap([ob], texels_per_m=10)
    r = ua.audit(ob, texels_per_m=10)
    check(r["zero_area_uv_faces"] == 0 and not any("zero UV area" in i for i in r["issues"]),
          "zero-area faces %d: %s" % (r["zero_area_uv_faces"], r["issues"]))
    del st


def array_copies_paired_by_position():
    """L2: Array -> Bevel (route A) -> Triangulate, applied: the copies are not contiguous face ranges, so stack_faces
    on index ranges refuses; pair_faces finds each copy's faces by position and all 4 copies stack."""
    ob = hs_panel("VENT")
    ob.scale = (0.6, 0.03 / 0.08, 0.1 / 2.0)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    arr = ob.modifiers.new("Array", "ARRAY")
    arr.count, arr.relative_offset_displace = 5, (0, 0, 1.5)
    bev = ob.modifiers.new("Bevel", "BEVEL")
    bev.limit_method, bev.width, bev.segments, bev.harden_normals = "ANGLE", 0.005, 2, True
    tri = ob.modifiers.new("Triangulate", "TRIANGULATE")
    tri.min_vertices, tri.keep_custom_normals = 4, True
    st = ua.apply_stack(ob)
    seam_and_unwrap(ob, st)
    me = ob.data
    cen = np.array([p.center[:] for p in me.polygons])
    step = 0.1 * 1.5
    copy = np.floor((cen[:, 2] - cen[:, 2].min()) / step + 1e-6).astype(int)
    src = [int(i) for i in np.flatnonzero(copy == 0)]
    for k in range(1, 5):
        ua.stack_faces(ob, src, ua.pair_faces(ob, src, (0, 0, k * step)))
    f = face_uvs(ob)
    check(all(np.allclose(f[a], f[b]) for k in range(1, 5)
              for a, b in zip(src, ua.pair_faces(ob, src, (0, 0, k * step)))), "copies not stacked")


def refusals_say_what_to_do():
    """L3, L4: the refusals name the fix: move a Mirror or Array above the Triangulate; for a shared mesh, apply on a
    single-user copy and point the others at it."""
    ob = hs_panel("LOW_MIRROR")
    add_stack(ob, "B")
    ob.modifiers.new("Mirror", "MIRROR")                          # appended below the Weighted Normal
    try:
        ua.apply_stack(ob)
        check(False, "a Mirror below the Triangulate was applied")
    except ValueError as e:
        check("above the Triangulate" in str(e) and "Triangulate down" not in str(e), "message: %s" % e)
    a = hs_panel("SHARED_A")
    add_stack(a, "A")
    b = bpy.data.objects.new("SHARED_B", a.data)
    bpy.context.scene.collection.objects.link(b)
    try:
        ua.apply_stack(a)
        check(False, "a shared mesh was applied")
    except ValueError as e:
        check("single-user copy" in str(e) and "point the others" in str(e), "message: %s" % e)


def stack_faces_names_the_causes():
    """L1: the refusal names the likely causes: a mirrored, scaled or re-ordered copy."""
    a = box(0, 0, 0, 0.4, 0.1, 0.2)
    b = [(x * 1.001 + 2, y * 1.001, z * 1.001) for x, y, z in a]            # scaled 1.001x
    ob = boxes_object("PARTS", [a, b])
    recipe_until_unwrap(ob)
    try:
        ua.stack_faces(ob, list(range(6)), list(range(6, 12)))
        check(False, "a scaled copy was stacked")
    except ValueError as e:
        check("scaled" in str(e) and "mirrored" in str(e), "message: %s" % e)


CASES = [stack_smooth_by_angle_first, stack_route_a_never_reshaded, stack_mirror_above_bevel, stack_bevel_then_mirror,
         stack_added_triangulate, seams_by_angle_matches_select_sharp, text_up_attribute_in_world_space,
         trim_sheet_2048x1024, material_filter_and_command_line, stack_faces_names_the_causes,
         lightmap_lods_at_their_own_footprint, hard_edges_route_a_boolean, modular_wall_mixed_materials,
         small_lightmaps_packed_for_64, plain_shading_leaves_other_pieces, chamfer_panel_lightmap_not_collapsed,
         array_copies_paired_by_position, refusals_say_what_to_do,
         pack_rotation_off_keeps_grain, keep_stacks_keeps_stacks, scale_false_keeps_density, layout_end_to_end,
         text_check_follows_align_rotation,
         lightmap_uv2_seams_not_smart_project, lightmap_flags_on_the_command_line, bevel_stack_order_of_work,
         stack_faces_checks_corner_order,
         layout_atlas_together, off_tile_island_is_reported, crate_grain_by_axis_across, merged_mirror_halves_bake,
         unwrap_margin_keeps_seams, lightmap_charts_cut_at_corners, uv0_is_the_default_layer,
         trim_strip_band_and_rows, stacking_tools, lightmap_pack_and_measured_footprint, active_layer_restored,
         seams_see_smooth_by_angle_modifier,
         mirror_modifier_halves, low_marks_survive_modifiers, set_density_in_edit_mode, footprint_helper,
         command_line_exit_code]


def main():
    print("uv_audit Blender tests on Blender %s" % bpy.app.version_string)
    failed = []
    for case in CASES:
        reset()
        try:
            case()
            print("PASS %s" % case.__name__)
        except Exception as e:                                # report every case, then fail the run
            print("FAIL %s: %s" % (case.__name__, e))
            traceback.print_exc()
            failed.append(case.__name__)
    print("%d case(s), %d failed" % (len(CASES), len(failed)))
    if failed:
        raise RuntimeError("failed: " + ", ".join(failed))


main()
