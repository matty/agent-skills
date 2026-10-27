"""Plain-Python tests for the rizomuv-uv-pipeline skill's scripts/uv_metrics.py: distortion, texel density, overlap,
padding, margin, flips, the one grader (distortion gate merged over the defaults, plus layout) and the visible-seam
measure (cushion-like prisms with seams across the top, underneath, at the back and on sharp or rounded edges), on
synthetic layouts. No RizomUV, no Blender.

Host: plain Python 3.9+ with numpy (the tests skip without it). Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_rizomuv_*.py"
"""

import json
import math
import sys
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "rizomuv-uv-pipeline" / "scripts"


def load(name):
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True            # never leave a __pycache__ in the skill
    try:
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        return __import__(name)
    finally:
        sys.dont_write_bytecode = keep


def quads(polys_xyz, polys_uv):
    """Mesh arrays with each polygon its own UV island (3D vertices shared by position)."""
    xyz, xid, uvw, uid, sizes, vmap = [], [], [], [], [], {}
    for P, U in zip(polys_xyz, polys_uv):
        sizes.append(len(P))
        for p, u in zip(P, U):
            k = tuple(round(c, 9) for c in p)
            if k not in vmap:
                vmap[k] = len(vmap)
                xyz.extend(p)
            xid.append(vmap[k])
            uid.append(len(uvw) // 3)
            uvw.extend((u[0], u[1], 0.0))
    return {"sizes": sizes, "xyz_ids": xid, "xyz": xyz, "uvw_ids": uid, "uvw": uvw}


A = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
B = [(2, 0, 0), (3, 0, 0), (3, 1, 0), (2, 1, 0)]


def sq(x, y, s):
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s)]


