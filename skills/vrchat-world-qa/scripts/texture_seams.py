"""Measure visible texture seams: the colour or normal step across every UV seam of a textured mesh, and across the
joints where placed kit pieces meet, against the texture's own step between neighbouring texels inside an island.

A seam shows when the texture changes more across it than it does anywhere nearby: UV-space noise or a painted
pattern that ignores the seam, a normal map baked with another tangent basis or with an island moved after the bake,
a tiling pattern whose phase jumps at a kit joint. Each seam edge is sampled at a few points along it, half a texel
inside each of its two faces (the same point in 3D, two places in the texture); the step between the two sides is
compared with the texture's own step between texels one apart, from there to 3.5 texels inside each face. A ratio near 1 is a seam nobody can find;
measured on Blender 5.2.2 (2026-10-27): noise baked from Object coordinates onto a smart-projected sphere 0.99, the
same noise from UV coordinates 8.06.

Host: Blender 4.2+ (bpy and its bundled numpy), no add-ons; tested on Blender 5.2.2. Shipped identically in the
pbr-texturing and vrchat-world-qa skills (tools/check_conventions.py fails when the copies differ). The sampling
maths (sample, inward offsets, the per-edge verdict) runs in plain Python with numpy, which is how the repo's tests
check it.

    import sys; sys.path.insert(0, r"<skill>/scripts")
    import texture_seams as ts
    r = ts.seams(ob, "textures/T_PROP_Chest_BaseColor.png")                 # every UV seam of one mesh
    r = ts.seams(ob, "textures/T_PROP_Chest_Normal.png", kind="normal")     # in object space, through MikkTSpace
    r = ts.joints([wall_a, wall_b], "textures/T_EXT_Brick_BaseColor.png")   # where placed pieces meet

Command line (exit 0 when no seam shows, 1 when one does, 2 for a request it cannot measure):
    blender -b --factory-startup --python-exit-code 1 scene.blend --python texture_seams.py --
            --objects "PROP_Chest*" --image textures/T_PROP_Chest_BaseColor.png [--kind color|normal] [--uv UVMap]
            [--material "M_PROP_*"] [--joints] [--json seams.json]

A seam edge shows (`visible_m`, an issue) when its mean step is over LIMITS["ratio"] (3) x its mean inner step (never
less than the texture's median step between neighbouring texels) and over the floor (colour: mean absolute step over
the channels; normal: degrees between the two sides' shading normals); between note_ratio (2) and that it is worth a
close look (`look_m`, a note). Measured on Blender 5.2.2 at 512 px: smooth noise or a smooth image laid by UVs, every
seam at p50 9-14; the same from Object coordinates or a Box-projected image, p95 1.1-1.4; a clean cage bake's normal
map p95 0.8 and the same map with one island turned after the bake, 6.2 m of 18 m showing; a busy library texture
(forest ground) cut at random by UVs, p95 2.3-2.4 with some edges in the note band. Edges where
the mesh folds sharper than LIMITS["fold_deg"] are reported apart (`folds_m`), not judged: a texture may change at
a real corner. joints() matches edges of different pieces that coincide in world space (within tol) and
judges the pair of faces that continue each other across them (two walls' fronts, not their end caps) the same
way; collection instances (a kit layout) are expanded through the depsgraph. Textures wrap
(Repeat), so tiling UVs far outside 0-1 sample as the engine does. The image is read as stored codes from its own
copy, loaded Non-Color: the scene's images and their settings are left alone. Nothing in the scene is changed.
"""

import fnmatch
import json
import math
import os
import sys

import numpy as np

try:
    import bpy
except ImportError:          # plain Python: the sampling maths works, the Blender functions do not
    bpy = None

LIMITS = dict(
    ratio=3.0,               # a seam edge shows (an issue) when its step is over this many times the texture's own
    note_ratio=2.0,          # ... and is worth a close look (a note) over this; a busy texture cut at random reads 2-3
    colour_floor=0.01,       # ... and over this mean absolute step (0-1 codes; 8-bit noise is about 0.002)
    normal_floor_deg=2.0,    # ... or, for a normal map, over this many degrees between the two sides' normals
    fold_deg=89.0,           # edges whose faces meet sharper than this are reported apart, not judged
    samples=9,               # sample points along each seam edge (at 1/(n+1) ... n/(n+1) of its length)
    uv_eps=1e-6,             # UVs closer than this are the same UV vertex
)


