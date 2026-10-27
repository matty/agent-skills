"""Plain-Python tests for the uv-unwrapping skill's scripts/uv_audit.py: the measurement maths on synthetic meshes,
without Blender (the script's measure() needs only numpy).

Host: plain Python 3.9+ with numpy (the tests skip without it). Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_uv_*.py"
"""

import importlib.util
import math
import sys
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "uv-unwrapping" / "scripts" / "uv_audit.py"


def load():
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True            # never leave a __pycache__ in the skill
    try:
        spec = importlib.util.spec_from_file_location("uv_audit_under_test", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = keep


def mesh(verts, faces, uvs, smooth=False, low=None):
    """Flat arrays in uv_audit's layout. Triangles fan from corner 0 (Blender's split of a convex quad)."""
    co = np.asarray(verts, float)
    lv, ls, lt, uv = [], [], [], []
    for f, fu in zip(faces, uvs):
        ls.append(len(lv))
        lt.append(len(f))
        lv += list(f)
        uv += [tuple(p) for p in fu]
    lv, ls, lt = np.array(lv), np.array(ls), np.array(lt)
    fn = []
    for f in faces:
        p = co[f]
        n = sum(np.cross(p[i], p[(i + 1) % len(f)]) for i in range(len(f)))
        fn.append(n / (np.linalg.norm(n) or 1.0))
    fn = np.array(fn)
    if smooth:
        vn = np.zeros_like(co)
        for k, f in enumerate(faces):
            for v in f:
                vn[v] += fn[k]
        vn /= np.maximum(np.linalg.norm(vn, axis=1), 1e-12)[:, None]
        cn = vn[lv]
    else:
        cn = np.repeat(fn, lt, axis=0)
    tri, tpoly = [], []
    for k, f in enumerate(faces):
        for i in range(1, len(f) - 1):
            tri.append((ls[k], ls[k] + i, ls[k] + i + 1))
            tpoly.append(k)
    return {"co": co, "lv": lv, "ls": ls, "lt": lt, "uv": np.array(uv, float), "cn": cn, "tri": np.array(tri),
            "tpoly": np.array(tpoly), "layer": "UVMap", "layers": ["UVMap"],
            "low": None if low is None else np.array(low, bool)}


def quad(x0, y0, x1, y1, z=0.0):
    return [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]


def square_uv(u0, v0, du, dv=None):
    dv = du if dv is None else dv
    return [(u0, v0), (u0 + du, v0), (u0 + du, v0 + dv), (u0, v0 + dv)]


def islands(uv_list):
    """One 1 x 1 m quad per UV square, far apart in 3D: one island each."""
    verts, faces = [], []
    for i in range(len(uv_list)):
        faces.append([4 * i, 4 * i + 1, 4 * i + 2, 4 * i + 3])
        verts += quad(3 * i, 0, 3 * i + 1, 1)
    return mesh(verts, faces, uv_list)


def two_islands_px(map_px, a_right, b_left, width=20):
    """Two square islands, A ending at pixel coordinate a_right and B starting at b_left (pixel centres sit on
    integers, so the real gap is b_left - a_right pixels)."""
    f = lambda px: (px + 0.5) / map_px
    v0, v1 = f(30), f(30 + width)
    return islands([[(f(a_right - width), v0), (f(a_right), v0), (f(a_right), v1), (f(a_right - width), v1)],
                    [(f(b_left), v0), (f(b_left + width), v0), (f(b_left + width), v1), (f(b_left), v1)]])


def strip(us, v0=0.1, v1=0.3, width=1.0):
    """A row of quads along X (one UV island), vertex i at x = i * width with UV u = us[i]."""
    n = len(us) - 1
    verts = [(i * width, 0, 0) for i in range(n + 1)] + [(i * width, 1, 0) for i in range(n + 1)]
    faces, uvs = [], []
    for i in range(n):
        faces.append([i, i + 1, i + 1 + n + 1, i + n + 1])
        uvs.append([(us[i], v0), (us[i + 1], v0), (us[i + 1], v1), (us[i], v1)])
    return mesh(verts, faces, uvs, smooth=True)


@unittest.skipUnless(np is not None, "numpy not installed")
class UvAuditMaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ua = load()

    def m(self, d, **kw):
        return self.ua.measure(d, "t", **kw)

    # ---- canonical numbers (this skill owns them; other skills state the same values)
    def test_canonical_numbers(self):
        ua = self.ua
        self.assertEqual(ua.LIMITS, {"angular_p95": 1.15, "angular_p99": 1.5, "angular_max": 2.0, "area_p95": 0.20,
                                     "texel_cv": 0.15})
        self.assertEqual(ua.TEXEL_BAND["unique"], (0.8, 1.25))
        self.assertEqual(ua.TEXEL_BAND["tiling"], (0.9, 1.1))
        self.assertEqual(ua.TEXEL_BAND["trim"], (0.9, 1.1))
        self.assertEqual(ua.default_pad(1024), 16)
        self.assertEqual(ua.default_pad(2048), 32)
        self.assertEqual(ua.default_pad(128, "lightmap"), 2)
        self.assertIsNone(ua.default_pad(1024, "tiling"))
        self.assertEqual(ua.FOOTPRINT_COVERAGE, 0.85)
        self.assertEqual(ua.LIGHTMAP_GAP_TEXELS, 2)
        self.assertEqual(ua.LIGHTMAP_HARD_ANGLE, 88.0)
        self.assertEqual(ua.map_size("2048x1024"), (2048, 1024))
        self.assertEqual(ua.map_size(512), (512, 512))
        self.assertEqual(ua.map_size("165.2"), (165, 165))          # the validator prints fractional footprints
        self.assertEqual(ua.map_size(165.9), (165, 165))

    def test_footprint_formula(self):
        # measured in Unity 2022.3 on 2026-10-16: a 2 x 3 x 0.2 m wall (14 m2, UV2 box share b 0.850) at 60 texels/m
        # got a 242.8 px square
        self.assertAlmostEqual(self.ua.footprint_px(14.0, 60), 243.5, delta=0.5)
        self.assertAlmostEqual(self.ua.footprint_px(14.0, 60, scale=0.5), 121.8, delta=0.5)
        self.assertAlmostEqual(self.ua.footprint_px(14.0, 60, coverage=1.0), 60 * math.sqrt(14), places=6)
        self.assertAlmostEqual(self.ua.uv_box_share([(0.1, 0.1), (0.6, 0.9)]), 0.4, places=6)

    def test_lightmap_footprint_from_measured_box(self):
        # two 1 x 1 m quads whose UV2 box covers 0.5 x 0.8 of the tile: b 0.4, footprint 20 x sqrt(2 / 0.4)
        d = islands([square_uv(0.1, 0.1, 0.2, 0.3), [(0.4, 0.6), (0.6, 0.6), (0.6, 0.9), (0.4, 0.9)]])
        r = self.m(d, purpose="lightmap", texels_per_m=40, pad_px=0)
        self.assertAlmostEqual(r["uv2_box_share"], 0.4, places=3)
        self.assertAlmostEqual(r["footprint_px"], 40 * math.sqrt(2 / 0.4), places=1)
        self.assertEqual(r["map_px"], [89, 89])                   # rounded down
        # under 64 px: checked as packed for 64 px, with the note (probe-light it or raise its scale)
        r = self.m(d, purpose="lightmap", texels_per_m=20, pad_px=0)
        self.assertAlmostEqual(r["footprint_px"], 20 * math.sqrt(2 / 0.4), places=1)
        self.assertEqual((r["map_px"], r["graded_at_px"]), ([64, 64], 64))
        self.assertTrue(any("under 64" in n and "probe-light" in n for n in r["notes"]), r["notes"])
        with self.assertRaises(ValueError):
            self.m(d, purpose="lightmap")                         # neither a footprint nor texels per metre

    # ---- distortion and density
    def test_density_and_shape(self):
        r = self.m(islands([square_uv(0.25, 0.25, 0.5)]), map_px=1024, px_per_m=512)
        self.assertEqual(r["texel_px_per_m"], 512.0)
        self.assertEqual(r["angular_p95"], 1.0)
        self.assertEqual(r["issues"], [])

    def test_angular_stretch(self):
        r = self.m(islands([square_uv(0.25, 0.25, 0.5, 0.25)]), map_px=1024)
        self.assertAlmostEqual(r["angular_p95"], 2.0, places=3)
        self.assertTrue(any("p95" in i for i in r["issues"]))

    def test_squashed_quad_fails_the_tail_gate(self):
        us = [0.1 + 0.02 * i for i in range(31)]
        for i in range(15, 31):                       # quad 14 squashed to 1/50 of its UV width, 3.3% of the area
            us[i] -= 0.02 - 0.02 / 50
        d = strip(us, width=0.1)
        d["uv"] = d["uv"].astype(np.float32).astype(float)
        r = self.m(d, map_px=1024)
        self.assertLessEqual(r["angular_p95"], 1.15)            # p95 alone would pass it
        self.assertGreater(r["angular_max"], 2.0)
        self.assertGreater(r["angular_p99"], 1.5)
        self.assertTrue(any("a face stretched" in i for i in r["issues"]))
        us = [0.1 + 0.02 * i for i in range(31)]
        for i in range(15, 31):                       # squashed past 1/100 of its island's density: collapsed
            us[i] -= 0.02 - 1e-6
        r = self.m(strip(us, width=0.1), map_px=1024)
        self.assertEqual(r["zero_area_uv_faces"], 1)
        self.assertTrue(any("zero UV area" in i for i in r["issues"]))

    def test_small_faces_at_lightmap_scale_are_not_collapsed(self):
        # a 5 x 5 mm chamfer corner next to a 1 m face, mapped at the same density on a 12 px lightmap footprint:
        # each of its triangles covers 0.00065 px^2 (under the old absolute 0.001 px^2), but it is not collapsed
        verts = quad(0, 0, 1, 1) + quad(2, 0, 2.005, 0.005)
        d = mesh(verts, [[0, 1, 2, 3], [4, 5, 6, 7]], [square_uv(0.05, 0.05, 0.6), square_uv(0.8, 0.8, 0.003)])
        r = self.m(d, purpose="lightmap", map_px=12, pad_px=0)
        tri_px2 = 0.5 * 0.003 ** 2 * 12 ** 2
        self.assertLess(tri_px2, 1e-3)
        self.assertEqual(r["zero_area_uv_faces"], 0)
        self.assertFalse(any("zero UV area" in i for i in r["issues"]), r["issues"])

    def test_collapsed_face_is_zero_area_not_folded(self):
        d = islands([square_uv(0.1, 0.1, 0.3), [(0.6, 0.1), (0.6, 0.2), (0.6, 0.3), (0.6, 0.4)]])
        r = self.m(d, map_px=1024)
        self.assertEqual(r["zero_area_uv_faces"], 1)
        self.assertEqual(r["folded_faces"], 0)

    def test_non_square_map(self):
        d = islands([[(0.1, 0.1), (0.35, 0.1), (0.35, 0.6), (0.1, 0.6)]])   # 1 m square, 0.25 x 0.5 UV
        r = self.m(d, map_px="2048x1024", px_per_m=512)
        self.assertAlmostEqual(r["angular_p95"], 1.0, places=3)
        self.assertEqual(r["texel_px_per_m"], 512.0)
        self.assertEqual(r["issues"], [])
        r = self.m(d, map_px=2048)                     # the same UVs read as a square map: stretched 2x
        self.assertAlmostEqual(r["angular_p95"], 2.0, places=3)

    def test_density_bands_by_purpose(self):
        def issues(f, purpose):
            d = islands([square_uv(0.1, 0.1, 0.5 * f)])
            return [i for i in self.m(d, map_px=1024, px_per_m=512, purpose=purpose)["issues"] if "texel" in i]
        self.assertEqual(issues(1.22, "unique"), [])
        self.assertTrue(issues(1.3, "unique"))
        self.assertTrue(issues(0.79, "unique"))
        self.assertEqual(issues(1.05, "tiling"), [])
        self.assertTrue(issues(1.15, "tiling"))
        self.assertTrue(issues(0.88, "trim"))

    def test_low_density_marks(self):
        d = islands([square_uv(0.1, 0.1, 0.5), square_uv(0.65, 0.1, 0.25)])
        d["low"] = np.array([False, True])
        r = self.m(d, map_px=1024, px_per_m=512)
        self.assertEqual(r["texel_px_per_m"], 512.0)
        self.assertEqual(r["low_density_px_per_m"], 256.0)
        self.assertEqual(r["issues"], [])
        d = islands([square_uv(0.1, 0.1, 0.4), square_uv(0.55, 0.1, 0.4)])
        d["low"] = np.array([False, True])            # marked but not lowered
        r = self.m(d, map_px=1024)
        self.assertTrue(any("not lowered" in i for i in r["issues"]))

    # ---- stacks, mirrors, folds
    def test_stacked_copies(self):
        d = islands([square_uv(0.2, 0.2, 0.3), square_uv(0.2, 0.2, 0.3)])
        r = self.m(d, map_px=1024)
        self.assertEqual((r["stacked_island_pairs"], r["overlapping_island_pairs"]), (1, 0))
        self.assertTrue(r["padding_ok"])
        self.assertEqual(r["issues"], [])
        r = self.m(d, map_px=128, purpose="lightmap")
        self.assertTrue(any("stacked island pairs in a lightmap" in i for i in r["issues"]))

    def test_mirror_modifier_halves_are_a_stack_not_folds(self):
        # x -2..2 merged on the axis; the mirrored half reuses the same UVs (Mirror modifier defaults)
        d = strip([0.1 + 0.2 * abs(x) for x in (-2, -1, 0, 1, 2)])
        r = self.m(d, map_px=1024)
        self.assertEqual(r["folded_faces"], 0)
        self.assertEqual(r["mirror_stacks"], 1)
        self.assertEqual(r["stacked_island_pairs"], 1)
        self.assertEqual(r["issues"], [])
        r = self.m(d, map_px=128, purpose="lightmap")
        self.assertTrue(any("stacked" in i for i in r["issues"]))

    def test_a_real_fold_is_still_reported(self):
        r = self.m(strip([0.1, 0.2, 0.15, 0.25]), map_px=1024)          # the middle quad folds back over the first
        self.assertEqual(r["folded_faces"], 1)
        self.assertEqual(r["mirror_stacks"], 0)
        self.assertTrue(any("folded" in i for i in r["issues"]))

    # ---- bounds
    def test_spill_past_the_tile(self):
        d = islands([[(0.6, 0.1), (1.3, 0.1), (1.3, 0.8), (0.6, 0.8)]])
        r = self.m(d, map_px=1024, px_per_m=716.8)
        self.assertEqual(r["islands_off_tile"], 1)
        self.assertTrue(any("leave the 0-1 tile" in i for i in r["issues"]))
        self.assertEqual(self.m(d, map_px=1024, px_per_m=716.8, purpose="tiling")["issues"], [])
        self.assertTrue(any("outside 0-1" in i for i in self.m(d, map_px=1024, purpose="lightmap")["issues"]))

    def test_whole_tile_bake_copy_is_not_a_spill(self):
        d = islands([square_uv(0.1, 0.1, 0.3), square_uv(1.1, 0.1, 0.3)])   # a stack copy moved +1 in U
        r = self.m(d, map_px=1024)
        self.assertEqual(r["islands_off_tile"], 0)
        self.assertEqual(r["issues"], [])

    # ---- padding
    def test_lightmap_gap_is_supersampled(self):
        r = self.m(two_islands_px(128, 40.94, 41.04), map_px=128, purpose="lightmap")   # 0.1 px apart
        self.assertEqual(r["pad_px"], 2)
        self.assertEqual(r["raster_scale"], 8)
        self.assertFalse(r["padding_ok"])
        self.assertTrue(any("px apart" in i for i in r["issues"]))
        r = self.m(two_islands_px(128, 40.5, 42.7), map_px=128, purpose="lightmap")     # 2.2 px apart
        self.assertTrue(r["padding_ok"])
        self.assertEqual(r["issues"], [])

    def test_default_padding_is_map_over_64(self):
        r = self.m(two_islands_px(1024, 300, 312), map_px=1024)
        self.assertEqual(r["pad_px"], 16)
        self.assertTrue(any("px apart" in i for i in r["issues"]))
        r = self.m(two_islands_px(1024, 300, 317.5), map_px=1024)
        self.assertEqual(r["issues"], [])

    def test_tiling_and_trim_may_overlap(self):
        d = islands([square_uv(0.0, 0.0, 0.5), square_uv(0.25, 0.0, 0.5)])
        for purpose in ("tiling", "trim"):
            self.assertEqual(self.m(d, map_px=1024, purpose=purpose)["issues"], [])
        self.assertTrue(any("partly overlap" in i for i in self.m(d, map_px=1024, pad_px=0)["issues"]))

    def test_shared_atlas(self):
        a = islands([square_uv(0.1, 0.1, 0.3)])
        b = islands([square_uv(0.3, 0.1, 0.3)])
        r = self.ua.measure_shared([("a", a), ("b", b)], map_px=1024)
        self.assertEqual(r["overlapping_pairs_between_objects"], 1)
        self.assertTrue(r["issues"])
        c = islands([square_uv(0.6, 0.1, 0.3)])
        self.assertEqual(self.ua.measure_shared([("a", a), ("c", c)], map_px=1024)["issues"], [])

    # ---- round 2: baking stacks, mirror halves, lightmap chart bends, orientation, trim bands and rows
    def test_baking_flags_stacks_left_inside_the_tile(self):
        d = islands([square_uv(0.2, 0.2, 0.3), square_uv(0.2, 0.2, 0.3)])
        self.assertEqual(self.m(d, map_px=1024)["issues"], [])                    # painted: a stack is fine
        r = self.m(d, map_px=1024, baking=True)
        self.assertTrue(any("inside 0-1 at bake time" in i for i in r["issues"]))
        d = islands([square_uv(0.2, 0.2, 0.3), square_uv(1.2, 0.2, 0.3)])        # the copy moved +1 U
        self.assertEqual(self.m(d, map_px=1024, baking=True)["issues"], [])
        d = strip([0.1 + 0.2 * abs(x) for x in (-2, -1, 0, 1, 2)])                # merged mirror halves
        self.assertTrue(any("bake time" in i for i in self.m(d, map_px=1024, baking=True)["issues"]))

    def test_island_ids_marks_the_flipped_half(self):
        d = strip([0.1 + 0.2 * abs(x) for x in (-2, -1, 0, 1, 2)])
        pa, pb, uv_split, _h, _k = self.ua._edges(d)
        ids, split, flipped = self.ua._island_ids(d, pa, pb, uv_split, self.ua._triangles(d)["au"])
        self.assertEqual(split, 1)
        self.assertEqual(flipped.tolist(), [True, True, False, False])           # the x < 0 half runs backwards

    def test_lightmap_charts_across_a_corner(self):
        verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (1, 1, 1), (0, 1, 1)]
        faces = [[0, 1, 2, 3], [3, 2, 4, 5]]                                      # two faces at 90 deg
        joined = [[(0.1, 0.1), (0.4, 0.1), (0.4, 0.4), (0.1, 0.4)], [(0.1, 0.4), (0.4, 0.4), (0.4, 0.7), (0.1, 0.7)]]
        apart = [joined[0], [(0.6, 0.4), (0.9, 0.4), (0.9, 0.7), (0.6, 0.7)]]
        r = self.m(mesh(verts, faces, joined, smooth=True), map_px=128, purpose="lightmap")
        self.assertEqual(r["chart_bends"], 1)
        self.assertTrue(any("cut the charts" in i for i in r["issues"]))
        r = self.m(mesh(verts, faces, apart, smooth=True), map_px=128, purpose="lightmap")
        self.assertEqual(r["chart_bends"], 0)
        self.assertFalse(any("cut the charts" in i for i in r["issues"]))

    def test_orientation_of_long_islands(self):
        verts = quad(0, 0, 1, 0.25)                                               # a 1 m board, grain along X
        along_v = mesh(verts, [[0, 1, 2, 3]], [[(0.2, 0.1), (0.2, 0.5), (0.1, 0.5), (0.1, 0.1)]])
        along_u = mesh(verts, [[0, 1, 2, 3]], [[(0.1, 0.1), (0.5, 0.1), (0.5, 0.2), (0.1, 0.2)]])
        r = self.m(along_u, map_px=1024, directional=True)
        self.assertEqual((r["elongated_islands"], r["elongated_along_v"]), (1, 0))
        self.assertEqual(r["issues"], [])
        r = self.m(along_v, map_px=1024, directional=True)
        self.assertEqual(r["elongated_along_v"], 1)
        self.assertTrue(any("run along V" in i for i in r["issues"]))
        self.assertFalse(any("run along V" in i for i in self.m(along_v, map_px=1024)["issues"]))   # not asked
        self.assertTrue(any("run along V" in i for i in self.m(along_v, map_px=1024, purpose="trim")["issues"]))

    def test_trim_band_is_per_island(self):
        # two 1 x 0.25 m strips on a 2048 x 1024 sheet: one at 512 px/m, one at 1.15x (the mean, 1.08x, passes)
        verts = quad(0, 0, 1, 0.25) + quad(0, 1, 1, 1.25)
        uvs = [[(0.0, 0.0), (0.25, 0.0), (0.25, 0.125), (0.0, 0.125)],
               [(0.0, 0.25), (0.2875, 0.25), (0.2875, 0.39375), (0.0, 0.39375)]]
        d = mesh(verts, [[0, 1, 2, 3], [4, 5, 6, 7]], uvs)
        r = self.m(d, map_px="2048x1024", px_per_m=512, purpose="trim")
        self.assertLess(r["texel_px_per_m"] / 512, 1.1)
        self.assertEqual(r["islands_off_density"], 1)
        self.assertTrue(any("islands outside 0.90-1.10x" in i for i in r["issues"]))
        self.assertEqual(r["island_px_per_m"], [512.0, 588.8])
        self.assertEqual(r["island_boxes_px"][1], [0.0, 256.0, 588.8, 403.2])

    def test_trim_rows(self):
        verts = quad(0, 0, 1, 0.25)
        inside = mesh(verts, [[0, 1, 2, 3]], [[(0.0, 0.0), (0.25, 0.0), (0.25, 0.125), (0.0, 0.125)]])
        across = mesh(verts, [[0, 1, 2, 3]], [[(0.0, 0.1), (0.25, 0.1), (0.25, 0.225), (0.0, 0.225)]])
        rows = "0-128,128-192"
        self.assertEqual(self.m(inside, map_px="2048x1024", purpose="trim", rows=rows)["islands_across_rows"], 0)
        r = self.m(across, map_px="2048x1024", purpose="trim", rows=rows)
        self.assertEqual(r["islands_across_rows"], 1)
        self.assertTrue(any("cross a trim row edge" in i for i in r["issues"]))

    def test_shared_tiling_overlaps_are_allowed(self):
        a = islands([square_uv(0.1, 0.1, 0.3)])
        b = islands([square_uv(0.3, 0.1, 0.3)])
        for purpose in ("tiling", "trim"):
            self.assertEqual(self.ua.measure_shared([("a", a), ("b", b)], map_px=1024, purpose=purpose)["issues"], [])

    # ---- round 3: lightmap requests, text and decals, unique band per island, exact edge, corner matching
    def test_texels_per_m_means_a_lightmap_audit(self):
        ua = self.ua
        self.assertEqual(ua._purpose(None, texels_per_m=20), "lightmap")
        self.assertEqual(ua._resolve_layer(None, "lightmap"), 1)
        self.assertEqual(ua._resolve_layer(None, "unique"), 0)
        self.assertIsNone(ua._resolve_layer("active", "unique"))
        d = islands([square_uv(0.1, 0.1, 0.3)])
        with self.assertRaises(ValueError):
            self.m(d, purpose="unique", texels_per_m=20)          # it would be ignored: refuse it
        self.assertEqual(self.m(d, purpose=None, texels_per_m=20)["purpose"], "lightmap")

    def test_text_mirrored_and_upside_down(self):
        verts = [(0, 0, 0), (1, 0, 0), (1, 0, 0.5), (0, 0, 0.5)]   # a sign facing -Y, 1 x 0.5 m
        face = [[0, 1, 2, 3]]

        def sign(uv):
            d = mesh(verts, face, [uv])
            d["text"] = np.array([True])
            return d
        upright = sign([(0.1, 0.1), (0.6, 0.1), (0.6, 0.35), (0.1, 0.35)])
        turned = sign([(0.6, 0.35), (0.1, 0.35), (0.1, 0.1), (0.6, 0.1)])     # 180 deg
        mirrored = sign([(0.6, 0.1), (0.1, 0.1), (0.1, 0.35), (0.6, 0.35)])   # U flipped
        self.assertEqual(self.m(upright, map_px=1024, text=True)["issues"], [])
        r = self.m(turned, map_px=1024, text=True)
        self.assertEqual(r["text_islands_not_upright"], 1)
        self.assertTrue(any("letters' up" in i for i in r["issues"]))
        self.assertEqual(self.m(turned, map_px=1024)["issues"], [])                       # not asked
        r = self.m(mirrored, map_px=1024, text=True)
        self.assertEqual(r["text_islands_mirrored"], 1)
        self.assertTrue(any("reads backwards" in i for i in r["issues"]))
        unmarked = mesh(verts, face, [[(0.1, 0.1), (0.6, 0.1), (0.6, 0.35), (0.1, 0.35)]])
        with self.assertRaises(ValueError):
            self.m(unmarked, map_px=1024, text=True)                                     # nothing marked uv_text

    def test_text_scope_poster_crate_strip(self):
        # a portrait poster 0.6 x 0.9 m, upright: text=True and directional=True must agree
        verts = [(0, 0, 0), (0.6, 0, 0), (0.6, 0, 0.9), (0, 0, 0.9)]
        d = mesh(verts, [[0, 1, 2, 3]], [[(0.1, 0.1), (0.4, 0.1), (0.4, 0.55), (0.1, 0.55)]])
        d["text"] = np.array([True])
        r = self.m(d, map_px=1024, directional=True, text=True)
        self.assertEqual(r["issues"], [])
        # a stencilled crate side (marked, upright) beside a vertical post whose grain runs along U (Z on +U)
        side = [(0, 0, 0), (0.6, 0, 0), (0.6, 0, 0.18), (0, 0, 0.18)]
        post = [(0.7, 0, 0), (0.74, 0, 0), (0.74, 0, 0.6), (0.7, 0, 0.6)]
        d = mesh(side + post, [[0, 1, 2, 3], [4, 5, 6, 7]],
                 [[(0.05, 0.05), (0.35, 0.05), (0.35, 0.14), (0.05, 0.14)],
                  [(0.05, 0.40), (0.05, 0.38), (0.35, 0.38), (0.35, 0.40)]])
        d["text"] = np.array([True, False])
        r = self.m(d, map_px=1024, directional=True, text=True)
        self.assertEqual(r["issues"], [])
        self.assertEqual(r["text_islands_not_upright"], 0)
        # a strip mirrored by a Mirror modifier (halves stacked, unmarked) next to a marked upright sign: not judged
        n = 4
        verts = [(x, 0, z) for z in (0, 0.2) for x in (-2, -1, 0, 1, 2)]
        faces, uvs = [], []
        us = [0.1 + 0.1 * abs(x) for x in (-2, -1, 0, 1, 2)]
        for i in range(n):
            faces.append([i, i + 1, i + 6, i + 5])
            uvs.append([(us[i], 0.1), (us[i + 1], 0.1), (us[i + 1], 0.3), (us[i], 0.3)])
        sg = len(verts)
        verts += [(5, 0, 0), (6, 0, 0), (6, 0, 0.5), (5, 0, 0.5)]
        faces.append([sg, sg + 1, sg + 2, sg + 3])
        uvs.append([(0.5, 0.5), (0.9, 0.5), (0.9, 0.7), (0.5, 0.7)])
        d = mesh(verts, faces, uvs)
        d["text"] = np.array([False] * n + [True])
        r = self.m(d, map_px=1024, pad_px=0, text=True)
        self.assertEqual((r["text_islands_mirrored"], r["text_islands_not_upright"]), (0, 0))
        self.assertFalse(any("text" in i for i in r["issues"]), r["issues"])

    def test_text_up_given_per_face(self):
        # letters turned up a pillar: the face is vertical, the letters' tops point along -X (uv_text_up)
        verts = [(0, 0, 0), (0.3, 0, 0), (0.3, 0, 2.0), (0, 0, 2.0)]
        along_u = [(0.1, 0.2), (0.1, 0.11), (0.7, 0.11), (0.7, 0.2)]       # Z on +U, -X on +V (turned, not mirrored)
        along_v = [(0.1, 0.1), (0.19, 0.1), (0.19, 0.7), (0.1, 0.7)]       # Z on +V, X on +U
        for uv, up, ok in ((along_u, (-1, 0, 0), True), (along_v, (-1, 0, 0), False), (along_v, None, True)):
            d = mesh(verts, [[0, 1, 2, 3]], [uv])
            d["text"] = np.array([True])
            if up is not None:
                d["text_up"] = np.array([up], float)
            r = self.m(d, map_px=1024, pad_px=0, text=True)
            self.assertEqual(r["text_islands_not_upright"] == 0, ok, (uv, up, r["issues"]))
        # a floor marking: +Z is its normal, so it has no up until given one
        verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
        d = mesh(verts, [[0, 1, 2, 3]], [square_uv(0.1, 0.1, 0.3)])
        d["text"] = np.array([True])
        r = self.m(d, map_px=1024, pad_px=0, text=True)
        self.assertEqual(r["text_islands_flat"], 1)
        self.assertTrue(any("uv_text_up" in i for i in r["issues"]))
        d["text_up"] = np.array([(0, 1, 0)], float)                         # letters' tops point along +Y
        r = self.m(d, map_px=1024, pad_px=0, text=True)
        self.assertEqual((r["text_islands_flat"], r["text_islands_not_upright"]), (0, 0))

    def test_hard_edge_means_over_half_a_degree(self):
        # two quads sharing an edge, one seam-free island; their corner normals there split by 0.03 deg (the noise a
        # Triangulate with Keep Normals leaves on re-encoded custom normals) or by 1 deg (a real hard edge)
        verts = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0)]
        faces = [[0, 1, 4, 3], [1, 2, 5, 4]]
        uvs = [[(0.1, 0.1), (0.4, 0.1), (0.4, 0.4), (0.1, 0.4)], [(0.4, 0.1), (0.7, 0.1), (0.7, 0.4), (0.4, 0.4)]]
        for deg, hard in ((0.03, 0), (1.0, 1)):
            d = mesh(verts, faces, uvs, smooth=True)
            a = math.radians(deg)
            for li in (5, 6):                                      # face 2's corners on the shared edge (1-4)
                d["cn"][d["ls"][1] + (0 if li == 5 else 3)] = (math.sin(a), 0.0, math.cos(a))
            r = self.m(d, map_px=1024, pad_px=0, baking=True)
            self.assertEqual(r["hard_edges_not_seams"], hard, (deg, r["issues"]))

    def test_lightmap_capacity(self):
        self.assertEqual(self.ua.lightmap_capacity_px(6), 6)          # rizomuv's bound: 6 charts need 6 px
        self.assertEqual(self.ua.lightmap_capacity_px(1), 2)
        self.assertEqual(self.ua.lightmap_capacity_px(65), 18)

    def test_lightmap_box_fill_note(self):
        ua = self.ua
        # Unity's R3: two 2 x 2 m quads whose charts sit in opposite corners, so the box is the whole tile and the
        # charts cover 0.125 of it: the box costs its texels, the charts get tpm x sqrt(0.125)
        d = islands([square_uv(0.0, 0.0, 0.25), square_uv(0.75, 0.75, 0.25)])
        d["co"] = d["co"] * np.array([2.0, 2.0, 1.0])                    # 2 x 2 m quads
        r = self.m(d, purpose="lightmap", texels_per_m=20)               # Unity's 20 texels/m: 56.6 px, under 64
        self.assertAlmostEqual(r["uv2_box_share"], 1.0, places=4)
        self.assertAlmostEqual(r["uv2_box_fill"], 0.125, places=3)
        self.assertAlmostEqual(r["effective_texels_per_m"], 20 * math.sqrt(0.125), places=1)
        self.assertTrue(any("under 64" in n for n in r["notes"]), r["notes"])   # the 2-texel gaps dominate there
        r = self.m(d, purpose="lightmap", texels_per_m=40)               # 113 px: the fill note
        self.assertTrue(any("fill 12%" in n or "fill 13%" in n for n in r["notes"]), r["notes"])
        # one chart filling its box: no note, at any aspect ratio (Unity's R2: 30 x 2 m, chart 1 x 0.125)
        d = mesh(quad(0, 0, 30, 2), [[0, 1, 2, 3]], [[(0, 0), (1, 0), (1, 0.125), (0, 0.125)]])
        r = self.m(d, purpose="lightmap", texels_per_m=20)
        self.assertEqual(r["notes"], [])
        self.assertAlmostEqual(r["footprint_px"], 438.2, delta=0.1)     # Unity measured a 438.0 px tile
        self.assertAlmostEqual(ua.footprint_px(60.0, 20, 1.0, 0.125), 438.18, places=1)

    def test_bakery_footprint(self):
        # Bakery (ftBuildGraphics.cs, read 2026-10-24): a rect of side texels/m x sqrt(2 x area x Scale In Lightmap)
        # on the UV2 box's short side, less its Default packer's 3-texel inset; no LOD factor
        ua = self.ua
        self.assertEqual((ua.BAKERY_AREA_FACTOR, ua.BAKERY_INSET_TEXELS, ua.EFFECTIVE_DENSITY_MIN), (2.0, 3, 0.5))
        self.assertEqual([ua.lightmapper_name(n) for n in (None, "progressive", "Bakery")], ["unity", "unity", "bakery"])
        with self.assertRaises(ValueError):
            ua.lightmapper_name("enlighten")
        side = 20 * math.sqrt(2 * 6.98)                   # the cinema's channelled wall panel: 74.7 px
        self.assertAlmostEqual(ua.footprint_px(6.98, 20, 1.0, 1.0, "bakery"), side - 6, places=9)
        self.assertAlmostEqual(ua.footprint_px(6.98, 20, 1.0, 0.25, "bakery"), (side - 6) / 0.5, places=9)   # square
        self.assertAlmostEqual(ua.footprint_px(6.98, 20, 1.0, 0.25, "bakery", short_side=0.25), (side - 6) / 0.25)
        self.assertAlmostEqual(ua.footprint_px(6.98, 20, 4.0, 1.0, "bakery"), 2 * side - 6, places=9)   # s = 2: S 4
        self.assertEqual(ua.footprint_px(0.001, 20, 1.0, 1.0, "bakery"), 0.0)        # a 0.9 px rect: nothing left
        self.assertEqual((ua.lod_factor(2), ua.lod_factor(2, "bakery")), (0.25, 1.0))
        self.assertAlmostEqual(ua.scale_factor(32, 64), 2.0)
        self.assertAlmostEqual(ua.scale_factor(32, 64, "bakery"), (70 / 38.0) ** 2)
        self.assertAlmostEqual(ua.uv_box_short_side([(0.1, 0.2), (0.9, 0.3)]), 0.1, places=9)
        self.assertAlmostEqual(ua.uv_box_short_side([(-0.5, 0.2), (0.9, 1.5)]), 0.8, places=9)   # clipped to the tile

    def test_bakery_effective_density_gate(self):
        ua = self.ua
        # two 2 x 2 m quads whose charts (0.05 on a side) sit in opposite corners: the box is the whole tile, the
        # charts cover 0.005 of it. Bakery at 40 texels/m: rect 160 px, footprint 154 px, effective density
        # 154 x sqrt(0.005 / 8) = 3.85 texels/m, under half of 40: an issue
        d = islands([square_uv(0.0, 0.0, 0.05), square_uv(0.95, 0.95, 0.05)])
        d["co"] = d["co"] * np.array([2.0, 2.0, 1.0])
        r = self.m(d, purpose="lightmap", texels_per_m=40, lightmapper="bakery")
        self.assertEqual(r["lightmapper"], "bakery")
        self.assertAlmostEqual(r["footprint_px"], 40 * math.sqrt(16) - 6, places=1)
        self.assertAlmostEqual(r["effective_texels_per_m"], 154 * math.sqrt(0.005 / 8), places=2)
        self.assertTrue(any(i.startswith("effective lightmap density 3.9 texels/m, under half the 40 planned")
                            for i in r["issues"]), r["issues"])
        self.assertFalse(any("fill" in n for n in r["notes"]), r["notes"])        # the issue says it once
        unity = self.m(d, purpose="lightmap", texels_per_m=40)                    # Unity: the advisory note only
        self.assertFalse(any("effective lightmap density" in i for i in unity["issues"]), unity["issues"])
        self.assertTrue(any("fill" in n for n in unity["notes"]), unity["notes"])
        # one chart filling its box: no issue; density (154 / 0.9) x sqrt(0.81 / 4) = 77 texels/m
        d = islands([square_uv(0.05, 0.05, 0.9)])
        d["co"] = d["co"] * np.array([2.0, 2.0, 1.0])
        r = self.m(d, purpose="lightmap", texels_per_m=40, lightmapper="bakery")
        self.assertFalse(any("effective" in i for i in r["issues"]), r["issues"])
        self.assertAlmostEqual(r["footprint_px"], (40 * math.sqrt(8) - 6) / 0.9, places=1)
        self.assertAlmostEqual(r["effective_texels_per_m"], (40 * math.sqrt(8) - 6) / 0.9 * 0.45, places=1)
        # Scale In Lightmap 0.25 on purpose plans half the density (sqrt(0.25)): judged against half of 40, not 80.
        # Charts 0.3 on a side in opposite corners at 80 texels/m: rect 160 px, (160 - 6) x sqrt(0.18 / 8) = 23.1
        corners = islands([square_uv(0.0, 0.0, 0.3), square_uv(0.7, 0.7, 0.3)])
        corners["co"] = corners["co"] * np.array([2.0, 2.0, 1.0])
        r = self.m(corners, purpose="lightmap", texels_per_m=80, lightmapper="bakery", lightmap_scale=0.25)
        self.assertAlmostEqual(r["effective_texels_per_m"], 154 * math.sqrt(0.18 / 8), places=1)
        self.assertLess(r["effective_texels_per_m"], 0.5 * 80)                     # under half the scene's 80 ...
        self.assertFalse(any("effective" in i for i in r["issues"]), r["issues"])    # ... but not of its own 40
        # under 64 px the 64 px note governs, as under Unity
        r = self.m(d, purpose="lightmap", texels_per_m=10, lightmapper="bakery")
        self.assertTrue(any("under 64" in n for n in r["notes"]), r["notes"])
        self.assertEqual(r["lod"], 0)
        r1 = self.m(d, purpose="lightmap", texels_per_m=40, lightmapper="bakery", lod=1)
        self.assertEqual(r1["footprint_px"], self.m(d, purpose="lightmap", texels_per_m=40,
                                                    lightmapper="bakery")["footprint_px"])

    def test_lod_scale(self):
        ua = self.ua
        self.assertEqual([ua.lod_level(n) for n in ("KIT_Wall_LOD1", "KIT_Wall_LOD2.001", "KIT_Wall", "KIT_LODGE",
                                                     "KIT_Wall_LOD0")], [1, 2, 0, 0, 0])
        d = islands([square_uv(0.1, 0.1, 0.8)])
        r0 = self.m(d, purpose="lightmap", texels_per_m=20)
        r1 = self.m(d, purpose="lightmap", texels_per_m=20, lod=1)
        r2 = self.m(d, purpose="lightmap", texels_per_m=20, lod=2)
        self.assertAlmostEqual(r1["footprint_px"] / r0["footprint_px"], 0.5, places=2)
        self.assertAlmostEqual(r2["footprint_px"] / r0["footprint_px"], 0.25, places=2)
        self.assertEqual((r0["lod"], r1["lod"], r2["lod"]), (0, 1, 2))

    def test_lightmap_flag_with_another_purpose_raises(self):
        with self.assertRaises(ValueError):
            self.ua._purpose("unique", lightmap=True)
        self.assertEqual(self.ua._purpose(None, lightmap=True), "lightmap")
        self.assertEqual(self.ua._purpose("lightmap", lightmap=True), "lightmap")

    def test_material_subset(self):
        # a tiling plate (material 0, 1024 px/m on a 1024 map: off any 512 band) and a trim strip at 512 px/m
        verts = quad(0, 0, 1, 1) + quad(2, 0, 3, 0.1)
        d = mesh(verts, [[0, 1, 2, 3], [4, 5, 6, 7]],
                 [square_uv(0.0, 0.0, 1.0), [(0.1, 0.1), (0.35, 0.1), (0.35, 0.15), (0.1, 0.15)]])
        d["mat_index"] = np.array([0, 1])
        d["mat_names"] = ["M_Wall", "M_Trim_A"]
        keep = self.ua._material_faces(d, "M_Trim*")
        self.assertEqual(keep.tolist(), [False, True])
        whole = self.m(d, purpose="trim", map_px="2048x1024", px_per_m=512)
        self.assertTrue(whole["issues"])                                    # the plate fails the trim band
        r = self.m(self.ua._subset(d, keep), purpose="trim", map_px="2048x1024", px_per_m=512)
        self.assertEqual((r["faces"], r["issues"]), (1, []))
        r = self.m(self.ua._subset(d, ~keep), purpose="tiling", map_px=1024, px_per_m=1024)
        self.assertEqual((r["faces"], r["issues"]), (1, []))

    def test_unique_band_per_unmarked_island(self):
        # a board end at 0.3x of 512 px/m next to an island at the target: the mean and cv pass, the island does not
        d = islands([square_uv(0.1, 0.1, 0.5), square_uv(0.7, 0.1, 0.15)])
        r = self.m(d, map_px=1024, px_per_m=512)
        self.assertTrue(any("islands outside 0.80-1.25x" in i for i in r["issues"]))
        d["low"] = np.array([False, True])                         # marked: a deliberate drop
        r = self.m(d, map_px=1024, px_per_m=512)
        self.assertFalse(any("islands outside" in i for i in r["issues"]))

    def test_lightmap_edge_margin_is_exact(self):
        f = lambda px: px / 128.0
        d = islands([[(f(0.99), f(10)), (f(20), f(10)), (f(20), f(30)), (f(0.99), f(30))]])  # 0.99 texel to the edge
        r = self.m(d, map_px=128, purpose="lightmap")
        self.assertTrue(any("from the tile edge" in i for i in r["issues"]))
        d = islands([[(f(1.0), f(10)), (f(20), f(10)), (f(20), f(30)), (f(1.0), f(30))]])
        self.assertFalse(any("from the tile edge" in i for i in self.m(d, map_px=128, purpose="lightmap")["issues"]))

    def test_corner_misfit(self):
        rng = np.random.default_rng(1)
        P = rng.random((12, 3))
        a = 0.7
        R = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
        Q = P @ R.T + np.array([3.0, -1.0, 0.5])                   # moved and turned
        self.assertLess(self.ua.corner_misfit(P, Q).max(), 1e-9)
        Q2 = Q.copy()
        Q2[[0, 1]] = Q2[[1, 0]]                                     # two corners swapped: a different order
        self.assertGreater(self.ua.corner_misfit(P, Q2).max(), 1e-3)
        self.assertGreater(self.ua.corner_misfit(P, P * np.array([-1, 1, 1])).max(), 1e-3)   # a mirror image

    # ---- seams vs hard edges
    def test_hard_edges_not_seams(self):
        verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (1, 1, 1), (0, 1, 1)]
        faces = [[0, 1, 2, 3], [3, 2, 4, 5]]                        # a 90 deg fold along the shared edge 2-3
        uvs = [[(0.1, 0.1), (0.4, 0.1), (0.4, 0.4), (0.1, 0.4)], [(0.1, 0.4), (0.4, 0.4), (0.4, 0.7), (0.1, 0.7)]]
        r = self.m(mesh(verts, faces, uvs), map_px=1024, baking=True)
        self.assertEqual(r["hard_edges_not_seams"], 1)
        self.assertTrue(any("hard edges" in i for i in r["issues"]))
        r = self.m(mesh(verts, faces, uvs, smooth=True), map_px=1024, baking=True)
        self.assertEqual(r["hard_edges_not_seams"], 0)

    # ---- tiling phase across joints (tile_uv / tile_phase)
    def test_tile_uv_reads_right_from_the_front_of_every_face(self):
        ua = self.ua
        # seen from the front, a step to the viewer's right raises U and a step up raises V
        for n, right, up in (((0, 1, 0), (-1, 0, 0), (0, 0, 1)), ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
                             ((1, 0, 0), (0, 1, 0), (0, 0, 1)), ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),
                             ((0, 0, 1), (1, 0, 0), (0, 1, 0)), ((0, 0, -1), (-1, 0, 0), (0, 1, 0))):
            forward = -np.asarray(n, float)
            self.assertTrue(np.allclose(np.cross(forward, up), right) or n[2] != 0)       # right = forward x up
            uv = ua.tile_uv([(0, 0, 0), right, up], n, 2.0)
            np.testing.assert_allclose(uv[0], (0, 0), atol=1e-12)                         # phase 0 at the pivot
            np.testing.assert_allclose(uv[1], (0.5, 0), atol=1e-12)
            np.testing.assert_allclose(uv[2], (0, 0.5), atol=1e-12)

    def test_tile_uv_breaks_45_deg_ties_the_same_way_in_float32_and_float64(self):
        ua = self.ua
        n64 = np.array([0.0, -math.sqrt(0.5), math.sqrt(0.5)])
        n32 = n64.astype(np.float32).astype(float) + np.array([0.0, -3e-8, 0.0])        # a float32 normal, a hair off
        p = [(0.3, 0.2, 0.1), (1.3, 0.2, 0.1)]
        np.testing.assert_allclose(ua.tile_uv(p, n64, 1.0), ua.tile_uv(p, n32, 1.0))
        # a 45 deg chamfer strip projected from a float32 normal audits clean against tile_phase's float64 Newell normal
        verts = [(0, -0.1, 3.0), (2, -0.1, 3.0), (2, 0.0, 3.1), (0, 0.0, 3.1)]
        d = mesh(verts, [[0, 1, 2, 3]], [[tuple(ua.tile_uv([v], n32, 1.0)[0]) for v in verts]])
        self.assertEqual(ua.tile_phase(d, 1.0, 1024)["off_faces"], 0)

    def test_tile_steps(self):
        ua = self.ua
        self.assertEqual(ua.tile_steps_issues(1.0, [1.0, 3.0]), [])
        self.assertEqual(ua.tile_steps_issues(0.5, [1.0, 3.0]), [])
        bad = ua.tile_steps_issues(4.0, [1.0, 3.0])                                       # the example spec's EXT
        self.assertEqual(len(bad), 2)
        self.assertIn("not a whole number", bad[0])

    def wall(self, x0, length, uv_fn, height=3.0):
        verts = [(x0, 0, 0), (x0 + length, 0, 0), (x0 + length, 0, height), (x0, 0, height)]
        return mesh(verts, [[0, 1, 2, 3]], [[uv_fn(v) for v in verts]])

    def test_tile_phase(self):
        ua = self.ua
        front = np.array([0.0, -1.0, 0.0])                                               # this quad faces -Y
        ok = self.wall(0, 2.0, lambda v: ua.tile_uv([v], front, 1.0)[0] + (3, -2))        # whole tiles off: fine
        r = ua.tile_phase(ok, 1.0, 1024)
        self.assertEqual((r["off_faces"], r["mirrored_faces"], r["issues"]), (0, 0, []), r)
        # Cube Projection centred on a 2 m piece's bounds: half a tile off
        centred = self.wall(0, 2.0, lambda v: ((v[0] - 1.0) / 1.0 + 0.5, (v[2] - 1.5) / 1.0 + 0.5))
        r = ua.tile_phase(centred, 1.0, 1024)
        self.assertEqual(r["off_faces"], 1)
        self.assertAlmostEqual(r["phase_px_max"], 512.0, delta=1e-6)
        mirrored = self.wall(0, 2.0, lambda v: (-v[0] / 1.0 + 0.25, v[2]))
        mirrored["uv"][:, 0] -= 0.25                                                      # U = -x: backwards
        r = ua.tile_phase(mirrored, 1.0, 1024)
        self.assertEqual(r["mirrored_faces"], 1)
        self.assertIn("mirrored", r["issues"][0])
        # a piece rotated 90 deg about Z and moved: its own frame brings it back
        rot = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
        moved = self.wall(0, 2.0, lambda v: ua.tile_uv([v], front, 1.0)[0])
        moved["co"] = moved["co"] @ rot.T + np.array([5.0, 7.0, 0.0])
        r = ua.tile_phase(moved, 1.0, 1024, frame=(rot, (5.0, 7.0, 0.0)), steps=[1.0, 3.0])
        self.assertEqual((r["off_faces"], r["issues"]), (0, []), r)
        # a mirrored frame is reported, not measured as if it were not
        r = ua.tile_phase(moved, 1.0, 1024, frame=(rot @ np.diag([-1.0, 1.0, 1.0]), (5.0, 7.0, 0.0)))
        self.assertIsNone(r["off_faces"])
        self.assertIn("mirrored (negative scale)", r["issues"][-1])
        # a phase variant: projected as if 1 m along a 2 m tile; audited with its offset it passes, without it not
        variant = self.wall(0, 1.0, lambda v: ua.tile_uv([np.add(v, (1.0, 0, 0))], front, 2.0)[0])
        self.assertEqual(ua.tile_phase(variant, 2.0, 1024, offset=(1.0, 0, 0))["off_faces"], 0)
        self.assertEqual(ua.tile_phase(variant, 2.0, 1024)["off_faces"], 1)


if __name__ == "__main__":
    unittest.main()
