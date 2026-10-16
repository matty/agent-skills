"""Audit a UV layout in Blender, set texel density, and pack with padding given in pixels.

Host: Blender with its bundled numpy; tested on 5.2.2, needs 4.1+ (Mesh.corner_normals). No add-ons, no RizomUV.

    import sys; sys.path.insert(0, r"<skill>/scripts")
    import uv_audit as ua
    ua.audit_selected(map_px=1024, pad_px=8)                         # UV0 of each selected mesh
    ua.audit_selected(layer=1, map_px=128, pad_px=4, lightmap=True)  # the lightmap UV (second layer)
    ua.audit_selected(map_px=2048, pad_px=16, baking=True)           # a layer that takes a baked normal map
    ua.seams_from_hard_edges(objs)                                   # a seam on every hard edge (after shading)
    ua.set_texel_density(objs, px_per_m=512, map_px=2048)            # scale to 512 px/m, then pack without rescaling
    ua.pack(objs, map_px=1024, pad_px=8)                             # fill the tile, 8 px between islands

From the command line (prints one line per object; --json writes the full reports):
    blender -b --factory-startup scene.blend --python uv_audit.py -- --objects "KIT_*" --map 1024 --pad 8 [--layer 1 --lightmap]
                                                  [--td 512] [--baking] [--json report.json]

What audit() measures, on the evaluated mesh (modifiers applied, as it exports) in world space:
  - islands, coverage, distortion (angular p95: 1.0 = shape kept; area p95: log2 of the density change inside
    an island);
  - folded faces (flipped inside an otherwise unflipped island: always a fault), mirrored islands (the whole
    island flipped: a normal fact of mirrored geometry, not a fault), faces with zero UV area;
  - UVs outside 0-1, overlap between different islands (stacked copies counted apart from partial overlaps),
    padding between islands (rasterised, within about a pixel) and margin to the tile edge, in pixels;
  - texel density in px/m (mean, spread between islands, against a target);
  - hard edges (split normals) that are not UV seams: on a layer that takes a baked normal map they bake a line.
audit() changes nothing. set_texel_density() and pack() change only the UV layer they work on, and make it the
active one; seams_from_hard_edges() changes only edge seams.
"""

import fnmatch
import json
import math
import sys

import bpy
import numpy as np

# Thresholds an audit line is checked against. Distortion matches the RizomUV pipeline's gate.
LIMITS = {"angular_p95": 1.15, "area_p95": 0.20, "texel_cv": 0.15, "texel_off_target": 0.20}
UV_EPS = 1e-6          # UVs closer than this count as the same UV vertex
RASTER_MAX = 2048      # coverage, overlap and padding are rasterised at min(map_px, RASTER_MAX)
MAX_UV_MAPS = 8        # Unity meshes carry UV0-UV7; most engines keep no more than 8


# ----------------------------------------------------------------------------------------------- mesh data
def _layer(me, layer):
    if not me.uv_layers:
        return None
    if layer is None:
        return me.uv_layers.active or me.uv_layers[0]
    if isinstance(layer, int):
        return me.uv_layers[layer] if layer < len(me.uv_layers) else None
    return me.uv_layers.get(layer)


