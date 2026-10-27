"""Topology and mesh-quality audit for Blender meshes (read-only).

Host: Blender (bpy, bmesh; tested on 5.2.2). determinism_hash and joint_match only read mesh data.
Load in Blender:  ns = {}; exec(open(r"<skill>/scripts/topology_audit.py", encoding="utf-8").read(), ns)

    ns["audit"](bpy.data.objects["MyPiece"])                 # dict of counts; ns["problems"](result) lists failures
    ns["problems"](result, flat_tol=0.5)                     # also fail big faces whose normals are off flat
    ns["audit_stack"](obj, flat_tol=0.5)                     # a hard-surface piece (references/hard-surface.md)
    snap = ns["normals_snapshot"](obj)                       # before UV work applies the stack ...
    ns["audit_stack"](obj, flat_tol=0.5, before=snap)        # ... and after: fails if the normals moved
    ns["audit_many"]([o for o in bpy.data.objects if o.name.startswith("SK_")])
    ns["joint_match"](obj_a, obj_b, lambda co: abs(co.x) < 1e-4)   # do two pieces share their joint vertices?
    ns["joint_normals"](obj_a, obj_b, lambda co: abs(co.x) < 1e-4) # ... and does the shading carry on across it?
    ns["determinism_hash"](obj)                               # compare across two builds: vertices and faces
    ns["high_low_gap"](low, [high])                          # how far high and low part (relief, silhouette), metres
    ns["bake_skew"](low)                                     # how slanted the bake's rays leave the low's faces

audit_stack and normals_snapshot switch Triangulate modifiers off or on for a reading and restore them; nothing else
is changed.
"""

import contextlib
import hashlib
import math


def _face_width(me, p):
    """A face's extent across its longest edge: a 10 mm chamfer strip is 0.01 wide however long it is."""
    vs = [me.vertices[i].co for i in p.vertices]
    longest = max((vs[i] - vs[i - 1]).length for i in range(len(vs)))
    return (2.0 if p.loop_total == 3 else 1.0) * p.area / max(longest, 1e-12)


def _flatness(me, min_width, list_deg):
    """Over faces at least min_width wide: (the worst angle in degrees between a corner normal and its own face's
    normal, that face's index or -1, [(angle, index, centre) for every face over list_deg, worst first])."""
    cn = me.corner_normals
    worst, at, over = 0.0, -1, []
    for p in me.polygons:
        if _face_width(me, p) < min_width:
            continue
        a = max(math.degrees(cn[li].vector.angle(p.normal, 0.0)) for li in p.loop_indices)
        if a > worst:
            worst, at = a, p.index
        if a > list_deg:
            over.append((a, p.index, p.center.copy()))
    over.sort(key=lambda t: -t[0])
    return worst, at, over


def _data_faces(ob, centres):
    """For points in object space (face centres of the evaluated mesh), the index of the nearest face of the object's
    own mesh data: the face a triangle or a bevel face came from, or one beside it. -1 when the data has no faces."""
    from mathutils.bvhtree import BVHTree
    me = ob.data
    if not centres or not len(me.polygons):
        return [-1] * len(centres)
    tree = BVHTree.FromPolygons([v.co for v in me.vertices], [tuple(p.vertices) for p in me.polygons])
    out = []
    for c in centres:
        idx = tree.find_nearest(c)[2]
        out.append(-1 if idx is None else idx)
    return out


def _one_per_face(mapped, over):
    """flat_faces entries, one per mesh-data face (its worst evaluated face; over is sorted worst first)."""
    out, seen = [], set()
    for k, (a, _, c) in enumerate(over):
        if mapped[k] not in seen:
            seen.add(mapped[k])
            out.append(dict(face=mapped[k], deg=round(a, 2), centre=tuple(round(x, 4) for x in c)))
    return out


INVERTED_REL_VOLUME = 1e-6    # a closed island whose |volume| is under this share of its bounding box is undetermined


def _signed_volume6(faces):
    """(6 x the signed volume, the bounding-box volume) of a closed island: positive when its faces point outwards.
    Summed in float64 about the island's own centre: bmesh coordinates are float32, and summed about a far-off origin
    the terms cancel until the sign is noise (2 cm tubes 5 m from the origin read inverted)."""
    pts = {v.index: tuple(v.co) for f in faces for v in f.verts}
    n = float(len(pts))
    c = [sum(p[k] for p in pts.values()) / n for k in range(3)]
    lo = [min(p[k] for p in pts.values()) for k in range(3)]
    hi = [max(p[k] for p in pts.values()) for k in range(3)]
    vol6 = 0.0
    for f in faces:
        ring = [(p[0] - c[0], p[1] - c[1], p[2] - c[2]) for p in (pts[v.index] for v in f.verts)]
        ax, ay, az = ring[0]
        for (bx, by, bz), (qx, qy, qz) in zip(ring[1:-1], ring[2:]):
            vol6 += ax * (by * qz - bz * qy) + ay * (bz * qx - bx * qz) + az * (bx * qy - by * qx)
    return vol6, (hi[0] - lo[0]) * (hi[1] - lo[1]) * (hi[2] - lo[2])


