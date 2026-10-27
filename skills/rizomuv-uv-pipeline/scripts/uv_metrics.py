"""Measure a UV layout: distortion, texel density, coverage, overlaps, padding, margin, flips, fragmentation,
bounds, and where its seams run (visible_seams). Gate it.

Host: any Python with numpy (Blender's bundled Python has it). No bpy, no RizomUV: it works on the same flat
arrays RizomUV uses (see rizom_uv.py for the layout), so it can grade UVs from any tool. blender_rizom.py has
mesh_arrays() and uv_arrays() to get them from a Blender object and layer.

    import uv_metrics as um
    rep = um.report(mesh, uvw_ids, uvw, map_px=1024, pad_px=16, margin_px=8)
    um.grade(rep)                             # [] when it passes, else readable failures (distortion and layout)
    um.check_gate(rep["distortion"])          # the distortion gate alone

grade() is the one verdict the pipeline uses: the distortion gate (GATE, a partial gate merges over it) plus the
layout checks (inside 0-1, no overlap, padding and margin at least what was asked, no flipped polygons) and, for a
filled texture pack, a coverage floor (MIN_FILL_COVERAGE, lowered for long thin pieces by coverage_floor()).
For a lightmap layer, call report() with map_px = the renderer's lightmap footprint in texels at the layout's
measured bounding-box share (bbox_share), pad_px=2,
margin_px=1 and pad_tol_px=0: the padding and margin are then checked in lightmap texels.

Triangulation: never fans, and never dependent on which corner a polygon starts at. A concave quad is split
through its reflex corner (the only valid split). A convex quad is split along the diagonal its UV layout was
flattened with: the split with the lower worst-case angular distortion (the shorter 3D diagonal on a tie). N-gons
are ear-clipped in their best-fit plane. Every measure uses the same triangles. A strongly non-planar quad looks
different depending on the split the engine uses; distortion() counts quads whose two splits differ by more than
10% as split_sensitive_quads. When that is non-zero, triangulate before unwrapping (so RizomUV, this grade and the
engine all see the same triangles).

Definitions (area-weighted over those triangles):
    angular   sigma1/sigma2 of the 3D->UV Jacobian. 1.0 = shape kept; 1.15 = a square drawn 15% longer one way
              p95 and p99 are the body and the tail; angular_max is the worst triangle that is not a sliver in 3D
              (slivers have no meaningful shape); angular_max_all includes them
    area      |log2(sigma1*sigma2 / island mean)|. 0 = even density inside each island; 0.2 = 1.15x apart
    global    |log2(sigma1*sigma2 / mesh mean)|. Same, but across islands (does packing keep one density?)
    islands_per_100_faces  fragmentation, counted per connected shell against its planar regions (faces joined
              across non-seam edges at under the preset's SharpEdges.AngleMin): only a shell cut into more than
              FRAGMENT_FREE_ISLANDS islands and into more islands than it has regions counts, as its islands beyond
              its regions per 100 of its faces; 0 when none does. A crate of planks, a mitred frame (16 faces, 16
              regions) and a 5-step stair (14 regions) are not fragmented; one flat or smooth shell in confetti is
    visible seams  metres of UV seam through smooth surface (dihedral < 15 deg) facing up or to the front (-Y), not
              marked in the seed: report()["seams"]; advisory (visible_seam_warning), never part of grade()
Polygon areas (texel density, linear ratio) use the exact polygon area (Newell in 3D, shoelace in UV).
"""

import numpy as np

# Default UV0 gate (texture channel). The values are the uv-unwrapping skill's (it owns them); measured on RizomUV
# 2027.0.598 (see ../references/distortion-and-quality.md). angular_p95/area: a well-unwrapped organic prop
# passes, the default QuadLoopCutter unwrap of a curved body fails (it measured angular p95 1.44, area p95 0.50).
# angular_p99: the tail p95 hides. angular_max: a hard limit on the worst non-sliver triangle (folds and collapsed
# UVs). island_*: the same p95 limits on every island holding ISLAND_MIN_SHARE of the area (the worst one), since
# the whole-object numbers hide a small stretched island (a label); area_local_max: log2 of the worst non-sliver
# face's density against its island's (a patch at 2x or 1/2 the texel density). area_global_mean and
# islands_per_100_faces: kept by this grader for its retries (shattering, uneven packs).
GATE = {"angular_p95": 1.15, "angular_p99": 1.5, "angular_max": 2.0, "area_local_p95": 0.20,
        "island_angular_p95": 1.15, "island_area_local_p95": 0.20, "area_local_max": 2.0,
        "area_global_mean": 0.05, "islands_per_100_faces": 25.0}
ISLAND_MIN_SHARE = 0.005        # islands with at least this share of the area meet the p95 limits on their own
FRAGMENT_FREE_ISLANDS = 12      # per shell: a box's 6 islands or a small kit piece's dozen are never "fragmented"
SLIVER_QUALITY = 0.02           # triangle quality 4*sqrt(3)*area / sum(edge^2): 1 equilateral, < 0.02 a sliver
PAD_TOL_PX = 0.5                # RizomUV's PaddingPerfect pads on a pixel grid: measured gaps 3.5-3.9 px at pad 4
MIN_FILL_COVERAGE = 0.35        # a filled texture pack below this is one sprawling island or worse: measured
                                # 2026-10-17, 1-segment chamfered boxes under the hard preset covered 0.10-0.22
SHAPE_COVERAGE_SHARE = 0.8      # a long thin piece cannot fill a square tile: its floor drops to this share of
                                # shape_coverage_limit (a 3 m beam 0.16 x 0.8 = 0.13), never below what it allows
FILL_COVERAGE_MAX_ISLANDS = 100 # sprawl means few islands: with hundreds the map/64 gaps take the tile (a craggy
                                # 5120-face rock, 532 islands: 0.20), so the floor applies up to this many islands
FRAGMENT_REGION_ANGLE = 40.0    # degrees: the hard preset's SharpEdges.AngleMin (unwrap_gated passes each attempt's)
# Visible seams (visible_seams): advisory, never a gate failure (see the function and distortion-and-quality.md).
VIEW_DIRS = ((0.0, 0.0, 1.0), (0.0, -1.0, 0.0))   # seen from above (+Z) and from the front (-Y, a kit piece's front)
SMOOTH_SEAM_DEG = 15.0          # dihedral under which a seam runs through smooth surface, not along an edge: a
                                # hard-surface seam sits on an edge of 30 deg or more (3-segment chamfer, 90 deg box)
VIEW_FACING = 0.5               # cos 60 deg: a face turned further from the viewer shows under half its area
SEAM_UV_TOL = 1e-5              # UV units (0.01 px at 1024): unwelded corners closer than this are not a seam
VISIBLE_SEAM_NOTE_M = 0.25      # note unmarked visible seams from this many metres (one 25 cm checker square at
VISIBLE_SEAM_NOTE_SHARE = 0.25  # 1 UV/m), or from this share of the bounding-box diagonal on a smaller piece.
                                # Measured 2026-10-24: autoseams on cushions 0.34-2.04 m, panel seams marked 0.0


