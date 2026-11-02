"""LOD1 from a quad LOD0 that keeps LOD0's UV maps (so it samples the same atlas and lightmap), trying the clean routes
first and saying which one it took.

Host: Blender 4.2+ (bpy, bmesh, numpy); route 2 needs the Quad Remesher engine (quad_remesh.py beside this file).
Load in Blender:
    path = r"<skill>/scripts/lod_quads.py"                     # __file__ lets it find its sibling scripts
    ns = {"__file__": path}; exec(open(path, encoding="utf-8").read(), ns)
    lod1, report = ns["lod1"](bpy.data.objects["PROP_Pot_Free_A_LOD0"], ratio=0.5, tol=0.015)

Routes, in order; the first that passes is kept:
  1. "loops": loop_decimate (whole edge loops ending at the rim only): clean quads, every UV corner exact. Passes when
     it reaches ratio x 1.2 of LOD0's triangles (the budget is triangles: what the engine draws) within tol. A lathe-like low (a pot) gets there; a remeshed low full of
     poles has few loops that run all the way (measured 2026-11-02: pot 588 to 288, cauldron 756 to only 686).
  2. "remesh": Quad Remesher at ratio x LOD0's quads with each UV island (of every map) a material, so an edge loop
     runs along every seam; each LOD1 corner takes the UVs of the nearest point on the same island of LOD0. Passes
     with no n-gons, deviation within tol and UV density (UV area / 3D area) at p5 0.7 or more of LOD0's median.
     Measured: the pot 304 clean quads at 9 mm; with 30-40 islands the engine left stray faces (26-60 mm off).
  3. "pole_loops": loop_decimate with pole_ends=True (loops may end at a pole): reaches the budget, UVs exact, but
     leaves a pentagon beside every pole end; the exporter's Triangulate turns them into triangles, three each, so it
     may stop short of the budget at 2 x tol ("short_of_budget"): measured, a sack's LOD1 kept 77% of its triangles.
     Then the choice is the user's: accept it, or Decimate (Collapse) to the budget and live with slivers.
tol: metres, the most the LOD may leave off LOD0 (detail_scale.min_width_m at the distance LOD1 takes over). Returns
(the new object <Piece>_LOD1 in LOD0's collections, report with "route", faces, ngons, irregular vertices, deviation
and the routes tried).
"""

import os

import bmesh
import bpy
import numpy as np
from mathutils.bvhtree import BVHTree

_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or "."))


def _load(name):
    ns = {}
    path = os.path.join(_HERE, name)
    exec(compile(open(path, encoding="utf-8").read(), path, "exec"), ns)
    return ns


def _copy(lod0, name):
    ob = lod0.copy()
    ob.data = lod0.data.copy()
    ob.modifiers.clear()
    ob.name = ob.data.name = name
    for c in lod0.users_collection:
        c.objects.link(ob)
    return ob


def _remove(ob):
    me = ob.data
    bpy.data.objects.remove(ob)
    if me.users == 0:
        bpy.data.meshes.remove(me)


