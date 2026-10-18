"""Quad Remesher's engine from Python, with frozen borders, validation and mirroring (see ../references/quad-remesher.md).

Host: Blender with the Quad Remesher add-on installed and run once (that downloads the engine); tested with Quad
Remesher 1.4.1 on Blender 5.2.2, Windows. weld_layout and mirror_half need only mathutils.
Load in Blender:  ns = {}; exec(open(r"<skill>/scripts/quad_remesh.py", encoding="utf-8").read(), ns)

    pts, tris, loop_points = ns["patch_input"](obj)         # a patch object with one border (a disc, or one half)
    faces, npos, raw = ns["remesh_patch"](pts, tris, loop_points, target=400)   # remesh, validate, retry other targets
    qp, qf, qm = ns["quad_remesh"](pts, faces, mats=None, TargetQuadCount=400, FreezeBorders=1)   # one engine run
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


def quad_remesh(pts, faces, mats=None, engine=None, timeout=600, **opts):
    """Remesh a mesh given as points (object space) and faces. mats: 0/1 per face, with UseMaterialIds keeps an edge
    loop on their border. opts: settings keys (TargetQuadCount, FreezeBorders, CurvatureAdaptivness, ...). Returns
    (points, faces, material index per face)."""
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
