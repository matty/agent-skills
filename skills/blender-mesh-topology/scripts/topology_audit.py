"""Topology and mesh-quality audit for Blender meshes (read-only).

Load in Blender:  ns = {}; exec(open(r"<skill>/scripts/topology_audit.py", encoding="utf-8").read(), ns)

    ns["audit"](bpy.data.objects["MyPiece"])                 # dict of counts; ns["problems"](result) lists failures
    ns["audit_many"]([o for o in bpy.data.objects if o.name.startswith("SK_")])
    ns["joint_match"](obj_a, obj_b, lambda co: abs(co.x) < 1e-4)   # do two pieces share their joint vertices?
    ns["determinism_hash"](obj)                               # compare across two builds
"""

import hashlib
import math

import bmesh


def audit(ob, sliver_deg=2.0, bad_corner_deg=3.0, fold_deg=25.0, short_edge=0.001):
    """Counts for one mesh object (object space). Poles are interior verts of all-quad fans with valence other than 4
    (deliberate ones from reduction templates are expected; look at where they are); fan centres have 8+ edges."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.normal_update()
    bm.faces.ensure_lookup_table()
    # islands and orientation
    seen, islands, inverted = set(), 0, 0
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, isl = [f], []
        seen.add(f.index)
        while stack:
            x = stack.pop()
            isl.append(x)
            for e in x.edges:
                for g in e.link_faces:
                    if g.index not in seen:
                        seen.add(g.index)
                        stack.append(g)
        islands += 1
        if all(len(e.link_faces) == 2 for g in isl for e in g.edges) and \
                sum(g.calc_area() * g.normal.dot(g.calc_center_median()) for g in isl) < -1e-9:
            inverted += 1
    bad_quads = 0
    for f in bm.faces:
        if len(f.verts) != 4:
            continue
        a, b, c, d = (v.co for v in f.verts)
        f1 = (b - a).cross(c - a).angle((c - a).cross(d - a), 0.0)
        f2 = (c - b).cross(d - b).angle((d - b).cross(a - b), 0.0)
        folded = min(f1, f2) > math.radians(fold_deg) and min(e.calc_length() for e in f.edges) >= 0.02
        if min(l.calc_angle() for l in f.loops) < math.radians(bad_corner_deg) or folded or max(f1, f2) > math.pi / 2:
            bad_quads += 1
    slivers = sum(1 for f in bm.faces if f.smooth and len(f.verts) <= 4 and
                  min(l.calc_angle() for l in f.loops) < math.radians(sliver_deg))
    inner = [v for v in bm.verts if not v.is_boundary and v.link_faces]
    nf = len(bm.faces)
    r = dict(
        faces=nf, triangles=sum(len(f.verts) - 2 for f in bm.faces),
        tri_faces_pct=round(100.0 * sum(1 for f in bm.faces if len(f.verts) == 3) / max(1, nf), 1),
        ngons=sum(1 for f in bm.faces if len(f.verts) > 4),
        islands=islands, inverted_islands=inverted,
        open_edges=sum(1 for e in bm.edges if len(e.link_faces) == 1),
        overfull_edges=sum(1 for e in bm.edges if len(e.link_faces) > 2),
        short_edges=sum(1 for e in bm.edges if e.calc_length() < short_edge),
        degenerate_faces=sum(1 for f in bm.faces if f.calc_area() < 1e-8),
        bad_quads=bad_quads, slivers=slivers,
        poles=sum(1 for v in inner if len(v.link_edges) != 4 and all(len(f.verts) == 4 for f in v.link_faces)),
        fan_centres=sum(1 for v in inner if len(v.link_edges) >= 8),
        loose_verts=sum(1 for v in bm.verts if not v.link_faces),
    )
    bm.free()
    return r


def problems(r, allow_open=False):
    """The failing keys of an audit result (open edges allowed for pieces meant to be open)."""
    keys = ["ngons", "inverted_islands", "overfull_edges", "short_edges", "degenerate_faces", "bad_quads", "slivers",
            "loose_verts"] + ([] if allow_open else ["open_edges"])
    return [k for k in keys if r[k]]


def audit_many(objects):
    """Audit several objects; prints a table sorted by triangle count and returns {name: result}."""
    out = {o.name: audit(o) for o in objects if o.type == 'MESH' and len(o.data.polygons)}
    cols = ["triangles", "tri_faces_pct", "poles", "fan_centres", "bad_quads", "slivers", "open_edges"]
    print("piece".ljust(28) + "".join(c.rjust(14) for c in cols) + "  problems")
    for name, r in sorted(out.items(), key=lambda kv: -kv[1]["triangles"]):
        print(name.ljust(28) + "".join(str(r[c]).rjust(14) for c in cols) + "  " + ",".join(problems(r)))
    return out


def joint_match(a, b, select, digits=5):
    """Do two objects share their vertices on a joint? select(co) picks joint vertices (object space of each, so place
    both masters in the same frame). Returns (only in a, only in b, shared) as sets of rounded positions."""
    pa = {tuple(round(c, digits) for c in v.co) for v in a.data.vertices if select(v.co)}
    pb = {tuple(round(c, digits) for c in v.co) for v in b.data.vertices if select(v.co)}
    return pa - pb, pb - pa, pa & pb


def determinism_hash(ob, digits=5):
    """A short hash of the sorted vertex positions: equal across two builds means the generator is repeatable."""
    key = repr(sorted(tuple(round(c, digits) for c in v.co) for v in ob.data.vertices)).encode()
    return hashlib.md5(key).hexdigest()[:12]
