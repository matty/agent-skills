"""Quad Remesher's engine from Python, with frozen borders, validation and mirroring (see ../references/quad-remesher.md).

Load in Blender:  ns = {}; exec(open(r"<skill>/scripts/quad_remesh.py", encoding="utf-8").read(), ns)

    qp, qf, qm = ns["quad_remesh"](pts, faces, mats=None, TargetQuadCount=400, FreezeBorders=1)
    layout = ns["weld_layout"](qp, qf, loop_points)          # None if not clean: retry with another target
    for sign in (1, -1): ns["mirror_half"](...)             # optional: build the other half yourself

The scene is left as it was: the temporary objects, meshes and materials are removed and the selection restored.
"""

import os
import subprocess
import tempfile
from collections import Counter

import bpy
from mathutils import Vector, kdtree

ENGINE = os.path.join(os.getenv("ALLUSERSPROFILE", r"C:\ProgramData"), "Exoside", "QuadRemesher", "Datas_Blender",
                      "QuadRemesherEngine_1.4", "xremesh.exe")


def quad_remesh(pts, faces, mats=None, engine=ENGINE, timeout=600, **opts):
    """Remesh a mesh given as points (object space) and faces. mats: 0/1 per face, with UseMaterialIds keeps an edge
    loop on their border. opts: settings keys (TargetQuadCount, FreezeBorders, CurvatureAdaptivness, ...). Returns
    (points, faces, material index per face)."""
    if not os.path.exists(engine):
        raise RuntimeError("Quad Remesher engine not found at %s (install the add-on and run it once)" % engine)
    wd = os.path.join(tempfile.gettempdir(), "Exoside", "QuadRemesher", "Blender").replace("\\", "/")
    os.makedirs(wd, exist_ok=True)
    fin, fout, prog, sett = (wd + "/inputMesh.fbx", wd + "/retopo.fbx", wd + "/progress.txt", wd + "/RetopoSettings.txt")
    for f in (fout, prog):
        if os.path.exists(f):
            os.remove(f)
    me = bpy.data.meshes.new("_qr_in")
    me.from_pydata([tuple(p) for p in pts], [], [tuple(f) for f in faces])
    if mats is not None:
        for k in range(max(mats) + 1):
            me.materials.append(bpy.data.materials.new("_qr_m%d" % k))
        me.polygons.foreach_set("material_index", list(mats))
    ob = bpy.data.objects.new("_qr_in", me)
    bpy.context.scene.collection.objects.link(ob)
    vl = bpy.context.view_layer
    sel, act = list(bpy.context.selected_objects), vl.objects.active
    before_obj, before_mat = set(bpy.data.objects), set(bpy.data.materials)
    try:
        for o in sel:
            o.select_set(False)
        ob.select_set(True)
        vl.objects.active = ob
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
        status = open(prog).read().strip() if os.path.exists(prog) else "no progress file"
        if not os.path.exists(fout):
            raise RuntimeError("Quad Remesher failed: " + status)
        bpy.ops.import_scene.fbx(filepath=fout, global_scale=1, axis_forward='-X', axis_up='Z')
        new = [o for o in bpy.data.objects if o not in before_obj and o is not ob]
        res = next(o for o in new if o.type == 'MESH')
        out = ([v.co.copy() for v in res.data.vertices], [list(p.vertices) for p in res.data.polygons],
               [p.material_index for p in res.data.polygons])
        for o in new:
            d = o.data
            bpy.data.objects.remove(o)
            if isinstance(d, bpy.types.Mesh) and d.users == 0:
                bpy.data.meshes.remove(d)
    finally:
        bpy.data.objects.remove(ob)
        bpy.data.meshes.remove(me)
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
    a loop edge and no edge may have more than two faces. Repeated border points, zero-area slivers and hairpin faces
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


def remesh_patch(pts, tris, loop, target, mats=None, tweaks=(1.0, 0.96, 1.04, 0.92, 1.08, 0.88, 1.12), **opts):
    """quad_remesh + weld_layout, retrying other target counts until the layout is clean. Returns (faces, new_points,
    raw output) or raises. Retry with another input fill spacing yourself if every target fails."""
    log = []
    for t in tweaks:
        out = quad_remesh(pts, tris, mats, TargetQuadCount=max(25, round(t * target)), FreezeBorders=1, **opts)
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
