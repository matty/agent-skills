"""Bake mesh maps from high-poly meshes onto a low-poly mesh's UVs with Cycles: a tangent-space normal map (OpenGL
Y+, MikkTSpace tangents of the low poly as evaluated), ambient occlusion, and curvature (Pointiness through an
Emission bake). Rays start from a cage built from the low poly with averaged normals, so hard edges bake without
seams: one uniform push sized to enclose the high polys, or a fitted cage pushed per vertex (narrow channels,
concave creases, upholstery). Texels whose cage ray would still start inside a high (a thin part close to another
surface: no push works) are re-baked by resolve_faults() with back faces ignored, as the Toolbag and Substance bakers
do and Cycles cannot (on by default; --no-resolve). Each map bakes at `supersample` times the size, is Gaussian
pre-filtered and box-filtered down (normals renormalised), and is written as a 16-bit PNG (or 8-bit with dither),
data values, no colour management. Maps may be square or not (1024x2048).

Material transfer: basecolor, roughness and metallic copy what feeds each high poly's Principled BSDF (a generated
or scanned model's textures, a node material) onto the low through the same cage, as an Emission bake: basecolor is
written sRGB-encoded, roughness and metallic as one-channel data.

Host: Blender 4.2+ (bpy, Cycles and the bundled numpy), no add-ons; tested on Blender 5.2.2. Changes nothing it does
not restore: temporary images, materials, nodes and the cage are removed, render settings put back. Never saves the
.blend.

Command line (open the .blend that holds the meshes):
    blender -b --factory-startup crate.blend --python-exit-code 1 --python bake_maps.py --
            --low PROP_Crate_Free_A --high Crate_high --size 2048 --out blender/substance/PROP/bake
            --name T_PROP_Crate --maps normal,ao,curvature[,basecolor,roughness,metallic] [--size 1024x2048] [--cage fitted] [--supersample 2]
            [--filter-sigma 0.5] [--extrusion 0.02] [--margin 16] [--samples 64] [--ao-distance 0.2] [--bits 16]
            [--gpu] [--explode] [--no-resolve]
As a module (Blender MCP or another script):
    ns = {"BAKE_MAPS_NO_MAIN": True}; exec(open(path, encoding="utf-8").read(), ns)
    paths = ns["bake"](low, [high], maps=("normal", "ao"), size=1024, out_dir=..., name="T_PROP_Crate")
    paths = ns["bake"](low, highs, size=(1024, 2048), cage="fitted")         # per-vertex cage, a tall map
    paths = ns["bake_exploded"](low, ns["parts_by_name"](low, highs), size=1024, out_dir=...)  # parts close together

Output: <out_dir>/<name>_Normal.png, _AO.png, _Curvature.png (_BaseColor, _Roughness, _Metallic); returns {map: path} plus "report" (sizes, seconds, the
cage push and how far the high polys stand out, cage_inside, the curvature gain used), which the command line also
writes to <out_dir>/<name>_bake.json. The low poly bakes as it exports:
modifiers applied (keep its Triangulate on, so the baker and the engine see the same triangles), through its active
render UV layer unless uv_layer is given. The low and high polys must be in the view layer: an object in an excluded
or disabled collection is not evaluated, and its matrix_world is stale (identity after a load).
"""

import argparse
import json
import os
import struct
import sys
import time
import zlib

import bpy
import numpy as np

MAP_SUFFIX = {"normal": "Normal", "ao": "AO", "curvature": "Curvature",
              "basecolor": "BaseColor", "roughness": "Roughness", "metallic": "Metallic"}
NEUTRAL = {"normal": (0.5, 0.5, 1.0), "ao": (1.0, 1.0, 1.0), "curvature": (0.5, 0.5, 0.5),
           "basecolor": (0.5, 0.5, 0.5), "roughness": (0.5, 0.5, 0.5), "metallic": (0.0, 0.0, 0.0)}
# material transfer: the Principled BSDF input each map copies from the high polys' own materials
TRANSFER = {"basecolor": "Base Color", "roughness": "Roughness", "metallic": "Metallic"}
PNG_COLOUR = {1: 0, 2: 4, 3: 2, 4: 6}        # channels -> PNG colour type: grey, grey + alpha, RGB, RGBA
FILTER_SIGMA = 0.5       # Gaussian pre-filter, in output texels: a box filter alone steps thin sloped detail
CURVATURE_SATURATED = 0.05     # a curvature map with more of its texels clipped than this gets a note in the report
FITTED = {"safety": 1.15, "margin": 0.0015, "floor": 0.002, "min_cos": 0.5, "dilate": 2, "repair": 10}  # metres


# ---- helpers ------------------------------------------------------------------------------------------------------

def map_size(size):
    """(width, height) from 1024, (1024, 2048) or "1024x2048"."""
    if isinstance(size, str):
        w, _, h = size.lower().partition("x")
        w, h = int(w), int(h or w)
    elif isinstance(size, (tuple, list)):
        w, h = int(size[0]), int(size[1])
    else:
        w = h = int(size)
    if w < 1 or h < 1:
        raise ValueError("a map must be at least 1 px across, not %r" % (size,))
    return w, h


def _require_evaluated(objs, depsgraph):
    """Refuse objects the depsgraph does not evaluate (in an excluded collection, or a collection or object disabled
    in viewports): their modifiers are not applied and matrix_world is stale, identity after a load."""
    bad = [o.name for o in objs if not o.evaluated_get(depsgraph).is_evaluated]
    if bad:
        raise ValueError("%s not evaluated in this view layer (an excluded collection, or disabled in viewports): "
                         "include them for the bake" % ", ".join(bad))


def make_cage(low, extrusion, depsgraph=None):
    """A cage object: the low poly as evaluated (same triangles as the bake), every vertex pushed out along its
    averaged normal by `extrusion`: one number, or one per vertex of the evaluated mesh (fitted_cage_extrusions).
    Object space; metres on a kit piece at scale 1. Averaged normals keep the rays continuous across hard edges;
    rays that follow split normals leave a seam along every hard edge."""
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    ev = low.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev)
    me.name = low.name + "_bake_cage"
    n = len(me.vertices)
    push = np.broadcast_to(np.asarray(extrusion, np.float64), (n,)) if np.ndim(extrusion) == 0 else \
        np.asarray(extrusion, np.float64)
    if push.shape != (n,):
        bpy.data.meshes.remove(me)
        raise ValueError("%d cage pushes for %d vertices" % (push.size, n))
    co = np.empty(n * 3, np.float32)
    nrm = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    me.vertices.foreach_get("normal", nrm)          # the vertex (averaged) normal, whatever the sharp edges
    me.vertices.foreach_set("co", (co.reshape(-1, 3) + nrm.reshape(-1, 3) * push[:, None]).astype(np.float32).ravel())
    me.update()
    cage = bpy.data.objects.new(me.name, me)
    cage.matrix_world = low.matrix_world.copy()
    bpy.context.scene.collection.objects.link(cage)
    return cage


def _low_mesh(low, dg):
    """The evaluated low poly: vertices, averaged vertex normals, polygons as vertex tuples, face normals, each
    polygon's per-corner cosine between its corners' vertex normals and its own normal, and the edges."""
    ev = low.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        nv, nf = len(me.vertices), len(me.polygons)
        co, vn, fn = np.empty(nv * 3, np.float32), np.empty(nv * 3, np.float32), np.empty(nf * 3, np.float32)
        me.vertices.foreach_get("co", co)
        me.vertices.foreach_get("normal", vn)
        me.polygons.foreach_get("normal", fn)
        edges = np.empty(len(me.edges) * 2, np.int64)
        me.edges.foreach_get("vertices", edges)
        polys = [tuple(p.vertices) for p in me.polygons]
    finally:
        ev.to_mesh_clear()
    co, vn, fn = co.reshape(-1, 3).astype(np.float64), vn.reshape(-1, 3).astype(np.float64), fn.reshape(-1, 3)
    cosines = [np.asarray([vn[i] @ fn[k] for i in p]) for k, p in enumerate(polys)]
    return {"co": co, "vn": vn, "fn": fn.astype(np.float64), "polys": polys, "cos": cosines,
            "edges": edges.reshape(-1, 2)}


