"""Blender-hosted tests for the pbr-texturing skill's scripts: bake_maps.py bakes an OpenGL tangent-space normal map,
AO and curvature from a high poly through a cage that encloses it (a cage that does not starts rays inside protruding
detail: black AO, rings for domes), restores everything it touched, writes 16-bit PNGs and dithered 8-bit ones (grey,
grey + alpha, RGB, RGBA), bakes non-square maps, sizes a uniform cage by the faces the detail stands on (not the
sharpest corner), fits a per-vertex cage that clears a narrow channel without losing floating piping, Gaussian
pre-filters before downsampling (a steadier sloped edge than a box filter), refuses highs in an excluded collection, and
its CLI bakes a saved .blend; lookdev_render.py shows a metal's roughness map where Workbench shows none of it, and
renders maps from the command line; pbr_check.py's convention test reads real Cycles bakes as OpenGL (and a green-flipped
copy as DirectX), and its Blender loader returns the same codes as its own PNG reader for 8- and 16-bit PNGs written by
Blender and by the scripts (a 16-bit PNG read under the default sRGB tag comes back linearised: the reason it sets
Non-Color).

Host: Blender 4.2+ (bpy, Cycles; tested on 5.2.2), run from anywhere:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_pbr_texturing_bake.py
Builds its fixtures in a temp folder, prints PASS <case> / FAIL <case>: <why>, and raises if any case failed.
"""

import math
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "skills" / "pbr-texturing" / "scripts"
TMP = Path(tempfile.mkdtemp(prefix="pbr_texturing_test_"))
RESULTS = []


def case(fn):
    try:
        fn()
        RESULTS.append(("PASS", fn.__name__, ""))
        print("PASS", fn.__name__)
    except Exception as exc:  # noqa: BLE001 - every failure is reported, then the run fails
        RESULTS.append(("FAIL", fn.__name__, str(exc)))
        print("FAIL %s: %s" % (fn.__name__, exc))
        traceback.print_exc()


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def load_ns(name, **extra):
    ns = dict(extra)
    path = SCRIPTS / name
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)
    return ns


BAKE = load_ns("bake_maps.py", BAKE_MAPS_NO_MAIN=True)
LOOK = load_ns("lookdev_render.py", LOOKDEV_NO_MAIN=True)
sys.dont_write_bytecode = True
sys.path.insert(0, str(SCRIPTS))
import pbr_check as PC  # noqa: E402

# island i of the low cube: column i % 3, row i // 3, each a 0.2733 UV square starting at (col / 3 + 0.03, row / 2
# + 0.03); bumps (r 0.06 m, standing 0.06 m proud) at face coordinates (0.72, 0.68) and (0.30, 0.26)
CELL, GAP = 1.0 / 3.0, 0.03
SIZE_UV = min(CELL, 0.5) - 2 * GAP
POS_FACE = []      # indices of the low cube's faces whose normal points along +X, +Y or +Z (their UVs are not mirrored)


def island_uv(i, s, t):
    col, row = i % 3, i // 3
    return col * CELL + GAP + s * SIZE_UV, row * 0.5 + GAP + t * SIZE_UV


def build_fixture():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    me = bpy.data.meshes.new("cube_low")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    uv = bm.loops.layers.uv.new("UVMap")
    bm.faces.ensure_lookup_table()
    POS_FACE.clear()
    for i, f in enumerate(bm.faces):
        n = f.normal
        ax = max(range(3), key=lambda k: abs(n[k]))
        a, b = [k for k in range(3) if k != ax]
        if n[ax] > 0:
            POS_FACE.append(i)
        for loop in f.loops:
            s, t = loop.vert.co[a] + 0.5, loop.vert.co[b] + 0.5
            if n[ax] < 0:
                s = 1.0 - s
            loop[uv].uv = island_uv(i, s, t)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = False
    low = bpy.data.objects.new("cube_low", me)
    bpy.context.scene.collection.objects.link(low)
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    high = bpy.context.active_object
    high.name = "cube_high"
    bev = high.modifiers.new("bev", "BEVEL")
    bev.width, bev.segments = 0.04, 4
    sub = high.modifiers.new("sub", "SUBSURF")
    sub.levels = sub.render_levels = 2
    bpy.ops.object.modifier_apply(modifier="bev")
    bpy.ops.object.modifier_apply(modifier="sub")
    parts = [high]
    for ax in range(3):
        for sign in (1, -1):
            for du, dv in ((0.22, 0.18), (-0.2, -0.24)):
                loc = [0.0, 0.0, 0.0]
                loc[ax] = 0.5 * sign
                others = [k for k in range(3) if k != ax]
                loc[others[0]], loc[others[1]] = du, dv
                bpy.ops.mesh.primitive_uv_sphere_add(radius=0.06, location=loc, segments=24, ring_count=12)
                parts.append(bpy.context.active_object)
    bpy.ops.object.select_all(action="DESELECT")
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = high
    bpy.ops.object.join()
    bpy.ops.object.shade_smooth()
    bpy.ops.object.select_all(action="DESELECT")
    return low, high