@unittest.skipUnless(np is not None, "numpy is not installed")
class Measures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.um = load("uv_metrics")

    def report(self, m, **kw):
        kw.setdefault("pad_px", 16)
        kw.setdefault("margin_px", 8)
        return self.um.report(m, m["uvw_ids"], m["uvw"], kw.pop("map_px", 1024), **kw)

    def test_unit_quad_is_undistorted_at_half_density(self):
        r = self.report(quads([A], [sq(0.25, 0.25, 0.5)]))
        self.assertEqual(r["distortion"]["angular_p95"], 1.0)
        self.assertEqual(r["distortion"]["area_local_p95"], 0.0)
        self.assertAlmostEqual(r["texel"]["px_per_unit_mean"], 512.0)
        self.assertAlmostEqual(r["coverage"], 0.25, places=2)
        self.assertEqual(self.um.grade(r), [])

    def test_small_stretched_island_fails_on_its_own(self):
        """A 15 cm label (2.2% of the area) stretched 1.45x in its own island passes the whole-object p95, p99 and
        max; the per-island p95 fails it."""
        s = 1.45 ** 0.5
        lab = [(5, 0, 0), (5.15, 0, 0), (5.15, 0.15, 0), (5, 0.15, 0)]
        u = [(0.6, 0.6), (0.6 + 0.075 * s, 0.6), (0.6 + 0.075 * s, 0.6 + 0.075 / s), (0.6, 0.6 + 0.075 / s)]
        r = self.report(quads([A, lab], [sq(0.05, 0.05, 0.5), u]))
        d = r["distortion"]
        self.assertEqual(d["angular_p95"], 1.0)
        self.assertLess(d["angular_p99"], 1.5)
        self.assertAlmostEqual(d["island_angular_p95"], 1.45, places=2)
        self.assertTrue(any(f.startswith("island_angular_p95") for f in self.um.grade(r)), self.um.grade(r))

    def test_two_to_one_stretch_reads_angular_two(self):
        m = quads([A], [[(0.1, 0.1), (0.5, 0.1), (0.5, 0.3), (0.1, 0.3)]])
        d = self.um.distortion(m, m["uvw_ids"], m["uvw"])
        self.assertAlmostEqual(d["angular_p95"], 2.0, places=3)
        self.assertTrue(any(f.startswith("angular_p95") for f in self.um.check_gate(d)))

    def test_concave_star_fills_exactly_its_area(self):
        star = [((1.0 if k % 2 == 0 else 0.4) * math.cos(math.pi * k / 5),
                 (1.0 if k % 2 == 0 else 0.4) * math.sin(math.pi * k / 5), 0.0) for k in range(10)]
        m = quads([star], [[(0.5 + 0.45 * p[0], 0.5 + 0.45 * p[1]) for p in star]])
        r = self.report(m)
        a3, a2 = self.um.polygon_areas(m, m["uvw_ids"], m["uvw"])
        self.assertAlmostEqual(float(a2[0] / a3[0]), 0.45 ** 2, places=9)
        self.assertEqual(r["overlap_px"], 0)
        self.assertEqual(r["distortion"]["angular_max"], 1.0)

    def test_stacked_islands_overlap_and_fail_the_layout(self):
        r = self.report(quads([A, B], [sq(0.1, 0.1, 0.3), sq(0.1, 0.1, 0.3)]))
        self.assertGreater(r["overlap_px"], 0)
        self.assertTrue(any(f.startswith("overlap") for f in self.um.grade(r)))
        self.assertTrue(any(f.startswith("padding") for f in self.um.grade(r)))

    def test_mirrored_island_counts_as_flipped(self):
        m = quads([A, B], [sq(0.1, 0.1, 0.3), [(0.8, 0.1), (0.5, 0.1), (0.5, 0.4), (0.8, 0.4)]])
        self.assertEqual(self.um.flipped_polygons(m, m["uvw_ids"], m["uvw"]), 1)
        self.assertIn("1 flipped polygon(s)", self.um.grade(self.report(m)))

    def test_nan_uvs_fail_once_and_keep_the_report_json_safe(self):
        m = quads([A, B], [[(0.1, 0.1), (0.4, 0.1), (float("nan"), 0.4), (0.1, 0.4)], sq(0.6, 0.6, 0.3)])
        r = self.report(m)
        fails = self.um.grade(r)
        self.assertEqual(sum(f.startswith("non-finite") for f in fails), 1)
        self.assertIsNone(r["margin_px_min"])
        json.dumps(self.um.json_safe(r), allow_nan=False)            # strict JSON: no NaN or Infinity

    def test_zero_area_faces_are_ignored_and_an_all_zero_mesh_raises(self):
        Z = [(5, 0, 0), (6, 0, 0), (7, 0, 0), (5.5, 0, 0)]
        m = quads([A, Z], [sq(0.1, 0.1, 0.3), sq(0.6, 0.6, 0.1)])
        self.assertEqual(self.report(m)["distortion"]["angular_p95"], 1.0)
        z = quads([Z], [sq(0.6, 0.6, 0.1)])
        with self.assertRaises(ValueError):
            self.um.distortion(z, z["uvw_ids"], z["uvw"])
        with self.assertRaises(ValueError):
            self.um.texel_density(z, z["uvw_ids"], z["uvw"], 1024)

    def test_texel_density_matches_the_linear_ratio(self):
        ru = load("rizom_uv")
        m = quads([A, B], [sq(0.1, 0.1, 0.3), sq(0.5, 0.1, 0.3)])
        td = self.um.texel_density(m, m["uvw_ids"], m["uvw"], 1024)["px_per_unit_mean"]
        self.assertAlmostEqual(td, ru.linear_ratio(m, m["uvw_ids"], m["uvw"]) * 1024, places=2)