def _arrays(ob, layer, evaluated=True, need_uv=True):
    """Flat numpy arrays of ob's mesh: world-space positions, corners, polygons, UVs, corner normals, triangles.
    None when the UV layer is missing, unless need_uv is False (the UVs are then all zero)."""
    if evaluated:
        dg = bpy.context.evaluated_depsgraph_get()
        src = ob.evaluated_get(dg)
        me = src.to_mesh()
        mw = np.array(src.matrix_world)
    else:
        src, me, mw = ob, ob.data, np.array(ob.matrix_world)
    try:
        lay = _layer(me, layer)
        if lay is None and need_uv:
            return None
        nv, nl, npoly = len(me.vertices), len(me.loops), len(me.polygons)
        co = np.empty(nv * 3)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
        lv = np.empty(nl, np.int64)
        me.loops.foreach_get("vertex_index", lv)
        ls = np.empty(npoly, np.int64)
        lt = np.empty(npoly, np.int64)
        me.polygons.foreach_get("loop_start", ls)
        me.polygons.foreach_get("loop_total", lt)
        uv = np.zeros(nl * 2)
        if lay is not None:
            lay.uv.foreach_get("vector", uv)
        cn = np.empty(nl * 3)
        me.corner_normals.foreach_get("vector", cn)
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        tri = np.empty(nt * 3, np.int64)
        me.loop_triangles.foreach_get("loops", tri)
        tpoly = np.empty(nt, np.int64)
        me.loop_triangles.foreach_get("polygon_index", tpoly)
        return {"co": co, "lv": lv, "ls": ls, "lt": lt, "uv": uv.reshape(-1, 2), "cn": cn.reshape(-1, 3),
                "tri": tri.reshape(-1, 3), "tpoly": tpoly, "layer": lay.name if lay else None,
                "layers": [l.name for l in me.uv_layers]}
    finally:
        if evaluated:
            src.to_mesh_clear()


def _edges(d):
    """Pairs of face corners across each manifold edge, and whether the UVs and the normals are split there."""
    ls, lt, lv = d["ls"], d["lt"], d["lv"]
    loop = np.arange(len(lv))
    poly = np.repeat(np.arange(len(ls)), lt)
    nxt = loop + 1
    last = ls + lt - 1
    nxt[last] = ls
    va, vb = lv[loop], lv[nxt]
    key = np.minimum(va, vb) * (len(d["co"]) + 1) + np.maximum(va, vb)
    order = np.argsort(key, kind="stable")
    k = key[order]
    _, first, count = np.unique(k, return_index=True, return_counts=True)
    two = first[count == 2]
    i, j = order[two], order[two + 1]
    lo = np.minimum(va, vb)
    # the corner of each side that sits on the edge's lower vertex, and the one on its higher vertex
    i_lo = np.where(va[i] == lo[i], loop[i], nxt[i])
    i_hi = np.where(va[i] == lo[i], nxt[i], loop[i])
    j_lo = np.where(va[j] == lo[j], loop[j], nxt[j])
    j_hi = np.where(va[j] == lo[j], nxt[j], loop[j])
    uv, cn = d["uv"], d["cn"]
    uv_split = (np.abs(uv[i_lo] - uv[j_lo]).max(1) > UV_EPS) | (np.abs(uv[i_hi] - uv[j_hi]).max(1) > UV_EPS)
    hard = (np.abs(cn[i_lo] - cn[j_lo]).max(1) > 1e-4) | (np.abs(cn[i_hi] - cn[j_hi]).max(1) > 1e-4)
    return poly[i], poly[j], uv_split, hard, key[i]


def _islands(npoly, pa, pb, joined):
    parent = np.arange(npoly)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, b in zip(pa[joined].tolist(), pb[joined].tolist()):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    roots = np.array([find(a) for a in range(npoly)])
    _, ids = np.unique(roots, return_inverse=True)
    return ids


