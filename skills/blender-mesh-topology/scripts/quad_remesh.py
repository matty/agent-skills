"""Quad Remesher's engine from Python, with frozen borders, validation and mirroring (see ../references/quad-remesher.md).

Host: Blender with the Quad Remesher add-on installed and run once (that downloads the engine); tested with Quad
Remesher 1.4.1 on Blender 5.2.2, Windows. weld_layout and mirror_half need only mathutils.
Load in Blender:  ns = {}; exec(open(r"<skill>/scripts/quad_remesh.py", encoding="utf-8").read(), ns)

    pts, tris, loop_points = ns["patch_input"](obj)         # a patch object with one border (a disc, or one half)
    faces, npos, raw = ns["remesh_patch"](pts, tris, loop_points, target=400)   # remesh, validate, retry other targets
    qp, qf, qm = ns["quad_remesh"](pts, faces, mats=None, TargetQuadCount=400, FreezeBorders=1)   # one engine run
    qp, qf, qm, tries = ns["quad_remesh_to_budget"](pts, faces, 700, CurvatureAdaptivness=20.0, SymAxis="X",
                                                    SymLocal=1)            # a whole organic low at a set budget
    layout = ns["weld_layout"](qp, qf, loop_points)          # None if not clean: retry with another target

A half remeshed up to its mirror line (x = 0) is made whole with mirror_half, building into a bmesh through
grid_topology's PointCache so the two halves share the loop's vertices:

    bm = bmesh.new(); cache = gt["PointCache"](bm)           # gt: grid_topology.py loaded the same way
    loop_verts = [cache.get(p) for p in loop_points]
    for sign in (1, -1):
        ns["mirror_half"](faces, npos, loop_verts, mirror_vert=lambda lv: cache.get((-lv.co.x, lv.co.y, lv.co.z)),
                          new_vert=lambda co: cache.get(co), face=lambda vs: bm.faces.new(vs), sign=sign)
    cache.weld(); bm.to_mesh(me)

Settings written by default (the add-on's own defaults differ where noted): TargetQuadCount 1000 (add-on 5000),
CurvatureAdaptivness 50, ExactQuadCount 0 (Adapt Quad Count on), AutoDetectHardEdges 0 (add-on 1), UseMaterialIds 1
when mats is given. Any engine key can be passed as a keyword.
The scene is left as it was: the temporary objects, meshes and materials are removed and the selection restored.
"""

import glob
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter

import bpy
from mathutils import Vector, kdtree


def _engine_folder_root():
    """Where the add-on installs engines, per https://exoside.com/quadremesher-troubleshooting (checked 2026-10-17)."""
    if sys.platform == "win32":
        return os.path.join(os.getenv("ALLUSERSPROFILE", r"C:\ProgramData"), "Exoside", "QuadRemesher", "Datas_Blender")
    if sys.platform == "darwin":
        return "/Users/Shared/Exoside/QuadRemesher/Datas_Blender"
    return os.path.expanduser("~/.local/share/Exoside/QuadRemesher/Datas_Blender")


def find_engine():
    """The newest installed engine (QuadRemesherEngine_<version>/xremesh[.exe]), or the 1.4 path if none is found."""
    exe = "xremesh.exe" if sys.platform == "win32" else "xremesh"
    found = glob.glob(os.path.join(_engine_folder_root(), "QuadRemesherEngine_*", exe))

    def version(path):
        m = re.search(r"QuadRemesherEngine_([\d.]+)", path)
        return tuple(int(x) for x in m.group(1).split(".") if x) if m else ()
    found.sort(key=version, reverse=True)
    return found[0] if found else os.path.join(_engine_folder_root(), "QuadRemesherEngine_1.4", exe)


def _work_folder():
    """The folder the engine requires (the add-on's: %TEMP%/Exoside/QuadRemesher/Blender on Windows)."""
    if sys.platform == "darwin":
        base = "/var/tmp/Exoside"
    elif sys.platform.startswith("linux"):
        base = "/tmp/Exoside"
    else:
        base = os.path.join(tempfile.gettempdir(), "Exoside")
    return os.path.join(base, "QuadRemesher", "Blender").replace("\\", "/")


ENGINE = find_engine()


