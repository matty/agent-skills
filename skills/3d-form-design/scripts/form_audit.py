"""Form audit for a modelled prop or piece: over-bevelling, one bevel width everywhere, box-like parts, floating parts
and box-shaped silhouettes. Read-only: it measures and reports (audit_object switches Triangulate modifiers off for
the reading and back on).

Host: plain Python 3.9+, standard library. The core works on vertex and face lists (metres), so it runs on any tool's
export; mesh_from_object() and audit_object() at the bottom need Blender (bpy, written for 4.2+; the Blender part has
not been run in this repo's tests, only the plain-Python core has). Bevels are found on quads: audit before
triangulating, and export OBJs with quads kept.

    python form_audit.py chair.obj                  # an OBJ export (Z up; --y-up for Y-up exports), report + problems
    python form_audit.py chair.obj --json           # the whole report as JSON

    ns = {}; exec(open(r"<skill>/scripts/form_audit.py", encoding="utf-8").read(), ns)   # in Blender
    r = ns["audit_object"](bpy.data.objects["PROP_Chair_A"])     # modifiers applied, object scale applied
    print(ns["format_report"](r)); ns["problems"](r)             # failing keys with the evidence

What it measures (references/form-audit.md has the reasoning and the thresholds):
- bevel sections: chains of narrow quads (aspect >= 2.5) that turn between two flatter faces, each step under 75 deg.
  Width = the chain's summed width; flat = how far the flanking flat region reaches from the bevel. ratio = width /
  flat. Tiers group widths within 1.3x of each other. kind: "bevel" (judged), "round" (the chain turns 150 deg or
  more: a profile such as an arch, a bullnose or a hinge knuckle), "marked" (a face of it in rounds=, in Blender the
  boolean face attribute form_round: a round the design calls for) or "sliver" (a flank under 0.1 mm wide: a mesh
  defect for the topology audit, nothing to measure against). Only bevels are judged and tiered.
- parts: loose parts (vertex-connected). Per part: bounding box, volume fill of the box (closed parts only), the share
  of its area facing an axis, and whether its box gaps every other part by more than the contact tolerance.
- silhouettes: front, side, top and three-quarter projections rasterised to a grid; rectangularity = filled / box,
  solidity = filled / convex hull.
"""

import argparse
import json
import math
import sys

STRIP_ASPECT = 2.5          # a bevel face is at least this many times longer than wide
STRIP_TURN_MAX = 75.0       # deg between a bevel face and either neighbour; a plank's side turns 90 and is not a bevel
STRIP_TURN_MIN = 1.0
FLAT_DEG = 1.0              # faces within this of each other form one flat region
HARD_EDGE_DEG = 45.0        # an unbevelled edge between two flat regions this sharp counts as a hard edge
TIER_STEP = 1.3             # widths within 1.3x of a tier's smallest share the tier
AXIS_COS = math.cos(math.radians(2.0))
CONTACT_TOL = 0.002         # m: parts closer than this touch
# thresholds for problems(); practice values, see references/form-audit.md
RATIO_WARN = 0.25           # bevel width over a quarter of the flat beside it
RATIO_FAIL = 0.5            # flat face less than about half its original width on a face bevelled both sides
BOX_FILL = 0.9
BOX_AXIS = 0.85
SIZE_SPREAD = 4.0           # parts differing this much in size should not share one bevel width
SIL_RECT = 0.95
ROUND_TURN_DEG = 150.0      # a chain turning this far between its flanks is the part's profile, not an edge bevel
SLIVER_M = 1e-4             # a flank narrower than this is a degenerate face, not a flat to measure against
ROUND_ATTR = "form_round"   # Blender boolean face attribute marking designed rounds (audit_object reads it)


# ---------------------------------------------------------------- vector helpers

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _len(a):
    return math.sqrt(_dot(a, a))


def _angle(n1, n2):
    return math.degrees(math.acos(max(-1.0, min(1.0, _dot(n1, n2)))))