def _triangles(d):
    """Per triangle: 3D area, UV area (signed), and the singular values of the 3D-to-UV map."""
    t = d["tri"]
    P = d["co"][d["lv"][t]]
    U = d["uv"][t]
    e1, e2 = P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]
    n = np.cross(e1, e2)
    a3 = 0.5 * np.linalg.norm(n, axis=1)
    l1 = np.linalg.norm(e1, axis=1)
    ok = (a3 > 1e-12) & (l1 > 1e-12)
    x = e1 / np.where(l1 > 0, l1, 1)[:, None]
    y = np.cross(n, x)
    y /= np.where(np.linalg.norm(y, axis=1) > 0, np.linalg.norm(y, axis=1), 1)[:, None]
    p1 = np.stack([l1, np.zeros_like(l1)], 1)
    p2 = np.stack([(e2 * x).sum(1), (e2 * y).sum(1)], 1)
    u1, u2 = U[:, 1] - U[:, 0], U[:, 2] - U[:, 0]
    au = 0.5 * (u1[:, 0] * u2[:, 1] - u1[:, 1] * u2[:, 0])
    det_p = p1[:, 0] * p2[:, 1] - p1[:, 1] * p2[:, 0]
    det_p = np.where(np.abs(det_p) > 1e-18, det_p, 1)
    # J = [u1 u2] @ inverse([p1 p2]) (columns), as a 2x2 per triangle
    inv = np.stack([np.stack([p2[:, 1], -p2[:, 0]], 1), np.stack([-p1[:, 1], p1[:, 0]], 1)], 1) / det_p[:, None, None]
    M = np.stack([u1, u2], 2)                      # columns u1, u2
    J = M @ inv                                    # rows of inv are the inverse's rows
    a, b, c, e = J[:, 0, 0], J[:, 0, 1], J[:, 1, 0], J[:, 1, 1]
    s = 0.5 * (a * a + b * b + c * c + e * e)
    det = a * e - b * c
    root = np.sqrt(np.maximum(s * s - det * det, 0))
    s1 = np.sqrt(np.maximum(s + root, 0))
    s2 = np.sqrt(np.maximum(s - root, 0))
    return {"a3": np.where(ok, a3, 0), "au": au, "s1": s1, "s2": s2, "ok": ok}


def _wpct(v, w, q):
    if not len(v) or w.sum() <= 0:
        return float("nan")
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return float(v[o][min(np.searchsorted(c, q * c[-1]), len(v) - 1)])


def _raster(d, island_of_tri, res, tris):
    """Island id per pixel (-1 empty, the last island drawn wins), pixels claimed by two different islands per
    island pair, and the pixels each island covers on its own."""
    grid = np.full((res, res), -1, np.int64)
    clash = {}
    cover = np.zeros(int(island_of_tri.max()) + 1 if len(island_of_tri) else 0, np.int64)
    U = d["uv"][d["tri"]] * res - 0.5          # pixel centres at integer coordinates
    for t in tris:
        p = U[t]
        x0, y0 = np.floor(p.min(0)).astype(int) + 1
        x1, y1 = np.floor(p.max(0)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, res - 1), min(y1, res - 1)
        if x1 < x0 or y1 < y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        (ax, ay), (bx, by), (cx, cy) = p
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12:
            continue
        w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
        w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w0 + w1 <= 1 + 1e-9)
        ys, xs = gy[inside], gx[inside]
        isl = island_of_tri[t]
        cover[isl] += len(ys)
        prev = grid[ys, xs]
        other = (prev >= 0) & (prev != isl)
        for o in np.unique(prev[other]).tolist():
            key = (min(o, isl), max(o, isl))
            clash[key] = clash.get(key, 0) + int(np.count_nonzero(prev[other] == o))
        grid[ys, xs] = isl
    return grid, clash, cover


def _min_gap(grid, limit_px):
    """Smallest centre-to-centre distance (raster pixels) between pixels of two different islands, if it is
    below limit_px; else None. Pixel centres sit up to a pixel inside an island, so this reads high by 0-2 px:
    a gap it reports is real, and a layout it passes is at most about a pixel short."""
    res = grid.shape[0]
    pad = np.pad(grid, 1, constant_values=-1)
    c = pad[1:-1, 1:-1]
    edge = (c >= 0) & ((pad[:-2, 1:-1] != c) | (pad[2:, 1:-1] != c) | (pad[1:-1, :-2] != c) | (pad[1:-1, 2:] != c))
    ys, xs = np.nonzero(edge)        # the pixel of an island nearest another island is always on its border
    ids = grid[ys, xs]
    r = int(math.ceil(limit_px))
    offs = sorted((math.hypot(dx, dy), dx, dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)
                  if 0 < math.hypot(dx, dy) < limit_px)
    for dist, dx, dy in offs:
        y, x = ys + dy, xs + dx
        ok = (y >= 0) & (y < res) & (x >= 0) & (x < res)
        other = grid[y[ok], x[ok]]
        if np.any((other >= 0) & (other != ids[ok])):
            return dist
    return None