def _high_points(low, highs, dg, max_samples, seed=0):
    """Points of the high polys in the low poly's object space, per object: at most max_samples of its vertices (an
    even stride) and as many points spread over its triangles by area (a sparse high, a plain box, has no vertex
    over the middle of its big faces)."""
    to_low = np.array(low.matrix_world.inverted())
    rng = np.random.default_rng(seed)
    out = []
    for h in highs:
        hev = h.evaluated_get(dg)
        hme = hev.to_mesh()
        try:
            hme.calc_loop_triangles()
            n, nt = len(hme.vertices), len(hme.loop_triangles)
            co = np.empty(n * 3, np.float32)
            hme.vertices.foreach_get("co", co)
            tris = np.empty(nt * 3, np.int64)
            hme.loop_triangles.foreach_get("vertices", tris)
        finally:
            hev.to_mesh_clear()
        co = co.reshape(-1, 3).astype(np.float64)
        pts = [co[::max(1, n // max(1, max_samples))]]
        if nt:
            a, b, c = (co[tris.reshape(-1, 3)[:, k]] for k in range(3))
            area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
            if area.sum() > 0.0:
                pick = rng.choice(nt, size=max_samples, p=area / area.sum())
                r1, r2 = rng.random(max_samples), rng.random(max_samples)
                s = np.sqrt(r1)[:, None]
                pts.append(a[pick] * (1.0 - s) + b[pick] * (s * (1.0 - r2[:, None])) + c[pick] * (s * r2[:, None]))
        m = to_low @ np.array(h.matrix_world)
        p = np.concatenate(pts)
        out.append(p @ m[:3, :3].T + m[:3, 3])
    return np.concatenate(out) if out else np.zeros((0, 3))


def protrusion(low, highs, depsgraph=None, max_samples=20000):
    """How far the high polys stand outside the low poly. For each sampled point of the highs (_high_points): its
    signed distance from the nearest low face along that face's normal (positive outside), the face's index and the
    point's weights on that face's corners. Returns (samples [(distance, face, weights)], the low mesh as _low_mesh
    gives it, the low BVH)."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from mathutils.interpolate import poly_3d_calc
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    _require_evaluated([low] + list(highs), dg)
    lm = _low_mesh(low, dg)
    verts = [Vector(c) for c in lm["co"]]
    bvh = BVHTree.FromPolygons(verts, lm["polys"])
    samples = []
    for c in _high_points(low, highs, dg, max_samples):
        p = Vector(c)
        loc, nrm, fi, _d = bvh.find_nearest(p)
        if loc is None:
            continue
        w = poly_3d_calc([verts[i] for i in lm["polys"][fi]], loc)
        samples.append(((p - loc).dot(nrm), fi, w))
    return samples, lm, bvh


def _percentiles(values):
    v = np.asarray(values, np.float64)
    if not v.size:
        return {"p50": 0.0, "p99": 0.0, "max": 0.0}
    return {"p50": float(np.percentile(v, 50)), "p99": float(np.percentile(v, 99)), "max": float(v.max())}


def cage_extrusion(low, highs, depsgraph=None, safety=1.1, max_samples=20000, stats=None):
    """The uniform cage push that encloses the high polys: for every sampled high point outside the low surface, its
    distance along the nearest low face's normal divided by the share of a push along the averaged normals that
    moves that point of the face out (its corners' cosines between vertex normal and face normal, weighted by where
    the point lies: 0.577 on a cube's faces, about 1 on smooth upholstery); the largest of those, times safety. Per
    point, so one sharp corner no longer inflates the push for the whole mesh (a global minimum cosine made it
    2-3x too deep on upholstery lows). Returns (extrusion, outside distance), both in the low poly's object space.
    stats (a dict) receives the protrusion's p50, p99 and max. A cage that does not enclose the high poly starts
    rays inside it: protruding detail bakes as rings and its AO comes out black. One that reaches a neighbouring
    surface starts rays inside that: use fitted_cage_extrusions for channels and creases."""
    samples, lm, _bvh = protrusion(low, highs, depsgraph, max_samples)
    out = [d for d, _f, _w in samples if d > 0.0]
    need = [d / max(float(np.dot(w, lm["cos"][f])), 0.1) for d, f, w in samples if d > 0.0]
    if stats is not None:
        stats.update(_percentiles(out))
    return (max(need) if need else 0.0) * safety, (max(out) if out else 0.0)


def _high_bvhs(low, highs, dg):
    """[(BVH of the evaluated high in its own object space, low-to-high matrix, its 3 x 3 inverse transposed)]."""
    from mathutils import Matrix
    from mathutils.bvhtree import BVHTree
    out = []
    for h in highs:
        to_high = Matrix(h.matrix_world).inverted() @ Matrix(low.matrix_world)
        out.append((BVHTree.FromObject(h, dg), to_high, to_high.to_3x3().inverted().transposed()))
    return out


def _ray_hits(bvhs, origin, direction, limit, first=False, max_hits=64):
    """The hits of a ray (low-poly object space, unit direction) through the high polys within limit, nearest
    first: [(distance, entering?)], entering when the surface faces against the ray. first=True stops each high at
    its first hit."""
    hits = []
    eps = 1e-6
    for bvh, m, mn in bvhs:
        o0 = m @ origin
        d = m @ (origin + direction) - o0                         # one low-poly unit along the ray
        dn, scale = d.normalized(), d.length
        cur, t = o0, 0.0
        for _ in range(max_hits):
            loc, nrm, _i, _dist = bvh.ray_cast(cur + dn * eps, dn, (limit - t) * scale + eps)
            if loc is None:
                break
            t = (loc - o0).dot(dn) / scale
            if t > limit:
                break
            hits.append((t, (mn @ nrm).dot(direction) < 0.0))
            if first:
                break
            cur = loc
    hits.sort()
    return hits[:1] if first else hits


CAGE_SAMPLES = np.array([(1 / 3.0, 1 / 3.0, 1 / 3.0), (0.75, 0.125, 0.125), (0.125, 0.75, 0.125),
                         (0.125, 0.125, 0.75), (0.5, 0.5, 0.0), (0.0, 0.5, 0.5), (0.5, 0.0, 0.5)])


def _cage_faults(lm, push, bvhs, reach, bad=None):
    """The bake's own rays traced at seven points of every cage triangle (polygons fanned), as Cycles casts them:
    from the cage point towards the low point at the same barycentric position, nearest hit. A ray whose first hit
    is the inside of a surface starts inside a high: inside one that stands off the low surface when the hit comes
    before the low point (a neighbour across a channel or crease: the cage reaches too far), inside the low's own
    high when it comes after (the cage is too small). Returns (triangles with a ray of the first kind, of the second,
    rays of the first kind, of the second, rays traced). bad (a set) receives the index of every polygon with a ray of
    either kind."""
    from mathutils import Vector
    vn = lm["vn"] / np.maximum(np.linalg.norm(lm["vn"], axis=1, keepdims=True), 1e-12)
    cage = lm["co"] + vn * np.asarray(push, np.float64)[:, None]
    across, short = [], []
    n_across = n_short = rays = 0
    for pi, p in enumerate(lm["polys"]):
        for k in range(1, len(p) - 1):
            tri = [p[0], p[k], p[k + 1]]
            kinds = set()
            for w in CAGE_SAMPLES:
                low_pt, cage_pt = w @ lm["co"][tri], w @ cage[tri]
                d = low_pt - cage_pt
                dist = float(np.linalg.norm(d))
                if dist < 1e-9:
                    continue
                rays += 1
                hit = _ray_hits(bvhs, Vector(cage_pt), Vector(d / dist), reach, first=True)
                if not hit or hit[0][1]:
                    continue
                if hit[0][0] < dist:
                    kinds.add("across")
                    n_across += 1
                else:
                    kinds.add("short")
                    n_short += 1
            if kinds and bad is not None:
                bad.add(pi)
            if "across" in kinds:
                across.append(tri)
            if "short" in kinds:
                short.append(tri)
    return across, short, n_across, n_short, rays


def cage_faults(low, highs, pushes, depsgraph=None):
    """Trace the bake's rays from a cage (the low poly's vertices pushed out by `pushes`: one number or one per
    vertex) at seven points of every triangle, and count the ones that start inside a high poly: {"neighbour": inside
    a high standing off the low (the cage reaches across a channel or crease: normals pointing into the surface),
    "own": inside the low's own high (the cage is too small: rings, black AO), "rays": rays traced}."""
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    lm = _low_mesh(low, dg)
    push = np.broadcast_to(np.asarray(pushes, np.float64), (len(lm["co"]),))
    _a, _s, n_across, n_short, rays = _cage_faults(lm, push, _high_bvhs(low, highs, dg),
                                                   1e3 * max(low.dimensions.length, 1.0))
    return {"neighbour": n_across, "own": n_short, "rays": rays}


def fitted_cage_extrusions(low, highs, depsgraph=None, max_samples=200000, report=None, reference_size=None,
                           **settings):
    """A cage push per vertex of the evaluated low poly, for pieces where no single push works: narrow channels
    (a channel-tufted back: a cage deep enough for one pad starts rays inside the next), concave creases, and pieces
    whose high stands far off in places and close in others.
    1. Requirement: for each high point sampled, its distance outside the nearest low face divided by
       max(min_cos, the cosine between a corner's vertex normal and the face) for each corner of that face; per
       vertex the largest, x safety + margin, at least floor, then dilated `dilate` times over the edges so the
       cage covers the space between vertices.
    2. March: a ray from the vertex along its normal through the highs, as far as twice the largest requirement.
       Each exit from a high moves the last exit, and the push is at least the last exit x safety + margin (the
       samples miss the middle of a sparse high's big faces). An entry whose nearest low surface faces back along
       the ray is the other side of a channel or crease: the push is capped at half way from the last exit to it.
       Detail standing on the vertex's own side (piping on a cushion, floaters) is marched through.
    3. Repair: the bake's own rays traced at seven points of every cage triangle (_cage_faults). Between a capped
       vertex and an uncapped one a cage face can still cut into a neighbour. In a triangle with a ray starting
       inside a high that stands off the low, its largest push shrinks (x 0.8, not under the vertex's last exit);
       in one with a ray starting inside its own high, its smallest push grows (x 1.25, not over its cap); up to
       `repair` rounds.
    settings override FITTED (safety 1.15, margin 1.5 mm, floor 2 mm, min_cos 0.5, dilate 2, repair 10; metres at
    scale 1). Returns a numpy array of pushes; report (a dict) receives min, max, mean, how many were capped and
    repaired, and the rays still starting inside a high ("faults", as cage_faults gives them)."""
    from mathutils import Vector
    cfg = dict(FITTED, **settings)
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    samples, lm, low_bvh = protrusion(low, highs, dg, max_samples)
    nv = len(lm["co"])
    req = np.zeros(nv)
    for d, f, _w in samples:
        if d <= 0.0:
            continue
        p = lm["polys"][f]
        need = d / np.maximum(lm["cos"][f], cfg["min_cos"])
        np.maximum.at(req, list(p), need)
    req = np.maximum(req * cfg["safety"] + cfg["margin"], cfg["floor"])
    e0, e1 = lm["edges"][:, 0], lm["edges"][:, 1]
    for _ in range(int(cfg["dilate"])):
        grown = req.copy()
        np.maximum.at(grown, e0, req[e1])
        np.maximum.at(grown, e1, req[e0])
        req = grown
    bvhs = _high_bvhs(low, highs, dg)
    push = req.copy()
    lower, upper = np.zeros(nv), np.full(nv, np.inf)            # per vertex: its own last exit, its cap
    capped = 0
    size = float(reference_size) if reference_size else low.dimensions.length
    reach = max(2.0 * float(req.max()) if nv else 0.0, 0.02 * size)   # sparse highs: gaps in samples
    for v in range(nv):
        origin, direction = Vector(lm["co"][v]), Vector(lm["vn"][v]).normalized()
        last_exit, cap = 0.0, None
        for t, entering in _ray_hits(bvhs, origin, direction, reach):
            if not entering:
                last_exit = t
                continue
            _loc, n_near, _i, _dist = low_bvh.find_nearest(origin + direction * t)
            if n_near is not None and n_near.dot(direction) < 0.0:
                cap = 0.5 * (last_exit + t)
                break
        want = max(req[v], last_exit * cfg["safety"] + cfg["margin"])
        lower[v] = last_exit
        if cap is not None:
            upper[v] = cap
        if cap is not None and cap < want:
            push[v] = cap
            capped += 1
        else:
            push[v] = want
    far = 1e3 * max(low.dimensions.length, 1.0)                 # the bake's rays have no length limit
    repaired = np.zeros(nv, bool)
    for rnd in range(int(cfg["repair"]) + 1):
        across, short, n_across, n_short, rays = _cage_faults(lm, push, bvhs, far)
        if not (n_across or n_short) or rnd == int(cfg["repair"]):
            break
        shrink = np.zeros(nv, bool)
        grow = np.zeros(nv, bool)
        for tri in across:
            shrink[max(tri, key=lambda i: push[i])] = True
        for tri in short:
            grow[min(tri, key=lambda i: push[i])] = True
        grow &= ~shrink
        push[shrink] = np.maximum(push[shrink] * 0.8, lower[shrink])
        push[grow] = np.minimum(push[grow] * 1.25, upper[grow])
        repaired |= shrink | grow
    if report is not None:
        st = _percentiles([d for d, _f, _w in samples if d > 0.0])
        report.update({"min": float(push.min()) if nv else 0.0, "max": float(push.max()) if nv else 0.0,
                       "mean": float(push.mean()) if nv else 0.0, "capped": int(capped),
                       "repaired": int(repaired.sum()), "high_outside": st["max"], "high_outside_p99": st["p99"],
                       "faults": {"neighbour": n_across, "own": n_short, "rays": rays}})
    return push


def _gauss_axis(a, sigma, axis):
    r = int(np.ceil(3.0 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k = (k / k.sum()).astype(a.dtype)
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    p = np.pad(a, pad, mode="edge")
    out = np.zeros_like(a)
    n = a.shape[axis]
    for i, kv in enumerate(k):
        out += kv * np.take(p, np.arange(i, i + n), axis=axis)
    return out


def downsample(a, f, sigma=FILTER_SIGMA):
    """A (height, width, channels) bake at f times the output size down to the output size: a Gaussian of sigma
    output texels (sigma x f samples) over the supersampled image, then a box filter over each f x f block. A box
    filter alone steps thin detail that runs at a slight slope to the texel grid (baked piping read as a dashed line),
    whatever the supersample: measured on a sloped edge, its position error barely moved from 2x to 4x (0.072 to
    0.065 texels rms), while sigma 0.5 cut it to 0.043 (edge 1.5 texels wide) and 0.8 to 0.030 (2.2 texels)."""
    if sigma and sigma > 0.0:
        s = float(sigma) * max(int(f), 1)
        a = _gauss_axis(_gauss_axis(a, s, 0), s, 1)
    if f <= 1:
        return a
    h, w = a.shape[0] // f, a.shape[1] // f
    return a[:h * f, :w * f].reshape(h, f, w, f, a.shape[2]).mean(axis=(1, 3))


def _image_array(img):
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)[::-1].copy()          # rows top to bottom


def save_png(path, rgb, bits=16, seed=0):
    """Write a float (height, width, channels) array in 0-1, rows top to bottom (as _image_array returns them;
    Blender's Image.pixels run bottom to top, and writing them unflipped turns the map upside down), as a PNG of 1
    (grey), 2 (grey + alpha), 3 (RGB) or 4 (RGBA) channels: 16 bits per channel, or 8 with triangular dither so
    smooth gradients do not band."""
    a = np.clip(np.asarray(rgb, np.float64), 0.0, 1.0)
    if a.ndim == 2:
        a = a[:, :, None]
    h, w, ch = a.shape
    if ch not in PNG_COLOUR:
        raise ValueError("save_png writes 1-4 channels, not %d" % ch)
    if bits == 16:
        codes = np.round(a * 65535.0).astype(">u2")
    else:
        rng = np.random.default_rng(seed)
        noise = rng.random(a.shape) - rng.random(a.shape)       # triangular, -1..1 LSB
        codes = np.clip(np.round(a * 255.0 + noise * 0.5), 0, 255).astype(np.uint8)
    raw = b"".join(b"\x00" + codes[y].tobytes() for y in range(h))

    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, bits, PNG_COLOUR[ch], 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    return path


def _active_image_nodes(obj, img):
    """Give every material of obj an active Image Texture node holding img (the bake target); returns an undo list."""
    undo = []
    if not obj.material_slots or all(s.material is None for s in obj.material_slots):
        mat = bpy.data.materials.new("bake_tmp_material")
        mat.use_nodes = True
        if not obj.material_slots:
            obj.data.materials.append(mat)
            undo.append(("pop_slot", obj))
        else:
            for s in obj.material_slots:
                s.material = mat
            undo.append(("clear_slots", obj))
        undo.append(("material", mat))
    for s in obj.material_slots:
        mat = s.material
        if mat is None:
            continue
        mat.use_nodes = True
        nt = mat.node_tree
        prev = nt.nodes.active
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = img
        node.select = True
        nt.nodes.active = node
        undo.append(("node", mat, node, prev))
    return undo


def _undo(undo):
    for item in reversed(undo):
        kind = item[0]
        if kind == "node":
            _k, mat, node, prev = item
            mat.node_tree.nodes.remove(node)
            if prev is not None:
                mat.node_tree.nodes.active = prev
        elif kind == "pop_slot":
            item[1].data.materials.pop()
        elif kind == "clear_slots":
            for s in item[1].material_slots:
                s.material = None
        elif kind == "material":
            bpy.data.materials.remove(item[1])


def _pointiness_materials(highs):
    """Swap every material of the high polys for an Emission of Cycles' Pointiness (raw, 0.5 on flat surfaces)."""
    mat = bpy.data.materials.new("bake_tmp_pointiness")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    emi = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(geo.outputs["Pointiness"], emi.inputs["Color"])
    nt.links.new(emi.outputs["Emission"], out.inputs["Surface"])
    saved = []
    for h in highs:
        mats = [s.material for s in h.material_slots]
        saved.append((h, mats))
        if not h.material_slots:
            h.data.materials.append(mat)
        else:
            for s in h.material_slots:
                s.material = mat
    return mat, saved


def _transfer_materials(highs, socket_name):
    """Swap each high-poly material for a copy whose surface is an Emission of what feeds its Principled BSDF's
    `socket_name` input (a texture, a node chain or the plain value), so an EMIT bake copies it onto the low.
    Returns (temporary materials, saved slots, notes); a material with no Principled BSDF bakes the neutral value."""
    temps, saved, notes, made = [], [], [], {}
    for h in highs:
        mats = [s.material for s in h.material_slots]
        saved.append((h, mats))
        for s in h.material_slots:
            src = s.material
            if src is None:
                continue
            if src.name not in made:
                m = src.copy()
                m.name = "bake_tmp_%s_%s" % (socket_name.replace(" ", ""), src.name)
                temps.append(m)
                made[src.name] = m
                nt = m.node_tree
                bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None) if nt else None
                out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)                     if nt else None
                if nt and out is None:
                    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
                if bsdf is None or out is None:
                    notes.append("%s: no Principled BSDF in material %s; baked the neutral value" % (socket_name, src.name))
                    m.use_nodes = True
                    nt = m.node_tree
                    nt.nodes.clear()
                    out = nt.nodes.new("ShaderNodeOutputMaterial")
                    emi = nt.nodes.new("ShaderNodeEmission")
                    emi.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1.0)
                    nt.links.new(emi.outputs["Emission"], out.inputs["Surface"])
                    continue
                emi = nt.nodes.new("ShaderNodeEmission")
                emi.inputs["Strength"].default_value = 1.0
                sock = bsdf.inputs[socket_name]
                if sock.is_linked:
                    nt.links.new(sock.links[0].from_socket, emi.inputs["Color"])
                else:
                    v = sock.default_value
                    emi.inputs["Color"].default_value = tuple(v) if hasattr(v, "__len__") else (v, v, v, 1.0)
                for l in list(out.inputs["Surface"].links):
                    nt.links.remove(l)
                nt.links.new(emi.outputs["Emission"], out.inputs["Surface"])
            s.material = made[src.name]
    return temps, saved, notes


def _linear_to_srgb(a):
    a = np.clip(a, 0.0, 1.0)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * np.power(a, 1.0 / 2.4) - 0.055)


def _restore_materials(mat, saved):
    for h, mats in saved:
        if not mats:
            h.data.materials.pop()
        else:
            for s, m in zip(h.material_slots, mats):
                s.material = m
    bpy.data.materials.remove(mat)


# ---- resolving the texels a cage cannot bake ------------------------------------------------------------------------
# Cycles casts one ray per texel from the cage to the low and keeps its first hit, back faces included; it has no
# "ignore back faces" switch (Toolbag and Painter have one). Where a thin part sits close to another surface (a
# handle by its body, legs under a pot) no single push works: far enough to clear the part's own high puts the cage
# inside its neighbour's. resolve_faults() re-casts those texels itself, the way those bakers do: a window along the
# averaged normal from the cage (front) to the same distance behind the low (rear), back faces stepped over, and the
# first front-facing hit wins.
RESOLVE = {"rear": 1.0, "retry": 3.0, "ao_rays": 24, "edge_px": 1.0, "grow": 1, "detect": True}


def _srgb_to_linear(a):
    a = np.clip(a, 0.0, 1.0)
    return np.where(a <= 0.04045, a / 12.92, np.power((a + 0.055) / 1.055, 2.4))


def _socket_source(mat, socket_name):
    """What feeds a Principled BSDF input, in a form the resolver can sample: ("value", rgb), ("image", image, UV layer
    name or None, channel index or None), or None for anything else (a node chain: those texels keep the Cycles value).
    Follows a glTF import's Image Texture -> Separate Color for roughness and metallic."""
    nt = mat.node_tree if mat is not None and mat.use_nodes else None
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None) if nt else None
    if bsdf is None:
        return ("value", (0.5, 0.5, 0.5))
    sock = bsdf.inputs[socket_name]
    if not sock.is_linked:
        v = sock.default_value
        return ("value", tuple(v)[:3] if hasattr(v, "__len__") else (v, v, v))
    link = sock.links[0]
    node, channel = link.from_node, None
    if node.type in ("SEPARATE_COLOR", "SEPRGB") and getattr(node, "mode", "RGB") == "RGB":
        channel = [o.name for o in node.outputs].index(link.from_socket.name)
        if not node.inputs[0].is_linked:
            return None
        node = node.inputs[0].links[0].from_node
    if node.type != "TEX_IMAGE" or node.image is None:
        return None
    vec = node.inputs["Vector"]
    uv = None
    if vec.is_linked:
        src = vec.links[0].from_node
        if src.type != "UVMAP":
            return None
        uv = src.uv_map or None
    return ("image", node.image, uv, channel)


