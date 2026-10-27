"""Bake mesh maps from high-poly meshes onto a low-poly mesh's UVs with Cycles: a tangent-space normal map (OpenGL
Y+, MikkTSpace tangents of the low poly as evaluated), ambient occlusion, and curvature (Pointiness through an
Emission bake). Rays start from a cage built from the low poly with averaged normals, so hard edges bake without
seams: one uniform push sized to enclose the high polys, or a fitted cage pushed per vertex (narrow channels,
concave creases, upholstery). Each map bakes at `supersample` times the size, is Gaussian pre-filtered and box-filtered
down (normals renormalised), and is written as a 16-bit PNG (or 8-bit with dither), data values, no colour
management. Maps may be square or not (1024x2048).

Host: Blender 4.2+ (bpy, Cycles and the bundled numpy), no add-ons; tested on Blender 5.2.2. Changes nothing it does
not restore: temporary images, materials, nodes and the cage are removed, render settings put back. Never saves the
.blend.

Command line (open the .blend that holds the meshes):
    blender -b --factory-startup crate.blend --python-exit-code 1 --python bake_maps.py --
            --low PROP_Crate_Free_A --high Crate_high --size 2048 --out blender/substance/PROP/bake
            --name T_PROP_Crate --maps normal,ao,curvature [--size 1024x2048] [--cage fitted] [--supersample 2]
            [--filter-sigma 0.5] [--extrusion 0.02] [--margin 16] [--samples 64] [--ao-distance 0.2] [--bits 16]
            [--gpu] [--explode]
As a module (Blender MCP or another script):
    ns = {"BAKE_MAPS_NO_MAIN": True}; exec(open(path, encoding="utf-8").read(), ns)
    paths = ns["bake"](low, [high], maps=("normal", "ao"), size=1024, out_dir=..., name="T_PROP_Crate")
    paths = ns["bake"](low, highs, size=(1024, 2048), cage="fitted")         # per-vertex cage, a tall map
    paths = ns["bake_exploded"](low, ns["parts_by_name"](low, highs), size=1024, out_dir=...)  # parts close together

Output: <out_dir>/<name>_Normal.png, _AO.png, _Curvature.png; returns {map: path} plus "report" (sizes, seconds, the
cage push and how far the high polys stand out, the curvature gain used). The low poly bakes as it exports:
modifiers applied (keep its Triangulate on, so the baker and the engine see the same triangles), through its active
render UV layer unless uv_layer is given. The low and high polys must be in the view layer: an object in an excluded
or disabled collection is not evaluated, and its matrix_world is stale (identity after a load).
"""

import argparse
import os
import struct
import sys
import time
import zlib

import bpy
import numpy as np

MAP_SUFFIX = {"normal": "Normal", "ao": "AO", "curvature": "Curvature"}
NEUTRAL = {"normal": (0.5, 0.5, 1.0), "ao": (1.0, 1.0, 1.0), "curvature": (0.5, 0.5, 0.5)}
PNG_COLOUR = {1: 0, 2: 4, 3: 2, 4: 6}        # channels -> PNG colour type: grey, grey + alpha, RGB, RGBA
FILTER_SIGMA = 0.5       # Gaussian pre-filter, in output texels: a box filter alone steps thin sloped detail
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


def _cage_faults(lm, push, bvhs, reach):
    """The bake's own rays traced at seven points of every cage triangle (polygons fanned), as Cycles casts them:
    from the cage point towards the low point at the same barycentric position, nearest hit. A ray whose first hit
    is the inside of a surface starts inside a high: inside one that stands off the low surface when the hit comes
    before the low point (a neighbour across a channel or crease: the cage reaches too far), inside the low's own
    high when it comes after (the cage is too small). Returns (triangles with a ray of the first kind, of the second,
    rays of the first kind, of the second, rays traced)."""
    from mathutils import Vector
    vn = lm["vn"] / np.maximum(np.linalg.norm(lm["vn"], axis=1, keepdims=True), 1e-12)
    cage = lm["co"] + vn * np.asarray(push, np.float64)[:, None]
    across, short = [], []
    n_across = n_short = rays = 0
    for p in lm["polys"]:
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