@unittest.skipUnless(np is not None, "numpy is not installed")
class Padding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.um = load("uv_metrics")

    def gaps(self, gap_px, pad_px, tol=0.5):
        g = gap_px / 1024.0
        m = quads([A, B], [sq(0.1, 0.1, 0.3), sq(0.4 + g, 0.1, 0.3)])
        return self.um.padding_gaps(m, m["uvw_ids"], m["uvw"], 1024, pad_px, tol)

    def test_gap_below_padding_is_counted_and_measured(self):
        r = self.gaps(10, 16)
        self.assertEqual(r["pairs_below_min"], 1)
        self.assertAlmostEqual(r["min_gap_px"], 10.0, places=6)

    def test_gap_near_padding_is_measured_exactly(self):
        r = self.gaps(10, 8)
        self.assertEqual(r["pairs_below_min"], 0)
        self.assertAlmostEqual(r["min_gap_px"], 10.0, places=6)

    def test_far_apart_islands_give_none_not_infinity(self):
        r = self.gaps(10, 2)                                  # 10 px is beyond 2 x pad: not measured
        self.assertIsNone(r["min_gap_px"])
        self.assertEqual(r["pairs_below_min"], 0)
        m = quads([A], [sq(0.1, 0.1, 0.3)])
        self.assertIsNone(self.um.padding_gaps(m, m["uvw_ids"], m["uvw"], 1024, 8)["min_gap_px"])

    def test_strict_tolerance_for_lightmap_texels(self):
        self.assertEqual(self.gaps(15.8, 16, tol=0.5)["pairs_below_min"], 0)   # grid tolerance for UV0
        self.assertEqual(self.gaps(15.8, 16, tol=0.0)["pairs_below_min"], 1)   # strict for lightmap texels

    def test_margin_is_checked_against_what_was_asked(self):
        m = quads([A], [sq(0.0, 0.0, 0.3)])
        r = self.um.report(m, m["uvw_ids"], m["uvw"], 1024, pad_px=16, margin_px=8)
        self.assertFalse(r["margin_ok"])
        self.assertTrue(any(f.startswith("margin") for f in self.um.grade(r)))


@unittest.skipUnless(np is not None, "numpy is not installed")
class Gate(unittest.TestCase):
    BAD = {"angular_p95": 1.10, "angular_p99": 9.0, "angular_max": 40.0, "area_local_p95": 0.9,
           "island_angular_p95": 1.10, "island_area_local_p95": 0.0, "area_local_max": 0.0,
           "area_global_mean": 0.6, "islands": 80, "faces": 100, "islands_per_100_faces": 80.0, "finite": True}

    @classmethod
    def setUpClass(cls):
        cls.um = load("uv_metrics")

    def test_canonical_values(self):
        self.assertEqual(self.um.GATE, {"angular_p95": 1.15, "angular_p99": 1.5, "angular_max": 2.0,
                                        "area_local_p95": 0.20, "island_angular_p95": 1.15,
                                        "island_area_local_p95": 0.20, "area_local_max": 2.0,
                                        "area_global_mean": 0.05, "islands_per_100_faces": 25.0})
        self.assertEqual(self.um.ISLAND_MIN_SHARE, 0.005)
        self.assertEqual(self.um.FRAGMENT_FREE_ISLANDS, 12)

    def test_partial_gate_merges_over_the_defaults(self):
        full = self.um.check_gate(self.BAD)
        partial = self.um.check_gate(self.BAD, {"angular_p95": 1.2})
        self.assertEqual(len(full), 5)
        self.assertEqual(partial, full)                       # loosening one key keeps every other check

    def test_infinity_switches_a_check_off(self):
        fails = self.um.check_gate(self.BAD, {"angular_max": float("inf")})
        self.assertFalse(any(f.startswith("angular_max") for f in fails))
        self.assertEqual(len(fails), 4)

    def test_fragmentation_skipped_for_twelve_islands_or_fewer(self):
        d = dict(self.BAD, angular_p99=1.0, angular_max=1.0, area_local_p95=0.0, area_global_mean=0.0,
                 islands=12, faces=12, islands_per_100_faces=100.0)
        self.assertEqual(self.um.check_gate(d), [])

    def test_bad_gates_fail_at_once(self):
        with self.assertRaises(TypeError):
            self.um.check_gate(self.BAD, 1.3)
        with self.assertRaises(ValueError):
            self.um.merge_gate({"angular_p59": 1.2})                  # a typo names the valid keys
        with self.assertRaises(TypeError):
            self.um.merge_gate({"angular_p95": "1.2"})

    def test_partial_gate_carries_to_the_island_twin(self):
        g = self.um.merge_gate({"angular_p95": 1.3})                    # as uv_audit judges both with one limit
        self.assertEqual((g["angular_p95"], g["island_angular_p95"], g["island_area_local_p95"]), (1.3, 1.3, 0.20))
        g = self.um.merge_gate({"angular_p95": 1.3, "island_angular_p95": 1.2})
        self.assertEqual(g["island_angular_p95"], 1.2)

    def test_coverage_floor(self):
        self.assertEqual(self.um.MIN_FILL_COVERAGE, 0.35)
        rep = {"distortion": dict(self.BAD, angular_p99=1.0, angular_max=1.0, area_local_p95=0.0,
                                  area_global_mean=0.0, islands=6, islands_per_100_faces=0.0), "coverage": 0.12}
        self.assertEqual(self.um.grade(rep), [])
        self.assertEqual(self.um.grade(rep, min_coverage=0.35), ["coverage 0.120 < 0.350"])
        many = dict(rep, islands=150)                            # hundreds of islands: the gaps take the tile
        self.assertEqual(self.um.grade(many, min_coverage=0.35), [])
        self.assertEqual(self.um.coverage_floor(dict(rep, islands=100)), 0.35)