def _newell(pts):
    nx = ny = nz = 0.0
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        nx += (p[1] - q[1]) * (p[2] + q[2])
        ny += (p[2] - q[2]) * (p[0] + q[0])
        nz += (p[0] - q[0]) * (p[1] + q[1])
    n = (nx, ny, nz)
    ln = _len(n)
    return ((0.0, 0.0, 0.0), 0.0) if ln == 0 else ((nx / ln, ny / ln, nz / ln), ln / 2.0)


def _line_dist(p, a, b):
    ab = _sub(b, a)
    lab = _len(ab)
    if lab == 0:
        return _len(_sub(p, a))
    return _len(_cross(ab, _sub(p, a))) / lab


# ---------------------------------------------------------------- mesh tables

class _Mesh:
    def __init__(self, verts, faces):
        self.v = [tuple(float(c) for c in p) for p in verts]
        self.f = [tuple(f) for f in faces if len(f) >= 3]
        self.n, self.area = [], []
        for f in self.f:
            n, a = _newell([self.v[i] for i in f])
            self.n.append(n)
            self.area.append(a)
        self.edges = {}     # (lo, hi) -> [face indices]
        for fi, f in enumerate(self.f):
            for i in range(len(f)):
                a, b = f[i], f[(i + 1) % len(f)]
                self.edges.setdefault((min(a, b), max(a, b)), []).append(fi)

    def across(self, fi, a, b):
        """The one other face on edge (a, b), or None when the edge is open or overfull."""
        fs = self.edges.get((min(a, b), max(a, b)), [])
        if len(fs) != 2:
            return None
        return fs[1] if fs[0] == fi else fs[0]


def _aligned(n):
    return max(abs(c) for c in n) >= AXIS_COS


def _strips(m):
    """{face: (width, length, (long edge 1, long edge 2))} for the bevel faces.

    A candidate is a quad at least STRIP_ASPECT times longer than wide that turns under STRIP_TURN_MAX to the faces
    across both long edges. A candidate is a bevel when a neighbour across a long edge dominates it: the neighbour
    faces an object axis and it does not, or both or neither do and the neighbour is at least twice as wide. Further
    segments of a round join from a bevel next to them when within 1.5x of its width, never into an axis-facing face
    from one that is not (so an octagonal prism's sides stay sides)."""
    cand = {}
    for fi, f in enumerate(m.f):
        if len(f) != 4 or m.area[fi] == 0:
            continue
        e = [(f[i], f[(i + 1) % 4]) for i in range(4)]
        ln = [_len(_sub(m.v[b], m.v[a])) for a, b in e]
        pairs = [((e[0], e[2]), (ln[0] + ln[2]) / 2), ((e[1], e[3]), (ln[1] + ln[3]) / 2)]

        def turns_ok(edges):
            for a, b in edges:
                o = m.across(fi, a, b)
                if o is None or not (STRIP_TURN_MIN <= _angle(m.n[fi], m.n[o]) < STRIP_TURN_MAX):
                    return False
            return True

        def between_axis_faces(edges):
            return not _aligned(m.n[fi]) and all(
                _aligned(m.n[o]) for a, b in edges for o in [m.across(fi, a, b)] if o is not None)

        pick = None
        # an off-axis quad between two axis-facing faces is a bevel whatever its aspect (a soap-bar cube's edge
        # quads are wider than long); otherwise the long pair, when the quad is narrow enough
        for edges, length in pairs:
            if turns_ok(edges) and between_axis_faces(edges):
                pick = (edges, length)
        if pick is None:
            edges, length = max(pairs, key=lambda p: p[1])
            width = m.area[fi] / length if length else 0.0
            if width > 0 and length >= STRIP_ASPECT * width and turns_ok(edges):
                pick = (edges, length)
        if pick is not None and pick[1] > 0:
            cand[fi] = (m.area[fi] / pick[1], pick[1], pick[0])

    def across_width(fi, o, a, b):
        if o in cand:
            return cand[o][0]
        return max(_line_dist(m.v[p], m.v[a], m.v[b]) for p in m.f[o])

    def dominates(o, wo, fi):
        ao, af = _aligned(m.n[o]), _aligned(m.n[fi])
        return (ao and not af) or (ao == af and wo >= 2.0 * cand[fi][0])

    out = {}
    for fi, (w, ln, long_edges) in cand.items():
        nbrs = [(o, across_width(fi, o, a, b)) for a, b in long_edges for o in [m.across(fi, a, b)]]
        if any(dominates(o, wo, fi) for o, wo in nbrs) and not any(
                _aligned(m.n[fi]) and not _aligned(m.n[o]) for o, _ in nbrs):
            out[fi] = cand[fi]
    stack = list(out)
    while stack:
        fi = stack.pop()
        for a, b in out[fi][2]:
            o = m.across(fi, a, b)
            if o in cand and o not in out:
                if _aligned(m.n[o]) and not _aligned(m.n[fi]):
                    continue
                if out[fi][0] / 1.5 <= cand[o][0] <= out[fi][0] * 1.5:
                    out[o] = cand[o]
                    stack.append(o)
    return out