def _join_pairs(bm, max_deg=10.0):
    """Join triangle pairs back into quads where the two lie within max_deg of one plane: undoes an applied
    Triangulate for counting (10 deg also rejoins a bevel's curved corner quads; measured on 1-3 segment bevels, the
    counts then equal the untriangulated mesh's)."""
    import bmesh
    bmesh.ops.join_triangles(bm, faces=bm.faces[:], cmp_seam=False, cmp_sharp=False, cmp_uvs=False, cmp_vcols=False,
                             cmp_materials=False, angle_face_threshold=math.radians(max_deg),
                             angle_shape_threshold=math.pi)


def flat_floor(ob, evaluated=True):
    """The width under which audit() leaves a face out of the flat check: 2.1 x the largest amount of the enabled
    Bevel modifiers (a one-segment chamfer is at most 2 x its amount wide, and its corners carry its neighbours'
    normals by design), at least 5 mm; 5 cm when no Bevel is live (an applied one: pass min_flat_width yourself,
    2.1 x its amount). Percent-width Bevels have no amount and count as no Bevel."""
    amounts = [m.width for m in ob.modifiers
               if evaluated and m.type == 'BEVEL' and m.show_viewport and m.offset_type != 'PERCENT']
    return max(2.1 * max(amounts), 0.005) if amounts else 0.05


def _planar(mesh, p, tol_deg=0.5):
    """True when face p's corners lie in one plane: every fan triangle's normal within tol_deg of the face's."""
    vs = [mesh.vertices[i].co for i in p.vertices]
    n = p.normal
    if n.length < 0.5:
        return True
    for i in range(1, len(vs) - 1):
        tn = (vs[i] - vs[0]).cross(vs[i + 1] - vs[0])
        if tn.length > 1e-12 and tn.normalized().dot(n) < math.cos(math.radians(tol_deg)):
            return False
    return True


def audit(ob, sliver_deg=2.0, bad_corner_deg=3.0, fold_deg=25.0, short_edge=None, evaluated=True,
          min_flat_width=None, flat_list_deg=0.5, join_tris=False):
    """Counts for one mesh object, in object space, with its modifiers applied (evaluated=True: the modifier stack's
    result; an exporter that triangulates again is not seen; False audits the mesh data alone).
    Poles are interior verts with valence other than 4, triangles included (deliberate ones from reduction templates
    are expected; look at where they are); fan centres have 8+ edges, or 2+ triangles meeting at them (a fan of
    triangles in a quad layout; on a triangulated mesh every vertex counts). Flipped edges are edges whose two faces
    both run along them in the same direction: a face wound the other way from its neighbours. Slivers are faces with
    a corner under sliver_deg, flat-shaded or not.
    Big faces: flat_faces_off_deg is the worst angle between a corner normal and its own face over faces at least
    min_flat_width wide (default flat_floor(ob): 2.1 x the largest live Bevel amount, 5 cm without one; reported as
    flat_min_width), about 0 on a hard-surface piece whose big faces read flat and naturally above 0 on smooth curved
    parts. flat_faces lists the faces over flat_list_deg, worst first, as {"face", "deg", "centre"}: "face" is the
    index of the nearest face of the object's own mesh data (the evaluated mesh's faces are renumbered by the
    modifiers), listed once with its worst evaluated face (the two triangles of a quad, the two halves of a Mirror);
    "centre" is that evaluated face's centre in object space. flat_worst_face is the worst one's "face", or -1.
    custom_normals, cn_quads and cn_quads_bent: whether the evaluated mesh carries custom normals, on how many faces
    of 4+ corners, and how many of those are not planar (an exporter that triangulates one may split it the other
    way; a planar quad keeps its corner normals, measured 0.0 deg on cards with transferred normals). flat_shaded_faces
    counts faces not shaded smooth. short_edge (metres): edges shorter count as short_edges; by default (reported as
    short_edge_m) 1 mm, or 1% of the piece's smallest side over 1 mm when that is less (a 5 mm screw's 0.5 mm head
    rim, the 0.48 mm corners of a 30 cm gear's 1.5 mm chamfers).
    join_tris=True joins triangle pairs back into quads before counting (an applied Triangulate, _join_pairs)."""
    import bmesh
    import bpy
    bm = bmesh.new()
    if evaluated:
        eval_ob = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = eval_ob.to_mesh()
    else:
        eval_ob, mesh = None, ob.data
    if min_flat_width is None:
        min_flat_width = flat_floor(ob, evaluated)
    try:
        bm.from_mesh(mesh)
        worst, at, over = _flatness(mesh, min_flat_width, flat_list_deg)
        custom = bool(mesh.has_custom_normals)
        cn_quads = sum(1 for p in mesh.polygons if p.loop_total >= 4) if custom else 0
        cn_bent = sum(1 for p in mesh.polygons if p.loop_total >= 4 and not _planar(mesh, p)) if custom else 0
        if short_edge is None:
            dims = sorted(max(v.co[k] for v in mesh.vertices) - min(v.co[k] for v in mesh.vertices)
                          for k in range(3)) if len(mesh.vertices) else [0.0]
            sides = [x for x in dims if x > 0.001]
            short_edge = min(0.001, 0.01 * sides[0]) if sides else 0.001
        flat_shaded = sum(1 for p in mesh.polygons if not p.use_smooth)
        worst_centre = mesh.polygons[at].center.copy() if at >= 0 else None
    finally:
        if eval_ob is not None:
            eval_ob.to_mesh_clear()
    if evaluated:
        mapped = _data_faces(ob, [c for _, _, c in over] + ([worst_centre] if worst_centre is not None else []))
    else:
        mapped = [i for _, i, _ in over] + ([at] if at >= 0 else [])
    if join_tris:
        _join_pairs(bm)
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
        if all(len(e.link_faces) == 2 for g in isl for e in g.edges):
            vol6, box = _signed_volume6(isl)
            if box > 0.0 and vol6 < -6.0 * INVERTED_REL_VOLUME * box:
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
    slivers = sum(1 for f in bm.faces if len(f.verts) <= 4 and
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
        flipped_edges=sum(1 for e in bm.edges
                          if len(e.link_loops) == 2 and e.link_loops[0].vert == e.link_loops[1].vert),
        short_edges=sum(1 for e in bm.edges if e.calc_length() < short_edge),
        degenerate_faces=sum(1 for f in bm.faces if f.calc_area() < 1e-8),
        bad_quads=bad_quads, slivers=slivers,
        poles=sum(1 for v in inner if len(v.link_edges) != 4),
        fan_centres=sum(1 for v in inner
                        if len(v.link_edges) >= 8 or sum(1 for f in v.link_faces if len(f.verts) == 3) >= 2),
        loose_verts=sum(1 for v in bm.verts if not v.link_faces),
        flat_faces_off_deg=round(worst, 2), flat_worst_face=mapped[-1] if at >= 0 else -1,
        flat_faces=_one_per_face(mapped, over), flat_min_width=round(min_flat_width, 4),
        custom_normals=custom, cn_quads=cn_quads, cn_quads_bent=cn_bent, flat_shaded_faces=flat_shaded,
        short_edge_m=round(short_edge, 6),
    )
    bm.free()
    return r