def fitted_cage_extrusions(low, highs, depsgraph=None, max_samples=200000, report=None, **settings):
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
    reach = max(2.0 * float(req.max()) if nv else 0.0, 0.02 * low.dimensions.length)   # sparse highs: gaps in samples
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


def _restore_materials(mat, saved):
    for h, mats in saved:
        if not mats:
            h.data.materials.pop()
        else:
            for s, m in zip(h.material_slots, mats):
                s.material = m
    bpy.data.materials.remove(mat)


# ---- the bake -------------------------------------------------------------------------------------------------------

def bake(low, highs, maps=("normal",), size=1024, out_dir=".", name=None, supersample=2, extrusion=None, margin=16,
         samples=None, ao_distance=None, bits=16, uv_layer=None, curvature_gain=None, gpu=False, cage=None,
         filter_sigma=FILTER_SIGMA):
    """Bake `maps` (normal, ao, curvature) from `highs` onto `low` and write <name>_<Map>.png into out_dir.
    size: 1024, (width, height) or "1024x2048"; cage: None or "uniform" (one push along the averaged normals:
    extrusion, default cage_extrusion(), enough to enclose the high polys), "fitted" (a push per vertex,
    fitted_cage_extrusions: narrow channels, concave creases, upholstery), or a cage object of your own;
    margin: dilation in pixels at the output size (scaled by supersample while baking; at least half the island
    gap); filter_sigma: the Gaussian pre-filter in output texels (0 for a plain box filter; 0.8 for detail under
    about 3 texels wide); samples: Cycles samples per map (default normal 8, ao 64, curvature 8); ao_distance: AO
    ray length in metres (default 10% of the diagonal); curvature_gain: fixed contrast for the curvature map
    (default: per map, so the 99th percentile of |pointiness - 0.5| reaches 0.5; give one value for every piece of
    a set so they match)."""
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
    out_w, out_h = map_size(size)
    diag = max(low.dimensions.length, 1e-6)
    stats, fitted = {}, {}
    push = None
    if mode == "uniform":
        if extrusion is None:
            extrusion, _outside = cage_extrusion(low, highs, stats=stats)
            extrusion = max(extrusion, 0.005 * diag)          # a little push even when the high poly sits inside
        push = extrusion = float(extrusion)
    elif mode == "fitted":
        push = fitted_cage_extrusions(low, highs, report=fitted)
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
    try:
        for m in maps:
            if m not in MAP_SUFFIX:
                raise ValueError("unknown map %r (normal, ao, curvature)" % m)
            t1 = time.time()
            img = bpy.data.images.new("bake_tmp_" + m, w, h, alpha=False, float_buffer=True)
            img.colorspace_settings.name = "Non-Color"
            img.pixels.foreach_set(np.tile(np.array(NEUTRAL[m] + (1.0,), np.float32), w * h))   # uncovered: neutral
            undo = _active_image_nodes(low, img)
            pmat = saved = None
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
                else:
                    scene.cycles.samples = samples or 8
                    pmat, saved = _pointiness_materials(highs)
                    bpy.ops.object.bake(type="EMIT", **kw)
                a = _image_array(img)[:, :, :3]
                if m == "normal":
                    a = a * 2.0 - 1.0                          # filter the vectors, then renormalise
                a = downsample(a, ss, filter_sigma)
                info = {}
                if m == "normal":
                    a /= np.maximum(np.linalg.norm(a, axis=2, keepdims=True), 1e-8)
                    a = (a + 1.0) / 2.0
                elif m == "ao":
                    a = a[:, :, :1]
                else:
                    p = a[:, :, 0] - 0.5
                    dev = np.abs(p[np.abs(p) > 1e-4])
                    gain = float(curvature_gain) if curvature_gain else (
                        0.5 / max(float(np.percentile(dev, 99)), 1e-6) if dev.size else 1.0)
                    a = np.clip(0.5 + p * gain, 0.0, 1.0)[:, :, None]
                    info["gain"] = round(gain, 3)
                path = os.path.join(out_dir, "%s_%s.png" % (name, MAP_SUFFIX[m]))
                save_png(path, a, bits=bits)
                out[m] = path
                info["seconds"] = round(time.time() - t1, 2)
                report["maps"][m] = info
            finally:
                if pmat is not None:
                    _restore_materials(pmat, saved)
                _undo(undo)
                bpy.data.images.remove(img)
    finally:
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