def sample(px, u, v):
    """The texel at UV (u, v) of an array with rows top to bottom."""
    r = min(int((1.0 - v) * px.shape[0]), px.shape[0] - 1)
    c = min(int(u * px.shape[1]), px.shape[1] - 1)
    return px[r, c]


def test_bake_normal_ao_curvature():
    low, high = build_fixture()
    images, mats, objs = set(bpy.data.images), set(bpy.data.materials), set(bpy.data.objects)
    engine = bpy.context.scene.render.engine
    out = TMP / "bake"
    res = BAKE["bake"](low, [high], maps=("normal", "ao", "curvature"), size=128, out_dir=str(out), name="T_TST_Cube")
    rep = res["report"]
    check(abs(rep["high_outside"] - 0.06) < 0.005, "high poly stands %s outside, expected 0.06" % rep["high_outside"])
    check(rep["extrusion"] > 0.06 / 0.577, "cage extrusion %s does not enclose 0.06 at a cube corner" % rep["extrusion"])
    check(set(bpy.data.images) == images and set(bpy.data.materials) == mats and set(bpy.data.objects) == objs,
          "temporary images, materials or objects left behind")
    check(bpy.context.scene.render.engine == engine, "render engine not restored")
    for m, colour in (("normal", 2), ("ao", 0), ("curvature", 0)):
        hdr = PC.png_header(res[m])
        check(hdr[:4] == (128, 128, 16, colour), "%s header %s" % (m, hdr))
    nrm, _ = PC.load(res["normal"])
    i = POS_FACE[0]
    flat = sample(nrm, *island_uv(i, 0.5, 0.5))[:3] * 255.0
    check(np.abs(flat - [127.5, 127.5, 255.0]).max() < 2.5, "flat face texel %s, expected about 128,128,255" % flat)
    conv, r, _n = PC.normal_convention(nrm[:, :, :3] * 2 - 1)
    check(conv == "opengl" and r >= 0.3, "Cycles bake read as %s (r %s)" % (conv, r))
    flipped = nrm.copy()
    flipped[:, :, 1] = 1.0 - flipped[:, :, 1]
    conv_f, r_f, _n = PC.normal_convention(flipped[:, :, :3] * 2 - 1)
    check(conv_f == "directx" and r_f <= -0.3, "green-flipped bake read as %s (r %s)" % (conv_f, r_f))
    print("  Cycles normal bake r %.3f, flipped %.3f" % (r, r_f))
    ao, _ = PC.load(res["ao"])
    top = float(sample(ao, *island_uv(i, 0.72, 0.68))[0])
    ring = min(float(sample(ao, *island_uv(i, 0.72 + d, 0.68))[0]) for d in (0.065, 0.07, 0.075, 0.08))
    check(top > 0.9, "AO on a bump top %.3f: the cage does not enclose the bump" % top)
    check(ring < 0.95, "no contact shadow round the bump base (AO %.3f)" % ring)
    curv, _ = PC.load(res["curvature"])
    c_flat = float(sample(curv, *island_uv(i, 0.5, 0.5))[0])
    c_edge = float(sample(curv, *island_uv(i, 0.5, 0.995))[0])
    check(abs(c_flat - 0.5) < 0.03 and c_edge > c_flat + 0.05,
          "curvature flat %.3f, convex bevel %.3f: convex should read brighter than 0.5" % (c_flat, c_edge))