class _Highs:
    """The high polys as evaluated, in the low's object space, as one BVH over their loop triangles, with what the
    resolver shades from: corner normals, material slots and UV layers."""

    def __init__(self, low, highs, dg):
        from mathutils import Matrix
        from mathutils.bvhtree import BVHTree
        cos, tris, self.parts = [], [], []
        nverts = ntris = 0
        inv_low = Matrix(low.matrix_world).inverted()
        for h in highs:
            ev = h.evaluated_get(dg)
            me = ev.to_mesh()
            try:
                m = np.array(inv_low @ Matrix(ev.matrix_world))
                nv, nl = len(me.vertices), len(me.loops)
                co = np.empty(nv * 3, np.float32)
                me.vertices.foreach_get("co", co)
                co = co.reshape(-1, 3).astype(np.float64) @ m[:3, :3].T + m[:3, 3]
                me.calc_loop_triangles()
                nt = len(me.loop_triangles)
                tv, tl, tm = np.empty(nt * 3, np.int64), np.empty(nt * 3, np.int64), np.empty(nt, np.int64)
                me.loop_triangles.foreach_get("vertices", tv)
                me.loop_triangles.foreach_get("loops", tl)
                me.loop_triangles.foreach_get("material_index", tm)
                cn = np.empty(nl * 3, np.float32)
                me.corner_normals.foreach_get("vector", cn)
                cn = cn.reshape(-1, 3).astype(np.float64) @ np.linalg.inv(m[:3, :3])
                cn /= np.maximum(np.linalg.norm(cn, axis=1, keepdims=True), 1e-12)
                uvs = {}
                for lay in me.uv_layers:
                    a = np.empty(nl * 2, np.float32)
                    lay.uv.foreach_get("vector", a)
                    uvs[lay.name] = a.reshape(-1, 2).astype(np.float64)
                render = next((l.name for l in me.uv_layers if l.active_render), None)
                self.parts.append({"object": h, "start": ntris, "tl": tl.reshape(-1, 3), "mat": tm, "cn": cn,
                                   "uv": uvs, "uv_default": render, "mats": [s.material for s in h.material_slots]})
                tris.append(tv.reshape(-1, 3) + nverts)
                cos.append(co)
                nverts += nv
                ntris += nt
            finally:
                ev.to_mesh_clear()
        self.co = np.vstack(cos)
        self.tri = np.vstack(tris)
        self.starts = np.array([p["start"] for p in self.parts] + [ntris])
        self.bvh = BVHTree.FromPolygons([tuple(c) for c in self.co], [tuple(int(i) for i in t) for t in self.tri])
        e1 = self.co[self.tri[:, 1]] - self.co[self.tri[:, 0]]
        e2 = self.co[self.tri[:, 2]] - self.co[self.tri[:, 0]]
        fn = np.cross(e1, e2)
        self.fn = fn / np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-20)

    def locate(self, f):
        k = int(np.searchsorted(self.starts, f, side="right") - 1)
        return k, f - self.parts[k]["start"]

    def bary(self, f, p):
        a, b, c = self.co[self.tri[f]]
        v0, v1, v2 = b - a, c - a, p - a
        d00, d01, d11, d20, d21 = v0 @ v0, v0 @ v1, v1 @ v1, v2 @ v0, v2 @ v1
        den = d00 * d11 - d01 * d01
        if abs(den) < 1e-30:
            return np.array([1.0, 0.0, 0.0])
        v = (d11 * d20 - d01 * d21) / den
        w = (d00 * d21 - d01 * d20) / den
        bc = np.clip(np.array([1.0 - v - w, v, w]), 0.0, 1.0)
        return bc / max(bc.sum(), 1e-12)

    def cast(self, origin, direction, length):
        """The front-facing hits (facing against the ray) along a ray within length, back faces stepped over:
        [(t, triangle)]."""
        from mathutils import Vector
        out, t = [], 0.0
        o, d = Vector(origin), Vector(direction)
        for _ in range(64):
            loc, _n, f, _dist = self.bvh.ray_cast(o + d * (t + 1e-7), d, max(length - t, 0.0))
            if loc is None:
                break
            t = (loc - o).dot(d)
            if float(self.fn[f] @ direction) < 0.0:
                out.append((t, f))
        return out

    def occluded(self, origin, direction, length):
        from mathutils import Vector
        return self.bvh.ray_cast(Vector(origin), Vector(direction), length)[0] is not None


