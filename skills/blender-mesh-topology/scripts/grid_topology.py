"""Building blocks for hand-designed grid topology (see ../references/grid-layout.md).

Host: Blender (mathutils; bmesh for flat_fill and PointCache; tested on 5.2.2). thin_plate_heights needs numpy, which
Blender bundles, and uses scipy only when it can be imported (Blender does not bundle it).
Load in Blender:  ns = {}; exec(open(r"<skill>/scripts/grid_topology.py", encoding="utf-8").read(), ns)

Faces are made through a `face(verts)` callable you pass in (for example `lambda vs: bm.faces.new(vs)`), so the helpers
work with plain bmesh or with a generator's own mesh wrapper. Points are mathutils.Vector; verts have a `.co`.
"""

import math

from mathutils import Vector


def _cross2(a, b):
    """z of the cross product of two 2-D vectors (numpy 2.5+ refuses np.cross on 2-element vectors)."""
    return a[0] * b[1] - a[1] * b[0]


def arc_segments(radius, span_deg, tol, max_edge=None):
    """Segments for an arc of `radius` over `span_deg`: enough to keep the chord sag r(1 - cos(step/2)) within `tol`,
    and (if given) no segment longer than `max_edge`."""
    step = 2.0 * math.degrees(math.acos(max(-1.0, 1.0 - tol / radius)))
    n = max(1, math.ceil(span_deg / step))
    if max_edge:
        n = max(n, math.ceil(math.radians(span_deg) * radius / max_edge))
    return n


def zone_stations(breaks, step, floors=None, multiple=None, adjust=None):
    """Stations from breaks[0] to breaks[-1], evenly spaced inside each zone between consecutive breaks, about `step`
    apart (one zone, breaks=[a, b], gives evenly spaced stations). floors: {zone index: minimum segments}. multiple:
    make the total segment count a multiple of this by adding segments to zone `adjust` (default the longest).
    Returns (stations, segments per zone)."""
    counts = [max(1, round((b - a) / step)) for a, b in zip(breaks, breaks[1:])]
    for z, n in (floors or {}).items():
        counts[z] = max(counts[z], n)
    if multiple:
        z = adjust if adjust is not None else max(range(len(counts)), key=lambda i: breaks[i + 1] - breaks[i])
        counts[z] += (-sum(counts)) % multiple
    out = [breaks[0]]
    for (a, b), n in zip(zip(breaks, breaks[1:]), counts):
        out += [a + (b - a) * i / n for i in range(1, n + 1)]
    return out, counts


def blend_error(section_at, a, b, n, samples=(0.25, 0.5, 0.75)):
    """Largest distance between a blended section (section_at(x) -> list of points, same count everywhere) and straight
    segments between n + 1 evenly spaced stations from a to b. Use it to set a zone's floor."""
    xs = [a + (b - a) * i / n for i in range(n + 1)]
    err = 0.0
    for xa, xb in zip(xs, xs[1:]):
        pa, pb = section_at(xa), section_at(xb)
        for f in samples:
            pt = section_at(xa + (xb - xa) * f)
            err = max(err, max((qa.lerp(qb, f) - qt).length for qa, qb, qt in zip(pa, pb, pt)))
    return err


def grid_faces(face, cols, rows):
    """Quads between neighbouring columns. cols: list of dicts {row index: vert}; a quad is made for rows i, i + 1 only
    where both columns carry both (cut-outs leave gaps for their own walls). rows: iterable of row indices."""
    rows = list(rows)
    out = []
    for ca, cb in zip(cols, cols[1:]):
        for i, j in zip(rows, rows[1:]):
            vs = [ca.get(i), cb.get(i), cb.get(j), ca.get(j)]
            if all(v is not None for v in vs):
                out.append(face(vs))
    return out


def _along(cs, t):
    """The point at fraction t (by length) along the polyline through the verts cs."""
    pts = [c.co for c in cs]
    lengths = [(b - a).length for a, b in zip(pts, pts[1:])]
    d = t * sum(lengths)
    for a, b, seg in zip(pts, pts[1:], lengths):
        if d <= seg:
            return a.lerp(b, d / seg if seg else 0.0)
        d -= seg
    return pts[-1].copy()


