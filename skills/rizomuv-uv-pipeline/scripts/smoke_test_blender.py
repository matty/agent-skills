"""End-to-end check: build test meshes, unwrap them with RizomUV through blender_rizom.py, assert quality.

Host: Blender 4.2+ with RizomUV 2027.0.417+ installed. Leaves the user's scene alone when run in the background:
    blender -b --factory-startup --python-exit-code 1 --python smoke_test_blender.py [-- --png <dir> --keep out.blend]

Meshes: a pointed-arch portal surround (hard surface, generator seams at the springing lines and apex) and a
revolved urn on a bevelled plinth (organic, auto seams only), both graded on UV0 and their lightmap UV at the
default 20 texels/m; then the cases that once went wrong: a texel-density pack must land on its target, an
impossible density must write nothing, linked duplicates with a Mirror and modifiers="apply" must each be
unwrapped, an imported first UV layer must not end up in the lightmap slot, a small piece's lightmap gaps must be
>= 2 texels at its footprint with a probe-light note, planks packed with directional="grain" must all run along U,
a sign with rizom_directional="upright" must read world up as +V, a 1-segment chamfered box under the hard preset
must go on to the organic preset instead of printing OK at 0.1-0.2 coverage, a bevelled 2.4 m strip packed at
512 px/m on 2048 px must fit through the organic preset (hard alone does not), a 3 m beam must print OK with a thin
piece note (a square tile cannot hold it better), a mesh shared by a full-size and a half-size object must keep
2-texel lightmap gaps at the smaller one's footprint, and a plank whose half-size copy gets 3.3 px must get a
lightmap UV packed for 64 px with the too-small note (every render mesh keeps a UV2), a mitred window frame and a
5-step stair must pass (islands that follow planar regions are not confetti), and a craggy 5120-face rock must print
OK with its many-islands note and a UV2 packed for a larger footprint. With --png <dir>, both
stretch maps must exist and be mostly grey (a saturated map means the neutral is wrong).

Measured 2026-10-17 on RizomUV 2027.0.598, Blender 5.2.2 (UV0 16 px gaps at 1024): arch 22 islands, angular p95
1.00, area p95 0, coverage 0.59; urn 18 islands, angular p95 1.09, area p95 0.10, coverage 0.55; no overlap,
flips, padding or margin failures on either layer. Exit code 1 on any failure.
"""

import math
import os
import sys

import bmesh
import bpy

sys.dont_write_bytecode = True                   # no __pycache__ in the skill folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_rizom as br  # noqa: E402
import probe_pack_enums as probe  # noqa: E402  (its pure-Python PNG reader)
import rizom_uv as ru  # noqa: E402
import uv_metrics as um  # noqa: E402
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


def build_box(name, size, loc):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    ob = _obj(name, bm)
    ob.location = loc
    return ob


def build_planks():
    """Six planks in one mesh, two long along each axis. Returns the object and, per polygon, its grain axis
    (0 X, 1 Y, 2 Z; -1 for end grain)."""
    bm, grain = bmesh.new(), []
    for center, size, axis in (((0, 0, 0), (1.2, 0.1, 0.2), 0), ((0, 0.5, 0), (1.0, 0.15, 0.1), 0),
                               ((1.5, 0, 0), (0.1, 1.2, 0.2), 1), ((2.0, 0, 0), (0.15, 0.9, 0.1), 1),
                               ((3.0, 0, 0.6), (0.1, 0.2, 1.2), 2), ((3.5, 0, 0.5), (0.15, 0.1, 1.0), 2)):
        before = len(bm.faces)
        vs = bmesh.ops.create_cube(bm, size=1.0)["verts"]
        bmesh.ops.scale(bm, vec=size, verts=vs)
        bmesh.ops.translate(bm, vec=center, verts=vs)
        bm.faces.ensure_lookup_table()
        grain += [-1 if abs(f.normal[axis]) > 0.9 else axis for f in bm.faces[before:]]
    ob = _obj("SMOKE_Planks", bm)
    ob.location = (0, 6, 0)
    return ob, grain