def test_cage_that_does_not_enclose_bakes_black_ao():
    low, high = build_fixture()
    res = BAKE["bake"](low, [high], maps=("ao",), size=64, out_dir=str(TMP / "small_cage"), name="T_TST_Small",
                       extrusion=0.02)
    ao, _ = PC.load(res["ao"])
    top = float(sample(ao, *island_uv(POS_FACE[0], 0.72, 0.68))[0])
    check(top < 0.3, "AO on a bump top %.3f with a 0.02 cage: expected black (rays start inside the bump)" % top)


def test_bpy_loader_matches_png_reader():
    d = TMP / "loader"
    d.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(4)
    grad = np.dstack([np.tile(np.linspace(0, 1, 37)[None, :], (23, 1)), rng.random((23, 37)),
                      np.full((23, 37), 0.5)])
    files = {"script16.png": BAKE["save_png"](str(d / "script16.png"), grad, bits=16),
             "script8.png": BAKE["save_png"](str(d / "script8.png"), grad, bits=8)}
    PC.write_png(str(d / "pbr8.png"), np.dstack([grad, np.full((23, 37), 0.75)]))
    files["pbr8.png"] = str(d / "pbr8.png")
    for bits in (8, 16):                           # PNGs Blender writes itself (Image.save)
        img = bpy.data.images.new("w%d" % bits, 37, 23, alpha=True, float_buffer=(bits == 16))
        img.colorspace_settings.name = "Non-Color"
        img.pixels.foreach_set(np.dstack([grad, np.ones((23, 37))])[::-1].astype(np.float32).ravel())
        p = str(d / ("blender%d.png" % bits))
        img.filepath_raw = p
        img.file_format = "PNG"
        img.save()
        bpy.data.images.remove(img)
        files[os.path.basename(p)] = p
    for name, p in sorted(files.items()):
        hdr = PC.png_header(p)
        a, info = PC.load(p)
        b, _ = PC.read_png(p)
        check(info["loader"] == "bpy", "%s: loader %s inside Blender" % (name, info["loader"]))
        err = float(np.abs(a - b).max())
        check(err < 1e-6, "%s (%d-bit): bpy loader and PNG reader differ by %g" % (name, hdr[2], err))
    check(PC.png_header(files["blender16.png"])[2] == 16, "Blender wrote a float image as %d-bit PNG"
          % PC.png_header(files["blender16.png"])[2])
    im = bpy.data.images.load(files["blender16.png"], check_existing=False)     # default sRGB tag
    px = np.empty(37 * 23 * 4, np.float32)
    im.pixels.foreach_get(px)
    bpy.data.images.remove(im)
    mid = px.reshape(23, 37, 4)[::-1][0, 18, 0]                                  # stored 0.5
    check(abs(mid - 0.214) < 0.01, "16-bit PNG under sRGB read %.3f, expected linearised 0.214" % mid)


def test_dithered_8bit_tracks_a_shallow_gradient():
    d = TMP / "dither"
    d.mkdir(parents=True, exist_ok=True)
    ramp = np.tile(np.linspace(0.40, 0.42, 512)[None, :], (64, 1))                 # about 5 codes over 512 px
    p = BAKE["save_png"](str(d / "ramp8.png"), ramp, bits=8)
    a, _ = PC.read_png(p)
    blocks = a[:, :, 0].reshape(64, 16, 32).mean(axis=(0, 2))
    want = ramp.reshape(64, 16, 32).mean(axis=(0, 2))
    err = float(np.abs(blocks - want).max() * 255.0)
    check(err < 0.25, "dithered blocks miss the gradient by %.2f codes" % err)
    plain = np.round(ramp * 255.0) / 255.0
    worst = float(np.abs(plain.reshape(64, 16, 32).mean(axis=(0, 2)) - want).max() * 255.0)
    check(worst > err, "rounding without dither (%.2f codes) should band worse than dither (%.2f)" % (worst, err))