# ----------------------------------------------------------------------------------------------- maths (no bpy)
def sample(img, uv):
    """Bilinear samples of img (height, width, channels) at uv (k, 2), rows bottom to top as Blender stores them,
    wrapping (Repeat) in both directions. Returns (k, channels)."""
    h, w = img.shape[:2]
    uv = np.asarray(uv, float).reshape(-1, 2)
    x = uv[:, 0] * w - 0.5
    y = uv[:, 1] * h - 0.5
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx = (x - x0)[:, None]
    fy = (y - y0)[:, None]
    xa, xb = x0 % w, (x0 + 1) % w
    ya, yb = y0 % h, (y0 + 1) % h
    return ((1 - fx) * (1 - fy) * img[ya, xa] + fx * (1 - fy) * img[ya, xb] + (1 - fx) * fy * img[yb, xa]
            + fx * fy * img[yb, xb])


def inward(uv0, uv1, centre, size):
    """Unit step into the face, in UV units per texel: perpendicular to the edge uv0-uv1 in pixel space, pointing to
    the face's UV centre. size: (width, height) in pixels."""
    size = np.asarray(size, float)
    e = (np.asarray(uv1, float) - np.asarray(uv0, float)) * size
    perp = np.array([-e[1], e[0]])
    n = np.linalg.norm(perp)
    if n < 1e-12:
        return None
    perp /= n
    mid = (np.asarray(uv0, float) + np.asarray(uv1, float)) * 0.5
    if np.dot(perp, (np.asarray(centre, float) - mid) * size) < 0:
        perp = -perp
    return perp / size


def colour_step(a, b):
    """Mean absolute difference over the channels, per sample row."""
    return np.abs(np.asarray(a, float) - np.asarray(b, float)).mean(axis=-1)


def angle_deg(a, b):
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    c = (a * b).sum(axis=-1) / np.maximum(np.linalg.norm(a, axis=-1) * np.linalg.norm(b, axis=-1), 1e-12)
    return np.degrees(np.arccos(np.clip(c, -1.0, 1.0)))


def shade(code, tangent, sign, normal):
    """Object-space shading normals from tangent-space normal-map codes (k, 3) in 0-1, OpenGL (Y+), through the
    MikkTSpace frame: bitangent = sign x (normal cross tangent), as Blender and Unity build it."""
    n = np.asarray(code, float)[:, :3] * 2.0 - 1.0
    t = np.asarray(tangent, float)
    nn = np.asarray(normal, float)
    b = np.asarray(sign, float)[:, None] * np.cross(nn, t)
    v = t * n[:, :1] + b * n[:, 1:2] + nn * n[:, 2:3]
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)


def baseline(img, kind):
    """The texture's own median step between neighbouring texels (colour: mean absolute over the channels; a normal
    map: 0, judged on the local step alone). A busy texture (gravel, leaf litter) cut at random shows no seam, and
    its local step along one edge can dip in a smooth patch: an edge is never judged against less than this."""
    if kind == "normal":
        return 0.0
    a = np.asarray(img, float)[:, :, :3]
    return float(np.median(np.concatenate([np.abs(np.diff(a, axis=0)).mean(axis=2).ravel(),
                                           np.abs(np.diff(a, axis=1)).mean(axis=2).ravel()])))


def verdict(step, inner, kind, limits=LIMITS, base=0.0):
    """(ratio, shows, look) for one edge from its per-sample steps across and inside, against the larger of its own
    inner step and the texture's baseline. The inner step is also floored at floor / note_ratio, so a flat texture
    (a brick's face) gives a finite ratio and both verdicts stay exactly "the step is over the floor and over that
    many times the inner step": shows over ratio, look over note_ratio."""
    floor = limits["normal_floor_deg"] if kind == "normal" else limits["colour_floor"]
    s, i = float(np.mean(step)), max(float(np.mean(inner)), base)
    ratio = s / max(i, floor / limits["note_ratio"])
    return ratio, bool(ratio > limits["ratio"]), bool(ratio > limits["note_ratio"])


