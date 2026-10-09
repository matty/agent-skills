"""End-to-end check: build two test meshes, unwrap them with RizomUV through blender_rizom.py, assert quality.

Host: Blender 4.2+ with RizomUV 2027.0.417+ installed. Leaves the user's scene alone when run in the background:
    blender -b --factory-startup --python smoke_test_blender.py [-- --keep out.blend] [-- --png <dir>]

Meshes: a pointed-arch portal surround (hard surface, generator seams at the springing lines and apex) and a
revolved urn on a bevelled plinth (organic, auto seams only). Expected on RizomUV 2027.0.598: arch angular
1.00 and coverage about 0.60; urn angular p95 about 1.09 and area p95 about 0.10; no overlaps, flips, padding or
margin breaches; a texel-density pack lands on its target; an impossible density is reported and writes
nothing; with --png <dir>, both stretch maps exist. Exit code 1 on any failure.
"""

import math
import os
import sys

import bmesh
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_rizom as br  # noqa: E402
import rizom_uv as ru  # noqa: E402
from rizom_link import rizom_session  # noqa: E402


def _obj(name, bm):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def build_arch():
    s, ys, h = 3.0, 2.2, 1.6               # span, springing height, rise
    b, d, c = 0.35, 0.45, 0.06             # band width, depth, chamfer
    r = (s * s / 4 + h * h) / s
    nj, na = 6, 14

    def outline(off):
        pts = [(-s / 2 - off, ys * i / nj) for i in range(nj + 1)]
        cx = -s / 2 + r
        a0, a1 = math.pi, math.atan2(h, -(r - s / 2))
        for i in range(1, na + 1):
            a = a0 + (a1 - a0) * i / na
            pts.append((cx + (r + off) * math.cos(a), ys + (r + off) * math.sin(a)))
        apex = pts[-1]
        for i in range(na - 1, -1, -1):
            a = a0 + (a1 - a0) * i / na
            pts.append((-(cx + (r + off) * math.cos(a)), ys + (r + off) * math.sin(a)))
        pts[nj + na] = (0.0, apex[1])
        pts += [(s / 2 + off, ys * i / nj) for i in range(nj - 1, -1, -1)]
        return pts

    inner, cham, outer = outline(0.0), outline(c), outline(b)
    bm = bmesh.new()
    of = [bm.verts.new((p[0], 0, p[1])) for p in outer]
    cf = [bm.verts.new((p[0], 0, p[1])) for p in cham]
    ifr = [bm.verts.new((p[0], c, p[1])) for p in inner]
    ib = [bm.verts.new((p[0], d, p[1])) for p in inner]
    ob_ = [bm.verts.new((p[0], d, p[1])) for p in outer]
    for k in range(len(inner) - 1):
        j = k + 1
        for q in ((of[k], of[j], cf[j], cf[k]), (cf[k], cf[j], ifr[j], ifr[k]), (ifr[k], ifr[j], ib[j], ib[k]),
                  (ib[k], ib[j], ob_[j], ob_[k]), (ob_[k], ob_[j], of[j], of[k])):
            bm.faces.new(q)
    for k in (0, len(inner) - 1):
        bm.faces.new((of[k], cf[k], ifr[k], ib[k], ob_[k]))
    for k in (nj, nj + na, nj + 2 * na):   # generator seams: both springing lines and the apex
        for a, b2 in ((of[k], cf[k]), (cf[k], ifr[k]), (ifr[k], ib[k]), (ib[k], ob_[k]), (ob_[k], of[k])):
            e = bm.edges.get((a, b2))
            if e:
                e.seam = True
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _obj("SMOKE_Arch", bm)