def test_cli_bakes_a_saved_blend():
    build_fixture()
    blend = TMP / "cli" / "fixture.blend"
    blend.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), copy=True)
    base = [bpy.app.binary_path, "-b", "--factory-startup", str(blend), "--python-exit-code", "1",
            "--python", str(SCRIPTS / "bake_maps.py"), "--"]
    run = subprocess.run(base + ["--low", "cube_low", "--high", "cube_high", "--size", "64x32", "--maps", "normal",
                                 "--out", str(TMP / "cli" / "out"), "--name", "T_TST_Cli"],
                         capture_output=True, text=True, timeout=300)
    check(run.returncode == 0, "CLI exit %d: %s" % (run.returncode, run.stdout[-800:] + run.stderr[-800:]))
    png = TMP / "cli" / "out" / "T_TST_Cli_Normal.png"
    check(png.is_file() and PC.png_header(str(png))[:2] == (64, 32), "CLI wrote no 64 x 32 normal map")
    bad = subprocess.run(base + ["--low", "nope", "--high", "cube_high"], capture_output=True, text=True,
                         timeout=300)
    check(bad.returncode == 2, "a missing object exits %d, expected 2" % bad.returncode)


def test_save_png_writes_grey_alpha_and_rgba():
    d = TMP / "alpha"
    d.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    for ch, colour in ((2, 4), (4, 6)):
        a = rng.random((9, 13, ch))
        for bits in (8, 16):
            p = BAKE["save_png"](str(d / ("c%d_%d.png" % (ch, bits))), a, bits=bits)
            hdr = PC.png_header(p)
            check(hdr[:4] == (13, 9, bits, colour), "%d channels at %d bits: header %s" % (ch, bits, hdr))
            back, _ = PC.read_png(p)                                       # always RGBA
            want = np.dstack([a[:, :, 0]] * 3 + [a[:, :, 1]]) if ch == 2 else a
            err = float(np.abs(back - want).max())
            check(err < (1.01 / 255.0 if bits == 8 else 1e-4), "%d channels at %d bits read back %g off"
                  % (ch, bits, err))
    try:
        BAKE["save_png"](str(d / "five.png"), np.zeros((2, 2, 5)))
        raise AssertionError("5 channels were written")
    except ValueError:
        pass


def test_bake_non_square_map():
    low, high = build_fixture()
    check(BAKE["map_size"]("1024x2048") == (1024, 2048) and BAKE["map_size"](512) == (512, 512),
          "map_size parsing")
    res = BAKE["bake"](low, [high], maps=("normal",), size=(64, 128), out_dir=str(TMP / "tall"), name="T_TST_Tall")
    check(res["report"]["size"] == [64, 128], "report size %s" % res["report"]["size"])
    check(PC.png_header(res["normal"])[:2] == (64, 128), "header %s" % (PC.png_header(res["normal"]),))
    nrm, _ = PC.load(res["normal"])
    flat = sample(nrm, *island_uv(POS_FACE[0], 0.5, 0.5))[:3] * 255.0
    check(np.abs(flat - [127.5, 127.5, 255.0]).max() < 2.5, "flat face texel %s on a 64 x 128 map" % flat)


def test_uniform_cage_follows_the_face_not_the_sharpest_corner():
    """A box with a finely divided top and a 10 mm dome on it: the dome's push is divided by the cosines where it
    stands (1 on the flat top), not by the box corners' 0.577, which used to inflate the push for the whole mesh."""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.4)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=9, use_grid_fill=True)
    low = object_from_bm("dome_low", bm)
    bm = bmesh.new()
    bm.from_mesh(low.data)
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=0.05,
                              matrix=Matrix.Translation((0.0, 0.0, 0.2 - 0.04)))
    high = object_from_bm("dome_high", bm)
    stats = {}
    ext, outside = BAKE["cage_extrusion"](low, [high], stats=stats)
    check(abs(outside - 0.01) < 0.001, "dome stands %.4f out, expected 0.01" % outside)
    check(outside <= ext < 1.3 * outside, "push %.4f for a 0.01 dome on a flat top (0.019 with the corners' cosine)"
          % ext)
    check(abs(stats["max"] - outside) < 1e-9 and 0.0 < stats["p99"] <= stats["max"], "stats %s" % stats)


def object_from_bm(name, bm):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def add_box(bm, lo, hi, cuts=0):
    """A box from lo to hi in bm, its faces divided into a (cuts + 1)^2 grid."""
    verts = bmesh.ops.create_cube(bm, size=1.0)["verts"]
    for v in verts:
        v.co = Vector([lo[k] + (v.co[k] + 0.5) * (hi[k] - lo[k]) for k in range(3)])
    if cuts:
        edges = list({e for v in verts for e in v.link_edges})
        bmesh.ops.subdivide_edges(bm, edges=edges, cuts=cuts, use_grid_fill=True)