def summarise(rows, kind, limits=LIMITS, base=0.0):
    """rows: per edge (length_m, midpoint xyz, step array, inner array, folded); base: the texture's baseline step.
    The report without issues."""
    seam_m = fold_m = vis_m = look_m = 0.0
    ratios, lengths, worst = [], [], []
    for length, mid, step, inner, folded in rows:
        if folded:
            fold_m += length
            continue
        ratio, shows, look = verdict(step, inner, kind, limits, base)
        seam_m += length
        ratios.append(ratio)
        lengths.append(length)
        vis_m += length if shows else 0.0
        look_m += length if look and not shows else 0.0
        if look:
            worst.append((round(ratio, 2), round(float(np.mean(step)), 4), [round(float(c), 3) for c in mid]))
    worst.sort(key=lambda r: -r[0])
    out = {"kind": kind, "edges": len(lengths), "seam_m": round(seam_m, 3), "visible_m": round(vis_m, 3),
           "look_m": round(look_m, 3), "folds_m": round(fold_m, 3), "worst": worst[:8]}
    if ratios:
        order = np.argsort(ratios)
        cum = np.cumsum(np.asarray(lengths)[order])
        out["ratio_p50"] = round(float(np.asarray(ratios)[order][np.searchsorted(cum, 0.5 * cum[-1])]), 2)
        out["ratio_p95"] = round(float(np.asarray(ratios)[order][min(len(order) - 1,
                                                                     np.searchsorted(cum, 0.95 * cum[-1]))]), 2)
    return out


# ----------------------------------------------------------------------------------------------- mesh data (bpy)
def load_image(image):
    """(pixels (h, w, 4) float, rows bottom to top, as stored codes; name). image: a path (loaded as its own copy,
    Non-Color, then removed) or a bpy image (read as it is)."""
    if isinstance(image, str):
        if not os.path.isfile(image):
            raise ValueError("no image at %s" % image)
        im = bpy.data.images.load(image, check_existing=False)
        try:
            im.colorspace_settings.name = "Non-Color"
            w, h = im.size
            px = np.empty(w * h * 4, np.float32)
            im.pixels.foreach_get(px)
            return px.reshape(h, w, 4), os.path.basename(image)
        finally:
            bpy.data.images.remove(im)
    w, h = image.size
    px = np.empty(w * h * 4, np.float32)
    image.pixels.foreach_get(px)
    return px.reshape(h, w, 4), image.name


def _placed(objects):
    """(name, evaluated object, world matrix) for every mesh among objects and every mesh instanced by them
    (collection instances, as a kit layout places pieces)."""
    dg = bpy.context.evaluated_depsgraph_get()
    names = {o.name for o in objects}
    out = []
    for o in objects:
        if o.type == "MESH":
            out.append((o.name, o.evaluated_get(dg), np.array(o.matrix_world)))
    for inst in dg.object_instances:
        if inst.is_instance and inst.parent is not None and inst.parent.original.name in names \
                and inst.object.type == "MESH":
            src = bpy.data.objects[inst.object.original.name]
            out.append(("%s/%s" % (inst.parent.original.name, src.name), src.evaluated_get(dg),
                        np.array(inst.matrix_world)))
    return out