def _sample_image(cache, img, uv, channel):
    """Bilinear, wrapping, in linear light for an sRGB 8-bit image (as Cycles reads it)."""
    if img.name not in cache:
        w, h = img.size
        px = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(h, w, 4)[:, :, :3].astype(np.float64)
        if img.colorspace_settings.name == "sRGB" and not img.is_float:
            px = _srgb_to_linear(px)
        cache[img.name] = px
    px = cache[img.name]
    h, w = px.shape[:2]
    x, y = (uv[0] % 1.0) * w - 0.5, (uv[1] % 1.0) * h - 0.5
    x0, y0 = int(np.floor(x)), int(np.floor(y))
    fx, fy = x - x0, y - y0
    x0, x1, y0, y1 = x0 % w, (x0 + 1) % w, y0 % h, (y0 + 1) % h
    v = (px[y0, x0] * (1 - fx) * (1 - fy) + px[y0, x1] * fx * (1 - fy) + px[y1, x0] * (1 - fx) * fy
         + px[y1, x1] * fx * fy)
    return np.full(3, v[channel]) if channel is not None else v


def _low_loops(low, dg, uv_layer):
    """The evaluated low poly's loop triangles with corner UVs, corner normals and MikkTSpace tangents (the frame of
    Cycles' tangent-space normal bake); tangent None when the mesh has n-gons."""
    ev = low.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        name = uv_layer or next((l.name for l in me.uv_layers if l.active_render), None)
        if name is None or name not in me.uv_layers:
            raise ValueError("%s has no UV layer %r to bake into" % (low.name, name))
        nl = len(me.loops)
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        tl, tp = np.empty(nt * 3, np.int64), np.empty(nt, np.int64)
        me.loop_triangles.foreach_get("loops", tl)
        me.loop_triangles.foreach_get("polygon_index", tp)
        lv = np.empty(nl, np.int64)
        me.loops.foreach_get("vertex_index", lv)
        uv = np.empty(nl * 2, np.float32)
        me.uv_layers[name].uv.foreach_get("vector", uv)
        tangent = sign = None
        try:
            me.calc_tangents(uvmap=name)
            tangent, sign = np.empty(nl * 3, np.float32), np.empty(nl, np.float32)
            me.loops.foreach_get("tangent", tangent)
            me.loops.foreach_get("bitangent_sign", sign)
            tangent = tangent.reshape(-1, 3).astype(np.float64)
        except RuntimeError:
            tangent = sign = None
        cn = np.empty(nl * 3, np.float32)
        me.corner_normals.foreach_get("vector", cn)
        return {"tl": tl.reshape(-1, 3), "tp": tp, "lv": lv, "uv": uv.reshape(-1, 2).astype(np.float64),
                "cn": cn.reshape(-1, 3).astype(np.float64), "tangent": tangent, "sign": sign}
    finally:
        ev.to_mesh_clear()


