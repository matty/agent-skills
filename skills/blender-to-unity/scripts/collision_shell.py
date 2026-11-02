"""Build a <Piece>_COL convex collision shell from a piece's render mesh, keeping every extreme (leg tips, handles,
corners) and staying under Unity's 255-triangle limit for a convex MeshCollider.

Host: Blender 4.2+ (bpy, bmesh and the bundled numpy), headless or live:
    blender -b --factory-startup KIT_Market.blend --python-exit-code 1 --python collision_shell.py -- \
        --piece PROP_Cauldron_Free_A [--piece ...] [--points 64] [--save]
As a module (Blender MCP or another script):
    ns = {"COLLISION_SHELL_NO_MAIN": True}; exec(open(path, encoding="utf-8").read(), ns)
    col, report = ns["shell"](bpy.data.objects["PROP_Cauldron_Free_A_LOD0"], max_points=64)

How: half the points are the render mesh's (evaluated, modifiers applied) furthest out in directions spread evenly
over a sphere, straight down and the other five axes always among them; then the vertex furthest outside the hull so
far is added, one at a time, until the hull has max_points corners. That hull is the shell. Decimating the mesh first and hulling what is left loses exactly those
extremes: measured 2026-11-02 on a generated cauldron, a hull of a 64-vertex Decimate floated 44 mm above the floor
because the leg tips were gone. The shell lies inside the full hull by at most `inside_m` (reported), never outside
it, and its floor is the mesh's floor.

The shell replaces any <Piece>_COL in the piece's collections, with the render mesh's transform, no materials, no UVs,
drawn as wire and hidden from renders. Report: points, triangles, closed, floor_gap_m (shell bottom above the mesh
bottom), inside_m (furthest a mesh vertex lies outside the shell: what the shell cuts off), volume_share (shell /
full hull). Prefer a Unity primitive collider (box, capsule) when one fits the piece: it is cheaper still.
"""

import argparse
import sys

import bmesh
import bpy
import numpy as np

UNITY_CONVEX_TRIS = 255      # Unity's limit for a convex MeshCollider (PhysX cooking)


def _points(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        return co.reshape(-1, 3)
    finally:
        ev.to_mesh_clear()


def _directions(n):
    k = np.arange(n) + 0.5
    z = 1.0 - 2.0 * k / n
    ph = np.pi * (1.0 + 5.0 ** 0.5) * k
    r = np.sqrt(np.maximum(1.0 - z * z, 0.0))
    fib = np.stack([r * np.cos(ph), r * np.sin(ph), z], 1)
    axes = np.array([(0, 0, -1), (0, 0, 1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)], float)
    return np.vstack([axes, fib])


def support_points(pts, max_points=64):
    """Indices of the points furthest out along as many directions as keep them within max_points (at least the six
    axis directions)."""
    pts = np.asarray(pts, float)
    c = pts.mean(0)
    q = pts - c

    def pick(n):
        return np.unique(np.argmax(q @ _directions(n).T, axis=0))
    best = pick(0)
    lo, hi = 0, 8
    while len(pick(hi)) <= max_points and hi < 20000:
        best, lo, hi = pick(hi), hi, hi * 2
    while hi - lo > 1:
        mid = (lo + hi) // 2
        got = pick(mid)
        if len(got) <= max_points:
            best, lo = got, mid
        else:
            hi = mid
    return best


def _hull(points):
    bm = bmesh.new()
    vs = [bm.verts.new(p) for p in points]
    res = bmesh.ops.convex_hull(bm, input=vs)
    keep = set(res["geom"])
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v not in keep], context="VERTS")
    bmesh.ops.delete(bm, geom=[e for e in bm.edges if not e.link_faces], context="EDGES")
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def _planes(bm):
    bm.faces.ensure_lookup_table()
    n = np.array([tuple(f.normal) for f in bm.faces])
    d = np.array([f.normal.dot(f.verts[0].co) for f in bm.faces])
    return n, d


def shell(ob, max_points=64, name=None):
    """A convex shell of ob's evaluated mesh as a new object (name: <Piece>_COL from ob's <Piece>_LODn name), and its
    report. Raises if it would exceed Unity's 255 triangles (it cannot with max_points 64: a hull of n points has at
    most 2n - 4 triangles)."""
    pts = _points(ob)
    if len(pts) < 4:
        raise ValueError("%s has too few vertices for a shell" % ob.name)
    idx = list(support_points(pts, max(8, max_points // 2)))
    for _ in range(4 * max_points):                  # then the vertex furthest outside, one at a time
        bm = _hull([tuple(p) for p in pts[idx]])
        n, d = _planes(bm)
        out = (pts @ n.T - d).max(1)
        j = int(np.argmax(out))
        if out[j] <= 1e-5 or len(bm.verts) >= max_points:
            break
        bm.free()
        idx.append(j)
    tris = len(bm.faces)
    if tris > UNITY_CONVEX_TRIS:
        bm.free()
        raise ValueError("%s: a shell of %d triangles is over Unity's %d: lower max_points"
                         % (ob.name, tris, UNITY_CONVEX_TRIS))
    inside = float(max(0.0, out.max()))                        # how far a mesh vertex sticks out of the shell
    closed = all(e.is_manifold for e in bm.edges)
    vol = bm.calc_volume()
    full = _hull([tuple(p) for p in pts])
    vol_full = full.calc_volume()
    full.free()
    base = name or (ob.name.rsplit("_LOD", 1)[0] + "_COL")
    old = bpy.data.objects.get(base)
    if old is not None:
        me_old = old.data
        bpy.data.objects.remove(old)
        if me_old.users == 0:
            bpy.data.meshes.remove(me_old)
    me = bpy.data.meshes.new(base)
    bm.to_mesh(me)
    zmin = min(v.co.z for v in bm.verts)
    bm.free()
    col = bpy.data.objects.new(base, me)
    for c in ob.users_collection:
        c.objects.link(col)
    col.matrix_world = ob.matrix_world.copy()
    col.display_type = "WIRE"
    col.hide_render = True
    rep = {"object": base, "from": ob.name, "points": len(me.vertices), "triangles": tris, "closed": closed,
           "floor_gap_m": round(float(zmin - pts[:, 2].min()), 5), "inside_m": round(inside, 5),
           "volume_share": round(vol / vol_full, 4) if vol_full > 0 else None}
    return col, rep


def main(argv):
    ap = argparse.ArgumentParser(prog="collision_shell.py", description=__doc__.split("\n")[0])
    ap.add_argument("--piece", action="append", required=True, help="piece name (its <Piece>_LOD0 is used)")
    ap.add_argument("--points", type=int, default=64)
    ap.add_argument("--save", action="store_true", help="save the .blend (no .blend1)")
    a = ap.parse_args(argv)
    code = 0
    for piece in a.piece:
        lod0 = bpy.data.objects.get(piece + "_LOD0") or bpy.data.objects.get(piece)
        if lod0 is None:
            print("[shell] no %s_LOD0" % piece)
            code = 2
            continue
        _col, rep = shell(lod0, a.points)
        print("[shell] %s" % rep)
    if a.save and code == 0:
        bpy.context.preferences.filepaths.save_version = 0        # no .blend1 beside the kit
        bpy.ops.wm.save_mainfile(compress=True)
    return code


if __name__ == "__main__" and not globals().get("COLLISION_SHELL_NO_MAIN"):
    sys.exit(main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []))