def _mesh_arrays(ev, mw, uv_layer=None, normals=False, material=None):
    """Flat arrays of an evaluated object's mesh in world space: positions, corners, faces, UVs, corner normals and,
    with normals=True, MikkTSpace tangents and signs (world space). material: faces kept by material name."""
    me = ev.to_mesh()
    try:
        lay = me.uv_layers.get(uv_layer) if uv_layer else me.uv_layers.active
        if lay is None:
            raise ValueError("%s has no UV map %r" % (ev.name, uv_layer or "(active)"))
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
        uv = np.empty(nl * 2)
        lay.uv.foreach_get("vector", uv)
        cn = np.empty(nl * 3)
        me.corner_normals.foreach_get("vector", cn)
        nm = mw[:3, :3]
        inv_t = np.linalg.inv(nm).T
        cn = cn.reshape(-1, 3) @ inv_t.T
        cn /= np.maximum(np.linalg.norm(cn, axis=1, keepdims=True), 1e-12)
        d = {"co": co, "lv": lv, "ls": ls, "lt": lt, "uv": uv.reshape(-1, 2), "cn": cn}
        if normals:
            if max(lt) > 4:
                raise ValueError("%s has n-gons: MikkTSpace tangents need triangles or quads (triangulate it as it "
                                 "exports)" % ev.name)
            me.calc_tangents(uvmap=lay.name)
            tg = np.empty(nl * 3)
            me.loops.foreach_get("tangent", tg)
            sg = np.empty(nl)
            me.loops.foreach_get("bitangent_sign", sg)
            tg = tg.reshape(-1, 3) @ nm.T
            tg /= np.maximum(np.linalg.norm(tg, axis=1, keepdims=True), 1e-12)
            d["tg"], d["sg"] = tg, sg * (1.0 if np.linalg.det(nm) > 0 else -1.0)
        keep = np.ones(npoly, bool)
        if material:
            slots = [s.material.name if s.material else "" for s in ev.original.material_slots]
            mi = np.empty(npoly, np.int64)
            me.polygons.foreach_get("material_index", mi)
            ok = np.array([bool(n) and fnmatch.fnmatchcase(n, material) for n in slots] or [False], bool)
            keep = ok[np.clip(mi, 0, len(ok) - 1)]
        d["keep"] = keep
        return d
    finally:
        ev.to_mesh_clear()


def _edge_sides(d):
    """{(v0, v1) sorted: [(face, corner at v0, corner at v1), ...]} over the kept faces."""
    sides = {}
    for f in range(len(d["ls"])):
        if not d["keep"][f]:
            continue
        s, n = int(d["ls"][f]), int(d["lt"][f])
        for k in range(n):
            la, lb = s + k, s + (k + 1) % n
            va, vb = int(d["lv"][la]), int(d["lv"][lb])
            if va < vb:
                sides.setdefault((va, vb), []).append((f, la, lb))
            else:
                sides.setdefault((vb, va), []).append((f, lb, la))
    return sides


def _face_centre(d, f):
    s, n = int(d["ls"][f]), int(d["lt"][f])
    return d["uv"][s:s + n].mean(axis=0)


def _face_normal(d, f):
    s, n = int(d["ls"][f]), int(d["lt"][f])
    p = d["co"][d["lv"][s:s + n]]
    c = np.cross(p, np.roll(p, -1, axis=0)).sum(axis=0)
    return c / max(np.linalg.norm(c), 1e-12)


def _side_samples(d, img, f, la, lb, kind, ts):
    """Samples along the edge from corner la to corner lb of face f: at 0.5, 1.5, 2.5 and 3.5 texels inside it, and
    half a texel outside it on the face's own UVs continued (what the texture would show there if it went on):
    (inside list, outside), colours (k, ch) or object-space normals (k, 3)."""
    h, w = img.shape[:2]
    uv0, uv1 = d["uv"][la], d["uv"][lb]
    step = inward(uv0, uv1, _face_centre(d, f), (w, h))
    if step is None:
        return None
    base = uv0[None, :] + (uv1 - uv0)[None, :] * ts[:, None]
    inside = [sample(img, base + k * step) for k in (0.5, 1.5, 2.5, 3.5)]
    out = sample(img, base - 0.5 * step)
    if kind != "normal":
        return [x[:, :3] for x in inside], out[:, :3]
    lerp = lambda a: d[a][la][None, :] * (1 - ts[:, None]) + d[a][lb][None, :] * ts[:, None]
    sign = np.full(len(ts), d["sg"][la])
    frame = (lerp("tg"), sign, lerp("cn"))
    return [shade(x, *frame) for x in inside], shade(out, *frame)


def _pair_rows(da, img_a, side_a, db, img_b, side_b, kind, limits, length, mid, folded, continued=False):
    """One edge's row for summarise. continued=False (a UV seam inside a mesh, where the islands need not continue
    each other in the texture): the step from one side to the other. continued=True (a joint between pieces laying
    the same tiling texture): how far each side differs from the other side's texture continued across the edge,
    near 0 when the pattern carries on whatever it holds at the joint (a mortar line, a plank gap)."""
    ts = np.arange(1, limits["samples"] + 1) / float(limits["samples"] + 1)
    a = _side_samples(da, img_a, side_a[0], side_a[1], side_a[2], kind, ts)
    b = _side_samples(db, img_b, side_b[0], side_b[1], side_b[2], kind, ts)
    if a is None or b is None:
        return None
    diff = angle_deg if kind == "normal" else colour_step
    (ia, oa), (ib, ob) = a, b
    if continued:
        step = 0.5 * (diff(oa, ib[0]) + diff(ob, ia[0]))
    else:
        step = diff(ia[0], ib[0])
    # the texture's own step one texel apart, at three depths on each side: steadier than one pair on a busy texture
    inner = np.mean([diff(x[k], x[k + 1]) for x in (ia, ib) for k in range(3)], axis=0)
    return (length, mid, step, inner, folded)