def _rasterise(uv_tri, w, h, edge_px):
    """Texels (column, row with rows top to bottom, as _image_array) whose centre lies in a UV triangle grown by
    edge_px texels, and their barycentric weights clamped to the triangle."""
    p = uv_tri * np.array([w, h], np.float64) - 0.5            # texel centres at whole numbers, rows bottom up
    lo = np.maximum(np.floor(p.min(0) - edge_px).astype(int), 0)
    hi = np.minimum(np.ceil(p.max(0) + edge_px).astype(int), [w - 1, h - 1])
    a, b, c = p
    den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if (hi < lo).any() or abs(den) < 1e-12:
        return np.zeros((0, 2), int), np.zeros((0, 3))
    xs, ys = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1))
    q = np.stack([xs.ravel(), ys.ravel()], 1).astype(np.float64)
    l1 = ((b[1] - c[1]) * (q[:, 0] - c[0]) + (c[0] - b[0]) * (q[:, 1] - c[1])) / den
    l2 = ((c[1] - a[1]) * (q[:, 0] - c[0]) + (a[0] - c[0]) * (q[:, 1] - c[1])) / den
    bary = np.stack([l1, l2, 1.0 - l1 - l2], 1)
    # how far outside each edge, in texels: the weight's deficit x that corner's height over the opposite edge
    heights = np.array([abs(den) / max(np.linalg.norm(e1 - e0), 1e-12) for e0, e1 in ((b, c), (c, a), (a, b))])
    keep = (np.minimum(bary, 0.0) * heights).min(1) >= -edge_px
    bary = np.clip(bary[keep], 0.0, None)
    bary /= np.maximum(bary.sum(1, keepdims=True), 1e-12)
    pix = q[keep].astype(int)
    pix[:, 1] = h - 1 - pix[:, 1]
    return pix, bary


def _inward_polygons(low, highs, cage, w, h, uv_layer, dg):
    """The low polygons where Cycles' own normal bake (1 sample, no margin) points into the surface (tangent z < 0):
    the faults the seven sampled cage rays per triangle miss, read off the result instead of predicted. A texel that
    points inward because the high really turns that far is re-baked to the same value, so taking it costs only
    time. Needs the bake's selection and visibility already set up (bake() calls it)."""
    scene = bpy.context.scene
    img = bpy.data.images.new("bake_tmp_detect", w, h, alpha=False, float_buffer=True)
    img.colorspace_settings.name = "Non-Color"
    img.pixels.foreach_set(np.tile(np.array((0.5, 0.5, 1.0, 1.0), np.float32), w * h))
    undo = _active_image_nodes(low, img)
    keep = scene.cycles.samples
    try:
        bpy.ops.object.select_all(action="DESELECT")
        for hobj in highs:
            hobj.select_set(True)
        low.select_set(True)
        bpy.context.view_layer.objects.active = low
        scene.cycles.samples = 1
        bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", normal_r="POS_X", normal_g="POS_Y",
                            normal_b="POS_Z", use_selected_to_active=True, use_cage=True, cage_object=cage.name,
                            max_ray_distance=0.0, margin=0, target="IMAGE_TEXTURES", use_clear=False,
                            uv_layer=uv_layer or "")
        z = _image_array(img)[:, :, 2]
    finally:
        scene.cycles.samples = keep
        _undo(undo)
        bpy.data.images.remove(img)
    pid = _uv_polygons(_low_loops(low, dg, uv_layer), w, h)
    hit = pid[(z < 0.5) & (pid >= 0)]                          # stored as (n + 1) / 2: z < 0 reads under 0.5
    return set(int(i) for i in np.unique(hit))


def _uv_polygons(ll, w, h):
    """Per texel (rows top to bottom), the low polygon covering it, -1 for the gutter."""
    pid = np.full((h, w), -1, np.int32)
    for t in range(len(ll["tl"])):
        pix, _b = _rasterise(ll["uv"][ll["tl"][t]], w, h, 0.5)
        pid[pix[:, 1], pix[:, 0]] = ll["tp"][t]
    return pid


def _grow_polys(polys, chosen, rings):
    """chosen plus every polygon sharing a vertex with it, `rings` times over."""
    chosen = set(chosen)
    if not chosen or rings <= 0:
        return chosen
    by_vert = {}
    for i, p in enumerate(polys):
        for v in p:
            by_vert.setdefault(v, []).append(i)
    for _ in range(int(rings)):
        chosen |= {j for i in list(chosen) for v in polys[i] for j in by_vert[v]}
    return chosen