# ----------------------------------------------------------------------------------------------- audit
def audit(ob, layer=None, map_px=1024, pad_px=None, px_per_m=None, lightmap=False, baking=False, evaluated=True,
          raster=True):
    """Measure one object's UV layer. layer: index, name or None (the active one). lightmap: inside 0-1, nothing
    stacked. baking: the layer will take a baked normal map, so hard edges must sit on UV seams. Returns a report
    dict whose "issues" list is empty when nothing needs a look."""
    if ob.mode == "EDIT":
        ob.update_from_editmode()
    d = _arrays(ob, layer, evaluated)
    if d is None:
        return {"object": ob.name, "layer": layer, "issues": ["no such UV layer"],
                "layers": [l.name for l in ob.data.uv_layers]}
    npoly = len(d["ls"])
    pa, pb, uv_split, hard, _key = _edges(d)
    isl_poly = _islands(npoly, pa, pb, ~uv_split)
    n_isl = int(isl_poly.max()) + 1 if npoly else 0
    tr = _triangles(d)
    isl_tri = isl_poly[d["tpoly"]]
    ok = tr["ok"]
    w = tr["a3"]
    ang = np.where(tr["s2"] > 1e-12, tr["s1"] / np.maximum(tr["s2"], 1e-30), np.inf)
    ratio = tr["s1"] * tr["s2"]                                  # UV area / 3D area per triangle
    # orientation per island: flipped triangles are a fold unless the whole island is mirrored
    neg = tr["au"] < 0
    neg_area = np.bincount(isl_tri, weights=w * neg, minlength=n_isl)
    tot_area = np.bincount(isl_tri, weights=w, minlength=n_isl)
    mirrored = neg_area > 0.5 * np.maximum(tot_area, 1e-30)
    fold = ok & (neg != mirrored[isl_tri])
    folded_faces = int(len(np.unique(d["tpoly"][fold])))
    zero_uv = ok & (np.abs(tr["au"]) < 1e-14)
    # distortion inside islands
    good = ok & ~zero_uv & np.isfinite(ang)
    isl_ratio = (np.bincount(isl_tri[good], weights=ratio[good] * w[good], minlength=n_isl)
                 / np.maximum(np.bincount(isl_tri[good], weights=w[good], minlength=n_isl), 1e-30))
    area_dev = np.abs(np.log2(np.maximum(ratio, 1e-30) / np.maximum(isl_ratio[isl_tri], 1e-30)))
    # texel density per island, px per metre (world units)
    td_isl = map_px * np.sqrt(np.maximum(isl_ratio, 0))
    td_mean = map_px * math.sqrt(max(float(np.abs(tr["au"][ok]).sum()) / max(float(w.sum()), 1e-30), 0))
    wi = np.bincount(isl_tri[good], weights=w[good], minlength=n_isl)
    td_cv = (float(np.sqrt(np.average((td_isl - td_mean) ** 2, weights=wi)) / td_mean)
             if td_mean > 0 and wi.sum() > 0 else float("nan"))
    uv = d["uv"]
    outside = float(np.mean((uv < -UV_EPS) | (uv > 1 + UV_EPS))) if len(uv) else 0.0
    rep = {"object": ob.name, "layer": d["layer"], "layers": d["layers"], "faces": npoly, "islands": n_isl,
           "angular_p95": round(_wpct(ang[good], w[good], 0.95), 3),
           "area_p95": round(_wpct(area_dev[good], w[good], 0.95), 3),
           "folded_faces": folded_faces, "mirrored_islands": int(mirrored.sum()),
           "zero_area_uv_faces": int(len(np.unique(d["tpoly"][zero_uv]))),
           "outside_0_1": round(outside, 4),
           "texel_px_per_m": round(td_mean, 1), "texel_cv": round(td_cv, 3),
           "texel_island_range": ([round(float(td_isl[wi > 0].min()), 1), round(float(td_isl[wi > 0].max()), 1)]
                                  if (wi > 0).any() else None),
           "hard_edges_not_seams": int(np.count_nonzero(hard & ~uv_split)),
           "margin_px": round(float(min(uv.min(), 1 - uv.max()) * map_px), 2) + 0.0 if len(uv) else None}
    if raster and len(d["tri"]):
        res = int(min(map_px, RASTER_MAX))
        grid, clash, px = _raster(d, isl_tri, res, np.nonzero(ok & ~zero_uv)[0])
        stacked = partial = 0
        overlap_px = 0
        for (a, b), n in clash.items():
            overlap_px += n
            small = max(min(px[a], px[b]), 1)
            if n / small > 0.9 and abs(int(px[a]) - int(px[b])) <= 0.1 * small:
                stacked += 1
            else:
                partial += 1
        rep.update({"coverage": round(float((grid >= 0).mean()), 4), "overlap_px": int(overlap_px),
                    "stacked_island_pairs": stacked, "overlapping_island_pairs": partial})
        if pad_px:
            scale = res / float(map_px)
            gap = _min_gap(grid, pad_px * scale)
            rep["padding_ok"] = gap is None
            rep["min_gap_px"] = None if gap is None else round(gap / scale, 1)
    rep["issues"] = _issues(rep, pad_px, px_per_m, lightmap, baking)
    return rep


