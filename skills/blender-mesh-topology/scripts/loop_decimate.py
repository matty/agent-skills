"""Reduce an over-dense structured low (face grids, bands, swept shells, lathe props) by removing whole edge loops.

Host: Blender 4.2+ (bpy, bmesh, mathutils; tested on 5.2.2). Load in Blender:
    ns = {}; exec(open(r"<skill>/scripts/loop_decimate.py", encoding="utf-8").read(), ns)
    dense = ob.copy(); dense.data = ob.data.copy()                 # keep the original to measure against
    r = ns["loop_decimate"](ob, tol=0.0025, protect_uv=["UVMap"])  # texture UV only on a probe-lit piece
    ns["deviation"](dense, ob)                                      # {"max": ..., "p95": ..., "mean": ...} in metres

Greedy: of every edge loop that may go, remove the one that leaves the least sag, and repeat while it stays under
tol. A loop vertex's sag is its distance to the segment between its two neighbours across the loop, plus the sag
already removed next to it (so removing neighbouring loops one after another cannot add up past tol unseen).

A loop is never removed when any of its edges is a marked seam, a UV seam of a protected map, sharp, a material
boundary or open, or when it touches a triangle or an n-gon, or ends at an interior vertex of 3 edges (it would leave
a 2-edge vertex inside the surface). It may end at the rim (that vertex goes, sag-checked) or at a pole of 5 or more
edges (the pole stays). So the result stays clean quads, and every UV map keeps the corners it had on the vertices
kept: bakes and lightmap UVs made on protected maps stay valid. Run it before custom normals (Weighted Normal, Harden
Normals), which dissolving faces does not carry.
"""

import bmesh
import bpy
from mathutils.bvhtree import BVHTree

ERR_LAYER = "loop_decimate_err"


def _uv_layers(bm, protect_uv):
    if protect_uv in ("all", None):
        return list(bm.loops.layers.uv.values())
    out = []
    for key in ([protect_uv] if isinstance(protect_uv, (str, int)) else protect_uv):
        lay = (bm.loops.layers.uv.values()[key] if isinstance(key, int) and key < len(bm.loops.layers.uv)
               else bm.loops.layers.uv.get(key) if isinstance(key, str) else None)
        if lay is None:
            raise ValueError("no UV map %r to protect" % (key,))
        out.append(lay)
    return out


def _uv_split(e, uvs, eps=1e-6):
    """True where the two faces on edge e disagree on a UV at either end, on any of the maps uvs."""
    la, lb = e.link_loops
    for lay in uvs:
        for v in e.verts:
            ua = next(l for l in la.face.loops if l.vert == v)[lay].uv
            ub = next(l for l in lb.face.loops if l.vert == v)[lay].uv
            if (ua - ub).length > eps:
                return True
    return False


def _blocked(e, uvs):
    if len(e.link_faces) != 2 or e.seam or not e.smooth:
        return True
    fa, fb = e.link_faces
    if len(fa.verts) != 4 or len(fb.verts) != 4 or fa.material_index != fb.material_index:
        return True
    return _uv_split(e, uvs)


def _quad_vertex(v):
    """An interior vertex where 4 quads meet: a loop runs straight through it."""
    return not v.is_boundary and len(v.link_edges) == 4 and all(len(f.verts) == 4 for f in v.link_faces)


def _across(e, v):
    """The edge leaving v opposite e (shares no face with it), at a vertex where 4 quads meet."""
    faces = set(e.link_faces)
    for o in v.link_edges:
        if o is not e and not faces & set(o.link_faces):
            return o
    return None


def _walk(e):
    """The edge loop through e: (edges in order, its vertices in order, closed)."""
    edges, verts = [e], [e.verts[0], e.verts[1]]
    v, cur = e.verts[1], e
    while _quad_vertex(v):
        nxt = _across(cur, v)
        if nxt is e:
            return edges, verts[:-1], True                          # back at the start: verts[-1] is verts[0]
        if nxt is None:
            break
        edges.append(nxt)
        v = nxt.other_vert(v)
        verts.append(v)
        cur = nxt
    v, cur = e.verts[0], e
    while _quad_vertex(v):
        nxt = _across(cur, v)
        if nxt is None:
            break
        edges.insert(0, nxt)
        v = nxt.other_vert(v)
        verts.insert(0, v)
        cur = nxt
    return edges, verts, False


def _sag(v, a, b):
    """Distance of v from the segment a-b."""
    ab = b - a
    t = 0.0 if ab.length_squared < 1e-30 else max(0.0, min(1.0, (v - a).dot(ab) / ab.length_squared))
    return (v - (a + ab * t)).length


