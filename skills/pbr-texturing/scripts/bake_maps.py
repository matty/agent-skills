"""Bake mesh maps from high-poly meshes onto a low-poly mesh's UVs with Cycles: a tangent-space normal map (OpenGL
Y+, MikkTSpace tangents of the low poly as evaluated), ambient occlusion, and curvature (Pointiness through an
Emission bake). Rays start from a cage built from the low poly with averaged normals, so hard edges bake without
seams; each map bakes at `supersample` times the size and is box-filtered down (normals renormalised); maps are
written as 16-bit PNGs (or 8-bit with dither), data values, no colour management.

Host: Blender 4.2+ (bpy, Cycles and the bundled numpy), no add-ons; tested on Blender 5.2.2. Changes nothing it does
not restore: temporary images, materials, nodes and the cage are removed, render settings put back. Never saves the
.blend.

Command line (open the .blend that holds the meshes):
    blender -b --factory-startup crate.blend --python-exit-code 1 --python bake_maps.py --
            --low PROP_Crate_Free_A --high Crate_high --size 2048 --out blender/substance/PROP/bake
            --name T_PROP_Crate --maps normal,ao,curvature [--supersample 2] [--extrusion 0.02] [--margin 16]
            [--samples 64] [--ao-distance 0.2] [--bits 16] [--gpu]
As a module (Blender MCP or another script):
    ns = {"BAKE_MAPS_NO_MAIN": True}; exec(open(path, encoding="utf-8").read(), ns)
    paths = ns["bake"](low, [high], maps=("normal", "ao"), size=1024, out_dir=..., name="T_PROP_Crate")

Output: <out_dir>/<name>_Normal.png, _AO.png, _Curvature.png; returns {map: path} plus "report" (sizes, seconds, the
curvature gain used). The low poly bakes as it exports: modifiers applied (keep its Triangulate on, so the baker and
the engine see the same triangles), through its active render UV layer unless uv_layer is given.
"""

import argparse
import math
import os
import struct
import sys
import time
import zlib

import bpy
import numpy as np

MAP_SUFFIX = {"normal": "Normal", "ao": "AO", "curvature": "Curvature"}
NEUTRAL = {"normal": (0.5, 0.5, 1.0), "ao": (1.0, 1.0, 1.0), "curvature": (0.5, 0.5, 0.5)}


# ---- helpers ------------------------------------------------------------------------------------------------------

def make_cage(low, extrusion, depsgraph=None):
    """A cage object: the low poly as evaluated (same triangles as the bake), every vertex pushed out along its
    averaged normal by `extrusion` (object space; metres on a kit piece at scale 1). Averaged normals keep the rays
    continuous across hard edges; rays that follow split normals leave a seam along every hard edge."""
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    ev = low.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev)
    me.name = low.name + "_bake_cage"
    for v in me.vertices:            # MeshVertex.normal is the vertex (averaged) normal, whatever the sharp edges
        v.co += v.normal * extrusion
    cage = bpy.data.objects.new(me.name, me)
    cage.matrix_world = low.matrix_world.copy()
    bpy.context.scene.collection.objects.link(cage)
    return cage