def problems(r, allow_open=False, flat_tol=None):
    """The failing keys of an audit result (open edges allowed for pieces meant to be open). flat_tol (degrees): also
    fail when big faces are off flat by more than that, for pieces whose big faces must read flat (hard-surface.md);
    smooth curved parts are over it by design, so read r["flat_faces"] on a piece that has them."""
    keys = ["ngons", "inverted_islands", "flipped_edges", "overfull_edges", "short_edges", "degenerate_faces",
            "bad_quads", "slivers", "loose_verts"] + ([] if allow_open else ["open_edges"])
    found = [k for k in keys if r[k]]
    if flat_tol is not None and r["flat_faces_off_deg"] > flat_tol:
        found.append("flat_faces_off_deg")
    return found


@contextlib.contextmanager
def _viewport(mods, state):
    """Set show_viewport on mods for the duration, then restore each one; the view layer is updated both ways."""
    import bpy
    old = [(m, m.show_viewport) for m in mods]
    for m in mods:
        m.show_viewport = state
    bpy.context.view_layer.update()
    try:
        yield
    finally:
        for m, v in old:
            m.show_viewport = v
        bpy.context.view_layer.update()


def _normals_by_position(ob, digits=5):
    import bpy
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    try:
        cn, out = me.corner_normals, {}
        for li, loop in enumerate(me.loops):
            key = tuple(round(c, digits) for c in me.vertices[loop.vertex_index].co)
            out.setdefault(key, []).append(cn[li].vector.copy())
        return out
    finally:
        ev.to_mesh_clear()


def _normals_change(a, b):
    """The largest angle from a corner normal to the nearest one at the same position in the other set (degrees)."""
    worst = 0.0
    for x, y in ((a, b), (b, a)):
        for pos, normals in x.items():
            ref = y.get(pos)
            if ref:
                worst = max(worst, max(min(math.degrees(n.angle(m, 0.0)) for m in ref) for n in normals))
    return round(worst, 2)


def normals_snapshot(ob):
    """The piece's corner normals as it exports, in world space and grouped by position, read with every Triangulate
    modifier switched on (then restored). Take it while the stack is live, before UV work applies it; afterwards
    audit_stack(ob, before=snapshot) fails when the normals moved. Apply scale before building the stack (Bevel
    amounts are in object space); a piece that already has a live Bevel and scale other than 1 runs the hand-off
    first and applies scale after it: applying scale under a live Bevel changes the chamfers
    (snapshot_geometry_changed)."""
    import bpy
    with _viewport([m for m in ob.modifiers if m.type == 'TRIANGULATE'], True):
        ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
        me = ev.to_mesh()
        try:
            mw = ob.matrix_world.copy()
            nm = mw.to_3x3().inverted_safe().transposed()
            cn, groups = me.corner_normals, {}
            for li, loop in enumerate(me.loops):
                co = mw @ me.vertices[loop.vertex_index].co
                g = groups.setdefault(tuple(round(c, 6) for c in co), (co, []))
                g[1].append((nm @ cn[li].vector).normalized())
            return list(groups.values())
        finally:
            ev.to_mesh_clear()