def bake_exploded(low, parts, maps=("normal", "ao", "curvature"), explode=("normal", "curvature"), distance=None,
                  **kw):
    """Bake a low poly made of parts that sit close together (a lid on a body, brackets on planks) so no part's rays
    catch another part's high poly: parts {low vertex group: [its highs]} (parts_by_name builds it from <Part>_high
    names). For the maps in `explode`, part k (in name order) and its highs move k x distance along +X (default twice
    the low's diagonal), bake() runs, and every vertex and object goes back exactly where it was; the other maps (AO
    by default: it wants the contact shadows between parts) bake with everything assembled. Low vertices in no group
    stay put with part 0. kw: bake()'s options (size, out_dir, name, cage, ...). Returns bake()'s dict, its report
    with "exploded" (the maps and the distance) and one report per pass."""
    names = sorted(parts)
    gi = {g.name: g.index for g in low.vertex_groups}
    missing = [n for n in names if n not in gi]
    if missing:
        raise ValueError("%s has no vertex groups %s" % (low.name, ", ".join(missing)))
    highs = [h for n in names for h in parts[n]]
    if len(set(highs)) != len(highs):
        raise ValueError("a high poly is listed under two parts")
    me = low.data
    member = np.full(len(me.vertices), -1, np.int64)
    for v in me.vertices:
        for g in v.groups:
            if g.weight > 0 and g.group in gi.values():
                k = names.index(next(n for n in names if gi[n] == g.group))
                if member[v.index] not in (-1, k):
                    raise ValueError("vertex %d of %s is in two part groups" % (v.index, low.name))
                member[v.index] = k
    dist = float(distance) if distance else 2.0 * max(low.dimensions.length, 1e-3)
    out, reports = {}, {}
    first = [m for m in maps if m in explode]
    rest = [m for m in maps if m not in explode]
    if first:
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        keep_co = co.copy()
        keep_mw = {h.name: h.matrix_world.copy() for h in highs}
        inv = np.array(low.matrix_world.inverted().to_3x3())
        try:
            shift = np.zeros((len(me.vertices), 3))
            ks = np.clip(member, 0, None)
            shift[:, 0] = ks * dist
            me.vertices.foreach_set("co", (co.reshape(-1, 3) + shift @ inv.T).ravel())
            me.update()
            for k, n in enumerate(names):
                for h in parts[n]:
                    m = h.matrix_world.copy()
                    m.translation.x += k * dist
                    h.matrix_world = m
            bpy.context.view_layer.update()
            r = bake(low, highs, maps=tuple(first), **kw)
        finally:
            me.vertices.foreach_set("co", keep_co)
            me.update()
            for h in highs:
                h.matrix_world = keep_mw[h.name]
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
    ap.add_argument("--explode", action="store_true", help="parts close together: pair <Part>_high objects with the "
                    "low's <Part> vertex groups and bake normal and curvature with the parts moved apart (AO assembled)")
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
              cage=a.cage, filter_sigma=a.filter_sigma)
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
    print("[bake] report %s" % res["report"])
    return 0


if __name__ == "__main__" and not globals().get("BAKE_MAPS_NO_MAIN"):
    sys.exit(main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []))