def box(dx, dy, dz):
    """A closed box dx x dy x dz as six quads (each its own island; UVs = a corner of the tile, unused here)."""
    c = [(x * dx, y * dy, z * dz) for z in (0, 1) for y in (0, 1) for x in (0, 1)]
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    return quads([[c[i] for i in f] for f in faces], [sq(0.1 * k, 0.1, 0.05) for k in range(6)])


@unittest.skipUnless(np is not None, "numpy is not installed")
class ThinPieces(unittest.TestCase):
    """A long thin piece cannot fill a square tile: the coverage floor follows what its shape allows."""

    @classmethod
    def setUpClass(cls):
        cls.um = load("uv_metrics")

    def test_shape_limit(self):
        self.assertAlmostEqual(self.um.shape_coverage_limit(box(3.0, 0.12, 0.12)), 1.4688 / 9.0288, places=4)
        self.assertAlmostEqual(self.um.shape_coverage_limit(box(1.2, 0.15, 0.03)), 0.441 / 1.4634, places=4)
        self.assertEqual(self.um.shape_coverage_limit(box(1, 1, 1)), 1.0)

    def test_floor_drops_only_for_thin_pieces(self):
        beam = {"distortion": {"finite": True, "islands": 6}, "shape_coverage_limit": 0.1627}
        self.assertAlmostEqual(self.um.coverage_floor(beam), 0.8 * 0.1627)
        self.assertEqual(self.um.grade(dict(beam, coverage=0.158), distortion=False, min_coverage=0.35), [])
        self.assertEqual(self.um.grade(dict(beam, coverage=0.10), distortion=False, min_coverage=0.35),
                         ["coverage 0.100 < 0.130"])
        cube = {"distortion": {"finite": True, "islands": 6}, "shape_coverage_limit": 1.0, "coverage": 0.22}
        self.assertEqual(self.um.grade(cube, distortion=False, min_coverage=0.35), ["coverage 0.220 < 0.350"])

    def test_limit_is_per_connected_shell(self):
        a, b, c = box(1, 1, 1), box(1, 1, 1), box(1, 1, 1)
        for m, dx in ((b, 5.0), (c, 10.0)):                           # three cubes 5 m apart in one object
            m["xyz"] = [v + (dx if i % 3 == 0 else 0.0) for i, v in enumerate(m["xyz"])]
        n = len(a["xyz"]) // 3
        three = {"sizes": a["sizes"] * 3, "xyz": a["xyz"] + b["xyz"] + c["xyz"],
                 "xyz_ids": a["xyz_ids"] + [i + n for i in b["xyz_ids"]] + [i + 2 * n for i in c["xyz_ids"]]}
        nu = len(a["uvw"]) // 3
        three["uvw"] = a["uvw"] + b["uvw"] + c["uvw"]
        three["uvw_ids"] = a["uvw_ids"] + [i + nu for i in b["uvw_ids"]] + [i + 2 * nu for i in c["uvw_ids"]]
        self.assertEqual(self.um.shape_coverage_limit(three), 1.0)      # was 18 / 11^2 = 0.15 over the whole object

    def test_report_carries_the_limit(self):
        m = box(3.0, 0.12, 0.12)
        rep = self.um.report(m, m["uvw_ids"], m["uvw"], 1024)
        self.assertAlmostEqual(rep["shape_coverage_limit"], 0.1627, places=4)