def build_urn():
    prof = [(0.0, 0.50), (0.30, 0.50), (0.30, 0.58), (0.24, 0.60), (0.13, 0.66), (0.11, 0.80), (0.19, 0.90),
            (0.29, 1.05), (0.32, 1.20), (0.29, 1.35), (0.19, 1.45), (0.14, 1.52), (0.16, 1.58), (0.23, 1.62),
            (0.23, 1.65), (0.20, 1.65), (0.12, 1.56), (0.17, 1.42), (0.0, 1.42)]
    seg = 24
    bm = bmesh.new()
    rings = []
    for rr, z in prof:
        if rr == 0.0:
            rings.append([bm.verts.new((0, 0, z))])
        else:
            rings.append([bm.verts.new((rr * math.cos(2 * math.pi * k / seg), rr * math.sin(2 * math.pi * k / seg), z))
                          for k in range(seg)])
    for a, b in zip(rings, rings[1:]):
        for k in range(seg):
            if len(a) == 1:
                bm.faces.new((a[0], b[(k + 1) % seg], b[k]))
            elif len(b) == 1:
                bm.faces.new((a[k], a[(k + 1) % seg], b[0]))
            else:
                bm.faces.new((a[k], a[(k + 1) % seg], b[(k + 1) % seg], b[k]))
    res = bmesh.ops.create_cube(bm, size=1.0)
    pv = res["verts"]
    bmesh.ops.scale(bm, vec=(0.7, 0.7, 0.5), verts=pv)
    bmesh.ops.translate(bm, vec=(0, 0, 0.25), verts=pv)
    top = [e for e in bm.edges if all(v in pv for v in e.verts) and all(abs(v.co.z - 0.5) < 1e-4 for v in e.verts)]
    bmesh.ops.bevel(bm, geom=top, offset=0.04, segments=1, affect="EDGES")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _obj("SMOKE_Urn", bm)


def _uv_bytes(ob, layer):
    import numpy as np
    a = np.empty(2 * len(ob.data.loops), dtype=np.float32)
    ob.data.uv_layers[layer].data.foreach_get("uv", a)
    return a.tobytes()


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    png_dir = os.path.abspath(argv[argv.index("--png") + 1]) if "--png" in argv else None
    arch, urn = build_arch(), build_urn()
    fails = []
    with rizom_session() as link:
        print("RizomUV", link.RizomUVVersion())
        reps = []
        for ob, kind in ((arch, "hard"), (urn, "organic")):
            png = os.path.join(png_dir, ob.name + "_stretch.png") if png_dir else None
            r = br.unwrap_object(link, ob, kind, stretch_png=png)
            reps.append(r)
            print(br._line(r))
            if png and not os.path.isfile(png):
                fails.append("stretch map not written: %s" % png)
        # texel-density packing: 300 px/m on a 1024 map must land on 300 and stay inside the tile
        td = br.unwrap_object(link, urn, "organic", uv0=ru.pack_spec(1024, 8, 4, px_per_unit=300.0), uv2=None)
        got = td["layers"]["UVMap"]["px_per_unit"]
        print("  texel density: asked 300 px/m, got %.1f, fits %s" % (got, td["layers"]["UVMap"]["fits"]))
        if not td["layers"]["UVMap"]["fits"] or abs(got / 300.0 - 1) > 0.02:
            fails.append("texel-density pack missed its target")
        # a density too high to fit must be reported, and must not overwrite the UVs already there
        before = _uv_bytes(urn, "UVMap")
        big = br.unwrap_object(link, urn, "organic", uv0=ru.pack_spec(256, 4, 2, px_per_unit=5000.0), uv2=None)
        if big["layers"]["UVMap"]["fits"]:
            fails.append("an impossible texel density was reported as fitting")
        elif big["layers"]["UVMap"]["written"] or _uv_bytes(urn, "UVMap") != before:
            fails.append("a pack that does not fit was written over the UVs")
        else:
            print("  overflow detected and nothing written (5000 px/m on a 256 map)")
    for r in reps:
        if r["gate_failures"]:
            fails.append("%s: %s" % (r["object"], r["gate_failures"]))
        for name, l in r["layers"].items():
            if (l["overlap_px"] or l["flipped_polygons"] or not l["in_unit_tile"] or l.get("padding_pairs_below_min")
                    or not l.get("margin_ok", True)):
                fails.append("%s %s: overlap %s flips %s bounds %s padding %s (min gap %s px) margin %s px" % (
                    r["object"], name, l["overlap_px"], l["flipped_polygons"], l["in_unit_tile"],
                    l.get("padding_pairs_below_min"), l.get("padding_min_px"), l.get("margin_px_min")))
            if not l["written"]:
                fails.append("%s %s was not written" % (r["object"], name))
            if l["coverage"] < 0.35:
                fails.append("%s %s: coverage %.2f" % (r["object"], name, l["coverage"]))
    if "--keep" in argv:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(argv[argv.index("--keep") + 1]))
    print("SMOKE TEST", "PASSED" if not fails else "FAILED")
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    code = main()
    if bpy.app.background:
        sys.exit(code)