def step_reduce(face, new_vert, top, bottom, mid_at, n=1):
    """A loop-reduction band of the 3 to 1 family, all quads: every group of n + 2 top segments becomes n bottom
    segments (n = 1: 3 to 1, n = 2: 4 to 2, n = 3: 5 to 3). top has (n + 2) * g + 1 verts and bottom n * g + 1 for g
    groups; each group's end verts sit under its end top verts. A closed ring (round a pipe) is passed with its first
    vert repeated at the end of both runs, so it still has (n + 2) * g + 1 and n * g + 1 entries and the last group
    closes the ring. Each group adds n + 1 verts mid-band, one
    under each of its top verts 1..n+1, at mid_at(f, cs, t) -> co (f: the top vert above; cs: the group's n + 1 bottom
    verts; t = k / (n + 2): the fraction along cs below f), and makes 2n + 2 quads. Poles: valence 3 at the first and
    last mid vert of a group; valence 6 at a bottom vert shared by two groups when a row continues below (4 at the
    band's ends); every other vert keeps valence 4. Winding follows the runs (f0 -> f1 -> mid -> c0), the same way as
    grid_faces when the top run is the earlier row. When the fine run is the later row (going coarse to fine, as the
    second band on a ring does), pass both runs reversed, or the band faces the other way (topology_audit's
    flipped_edges counts it)."""
    m = n + 2
    groups = (len(top) - 1) // m
    assert n >= 1 and (len(top) - 1) % m == 0 and groups * n == len(bottom) - 1, \
        "top needs n + 2 segments for every n bottom segments (a closed ring repeats its first vert at the end)"
    out = []
    for g in range(groups):
        f = top[g * m:(g + 1) * m + 1]
        cs = bottom[g * n:(g + 1) * n + 1]
        mids = [new_vert(mid_at(f[k + 1], cs, (k + 1) / m)) for k in range(n + 1)]
        out.append(face([f[0], f[1], mids[0], cs[0]]))
        for k in range(1, n + 1):
            out.append(face([f[k], f[k + 1], mids[k], mids[k - 1]]))
        out.append(face([f[n + 1], f[n + 2], cs[n], mids[n]]))
        for k in range(n):
            out.append(face([mids[k], mids[k + 1], cs[k + 1], cs[k]]))
    return out


def step_3to1(face, new_vert, top, bottom, mid_at):
    """A 3 to 1 reduction band (step_reduce with n = 1): top has 3n + 1 verts, bottom n + 1. For each group of three
    top segments two points are added mid-band (new_vert(co)) at mid_at(f, c0, c1, k) -> co, k = 1 or 2 for the point
    under f1 or f2, and four quads are made: [f0 f1 p c0] [f1 f2 q p] [f2 f3 c1 q] [p q c1 c0]."""
    return step_reduce(face, new_vert, top, bottom, lambda f, cs, t: mid_at(f, cs[0], cs[1], round(t * 3)), 1)


def mid_between(surface=None):
    """A mid_at for step_3to1: halfway between f and the matching point on the bottom segment (1/3 or 2/3 along it),
    optionally moved onto a surface (surface(co) -> co)."""
    def mid(f, c0, c1, k):
        co = (f.co + c0.co.lerp(c1.co, k / 3.0)) / 2.0
        return surface(co) if surface else co
    return mid


def mid_along(surface=None):
    """A mid_at for step_reduce: halfway between f and the point a fraction t along the group's bottom verts,
    optionally moved onto a surface (surface(co) -> co)."""
    def mid(f, cs, t):
        co = (f.co + _along(cs, t)) / 2.0
        return surface(co) if surface else co
    return mid


def zipper(face, A, B):
    """Faces between two runs of verts whose ends are in step (A[0] beside B[0], A[-1] beside B[-1]), matched by
    arc-length fraction: a quad where both advance together, otherwise triangles. Keep it to one narrow row of similar
    density on both sides; where one run is much denser (a semicircle against a few grid points) use flat_fill on the
    region instead (a greedy best-angle zipper was tried and wandered into long fans)."""
    def fractions(run):
        cum = [0.0]
        for p, q in zip(run, run[1:]):
            cum.append(cum[-1] + (q.co - p.co).length)
        return [c / cum[-1] for c in cum]
    fa, fb = fractions(A), fractions(B)
    i = j = 0
    out = []
    while i < len(A) - 1 or j < len(B) - 1:
        if i < len(A) - 1 and j < len(B) - 1 and abs(fa[i + 1] - fb[j + 1]) < 1e-6:
            out.append(face([A[i], A[i + 1], B[j + 1], B[j]]))
            i, j = i + 1, j + 1
        elif j == len(B) - 1 or (i < len(A) - 1 and fa[i + 1] <= fb[j + 1]):
            out.append(face([A[i], A[i + 1], B[j]]))
            i += 1
        else:
            out.append(face([A[i], B[j + 1], B[j]]))
            j += 1
    return out