# two slabs 12 mm apart, their highs standing 5 mm proud on the facing sides (2 mm between the highs); a 12 mm piping
# cord floating 1 mm over slab A's top
SLAB_A, SLAB_B = ((-0.1, -0.1, 0.0), (0.0, 0.1, 0.1)), ((0.012, -0.1, 0.0), (0.112, 0.1, 0.1))
SIDES = [(ax, sg) for ax in range(3) for sg in (1, -1)]


def slab_cell(part, ax, sg):
    i = part * 6 + SIDES.index((ax, sg))
    return (i % 4) * 0.25 + 0.02, (i // 4) / 3.0 + 0.02, 0.21, 1.0 / 3.0 - 0.04       # u0, v0, du, dv


def build_channel_fixture():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    bm = bmesh.new()
    add_box(bm, *SLAB_A, cuts=7)
    add_box(bm, *SLAB_B, cuts=7)
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        n = f.normal
        ax = max(range(3), key=lambda k: abs(n[k]))
        sg = 1 if n[ax] > 0 else -1
        part = 0 if f.calc_center_median().x < 0.006 else 1
        lo, hi = (SLAB_A, SLAB_B)[part]
        a, b = [k for k in range(3) if k != ax]
        u0, v0, du, dv = slab_cell(part, ax, sg)
        for loop in f.loops:
            s = (loop.vert.co[a] - lo[a]) / (hi[a] - lo[a])
            t = (loop.vert.co[b] - lo[b]) / (hi[b] - lo[b])
            loop[uv].uv = (u0 + s * du, v0 + t * dv)
    low = object_from_bm("channel_low", bm)
    bm = bmesh.new()
    add_box(bm, (-0.1, -0.1, 0.0), (0.005, 0.1, 0.1))
    bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=0.006, radius2=0.006, depth=0.18,
                          matrix=Matrix.Translation((-0.05, 0.0, 0.107)) @ Matrix.Rotation(math.pi / 2, 4, "X"))
    high_a = object_from_bm("channel_high_A", bm)
    bm = bmesh.new()
    add_box(bm, (0.007, -0.1, 0.0), (0.112, 0.1, 0.1))
    high_b = object_from_bm("channel_high_B", bm)
    for p in high_a.data.polygons:
        p.use_smooth = p.center.z > 0.1005                  # the cord smooth, the boxes flat
    return low, [high_a, high_b]


def cell_texels(px, part, ax, sg, inset=2):
    u0, v0, du, dv = slab_cell(part, ax, sg)
    hgt, wid = px.shape[:2]
    c0, c1 = int(u0 * wid) + inset, int((u0 + du) * wid) - inset
    r0, r1 = int((1.0 - v0 - dv) * hgt) + inset, int((1.0 - v0) * hgt) - inset
    return px[r0:r1, c0:c1]


def test_fitted_cage_clears_a_channel_and_keeps_floating_piping():
    low, highs = build_channel_fixture()
    inward = {}
    for label, kw in (("uniform", {"extrusion": 0.010}), ("fitted", {"cage": "fitted"})):
        res = BAKE["bake"](low, highs, maps=("normal",), size=256, out_dir=str(TMP / ("channel_" + label)),
                           name="T_TST_Channel", **kw)
        nrm, _ = PC.load(res["normal"])
        z = nrm[:, :, 2] * 2.0 - 1.0
        inward[label] = sum(int((cell_texels(z, part, 0, sg) < 0.0).sum()) for part, sg in ((0, 1), (1, -1)))
        print("  %s cage: %d inward texels on the facing sides, report %s" % (label, inward[label],
                                                                           {k: res["report"].get(k) for k in
                                                                            ("extrusion", "capped", "repaired",
                                                                             "cage_inside")}))
        if label == "uniform":
            check(res["report"]["cage_inside"]["neighbour"] > 0, "a 10 mm cage across a 2 mm gap reported no ray "
                  "starting inside the neighbour: %s" % res["report"]["cage_inside"])
        else:
            rep = res["report"]
            check(rep["capped"] > 0 and rep["cage_inside"]["neighbour"] == 0 and rep["cage_inside"]["own"] == 0,
                  "fitted report %s" % rep)
            check(0.002 - 1e-9 <= rep["extrusion"]["min"] and rep["extrusion"]["max"] < 0.03, "range %s"
                  % rep["extrusion"])
            top = cell_texels(nrm[:, :, :3] * 2.0 - 1.0, 0, 2, 1)
            check(float(np.abs(top[:, :, 0]).max()) > 0.3,
                  "the floating piping on slab A's top did not bake (max |x| %.2f): the cage stopped under it"
                  % float(np.abs(top[:, :, 0]).max()))
    check(inward["uniform"] > 50, "a 10 mm uniform cage baked only %d inward texels" % inward["uniform"])
    check(inward["fitted"] == 0, "the fitted cage baked %d inward texels" % inward["fitted"])