# ----------------------------------------------------------------------------------------------- input
def _arrays(mesh, uvw_ids, uvw):
    sizes = np.asarray(mesh["sizes"], dtype=np.int64)
    xid = np.asarray(mesh["xyz_ids"], dtype=np.int64)
    xyz = np.asarray(mesh["xyz"], dtype=np.float64).reshape(-1, 3)
    uid = np.asarray(uvw_ids, dtype=np.int64)
    uv = np.asarray(uvw, dtype=np.float64).reshape(-1, 3)[:, :2]
    if len(sizes) == 0:
        raise ValueError("the mesh has no polygons")
    if sizes.min() < 3:
        raise ValueError("a polygon has fewer than 3 corners")
    if int(sizes.sum()) != len(xid) or len(xid) != len(uid):
        raise ValueError("corner counts disagree: sizes sum %d, xyz_ids %d, uvw_ids %d"
                         % (int(sizes.sum()), len(xid), len(uid)))
    if xid.max() >= len(xyz) or uid.max() >= len(uv) or xid.min() < 0 or uid.min() < 0:
        raise ValueError("a corner index points outside xyz or uvw")
    return sizes, xid, xyz, uid, uv


def _starts(sizes):
    return np.concatenate([[0], np.cumsum(sizes)[:-1]]).astype(np.int64)


def _next_corner(sizes):
    """Index of the next corner in the same polygon, for every corner."""
    starts = _starts(sizes)
    nxt = np.arange(int(sizes.sum()), dtype=np.int64) + 1
    nxt[starts + sizes - 1] = starts
    return nxt


def _face_of_corner(sizes):
    return np.repeat(np.arange(len(sizes)), sizes)


# ----------------------------------------------------------------------------------------------- triangulation
def triangles(sizes):
    """Fan triangulation from corner 0: (T, 3) corner indices and the polygon of each triangle. Kept only for
    comparisons: it depends on the start corner and is wrong for concave polygons. Use triangulate()."""
    sizes = np.asarray(sizes, dtype=np.int64)
    starts = _starts(sizes)
    face = np.repeat(np.arange(len(sizes)), np.maximum(sizes - 2, 0))
    k = np.concatenate([np.arange(1, n - 1) for n in sizes if n > 2]) if len(face) else np.zeros(0, np.int64)
    s = starts[face]
    return np.stack([s, s + k, s + k + 1], axis=1), face


def _newell(V):
    """Area vector (x2) of one or many polygons given as (..., n, 3)."""
    W = np.roll(V, -1, axis=-2)
    return np.stack([np.sum((V[..., 1] - W[..., 1]) * (V[..., 2] + W[..., 2]), -1),
                     np.sum((V[..., 2] - W[..., 2]) * (V[..., 0] + W[..., 0]), -1),
                     np.sum((V[..., 0] - W[..., 0]) * (V[..., 1] + W[..., 1]), -1)], -1)


def _ear_clip(V):
    """Triangles (local corner indices) of one simple polygon, ear-clipped in its best-fit plane."""
    n = len(V)
    N = _newell(V)
    ax = int(np.argmax(np.abs(N)))
    i, j = ((1, 2), (2, 0), (0, 1))[ax]
    pts = V[:, [i, j]] if N[ax] >= 0 else V[:, [j, i]]          # counter-clockwise in 2D

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def inside(p, a, b, c):
        return cross(a, b, p) >= 0 and cross(b, c, p) >= 0 and cross(c, a, p) >= 0

    idx = list(range(n))
    out = []
    while len(idx) > 3:
        m = len(idx)
        for k in range(m):
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % m]
            if cross(pts[a], pts[b], pts[c]) <= 0:
                continue                                         # reflex or collinear corner: not an ear
            if any(inside(pts[o], pts[a], pts[b], pts[c]) for o in idx
                   if o not in (a, b, c) and not np.allclose(pts[o], pts[a]) and not np.allclose(pts[o], pts[b])
                   and not np.allclose(pts[o], pts[c])):
                continue
            out.append((a, b, c))
            idx.pop(k)
            break
        else:
            break                                                # self-intersecting or degenerate: fan the rest
    out += [(idx[0], idx[k], idx[k + 1]) for k in range(1, len(idx) - 1)]
    return out


def _tri_angular(P, U):
    """sigma1/sigma2 per triangle for (N, 3, 3) positions and (N, 3, 2) UVs (inf where undefined)."""
    e1, e2 = P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]
    n = np.cross(e1, e2)
    ln, l1 = np.linalg.norm(n, axis=1), np.linalg.norm(e1, axis=1)
    ok = (ln > 1e-300) & (l1 > 1e-300) & np.all(np.isfinite(U), axis=(1, 2))
    out = np.full(len(P), np.inf)
    if not ok.any():
        return out
    e1, e2, n, U = e1[ok], e2[ok], n[ok] / ln[ok][:, None], U[ok]
    x = e1 / l1[ok][:, None]
    y = np.cross(n, x)
    S = np.stack([np.stack([np.sum(e1 * x, 1), np.sum(e2 * x, 1)], 1),
                  np.stack([np.sum(e1 * y, 1), np.sum(e2 * y, 1)], 1)], 1)
    T = np.stack([U[:, 1] - U[:, 0], U[:, 2] - U[:, 0]], 2)
    sv = np.linalg.svd(T @ np.linalg.inv(S), compute_uv=False)
    out[ok] = np.where(sv[:, 1] > 1e-12 * np.maximum(sv[:, 0], 1e-300), sv[:, 0] / np.maximum(sv[:, 1], 1e-300), 1e6)
    return out


