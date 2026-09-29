"""Building blocks for hand-designed grid topology (see ../references/grid-layout.md).

Load in Blender:  ns = {}; exec(open(r"<skill>/scripts/grid_topology.py", encoding="utf-8").read(), ns)

Faces are made through a `face(verts)` callable you pass in (for example `lambda vs: bm.faces.new(vs)`), so the helpers
work with plain bmesh or with a generator's own mesh wrapper. Points are mathutils.Vector.
"""

import math

from mathutils import Vector


def arc_segments(radius, span_deg, tol, max_edge=None):
    """Segments for an arc of `radius` over `span_deg`: enough to keep the chord sag within `tol`, and (if given) no
    segment longer than `max_edge`."""
    step = 2.0 * math.degrees(math.acos(max(-1.0, 1.0 - tol / radius)))
    n = max(1, math.ceil(span_deg / step))
    if max_edge:
        n = max(n, math.ceil(math.radians(span_deg) * radius / max_edge))
    return n


def zone_stations(breaks, step, floors=None, multiple=None, adjust=None):
    """Stations from breaks[0] to breaks[-1], evenly spaced inside each zone between consecutive breaks, about `step`
    apart. floors: {zone index: minimum segments}. multiple: make the total segment count a multiple of this by adding
    segments to zone `adjust` (default the longest). Returns (stations, segments per zone)."""
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
            if all(vs):
                out.append(face(vs))
    return out


def step_3to1(face, new_vert, top, bottom, mid_at):
    """A 3 to 1 reduction band: top has 3n + 1 verts, bottom n + 1. For each group of three top segments two points are
    added mid-band (new_vert(co)) at mid_at(f, c0, c1, k) -> co, k = 1 or 2 for the point under f1 or f2, and four
    quads are made: [f0 f1 p c0] [f1 f2 q p] [f2 f3 c1 q] [p q c1 c0]."""
    assert (len(top) - 1) == 3 * (len(bottom) - 1), "top must have three segments per bottom segment"
    out = []
    for s in range(0, len(top) - 1, 3):
        f0, f1, f2, f3 = top[s:s + 4]
        c0, c1 = bottom[s // 3], bottom[s // 3 + 1]
        p, q = new_vert(mid_at(f1, c0, c1, 1)), new_vert(mid_at(f2, c0, c1, 2))
        out += [face([f0, f1, p, c0]), face([f1, f2, q, p]), face([f2, f3, c1, q]), face([p, q, c1, c0])]
    return out


def mid_between(surface=None):
    """A mid_at for step_3to1: halfway between f and the matching point on the bottom segment (1/3 or 2/3 along it),
    optionally moved onto a surface (surface(co) -> co)."""
    def mid(f, c0, c1, k):
        co = (f.co + c0.co.lerp(c1.co, k / 3.0)) / 2.0
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
    once. Coordinates reached by different sums can land either side of a rounding step, so also call weld() (remove
    doubles within dist on the cached verts only) before adding separate islands."""
    def __init__(self, bm, digits=6):
        self.bm, self.digits, self.map = bm, digits, {}

    def get(self, co):
        k = tuple(round(c, self.digits) for c in co)
        if k not in self.map:
            self.map[k] = self.bm.verts.new(co)
        return self.map[k]

    def weld(self, dist=1e-5):
        import bmesh
        bmesh.ops.remove_doubles(self.bm, verts=[v for v in self.map.values() if v.is_valid], dist=dist)


def flat_fill(bm, loop, join=True):
    """The fewest faces for a small flat region bounded by loop (BMVerts in order, a simple polygon in its own plane):
    a constrained Delaunay of the outline alone (the triangulation with the best smallest angles), paired into quads
    where that makes a good quad. Use it for small regions only: over a large region with few outline points it makes a
    web of long triangles; lay large flat parts out as quads on the grid's columns instead."""
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
    if join:
        bmesh.ops.join_triangles(bm, faces=tris, angle_face_threshold=math.radians(2.0),
                                 angle_shape_threshold=math.radians(60.0))
    return tris


def thin_plate_heights(points, tris, fixed):
    """Least-bending (biharmonic) heights over a plan triangulation. points: list of (x, y); tris: index triples;
    fixed: {index: z}. Hold known sections two rows deep so slopes carry across. Returns a list of z. Needs scipy (it
    ships with Blender's Python)."""
    import numpy as np
    import scipy.sparse as sp
    import scipy.sparse.linalg as spl
    P = np.asarray(points, float)
    n = len(P)
    I, J, W = [], [], []
    area = np.zeros(n)
    for t in tris:
        ar = abs(np.cross(P[t[1]] - P[t[0]], P[t[2]] - P[t[0]])) / 2
        for k in range(3):
            i0, i1, i2 = t[k], t[(k + 1) % 3], t[(k + 2) % 3]
            u, v = P[i1] - P[i0], P[i2] - P[i0]
            cot = np.dot(u, v) / max(abs(np.cross(u, v)), 1e-12)
            I += [i1, i2, i1, i2]
            J += [i2, i1, i1, i2]
            W += [0.5 * cot, 0.5 * cot, -0.5 * cot, -0.5 * cot]
            area[t[k]] += ar / 3
    L = sp.csr_matrix((W, (I, J)), shape=(n, n))
    Q = (L.T @ sp.diags(1.0 / np.maximum(area, 1e-12)) @ L).tocsr()
    Z = np.zeros(n)
    fx = np.array(sorted(fixed))
    Z[fx] = [fixed[i] for i in fx]
    fr = np.setdiff1d(np.arange(n), fx)
    Z[fr] = spl.spsolve(Q[fr][:, fr].tocsc(), -Q[fr][:, fx] @ Z[fx])
    return Z.tolist()


def grid_triangles(n_cols, n_rows):
    """Index triples for a (column-major) n_cols x n_rows point grid, for thin_plate_heights."""
    tris = []
    for j in range(n_cols - 1):
        for i in range(n_rows - 1):
            a, b, c, d = j * n_rows + i, (j + 1) * n_rows + i, (j + 1) * n_rows + i + 1, j * n_rows + i + 1
            tris += [(a, b, c), (a, c, d)]
    return tris