def _snapshot_change(a, b, tol=1e-4):
    """(the largest angle in degrees from a normal in one snapshot to the nearest normal at the same position, within
    tol metres, in the other, both ways; the smaller share of positions found in the other snapshot)."""
    from mathutils.kdtree import KDTree

    def one_way(x, y):
        if not x or not y:
            return 0.0, 0.0
        kd = KDTree(len(y))
        for i, (co, _) in enumerate(y):
            kd.insert(co, i)
        kd.balance()
        worst, found = 0.0, 0
        for co, normals in x:
            _, i, dist = kd.find(co)
            if i is None or dist > tol:
                continue
            found += 1
            worst = max(worst, max(min(math.degrees(n.angle(m, 0.0)) for m in y[i][1]) for n in normals))
        return worst, found / len(x)
    w1, f1 = one_way(a, b)
    w2, f2 = one_way(b, a)
    return round(max(w1, w2), 2), round(min(f1, f2), 4)


SMOOTH_BY_ANGLE = "Smooth by Angle"
STACK_OFF_KEYS = ("slivers", "bad_quads", "poles", "fan_centres", "tri_faces_pct")


# Modifiers that change the topology (as scripts/hard_surface.py's hand-off counts them), plus Geometry Nodes other
# than Smooth by Angle
TOPOLOGY_TYPES = frozenset({"ARRAY", "BEVEL", "BOOLEAN", "BUILD", "DECIMATE", "EDGE_SPLIT", "MASK", "MIRROR",
                            "MULTIRES", "REMESH", "SCREW", "SKIN", "SOLIDIFY", "SUBSURF", "WELD", "WIREFRAME"})


def _is_smooth_by_angle(m):
    return m.type == 'NODES' and m.node_group is not None and SMOOTH_BY_ANGLE in m.node_group.name


def _changes_topology(m):
    return m.type in TOPOLOGY_TYPES or (m.type == 'NODES' and not _is_smooth_by_angle(m))


def stack_route(ob):
    """"B" when an enabled Weighted Normal modifier is in the stack; "A" when an enabled Bevel has Harden Normals on or
    the mesh data already carries custom normals (a stack applied earlier); None when the piece has no hard-surface
    stack. Disabled modifiers (viewport toggle off) do not count: the export leaves them out too."""
    live = [m for m in ob.modifiers if m.show_viewport]
    if any(m.type == 'WEIGHTED_NORMAL' for m in live):
        return "B"
    if any(m.type == 'BEVEL' and m.harden_normals for m in live) or ob.data.has_custom_normals:
        return "A"
    return None