def seams(ob, image, kind="color", uv_layer=None, material=None, limits=LIMITS):
    """Every UV seam of ob's evaluated mesh (an edge whose two faces' UVs differ at either end): the step across it
    against the texture's own inner step. kind "color" for colour, roughness or AO maps, "normal" for a tangent-space
    normal map (OpenGL). Returns the report with "issues"."""
    if kind not in ("color", "normal"):
        raise ValueError("kind is 'color' or 'normal'")
    img, name = load_image(image)
    dg = bpy.context.evaluated_depsgraph_get()
    d = _mesh_arrays(ob.evaluated_get(dg), np.array(ob.matrix_world), uv_layer, kind == "normal", material)
    rows = []
    for (va, vb), sides in _edge_sides(d).items():
        if len(sides) != 2:
            continue
        (fa, a0, a1), (fb, b0, b1) = sides
        if np.abs(d["uv"][a0] - d["uv"][b0]).max() < limits["uv_eps"] and \
                np.abs(d["uv"][a1] - d["uv"][b1]).max() < limits["uv_eps"]:
            continue                                                     # not a seam
        pa, pb = d["co"][va], d["co"][vb]
        fold = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(_face_normal(d, fa), _face_normal(d, fb)))))))
        r = _pair_rows(d, img, (fa, a0, a1), d, img, (fb, b0, b1), kind, limits, float(np.linalg.norm(pb - pa)),
                       (pa + pb) / 2, fold > limits["fold_deg"])
        if r:
            rows.append(r)
    rep = dict(summarise(rows, kind, limits, baseline(img, kind)), object=ob.name, image=name)
    _verdicts(rep, "UV seams", limits)
    return rep


def _face_centroid(d, f):
    s, n = int(d["ls"][f]), int(d["lt"][f])
    return d["co"][d["lv"][s:s + n]].mean(axis=0)


def joints(objects, image, kind="color", uv_layer=None, material=None, tol=1e-4, limits=LIMITS):
    """Where placed pieces meet: edges of different pieces that coincide in world space (within tol metres). Of the
    faces at such an edge, the pair from two pieces that continue each other is judged: facing within fold_deg of the
    same way and lying on opposite sides of the edge (two walls' fronts; their end caps pressed together face apart
    and are skipped). Each side is compared with the other side's texture continued half a texel across the joint,
    so a mortar line or plank gap that happens to fall on the joint is not mistaken for a jump. objects: mesh objects and/or
    collection-instance empties (a kit layout). Returns the report with "issues" and "pairs" (piece pairs that meet)."""
    if kind not in ("color", "normal"):
        raise ValueError("kind is 'color' or 'normal'")
    img, name = load_image(image)
    datas = []
    for nm, ev, mw in _placed(objects):
        d = _mesh_arrays(ev, mw, uv_layer, kind == "normal", material)
        d["name"] = nm
        datas.append(d)
    q = 1.0 / tol
    edges = {}
    for i, d in enumerate(datas):
        for (va, vb), sides in _edge_sides(d).items():
            ka = tuple(np.round(d["co"][va] * q).astype(np.int64))
            kb = tuple(np.round(d["co"][vb] * q).astype(np.int64))
            key = (ka, kb) if ka <= kb else (kb, ka)
            for side in sides:                                        # both sides run from the key's first point
                edges.setdefault(key, []).append((i, side if ka <= kb else (side[0], side[2], side[1])))
    cos_fold = math.cos(math.radians(limits["fold_deg"]))
    rows, pairs = [], set()
    for key, owners in edges.items():
        if len({o[0] for o in owners}) < 2:
            continue
        best = None
        for x in range(len(owners)):
            for y in range(x + 1, len(owners)):
                (i, sa), (j, sb) = owners[x], owners[y]
                if i == j:
                    continue
                da, db = datas[i], datas[j]
                dot = float(np.dot(_face_normal(da, sa[0]), _face_normal(db, sb[0])))
                pa, pb = da["co"][da["lv"][sa[1]]], da["co"][da["lv"][sa[2]]]
                mid = (pa + pb) / 2
                if dot < cos_fold or float(np.dot(_face_centroid(da, sa[0]) - mid,
                                                  _face_centroid(db, sb[0]) - mid)) >= 0:
                    continue
                if best is None or dot > best[0]:
                    best = (dot, i, sa, j, sb, pa, pb)
        if best is None:
            continue
        _dot, i, sa, j, sb, pa, pb = best
        da, db = datas[i], datas[j]
        r = _pair_rows(da, img, sa, db, img, sb, kind, limits, float(np.linalg.norm(pb - pa)), (pa + pb) / 2, False,
                       continued=True)
        if r:
            rows.append(r)
            pairs.add(tuple(sorted((da["name"], db["name"]))))
    rep = dict(summarise(rows, kind, limits, baseline(img, kind)), image=name, pieces=len(datas), pairs=sorted(pairs))
    _verdicts(rep, "joints between pieces", limits)
    return rep