def _cost(edges, verts, closed, uvs, err):
    """The loop's cost (largest sag plus carried error), or None when it may not go."""
    faces = [f for e in edges for f in e.link_faces]
    in_loop = set(edges)
    if len(set(faces)) != len(faces):
        return None
    if any(_blocked(e, uvs) for e in edges):
        return None
    ends = [] if closed else [verts[0], verts[-1]]
    worst = 0.0
    for v in verts:
        others = [o for o in v.link_edges if o not in in_loop]
        if v in ends and len(others) != 2:
            if not v.is_boundary and len(v.link_edges) <= 3:
                return None                                         # an interior 3-edge end would keep 2 edges
            continue                                                # a pole: it stays
        if len(others) != 2:
            return None
        a, b = (o.other_vert(v).co for o in others)
        worst = max(worst, _sag(v.co, a, b) + v[err])
    return worst


def _loops(bm, uvs, err):
    seen, out = set(), []
    for e in bm.edges:
        if e in seen or len(e.link_faces) != 2:
            continue
        edges, verts, closed = _walk(e)
        seen.update(edges)
        c = _cost(edges, verts, closed, uvs, err)
        if c is not None:
            out.append((c, edges, verts))
    return out


def loop_decimate(ob, tol, protect_uv="all", max_loops=None):
    """Remove edge loops from ob's mesh (Object Mode, its own data, not the modifier result) while the sag each removal
    leaves, plus what earlier removals left next to it, stays within tol metres (object space). protect_uv: "all" (the
    default) keeps every UV map's seams, or a list of map names or indices: on a probe-lit piece whose lightmap UV has
    a chart per face, protect only the texture UV or nothing can go. max_loops: stop after that many. Returns
    loops_removed, faces_before, faces_after, tris_before, tris_after and worst (the largest cost accepted, m)."""
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    me = ob.data
    bm = bmesh.new()
    try:
        bm.from_mesh(me)
        err = bm.verts.layers.float.new(ERR_LAYER)                   # before any element is held: a layer added
        uvs = _uv_layers(bm, protect_uv)                            # later invalidates the Python references

        def tris():
            return sum(len(f.verts) - 2 for f in bm.faces)

        faces0, tris0 = len(bm.faces), tris()
        removed, worst = 0, 0.0
        while max_loops is None or removed < max_loops:
            cands = [c for c in _loops(bm, uvs, err) if c[0] <= tol]
            if not cands:
                break
            cost, edges, verts = min(cands, key=lambda c: c[0])
            in_loop = set(edges)
            for v in verts:                                         # carry the sag to the neighbours that stay
                for o in v.link_edges:
                    if o not in in_loop:
                        w = o.other_vert(v)
                        w[err] = max(w[err], cost)
            bmesh.ops.dissolve_edges(bm, edges=edges, use_verts=True)
            removed += 1
            worst = max(worst, cost)
        out = {"loops_removed": removed, "faces_before": faces0, "faces_after": len(bm.faces), "tris_before": tris0,
               "tris_after": tris(), "worst": worst}
        bm.verts.layers.float.remove(bm.verts.layers.float[ERR_LAYER])
        bm.to_mesh(me)
        me.update()
        return out
    finally:
        bm.free()


def deviation(dense, low, samples="verts"):
    """How far the low sits from the dense mesh: the distance from every dense vertex (samples="verts") or also every
    face centre ("faces") to the low's surface, in world space after modifiers. Returns max, p95 and mean (m). Judge
    it against the relief that still reads at the viewing distance (detail_scale.stereo_relief_m)."""
    dg = bpy.context.evaluated_depsgraph_get()
    le = low.evaluated_get(dg)
    lm = le.to_mesh()
    try:
        mw = le.matrix_world
        tree = BVHTree.FromPolygons([mw @ v.co for v in lm.vertices], [tuple(p.vertices) for p in lm.polygons])
    finally:
        le.to_mesh_clear()
    de = dense.evaluated_get(dg)
    dm = de.to_mesh()
    try:
        mw = de.matrix_world
        pts = [mw @ v.co for v in dm.vertices]
        if samples == "faces":
            pts += [mw @ p.center for p in dm.polygons]
    finally:
        de.to_mesh_clear()
    d = sorted(tree.find_nearest(p)[3] for p in pts)
    if not d:
        return {"max": 0.0, "p95": 0.0, "mean": 0.0}
    return {"max": d[-1], "p95": d[min(len(d) - 1, int(0.95 * len(d)))], "mean": sum(d) / len(d)}