def audit_stack(ob, allow_open=False, flat_tol=None, normals_tol=0.5, before=None, **kw):
    """Audit a hard-surface piece (references/hard-surface.md) as it exports, judging the counts a triangulation
    distorts on the untriangulated mesh. "triangulate" says how the stack triangulates:
      live      an enabled Triangulate modifier: slivers, bad quads, poles, fan centres and the triangle share come
                from a pass with every enabled Triangulate's viewport toggle (show_viewport) off, restored afterwards;
      applied   no enabled Triangulate and only triangles (applied for a bake, say): those counts come from the mesh
                with triangle pairs joined back into quads;
      disabled  a Triangulate switched off in the viewport; none: no Triangulate. Nothing to undo: one pass.
    Everything else (n-gons, flipped, open and overfull edges, flat_faces_off_deg) is the mesh as it exports.
    "route" is stack_route(ob): "A", "B", or None when the piece has no hard-surface stack (then this is audit() plus
    the Triangulate toggle). Problems beyond problems():
      custom_normals_on_quads       custom normals on faces of 4+ corners as it exports (Triangulate disabled, missing
                                    or above Minimum Vertices 4): the exporter's triangulation changes them;
      triangulate_moves_normals     corner normals change when the Triangulates below the last enabled Weighted Normal
                                    (all of them on route A) are toggled: Keep Normals (keep_custom_normals) is off;
      triangulate_below_weighted_normal  route B whose Weighted Normal has no enabled Triangulate above it but one
                                    below: it weights the untriangulated faces (the stack's Triangulate goes directly
                                    above the Weighted Normal, never after it);
      topology_below_triangulate    a Mirror, Array or other topology-changing modifier below the first Triangulate or
                                    Weighted Normal (modifiers.new appends at the bottom): Mirror and Array go first,
                                    above the Bevel; the UV hand-off refuses such a stack;
      smooth_by_angle_late          a Smooth by Angle below a Bevel, Triangulate or Weighted Normal (Shade Auto Smooth
                                    pins it last): it re-sharpens the chamfers;
      smooth_by_angle_without_bevel a Smooth by Angle with no enabled Bevel below it: the chamfers are already mesh
                                    data (a stack applied without it), and it re-sharpens them;
      flat_shaded_faces             route B with faces not shaded smooth: the Weighted Normal cannot shade the chamfers;
      normals_changed_since_snapshot  with before=normals_snapshot(ob) taken earlier: the normals as exported moved by
                                    more than normals_tol; snapshot_geometry_changed: under 99% of the positions still
                                    match (faces lost or moved, chamfers on a mirror plane say), so the normals could
                                    not be compared.
    Returns {"on", "off", "merged", "route", "triangulate", "normals_change_deg", "snapshot_change_deg",
    "snapshot_matched", "problems"}."""
    kw.setdefault("flat_list_deg", flat_tol if flat_tol is not None else 0.5)
    mods = list(ob.modifiers)
    route = stack_route(ob)
    tris = [m for m in mods if m.type == 'TRIANGULATE' and m.show_viewport]
    last_wn = max([i for i, m in enumerate(mods) if m.type == 'WEIGHTED_NORMAL' and m.show_viewport], default=-1)
    late, no_bevel = False, False
    for i, m in enumerate(mods):
        if route and m.show_viewport and _is_smooth_by_angle(m):
            late = late or any(n.show_viewport and n.type in ('BEVEL', 'TRIANGULATE', 'WEIGHTED_NORMAL')
                               for n in mods[:i])
            no_bevel = no_bevel or not any(n.show_viewport and n.type == 'BEVEL' for n in mods[i + 1:])
    on = audit(ob, **kw)
    change = None
    if tris:
        state = "live"
        compare = [m for m in tris if mods.index(m) > last_wn] if route and not late else []
        a = _normals_by_position(ob) if compare else None
        with _viewport(tris, False):
            off = audit(ob, **kw)
            b = _normals_by_position(ob) if compare and len(compare) == len(tris) else None
        if compare and b is None:
            with _viewport(compare, False):
                b = _normals_by_position(ob)
        change = _normals_change(a, b) if compare else None
    elif route and on["faces"] and on["triangles"] == on["faces"]:
        state = "applied"
        off = audit(ob, join_tris=True, **kw)
    else:
        state = "disabled" if any(m.type == 'TRIANGULATE' for m in mods) else "none"
        off = on
    merged = dict(on, **{k: off[k] for k in STACK_OFF_KEYS})
    found = problems(merged, allow_open, flat_tol)
    live_hs = any(m.show_viewport and (m.type == 'WEIGHTED_NORMAL' or (m.type == 'BEVEL' and m.harden_normals))
                  for m in ob.modifiers)
    if on["cn_quads"] if live_hs else on["cn_quads_bent"]:   # a live hard-surface stack keeps its Triangulate live;
        found.append("custom_normals_on_quads")              # normals in the data (cards) only matter on bent quads
    if change is not None and change > normals_tol:
        found.append("triangulate_moves_normals")
    if late:
        found.append("smooth_by_angle_late")
    elif no_bevel:
        found.append("smooth_by_angle_without_bevel")
    if route == "B" and on["flat_shaded_faces"]:
        found.append("flat_shaded_faces")
    if route == "B" and not any(mods.index(m) < last_wn for m in tris) and any(mods.index(m) > last_wn for m in tris):
        found.append("triangulate_below_weighted_normal")
    anchor = next((i for i, m in enumerate(mods) if m.type in ('TRIANGULATE', 'WEIGHTED_NORMAL')), len(mods))
    if route and any(_changes_topology(m) for m in mods[anchor + 1:]):
        found.append("topology_below_triangulate")
    snap = (None, None)
    if before is not None:
        snap = _snapshot_change(before, normals_snapshot(ob))
        if snap[1] < 0.99:
            found.append("snapshot_geometry_changed")
        elif snap[0] > normals_tol:
            found.append("normals_changed_since_snapshot")
    return dict(on=on, off=off, merged=merged, route=route, triangulate=state, normals_change_deg=change,
                snapshot_change_deg=snap[0], snapshot_matched=snap[1], problems=found)


def audit_many(objects, **kw):
    """Audit several objects; prints a table sorted by triangle count and returns {name: result}."""
    out = {o.name: audit(o, **kw) for o in objects if o.type == 'MESH' and len(o.data.polygons)}
    cols = ["triangles", "tri_faces_pct", "poles", "fan_centres", "bad_quads", "slivers", "open_edges",
            "flat_faces_off_deg"]
    print("piece".ljust(28) + "".join(c.rjust(14) for c in cols) + "  problems")
    for name, r in sorted(out.items(), key=lambda kv: -kv[1]["triangles"]):
        print(name.ljust(28) + "".join(str(r[c]).rjust(14) for c in cols) + "  " + ",".join(problems(r)))
    return out


def joint_match(a, b, select, digits=5, matrix_a=None, matrix_b=None):
    """Do two objects share their vertices on a joint? Positions are compared in one frame: each object's vertices go
    through matrix_a / matrix_b if given (otherwise as they sit in object space). Kit pieces all have their pivot at
    the origin, so to check a 2 m wall's x=2 end against the next wall's x=0 end pass
    matrix_b=Matrix.Translation((2, 0, 0)). select(co) picks joint vertices, given the transformed position.
    Returns (only in a, only in b, shared) as sets of rounded positions."""
    def pts(ob, m):
        out = set()
        for v in ob.data.vertices:
            co = m @ v.co if m is not None else v.co
            if select(co):
                out.add(tuple(round(c, digits) for c in co))
        return out
    pa, pb = pts(a, matrix_a), pts(b, matrix_b)
    return pa - pb, pb - pa, pa & pb