def density_colour(factor):
    """The vertex colour (sRGB) the add-on paints for a quad-density factor: white 1, red (1, 1 - t, 1 - t) up to 4 x
    as dense at t = 1 (factor 1 + 3 t), cyan (1 - t, 1, 1) down to a quarter (factor 1 / (1 + 3 t)); the add-on's own
    slider mapping (quad_remesher_1_4 __init__.paintDensityPropertyCB)."""
    f = min(max(float(factor), 0.25), 4.0)
    if f >= 1.0:
        t = (f - 1.0) / 3.0
        return (1.0, 1.0 - t, 1.0 - t)
    t = (1.0 / f - 1.0) / 3.0
    return (1.0 - t, 1.0, 1.0)


def quad_remesh(pts, faces, mats=None, engine=None, timeout=600, density=None, **opts):
    """Remesh a mesh given as points (object space) and faces. mats: 0/1 per face, with UseMaterialIds keeps an edge
    loop on their border. density: a quad-density factor per point (0.25 to 4, 1 = the target's own size), written
    as the add-on's painted vertex colours with UseVertexColorMap on: put quads where they are needed (a low's
    protruding parts) at the same TargetQuadCount. opts: settings keys (TargetQuadCount, FreezeBorders,
    CurvatureAdaptivness, ...). Returns (points, faces, material index per face)."""
    engine = engine or ENGINE
    if not os.path.exists(engine):
        raise RuntimeError("Quad Remesher engine not found at %s (install the add-on and run it once)" % engine)
    wd = _work_folder()
    os.makedirs(wd, exist_ok=True)
    fin, fout, prog, sett = (wd + "/inputMesh.fbx", wd + "/retopo.fbx", wd + "/progress.txt", wd + "/RetopoSettings.txt")
    for f in (fout, prog):
        if os.path.exists(f):
            os.remove(f)
    before_obj, before_mat = set(bpy.data.objects), set(bpy.data.materials)
    vl = bpy.context.view_layer
    sel, act = list(bpy.context.selected_objects), vl.objects.active
    me = bpy.data.meshes.new("_qr_in")
    me.from_pydata([tuple(p) for p in pts], [], [tuple(f) for f in faces])
    if density is not None:
        if len(density) != len(pts):
            raise ValueError("density has %d values for %d points" % (len(density), len(pts)))
        col = me.color_attributes.new("QR_density", "BYTE_COLOR", "POINT")
        for v, f in zip(col.data, density):
            v.color_srgb = density_colour(f) + (1.0,)
        me.color_attributes.active_color = col
        opts = dict(opts, UseVertexColorMap="True")
    if mats is not None:
        for k in range(max(mats) + 1):
            me.materials.append(bpy.data.materials.new("_qr_m%d" % k))
        me.polygons.foreach_set("material_index", list(mats))
    ob = bpy.data.objects.new("_qr_in", me)
    bpy.context.scene.collection.objects.link(ob)
    try:
        for o in sel:
            o.select_set(False)
        ob.select_set(True)
        vl.objects.active = ob
        # Exactly the add-on's export: raw object-space values, no unit or axis conversion.
        bpy.ops.export_scene.fbx(filepath=fin, use_selection=True, bake_anim=False, global_scale=1,
                                 apply_unit_scale=False, apply_scale_options='FBX_SCALE_NONE', use_space_transform=False,
                                 axis_forward='-X', axis_up='Z')
        s = dict(HostApp="Blender", HostAppVer=bpy.app.version_string, FileIn='"%s"' % fin, FileOut='"%s"' % fout,
                 ProgressFile='"%s"' % prog, TargetQuadCount=1000, CurvatureAdaptivness=50.0, ExactQuadCount=0,
                 UseVertexColorMap="False", UseMaterialIds=int(mats is not None), UseIndexedNormals=0,
                 AutoDetectHardEdges=0)
        s.update(opts)
        with open(sett, "w") as fh:
            fh.write("".join("%s=%s\n" % kv for kv in s.items()))
        subprocess.run([engine, "-s", sett], timeout=timeout)
        status = "no progress file"
        if os.path.exists(prog):
            with open(prog) as fh:
                status = fh.read().strip()
        if not os.path.exists(fout):
            raise RuntimeError("Quad Remesher failed: " + status)
        # Like the add-on (use_manual_orientation=True with the export's axes). Only the object's matrix depends on
        # these; the local mesh data read below stays in the exported space unless bake_space_transform is on.
        bpy.ops.import_scene.fbx(filepath=fout, global_scale=1, use_manual_orientation=True, axis_forward='-X',
                                 axis_up='Z')
        new = [o for o in bpy.data.objects if o not in before_obj and o is not ob]
        res = next((o for o in new if o.type == 'MESH'), None)
        if res is None:
            raise RuntimeError("Quad Remesher wrote no mesh: " + status)
        out = ([v.co.copy() for v in res.data.vertices], [list(p.vertices) for p in res.data.polygons],
               [p.material_index for p in res.data.polygons])
    finally:
        for o in [o for o in bpy.data.objects if o not in before_obj]:     # the input object and everything imported
            d = o.data
            bpy.data.objects.remove(o)
            if isinstance(d, bpy.types.Mesh) and d.users == 0:
                bpy.data.meshes.remove(d)
        for mt in set(bpy.data.materials) - before_mat:
            bpy.data.materials.remove(mt)
        for o in sel:
            if o.name in bpy.data.objects:
                o.select_set(True)
        vl.objects.active = act
    return out