def zipper_by(face, A, B, key, tol=1e-6):
    """Like zipper, but the runs are matched by a coordinate (key(vert) -> float, rising along both runs, for example
    lambda v: v.co.y along a deck): a quad wherever both runs have a point at the same key, triangles elsewhere. Put
    matching stations on both runs to get quads."""
    i = j = 0
    out = []
    while i < len(A) - 1 or j < len(B) - 1:
        if i < len(A) - 1 and j < len(B) - 1 and abs(key(A[i + 1]) - key(B[j + 1])) < tol:
            out.append(face([A[i], A[i + 1], B[j + 1], B[j]]))
            i, j = i + 1, j + 1
        elif j == len(B) - 1 or (i < len(A) - 1 and key(A[i + 1]) < key(B[j + 1])):
            out.append(face([A[i], A[i + 1], B[j]]))
            i += 1
        else:
            out.append(face([A[i], B[j + 1], B[j]]))
            j += 1
    return out


def ladder(face, A, B):
    """Quads straight across between two runs with the same number of points that correspond one to one (mirror images,
    two facing semicircles of equal segments, the two sides of a symmetric deck): [A[k], A[k+1], B[k+1], B[k]]."""
    assert len(A) == len(B)
    return [face([A[k], A[k + 1], B[k + 1], B[k]]) for k in range(len(A) - 1)]


class PointCache:
    """One vertex per point for layouts built from computed coordinates: get(co) returns the vertex there, creating it
    once. Coordinates reached by different sums can land either side of a rounding step, so also call weld() (merge
    doubles within dist among the cached verts only) before adding separate islands; the cache then points at the
    surviving verts."""
    def __init__(self, bm, digits=6):
        self.bm, self.digits, self.map = bm, digits, {}

    def get(self, co):
        k = tuple(round(c, self.digits) for c in co)
        if k not in self.map:
            self.map[k] = self.bm.verts.new(co)
        return self.map[k]

    def weld(self, dist=1e-5):
        """Merge cached verts closer than dist; returns how many were merged away."""
        import bmesh
        verts = [v for v in self.map.values() if v.is_valid]
        targetmap = bmesh.ops.find_doubles(self.bm, verts=verts, dist=dist)["targetmap"]
        if targetmap:
            bmesh.ops.weld_verts(self.bm, targetmap=targetmap)
        self.map = {k: targetmap.get(v, v) for k, v in self.map.items()}
        self.map = {k: v for k, v in self.map.items() if v.is_valid}
        return len(targetmap)