def cage_extrusion(low, highs, depsgraph=None, safety=1.1, max_samples=20000):
    """The cage push that encloses the high polys: how far the high-poly vertices stand outside the low poly's
    surface (signed distance to the nearest low face, sampled up to max_samples vertices per object), divided by the
    smallest cosine between a vertex's averaged normal and its faces' normals (a vertex pushed along the averaged
    normal moves its faces out by only that share: 0.577 at a cube corner), times safety. Returns (extrusion,
    outside distance), both in the low poly's object space. A cage that does not enclose the high poly starts rays
    inside it: protruding detail bakes as rings and its AO comes out black."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    ev = low.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        verts = [v.co.copy() for v in me.vertices]
        polys = [tuple(p.vertices) for p in me.polygons]
        min_cos = 1.0
        for p in me.polygons:
            for vi in p.vertices:
                min_cos = min(min_cos, me.vertices[vi].normal.dot(p.normal))
    finally:
        ev.to_mesh_clear()
    bvh = BVHTree.FromPolygons(verts, polys)
    to_low = low.matrix_world.inverted()
    outside = 0.0
    for h in highs:
        hev = h.evaluated_get(dg)
        hme = hev.to_mesh()
        try:
            n = len(hme.vertices)
            co = np.empty(n * 3, np.float32)
            hme.vertices.foreach_get("co", co)
            co = co.reshape(-1, 3)[::max(1, n // max_samples)]
            m = to_low @ h.matrix_world
            for c in co:
                p = m @ Vector(c)
                loc, nrm, _i, _d = bvh.find_nearest(p)
                if loc is not None:
                    outside = max(outside, (p - loc).dot(nrm))
        finally:
            hev.to_mesh_clear()
    return outside / max(min_cos, 0.1) * safety, outside


def _box_down(a, f):
    if f <= 1:
        return a
    h, w = a.shape[0] // f, a.shape[1] // f
    return a[:h * f, :w * f].reshape(h, f, w, f, a.shape[2]).mean(axis=(1, 3))


def _image_array(img):
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)[::-1].copy()          # rows top to bottom


def save_png(path, rgb, bits=16, seed=0):
    """Write a float (height, width, 1 or 3) array in 0-1, rows top to bottom, as a grey or RGB PNG: 16 bits per
    channel, or 8 with triangular dither so smooth gradients do not band."""
    a = np.clip(np.asarray(rgb, np.float64), 0.0, 1.0)
    if a.ndim == 2:
        a = a[:, :, None]
    h, w, ch = a.shape
    if bits == 16:
        codes = np.round(a * 65535.0).astype(">u2")
    else:
        rng = np.random.default_rng(seed)
        noise = rng.random(a.shape) - rng.random(a.shape)       # triangular, -1..1 LSB
        codes = np.clip(np.round(a * 255.0 + noise * 0.5), 0, 255).astype(np.uint8)
    raw = b"".join(b"\x00" + codes[y].tobytes() for y in range(h))
    colour = {1: 0, 3: 2}[ch]

    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, bits, colour, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    return path


def _active_image_nodes(obj, img):
    """Give every material of obj an active Image Texture node holding img (the bake target); returns an undo list."""
    undo = []
    if not obj.material_slots or all(s.material is None for s in obj.material_slots):
        mat = bpy.data.materials.new("bake_tmp_material")
        mat.use_nodes = True
        if not obj.material_slots:
            obj.data.materials.append(mat)
            undo.append(("pop_slot", obj))
        else:
            for s in obj.material_slots:
                s.material = mat
            undo.append(("clear_slots", obj))
        undo.append(("material", mat))
    for s in obj.material_slots:
        mat = s.material
        if mat is None:
            continue
        mat.use_nodes = True
        nt = mat.node_tree
        prev = nt.nodes.active
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = img
        node.select = True
        nt.nodes.active = node
        undo.append(("node", mat, node, prev))
    return undo


def _undo(undo):
    for item in reversed(undo):
        kind = item[0]
        if kind == "node":
            _k, mat, node, prev = item
            mat.node_tree.nodes.remove(node)
            if prev is not None:
                mat.node_tree.nodes.active = prev
        elif kind == "pop_slot":
            item[1].data.materials.pop()
        elif kind == "clear_slots":
            for s in item[1].material_slots:
                s.material = None
        elif kind == "material":
            bpy.data.materials.remove(item[1])


def _pointiness_materials(highs):
    """Swap every material of the high polys for an Emission of Cycles' Pointiness (raw, 0.5 on flat surfaces)."""
    mat = bpy.data.materials.new("bake_tmp_pointiness")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    emi = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(geo.outputs["Pointiness"], emi.inputs["Color"])
    nt.links.new(emi.outputs["Emission"], out.inputs["Surface"])
    saved = []
    for h in highs:
        mats = [s.material for s in h.material_slots]
        saved.append((h, mats))
        if not h.material_slots:
            h.data.materials.append(mat)
        else:
            for s in h.material_slots:
                s.material = mat
    return mat, saved