def _stats(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    out = {"faces": len(bm.faces), "ngons": sum(1 for f in bm.faces if len(f.verts) > 4),
           "tris": sum(1 for f in bm.faces if len(f.verts) == 3),
           "irregular": sum(1 for v in bm.verts if not v.is_boundary and len(v.link_edges) != 4)}
    bm.free()
    return out


def uv_islands(bm, layers):
    """Face index -> island id; faces join across an edge only where every layer's UVs agree at both its ends."""
    parent = list(range(len(bm.faces)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        f0, f1 = e.link_faces
        same = all((next(l[lay].uv for l in f0.loops if l.vert is v)
                    - next(l[lay].uv for l in f1.loops if l.vert is v)).length <= 1e-6
                   for lay in layers for v in e.verts)
        if same:
            parent[find(f0.index)] = find(f1.index)
    roots = {}
    return [roots.setdefault(find(f.index), len(roots)) for f in bm.faces]


def _density(bm, lay):
    r = []
    for f in bm.faces:
        a3 = f.calc_area()
        uv = [l[lay].uv for l in f.loops]
        a2 = 0.5 * abs(sum(uv[i].x * uv[i - 1].y - uv[i - 1].x * uv[i].y for i in range(len(uv))))
        if a3 > 1e-12:
            r.append(a2 / a3)
    return np.array(r)


def remesh_lod(lod0, ratio, name):
    """Route 2 on its own: (object, report)."""
    qr = _load("quad_remesh.py")
    bm0 = bmesh.new()
    bm0.from_mesh(lod0.data)
    names = [l.name for l in lod0.data.uv_layers]
    layers = [bm0.loops.layers.uv[n] for n in names]
    isl = uv_islands(bm0, layers)
    pts = [v.co.copy() for v in bm0.verts]
    faces = [[v.index for v in f.verts] for f in bm0.faces]
    lp, lf, lm, tries = qr["quad_remesh_to_budget"](pts, faces, max(int(len(faces) * ratio), 8), mats=isl,
                                                     UseMaterialIds=1, CurvatureAdaptivness=20.0)
    tri_of = {}
    for f in bm0.faces:
        for k in range(1, len(f.loops) - 1):
            ls = (f.loops[0], f.loops[k], f.loops[k + 1])
            tri_of.setdefault(isl[f.index], []).append(([l.vert.co.copy() for l in ls],
                                                        [[l[lay].uv.copy() for l in ls] for lay in layers]))
    trees = {m: BVHTree.FromPolygons([c for t in tl for c in t[0]], [(3 * i, 3 * i + 1, 3 * i + 2)
                                                                      for i in range(len(tl))])
             for m, tl in tri_of.items()}
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(p) for p in lp], [], [tuple(f) for f in lf])
    for n in names:
        me.uv_layers.new(name=n)
    for poly in me.polygons:
        poly.use_smooth = True
        m = lm[poly.index] if poly.index < len(lm) else 0
        tree, tl = trees.get(m), tri_of.get(m)
        if tree is None:
            continue
        for li in poly.loop_indices:
            loc, _n, ti, _d = tree.find_nearest(me.vertices[me.loops[li].vertex_index].co)
            a, b, c = tl[ti][0]
            v0, v1, v2 = b - a, c - a, loc - a
            d00, d01, d11, d20, d21 = v0.dot(v0), v0.dot(v1), v1.dot(v1), v2.dot(v0), v2.dot(v1)
            den = (d00 * d11 - d01 * d01) or 1e-30
            w1, w2 = (d11 * d20 - d01 * d21) / den, (d00 * d21 - d01 * d20) / den
            for k, n in enumerate(names):
                ua, ub, uc = tl[ti][1][k]
                me.uv_layers[n].data[li].uv = ua * (1 - w1 - w2) + ub * w1 + uc * w2
    for mat in lod0.data.materials:
        me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    for c in lod0.users_collection:
        c.objects.link(ob)
    ob.matrix_world = lod0.matrix_world.copy()
    bm1 = bmesh.new()
    bm1.from_mesh(me)
    d0 = float(np.median(_density(bm0, layers[0])))
    d1 = _density(bm1, bm1.loops.layers.uv[names[0]]) / max(d0, 1e-12)
    bm0.free()
    bm1.free()
    return ob, {"tries": tries, "islands": max(isl) + 1, "uv_density_p5": round(float(np.percentile(d1, 5)), 3)}


def lod1(lod0, ratio=0.5, tol=0.015, name=None):
    """A LOD1 of lod0 (see the module docstring for the routes). Replaces an object of the same name."""
    ld = _load("loop_decimate.py")
    name = name or lod0.name.rsplit("_LOD", 1)[0] + "_LOD1"
    old = bpy.data.objects.get(name)
    if old is not None:
        _remove(old)
    n0 = sum(len(p.vertices) - 2 for p in lod0.data.polygons)        # the budget is triangles: what the engine draws
    goal = ratio * 1.2 * n0
    tried = []

    def tris_of(ob):
        return sum(len(p.vertices) - 2 for p in ob.data.polygons)

    def done(ob, route, extra=None):
        ob.name = ob.data.name = name
        st = _stats(ob)
        st.update({"triangles": tris_of(ob), "triangle_share": round(tris_of(ob) / float(max(n0, 1)), 3), "route": route, "deviation_max": round(ld["deviation"](lod0, ob)["max"], 4), "tried": tried})
        st.update(extra or {})
        return ob, st

    ob = _copy(lod0, name + "_loops")
    ld["loop_decimate"](ob, tol=tol)
    if tris_of(ob) <= goal:
        return done(ob, "loops")
    tried.append({"route": "loops", "triangles": tris_of(ob)})
    _remove(ob)
    try:
        ob, extra = remesh_lod(lod0, ratio, name + "_remesh")
        dev = ld["deviation"](lod0, ob)["max"]
        st = _stats(ob)
        if st["ngons"] == 0 and dev <= tol and extra["uv_density_p5"] >= 0.7 and tris_of(ob) <= goal:
            return done(ob, "remesh", extra)
        tried.append(dict(extra, route="remesh", faces=st["faces"], deviation_max=round(dev, 4)))
        _remove(ob)
    except RuntimeError as ex:                                      # no engine, or it failed
        tried.append({"route": "remesh", "error": str(ex)[:160]})
    ob = _copy(lod0, name + "_pole_loops")
    t = tol
    for _ in range(12):                                           # loosen tol (up to 2 x) only as far as needed
        ld["loop_decimate"](ob, tol=t, pole_ends=True)
        if tris_of(ob) <= goal or t >= 2 * tol:
            break
        t = min(t * 1.1, 2 * tol)
    return done(ob, "pole_loops", {"tol_used": round(t, 4), "short_of_budget": tris_of(ob) > goal})