@unittest.skipUnless(np is not None, "numpy is not installed")
class Fragmentation(unittest.TestCase):
    """Fragmentation counts per connected shell: many boxes are fine, one shell in confetti is not."""

    @classmethod
    def setUpClass(cls):
        cls.um = load("uv_metrics")

    def strip(self, n, x0=0.0, separate=False):
        """n unit quads in a row; separate=True gives each its own vertices (n shells)."""
        P = [[(x0 + i + (0.5 * i if separate else 0), 0, 0), (x0 + i + 1 + (0.5 * i if separate else 0), 0, 0),
              (x0 + i + 1 + (0.5 * i if separate else 0), 1, 0), (x0 + i + (0.5 * i if separate else 0), 1, 0)]
             for i in range(n)]
        U = [sq(0.02 + (i % 10) * 0.095, 0.02 + (i // 10) * 0.095, 0.08) for i in range(n)]
        return quads(P, U)

    def test_many_small_shells_are_not_fragmented(self):
        m = self.strip(30, separate=True)                       # 30 shells, one island each (a crate of planks)
        d = self.um.distortion(m, m["uvw_ids"], m["uvw"])
        self.assertEqual((d["shells"], d["islands"], d["islands_per_100_faces"]), (30, 30, 0.0))
        self.assertEqual(d["islands_per_100_faces_all"], 100.0)
        self.assertFalse(any(f.startswith("islands_per_100_faces") for f in self.um.check_gate(d)))

    def test_one_shell_cut_into_confetti_is_fragmented(self):
        cut = self.strip(30)                                    # one connected flat strip, every quad its own island
        seed = dict(cut, uvw_ids=list(cut["xyz_ids"]), uvw=list(cut["xyz"]))     # no seams marked
        d = self.um.distortion(seed, cut["uvw_ids"], cut["uvw"])
        self.assertEqual((d["shells"], d["islands"]), (1, 30))
        self.assertAlmostEqual(d["islands_per_100_faces"], 100.0 * 29 / 30, places=2)   # 29 beyond its 1 region
        self.assertTrue(any(f.startswith("islands_per_100_faces") for f in self.um.check_gate(d)))

    def test_islands_that_follow_planar_regions_are_not_confetti(self):
        cut = self.strip(30)                                    # every quad its own island, each one seamed off,
        d = self.um.distortion(cut, cut["uvw_ids"], cut["uvw"])  # like a mitred frame's faces
        self.assertEqual((d["islands"], d["islands_per_100_faces"]), (30, 0.0))

    def test_planar_regions(self):
        b = box(1, 1, 1)
        seamless = dict(b, uvw_ids=list(b["xyz_ids"]), uvw=list(b["xyz"]))
        self.assertEqual(len(set(self.um.planar_regions(seamless).tolist())), 6)          # 90 deg > 40
        self.assertEqual(len(set(self.um.planar_regions(seamless, 100.0).tolist())), 1)
        flat = self.strip(30)
        self.assertEqual(len(set(self.um.planar_regions(flat).tolist())), 30)            # seams everywhere
        joined = dict(flat, uvw_ids=list(flat["xyz_ids"]), uvw=list(flat["xyz"]))
        self.assertEqual(len(set(self.um.planar_regions(joined).tolist())), 1)

    def test_bbox_share(self):
        m = quads([A, B], [sq(0.1, 0.1, 0.3), sq(0.5, 0.5, 0.3)])
        self.assertAlmostEqual(self.um.bbox_share(m["uvw_ids"], m["uvw"]), 0.7 * 0.7)


def rect_profile(D, H, n):
    """A D x H rectangle in (y, z), counter-clockwise (y right, z up), each side in n segments: bottom, back (+y),
    top, front (-y). Returns the points and each segment's side name."""
    corners = [(-D / 2, 0.0), (D / 2, 0.0), (D / 2, H), (-D / 2, H)]
    pts, side = [], []
    for k, name in enumerate(("bottom", "back", "top", "front")):
        (y0, z0), (y1, z1) = corners[k], corners[(k + 1) % 4]
        for t in range(n):
            pts.append((y0 + (y1 - y0) * t / n, z0 + (z1 - z0) * t / n))
            side.append(name)
    return pts, side


def rounded_profile(D, H, r, k, n=4):
    """A D x H rectangle with its four corners rounded at radius r in k segments, counter-clockwise; the flat sides
    in n segments. Segment names: bottom, back, top, front, and round_<corner> with the arc step."""
    pts, side = [], []
    flats = [((-D / 2 + r, 0.0), (D / 2 - r, 0.0), "bottom"), ((D / 2, r), (D / 2, H - r), "back"),
             ((D / 2 - r, H), (-D / 2 + r, H), "top"), ((-D / 2, H - r), (-D / 2, r), "front")]
    centres = [(D / 2 - r, r), (D / 2 - r, H - r), (-D / 2 + r, H - r), (-D / 2 + r, r)]
    for c, ((y0, z0), (y1, z1), name) in enumerate(flats):
        for t in range(n):
            pts.append((y0 + (y1 - y0) * t / n, z0 + (z1 - z0) * t / n))
            side.append(name)
        cy, cz = centres[c]
        a0 = -math.pi / 2 + c * math.pi / 2                    # the arc after this flat side
        for t in range(k):
            a = a0 + (math.pi / 2) * t / k
            pts.append((cy + r * math.cos(a), cz + r * math.sin(a)))
            side.append("round%d_%d" % (c, t))
    return pts, side


def prism(profile, L, nx, label, seed_label=None):
    """The (y, z) profile extruded along x from 0 to L in nx steps, closed by n-gon caps, outward normals. label(side,
    j) names each side quad's island (j: its step along x); faces with one name share UV vertices, so the seams fall
    between names. seed_label the same for the seams marked in the seed topology (None: no seams marked). Returns
    (mesh with that seed, layout uvw_ids, layout uvw)."""
    pts, side = profile
    n = len(pts)
    xyz = [(L * j / nx, y, z) for j in range(nx + 1) for y, z in pts]
    vid = lambda i, j: j * n + (i % n)
    faces, names, seeds = [], [], []
    for j in range(nx):
        for i in range(n):
            faces.append([vid(i, j), vid(i + 1, j), vid(i + 1, j + 1), vid(i, j + 1)])
            names.append(label(side[i], j))
            seeds.append(seed_label(side[i], j) if seed_label else 0)
    faces += [[vid(i, 0) for i in reversed(range(n))], [vid(i, nx) for i in range(n)]]
    names += ["cap0", "cap1"]
    seeds += ["cap0", "cap1"] if seed_label else [0, 0]

    def layout(lab):
        ids, uvw, key, order = [], [], {}, {}
        for f, l in zip(faces, lab):
            k = order.setdefault(l, len(order))
            for v in f:
                if (v, l) not in key:
                    key[(v, l)] = len(key)
                    x, y, z = xyz[v]
                    uvw.extend((0.05 * x + 0.1 * k, 0.05 * (y + z), 0.0))
                ids.append(key[(v, l)])
        return ids, uvw
    sid, suvw = layout(seeds)
    mesh = {"sizes": [len(f) for f in faces], "xyz_ids": [v for f in faces for v in f],
            "xyz": [c for p in xyz for c in p], "uvw_ids": sid, "uvw": suvw}
    ids, uvw = layout(names)
    return mesh, ids, uvw


@unittest.skipUnless(np is not None, "numpy is not installed")
class VisibleSeams(unittest.TestCase):
    """Seams through smooth surface that faces up or to the front (-Y): the grade cannot see them (issue #5)."""

    @classmethod
    def setUpClass(cls):
        cls.um = load("uv_metrics")

    def cushion(self, cut=None, **kw):
        """A 0.6 x 0.6 x 0.15 m box cushion (x = width), each side its own island; cut=<side> splits that side
        across at x = 0.3."""
        return prism(rect_profile(0.6, 0.15, 6), 0.6, 6, lambda s, j: s + ("A" if s == cut and j < 3 else ""), **kw)

    def seams(self, mesh, ids, uvw, **kw):
        return self.um.visible_seams(mesh, ids, uvw, **kw)

    def test_canonical_thresholds(self):
        self.assertEqual((self.um.SMOOTH_SEAM_DEG, self.um.VIEW_FACING), (15.0, 0.5))
        self.assertEqual(self.um.VIEW_DIRS, ((0.0, 0.0, 1.0), (0.0, -1.0, 0.0)))     # up and the kit's front
        self.assertEqual((self.um.VISIBLE_SEAM_NOTE_M, self.um.VISIBLE_SEAM_NOTE_SHARE), (0.25, 0.25))

    def test_a_cut_across_the_top_is_visible(self):
        s = self.seams(*self.cushion("top"))
        self.assertAlmostEqual(s["visible_seam_m"], 0.6)
        self.assertAlmostEqual(s["visible_seam_unmarked_m"], 0.6)
        self.assertAlmostEqual(s["smooth_seam_m"], 0.6)
        self.assertAlmostEqual(s["seam_m"], 4 * 0.6 + 2 * 1.5 + 0.6)          # the box edges and caps are seams too
        self.assertEqual(s["visible_seam_bounds"], [[0.3, -0.3, 0.15], [0.3, 0.3, 0.15]])

    def test_seams_on_sharp_edges_underneath_or_at_the_back_are_not(self):
        for cut in (None, "bottom", "back"):
            s = self.seams(*self.cushion(cut))
            self.assertEqual(s["visible_seam_m"], 0.0, cut)
            self.assertAlmostEqual(s["smooth_seam_m"], {None: 0.0, "bottom": 0.6, "back": 0.15}[cut], msg=cut)
            self.assertIsNone(s["visible_seam_bounds"])

    def test_the_front_counts_and_the_view_directions_can_change(self):
        mesh, ids, uvw = self.cushion("front")
        self.assertAlmostEqual(self.seams(mesh, ids, uvw)["visible_seam_m"], 0.15)
        self.assertEqual(self.seams(mesh, ids, uvw, view_dirs=((0, 0, 1),))["visible_seam_m"], 0.0)
        self.assertAlmostEqual(self.seams(*self.cushion("back"), view_dirs=None)["visible_seam_m"], 0.15)  # all round

    @staticmethod
    def welt(k):
        """Top panel = the top and the upper half of both top rounds; the rest is the band: welts at 45 deg."""
        def label(side, j):
            arc, _, t = side.partition("_")
            upper = (arc == "round2" and int(t) < k // 2) or (arc == "round1" and int(t) >= k // 2)
            return "panel" if side == "top" or upper else "band"
        return label

    def test_a_welt_on_a_rounded_edge_is_smooth_only_when_the_round_is(self):
        for k, want in ((8, 1.2), (2, 0.0)):       # 11.25 deg steps are smooth, 45 deg steps are an edge
            s = self.seams(*prism(rounded_profile(0.6, 0.15, 0.05, k), 0.6, 6, self.welt(k)))
            self.assertAlmostEqual(s["visible_seam_m"], want, msg=k)        # front and back welts face up

    def test_marked_seams_are_measured_but_not_noted(self):
        rounded = rounded_profile(0.6, 0.15, 0.05, 8)
        auto = self.seams(*prism(rounded, 0.6, 6, self.welt(8)))
        self.assertTrue(self.um.visible_seam_warning(auto).startswith("visible seams 1.20 m: "))
        marked = self.seams(*prism(rounded, 0.6, 6, self.welt(8), seed_label=self.welt(8)))
        self.assertAlmostEqual(marked["visible_seam_m"], 1.2)
        self.assertEqual(marked["visible_seam_unmarked_m"], 0.0)
        self.assertIsNone(self.um.visible_seam_warning(marked))

    def test_unwelded_corners_with_equal_uvs_are_not_a_seam(self):
        m = quads([[(i, j, 0), (i + 1, j, 0), (i + 1, j + 1, 0), (i, j + 1, 0)] for i in range(3) for j in range(3)],
                  [[(0.1 * i, 0.1 * j), (0.1 * i + 0.1, 0.1 * j), (0.1 * i + 0.1, 0.1 * j + 0.1),
                    (0.1 * i, 0.1 * j + 0.1)] for i in range(3) for j in range(3)])   # one UV id per corner
        s = self.seams(dict(m, uvw_ids=list(m["xyz_ids"]), uvw=list(m["xyz"])), m["uvw_ids"], m["uvw"])
        self.assertEqual((s["seam_m"], s["visible_seam_m"]), (0.0, 0.0))      # and the open border is no seam

    def test_an_inverted_shell_reads_the_same(self):
        mesh, ids, uvw = self.cushion("top")
        starts = [sum(mesh["sizes"][:k]) for k in range(len(mesh["sizes"]))]

        def rev(a):                                # every polygon's corners in reverse: normals point inward
            return [v for s, n in zip(starts, mesh["sizes"]) for v in reversed(a[s:s + n])]
        s = self.seams(dict(mesh, xyz_ids=rev(mesh["xyz_ids"]), uvw_ids=rev(mesh["uvw_ids"])), rev(ids), uvw)
        self.assertAlmostEqual(s["visible_seam_m"], 0.6)                      # its top still reads as the top

    def test_report_carries_the_seams_and_the_note_threshold(self):
        mesh, ids, uvw = self.cushion("top")
        rep = self.um.report(mesh, ids, uvw, 1024)
        self.assertAlmostEqual(rep["seams"]["visible_seam_unmarked_m"], 0.6)
        self.assertAlmostEqual(rep["seams"]["size_m"], math.sqrt(0.6 ** 2 + 0.6 ** 2 + 0.15 ** 2), places=3)
        self.assertFalse([f for f in self.um.grade(rep) if "seam" in f])      # advisory: never a gate failure
        note = self.um.visible_seam_warning
        self.assertIsNone(note({"visible_seam_unmarked_m": 0.24, "size_m": 2.0}))          # under 25 cm
        self.assertIsNotNone(note({"visible_seam_unmarked_m": 0.25, "size_m": 2.0}))
        self.assertIsNotNone(note({"visible_seam_unmarked_m": 0.06, "size_m": 0.2}))       # a quarter of a small piece
        self.assertIsNone(note({"visible_seam_unmarked_m": 0.04, "size_m": 0.2}))
        self.assertIsNone(note({"visible_seam_unmarked_m": 0.0, "size_m": 0.0}))
        ru = load("rizom_uv")
        warns = ru.layer_report(mesh, ids, uvw, ru.pack_spec(1024))["warnings"]
        self.assertTrue(any(w.startswith("visible seams 0.60 m") for w in warns), warns)


if __name__ == "__main__":
    unittest.main()