def _restore_materials(mat, saved):
    for h, mats in saved:
        if not mats:
            h.data.materials.pop()
        else:
            for s, m in zip(h.material_slots, mats):
                s.material = m
    bpy.data.materials.remove(mat)


# ---- the bake -------------------------------------------------------------------------------------------------------

def bake(low, highs, maps=("normal",), size=1024, out_dir=".", name=None, supersample=2, extrusion=None, margin=16,
         samples=None, ao_distance=None, bits=16, uv_layer=None, curvature_gain=None, gpu=False, cage=None):
    """Bake `maps` (normal, ao, curvature) from `highs` onto `low` and write <name>_<Map>.png into out_dir.
    extrusion: cage push along the averaged normals (default: cage_extrusion(), enough to enclose the high polys);
    margin: dilation in pixels at
    the output size (scaled by supersample while baking; at least half the island gap); samples: Cycles samples per
    map (default normal 8, ao 64, curvature 8); ao_distance: AO ray length in metres (default 10% of the diagonal);
    curvature_gain: fixed contrast for the curvature map (default: per map, so the 99th percentile of |pointiness -
    0.5| reaches 0.5; give one value for every piece of a set so they match)."""
    t0 = time.time()
    scene = bpy.context.scene
    name = name or low.name
    os.makedirs(out_dir, exist_ok=True)
    highs = [h for h in highs if h is not None and h != low]
    if not highs:
        raise ValueError("no high-poly objects to bake from")
    diag = max(low.dimensions.length, 1e-6)
    outside = None
    if extrusion is None:
        extrusion, outside = cage_extrusion(low, highs)
        extrusion = max(extrusion, 0.005 * diag)          # a little push even when the high poly sits inside
    extrusion = float(extrusion)
    ao_distance = 0.1 * diag if ao_distance is None else float(ao_distance)
    ss = max(1, int(supersample))
    w = h = int(size) * ss
    keep = {"engine": scene.render.engine, "samples": scene.cycles.samples, "device": scene.cycles.device,
            "ao": scene.world.light_settings.distance if scene.world else None,
            "selected": [o for o in bpy.context.view_layer.objects if o.select_get()],
            "active": bpy.context.view_layer.objects.active}
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU" if gpu else "CPU"
    own_cage = cage is None
    cage = cage or make_cage(low, extrusion)
    out, report = {}, {"size": int(size), "supersample": ss, "extrusion": round(extrusion, 5),
                       "high_outside": None if outside is None else round(outside, 5),
                       "ao_distance": round(ao_distance, 5), "maps": {}}
    try:
        for m in maps:
            if m not in MAP_SUFFIX:
                raise ValueError("unknown map %r (normal, ao, curvature)" % m)
            t1 = time.time()
            img = bpy.data.images.new("bake_tmp_" + m, w, h, alpha=False, float_buffer=True)
            img.colorspace_settings.name = "Non-Color"
            img.pixels.foreach_set(np.tile(np.array(NEUTRAL[m] + (1.0,), np.float32), w * h))   # uncovered: neutral
            undo = _active_image_nodes(low, img)
            pmat = saved = None
            try:
                bpy.ops.object.select_all(action="DESELECT")
                for hobj in highs:
                    hobj.select_set(True)
                low.select_set(True)
                bpy.context.view_layer.objects.active = low
                kw = dict(use_selected_to_active=True, use_cage=True, cage_object=cage.name, max_ray_distance=0.0,
                          margin=int(margin) * ss, margin_type="ADJACENT_FACES", target="IMAGE_TEXTURES",
                          use_clear=False, uv_layer=uv_layer or "")
                if m == "normal":
                    scene.cycles.samples = samples or 8
                    bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", normal_r="POS_X", normal_g="POS_Y",
                                        normal_b="POS_Z", **kw)
                elif m == "ao":
                    scene.cycles.samples = samples or 64
                    if scene.world:
                        scene.world.light_settings.distance = ao_distance
                    bpy.ops.object.bake(type="AO", **kw)
                else:
                    scene.cycles.samples = samples or 8
                    pmat, saved = _pointiness_materials(highs)
                    bpy.ops.object.bake(type="EMIT", **kw)
                a = _box_down(_image_array(img)[:, :, :3], ss)
                info = {}
                if m == "normal":
                    n = a * 2.0 - 1.0
                    n /= np.maximum(np.linalg.norm(n, axis=2, keepdims=True), 1e-8)
                    a = (n + 1.0) / 2.0
                elif m == "ao":
                    a = a[:, :, :1]
                else:
                    p = a[:, :, 0] - 0.5
                    dev = np.abs(p[np.abs(p) > 1e-4])
                    gain = float(curvature_gain) if curvature_gain else (
                        0.5 / max(float(np.percentile(dev, 99)), 1e-6) if dev.size else 1.0)
                    a = np.clip(0.5 + p * gain, 0.0, 1.0)[:, :, None]
                    info["gain"] = round(gain, 3)
                path = os.path.join(out_dir, "%s_%s.png" % (name, MAP_SUFFIX[m]))
                save_png(path, a, bits=bits)
                out[m] = path
                info["seconds"] = round(time.time() - t1, 2)
                report["maps"][m] = info
            finally:
                if pmat is not None:
                    _restore_materials(pmat, saved)
                _undo(undo)
                bpy.data.images.remove(img)
    finally:
        if own_cage:
            me = cage.data
            bpy.data.objects.remove(cage)
            bpy.data.meshes.remove(me)
        scene.render.engine = keep["engine"]
        scene.cycles.samples = keep["samples"]
        scene.cycles.device = keep["device"]
        if scene.world and keep["ao"] is not None:
            scene.world.light_settings.distance = keep["ao"]
        bpy.ops.object.select_all(action="DESELECT")
        for o in keep["selected"]:
            o.select_set(True)
        bpy.context.view_layer.objects.active = keep["active"]
    report["seconds"] = round(time.time() - t0, 2)
    out["report"] = report
    return out