def resolve_faults(low, highs, lm, push, polys, maps, w, h, uv_layer=None, ao_distance=None, depsgraph=None):
    """Bake the texels of the low's polygons `polys` (those with a cage ray starting inside a high) without Cycles:
    per texel a ray along the averaged normal from the cage (push) back through the low to RESOLVE["rear"] x push
    behind it (when it holds no front face, once more RESOLVE["retry"] times wider each way), back faces stepped over,
    the first front-facing hit kept (none: the nearest surface, a flat normal where it faces away); then each map
    shaded there:
    normal (the high's corner normals in the low's MikkTSpace frame), ao (RESOLVE["ao_rays"] cosine rays against the
    highs, ao_distance long), basecolor, roughness and metallic (the image or value feeding each high material's
    Principled input). Curvature and a node-chain input keep Cycles' value.
    w, h: the size baked (with supersampling). Returns (texels, report): texels {"rows", "cols", "ok", map: (n, 3)
    values in the bake's raw encoding, NaN where Cycles' stays, "covered": the UV coverage mask} or None."""
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    ll = _low_loops(low, dg, uv_layer)
    rep = {"polygons": len(polys), "texels": 0, "hit": 0, "nearest": 0, "flat": 0, "missed": 0, "left_to_cycles": []}
    if not polys:
        return None, rep
    hs = _Highs(low, highs, dg)
    vn = lm["vn"] / np.maximum(np.linalg.norm(lm["vn"], axis=1, keepdims=True), 1e-12)
    push = np.broadcast_to(np.asarray(push, np.float64), (len(lm["co"]),))
    pix, wts, tris = [], [], []
    for t in np.nonzero(np.isin(ll["tp"], sorted(polys)))[0]:
        p, b = _rasterise(ll["uv"][ll["tl"][t]], w, h, RESOLVE["edge_px"])
        pix.append(p)
        wts.append(b)
        tris.append(np.full(len(p), t))
    pix, wts, tris = np.vstack(pix), np.vstack(wts), np.concatenate(tris)
    _u, first = np.unique(pix[:, 1] * w + pix[:, 0], return_index=True)   # a texel on a shared edge: once
    pix, wts, tris = pix[first], wts[first], tris[first]
    n = len(pix)
    rep["texels"] = n
    pid = _uv_polygons(ll, w, h)
    # Cycles' margin (adjacent faces) fills the gutter beside a polygon from its neighbours across the UV seam, so the
    # gutter of a polygon next to a resolved one carries the old faulty values: _apply_resolved rebuilds it
    near = _grow_polys(lm["polys"], polys, 1)
    out = {"rows": pix[:, 1], "cols": pix[:, 0], "ok": np.zeros(n, bool), "covered": pid >= 0,
           "dirty": np.isin(pid, sorted(near))}
    for m in maps:
        if m in ("normal", "ao") or m in TRANSFER:
            out[m] = np.full((n, 3), np.nan)
    sources = {m: [[_socket_source(mt, TRANSFER[m]) for mt in part["mats"]] or [("value", (0.5, 0.5, 0.5))]
                   for part in hs.parts] for m in maps if m in TRANSFER}
    cache = {}
    ao_dist = float(ao_distance) if ao_distance else 0.1 * low.dimensions.length
    rng = np.random.default_rng(0)
    for i in range(n):
        lt = ll["tl"][tris[i]]
        wv = wts[i]
        verts = ll["lv"][lt]
        pos = wv @ lm["co"][verts]
        nrm = wv @ vn[verts]
        nrm /= max(np.linalg.norm(nrm), 1e-12)
        front = max(float(wv @ push[verts]), 1e-4)
        hits = hs.cast(pos + nrm * front, -nrm, front * (1.0 + RESOLVE["rear"]))
        if not hits and RESOLVE["retry"]:                  # nothing in the window: once more, retry x wider each way
            front *= RESOLVE["retry"]
            hits = hs.cast(pos + nrm * front, -nrm, front * (1.0 + RESOLVE["rear"]))
        flat = False
        if hits:
            t, f = hits[0]                                 # the first front face from the cage, as Toolbag and
            # Painter take it with back faces ignored (not the one nearest the low: a bump welded onto a body hides
            # the body's surface inside it, and that one is nearer)
            hit = pos + nrm * (front - t)
        else:                                              # no front face on the ray: the nearest surface
            from mathutils import Vector
            loc, _n, f, _d = hs.bvh.find_nearest(Vector(pos))
            if loc is None:
                rep["missed"] += 1
                continue
            hit = np.array(loc)
            if float(hs.fn[f] @ nrm) > 0.0:
                rep["nearest"] += 1
            else:                                          # none faces the low here (the low spans air): its colour,
                rep["flat"] += 1                           # and a flat normal rather than one pointing inward
                flat = True
        bc = hs.bary(f, hit)
        k, lf = hs.locate(f)
        part = hs.parts[k]
        hn = bc @ part["cn"][part["tl"][lf]]
        hn /= max(np.linalg.norm(hn), 1e-12)
        out["ok"][i] = True
        if "normal" in out and flat:
            out["normal"][i] = (0.5, 0.5, 1.0)
        elif "normal" in out and ll["tangent"] is not None:
            nn = wv @ ll["cn"][lt]
            nn /= max(np.linalg.norm(nn), 1e-12)
            tg = wv @ ll["tangent"][lt]
            tg -= nn * (tg @ nn)
            tg /= max(np.linalg.norm(tg), 1e-12)
            bt = float(ll["sign"][lt[0]]) * np.cross(nn, tg)
            out["normal"][i] = np.array([hn @ tg, hn @ bt, hn @ nn]) * 0.5 + 0.5
        if "ao" in out:
            t1 = np.cross(hn, [1.0, 0.0, 0.0] if abs(hn[0]) < 0.9 else [0.0, 1.0, 0.0])
            t1 /= np.linalg.norm(t1)
            t2 = np.cross(hn, t1)
            org, free = hit + hn * 1e-4, 0
            for _r in range(RESOLVE["ao_rays"]):
                r1, r2 = rng.random(), rng.random()
                s = np.sqrt(r1)
                d = t1 * s * np.cos(2 * np.pi * r2) + t2 * s * np.sin(2 * np.pi * r2) + hn * np.sqrt(1.0 - r1)
                free += not hs.occluded(org, d, ao_dist)
            out["ao"][i] = free / RESOLVE["ao_rays"]
        for m, per_part in sources.items():
            src = per_part[k][min(int(part["mat"][lf]), len(per_part[k]) - 1)]
            if src is None:
                continue
            if src[0] == "value":
                out[m][i] = src[1]
                continue
            _kind, img, uvname, channel = src
            uvs = part["uv"].get(uvname or part["uv_default"])
            if uvs is not None:
                out[m][i] = _sample_image(cache, img, bc @ uvs[part["tl"][lf]], channel)
    rep["hit"] = int(out["ok"].sum())
    for m in maps:
        if m not in out or np.isnan(out[m][out["ok"]]).all() and out["ok"].any():
            rep["left_to_cycles"].append(m)
    return out, rep


def _clean_gutter_normals(a, covered, margin_px):
    """A normal-map gutter texel (outside every UV triangle, within margin_px) that points into the surface can only be
    a fault copied there by the margin (it has no surface of its own): it takes the value of the nearest island-edge
    texel instead. a: the supersampled normal bake, raw (n + 1) / 2, rows top to bottom. Returns the texels fixed."""
    from mathutils import kdtree
    bad = (a[:, :, 2] < 0.5) & ~covered
    if not bad.any():
        return 0
    edge = covered & ~(np.roll(covered, 1, 0) & np.roll(covered, -1, 0) & np.roll(covered, 1, 1)
                       & np.roll(covered, -1, 1))
    er, ec = np.nonzero(edge)
    if not len(er):
        return 0
    tree = kdtree.KDTree(len(er))
    for i, (r, c) in enumerate(zip(er, ec)):
        tree.insert((float(c), float(r), 0.0), i)
    tree.balance()
    fixed = 0
    for r, c in zip(*np.nonzero(bad)):
        _co, i, d = tree.find((float(c), float(r), 0.0))
        if i is not None and d <= margin_px + 1:
            a[r, c] = a[er[i], ec[i]]
            fixed += 1
    return fixed


def _apply_resolved(a, res, m, margin_px):
    """Write the resolved texels of map m into the supersampled bake a (rows top to bottom, raw encoding), then rebuild
    the gutter around them: a texel outside every UV triangle, within margin_px, whose nearest covered texel (grown one
    ring at a time) lies in a resolved polygon or one beside it takes that texel's value. (Cycles filled those from
    the faulty values across the seam: measured on a cauldron, 2,843 of 3,381 inward texels left after resolving were
    gutter.) Returns the texels written."""
    if res is None or m not in res:
        return 0
    good = res["ok"] & ~np.isnan(res[m]).any(1)
    rows, cols = res["rows"][good], res["cols"][good]
    if not len(rows):
        return 0
    c = a.shape[2]
    a[rows, cols] = res[m][good][:, :c]
    h, w = a.shape[:2]
    dr_, dc_ = np.nonzero(res["dirty"])
    r0, r1 = max(min(rows.min(), dr_.min()) - margin_px, 0), min(max(rows.max(), dr_.max()) + margin_px + 1, h)
    c0, c1 = max(min(cols.min(), dc_.min()) - margin_px, 0), min(max(cols.max(), dc_.max()) + margin_px + 1, w)
    cov = res["covered"][r0:r1, c0:c1]
    src = np.where(cov, 0, -1).astype(np.int8)               # -1 gutter, 0 clean, 1 resolved or beside it
    src[res["dirty"][r0:r1, c0:c1]] = 1
    src[rows - r0, cols - c0] = 1
    val = a[r0:r1, c0:c1].copy()
    for _ in range(int(margin_px)):
        grown = False
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nb_src = np.full_like(src, -1)
            nb_val = np.zeros_like(val)
            sr = slice(max(dr, 0), src.shape[0] + min(dr, 0))
            dr_ = slice(max(-dr, 0), src.shape[0] + min(-dr, 0))
            sc = slice(max(dc, 0), src.shape[1] + min(dc, 0))
            dc_ = slice(max(-dc, 0), src.shape[1] + min(-dc, 0))
            nb_src[dr_, dc_] = src[sr, sc]
            nb_val[dr_, dc_] = val[sr, sc]
            take = (src == -1) & (nb_src >= 0)
            if take.any():
                src[take] = nb_src[take] + 2                 # mark as reached this ring (2 or 3), settled below
                val[take] = nb_val[take]
                grown = True
        src[src >= 2] -= 2
        if not grown:
            break
    fill = (src == 1) & ~cov
    a[r0:r1, c0:c1][fill] = val[fill]
    return int(len(rows))


# ---- the bake -------------------------------------------------------------------------------------------------------