def crossings(pts, faces):
    """How many faces cut through another face of the same mesh (faces sharing a vertex do not count)."""
    from mathutils.bvhtree import BVHTree
    tree = BVHTree.FromPolygons([tuple(p) for p in pts], [tuple(f) for f in faces])
    sets = [set(f) for f in faces]
    bad = set()
    for i, j in tree.overlap(tree):
        if i != j and not sets[i] & sets[j]:
            bad.update((i, j))
    return len(bad)


def quad_remesh_to_budget(pts, faces, quads, tol=0.06, runs=4, clean=True, nudges=(0.97, 1.03, 0.94, 1.06, 0.91, 1.09),
                          **opts):
    """quad_remesh() steered to `quads` faces (within tol) with the engine's adaptive count left on: adaptive mode and a
    density map both ignore ExactQuadCount, so the target is scaled by quads / got and the engine run again (one to
    three more runs). clean=True: a result whose faces cut through each other (crossings(): a thin wall's two sides,
    a leg's root through the body) is run again at the nudged targets, and the first clean one within tol is kept,
    else the one with the fewest. Measured 2026-11-02 on a generated cauldron: the same settings gave 0, 8, 19, 18, 7
    and 14 crossing faces at targets 1.0, 0.94, 1.06, 0.88, 1.12 and 1.2 x the budget: which runs cross is chance.
    Returns (points, faces, materials, [(target, faces got, crossing faces), ...]).
    Measured on four generated props at one budget: adaptive count with CurvatureAdaptivness 20 and SymAxis on the
    symmetric ones gave a cauldron 56 irregular vertices against 109 with ExactQuadCount=1 (mean quad corner 7.1
    against 10.2 degrees off square), a sack 96 against 127 (15.0 against 20.9 degrees)."""
    def run(target):
        out = quad_remesh(pts, faces, TargetQuadCount=max(int(round(target)), 4), **opts)
        c = crossings(out[0], out[1]) if clean else 0
        tries.append((max(int(round(target)), 4), len(out[1]), c))
        return out, c
    target, tries = float(quads), []
    out, c = run(target)
    for _ in range(int(runs) - 1):
        if abs(len(out[1]) / float(quads) - 1.0) <= tol:
            break
        target *= quads / float(max(len(out[1]), 1))
        out, c = run(target)
    best = (c, out)
    if clean and c:
        base = target
        for f in nudges:
            o2, c2 = run(base * f)
            if abs(len(o2[1]) / float(quads) - 1.0) > tol:
                continue
            if c2 < best[0]:
                best = (c2, o2)
            if c2 == 0:
                break
    out = best[1]
    return out[0], out[1], out[2], tries