def main(argv):
    ap = argparse.ArgumentParser(prog="bake_maps.py", description=__doc__.split("\n")[0])
    ap.add_argument("--low", required=True, help="the low-poly object")
    ap.add_argument("--high", required=True, action="append", help="a high-poly object (repeat for several)")
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--out", default=".")
    ap.add_argument("--name", help="file name prefix (default: the low poly's name)")
    ap.add_argument("--maps", default="normal,ao,curvature")
    ap.add_argument("--supersample", type=int, default=2)
    ap.add_argument("--extrusion", type=float)
    ap.add_argument("--margin", type=int, default=16)
    ap.add_argument("--samples", type=int)
    ap.add_argument("--ao-distance", type=float)
    ap.add_argument("--curvature-gain", type=float)
    ap.add_argument("--bits", type=int, choices=(8, 16), default=16)
    ap.add_argument("--uv-layer")
    ap.add_argument("--gpu", action="store_true")
    a = ap.parse_args(argv)
    obs = bpy.data.objects
    missing = [n for n in [a.low] + a.high if n not in obs]
    if missing:
        print("[bake] no object named %s" % ", ".join(missing))
        return 2
    res = bake(obs[a.low], [obs[n] for n in a.high], maps=tuple(m.strip() for m in a.maps.split(",") if m.strip()),
               size=a.size, out_dir=a.out, name=a.name, supersample=a.supersample, extrusion=a.extrusion,
               margin=a.margin, samples=a.samples, ao_distance=a.ao_distance, bits=a.bits, uv_layer=a.uv_layer,
               curvature_gain=a.curvature_gain, gpu=a.gpu)
    for m, p in res.items():
        if m != "report":
            print("[bake] %s -> %s" % (m, p))
    print("[bake] report %s" % res["report"])
    return 0


if __name__ == "__main__" and not globals().get("BAKE_MAPS_NO_MAIN"):
    sys.exit(main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []))