def bake(low, highs, maps=("normal",), size=1024, out_dir=".", name=None, supersample=2, extrusion=None, margin=16,
         samples=None, ao_distance=None, bits=16, uv_layer=None, curvature_gain=None, gpu=False, cage=None,
         filter_sigma=FILTER_SIGMA, reference_size=None, occluders=(), resolve=True):
    """Bake `maps` (normal, ao, curvature; basecolor, roughness, metallic) from `highs` onto `low` and write
    <name>_<Map>.png into out_dir. basecolor, roughness and metallic copy the high polys' own materials (whatever
    feeds their Principled BSDF: a generated or scanned model's textures) through the same cage; basecolor is
    written sRGB-encoded, the others as data.
    size: 1024, (width, height) or "1024x2048"; cage: None or "uniform" (one push along the averaged normals:
    extrusion, default cage_extrusion(), enough to enclose the high polys), "fitted" (a push per vertex,
    fitted_cage_extrusions: narrow channels, concave creases, upholstery), or a cage object of your own;
    margin: dilation in pixels at the output size (scaled by supersample while baking; at least half the island
    gap); filter_sigma: the Gaussian pre-filter in output texels (0 for a plain box filter; 0.8 for detail under
    about 3 texels wide); samples: Cycles samples per map (default normal 8, ao 64, curvature 8); ao_distance: AO
    ray length in metres (default 10% of the diagonal); curvature_gain: fixed contrast for the curvature map
    (default: per map, so the 99th percentile of |pointiness - 0.5| reaches 0.5; give one value for every piece of
    a set so they match). reference_size: the diagonal in metres the default cage floor and AO distance scale with
    (default the low's; bake_exploded passes the assembled low's, not the spread-out one's). Every other
    render-visible object is hidden while baking and restored (an unrelated box over the low took its AO from 0.99 to
    0.70): occluders lists objects that should still cast AO (a floor for contact shadow); the report counts the
    hidden ones. resolve (default on, uniform and fitted cages): the texels of polygons with a cage ray starting inside
    a high are re-cast by resolve_faults() (back faces stepped over, the first front face kept) and written
    over Cycles' result; the report's "resolved" says how many."""
    t0 = time.time()
    scene = bpy.context.scene
    name = name or low.name
    os.makedirs(out_dir, exist_ok=True)
    highs = [h for h in highs if h is not None and h != low]
    if not highs:
        raise ValueError("no high-poly objects to bake from")
    mode = "own" if cage is not None and not isinstance(cage, str) else (cage or "uniform")
    if mode not in ("uniform", "fitted", "own"):
        raise ValueError("cage must be None, 'uniform', 'fitted' or a cage object, not %r" % (cage,))
    if mode == "fitted" and extrusion is not None:
        raise ValueError("extrusion sets a uniform cage: leave it out with cage='fitted'")
    _require_evaluated([low] + highs, bpy.context.evaluated_depsgraph_get())
    split = [m.name for m in low.modifiers if m.show_viewport != m.show_render]
    if split:
        raise ValueError("%s: modifier(s) %s are on in the viewport or the render but not both; the bake evaluates the "
                         "render stack and its cage the viewport one, so their faces differ (Blender's 'cage mesh "
                         "must have the same number of faces'). Turn the Triangulate back on after the UV layout, or "
                         "match the two toggles" % (low.name, ", ".join(split)))
    out_w, out_h = map_size(size)
    diag = max(float(reference_size) if reference_size else low.dimensions.length, 1e-6)
    stats, fitted = {}, {}
    push = None
    if mode == "uniform":
        if extrusion is None:
            extrusion, _outside = cage_extrusion(low, highs, stats=stats)
            extrusion = max(extrusion, 0.005 * diag)          # a little push even when the high poly sits inside
        push = extrusion = float(extrusion)
    elif mode == "fitted":
        push = fitted_cage_extrusions(low, highs, report=fitted, reference_size=diag)
    ao_distance = 0.1 * diag if ao_distance is None else float(ao_distance)
    ss = max(1, int(supersample))
    w, h = out_w * ss, out_h * ss
    keep = {"engine": scene.render.engine, "samples": scene.cycles.samples, "device": scene.cycles.device,
            "ao": scene.world.light_settings.distance if scene.world else None,
            "selected": [o for o in bpy.context.view_layer.objects if o.select_get()],
            "active": bpy.context.view_layer.objects.active}
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU" if gpu else "CPU"
    own_cage = mode != "own"
    cage = make_cage(low, push) if own_cage else cage
    out, report = {}, {"size": [out_w, out_h], "supersample": ss, "filter_sigma": float(filter_sigma or 0.0),
                       "cage": mode, "ao_distance": round(ao_distance, 5), "maps": {}}
    if mode == "uniform":
        report["extrusion"] = round(extrusion, 5)
    elif mode == "fitted":
        report["extrusion"] = {k: round(fitted[k], 5) for k in ("min", "max", "mean")}
        report["capped"], report["repaired"] = fitted["capped"], fitted["repaired"]
        stats = {"max": fitted["high_outside"], "p99": fitted["high_outside_p99"]}
    if stats:
        report["high_outside"] = round(stats["max"], 5)
        report["high_outside_p99"] = round(stats["p99"], 5)
    elif mode == "uniform":
        report["high_outside"] = report["high_outside_p99"] = None       # extrusion given: not measured
    if mode == "fitted":
        report["cage_inside"] = fitted["faults"]
    elif mode == "uniform":
        report["cage_inside"] = cage_faults(low, highs, push)
    resolved = None
    keepers = {low, cage} | set(highs) | set(occluders or ())
    hidden = [o for o in scene.objects if (o.type in ("MESH", "CURVE", "SURFACE", "META", "FONT")
                                           or (o.type == "EMPTY" and o.instance_type == "COLLECTION"))
              and not o.hide_render and o not in keepers]
    for o in hidden:
        o.hide_render = True
    report["hidden_for_bake"] = len(hidden)
    try:
        if resolve and mode != "own":
            t2 = time.time()
            dg = bpy.context.evaluated_depsgraph_get()
            lm = _low_mesh(low, dg)
            bad = set()
            _cage_faults(lm, np.broadcast_to(np.asarray(push, np.float64), (len(lm["co"]),)),
                         _high_bvhs(low, highs, dg), 1e3 * max(low.dimensions.length, 1.0), bad=bad)
            bad = _grow_polys(lm["polys"], bad, RESOLVE["grow"])     # seven rays per triangle miss faults between them
            seen = _inward_polygons(low, highs, cage, w, h, uv_layer, dg) if RESOLVE["detect"] else set()
            resolved, rr = resolve_faults(low, highs, lm, push, bad | seen, maps, w, h, uv_layer=uv_layer,
                                          ao_distance=ao_distance, depsgraph=dg)
            rr["detected_polygons"] = len(seen - bad)
            rr["seconds"] = round(time.time() - t2, 2)
            report["resolved"] = rr
        for m in maps:
            if m not in MAP_SUFFIX:
                raise ValueError("unknown map %r (%s)" % (m, ", ".join(MAP_SUFFIX)))
            t1 = time.time()
            img = bpy.data.images.new("bake_tmp_" + m, w, h, alpha=False, float_buffer=True)
            img.colorspace_settings.name = "Non-Color"
            img.pixels.foreach_set(np.tile(np.array(NEUTRAL[m] + (1.0,), np.float32), w * h))   # uncovered: neutral
            undo = _active_image_nodes(low, img)
            pmat = saved = None
            temps = tsaved = None
            try:
                bpy.ops.object.select_all(action="DESELECT")
                for hobj in highs:
                    hobj.select_set(True)
                low.select_set(True)
                bpy.context.view_layer.objects.active = low
                kw = dict(use_selected_to_active=True, use_cage=True, cage_object=cage.name, max_ray_distance=0.0,
                          margin=int(margin) * ss, margin_type="ADJACENT_FACES", target="IMAGE_TEXTURES",
                          use_clear=False, uv_layer=uv_layer or "")
                if m == "normal":
                    scene.cycles.samples = samples or 8
                    bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", normal_r="POS_X", normal_g="POS_Y",
                                        normal_b="POS_Z", **kw)
                elif m == "ao":
                    scene.cycles.samples = samples or 64
                    if scene.world:
                        scene.world.light_settings.distance = ao_distance
                    bpy.ops.object.bake(type="AO", **kw)
                elif m in TRANSFER:
                    scene.cycles.samples = samples or 8
                    temps, tsaved, tnotes = _transfer_materials(highs, TRANSFER[m])
                    report.setdefault("notes", []).extend(tnotes)
                    bpy.ops.object.bake(type="EMIT", **kw)
                else:
                    scene.cycles.samples = samples or 8
                    pmat, saved = _pointiness_materials(highs)
                    bpy.ops.object.bake(type="EMIT", **kw)
                a = _image_array(img)[:, :, :3]
                info = {}
                if resolved is not None:
                    info["resolved_texels"] = _apply_resolved(a, resolved, m, int(margin) * ss)
                    if m == "normal":
                        info["gutter_fixed"] = _clean_gutter_normals(a, resolved["covered"], int(margin) * ss)
                if m == "normal":
                    a = a * 2.0 - 1.0                          # filter the vectors, then renormalise
                a = downsample(a, ss, filter_sigma)
                if m == "normal":
                    a /= np.maximum(np.linalg.norm(a, axis=2, keepdims=True), 1e-8)
                    a = (a + 1.0) / 2.0
                elif m == "ao":
                    a = a[:, :, :1]
                elif m == "basecolor":
                    a = _linear_to_srgb(a)                     # baked as linear light; stored like any colour map
                    info["colour_space"] = "sRGB"
                elif m in TRANSFER:
                    a = np.clip(a[:, :, :1], 0.0, 1.0)
                else:
                    p = a[:, :, 0] - 0.5
                    dev = np.abs(p[np.abs(p) > 1e-4])
                    gain = float(curvature_gain) if curvature_gain else (
                        0.5 / max(float(np.percentile(dev, 99)), 1e-6) if dev.size else 1.0)
                    a = np.clip(0.5 + p * gain, 0.0, 1.0)[:, :, None]
                    info["gain"] = round(gain, 3)
                    used = np.abs(p) > 1e-4                    # texels the bake wrote something into
                    sat = float(((a[:, :, 0] <= 0.001) | (a[:, :, 0] >= 0.999))[used].mean()) if used.any() else 0.0
                    info["saturated_share"] = round(sat, 4)
                    if sat > CURVATURE_SATURATED:
                        report.setdefault("notes", []).append(
                            "curvature: %.0f%% of its texels clipped to 0 or 1 at gain %.3g: a shared gain from a "
                            "denser high, or a sparse high read as all edges; cut the high to a grid of about 2 bake "
                            "texels before its bevels, or bake this set with its own gain" % (100 * sat, gain))
                path = os.path.join(out_dir, "%s_%s.png" % (name, MAP_SUFFIX[m]))
                save_png(path, a, bits=bits)
                out[m] = path
                info["seconds"] = round(time.time() - t1, 2)
                report["maps"][m] = info
            finally:
                if pmat is not None:
                    _restore_materials(pmat, saved)
                if tsaved is not None:
                    for hobj, mats in tsaved:
                        for slot, mat0 in zip(hobj.material_slots, mats):
                            slot.material = mat0
                    for t in temps:
                        bpy.data.materials.remove(t)
                _undo(undo)
                bpy.data.images.remove(img)
    finally:
        for o in hidden:
            o.hide_render = False
        if own_cage:
            me = cage.data
            bpy.data.objects.remove(cage)
            bpy.data.meshes.remove(me)
        scene.render.engine = keep["engine"]
        scene.cycles.samples = keep["samples"]
        scene.cycles.device = keep["device"]
        if scene.world and keep["ao"] is not None:
            scene.world.light_settings.distance = keep["ao"]
        bpy.ops.object.select_all(action="DESELECT")
        for o in keep["selected"]:
            o.select_set(True)
        bpy.context.view_layer.objects.active = keep["active"]
    report["seconds"] = round(time.time() - t0, 2)
    out["report"] = report
    return out