def flat_fill(bm, loop, join=True):
    """The fewest faces for a small flat region bounded by loop (BMVerts in order, a simple polygon in its own plane):
    a constrained Delaunay of the outline alone (the triangulation with the best smallest angles), paired into quads
    where that makes a good quad. Returns the faces it leaves in bm. Use it for small regions only: over a large region
    with few outline points it makes a web of long triangles; lay large flat parts out as quads on the grid's columns
    instead."""
    import bmesh
    from mathutils.geometry import delaunay_2d_cdt
    pts = [v.co for v in loop]
    n = len(pts)
    nrm = Vector()
    for i in range(n):
        a_, b_ = pts[i], pts[(i + 1) % n]
        nrm += Vector(((a_.y - b_.y) * (a_.z + b_.z), (a_.z - b_.z) * (a_.x + b_.x), (a_.x - b_.x) * (a_.y + b_.y)))
    nrm.normalize()
    u = (pts[1] - pts[0]).normalized()
    u = (u - nrm * u.dot(nrm)).normalized()
    w = nrm.cross(u)
    poly = [Vector(((p - pts[0]).dot(u), (p - pts[0]).dot(w))) for p in pts]

    def inside(q):
        c = False
        for i in range(n):
            a_, b_ = poly[i], poly[i - 1]
            if (a_.y > q.y) != (b_.y > q.y) and q.x < a_.x + (q.y - a_.y) * (b_.x - a_.x) / (b_.y - a_.y):
                c = not c
        return c
    vs, es, fs, orig_v, oe, of = delaunay_2d_cdt(poly, [(i, (i + 1) % n) for i in range(n)], [], 0, 1e-9)
    back = [min(o) if o else None for o in orig_v]
    tris = []
    for f in fs:
        c = sum((vs[i] for i in f), Vector((0.0, 0.0))) / 3
        # CDT works in single precision: collinear outline points give triangles of about 1e-8, not 0
        if abs((vs[f[1]] - vs[f[0]]).cross(vs[f[2]] - vs[f[0]])) > 1e-6 and inside(c):
            tris.append(bm.faces.new([loop[back[i]] for i in f]))
    if not join:
        return tris
    for f in tris:
        f.normal_update()          # new faces have no normal yet, and join_triangles compares normals (5.2.2: no joins)
    # join_triangles removes the triangles it pairs and returns only the new quads
    quads = bmesh.ops.join_triangles(bm, faces=tris, angle_face_threshold=math.radians(2.0),
                                     angle_shape_threshold=math.radians(60.0))["faces"]
    return [f for f in tris if f.is_valid] + list(quads)


def thin_plate_heights(points, tris, fixed, use_scipy=None):
    """Least-bending (biharmonic) heights over a plan triangulation. points: list of (x, y); tris: index triples;
    fixed: {index: z}. Hold known sections two rows deep so slopes carry across: a plane or a quadratic held that way is
    reproduced exactly. Returns a list of z. Needs numpy (Blender bundles it). use_scipy: None = scipy's sparse solver
    when importable, else a dense numpy solve (fine to a few thousand points); True = require scipy; False = numpy."""
    import numpy as np
    P = np.asarray(points, float)
    n = len(P)
    I, J, W = [], [], []
    area = np.zeros(n)
    for t in tris:
        ar = abs(_cross2(P[t[1]] - P[t[0]], P[t[2]] - P[t[0]])) / 2
        for k in range(3):
            i0, i1, i2 = t[k], t[(k + 1) % 3], t[(k + 2) % 3]
            u, v = P[i1] - P[i0], P[i2] - P[i0]
            cot = float(np.dot(u, v)) / max(abs(_cross2(u, v)), 1e-12)
            I += [i1, i2, i1, i2]
            J += [i2, i1, i1, i2]
            W += [0.5 * cot, 0.5 * cot, -0.5 * cot, -0.5 * cot]
            area[t[k]] += ar / 3
    inv_area = 1.0 / np.maximum(area, 1e-12)
    Z = np.zeros(n)
    fx = np.array(sorted(fixed), dtype=int)
    Z[fx] = [fixed[i] for i in fx]
    fr = np.setdiff1d(np.arange(n), fx)
    sparse = None
    if use_scipy is not False:
        try:
            import scipy.sparse as sparse
            import scipy.sparse.linalg as sparse_linalg
        except ImportError:
            if use_scipy:
                raise
            sparse = None
    if sparse is not None:
        L = sparse.csr_matrix((W, (I, J)), shape=(n, n))
        Q = (L.T @ sparse.diags(inv_area) @ L).tocsr()
        Z[fr] = sparse_linalg.spsolve(Q[fr][:, fr].tocsc(), -Q[fr][:, fx] @ Z[fx])
    else:
        L = np.zeros((n, n))
        np.add.at(L, (np.array(I, dtype=int), np.array(J, dtype=int)), W)
        Q = L.T @ (L * inv_area[:, None])
        Z[fr] = np.linalg.solve(Q[np.ix_(fr, fr)], -Q[np.ix_(fr, fx)] @ Z[fx])
    return Z.tolist()


def grid_triangles(n_cols, n_rows):
    """Index triples for a (column-major) n_cols x n_rows point grid, for thin_plate_heights."""
    tris = []
    for j in range(n_cols - 1):
        for i in range(n_rows - 1):
            a, b, c, d = j * n_rows + i, (j + 1) * n_rows + i, (j + 1) * n_rows + i + 1, j * n_rows + i + 1
            tris += [(a, b, c), (a, c, d)]
    return tris