def joint_normals(a, b, select, digits=5, matrix_a=None, matrix_b=None):
    """Does the shading carry on across a joint? At each joint position the two pieces share (as joint_match finds
    them, in one frame through matrix_a / matrix_b), each corner normal of either evaluated mesh is matched to the
    nearest corner normal of the other piece there (its front against the neighbour's front, its top against the top).
    Faces lying wholly in the joint (every corner selected: the end caps pressed together) are left out, so a crease
    of any angle counts (a piece smoothed across its folds against a hard-shaded one reads 54.7 deg). The worst match,
    both ways, is reported. A smooth curved piece ending against a straight one leans its end vertices by half a facet
    angle, a crease in the shading at every such joint; custom normals on the joint vertices set to the true surface
    normal put it right. Returns {"positions": shared positions compared, "max_deg", "worst": [(deg, position),
    ...]}."""
    import bpy
    dg = bpy.context.evaluated_depsgraph_get()

    def corners(ob, m):
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        try:
            rot = (m.to_3x3() if m is not None else None)
            out = {}
            for p in me.polygons:
                pos = [m @ me.vertices[i].co if m is not None else me.vertices[i].co.copy() for i in p.vertices]
                inside = [bool(select(co)) for co in pos]
                if all(inside):
                    continue                                   # an end cap lying in the joint
                for li, co, sel in zip(p.loop_indices, pos, inside):
                    if not sel:
                        continue
                    n = me.corner_normals[li].vector.copy()
                    if rot is not None:
                        n = (rot.inverted().transposed() @ n).normalized()
                    out.setdefault(tuple(round(c, digits) for c in co), []).append(n)
            return out
        finally:
            ev.to_mesh_clear()
    ca, cb = corners(a, matrix_a), corners(b, matrix_b)
    shared = set(ca) & set(cb)
    per = {key: 0.0 for key in shared}
    for x, y in ((ca, cb), (cb, ca)):
        for key in shared:
            for n in x[key]:
                per[key] = max(per[key], min(math.degrees(n.angle(m, 0.0)) for m in y[key]))
    worst = sorted(((round(d, 3), list(key)) for key, d in per.items()), key=lambda w: -w[0])
    return {"positions": len(worst), "max_deg": worst[0][0] if worst else 0.0, "worst": worst[:5]}


def determinism_hash(ob, digits=5):
    """A short hash of the mesh data's vertex positions and faces (each face as its corner positions in winding order,
    starting from the smallest): equal across two builds means the generator made the same mesh, topology included.
    Vertex and face order do not matter; a flipped face or a different diagonal does."""
    pos = [tuple(round(float(c), digits) + 0.0 for c in v.co) for v in ob.data.vertices]   # + 0.0: -0.0 -> 0.0
    faces = []
    for p in ob.data.polygons:
        corners = [pos[i] for i in p.vertices]
        k = min(range(len(corners)), key=lambda i: corners[i])
        faces.append(tuple(corners[k:] + corners[:k]))
    key = repr((sorted(pos), sorted(faces))).encode()
    return hashlib.md5(key).hexdigest()[:12]


# ---- high and low poly ---------------------------------------------------------------------------------------------

def _world_mesh(ob, dg, with_poly=False):
    """(vertices (n, 3), triangles (m, 3), triangle areas, vertex normals (n, 3)) of ob as evaluated, in world space,
    and with_poly each triangle's polygon index. A mirrored object (negative scale) has its triangles' winding
    reversed so they still face outward."""
    import numpy as np
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        mw = np.array(ev.matrix_world)
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
        vn = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("normal", vn)
        vn = vn.reshape(-1, 3) @ np.linalg.inv(mw[:3, :3])
        vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)
        me.calc_loop_triangles()
        tri = np.empty(len(me.loop_triangles) * 3, np.int64)
        me.loop_triangles.foreach_get("vertices", tri)
        tri = tri.reshape(-1, 3)
        if np.linalg.det(mw[:3, :3]) < 0:
            tri = tri[:, ::-1].copy()
        area = 0.5 * np.linalg.norm(np.cross(co[tri[:, 1]] - co[tri[:, 0]], co[tri[:, 2]] - co[tri[:, 0]]), axis=1)
        if with_poly:
            tpoly = np.empty(len(me.loop_triangles), np.int64)
            me.loop_triangles.foreach_get("polygon_index", tpoly)
            return co, tri, area, vn, tpoly
        return co, tri, area, vn
    finally:
        ev.to_mesh_clear()