def build_chamfered(name, dims, loc, offset=0.02):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=dims, verts=bm.verts)
    bmesh.ops.bevel(bm, geom=list(bm.edges), offset=offset, segments=1, affect="EDGES")
    ob = _obj(name, bm)
    ob.location = loc
    return ob


def build_frame(name, loc, W=1.0, H=1.4, w=0.1, d=0.08):
    """A mitred window frame, quads only, with the mitre seams marked (16 faces, 16 planar regions)."""
    bm = bmesh.new()
    o, i_ = [(0, 0), (W, 0), (W, H), (0, H)], [(w, w), (W - w, w), (W - w, H - w), (w, H - w)]
    F = [[bm.verts.new((x, 0, z)) for x, z in ring] for ring in (o, i_)]
    B = [[bm.verts.new((x, d, z)) for x, z in ring] for ring in (o, i_)]
    for k in range(4):
        j = (k + 1) % 4
        bm.faces.new((F[0][k], F[0][j], F[1][j], F[1][k]))
        bm.faces.new((B[0][j], B[0][k], B[1][k], B[1][j]))
        bm.faces.new((F[0][j], F[0][k], B[0][k], B[0][j]))
        bm.faces.new((F[1][k], F[1][j], B[1][j], B[1][k]))
    for k in range(4):
        for a, b in ((F[0][k], F[1][k]), (B[0][k], B[1][k]), (F[0][k], B[0][k]), (F[1][k], B[1][k])):
            e = bm.edges.get((a, b))
            if e:
                e.seam = True
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = _obj(name, bm)
    ob.location = loc
    return ob