def triangulate(sizes, xyz_ids, xyz, uvw_ids=None, uvw=None, info=None):
    """(T, 3) corner indices and the polygon of each triangle. Concave quads through the reflex corner; convex
    quads along the diagonal their UV layout fits best (lower worst-case angular distortion), or the shorter 3D
    diagonal without UVs or on a tie; n-gons ear-clipped. Independent of the start corner. Pass a dict as info to
    receive "split_sensitive_quads" and "split_sensitive_area" (quads whose two splits differ by > 10%)."""
    sizes = np.asarray(sizes, dtype=np.int64)
    xid = np.asarray(xyz_ids, dtype=np.int64)
    P = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)[xid]
    Ucorner = None
    if uvw_ids is not None and uvw is not None:
        Ucorner = np.asarray(uvw, dtype=np.float64).reshape(-1, 3)[:, :2][np.asarray(uvw_ids, dtype=np.int64)]
    starts = _starts(sizes)
    tris, faces = [np.zeros((0, 3), np.int64)], [np.zeros(0, np.int64)]
    t3 = np.nonzero(sizes == 3)[0]
    if len(t3):
        s = starts[t3]
        tris.append(np.stack([s, s + 1, s + 2], 1))
        faces.append(t3)
    q = np.nonzero(sizes == 4)[0]
    if len(q):
        c = starts[q][:, None] + np.arange(4)
        V = P[c]
        V = V - V[:, :1]                                          # precision on far-from-origin meshes
        N = _newell(V)
        turn = np.einsum("qkj,qj->qk", np.cross(V - np.roll(V, 1, axis=1), np.roll(V, -1, axis=1) - V), N)
        reflex = turn < -1e-12 * np.maximum(np.einsum("qj,qj->q", N, N), 1e-300)[:, None]
        use13 = np.linalg.norm(V[:, 3] - V[:, 1], axis=1) < np.linalg.norm(V[:, 2] - V[:, 0], axis=1)
        has = reflex.any(1)
        if Ucorner is not None:
            W = Ucorner[c]
            m02 = np.maximum(_tri_angular(V[:, [0, 1, 2]], W[:, [0, 1, 2]]),
                             _tri_angular(V[:, [0, 2, 3]], W[:, [0, 2, 3]]))
            m13 = np.maximum(_tri_angular(V[:, [1, 2, 3]], W[:, [1, 2, 3]]),
                             _tri_angular(V[:, [1, 3, 0]], W[:, [1, 3, 0]]))
            with np.errstate(invalid="ignore"):                   # inf - inf on degenerate quads: no clear winner
                clear = np.abs(m02 - m13) > 1e-9 * np.maximum(np.minimum(m02, m13), 1.0)
            use13 = np.where(clear, m13 < m02, use13)
            if info is not None:
                lo, hi = np.minimum(m02, m13), np.maximum(m02, m13)
                sens = (~has) & np.isfinite(lo) & (hi > 1.1 * lo)
                area = 0.5 * np.linalg.norm(N, axis=1)
                info["split_sensitive_quads"] = int(np.count_nonzero(sens))
                info["split_sensitive_area"] = float(area[sens].sum())
        use13 = np.where(has, (np.argmax(reflex, 1) % 2) == 1, use13)
        a = np.where(use13[:, None], c[:, [1, 2, 3]], c[:, [0, 1, 2]])
        b = np.where(use13[:, None], c[:, [1, 3, 0]], c[:, [0, 2, 3]])
        tris += [a, b]
        faces += [q, q]
    for f in np.nonzero(sizes > 4)[0]:
        idx = starts[f] + np.arange(sizes[f])
        t = np.asarray(_ear_clip(P[idx] - P[idx[0]]), dtype=np.int64)
        tris.append(idx[t])
        faces.append(np.full(len(t), f, np.int64))
    tri, face = np.concatenate(tris), np.concatenate(faces)
    order = np.argsort(face, kind="stable")
    return tri[order], face[order]


def islands(sizes, uvw_ids):
    """Island index per polygon: polygons sharing a UV vertex belong to one island."""
    uid = np.asarray(uvw_ids, dtype=np.int64)
    parent = np.arange(uid.max() + 1 if len(uid) else 0)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    c = 0
    firsts = []
    for n in np.asarray(sizes, dtype=np.int64).tolist():
        r0 = find(uid[c])
        for i in range(c + 1, c + n):
            r = find(uid[i])
            if r != r0:
                parent[r] = r0
        firsts.append(uid[c])
        c += n
    roots = [find(f) for f in firsts]
    lut = {}
    return np.array([lut.setdefault(r, len(lut)) for r in roots], dtype=np.int64)


def _wpct(values, weights, q):
    order = np.argsort(values)
    cw = np.cumsum(weights[order])
    return float(values[order][min(np.searchsorted(cw, q * cw[-1]), len(values) - 1)])


def _prep(mesh, uvw_ids, uvw, tri=None, info=None):
    sizes, xid, xyz, uid, uv = _arrays(mesh, uvw_ids, uvw)
    if tri is None:
        tri = triangulate(sizes, xid, xyz, uid, np.asarray(uvw, dtype=np.float64), info=info)
    return sizes, xid, xyz, uid, uv, tri


# ----------------------------------------------------------------------------------------------- measures
def distortion(mesh, uvw_ids, uvw, tri=None, info=None, region_angle=FRAGMENT_REGION_ANGLE):
    info = {} if info is None else info
    sizes, xid, xyz, uid, uv, (tri, face) = _prep(mesh, uvw_ids, uvw, tri, info)
    P = xyz[xid[tri]]                                     # (T, 3, 3)
    U = uv[uid[tri]]                                      # (T, 3, 2)
    e1, e2 = P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]
    n = np.cross(e1, e2)
    a3 = np.linalg.norm(n, axis=1) / 2
    ok = a3 > max(float(a3.max()) * 1e-10, 1e-300) if len(a3) else a3 > 0
    if not ok.any():
        raise ValueError("every triangle has zero 3D area: the mesh is degenerate")
    finite = np.all(np.isfinite(U), axis=(1, 2))
    e1, e2, n, a3, U, face, P = e1[ok], e2[ok], n[ok], a3[ok], U[ok], face[ok], P[ok]
    finite = finite[ok]
    U = np.where(finite[:, None, None], U, 0.0)
    x = e1 / np.linalg.norm(e1, axis=1)[:, None]
    y = np.cross(n / np.linalg.norm(n, axis=1)[:, None], x)
    S = np.stack([np.stack([np.sum(e1 * x, 1), np.sum(e2 * x, 1)], 1),
                  np.stack([np.sum(e1 * y, 1), np.sum(e2 * y, 1)], 1)], 1)          # 3D edges in the plane
    T = np.stack([U[:, 1] - U[:, 0], U[:, 2] - U[:, 0]], 2)                          # UV edges (columns)
    J = T @ np.linalg.inv(S)
    sv = np.linalg.svd(J, compute_uv=False)
    s1, s2 = sv[:, 0], sv[:, 1]
    ang = np.where(s2 > 1e-12 * np.maximum(s1, 1e-300), s1 / np.maximum(s2, 1e-300), 1e6)
    ang = np.where(finite, ang, np.inf)
    R = np.where(finite, s1 * s2, np.nan)                 # UV area per 3D area
    ell = np.sum((P[:, 1] - P[:, 0]) ** 2 + (P[:, 2] - P[:, 1]) ** 2 + (P[:, 0] - P[:, 2]) ** 2, axis=1)
    quality = 4 * np.sqrt(3) * a3 / np.maximum(ell, 1e-300)
    shaped = quality >= SLIVER_QUALITY
    w = a3 / a3.sum()
    isl_face = islands(sizes, uid)
    isl = isl_face[face]
    good = finite & (R > 0)
    imean = np.zeros(isl.max() + 1)
    asum = np.zeros(isl.max() + 1)
    np.add.at(imean, isl[good], (a3 * R)[good])
    np.add.at(asum, isl[good], a3[good])
    imean /= np.maximum(asum, 1e-300)
    gmean = float(np.sum((w * R)[good])) / max(float(np.sum(w[good])), 1e-300)
    local = np.where(good, np.abs(np.log2(np.maximum(R, 1e-300) / np.maximum(imean[isl], 1e-300))), np.inf)
    glob = np.where(good, np.abs(np.log2(np.maximum(R, 1e-300) / max(gmean, 1e-300))), np.inf)
    nisl, nfaces = int(isl_face.max() + 1), len(sizes)
    isl_a95, isl_l95 = 1.0, 0.0
    big = np.flatnonzero(asum >= ISLAND_MIN_SHARE * max(float(asum.sum()), 1e-300))
    if len(big):
        order = np.argsort(isl, kind="stable")
        cuts = np.searchsorted(isl[order], np.arange(len(asum) + 1))
        for i in big:
            m = order[cuts[i]:cuts[i + 1]]
            m = m[good[m]]
            isl_a95 = max(isl_a95, _wpct(ang[m], a3[m], 0.95))
            isl_l95 = max(isl_l95, _wpct(local[m], a3[m], 0.95))
    even = good & shaped
    frag, nshells = fragmentation(sizes, xid, isl_face, regions=lambda: planar_regions(mesh, region_angle))
    return {"angular_mean": round(float(np.sum(w * ang)), 4), "angular_p95": round(_wpct(ang, w, 0.95), 4),
            "angular_p99": round(_wpct(ang, w, 0.99), 4),
            "angular_max": round(float(ang[shaped].max()) if shaped.any() else float(ang.max()), 3),
            "angular_max_all": round(float(ang.max()), 3),
            "area_local_mean": round(float(np.sum(w * local)), 4), "area_local_p95": round(_wpct(local, w, 0.95), 4),
            "island_angular_p95": round(float(isl_a95), 4), "island_area_local_p95": round(float(isl_l95), 4),
            "area_local_max": round(float(local[even].max()) if even.any() else 0.0, 4),
            "area_global_mean": round(float(np.sum(w * glob)), 4), "linear_ratio": float(np.sqrt(max(gmean, 0.0))),
            "finite": bool(finite.all()), "islands": nisl, "faces": nfaces, "shells": nshells,
            "islands_per_100_faces": frag, "islands_per_100_faces_all": round(100.0 * nisl / nfaces, 2),
            "split_sensitive_quads": info.get("split_sensitive_quads", 0),
            "split_sensitive_area_share": round(info.get("split_sensitive_area", 0.0) / float(a3.sum()), 5)}