def _surface_samples(co, tri, area, n, seed=0):
    """n points spread over the triangles by area (none when the surface has no area)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    if n <= 0 or area.sum() <= 0:
        return np.zeros((0, 3))
    pick = rng.choice(len(tri), size=n, p=area / area.sum())
    a, b = rng.random(n), rng.random(n)
    flip = a + b > 1
    a[flip], b[flip] = 1 - a[flip], 1 - b[flip]
    t = tri[pick]
    return co[t[:, 0]] + a[:, None] * (co[t[:, 1]] - co[t[:, 0]]) + b[:, None] * (co[t[:, 2]] - co[t[:, 0]])


def _signed_outside(points, trees):
    """Per point: its signed distance outside the nearest surface among trees (positive: on the side its normal
    points to)."""
    import numpy as np
    from mathutils import Vector
    out = np.empty(len(points))
    for i, p in enumerate(points):
        best = None
        for t in trees:
            loc, nrm, _idx, dist = t.find_nearest(Vector(p))
            if loc is not None and (best is None or dist < best[0]):
                best = (dist, loc, nrm)
        out[i] = 0.0 if best is None else float(np.dot(np.asarray(p) - np.asarray(best[1]), np.asarray(best[2])))
    return out


def high_low_gap(low, highs, depsgraph=None, samples=20000, seed=0):
    """How far a low poly and its high polys part, in metres, both evaluated in world space (closed meshes with
    outward normals): high_outside, how far the high stands outside the low (the relief the bake turns into a normal
    map, and how far the cage must reach); low_outside, how far the low stands outside every high (a silhouette the
    high does not have). The highs are one surface, sampled by area (`samples` points each side): splitting a high
    into two objects or adding rivets changes nothing. Percentiles (p99, p999) come from the area samples, max from
    those and every vertex. Where the low stands outside the high, a point whose surroundings on the low (3 x its
    distance away, at least 2 mm) meet the high again lies over a recess of the high (a groove, a panel line, a dent:
    relief the bake carries), the rest is a bulge of the low. Judge them at the nearest viewing distance d with
    detail_scale.py: low_outside_max (bulges only) above min_width_m(d) (2 px) is a silhouette the player sees that
    the texture cannot explain (a 4 cm bump on 0.6% of a low read p99 0); high_outside_p99 and recess_max above
    stereo_relief_m(d) are relief that shows depth and belongs in the low's geometry (a crate's 1.5 mm V grooves are
    recesses, not bulges). low_outside_raw_max is the largest before that split. Raises ValueError for a low or high
    with no faces. Read-only."""
    import bpy
    import numpy as np
    from mathutils.bvhtree import BVHTree
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    lo = _world_mesh(low, dg)
    hi = [_world_mesh(h, dg) for h in highs]
    empty = [ob.name for ob, m in zip([low] + list(highs), [lo] + hi) if not len(m[1])]
    if empty or not hi:
        raise ValueError("high_low_gap needs faces on the low and on at least one high: %s"
                         % (", ".join(empty) or "no highs given"))
    offs = np.cumsum([0] + [len(h[0]) for h in hi])
    hco = np.vstack([h[0] for h in hi])
    htri = np.vstack([h[1] + o for h, o in zip(hi, offs)])
    harea = np.concatenate([h[2] for h in hi])
    tree = lambda co, tri: BVHTree.FromPolygons([tuple(c) for c in co], [tuple(int(i) for i in t) for t in tri])
    low_tree, high_tree = tree(lo[0], lo[1]), tree(hco, htri)
    hs = np.maximum(_signed_outside(_surface_samples(hco, htri, harea, samples, seed), [low_tree]), 0.0)
    lpts = _surface_samples(lo[0], lo[1], lo[2], samples, seed)
    ls = np.maximum(_signed_outside(lpts, [high_tree]), 0.0)
    hv = np.maximum(_signed_outside(hco, [low_tree]), 0.0)
    lv = np.maximum(_signed_outside(lo[0], [high_tree]), 0.0)
    bulge, recess = _split_recesses(np.vstack([lpts, lo[0]]), np.concatenate([ls, lv]), low_tree, high_tree)
    r = lambda v: round(float(v), 5)
    pct = lambda v, q: r(np.percentile(v, q)) if len(v) else 0.0
    return {"high_outside_max": r(max(hs.max(initial=0.0), hv.max(initial=0.0))),
            "high_outside_p99": pct(hs, 99), "high_outside_p999": pct(hs, 99.9),
            "low_outside_max": r(bulge), "recess_max": r(recess),
            "low_outside_raw_max": r(max(ls.max(initial=0.0), lv.max(initial=0.0))),
            "low_outside_p99": pct(ls, 99), "low_outside_p999": pct(ls, 99.9),
            "points": [int(len(hs) + len(hv)), int(len(ls) + len(lv))]}


def _split_recesses(points, outside, low_tree, high_tree, cap=4000, floor=1e-4):
    """(largest bulge, largest recess) among the low points standing outside the high, worst first: around a point
    at distance d, eight points 3 d away (at least 2 mm) on the low's surface; if any of them lies within d / 4 of the
    high, the high comes back up there and the point sits over a recess. The first bulge found is the largest; at
    most `cap` points are classified."""
    import math
    import numpy as np
    from mathutils import Vector
    order = np.argsort(-outside)
    recess = 0.0
    for n, i in enumerate(order):
        d = float(outside[i])
        if d <= floor or n >= cap:
            return (d if n >= cap else 0.0), recess
        p = Vector(points[i])
        loc, nrm, _f, _dist = low_tree.find_nearest(p)
        if loc is None:
            return d, recess
        t1 = nrm.orthogonal().normalized()
        t2 = nrm.cross(t1)
        rad = max(3.0 * d, 0.002)
        back = False
        for k in range(8):
            a = 2.0 * math.pi * k / 8
            q = low_tree.find_nearest(loc + rad * (math.cos(a) * t1 + math.sin(a) * t2))[0]
            h = high_tree.find_nearest(q) if q is not None else (None,)
            if h[0] is not None and float((q - h[0]).dot(h[1])) < 0.25 * d:
                back = True
                break
        if not back:
            return d, recess
        recess = max(recess, d)
    return 0.0, recess


def bake_skew(low, limit_deg=15.0, depsgraph=None, highs=None, faces=None, relief_m=None):
    """Where a bake's rays leave a low poly at a slant. A cage built from averaged normals (Blender's Selected to
    Active with a cage, and bake_maps.py) casts each ray along the vertex normals interpolated across the triangle, so
    at each of 15 barycentric points per triangle this takes the angle between that interpolated normal and the
    surface it lands on: the high's normal at the nearest high point when highs are given (what skews detail: a
    cylinder low built to the chord rule sends radial rays onto a round high and reads 0), else the low face's own
    normal. Detail projected along a slanted ray lands shifted ("skewed") by about relief x tan(angle): 15 deg moves
    10 mm of relief 2.7 mm. faces: the low's polygon indices to judge (the faces a player sees; default all).
    Returns the share of the judged area over limit_deg, the area-weighted p95 angle and the worst faces' centres;
    with relief_m (the baked relief, high_low_gap's high_outside_p99) also shift_m, relief x tan(p95): how far the
    detail lands off, to hold against detail_scale's min_width_m(d) (a 0.7 mm bottle relief at 26 deg moves 0.34 mm).
    Read-only."""
    import bpy
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    co, tri, area, vn, tpoly = _world_mesh(low, dg, with_poly=True)
    if faces is not None:
        keep = np.isin(tpoly, np.asarray(list(faces), np.int64))
        tri, area = tri[keep], area[keep]
    if not len(tri):
        return {"over_share": 0.0, "p95_deg": 0.0, "limit_deg": limit_deg, "worst": [], "against": "none",
                "shift_m": 0.0 if relief_m is not None else None}
    fn = np.cross(co[tri[:, 1]] - co[tri[:, 0]], co[tri[:, 2]] - co[tri[:, 0]])
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    bary = np.array([(i / 4.0, j / 4.0, 1.0 - (i + j) / 4.0) for i in range(5) for j in range(5 - i)])
    n = np.einsum("pk,tkc->tpc", bary, vn[tri])                     # (triangles, 15 points, 3)
    n /= np.maximum(np.linalg.norm(n, axis=2, keepdims=True), 1e-12)
    if highs:
        hs = [_world_mesh(h, dg) for h in highs]
        offs = np.cumsum([0] + [len(h[0]) for h in hs])
        tree = BVHTree.FromPolygons([tuple(c) for c in np.vstack([h[0] for h in hs])],
                                    [tuple(int(i) for i in t) for t in np.vstack([h[1] + o for h, o in zip(hs, offs)])])
        pts = np.einsum("pk,tkc->tpc", bary, co[tri])
        ref = np.empty_like(n)
        for ti in range(len(tri)):
            for pi in range(len(bary)):
                hit = tree.find_nearest(Vector(pts[ti, pi]))
                ref[ti, pi] = tuple(hit[1]) if hit[0] is not None else fn[ti]
    else:
        ref = np.repeat(fn[:, None, :], len(bary), axis=1)
    ang = np.degrees(np.arccos(np.clip((n * ref).sum(axis=2), -1.0, 1.0)))
    w = np.repeat(area[:, None] / len(bary), len(bary), axis=1)
    flat, wf = ang.ravel(), w.ravel()
    order = np.argsort(flat)
    cum = np.cumsum(wf[order])
    p95 = float(flat[order][min(len(order) - 1, np.searchsorted(cum, 0.95 * cum[-1]))])
    mean_t = ang.mean(axis=1)
    worst = np.argsort(-mean_t)[:5]
    centre = co[tri].mean(axis=1)
    return {"over_share": round(float(wf[flat > limit_deg].sum() / max(wf.sum(), 1e-12)), 4), "p95_deg": round(p95, 2),
            "limit_deg": limit_deg, "against": "high" if highs else "low faces",
            "shift_m": round(float(relief_m) * math.tan(math.radians(p95)), 6) if relief_m is not None else None,
            "worst": [(round(float(mean_t[i]), 1), [round(float(x), 3) for x in centre[i]])
                      for i in worst if mean_t[i] > limit_deg]}