def _issues(r, pad_px, px_per_m, lightmap, baking):
    out = []
    if len(r["layers"]) > MAX_UV_MAPS:
        out.append("%d UV layers: engines such as Unity keep only 8 (UV0-UV7)" % len(r["layers"]))
    if r["angular_p95"] > LIMITS["angular_p95"]:
        out.append("angular stretch p95 %.2f" % r["angular_p95"])
    if r["area_p95"] > LIMITS["area_p95"]:
        out.append("uneven density inside islands (area p95 %.2f)" % r["area_p95"])
    if r["folded_faces"]:
        out.append("%d folded faces" % r["folded_faces"])
    if r["zero_area_uv_faces"]:
        out.append("%d faces with zero UV area" % r["zero_area_uv_faces"])
    if lightmap and r["outside_0_1"] > 0:
        out.append("UVs outside 0-1")
    if r.get("overlapping_island_pairs"):
        out.append("%d island pairs partly overlap" % r["overlapping_island_pairs"])
    if lightmap and r.get("stacked_island_pairs"):
        out.append("%d stacked island pairs in a lightmap" % r["stacked_island_pairs"])
    if pad_px and r.get("padding_ok") is False:
        out.append("islands %.1f px apart (< %g)" % (r["min_gap_px"], pad_px))
    if pad_px and r["margin_px"] is not None and r["outside_0_1"] == 0 and r["margin_px"] < pad_px / 2.0 - 0.5:
        out.append("%.1f px from the tile edge (< %g)" % (r["margin_px"], pad_px / 2.0))
    if r["texel_cv"] == r["texel_cv"] and r["texel_cv"] > LIMITS["texel_cv"]:
        out.append("texel density varies between islands (cv %.2f)" % r["texel_cv"])
    if px_per_m and abs(r["texel_px_per_m"] / float(px_per_m) - 1) > LIMITS["texel_off_target"]:
        out.append("texel density %.0f px/m, target %g" % (r["texel_px_per_m"], px_per_m))
    if baking and r["hard_edges_not_seams"]:
        out.append("%d hard edges not on a UV seam" % r["hard_edges_not_seams"])
    return out


def line(r):
    if "angular_p95" not in r:
        return "  CHECK  %-28s %s" % (r["object"], "; ".join(r["issues"]))
    return ("  %s  %-28s %-16s %4d isl  cov %s  ang p95 %.3f  area p95 %.3f  %6.0f px/m  %s"
            % ("CHECK" if r["issues"] else "OK   ", r["object"], r["layer"][:16], r["islands"],
               r.get("coverage", "-"), r["angular_p95"], r["area_p95"], r["texel_px_per_m"],
               "; ".join(r["issues"]) or "no issues"))