def planar_regions(mesh, angle_deg=FRAGMENT_REGION_ANGLE):
    """Region index per polygon: polygons joined across edges that are not seams (both ends share their seed UV
    vertex in mesh["uvw_ids"]) and whose normals differ by less than angle_deg. The islands a hard-surface piece
    falls into naturally: a mitred frame with mitre seams has 16 regions in 16 faces, a 5-step stair 14 (treads,
    risers, back, bottom and two sides)."""
    sizes = np.asarray(mesh["sizes"], dtype=np.int64)
    xid = np.asarray(mesh["xyz_ids"], dtype=np.int64)
    sid = np.asarray(mesh["uvw_ids"], dtype=np.int64)
    xyz = np.asarray(mesh["xyz"], dtype=np.float64).reshape(-1, 3)
    starts, nxt, foc = _starts(sizes), _next_corner(sizes), _face_of_corner(sizes)
    P = xyz[xid] - xyz[xid][starts][foc]
    nrm = np.add.reduceat(np.cross(P, P[nxt]), starts, axis=0)                 # Newell
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-300)
    a, b = xid, xid[nxt]
    key = np.stack([np.minimum(a, b), np.maximum(a, b)], 1)
    uv_ends = np.where((a <= b)[:, None], np.stack([sid, sid[nxt]], 1), np.stack([sid[nxt], sid], 1))
    order = np.lexsort((key[:, 1], key[:, 0]))
    k, u, f = key[order], uv_ends[order], foc[order]
    i = np.flatnonzero(np.all(k[1:] == k[:-1], axis=1) & (k[1:, 0] != k[1:, 1]))
    fa, fb = f[i], f[i + 1]
    keep = np.all(u[i] == u[i + 1], axis=1) & (np.einsum("ij,ij->i", nrm[fa], nrm[fb])
                                               > np.cos(np.radians(float(angle_deg))))
    parent = list(range(len(sizes)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for p, q in zip(fa[keep].tolist(), fb[keep].tolist()):
        rp, rq = find(p), find(q)
        if rp != rq:
            parent[rq] = rp
    lut = {}
    return np.array([lut.setdefault(find(x), len(lut)) for x in range(len(sizes))], dtype=np.int64)


def fragmentation(sizes, xyz_ids, island_of_face, regions=None):
    """(islands beyond the planar regions per 100 faces, over the shells cut into more than FRAGMENT_FREE_ISLANDS
    islands and into more islands than regions; shell count). A shell is a connected piece of the mesh (polygons
    sharing 3D vertices). regions: a function returning planar_regions() (called only when a shell has more than
    FRAGMENT_FREE_ISLANDS islands); None counts every face as its own region. 0.0 when no shell is fragmented."""
    shell = islands(sizes, xyz_ids)                       # connected by shared 3D vertices
    n = int(shell.max()) + 1

    def per_shell(labels):
        pairs = np.unique(np.stack([shell, labels], 1), axis=0)
        return np.bincount(pairs[:, 0], minlength=n)
    isl_per_shell = per_shell(island_of_face)
    bad = isl_per_shell > FRAGMENT_FREE_ISLANDS
    if not bad.any():
        return 0.0, n
    faces_per_shell = np.bincount(shell, minlength=n)
    reg_per_shell = per_shell(regions()) if regions is not None else faces_per_shell
    excess = isl_per_shell - reg_per_shell
    bad &= excess > 0
    if not bad.any():
        return 0.0, n
    frag = 100.0 * float(excess[bad].sum()) / float(faces_per_shell[bad].sum())
    return round(frag, 2), n


def polygon_areas(mesh, uvw_ids, uvw):
    """Exact (3D, UV) area of every polygon: Newell's formula in 3D, the shoelace formula in UV. Concave
    polygons are handled; a non-planar polygon gets its projected (vector) area."""
    sizes, xid, xyz, uid, uv = _arrays(mesh, uvw_ids, uvw)
    starts, nxt, foc = _starts(sizes), _next_corner(sizes), _face_of_corner(sizes)
    P = xyz[xid]
    P = P - P[starts][foc]
    A3 = 0.5 * np.linalg.norm(np.add.reduceat(np.cross(P, P[nxt]), starts, axis=0), axis=1)
    U = uv[uid]
    A2 = 0.5 * np.abs(np.add.reduceat(U[:, 0] * U[nxt, 1] - U[nxt, 0] * U[:, 1], starts))
    return A3, A2


def texel_density(mesh, uvw_ids, uvw, map_px):
    """Area-weighted mean texels per mesh unit at map_px, and its coefficient of variation across polygons."""
    A3, A2 = polygon_areas(mesh, uvw_ids, uvw)
    ok = (A3 > 1e-12) & np.isfinite(A2)
    if not ok.any():
        raise ValueError("no polygon with non-zero 3D area")
    td = np.sqrt(A2[ok] / A3[ok]) * map_px
    w = A3[ok] / A3[ok].sum()
    mean = float(np.sum(w * td))
    return {"px_per_unit_mean": round(mean, 2),
            "cv": round(float(np.sqrt(np.sum(w * (td - mean) ** 2)) / mean), 4) if mean > 0 else None}


def raster(mesh, uvw_ids, uvw, res, tri=None):
    """Island-index raster (-1 empty) sampled at pixel centres, and the number of pixels claimed by two or more
    islands. Triangles come from triangulate(), so concave polygons fill exactly their own area."""
    sizes, xid, xyz, uid, uv, (tri, face) = _prep(mesh, uvw_ids, uvw, tri)
    isl = islands(sizes, uid)[face]
    T = uv[uid[tri]] * res
    keep = np.all(np.isfinite(T), axis=(1, 2))
    T, isl = T[keep], isl[keep]
    x0 = np.maximum(np.ceil(T[:, :, 0].min(1) - 0.5), 0).astype(np.int64)
    x1 = np.minimum(np.floor(T[:, :, 0].max(1) - 0.5), res - 1).astype(np.int64)
    y0 = np.maximum(np.ceil(T[:, :, 1].min(1) - 0.5), 0).astype(np.int64)
    y1 = np.minimum(np.floor(T[:, :, 1].max(1) - 0.5), res - 1).astype(np.int64)
    span = np.maximum(x1 - x0, y1 - y0) + 1
    live = (x1 >= x0) & (y1 >= y0)
    pix, own = [], []
    lo = 0
    for cls in (1, 2, 4, 8, 16, 32, 64, 128):
        sel = np.nonzero(live & (span > lo) & (span <= cls))[0]
        lo = cls
        step = max(1, 4_000_000 // (cls * cls))
        for c0 in range(0, len(sel), step):
            t = sel[c0:c0 + step]
            o = np.arange(cls)
            X = x0[t][:, None, None] + o[None, None, :]
            Y = y0[t][:, None, None] + o[None, :, None]
            cx, cy = X + 0.5, Y + 0.5
            (ax, ay), (bx, by), (qx, qy) = [(T[t, k, 0][:, None, None], T[t, k, 1][:, None, None]) for k in range(3)]
            s1 = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
            s2 = (qx - bx) * (cy - by) - (qy - by) * (cx - bx)
            s3 = (ax - qx) * (cy - qy) - (ay - qy) * (cx - qx)
            ins = (((s1 >= 0) & (s2 >= 0) & (s3 >= 0)) | ((s1 <= 0) & (s2 <= 0) & (s3 <= 0)))
            ins &= (X <= x1[t][:, None, None]) & (Y <= y1[t][:, None, None])
            ti, yi, xi = np.nonzero(ins)
            pix.append(Y[ti, yi, 0] * res + X[ti, 0, xi])
            own.append(isl[t][ti])
    for t in np.nonzero(live & (span > lo))[0]:            # very large triangles, one by one
        Xg, Yg = np.meshgrid(np.arange(x0[t], x1[t] + 1), np.arange(y0[t], y1[t] + 1))
        cx, cy = Xg + 0.5, Yg + 0.5
        (ax, ay), (bx, by), (qx, qy) = T[t]
        s1 = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        s2 = (qx - bx) * (cy - by) - (qy - by) * (cx - bx)
        s3 = (ax - qx) * (cy - qy) - (ay - qy) * (cx - qx)
        ins = ((s1 >= 0) & (s2 >= 0) & (s3 >= 0)) | ((s1 <= 0) & (s2 <= 0) & (s3 <= 0))
        pix.append((Yg * res + Xg)[ins])
        own.append(np.full(int(ins.sum()), isl[t]))
    grid = -np.ones(res * res, dtype=np.int64)
    if not pix:
        return grid.reshape(res, res), 0
    pix, own = np.concatenate(pix), np.concatenate(own)
    nisl = int(own.max()) + 1 if len(own) else 1
    key = np.unique(pix * nisl + own)
    upix, uown = key // nisl, key % nisl
    grid[upix] = uown
    claims = np.bincount(upix, minlength=res * res)
    return grid.reshape(res, res), int(np.count_nonzero(claims >= 2))


def padding_violations(grid, pad_px):
    """Legacy raster check: island pairs whose pixels lie closer than pad_px pixels (Euclidean, pixel centres).
    A raster cannot see sub-pixel gaps: it can miss a true gap up to about one pixel short of the padding. Use
    padding_gaps() for an exact answer."""
    d = int(np.ceil(pad_px))
    h, w = grid.shape
    pairs = set()
    for dy in range(-d, d + 1):
        for dx in range(0, d + 1):
            if (dx == 0 and dy <= 0) or (dx * dx + dy * dy) > pad_px * pad_px:
                continue
            a = grid[max(0, -dy):h - max(0, dy), 0:w - dx]
            b = grid[max(0, dy):h + min(0, dy), dx:w]
            m = (a >= 0) & (b >= 0) & (a != b)
            if m.any():
                for p, q in set(zip(a[m].tolist(), b[m].tolist())):
                    pairs.add((min(p, q), max(p, q)))
    return len(pairs)


def _seg_dist(p1, q1, p2, q2):
    """Distance between segments p1q1 and p2q2, broadcast over leading dimensions (2D)."""
    def pt(p, a, b):
        ab = b - a
        t = np.clip(np.sum((p - a) * ab, -1) / np.maximum(np.sum(ab * ab, -1), 1e-30), 0, 1)
        return np.linalg.norm(p - (a + t[..., None] * ab), axis=-1)
    d = np.minimum(np.minimum(pt(p1, p2, q2), pt(q1, p2, q2)), np.minimum(pt(p2, p1, q1), pt(q2, p1, q1)))

    def orient(a, b, c):
        return (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0])
    hit = ((orient(p1, q1, p2) * orient(p1, q1, q2)) < 0) & ((orient(p2, q2, p1) * orient(p2, q2, q1)) < 0)
    return np.where(hit, 0.0, d)


def padding_gaps(mesh, uvw_ids, uvw, map_px, pad_px, tol_px=PAD_TOL_PX):
    """Exact padding near the limit: the boundary-to-boundary Euclidean gap, in pixels at map_px, between islands.
    Returns {"min_gap_px", "pairs_below_min", "worst": [(island a, island b, gap px), ...]}; a pair is below the
    minimum when its gap < pad_px - tol_px (0 = strict). pairs_below_min is exact. Only pairs closer than about
    2 x pad_px are measured, so min_gap_px is the true smallest gap when it is below that, and None when every pair
    of islands is farther apart (or there is only one island)."""
    sizes, xid, xyz, uid, uv = _arrays(mesh, uvw_ids, uvw)
    isl = islands(sizes, uid)[_face_of_corner(sizes)]
    nxt = _next_corner(sizes)
    a, b = uid, uid[nxt]
    lo_, hi_ = np.minimum(a, b), np.maximum(a, b)
    key = lo_ * (int(uid.max()) + 1) + hi_
    _, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    bnd = cnt[inv] == 1
    if isl.max() < 1 or not bnd.any():
        return {"min_gap_px": None, "pairs_below_min": 0, "worst": []}
    A, B, O = uv[a[bnd]] * map_px, uv[b[bnd]] * map_px, isl[bnd]
    keep = np.all(np.isfinite(A), 1) & np.all(np.isfinite(B), 1)
    A, B, O = A[keep], B[keep], O[keep]
    L = max(float(pad_px), 0.5)                              # pieces no longer than the padding
    n = np.maximum(np.ceil(np.linalg.norm(B - A, axis=1) / L), 1).astype(np.int64)
    rep = np.repeat(np.arange(len(A)), n)
    k = np.arange(len(rep)) - np.repeat(np.cumsum(n) - n, n)
    t0, t1 = (k / n[rep])[:, None], ((k + 1) / n[rep])[:, None]
    P0, P1, PO = A[rep] + (B[rep] - A[rep]) * t0, A[rep] + (B[rep] - A[rep]) * t1, O[rep]
    cell = 2.0 * L                                           # pieces closer than the padding share a 3x3 block
    cx = np.floor((P0[:, 0] + P1[:, 0]) / 2 / cell).astype(np.int64)
    cy = np.floor((P0[:, 1] + P1[:, 1]) / 2 / cell).astype(np.int64)
    buckets = {}
    for i, c in enumerate(zip(cx.tolist(), cy.tolist())):
        buckets.setdefault(c, []).append(i)
    K = int(PO.max()) + 1
    keys, gaps = [], []

    def first_per_key(kk, d):
        o = np.lexsort((d, kk))
        kk, d = kk[o], d[o]
        first = np.ones(len(kk), dtype=bool)
        first[1:] = kk[1:] != kk[:-1]
        return kk[first], d[first]
    for (gx, gy), mine in buckets.items():
        near = [j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in buckets.get((gx + dx, gy + dy), ())]
        mi, nj = np.asarray(mine), np.asarray(near)
        diff = PO[mi][:, None] != PO[nj][None, :]
        if not diff.any():
            continue
        ii, jj = np.nonzero(diff)
        d = _seg_dist(P0[mi][ii], P1[mi][ii], P0[nj][jj], P1[nj][jj])
        pa, pb = PO[mi][ii], PO[nj][jj]
        kk, d = first_per_key(np.minimum(pa, pb) * K + np.maximum(pa, pb), d)
        keys.append(kk)
        gaps.append(d)
    if not keys:
        return {"min_gap_px": None, "pairs_below_min": 0, "worst": []}       # every pair farther than ~2 x pad_px
    kk, d = first_per_key(np.concatenate(keys), np.concatenate(gaps))
    o = np.argsort(d, kind="stable")
    worst = [(int(k // K), int(k % K), round(float(g), 3)) for k, g in zip(kk[o][:5], d[o][:5])]
    limit = float(pad_px) - float(tol_px)
    return {"min_gap_px": worst[0][2], "pairs_below_min": int(np.count_nonzero(d < limit)), "worst": worst}


def flipped_polygons(mesh, uvw_ids, uvw):
    """Polygons whose UV winding is clockwise (negative shoelace area): mirrored in UV."""
    sizes, _, _, uid, uv = _arrays(mesh, uvw_ids, uvw)
    starts, nxt = _starts(sizes), _next_corner(sizes)
    U = uv[uid]
    s = np.add.reduceat(U[:, 0] * U[nxt, 1] - U[nxt, 0] * U[:, 1], starts)
    return int(np.count_nonzero(s < 0))


def visible_seams(mesh, uvw_ids, uvw, view_dirs=VIEW_DIRS, smooth_deg=SMOOTH_SEAM_DEG, facing=VIEW_FACING,
                  uv_tol=SEAM_UV_TOL):
    """Where the UV seams run, in mesh units (metres for world-space input). The grade measures distortion only, so
    an autoseam cut across a smooth, visible top passes it; with a tiling texture the pattern jumps at that cut.
    A seam edge is an interior edge (exactly two faces) whose UV coordinates differ across it at either end (more
    than uv_tol): unwelded corners with equal coordinates are not a seam. It is smooth when its two faces meet at a
    dihedral under smooth_deg (a hard-surface seam on a sharp edge never is), and visible when the mean normal of its
    two faces has a component of at least `facing` along one of view_dirs (default: up +Z and the front -Y; None
    counts every direction), with each closed shell turned outward first (an inverted shell would read its top as
    its bottom). Marked: split in the seed topology mesh["uvw_ids"] (the seams you marked; rizom_uv and
    blender_rizom.mesh_arrays seed with them), so the rest are the cuts the unwrapper chose.
    Returns seam_m (every seam), smooth_seam_m, visible_seam_m, visible_seam_unmarked_m, visible_seam_bounds
    ([min xyz, max xyz] of the unmarked visible seams, or None) and size_m (the bounding-box diagonal: the scale of
    visible_seam_warning)."""
    sizes, xid, xyz, uid, uv = _arrays(mesh, uvw_ids, uvw)
    used = xyz[np.unique(xid)]
    size = round(float(np.linalg.norm(used.max(0) - used.min(0))), 3)
    starts, nxt, foc = _starts(sizes), _next_corner(sizes), _face_of_corner(sizes)
    P = xyz[xid] - xyz[xid][starts][foc]
    nrm = np.add.reduceat(np.cross(P, P[nxt]), starts, axis=0)                 # Newell: 2 x the area vector
    a, b = xid, xid[nxt]
    key = np.stack([np.minimum(a, b), np.maximum(a, b)], 1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    k = key[order]
    same = np.all(k[1:] == k[:-1], axis=1) & (k[1:, 0] != k[1:, 1])
    lone = np.r_[True, ~same[:-1]] & np.r_[~same[1:], True]                    # exactly two corners on the edge
    i = np.flatnonzero(same & lone)
    # A closed shell whose normals point inward (bmesh's recalc_face_normals did that to a thin bevelled box) would
    # read its top as its bottom: turn each closed shell outward by the sign of its volume, sum(centroid . area)/3.
    paired = np.zeros(len(xid), dtype=bool)
    paired[order[i]] = paired[order[i + 1]] = True
    shell = islands(sizes, xid)
    open_shell = np.bincount(shell[foc[~paired]], minlength=int(shell.max()) + 1) > 0
    cen = np.add.reduceat(xyz[xid] - xyz.mean(0), starts, axis=0) / sizes[:, None]
    vol = np.bincount(shell, weights=np.einsum("ij,ij->i", cen, nrm), minlength=len(open_shell))
    nrm = np.where(((vol < 0) & ~open_shell)[shell][:, None], -nrm, nrm)
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = np.where(ln > 1e-300, nrm / np.maximum(ln, 1e-300), np.nan)          # zero-area faces: never smooth
    c1, c2 = order[i], order[i + 1]
    out = {"seam_m": 0.0, "smooth_seam_m": 0.0, "visible_seam_m": 0.0, "visible_seam_unmarked_m": 0.0,
           "visible_seam_bounds": None, "size_m": size}
    if not len(c1):
        return out
    agree = xid[c2] == xid[c1]                       # the second face runs the edge the same way: flipped winding
    a1, b1 = c1, nxt[c1]
    a2, b2 = np.where(agree, c2, nxt[c2]), np.where(agree, nxt[c2], c2)

    def split(ids, coords=None):
        if coords is None:                                                      # the seed: split ids are a seam
            return (ids[a1] != ids[a2]) | (ids[b1] != ids[b2])
        with np.errstate(invalid="ignore"):
            return ((np.abs(coords[ids[a1]] - coords[ids[a2]]).max(1) > uv_tol)
                    | (np.abs(coords[ids[b1]] - coords[ids[b2]]).max(1) > uv_tol))
    seam = split(uid, uv)
    f1, f2 = foc[c1], foc[c2]
    n1, n2 = nrm[f1], np.where(agree[:, None], -nrm[f2], nrm[f2])
    with np.errstate(invalid="ignore"):
        smooth = np.einsum("ij,ij->i", n1, n2) > np.cos(np.radians(float(smooth_deg)))
        mean = n1 + n2
        mean /= np.maximum(np.linalg.norm(mean, axis=1, keepdims=True), 1e-300)
        if view_dirs is None:
            seen = np.ones(len(c1), dtype=bool)
        else:
            D = np.asarray(view_dirs, dtype=np.float64).reshape(-1, 3)
            D = D / np.linalg.norm(D, axis=1, keepdims=True)
            seen = (mean @ D.T).max(1) >= float(facing)
    seed = mesh.get("uvw_ids") if hasattr(mesh, "get") else None
    marked = split(np.asarray(seed, dtype=np.int64)) if seed is not None and len(seed) == len(uid) else \
        np.zeros(len(c1), dtype=bool)
    length = np.linalg.norm(xyz[xid[c1]] - xyz[xid[nxt[c1]]], axis=1)
    vis = seam & smooth & seen
    hidden = vis & ~marked
    out.update(seam_m=round(float(length[seam].sum()), 3), smooth_seam_m=round(float(length[seam & smooth].sum()), 3),
               visible_seam_m=round(float(length[vis].sum()), 3),
               visible_seam_unmarked_m=round(float(length[hidden].sum()), 3))
    if hidden.any():
        ends = np.concatenate([xyz[xid[c1[hidden]]], xyz[xid[nxt[c1[hidden]]]]])
        out["visible_seam_bounds"] = [[round(float(x), 3) for x in ends.min(0)],
                                      [round(float(x), 3) for x in ends.max(0)]]
    return out


def visible_seam_warning(seams):
    """The advisory note for a visible_seams() result, or None: unmarked seams on visible smooth faces of at least
    VISIBLE_SEAM_NOTE_M, or VISIBLE_SEAM_NOTE_SHARE of the piece's size when that is smaller. Never a gate failure:
    a closed smooth body (an urn, a rock) needs its seams somewhere, the facing directions are a guess for a piece
    seen from every side, and the retry ladder only adds cuts; moving a seam takes a marked one."""
    if not seams:
        return None
    m = seams.get("visible_seam_unmarked_m") or 0.0
    if m <= 0 or m < min(VISIBLE_SEAM_NOTE_M, VISIBLE_SEAM_NOTE_SHARE * (seams.get("size_m") or 0.0)):
        return None
    lo, hi = seams.get("visible_seam_bounds") or ([0, 0, 0], [0, 0, 0])
    return ("visible seams %.2f m: cuts across smooth faces that face up or to the front (between %s and %s); a "
            "tiling texture jumps there. Mark the structural seams (panel edges, welts, the back or underside) and "
            "unwrap again, or check checker_preview(ob, cell_m=0.25)" % (m, tuple(lo), tuple(hi)))


def report(mesh, uvw_ids, uvw, map_px, pad_px=None, margin_px=None, raster_px=None, pad_tol_px=PAD_TOL_PX,
           region_angle=FRAGMENT_REGION_ANGLE):
    """Everything at once. raster_px defaults to map_px clamped to 256-2048 (coverage and overlap are counted in
    those pixels); padding and margin are exact and in map_px pixels (map_px may be a fractional lightmap
    footprint). margin_px_min is None when a UV is not finite; padding_min_px is None when every pair of islands
    is farther apart than about 2 x pad_px (see padding_gaps)."""
    info = {}
    sizes, xid, xyz, uid, uv, tri = _prep(mesh, uvw_ids, uvw, info=info)
    res = int(raster_px or min(max(map_px, 256), 2048))
    grid, clash = raster(mesh, uvw_ids, uvw, res, tri=tri)
    dist = distortion(mesh, uvw_ids, uvw, tri=tri, info=info, region_angle=region_angle)
    finite = bool(np.all(np.isfinite(uv[np.unique(uid)])))
    used = uv[np.unique(uid)]
    margin = float(min(used.min(), 1.0 - used.max()) * map_px) if finite else None
    out = {"faces": dist["faces"], "islands": dist["islands"], "shells": dist["shells"],
           "islands_per_100_faces": dist["islands_per_100_faces"], "finite": finite,
           "in_unit_tile": bool(finite and used.min() >= -1e-6 and used.max() <= 1 + 1e-6),
           "flipped_polygons": flipped_polygons(mesh, uvw_ids, uvw),
           "overlap_px": clash, "coverage": round(float(np.count_nonzero(grid >= 0)) / grid.size, 4),
           "bbox_share": round(bbox_share(uvw_ids, uvw), 4) if finite else None,
           "margin_px_min": None if margin is None else round(margin, 3),
           "texel": texel_density(mesh, uvw_ids, uvw, map_px), "distortion": dist,
           "shape_coverage_limit": round(shape_coverage_limit(mesh, uvw_ids, uvw), 4),
           "seams": visible_seams(mesh, uvw_ids, uvw), "pad_px": pad_px, "margin_px": margin_px}
    if margin_px is not None:
        out["margin_ok"] = bool(margin is not None and margin >= float(margin_px) - pad_tol_px)
    if pad_px:
        g = padding_gaps(mesh, uvw_ids, uvw, map_px, pad_px, pad_tol_px)
        out["padding_min_px"] = g["min_gap_px"]
        out["padding_pairs_below_min"] = g["pairs_below_min"]
    return out


def shape_coverage_limit(mesh, uvw_ids=None, uvw=None):
    """About the most a filled square tile can cover with this piece at one density: its 3D surface area over the
    square of the bounding-box diagonal of its largest connected shell (an island cut from a shell is about as long
    as that shell at most), capped at 1. A 3 x 0.12 x 0.12 m beam 0.16, a 1.2 x 0.15 x 0.03 m plank 0.30, a 1 m cube
    1, three 1 m cubes 5 m apart in one object 1. It lowers the coverage floor for long thin pieces only: a compact
    piece that covers little (a sprawling chamfer ring) still fails, and so does a band (a rim, a washer, a hoop),
    which unrolls to pi x its diameter until seams cut it."""
    ids = mesh["uvw_ids"] if uvw_ids is None else uvw_ids
    a3 = float(polygon_areas(mesh, ids, mesh["uvw"] if uvw is None else uvw)[0].sum())
    sizes = np.asarray(mesh["sizes"], dtype=np.int64)
    xid = np.asarray(mesh["xyz_ids"], dtype=np.int64)
    shell = islands(sizes, xid)[_face_of_corner(sizes)]          # connected shell of every corner
    order = np.argsort(shell, kind="stable")
    pts = np.asarray(mesh["xyz"], dtype=np.float64).reshape(-1, 3)[xid][order]
    cut = np.flatnonzero(np.r_[True, shell[order][1:] != shell[order][:-1]])
    span = np.maximum.reduceat(pts, cut, axis=0) - np.minimum.reduceat(pts, cut, axis=0)
    d2 = float((span ** 2).sum(1).max())
    return 1.0 if d2 <= 0 else min(1.0, a3 / d2)


def coverage_floor(rep, min_coverage=MIN_FILL_COVERAGE):
    """The coverage a filled pack must reach: min_coverage, lowered for a long thin piece to SHAPE_COVERAGE_SHARE of
    its shape_coverage_limit (a 25:1 piece cannot fill a square tile, whatever the seams), and none above
    FILL_COVERAGE_MAX_ISLANDS islands (the map/64 gaps take the tile)."""
    if rep.get("islands", 0) > FILL_COVERAGE_MAX_ISLANDS:
        return 0.0
    lim = rep.get("shape_coverage_limit")
    return float(min_coverage) if lim is None else min(float(min_coverage), SHAPE_COVERAGE_SHARE * lim)


def bbox_share(uvw_ids, uvw):
    """Area of the bounding box of the UVs the corners use, as a share of the 0-1 tile (b in the lightmap footprint
    texels_per_m x sqrt(A / b) x scale: Unity sizes a renderer's lightmap rectangle from it)."""
    uv = np.asarray(uvw, dtype=np.float64).reshape(-1, 3)[:, :2][np.unique(np.asarray(uvw_ids, dtype=np.int64))]
    span = uv.max(0) - uv.min(0)
    return float(span[0] * span[1])


def merge_gate(gate=None):
    """GATE with the given keys overriding it: a partial gate tightens or loosens those keys and keeps the rest; a
    whole-object key it sets (angular_p95, area_local_p95) also sets its per-island twin unless the gate sets that
    too, as uv-unwrapping's audit judges both against one limit. A value of float('inf') switches that check off. Raises TypeError or ValueError for anything but a dict of
    known keys and numbers, so a typo fails at once instead of sending every piece to review."""
    if gate is None:
        return dict(GATE)
    if not isinstance(gate, dict):
        raise TypeError("gate must be a dict of thresholds such as {'angular_p95': 1.2}, not %r" % (gate,))
    unknown = sorted(set(gate) - set(GATE))
    if unknown:
        raise ValueError("unknown gate key(s) %s: use %s" % (unknown, ", ".join(sorted(GATE))))
    for k, v in gate.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise TypeError("gate[%r] must be a number, not %r" % (k, v))
    merged = dict(GATE)
    merged.update(gate)
    for whole, island in (("angular_p95", "island_angular_p95"), ("area_local_p95", "island_area_local_p95")):
        if whole in gate and island not in gate:
            merged[island] = gate[whole]
    return merged


def check_gate(dist, gate=None):
    """Readable failures of a distortion() result against the gate; [] means it passes. Non-finite values fail.
    A partial gate merges over GATE (merge_gate); islands_per_100_faces is skipped for small island counts."""
    gate = merge_gate(gate)
    fails = [] if dist.get("finite", True) else ["non-finite UVs (NaN or infinity)"]
    for k, v in gate.items():
        if k == "islands_per_100_faces" and dist.get("islands", 0) <= FRAGMENT_FREE_ISLANDS:
            continue
        if v == float("inf"):
            continue
        x = dist.get(k)
        if x is None:
            fails.append("%s missing from the measurement" % k)
        elif not (x <= v):                       # also catches NaN
            fails.append("%s %.3f > %.3f" % (k, x, v))
    return fails


def layout_failures(rep, flips=True):
    """Readable layout failures of a report(): outside the 0-1 tile, overlapping islands, padding or margin below
    what report() was asked to check, flipped (mirrored or folded) polygons. [] means the layout is clean."""
    fails = []
    if not rep.get("finite", True):
        fails.append("non-finite UVs (NaN or infinity)")
    elif not rep.get("in_unit_tile", True):
        fails.append("UVs outside the 0-1 tile")
    if rep.get("overlap_px"):
        fails.append("overlap %d px" % rep["overlap_px"])
    if rep.get("padding_pairs_below_min"):
        fails.append("padding: %d island pair(s) closer than %s px (closest %s px)"
                     % (rep["padding_pairs_below_min"], rep.get("pad_px"), rep.get("padding_min_px")))
    if rep.get("margin_ok") is False:
        fails.append("margin: %s px to the tile edge, asked %s" % (rep.get("margin_px_min"), rep.get("margin_px")))
    if flips and rep.get("flipped_polygons"):
        fails.append("%d flipped polygon(s)" % rep["flipped_polygons"])
    return fails


def grade(rep, gate=None, distortion=True, layout=True, flips=True, min_coverage=None):
    """The one verdict: distortion gate failures (check_gate, partial gate merged over GATE) plus layout failures
    (layout_failures) of a report(), plus coverage below min_coverage (pass MIN_FILL_COVERAGE for a filled texture
    pack; coverage_floor() lowers it for long thin pieces). [] means the layer passes."""
    fails = check_gate(rep["distortion"], gate) if distortion else []
    if layout:
        fails += [f for f in layout_failures(rep, flips) if f not in fails]
    if min_coverage and rep.get("coverage") is not None:
        floor = coverage_floor(rep, min_coverage)
        if rep["coverage"] < floor:
            fails.append("coverage %.3f < %.3f" % (rep["coverage"], floor))
    return fails


def json_safe(obj):
    """A copy with every NaN or infinity replaced by None and numpy scalars made plain, for json.dump(...,
    allow_nan=False): strict JSON parsers reject NaN and Infinity."""
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    return obj