def _flat_regions(m, strips):
    """Face -> region id, joining non-strip faces across edges where they lie within FLAT_DEG of one plane."""
    region = {}
    rid = 0
    for start in range(len(m.f)):
        if start in strips or start in region:
            continue
        region[start] = rid
        stack = [start]
        while stack:
            fi = stack.pop()
            f = m.f[fi]
            for i in range(len(f)):
                o = m.across(fi, f[i], f[(i + 1) % len(f)])
                if o is None or o in strips or o in region:
                    continue
                if _angle(m.n[fi], m.n[o]) <= FLAT_DEG:
                    region[o] = rid
                    stack.append(o)
        rid += 1
    return region


def _parts(m):
    """Vertex-connected loose parts: list of sets of face indices."""
    parent = list(range(len(m.v)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for f in m.f:
        r0 = find(f[0])
        for i in f[1:]:
            ri = find(i)
            if ri != r0:
                parent[ri] = r0
    groups = {}
    for fi, f in enumerate(m.f):
        groups.setdefault(find(f[0]), set()).add(fi)
    return list(groups.values())


# ---------------------------------------------------------------- bevels

def bevel_sections(verts, faces, _m=None, rounds=None):
    """Every bevel cross-section: dict(width, length, flat, ratio, turn, faces, flanks, contact, kind). Read the module
    docstring for what counts as one and for kind; rounds: face indices of designed rounds (kind "marked")."""
    rounds = set(rounds or ())
    m = _m or _Mesh(verts, faces)
    strips = _strips(m)
    region = _flat_regions(m, strips)
    # region vertex sets, for the flat measurement
    rverts = {}
    for fi, r in region.items():
        rverts.setdefault(r, set()).update(m.f[fi])
    zmin = min(p[2] for p in m.v) if m.v else 0.0
    seen = set()
    out = []
    for s in strips:
        if s in seen:
            continue
        chain, stack, flanks = [], [s], []
        seen.add(s)
        while stack:
            fi = stack.pop()
            chain.append(fi)
            for a, b in strips[fi][2]:
                o = m.across(fi, a, b)
                if o in strips:
                    if o not in seen:
                        seen.add(o)
                        stack.append(o)
                else:
                    flanks.append((o, a, b))
        if len(flanks) != 2:
            continue        # a closed ring (a cylinder's facets) or a branching chain: not a bevel between two faces
        widths = [strips[fi][0] for fi in chain]
        lengths = [strips[fi][1] for fi in chain]
        flats, contact = [], False
        for o, a, b in flanks:
            r = region.get(o)
            pts = rverts.get(r, set(m.f[o]))
            flats.append(max(_line_dist(m.v[p], m.v[a], m.v[b]) for p in pts))
            if m.n[o][2] < -0.99 and all(abs(m.v[p][2] - zmin) < CONTACT_TOL for p in m.f[o]):
                contact = True
        width = sum(widths)
        flat = min(flats)
        turn = _angle(m.n[flanks[0][0]], m.n[flanks[1][0]])
        kind = ("marked" if rounds.intersection(chain) else "sliver" if flat < SLIVER_M
                else "round" if turn >= ROUND_TURN_DEG else "bevel")
        out.append(dict(width=width, length=sum(lengths) / len(lengths), flat=flat,
                        ratio=(width / flat) if flat > 0 else float("inf"),
                        turn=turn, faces=sorted(chain),
                        flanks=[flanks[0][0], flanks[1][0]], contact=contact, kind=kind))
    return out


def tiers(widths_lengths, step=TIER_STEP):
    """Group (width, length) pairs: a new tier starts when a width is over step x the current tier's smallest.
    Returns [dict(width_min, width_max, count, length)] smallest first."""
    out = []
    for w, ln in sorted(widths_lengths):
        if not out or w > out[-1]["width_min"] * step:
            out.append(dict(width_min=w, width_max=w, count=0, length=0.0))
        t = out[-1]
        t["width_max"] = w
        t["count"] += 1
        t["length"] += ln
    return out


def hard_edges(m, strips, region):
    """Total length (m) and count of unbevelled edges between two flat regions meeting at HARD_EDGE_DEG or more."""
    count, length = 0, 0.0
    for (a, b), fs in m.edges.items():
        if len(fs) != 2 or fs[0] in strips or fs[1] in strips:
            continue
        if region.get(fs[0]) == region.get(fs[1]):
            continue
        if _angle(m.n[fs[0]], m.n[fs[1]]) >= HARD_EDGE_DEG:
            count += 1
            length += _len(_sub(m.v[b], m.v[a]))
    return count, length


# ---------------------------------------------------------------- parts

def _part_report(m, fs, zmin):
    vs = set()
    for fi in fs:
        vs.update(m.f[fi])
    pts = [m.v[i] for i in vs]
    lo = tuple(min(p[k] for p in pts) for k in range(3))
    hi = tuple(max(p[k] for p in pts) for k in range(3))
    dims = tuple(hi[k] - lo[k] for k in range(3))
    area = sum(m.area[fi] for fi in fs)
    axis = sum(m.area[fi] for fi in fs if max(abs(c) for c in m.n[fi]) >= AXIS_COS)
    # closed when every edge of the part has exactly two faces
    closed = True
    for fi in fs:
        f = m.f[fi]
        for i in range(len(f)):
            if len(m.edges[(min(f[i], f[(i + 1) % len(f)]), max(f[i], f[(i + 1) % len(f)]))]) != 2:
                closed = False
                break
        if not closed:
            break
    fill = None
    box = dims[0] * dims[1] * dims[2]
    if closed and box > 0:
        vol = 0.0
        for fi in fs:
            f = m.f[fi]
            p0 = m.v[f[0]]
            for i in range(1, len(f) - 1):
                vol += _dot(p0, _cross(m.v[f[i]], m.v[f[i + 1]])) / 6.0
        fill = abs(vol) / box
    sd = sorted(dims)
    return dict(lo=lo, hi=hi, dims=dims, size=max(dims), area=area, axis_share=axis / area if area else 0.0,
                closed=closed, fill=fill, cube=(sd[0] / sd[2] >= 0.85) if sd[2] > 0 else False,
                grounded=abs(lo[2] - zmin) < CONTACT_TOL, faces=len(fs))


def _box_gap(a, b):
    g = 0.0
    for k in range(3):
        d = max(a["lo"][k] - b["hi"][k], b["lo"][k] - a["hi"][k], 0.0)
        g = max(g, d)
    return g


def size_tiers(sizes, step=2.0):
    """How many size tiers the parts make, a new tier at each step x jump (big, medium, small wants 3)."""
    out = 0
    last = None
    for s in sorted(sizes, reverse=True):
        if last is None or s * step <= last:
            out += 1
            last = s
    return out


# ---------------------------------------------------------------- silhouettes

VIEWS = {
    "front": lambda p: (p[0], p[2]),
    "side": lambda p: (p[1], p[2]),
    "top": lambda p: (p[0], p[1]),
    "three_quarter": lambda p: (
        (p[0] - p[1]) / math.sqrt(2.0),
        p[2] * math.cos(math.radians(30)) - (p[0] + p[1]) / math.sqrt(2.0) * math.sin(math.radians(30))),
}


def _hull_area(points):
    pts = sorted(set(points))
    if len(pts) < 3:
        return 0.0

    def turn(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    return abs(sum(hull[i][0] * hull[(i + 1) % len(hull)][1] - hull[(i + 1) % len(hull)][0] * hull[i][1]
                   for i in range(len(hull)))) / 2.0


def silhouette(verts, faces, view="front", res=96):
    """Orthographic silhouette of the mesh on a res-pixel grid (longest side): dict(rectangularity, solidity, aspect).
    rectangularity = filled / bounding box, solidity = filled / convex hull (1.0 for a box from any axis view)."""
    proj = VIEWS[view]
    p2 = [proj(p) for p in verts]
    xs, ys = [p[0] for p in p2], [p[1] for p in p2]
    x0, y0 = min(xs), min(ys)
    span = max(max(xs) - x0, max(ys) - y0)
    if span == 0:
        return dict(rectangularity=0.0, solidity=0.0, aspect=0.0)
    px = span / res
    w = max(1, int(math.ceil((max(xs) - x0) / px)))
    h = max(1, int(math.ceil((max(ys) - y0) / px)))
    grid = [bytearray(w) for _ in range(h)]
    for f in faces:
        q = [((p2[i][0] - x0) / px, (p2[i][1] - y0) / px) for i in f]
        for k in range(1, len(q) - 1):
            a, b, c = q[0], q[k], q[k + 1]
            den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(den) < 1e-12:
                continue
            for yy in range(max(0, int(min(a[1], b[1], c[1]))), min(h, int(max(a[1], b[1], c[1])) + 1)):
                cy = yy + 0.5
                for xx in range(max(0, int(min(a[0], b[0], c[0]))), min(w, int(max(a[0], b[0], c[0])) + 1)):
                    cx = xx + 0.5
                    l1 = ((b[1] - c[1]) * (cx - c[0]) + (c[0] - b[0]) * (cy - c[1])) / den
                    l2 = ((c[1] - a[1]) * (cx - c[0]) + (a[0] - c[0]) * (cy - c[1])) / den
                    if l1 >= -1e-9 and l2 >= -1e-9 and l1 + l2 <= 1 + 1e-9:
                        grid[yy][xx] = 1
    filled, corners = 0, []
    for yy in range(h):
        row = grid[yy]
        for xx in range(w):
            if row[xx]:
                filled += 1
                corners += [(xx, yy), (xx + 1, yy), (xx, yy + 1), (xx + 1, yy + 1)]
    hull = _hull_area(corners)
    return dict(rectangularity=filled / float(w * h), solidity=(filled / hull) if hull else 0.0,
                aspect=(max(xs) - x0) / (max(ys) - y0) if max(ys) > y0 else 0.0)


# ---------------------------------------------------------------- audit

def audit(verts, faces, silhouettes=True, rounds=None):
    """The full report for one mesh, verts in metres with Z up. See format_report() and problems(). rounds: face
    indices of rounds the design calls for (a corner bumper, a moulded lip): reported, never judged as bevels."""
    m = _Mesh(verts, faces)
    if not m.f:
        raise ValueError("no faces")
    strips = _strips(m)
    region = _flat_regions(m, strips)
    secs = bevel_sections(verts, faces, _m=m, rounds=rounds)
    bev = [s for s in secs if s["kind"] == "bevel"]
    zmin = min(p[2] for p in m.v)
    parts = [_part_report(m, fs, zmin) for fs in _parts(m)]
    for i, p in enumerate(parts):
        p["floating"] = (not p["grounded"]) and len(parts) > 1 and all(
            _box_gap(p, q) > CONTACT_TOL for j, q in enumerate(parts) if j != i)
    total_area = sum(p["area"] for p in parts)
    box_area = sum(p["area"] for p in parts
                   if p["fill"] is not None and p["fill"] >= BOX_FILL and p["axis_share"] >= BOX_AXIS)
    hc, hl = hard_edges(m, strips, region)
    r = dict(
        faces=len(m.f), verts=len(m.v),
        bevels=secs,
        bevel_tiers=tiers([(s["width"], s["length"]) for s in bev]),
        bevel_length=sum(s["length"] for s in bev),
        rounds=sum(1 for s in secs if s["kind"] in ("round", "marked")),
        sliver_sections=sum(1 for s in secs if s["kind"] == "sliver"),
        hard_edge_count=hc, hard_edge_length=hl,
        parts=parts,
        size_tiers=size_tiers([p["size"] for p in parts]),
        axis_share=sum(p["axis_share"] * p["area"] for p in parts) / total_area if total_area else 0.0,
        box_share=box_area / total_area if total_area else 0.0,
    )
    if silhouettes:
        r["silhouettes"] = {v: silhouette(m.v, m.f, v) for v in VIEWS}
    return r


def problems(r, ratio_warn=RATIO_WARN, ratio_fail=RATIO_FAIL, expect_sharp=True):
    """[(key, evidence)] for a report from audit(). Keys starting warn_ are judgement calls for the review renders;
    the rest should be fixed unless the reference really looks like that (say so in the report)."""
    out = []
    every = r["bevels"]
    secs = [s for s in every if s.get("kind", "bevel") == "bevel"]
    over = [s for s in secs if s["ratio"] > ratio_fail]
    if over:
        worst = max(over, key=lambda s: s["ratio"])
        out.append(("over_bevelled", "%d bevel(s) wider than %.0f%% of the flat beside them; worst %.1f mm against "
                    "%.1f mm of flat" % (len(over), ratio_fail * 100, worst["width"] * 1000, worst["flat"] * 1000)))
    wide = [s for s in secs if ratio_warn < s["ratio"] <= ratio_fail]
    if wide:
        out.append(("warn_wide_bevels", "%d bevel(s) between %.0f%% and %.0f%% of their flat" %
                    (len(wide), ratio_warn * 100, ratio_fail * 100)))
    contact = [s for s in every if s["contact"] and s.get("kind", "bevel") != "sliver"]
    if contact:
        out.append(("contact_bevelled", "%d bevel(s) on the bottom contact face: it sits on the floor, nobody sees "
                    "that edge, and it opens a dark gap under the piece" % len(contact)))
    sizes = [p["size"] for p in r["parts"]]
    if len(r["bevel_tiers"]) == 1 and len(secs) >= 8 and sizes and max(sizes) >= SIZE_SPREAD * min(sizes):
        t = r["bevel_tiers"][0]
        out.append(("one_bevel_width", "every bevel is %.1f-%.1f mm on parts from %.2f to %.2f m: small parts read "
                    "soft, big ones razor-edged" % (t["width_min"] * 1000, t["width_max"] * 1000, min(sizes),
                                                    max(sizes))))
    slivers = [s for s in every if s.get("kind") == "sliver"]
    if slivers:
        out.append(("warn_sliver_flanks", "%d bevel(s) end on a face under %.1f mm wide (a Boolean or merge left "
                    "slivers): fix the mesh (topology audit), then audit again" % (len(slivers), SLIVER_M * 1000)))
    if expect_sharp and secs and r["hard_edge_count"] == 0:
        out.append(("warn_every_edge_bevelled", "no hard edge left: check contact, joint, hidden and cut-sheet edges, "
                    "which stay sharp"))
    if r["box_share"] >= 0.6:
        out.append(("blocky", "%.0f%% of the surface is on box-like parts (fill >= %.2f of their bounding box, "
                    ">= %.0f%% facing an axis)" % (r["box_share"] * 100, BOX_FILL, BOX_AXIS * 100)))
    cubes = [p for p in r["parts"] if p["cube"] and p["fill"] is not None and p["fill"] >= BOX_FILL]
    if cubes:
        out.append(("warn_cube_parts", "%d part(s) are near-cubes (sides within 15%%)" % len(cubes)))
    floating = [p for p in r["parts"] if p["floating"]]
    if floating:
        out.append(("floating_parts", "%d part(s) touch nothing and are off the ground, e.g. at z %.3f m" %
                    (len(floating), floating[0]["lo"][2])))
    if len(r["parts"]) >= 3 and r["size_tiers"] < 2:
        out.append(("warn_size_tiers", "%d parts all within 2x of each other in size: no big, medium and small" %
                    len(r["parts"])))
    sil = r.get("silhouettes")
    if sil and all(sil[v]["rectangularity"] >= SIL_RECT for v in ("front", "side")):
        out.append(("warn_box_silhouette", "front and side silhouettes fill %.0f%% and %.0f%% of their bounding box" %
                    (sil["front"]["rectangularity"] * 100, sil["side"]["rectangularity"] * 100)))
    return out


def format_report(r):
    lines = ["faces %d, parts %d (size tiers %d), axis-facing area %.0f%%, box-like area %.0f%%" %
             (r["faces"], len(r["parts"]), r["size_tiers"], r["axis_share"] * 100, r["box_share"] * 100),
             "bevels: %d sections, %.2f m; hard edges left: %d, %.2f m; profile rounds %d, sliver flanks %d" %
             (sum(1 for s in r["bevels"] if s.get("kind", "bevel") == "bevel"), r["bevel_length"],
              r["hard_edge_count"], r["hard_edge_length"], r.get("rounds", 0), r.get("sliver_sections", 0))]
    for t in r["bevel_tiers"]:
        lines.append("  tier %.1f-%.1f mm: %d sections, %.2f m" %
                     (t["width_min"] * 1000, t["width_max"] * 1000, t["count"], t["length"]))
    judged = [s for s in r["bevels"] if s.get("kind", "bevel") == "bevel"]
    if judged:
        ratios = sorted(s["ratio"] for s in judged)
        lines.append("  width / flat: median %.2f, max %.2f" % (ratios[len(ratios) // 2], ratios[-1]))
    for v, s in sorted(r.get("silhouettes", {}).items()):
        lines.append("silhouette %-13s rectangularity %.2f, solidity %.2f, aspect %.2f" %
                     (v, s["rectangularity"], s["solidity"], s["aspect"]))
    return "\n".join(lines)


# ---------------------------------------------------------------- OBJ

def read_obj(path, y_up=False):
    verts, faces = [], []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("v "):
                x, y, z = (float(c) for c in line.split()[1:4])
                verts.append((x, -z, y) if y_up else (x, y, z))
            elif line.startswith("f "):
                idx = []
                for tok in line.split()[1:]:
                    i = int(tok.split("/")[0])
                    idx.append(i - 1 if i > 0 else len(verts) + i)
                faces.append(tuple(idx))
    return verts, faces


# ---------------------------------------------------------------- Blender

def mesh_from_object(ob, evaluated=True):
    """(verts, faces) of a Blender mesh object with its modifiers applied (evaluated=True) and its object scale
    applied, in the object's own axes (rotation and translation left out): what the piece really measures, with
    'facing an axis' meaning the piece's own axes. Needs bpy."""
    import bpy  # noqa: F401  (only available inside Blender)
    src = ob
    if evaluated:
        src = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = src.to_mesh()
    try:
        s = ob.matrix_world.to_scale()
        verts = [(v.co.x * s.x, v.co.y * s.y, v.co.z * s.z) for v in me.vertices]
        faces = [tuple(p.vertices) for p in me.polygons]
    finally:
        src.to_mesh_clear()
    return verts, faces


def round_faces(ob, evaluated=True):
    """Indices of the faces marked as designed rounds (boolean face attribute form_round), on the same mesh
    mesh_from_object reads: me.attributes.new("form_round", "BOOLEAN", "FACE"), then set it on the faces. A Bevel
    modifier's faces inherit the mark from the faces they grow from, so marking a whole part (a corner bumper) marks
    every round it carries. Needs bpy."""
    import bpy  # noqa: F401  (only available inside Blender)
    src = ob.evaluated_get(bpy.context.evaluated_depsgraph_get()) if evaluated else ob
    me = src.to_mesh()
    try:
        a = me.attributes.get(ROUND_ATTR)
        if a is None or a.domain != "FACE" or a.data_type != "BOOLEAN":
            return set()
        return {i for i, d in enumerate(a.data) if d.value}
    finally:
        src.to_mesh_clear()


def bevel_modifier_notes(ob):
    """Settings on the object's enabled Bevel modifiers that cause the over-chamfered look (Blender only)."""
    notes = []
    scale = ob.matrix_world.to_scale()
    if max(scale) - min(scale) > 1e-4 * max(scale):
        notes.append("non-uniform object scale %s: bevel widths are in object space and come out uneven; apply scale"
                     % (tuple(round(s, 4) for s in scale),))
    for md in ob.modifiers:
        if md.type != "BEVEL" or not md.show_viewport:
            continue
        if md.limit_method == "NONE":
            notes.append("%s: Limit Method None bevels every edge, contact and joint edges included; use Weight "
                         "or Angle" % md.name)
        if md.offset_type == "PERCENT":
            notes.append("%s: Percent width follows each edge's length, so widths vary by accident; use Offset or "
                         "Width in metres" % md.name)
        if md.affect != "EDGES":
            notes.append("%s: affects vertices, not edges" % md.name)
        if md.segments > 3 and md.width < 0.01:
            notes.append("%s: %d segments on a %.1f mm bevel: invisible facets, wasted triangles" %
                         (md.name, md.segments, md.width * 1000))
    return notes


def audit_object(ob, evaluated=True, silhouettes=True):
    """audit() of a Blender mesh object (modifiers and object scale applied), plus Bevel modifier notes under
    'modifier_notes'. Bevels are found on quads, so enabled Triangulate modifiers are switched off for the reading
    and restored afterwards; nothing else is changed. An already triangulated mesh reports no bevels. Faces with the
    boolean face attribute form_round set are designed rounds (kind "marked"), never judged as bevels."""
    import bpy
    tris = [md for md in ob.modifiers if md.type == "TRIANGULATE" and md.show_viewport]
    try:
        for md in tris:
            md.show_viewport = False
        bpy.context.view_layer.update()
        verts, faces = mesh_from_object(ob, evaluated)
        rounds = round_faces(ob, evaluated)
    finally:
        for md in tris:
            md.show_viewport = True
        bpy.context.view_layer.update()
    r = audit(verts, faces, silhouettes, rounds=rounds)
    r["name"] = ob.name
    r["modifier_notes"] = bevel_modifier_notes(ob)
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("obj", help="an OBJ file, metres")
    ap.add_argument("--y-up", action="store_true", help="the OBJ is Y up (most exporters' default)")
    ap.add_argument("--json", action="store_true", help="print the whole report as JSON")
    ap.add_argument("--no-silhouettes", action="store_true")
    a = ap.parse_args(argv)
    verts, faces = read_obj(a.obj, a.y_up)
    r = audit(verts, faces, silhouettes=not a.no_silhouettes)
    if a.json:
        print(json.dumps(r, indent=1, default=str))
    else:
        print(format_report(r))
        for k, ev in problems(r):
            print("%s: %s" % (k, ev))
    return 1 if any(not k.startswith("warn_") for k, _ in problems(r)) else 0


if __name__ == "__main__":
    sys.exit(main())