def parts_by_name(low, highs):
    """{vertex group of low: [highs]} from names: a high called <Part>_high (or <Part>_high.001, <Part>_high_bolts)
    belongs to the low's vertex group <Part>. Raises on a high with no matching group."""
    groups = {g.name for g in low.vertex_groups}
    parts = {}
    for h in highs:
        base = h.name.split("_high")[0] if "_high" in h.name else None
        if base not in groups:
            raise ValueError("%s: no vertex group %r on %s for it (name highs <Part>_high after the low's part "
                             "groups)" % (h.name, base, low.name))
        parts.setdefault(base, []).append(h)
    return parts


def bake_exploded(low, parts, maps=("normal", "ao", "curvature"), explode=("normal", "ao", "curvature"), distance=None,
                  **kw):
    """Bake a low poly made of parts that sit close together (a lid on a body, brackets on planks) so no part's rays
    catch another part's high poly: parts {low vertex group: [its highs]} (parts_by_name builds it from <Part>_high
    names). For the maps in `explode` (all three by default), part k (in name order) and its highs move k x distance
    along +X (default twice the low's diagonal), bake() runs, and every vertex and object goes back exactly where it
    was; maps left out of `explode` bake with everything assembled. AO assembled keeps the contact shadows between
    parts but lets a part's rays land on its neighbour's high, the fault exploding prevents: leave "ao" out only when
    the assembled pass's cage_inside neighbour count is 0. Low vertices in no part group (or only in other groups)
    stay put with part 0. Only highs with no high among their parents move (their children follow), and a high
    parented to another part's high is refused. kw: bake()'s options (size, out_dir, name, cage, ...). Returns
    bake()'s dict, its report with "exploded" (the maps and the distance) and one report per pass."""
    names = sorted(parts)
    gi = {g.name: g.index for g in low.vertex_groups}
    missing = [n for n in names if n not in gi]
    if missing:
        raise ValueError("%s has no vertex groups %s" % (low.name, ", ".join(missing)))
    highs = [h for n in names for h in parts[n]]
    if len(set(highs)) != len(highs):
        raise ValueError("a high poly is listed under two parts")
    part_of = {h: k for k, n in enumerate(names) for h in parts[n]}
    roots = []
    for h in highs:
        up = h.parent
        while up is not None and up not in part_of:
            up = up.parent
        if up is None:
            roots.append(h)
        elif part_of[up] != part_of[h]:
            raise ValueError("%s is parented to %s, a high of another part: clear its parent (keep transform) "
                             "before an exploded bake" % (h.name, up.name))
    me = low.data
    group_part = {gi[n]: k for k, n in enumerate(names)}
    member = np.full(len(me.vertices), -1, np.int64)
    for v in me.vertices:
        for g in v.groups:
            k = group_part.get(g.group)
            if g.weight > 0 and k is not None:
                if member[v.index] not in (-1, k):
                    raise ValueError("vertex %d of %s is in two part groups" % (v.index, low.name))
                member[v.index] = k
    size = max(low.dimensions.length, 1e-3)                   # assembled: the defaults scale with this, not with
    kw.setdefault("reference_size", size)                     # the parts spread out (an 18 m spread made a 90 mm
    dist = float(distance) if distance else 2.0 * size        # cage floor and 1.8 m AO rays)
    out, reports = {}, {}
    first = [m for m in maps if m in explode]
    rest = [m for m in maps if m not in explode]
    if first:
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        keep_co = co.copy()
        keep_basis = {h.name: h.matrix_basis.copy() for h in roots}
        inv = np.array(low.matrix_world.inverted().to_3x3())
        try:
            shift = np.zeros((len(me.vertices), 3))
            ks = np.clip(member, 0, None)
            shift[:, 0] = ks * dist
            me.vertices.foreach_set("co", (co.reshape(-1, 3) + shift @ inv.T).ravel())
            me.update()
            for h in roots:
                m = h.matrix_world.copy()
                m.translation.x += part_of[h] * dist
                h.matrix_world = m
            bpy.context.view_layer.update()
            r = bake(low, highs, maps=tuple(first), **kw)
        finally:
            me.vertices.foreach_set("co", keep_co)
            me.update()
            for h in roots:
                h.matrix_basis = keep_basis[h.name]
            bpy.context.view_layer.update()
        reports["exploded"] = r.pop("report")
        out.update(r)
    if rest:
        r = bake(low, highs, maps=tuple(rest), **kw)
        reports["assembled"] = r.pop("report")
        out.update(r)
    out["report"] = {"exploded": {"maps": first, "distance": round(dist, 4), "parts": names}, "passes": reports}
    return out


def main(argv):
    ap = argparse.ArgumentParser(prog="bake_maps.py", description=__doc__.split("\n")[0])
    ap.add_argument("--low", required=True, help="the low-poly object")
    ap.add_argument("--high", required=True, action="append", help="a high-poly object (repeat for several)")
    ap.add_argument("--size", default="1024", help="1024, or width x height: 1024x2048")
    ap.add_argument("--out", default=".")
    ap.add_argument("--name", help="file name prefix (default: the low poly's name)")
    ap.add_argument("--maps", default="normal,ao,curvature")
    ap.add_argument("--cage", choices=("uniform", "fitted"), default="uniform")
    ap.add_argument("--supersample", type=int, default=2)
    ap.add_argument("--filter-sigma", type=float, default=FILTER_SIGMA)
    ap.add_argument("--extrusion", type=float)
    ap.add_argument("--margin", type=int, default=16)
    ap.add_argument("--samples", type=int)
    ap.add_argument("--ao-distance", type=float)
    ap.add_argument("--curvature-gain", type=float)
    ap.add_argument("--bits", type=int, choices=(8, 16), default=16)
    ap.add_argument("--uv-layer")
    ap.add_argument("--gpu", action="store_true")
    ap.add_argument("--no-resolve", action="store_true", help="leave the texels whose cage rays start inside a high "
                    "as Cycles baked them (default: re-baked with back faces ignored)")
    ap.add_argument("--explode", action="store_true", help="parts close together: pair <Part>_high objects with the "
                    "low's <Part> vertex groups and bake every map with the parts moved apart")
    a = ap.parse_args(argv)
    obs = bpy.data.objects
    missing = [n for n in [a.low] + a.high if n not in obs]
    if missing:
        print("[bake] no object named %s" % ", ".join(missing))
        return 2
    try:
        size = map_size(a.size)
    except ValueError as ex:
        print("[bake] --size %s: %s" % (a.size, ex))
        return 2
    kw = dict(maps=tuple(m.strip() for m in a.maps.split(",") if m.strip()), size=size, out_dir=a.out, name=a.name,
              supersample=a.supersample, extrusion=a.extrusion, margin=a.margin, samples=a.samples,
              ao_distance=a.ao_distance, bits=a.bits, uv_layer=a.uv_layer, curvature_gain=a.curvature_gain, gpu=a.gpu,
              cage=a.cage, filter_sigma=a.filter_sigma, resolve=not a.no_resolve)
    highs = [obs[n] for n in a.high]
    try:
        res = (bake_exploded(obs[a.low], parts_by_name(obs[a.low], highs), **kw) if a.explode
               else bake(obs[a.low], highs, **kw))
    except ValueError as ex:
        print("[bake] %s" % ex)
        return 2
    for m, p in res.items():
        if m != "report":
            print("[bake] %s -> %s" % (m, p))
    rp = os.path.join(a.out, "%s_bake.json" % (a.name or a.low))
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(res["report"], f, indent=1)
    print("[bake] report %s -> %s" % (res["report"], rp))
    return 0


if __name__ == "__main__" and not globals().get("BAKE_MAPS_NO_MAIN"):
    sys.exit(main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []))