def audit_objects(objects, report_path=None, **kw):
    reps = []
    for ob in objects:
        if ob.type != "MESH":
            continue
        r = audit(ob, **kw)
        reps.append(r)
        print(line(r))
    if report_path:
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(reps, fh, indent=1)
    return reps


def audit_selected(**kw):
    return audit_objects([o for o in bpy.context.selected_objects if o.type == "MESH"], **kw)


# ----------------------------------------------------------------------------------------------- changes
def seams_from_hard_edges(objects, clear=False):
    """Mark a seam on every hard edge (where the corner normals split) of each mesh: the rule for meshes that take
    a baked normal map. Hardness is read from the mesh's own normals, so shade it smooth by angle first
    (bpy.ops.object.shade_smooth_by_angle): on a flat-shaded mesh every edge is hard. Angle-based sharpness misses
    bevelled corners and closed tubes; those seams still need placing by hand. clear=True first removes all
    seams. Returns {object name: hard edges marked}."""
    out = {}
    was_edit = bpy.context.mode == "EDIT_MESH"
    if was_edit:
        bpy.ops.object.mode_set(mode="OBJECT")      # edge data written in Edit Mode is lost on the next toggle
    for ob in [o for o in objects if o.type == "MESH"]:
        me = ob.data
        d = _arrays(ob, None, evaluated=False, need_uv=False)
        _pa, _pb, _uv_split, hard, key = _edges(d)
        ev = np.empty(len(me.edges) * 2, np.int64)
        me.edges.foreach_get("vertices", ev)
        ev = ev.reshape(-1, 2)
        ekey = ev.min(1) * (len(d["co"]) + 1) + ev.max(1)
        order = np.argsort(ekey)
        idx = order[np.searchsorted(ekey[order], key[hard])]
        seam = np.zeros(len(me.edges), bool)
        if not clear:
            me.edges.foreach_get("use_seam", seam)
        seam[idx] = True
        me.edges.foreach_set("use_seam", seam)
        me.update()
        out[ob.name] = int(len(idx))
    if was_edit:
        bpy.ops.object.mode_set(mode="EDIT")
    return out


def _edit(objects):
    """Enter edit mode on exactly these mesh objects with every face selected; returns the previous state."""
    prev = (bpy.context.view_layer.objects.active, [o for o in bpy.context.selected_objects], bpy.context.mode)
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    return prev


def _restore(prev):
    bpy.ops.object.mode_set(mode="OBJECT")
    active, selected, mode = prev
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in selected:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active
    if mode == "EDIT_MESH" and active is not None and active.type == "MESH":
        bpy.ops.object.mode_set(mode="EDIT")


def _set_active_layer(ob, layer):
    lay = _layer(ob.data, layer)
    if lay is None:
        raise ValueError("%s has no UV layer %r" % (ob.name, layer))
    ob.data.uv_layers.active = lay
    return lay


def pack(objects, map_px=1024, pad_px=8, layer=None, scale=True, rotate=True, together=False, shape="CONCAVE"):
    """Pack each object's layer into the 0-1 tile with pad_px pixels between islands and pad_px / 2 to the edge.
    scale=False keeps the island sizes (after set_texel_density). together=True packs all objects into one tile
    (a shared atlas). Blender's FRACTION margin puts `margin` at the edge and twice it between islands (measured
    on 5.2.2), so margin = pad_px / (2 * map_px)."""
    objects = [o for o in objects if o.type == "MESH"]
    groups = [objects] if together else [[o] for o in objects]
    for group in groups:
        for o in group:
            _set_active_layer(o, layer)
        prev = _edit(group)
        try:
            bpy.ops.uv.select_all(action="SELECT")
            bpy.ops.uv.pack_islands(udim_source="CLOSEST_UDIM", rotate=rotate, rotate_method="CARDINAL",
                                    scale=scale, merge_overlap=False, margin_method="FRACTION",
                                    margin=pad_px / (2.0 * map_px), shape_method=shape)
        finally:
            _restore(prev)