def test_downsample_filter_steadies_a_sloped_edge():
    """A sharp edge at a slope of 1 in 37, area-sampled 3 x 3 per supersample texel (as Cycles' jittered bake
    samples are), brought down from 2x: where its 50% crossing lands in each column against the true line."""
    f, sub, n = 2, 3, 256
    ys = (np.arange(48 * f * sub) + 0.5) / (f * sub)
    xs = (np.arange(n * f * sub) + 0.5) / (f * sub)
    fine = (ys[:, None] > 20.3 + xs[None, :] / 37.0).astype(np.float32)
    ss = fine.reshape(48 * f, sub, n * f, sub).mean(axis=(1, 3))[:, :, None]

    def error(sigma):
        a = BAKE["downsample"](ss, f, sigma)[:, :, 0]
        cross = []
        for j in range(a.shape[1]):
            i = int(np.argmax(a[:, j] >= 0.5))
            cross.append(i - 0.5 + (0.5 - a[i - 1, j]) / (a[i, j] - a[i - 1, j]))
        e = np.array(cross) - (20.3 + (np.arange(a.shape[1]) + 0.5) / 37.0)
        return float((e - e.mean()).std())

    box, gauss = error(0.0), error(BAKE["FILTER_SIGMA"])
    print("  edge position error: box %.3f, gauss %.3f texels rms" % (box, gauss))
    check(gauss < 0.7 * box, "the Gaussian pre-filter (%.3f) does not steady the edge against a box (%.3f)"
          % (gauss, box))
    flat = BAKE["downsample"](np.full((8, 12, 3), 0.25, np.float32), 2, 0.5)
    check(flat.shape == (4, 6, 3) and np.allclose(flat, 0.25), "a flat image changes under the filter")


def test_bake_refuses_an_excluded_high():
    low, high = build_fixture()
    coll = bpy.data.collections.new("HIGH_excluded")
    bpy.context.scene.collection.children.link(coll)
    for c in high.users_collection:
        c.objects.unlink(high)
    coll.objects.link(high)
    bpy.context.view_layer.layer_collection.children[coll.name].exclude = True
    try:
        BAKE["bake"](low, [high], maps=("normal",), size=32, out_dir=str(TMP / "excluded"))
        raise AssertionError("baked from a high in an excluded collection")
    except ValueError as ex:
        check("not evaluated" in str(ex) and "cube_high" in str(ex), "message: %s" % ex)
    finally:
        bpy.data.collections.remove(coll)


def write_maps(d, smooth):
    """A 0.8 grey base colour and a fully metallic packed map at the given smoothness, as 8-bit PNGs."""
    d.mkdir(parents=True, exist_ok=True)
    base = str(d / "T_TST_Metal_BaseColor.png")
    PC.write_png(base, np.full((8, 8, 3), 0.8, np.float32))
    ms = np.zeros((8, 8, 4), np.float32)
    ms[:, :, 0], ms[:, :, 3] = 1.0, smooth
    msp = str(d / "T_TST_Metal_MetallicSmoothness.png")
    PC.write_png(msp, ms)
    return base, msp