def build_stair(name, steps, loc, width=1.0, rise=0.18, run=0.28):
    """A closed quad stair, no seams (5 steps: 50 faces, 14 planar regions)."""
    bm = bmesh.new()
    sides = []
    for xs in (0.0, width):
        sides.append({(i, j): bm.verts.new((xs, i * run, j * rise)) for i in range(steps + 1)
                      for j in range(steps + 1) if j <= min(i + 1, steps)})
    left, right = sides
    for s, flip in ((left, True), (right, False)):
        for i in range(steps):
            for j in range(i + 1):
                q = (s[(i, j)], s[(i + 1, j)], s[(i + 1, j + 1)], s[(i, j + 1)])
                bm.faces.new(tuple(reversed(q)) if flip else q)
    for i in range(steps):
        bm.faces.new((left[(i, i)], left[(i, i + 1)], right[(i, i + 1)], right[(i, i)]))
        bm.faces.new((left[(i, i + 1)], left[(i + 1, i + 1)], right[(i + 1, i + 1)], right[(i, i + 1)]))
        bm.faces.new((left[(i, 0)], right[(i, 0)], right[(i + 1, 0)], left[(i + 1, 0)]))
    for j in range(steps):
        bm.faces.new((left[(steps, j)], right[(steps, j)], right[(steps, j + 1)], left[(steps, j + 1)]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = _obj(name, bm)
    ob.location = loc
    return ob


def build_rock(name, loc):
    """A craggy 5120-face rock (icosphere 5 with fractal noise): over 500 islands under the organic preset."""
    from mathutils import Vector, noise
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=5, radius=0.5)
    bm.normal_update()
    for v in bm.verts:
        v.co += v.normal.copy() * (0.15 * noise.fractal(v.co * 5.0 + Vector((3.3, 3.3, 3.3)), 0.6, 2.0, 5))
        v.co.z *= 0.8
    ob = _obj(name, bm)
    ob.location = loc
    return ob


def uv_direction(ob, layer, axis_vec):
    """Per polygon: the UV direction (du, dv) of a world direction, through the polygon's 3D -> UV Jacobian."""
    import numpy as np
    me = ob.data
    uv = np.empty(2 * len(me.loops))
    me.uv_layers[layer].uv.foreach_get("vector", uv)
    uv = uv.reshape(-1, 2)
    mw = np.array(ob.matrix_world)[:3, :3]
    out = []
    for p in me.polygons:
        li = list(p.loop_indices)
        P = [mw @ np.array(me.vertices[me.loops[k].vertex_index].co) for k in li]
        e1, e2 = P[1] - P[0], P[-1] - P[0]
        J = np.stack([uv[li[1]] - uv[li[0]], uv[li[-1]] - uv[li[0]], np.zeros(2)], 1) @ np.linalg.inv(
            np.stack([e1, e2, np.cross(e1, e2)], 1))
        out.append(J @ np.asarray(axis_vec, dtype=float))
    return out


def _uv_bytes(ob, layer):
    import numpy as np
    a = np.empty(2 * len(ob.data.loops), dtype=np.float32)
    ob.data.uv_layers[layer].uv.foreach_get("vector", a)
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
            if png:
                if not os.path.isfile(png):
                    fails.append("stretch map not written: %s" % png)
                elif probe.grey_share(png) < 0.5:
                    fails.append("stretch map %s is mostly saturated: the neutral does not match RizomUV's grading"
                                 % png)
        # texel-density packing: 300 px/m on a 1024 map must land on 300 and stay inside the tile
        td = br.unwrap_object(link, urn, "organic", uv0=ru.pack_spec(1024, px_per_unit=300.0), uv2=None)
        got = td["layers"]["UVMap"]["px_per_unit"]
        print("  texel density: asked 300 px/m, got %.1f, fits %s" % (got, td["layers"]["UVMap"]["fits"]))
        if not td["layers"]["UVMap"]["fits"] or abs(got / 300.0 - 1) > 0.02:
            fails.append("texel-density pack missed its target")
        # a density too high to fit must be reported, and must not overwrite the UVs already there
        before = _uv_bytes(urn, "UVMap")
        big = br.unwrap_object(link, urn, "organic", uv0=ru.pack_spec(256, px_per_unit=5000.0), uv2=None)
        if big["layers"]["UVMap"]["fits"]:
            fails.append("an impossible texel density was reported as fitting")
        elif big["layers"]["UVMap"]["written"] or _uv_bytes(urn, "UVMap") != before:
            fails.append("a pack that does not fit was written over the UVs")
        else:
            print("  overflow detected and nothing written (5000 px/m on a 256 map)")
        # an imported first layer must not slide into the lightmap slot when no lightmap UV is written
        imp = build_box("SMOKE_Import", 1.0, (6, 0, 0))
        imp.data.uv_layers.new(name="UVChannel_1")
        br.unwrap_object(link, imp, "hard", uv2=None)
        names = [l.name for l in imp.data.uv_layers]
        print("  imported mesh, no lightmap UV: layers %s" % names)
        if names != ["UVMap"]:
            fails.append("imported first layer: layers %s, expected ['UVMap']" % names)
        # a small piece: lightmap gaps >= 2 texels at its 20 texels/m footprint, and the under-64 px note
        small = build_box("SMOKE_Small", 0.41, (8, 0, 0))
        sr = br.unwrap_object(link, small, "hard")
        l2 = sr["layers"]["UVMap_Lightmap"]
        print("  small piece: footprint %.1f px, closest gap %s texels, warnings %s"
              % (l2["footprint_px"], l2.get("padding_min_px"), [w[:40] for w in sr["warnings"]]))
        if l2["failures"] or not l2["written"]:
            fails.append("small piece lightmap UV: %s" % (l2["failures"] or "not written"))
        if not any("probe-light" in w for w in sr["warnings"]):
            fails.append("small piece: no probe-light note below 64 px")
        reps.append(sr)
        # grain: every plank face's long axis runs along U
        planks, grain = build_planks()
        pr = br.unwrap_object(link, planks, "hard", uv2=None, directional="grain")
        per_axis = [uv_direction(planks, 0, v) for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
        faces = [(i, g) for i, g in enumerate(grain) if g >= 0]
        along_u = sum(1 for i, g in faces if abs(per_axis[g][i][1]) <= 1e-6 * abs(per_axis[g][i][0]))
        print("  grain: %d of %d plank faces along U" % (along_u, len(faces)))
        if along_u != len(faces) or not faces or pr["failures"] or len(per_axis[0]) != len(grain):
            fails.append("grain: %d of %d faces along U %s" % (along_u, len(faces), pr["failures"]))
        # upright: world up reads as +V on a sign's vertical faces (per-object property)
        sign = build_box("SMOKE_Sign", 1.0, (0, 9, 1))
        sign.scale = (1.2, 0.05, 0.6)
        sign["rizom_directional"] = "upright"
        br.unwrap_object(link, sign, "hard", uv2=None)
        ups = [d for d, p in zip(uv_direction(sign, 0, (0, 0, 1)), sign.data.polygons) if abs(p.normal.z) < 0.5]
        print("  upright: world up on the vertical faces -> %s" % [tuple(round(float(x), 3) for x in d) for d in ups])
        if not all(d[1] > 0 and abs(d[0]) <= 1e-6 * d[1] for d in ups):
            fails.append("upright: world up is not +V on every vertical face")
        # a 1-segment chamfered box: the hard preset sprawls (coverage 0.1-0.2), the organic retry must take over
        cham = build_chamfered("SMOKE_Chamfer", (1.0, 1.0, 1.0), (0, 12, 0))
        cr = br.unwrap_object(link, cham, "hard", uv2=None)
        print(br._line(cr))
        if cr["failures"] or cr["attempt"] != "organic preset" or cr["layers"]["UVMap"]["coverage"] < 0.35:
            fails.append("chamfered box: %s" % br._line(cr).strip())
        # a bevelled trim strip at 512 px/m: hard joins the bevel ring into one island too long for 2048 px
        strip = build_chamfered("SMOKE_Strip", (2.4, 0.04, 0.3), (0, 18, 1), offset=0.006)
        st = br.unwrap_object(link, strip, "hard", uv0=ru.pack_spec(2048, px_per_unit=512.0), uv2=None)
        print(br._line(st))
        if not st["layers"]["UVMap"]["fits"] or st["attempt"] != "organic preset" or st["failures"]:
            fails.append("bevelled strip at 512 px/m: %s" % br._line(st).strip())
        # a mitred frame with its mitre seams and a 5-step stair: one island per planar region is not confetti
        for ob in (build_frame("SMOKE_Frame", (0, 27, 0)), build_stair("SMOKE_Stair5", 5, (3, 27, 0))):
            fr = br.unwrap_object(link, ob, "hard", uv2=None)
            print(br._line(fr))
            if fr["failures"]:
                fails.append("%s: %s" % (ob.name, br._line(fr).strip()))
        # a craggy rock: hundreds of islands, no coverage floor, and a UV2 packed for a larger footprint
        rk = br.unwrap_object(link, build_rock("SMOKE_Rock", (6, 27, 0)), "organic")
        print(br._line(rk))
        rl2 = rk["layers"]["UVMap_Lightmap"]
        if (rk["failures"] or not rl2["written"] or not any(w.startswith("many islands") for w in rk["warnings"])
                or not rl2.get("fallback_ok")):
            fails.append("craggy rock: %s" % br._line(rk).strip())
        # a long thin beam: its coverage is what its shape allows, so OK with a note, not REVIEW
        beam = build_box("SMOKE_Beam", 1.0, (0, 21, 0))
        beam.scale = (3.0, 0.12, 0.12)
        bm_r = br.unwrap_object(link, beam, "hard", uv2=None)
        print(br._line(bm_r))
        if bm_r["failures"] or not any(w.startswith("thin piece") for w in bm_r["warnings"]):
            fails.append("thin beam: %s" % br._line(bm_r).strip())
    # a mesh shared by a full-size and a half-size object: lightmap gaps >= 2 texels at the smaller footprint
    full = build_box("SMOKE_Shared", 1.0, (0, 15, 0))
    half = bpy.data.objects.new("SMOKE_Shared_half", full.data)
    half.scale = (0.5, 0.5, 0.5)
    half.location = (2, 15, 0)
    bpy.context.scene.collection.objects.link(half)
    shared = br.unwrap_objects([full, half], kind="hard")
    l2 = shared[0]["layers"]["UVMap_Lightmap"]
    print("  shared mesh: footprints %s, graded at %s px, closest gap %s texels"
          % (l2.get("footprints_px"), l2.get("graded_at_px"), l2.get("padding_min_px")))
    if (set(l2.get("footprints_px", {})) != {full.name, half.name} or l2["failures"]
            or l2["graded_at_px"] != min(l2["footprints_px"].values())):
        fails.append("shared mesh lightmap: %s" % (l2["failures"] or l2.get("footprints_px")))
    # a plank and its half-size copy at Scale In Lightmap 0.5: 3.3 px cannot hold 6 charts: a UV2 packed for 64 px
    plank = build_box("SMOKE_Plank", 1.0, (0, 24, 0))
    plank.scale = (1.2, 0.15, 0.03)
    small_copy = bpy.data.objects.new("SMOKE_Plank_small", plank.data)
    small_copy.scale, small_copy.location = (0.6, 0.075, 0.015), (0, 25, 0)
    small_copy["rizom_lightmap_scale"] = 0.5
    bpy.context.scene.collection.objects.link(small_copy)
    tiny = br.unwrap_objects([plank, small_copy], kind="hard")
    l2 = tiny[0]["layers"]["UVMap_Lightmap"]
    print(br._line(tiny[0]))
    if (not l2.get("fallback") or not l2["written"] or l2["failures"] or l2["graded_at_px"] < 64
            or "UV2 packed for 64 px" not in br._line(tiny[0])):
        fails.append("too-small lightmap UV: %s" % br._line(tiny[0]).strip())
    # linked duplicates with a Mirror and modifiers="apply": each copy gets its own mesh and is unwrapped
    a = build_box("SMOKE_DupA", 1.0, (10, 0, 0))
    a.modifiers.new("mirror", "MIRROR")
    b = bpy.data.objects.new("SMOKE_DupB", a.data)
    b.location = (13, 0, 0)
    b.modifiers.new("mirror", "MIRROR")
    bpy.context.scene.collection.objects.link(b)
    dup = br.unwrap_objects([a, b], kind="hard", modifiers="apply")
    if any("shared_mesh_of" in r or "error" in r for r in dup) or b.modifiers or a.data == b.data:
        fails.append("modifiers='apply' with linked duplicates: %s" % [br._line(r).strip()[:60] for r in dup])
    for r in reps:
        if r["failures"]:
            fails.append("%s: %s" % (r["object"], r["failures"]))
        for name, l in r["layers"].items():
            if not l["written"]:
                fails.append("%s %s was not written" % (r["object"], name))
            lightmapped = l.get("footprint_px", ru.LIGHTMAP_MIN_FOOTPRINT_PX) >= ru.LIGHTMAP_MIN_FOOTPRINT_PX
            if l["coverage"] < 0.35 and lightmapped:       # a probe-lit piece's lightmap coverage does not matter
                fails.append("%s %s: coverage %.2f" % (r["object"], name, l["coverage"]))
    if "--keep" in argv:
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(argv[argv.index("--keep") + 1]))
    print("SMOKE TEST", "PASSED" if not fails else "FAILED")
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    code = main()
    if bpy.app.background:
        sys.exit(code)