def _verdicts(rep, what, limits):
    rep["issues"] = (["%.2f m of %.2f m of %s show (step over %.1f x the texture's own; worst ratio %.1f at %s)"
                      % (rep["visible_m"], rep["seam_m"], what, limits["ratio"], rep["worst"][0][0],
                         rep["worst"][0][2])] if rep["visible_m"] > 0 else [])
    rep["notes"] = (["%.2f m of %s step %.1f-%.1f x the texture's own: look at them in a close render (a busy texture "
                     "cut at random reads this high and hides it)" % (rep["look_m"], what, limits["note_ratio"],
                                                                      limits["ratio"])] if rep["look_m"] > 0 else [])


def line(r):
    what = r.get("object") or ("joints of %d pieces" % r.get("pieces", 0))
    return "  %s  %-28s %-6s %3d edges  seams %.2f m  visible %.2f m  ratio p50 %s p95 %s  %s%s" % (
        "CHECK" if r["issues"] else "OK   ", what, r["kind"], r["edges"], r["seam_m"], r["visible_m"],
        r.get("ratio_p50", "-"), r.get("ratio_p95", "-"), "; ".join(r["issues"]) or "no seam shows",
        "".join("  NOTE: %s" % n for n in r.get("notes", [])))


# ----------------------------------------------------------------------------------------------- command line
def _run(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="texture_seams.py", description=__doc__.split("\n")[0])
    ap.add_argument("--objects", default="*", help="name pattern (case-sensitive fnmatch): meshes, and with --joints "
                    "collection-instance empties too")
    ap.add_argument("--image", required=True, help="the texture to judge (a path)")
    ap.add_argument("--kind", choices=("color", "normal"), default="color")
    ap.add_argument("--uv", default=None, help="UV map name (default the active one)")
    ap.add_argument("--material", default=None, help="only faces whose material name matches (a name or pattern)")
    ap.add_argument("--joints", action="store_true", help="judge where the matched pieces meet instead of their seams")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    obs = [o for o in bpy.data.objects if fnmatch.fnmatchcase(o.name, a.objects)
           and (o.type == "MESH" or (a.joints and o.instance_type == "COLLECTION"))]
    if not obs:
        raise ValueError("no object matched --objects %r" % a.objects)
    if a.joints:
        reps = [joints(obs, a.image, a.kind, a.uv, a.material)]
    else:
        reps = [seams(o, a.image, a.kind, a.uv, a.material) for o in obs]
    for r in reps:
        print(line(r))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(reps, f, indent=2)
    return 1 if any(r["issues"] for r in reps) else 0


def _main(argv):
    try:
        return _run(argv)
    except ValueError as e:
        print("texture_seams: %s" % e)
        return 2


if __name__ == "__main__" and bpy is not None and not globals().get("TEXTURE_SEAMS_NO_MAIN"):
    sys.exit(_main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []))