def workbench(objects, png):
    sc = bpy.context.scene
    keep = (sc.render.engine, sc.display.shading.color_type, sc.display.shading.light)
    others = [o for o in sc.objects if o.type in ("MESH", "LIGHT") and o not in objects and not o.hide_render]
    for o in others:
        o.hide_render = True
    cam = bpy.data.objects.new("wb_cam", bpy.data.cameras.new("wb_cam"))
    sc.collection.objects.link(cam)
    cam.location = (0, -4, 1.2)
    cam.rotation_euler = (math.radians(80), 0, 0)
    old_cam = sc.camera
    sc.camera = cam
    try:
        sc.render.engine = "BLENDER_WORKBENCH"
        sc.display.shading.color_type = "TEXTURE"
        sc.display.shading.light = "STUDIO"
        sc.render.resolution_x, sc.render.resolution_y = 160, 90
        sc.render.filepath = png
        bpy.ops.render.render(write_still=True)
    finally:
        sc.render.engine, sc.display.shading.color_type, sc.display.shading.light = keep
        sc.camera = old_cam
        bpy.data.objects.remove(cam)
        for o in others:
            o.hide_render = False


def test_lookdev_shows_roughness_and_workbench_does_not():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    renders = {}
    for smooth in (0.9, 0.1):
        base, ms = write_maps(TMP / ("look%g" % smooth), smooth)
        roles = LOOK["maps_by_role"]([base, ms])
        check(set(roles) == {"base_color", "metallic_smoothness"}, "maps_by_role found %s" % roles)
        mat = LOOK["material_from_maps"]("M_TST_%g" % smooth, **roles)
        obs = LOOK["preview_meshes"](mat)
        look = str(TMP / ("look_%g.png" % smooth))
        used = LOOK["render"](obs, look, size=(160, 90), samples=8)
        wb = str(TMP / ("wb_%g.png" % smooth))
        workbench(obs, wb)
        renders[smooth] = (PC.load(look)[0][:, :, :3], PC.load(wb)[0][:, :, :3])
        for ob in obs:
            me = ob.data
            bpy.data.objects.remove(ob)
            bpy.data.meshes.remove(me)
    look_diff = float(np.abs(renders[0.9][0] - renders[0.1][0]).mean())
    wb_diff = float(np.abs(renders[0.9][1] - renders[0.1][1]).mean())
    print("  look-dev (%s) smooth vs rough metal mean difference %.4f; Workbench %.4f" % (used, look_diff, wb_diff))
    check(look_diff > 0.01, "look-dev renders of smoothness 0.9 and 0.1 barely differ (%.4f)" % look_diff)
    check(wb_diff < 0.002, "Workbench renders differ by %.4f: expected no roughness response" % wb_diff)
    check(bpy.context.scene.render.engine != "CYCLES" or used == "CYCLES", "render engine not restored")


def test_lookdev_cli_renders_maps():
    base, ms = write_maps(TMP / "cli_maps", 0.6)
    png = TMP / "cli_maps" / "look.png"
    run = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1", "--python",
                          str(SCRIPTS / "lookdev_render.py"), "--", "--maps", str(TMP / "cli_maps" / "T_TST_*.png"),
                          "--png", str(png), "--size", "128", "72", "--samples", "4"],
                         capture_output=True, text=True, timeout=300)
    check(run.returncode == 0 and png.is_file(), "CLI exit %d: %s" % (run.returncode, run.stdout[-600:] + run.stderr[-600:]))
    px, _ = PC.load(str(png))
    check(float(px[:, :, :3].mean()) > 0.05, "look-dev render is black")


for fn in (test_bake_normal_ao_curvature,
           test_cage_that_does_not_enclose_bakes_black_ao,
           test_bpy_loader_matches_png_reader,
           test_dithered_8bit_tracks_a_shallow_gradient,
           test_save_png_writes_grey_alpha_and_rgba,
           test_bake_non_square_map,
           test_uniform_cage_follows_the_face_not_the_sharpest_corner,
           test_fitted_cage_clears_a_channel_and_keeps_floating_piping,
           test_downsample_filter_steadies_a_sloped_edge,
           test_bake_refuses_an_excluded_high,
           test_cli_bakes_a_saved_blend,
           test_lookdev_shows_roughness_and_workbench_does_not,
           test_lookdev_cli_renders_maps):
    case(fn)
failed = [r for r in RESULTS if r[0] == "FAIL"]
if not failed:
    shutil.rmtree(TMP, ignore_errors=True)                     # keep the fixtures only when a case failed
print("%d passed, %d failed%s" % (len(RESULTS) - len(failed), len(failed),
                                  " (fixtures kept in %s)" % TMP if failed else ""))
if failed:
    raise SystemExit("FAILED: " + ", ".join(r[1] for r in failed))
