"""Bring a generated GLB (TRELLIS.2, Pixal3D or any image-to-3D model) into Blender as a
high poly: report what arrived, size it to the real object, stand it on the ground.

Host: Blender 4.2+ (bpy, bmesh), run inside Blender or headless:

  blender -b --factory-startup --python-exit-code 1 --python glb_intake.py -- IN.glb --height 0.9 \
      [--longest 1.2] [--name BARREL_high] [--upright [X]] [--drop-floaters 0.001]       [--save OUT.blend] [--json REPORT.json]

Size: give exactly one of --height (Z extent, metres) or --longest (largest extent).
A generated model has no real scale: its numbers are the generator's normalised box.
--drop-floaters F deletes loose parts holding less than F of all triangles; without it
loose parts are only reported (a small loose part can be a real detail: a nail, a ring).

--upright stands a tilted model (Pixal3D's are tilted to the camera) on its largest flat
base; the report gives the angle and how much area that base has. It leaves a model with
no clear base alone: set its up axis with --rotate X,Y,Z (degrees) instead. Multi-view
Pixal3D models are posed to the level front view already: skip --upright for them.
From a Blender MCP: exec this file, then call intake(path, height=..., stand="X", ...) which
returns the report dict.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector


def _import(path: str) -> list[bpy.types.Object]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    return [o for o in bpy.data.objects if o not in before]


def _join_meshes(objs: list[bpy.types.Object], name: str) -> bpy.types.Object:
    meshes = [o for o in objs if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("the GLB holds no mesh")
    # bake parent transforms into the meshes, then drop empties
    for o in meshes:
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
    for o in objs:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    ob.name = ob.data.name = name
    return ob


def weld(ob, rel: float = 1e-6) -> int:
    """Merge vertices that share a position. glTF stores one vertex per UV and normal, so a
    generated GLB arrives cut along every UV seam: hundreds of 'loose parts' and tens of
    thousands of open edges that are only UV islands. UVs live on face corners in Blender,
    so welding keeps them; custom split normals are dropped (the high is shaded smooth)."""
    lo, hi = _bounds(ob)
    dist = max((hi - lo).length * rel, 1e-9)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    n0 = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=dist)
    n1 = len(bm.verts)
    bm.to_mesh(ob.data)
    bm.free()
    if ob.data.has_custom_normals:
        bpy.context.view_layer.objects.active = ob
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    ob.data.update()
    return n0 - n1


def _bounds(ob) -> tuple[Vector, Vector]:
    vs = [ob.matrix_world @ v.co for v in ob.data.vertices]
    lo = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
    hi = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
    return lo, hi


def _loose_parts(bm) -> list[list]:
    """Faces grouped by connectivity through shared vertices."""
    bm.faces.ensure_lookup_table()
    seen, parts = set(), []
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, part = [f], []
        seen.add(f.index)
        while stack:
            g = stack.pop()
            part.append(g)
            for v in g.verts:
                for h in v.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stack.append(h)
        parts.append(part)
    parts.sort(key=len, reverse=True)
    return parts


def hidden_fraction(ob, points: int = 1500, dirs: int = 256, seed: int = 0) -> float:
    """The share of the surface (area-weighted seeded samples) that no ray reaches from outside: from each sample,
    `dirs` rays spread evenly over the whole sphere, and it counts as seen when any of them leaves the model. The
    inner sheet of a double skin and a wall buried inside the model are never seen; the inside of an open pot is,
    through its mouth. Orientation-free (both sides tried), so flipped normals do not matter."""
    import numpy as np
    from mathutils.bvhtree import BVHTree
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        tri = np.empty(len(me.loop_triangles) * 3, np.int64)
        me.loop_triangles.foreach_get("vertices", tri)
        tri = tri.reshape(-1, 3)
    finally:
        ev.to_mesh_clear()
    if not len(tri):
        return 0.0
    bvh = BVHTree.FromPolygons([tuple(c) for c in co], [tuple(int(i) for i in t) for t in tri])
    a, b, c = co[tri[:, 0]], co[tri[:, 1]], co[tri[:, 2]]
    cr = np.cross(b - a, c - a)
    area = np.linalg.norm(cr, axis=1)
    if area.sum() <= 0:
        return 0.0
    n = cr / np.maximum(area, 1e-30)[:, None]
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(tri), size=points, p=area / area.sum())
    u, v = rng.random(points), rng.random(points)
    f = u + v > 1
    u[f], v[f] = 1 - u[f], 1 - v[f]
    pts = a[pick] + u[:, None] * (b[pick] - a[pick]) + v[:, None] * (c[pick] - a[pick])
    eps = 2e-5 * float(np.linalg.norm(co.max(0) - co.min(0)))
    k = np.arange(dirs) + 0.5                                  # a Fibonacci sphere: even, no clumps
    z = 1 - 2 * k / dirs
    ph = np.pi * (1 + 5 ** 0.5) * k
    rays = np.stack([np.sqrt(1 - z * z) * np.cos(ph), np.sqrt(1 - z * z) * np.sin(ph), z], 1)
    hidden = 0
    for i in range(points):
        nn = n[pick[i]]
        seen = False
        for d in rays:
            o = pts[i] + nn * (eps if d @ nn >= 0 else -eps)
            if bvh.ray_cast(Vector(o), Vector(d))[0] is None:
                seen = True
                break
        hidden += not seen
    return round(hidden / points, 3)


SHEETS_HIDDEN = 0.2       # hidden_fraction from here up: double sheets or buried walls (measured: 0.52 and 0.78 on
                          # udf barrels, 0.0 on the solid one, 0.09 on an open cast-iron cauldron with thin walls)
SHEETS_THIN = 0.1         # thin_gap_fraction above this with little hidden: real thin walls (an open vessel)


def sheet_check(ob, lines: int = 300, gap: float = 0.005, seed: int = 0, hidden: bool = True) -> dict:
    """Cast seeded random lines through the bounds and list every surface each crosses, then (hidden=True) measure
    how much of the surface no ray from outside can reach.

    A clean closed skin is crossed an even number of times with wide gaps between. A generator's remesh can instead
    leave double sheets (two parallel surfaces a few mm apart) and hidden inner walls: then many gaps are under `gap`
    of the model's size. But a real thin wall (an open pot or cauldron) gives the same thin gaps; what tells them
    apart is that a double sheet's inner skin is never seen from outside, while a vessel's inside is seen through its
    mouth. verdict: "double sheets or hidden walls" (hidden_fraction >= SHEETS_HIDDEN), "thin walls" (thin gaps,
    little hidden), or "clean"."""
    import random
    from mathutils.bvhtree import BVHTree
    rng = random.Random(seed)
    bvh = BVHTree.FromObject(ob, bpy.context.evaluated_depsgraph_get())
    lo, hi = _bounds(ob)
    centre, radius = (lo + hi) / 2, (hi - lo).length / 2
    size = (hi - lo).length
    crossings, gaps = [], []
    for _ in range(lines):
        d = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))).normalized()
        p = centre + Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))) * radius * 0.5
        o = p - d * radius * 2
        hits, t, far = [], 0.0, radius * 4
        while len(hits) < 64:
            r = bvh.ray_cast(o + d * (t + size * 1e-6), d, far - t)
            if r[0] is None:
                break
            t = (r[0] - o).length
            hits.append(t)
        if hits:
            crossings.append(len(hits))
            gaps += [b - a for a, b in zip(hits, hits[1:])]
    thin = sum(1 for g in gaps if g < gap * size)
    out = {"lines_hit": len(crossings),
           "mean_crossings": round(sum(crossings) / len(crossings), 2) if crossings else 0,
           "thin_gap_fraction": round(thin / len(gaps), 3) if gaps else 0.0}
    if hidden:
        out["hidden_fraction"] = hidden_fraction(ob, seed=seed)
        out["verdict"] = ("double sheets or hidden walls" if out["hidden_fraction"] >= SHEETS_HIDDEN else
                          "thin walls" if out["thin_gap_fraction"] > SHEETS_THIN else "clean")
    return out


def report(ob) -> dict:
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    tris = sum(len(f.verts) - 2 for f in bm.faces)
    parts = _loose_parts(bm)
    boundary = sum(1 for e in bm.edges if e.is_boundary)
    nonmanifold = sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary)
    part_tris = [sum(len(f.verts) - 2 for f in p) for p in parts]
    bm.free()
    lo, hi = _bounds(ob)
    size = hi - lo
    images = {}
    for slot in ob.material_slots:
        if not slot.material or not slot.material.use_nodes:
            continue
        for n in slot.material.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image:
                used = sorted({f"{l.to_node.type}.{l.to_socket.name}" for o in n.outputs
                               for l in o.links})
                e = images.setdefault(n.image.name, {"image": n.image.name,
                                                     "size": list(n.image.size), "feeds": []})
                e["feeds"] = sorted(set(e["feeds"]) | set(used))
    images = list(images.values())
    return {
        "object": ob.name,
        "triangles": tris,
        "vertices": len(me.vertices),
        "size_m": [round(size.x, 4), round(size.y, 4), round(size.z, 4)],
        "loose_parts": len(parts),
        "largest_parts_tris": part_tris[:8],
        "small_parts": sum(1 for t in part_tris if t < 0.001 * tris),
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "uv_layers": [uv.name for uv in me.uv_layers],
        "materials": [s.material.name for s in ob.material_slots if s.material],
        "images": images,
        "sheets": sheet_check(ob),
    }


def drop_floaters(ob, fraction: float) -> int:
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    tris = sum(len(f.verts) - 2 for f in bm.faces)
    kill = []
    for p in _loose_parts(bm)[1:]:
        if sum(len(f.verts) - 2 for f in p) < fraction * tris:
            kill += p
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    bm.to_mesh(ob.data)
    bm.free()
    return len(kill)


def upright(ob, axis: str = "X", limit_deg: float = 45.0, cone_deg: float = 12.0,
            band: float = 0.05, min_base: float = 0.02, min_gain: float = 2.0) -> dict:
    """Rotate about one axis so the object stands on its largest flat base.

    A pixel-aligned generator (Pixal3D) returns the model in the camera's frame, tilted
    about the camera's horizontal axis (Blender X after import) by the view's elevation.
    Each candidate angle is scored by the area of downward faces (within cone_deg of -Z)
    lying within `band` of the height above the lowest point (5%: a barrel's base sits about
    4% up inside its bottom hoop), weighted by flatness. When no angle gives a base of at
    least `min_base` of all area, or the best is under `min_gain` times the base it already
    has, the mesh is left alone and "rotated" is false: a model with no flat base needs its
    up axis set by eye (`rotate`). *Measured* 2026-11-02: bases scored 0.025-0.064 (barrels,
    a stump); a cushion standing on its rounded edge at most 0.013 at any angle, and with
    the old 0.01 floor an already upright multi-view cushion was turned 46 degrees. limit_deg bounds the search to camera
    elevations; *measured* 2026-11-02: an unbounded search turned an upright TRELLIS.2
    barrel 76 degrees onto its side.
    """
    import numpy as np
    me = ob.data
    me.calc_loop_triangles()
    n = len(me.polygons)
    normals = np.empty(n * 3, np.float32); me.polygons.foreach_get("normal", normals)
    centres = np.empty(n * 3, np.float32); me.polygons.foreach_get("center", centres)
    areas = np.empty(n, np.float32); me.polygons.foreach_get("area", areas)
    normals, centres = normals.reshape(-1, 3), centres.reshape(-1, 3)
    i = "XYZ".index(axis.upper())
    total = float(areas.sum()) or 1.0
    cos_cone = np.cos(np.radians(cone_deg))

    def score(deg):
        t = np.radians(deg)
        c, s = np.cos(t), np.sin(t)
        # z after Matrix.Rotation(t, 4, axis): about X z' = s*y + c*z; about Y z' = -s*x + c*z
        def rot_z(v):
            if i == 0:
                return s * v[:, 1] + c * v[:, 2]
            if i == 1:
                return -s * v[:, 0] + c * v[:, 2]
            return v[:, 2]
        nz, cz = rot_z(normals), rot_z(centres)
        zmin, zmax = cz.min(), cz.max()
        mask = (nz < -cos_cone) & (cz < zmin + band * (zmax - zmin))
        # weight by flatness so the score peaks at exactly level, not anywhere on the plateau
        flat = (-nz[mask] - cos_cone) / (1.0 - cos_cone)
        return float((areas[mask] * flat).sum())

    coarse = np.arange(-limit_deg, limit_deg + 0.01, 1.0)
    best = max(coarse, key=score)
    fine = np.arange(max(best - 1.0, -limit_deg), min(best + 1.0, limit_deg) + 0.01, 0.1)
    best = float(max(fine, key=score))
    base = score(best) / total      # flatness-weighted, so slightly under the plain area
    here = score(0.0) / total
    if base < min_base or base < min_gain * here:
        return {"axis": axis.upper(), "degrees": 0.0, "base_fraction": round(base, 4),
                "rotated": False}
    R = Matrix.Rotation(np.radians(best), 4, axis.upper())
    me.transform(R)
    me.update()
    return {"axis": axis.upper(), "degrees": round(best, 1), "base_fraction": round(base, 4),
            "rotated": True}


def rotate(ob, degrees_xyz) -> None:
    """Rotate the mesh data by Euler XYZ degrees (an up axis set by eye)."""
    import math
    from mathutils import Euler
    ob.data.transform(Euler([math.radians(d) for d in degrees_xyz], "XYZ").to_matrix().to_4x4())
    ob.data.update()


def size_and_ground(ob, height: float | None = None, longest: float | None = None) -> float:
    """Scale uniformly to the real size, origin at the bottom centre, standing on Z=0."""
    if (height is None) == (longest is None):
        raise ValueError("give exactly one of height or longest")
    lo, hi = _bounds(ob)
    size = hi - lo
    current = size.z if height is not None else max(size)
    if current <= 0:
        raise ValueError("the mesh has no extent on that axis")
    k = (height if height is not None else longest) / current
    pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    ob.data.transform(Matrix.Translation(-pivot))
    ob.data.transform(Matrix.Scale(k, 4))
    ob.location = (0, 0, 0)
    ob.data.update()
    return k


def intake(path: str, height: float | None = None, longest: float | None = None,
           name: str = "GEN_high", drop: float | None = None,
           stand: str | None = None, turn=None) -> dict:
    ob = _join_meshes(_import(path), name)
    raw_vertices = len(ob.data.vertices)
    welded = weld(ob)
    arrived = report(ob)
    dropped = drop_floaters(ob, drop) if drop else 0
    if turn:
        rotate(ob, turn)
    stood = upright(ob, stand) if stand else None
    k = size_and_ground(ob, height, longest)
    final = report(ob)
    return {"source": str(path), "raw_vertices": raw_vertices, "welded_vertices": welded,
            "arrived": arrived, "dropped_faces": dropped, "rotated_by": list(turn) if turn else None,
            "upright": stood,
            "scale_applied": round(k, 6), "final": final}


def _main():
    import argparse
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--height", type=float)
    g.add_argument("--longest", type=float)
    ap.add_argument("--name", default="GEN_high")
    ap.add_argument("--drop-floaters", type=float, default=None)
    ap.add_argument("--upright", nargs="?", const="X", default=None, metavar="AXIS",
                    help="stand it on its largest flat base by rotating about AXIS (default X): "
                         "needed for Pixal3D, which returns the model tilted to the camera")
    ap.add_argument("--rotate", type=lambda v: [float(x) for x in v.split(",")], metavar="X,Y,Z",
                    help="rotate by Euler XYZ degrees first (an up axis set by eye), e.g. --rotate -25,0,0")
    ap.add_argument("--save")
    ap.add_argument("--json")
    ap.add_argument("--keep-scene", action="store_true",
                    help="import into the open scene (default: start empty, so a --save holds only the model)")
    a = ap.parse_args(argv)
    if not a.keep_scene:
        bpy.ops.wm.read_factory_settings(use_empty=True)
    res = intake(a.glb, a.height, a.longest, a.name, a.drop_floaters, a.upright, a.rotate)
    text = json.dumps(res, indent=1)
    print(text)
    if a.json:
        Path(a.json).write_text(text, encoding="utf-8")
    if a.save:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(a.save).resolve()))


if __name__ == "__main__" and "--" in sys.argv:
    _main()