def weld_layout(qp, qf, loop, tol=2e-4, log=None):
    """Weld the engine's output to a frozen border loop (list of points in order) and check it. Returns (faces,
    new_points) with vertex keys ("L", loop index) or ("N", k), or None when it is not clean: every border edge must be
    a loop edge and no edge may have more than two faces. Repeated border points, collapsed faces and hairpin faces
    (which the engine leaves at frozen borders) are dropped."""
    lk = kdtree.KDTree(len(loop))
    for i, p in enumerate(loop):
        lk.insert(p, i)
    lk.balance()
    ids, own = [], {}
    for p in qp:
        _, i, d = lk.find(p)
        ids.append(("L", i) if d < tol else own.setdefault(tuple(round(c / 1e-4) for c in p), ("N", len(own))))
    npos = {k: Vector(qp[j]) for j, k in enumerate(ids) if k[0] == "N"}
    faces, seen = [], set()
    for f in qf:
        vs = [ids[i] for i in f]
        vs = [v for k, v in enumerate(vs) if v != vs[k - 1]]
        if len(vs) < 3 or len(set(vs)) != len(vs) or frozenset(vs) in seen:
            continue
        seen.add(frozenset(vs))
        faces.append(vs)
    if not faces:
        if log is not None:
            log.append("no faces left")
        return None
    ec = Counter(frozenset((f[k], f[k - 1])) for f in faces for k in range(len(f)))
    if max(ec.values()) > 2:
        if log is not None:
            log.append("edge with %d faces" % max(ec.values()))
        return None
    border = {e for e, c in ec.items() if c == 1}
    want = {frozenset((("L", i), ("L", (i + 1) % len(loop)))) for i in range(len(loop))}
    if border != want:
        if log is not None:
            log.append("border: %d extra, %d missing edges" % (len(border - want), len(want - border)))
        return None
    return faces, npos


def patch_input(ob):
    """(pts, tris, loop_points) for remesh_patch from a mesh object that is one patch with one border: a disc-like
    region split off a mesh, or one half up to its mirror line. Object space, from the mesh data (apply modifiers
    first); the faces are triangulated in a copy, the object is not changed. loop_points runs once round the border in
    order; it is the frozen loop, so space it near the target edge and give it an even count first
    (references/quad-remesher.md). Raises ValueError when the border is not one simple closed loop."""
    import bmesh
    bm = bmesh.new()
    try:
        bm.from_mesh(ob.data)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()
        pts = [v.co.copy() for v in bm.verts]
        tris = [tuple(v.index for v in f.verts) for f in bm.faces]
        nb = {}
        for e in bm.edges:
            if e.is_boundary:
                a, b = (v.index for v in e.verts)
                nb.setdefault(a, []).append(b)
                nb.setdefault(b, []).append(a)
    finally:
        bm.free()
    if not nb:
        raise ValueError("the patch has no border")
    if any(len(v) != 2 for v in nb.values()):
        raise ValueError("the border is not a simple loop: a vertex sits on 3+ border edges")
    start = next(iter(nb))
    loop, prev, cur = [start], None, start
    while True:
        a, b = nb[cur]
        nxt = a if a != prev else b
        if nxt == start:
            break
        loop.append(nxt)
        prev, cur = cur, nxt
    if len(loop) != len(nb):
        raise ValueError("the border is several loops (%d of %d border vertices in the first): one border only"
                         % (len(loop), len(nb)))
    return pts, tris, [pts[i].copy() for i in loop]


def remesh_patch(pts, tris, loop, target, mats=None, tweaks=(1.0, 0.96, 1.04, 0.92, 1.08, 0.88, 1.12), **opts):
    """quad_remesh + weld_layout with FreezeBorders on, retrying other target counts until the layout is clean.
    Returns (faces, new_points, raw output) or raises. Retry with another input fill spacing yourself if every target
    fails."""
    log = []
    opts = dict(opts, FreezeBorders=opts.get("FreezeBorders", 1))
    for t in tweaks:
        out = quad_remesh(pts, tris, mats, **dict(opts, TargetQuadCount=max(25, round(t * target))))
        lay = weld_layout(out[0], out[1], loop, log=log)
        if lay is not None:
            return lay[0], lay[1], out
    raise RuntimeError("no clean layout: " + "; ".join(log))


def mirror_half(faces, npos, loop_verts, mirror_vert, new_vert, face, sign=1):
    """Make one half from a welded layout: loop keys map to loop_verts (sign 1) or to mirror_vert(loop vert) (sign -1);
    new points to new_vert(co) with x mirrored for sign -1. Face winding is reversed for the mirror image."""
    made = {}

    def v(key):
        if key not in made:
            if key[0] == "L":
                lv = loop_verts[key[1]]
                made[key] = lv if sign > 0 else mirror_vert(lv)
            else:
                p = npos[key]
                made[key] = new_vert(Vector((sign * p.x, p.y, p.z)))
        return made[key]
    return [face([v(k) for k in (f if sign > 0 else f[::-1])]) for f in faces]