def set_texel_density(objects, px_per_m, map_px, layer=None, per_island=True, pack_after=True, pad_px=8):
    """Scale UVs so the surface gets px_per_m texels per metre on a map_px texture, measured in world space on
    the evaluated mesh. per_island=True also evens out islands (like Average Islands Scale). Then packs without
    rescaling (pack_after); islands that no longer fit end up outside 0-1, which audit() reports. Returns the
    factor applied per object."""
    out = {}
    for ob in [o for o in objects if o.type == "MESH"]:
        lay = _set_active_layer(ob, layer)
        d = _arrays(ob, lay.name, evaluated=True)
        if len(d["uv"]) != len(ob.data.loops):
            raise ValueError("%s: modifiers change its corners; apply them before setting texel density" % ob.name)
        npoly = len(d["ls"])
        pa, pb, uv_split, _hard, _key = _edges(d)
        isl_poly = _islands(npoly, pa, pb, ~uv_split)
        tr = _triangles(d)
        isl_tri = isl_poly[d["tpoly"]]
        n = int(isl_poly.max()) + 1
        a3 = np.bincount(isl_tri, weights=tr["a3"], minlength=n)
        au = np.bincount(isl_tri, weights=np.abs(tr["au"]), minlength=n)
        target = px_per_m / float(map_px)                       # UV units per metre
        if per_island:
            f = np.where(au > 0, target / np.sqrt(np.maximum(au, 1e-30) / np.maximum(a3, 1e-30)), 1.0)
        else:
            f = np.full(n, target / math.sqrt(max(au.sum(), 1e-30) / max(a3.sum(), 1e-30)))
        isl_loop = np.repeat(isl_poly, d["lt"])
        uv = d["uv"].copy()
        centre = np.zeros((n, 2))
        corners = np.maximum(np.bincount(isl_loop, minlength=n), 1)
        for k in range(2):
            centre[:, k] = np.bincount(isl_loop, weights=uv[:, k], minlength=n) / corners
        uv = centre[isl_loop] + (uv - centre[isl_loop]) * f[isl_loop][:, None]
        lay.uv.foreach_set("vector", uv.ravel())
        ob.data.update()
        out[ob.name] = round(float(np.average(f, weights=np.maximum(a3, 1e-30))), 4)
    if pack_after:
        pack(objects, map_px=map_px, pad_px=pad_px, layer=layer, scale=False)
    return out


# ----------------------------------------------------------------------------------------------- command line
def _main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="uv_audit.py")
    ap.add_argument("--objects", default="*", help="name pattern (fnmatch), default every mesh")
    ap.add_argument("--layer", default=None, help="UV layer index or name, default the active one")
    ap.add_argument("--map", type=int, default=1024, help="texture size in pixels")
    ap.add_argument("--pad", type=float, default=None, help="padding between islands in pixels")
    ap.add_argument("--td", type=float, default=None, help="target texel density, px per metre")
    ap.add_argument("--lightmap", action="store_true", help="lightmap rules: inside 0-1, no stacked islands")
    ap.add_argument("--baking", action="store_true", help="normal-map bake: hard edges must be UV seams")
    ap.add_argument("--json", default=None, help="write the full reports here")
    a = ap.parse_args(argv)
    layer = int(a.layer) if a.layer is not None and a.layer.isdigit() else a.layer
    obs = [o for o in bpy.data.objects if o.type == "MESH" and fnmatch.fnmatch(o.name, a.objects)]
    reps = audit_objects(obs, report_path=a.json, layer=layer, map_px=a.map, pad_px=a.pad, px_per_m=a.td,
                         lightmap=a.lightmap, baking=a.baking)
    return 1 if any(r["issues"] for r in reps) else 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []))
