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
    ns["determinism_hash"](obj)                               # compare across two builds: vertices and faces

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


def audit(ob, sliver_deg=2.0, bad_corner_deg=3.0, fold_deg=25.0, short_edge=0.001, evaluated=True,
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
    custom_normals and cn_quads: whether the evaluated mesh carries custom normals, and on how many faces of 4+
    corners (an exporter that triangulates changes those). flat_shaded_faces counts faces not shaded smooth.
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
        custom_normals=custom, cn_quads=cn_quads, flat_shaded_faces=flat_shaded,
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
    if on["cn_quads"]:
        found.append("custom_normals_on_quads")
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
