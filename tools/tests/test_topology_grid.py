"""Plain-Python tests for blender-mesh-topology's scripts/grid_topology.py: reduction bands (valences, winding,
parity), stations, zippers, grid_faces with index-based verts, and thin_plate_heights with and without scipy.

Host: plain Python 3.9+; the thin-plate tests need numpy (skipped without it), the scipy comparison needs scipy.
Blender's mathutils is replaced by a small stand-in. Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_topology_*.py"
"""

import importlib.util
import math
import sys
import types
import unittest
import warnings
from collections import Counter, defaultdict
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None
try:
    import scipy  # noqa: F401
    HAVE_SCIPY = True
except ImportError:
    HAVE_SCIPY = False

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "blender-mesh-topology" / "scripts" / "grid_topology.py"


class Vector:
    """Enough of mathutils.Vector for the helpers under test."""
    def __init__(self, seq=(0.0, 0.0, 0.0)):
        self.v = [float(c) for c in seq]

    def __iter__(self):
        return iter(self.v)

    def __len__(self):
        return len(self.v)

    def __getitem__(self, i):
        return self.v[i]

    x = property(lambda self: self.v[0])
    y = property(lambda self: self.v[1])
    z = property(lambda self: self.v[2])

    def __add__(self, o):
        return Vector(a + b for a, b in zip(self.v, o))

    def __sub__(self, o):
        return Vector(a - b for a, b in zip(self.v, o))

    def __mul__(self, s):
        return Vector(a * s for a in self.v)

    def __truediv__(self, s):
        return Vector(a / s for a in self.v)

    @property
    def length(self):
        return math.sqrt(sum(a * a for a in self.v))

    def lerp(self, o, f):
        return Vector(a + (b - a) * f for a, b in zip(self.v, o))

    def copy(self):
        return Vector(self.v)


def load():
    stub = types.ModuleType("mathutils")
    stub.Vector = Vector
    saved = sys.modules.get("mathutils")
    sys.modules["mathutils"] = stub
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("grid_topology_under_test", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = keep
        if saved is None:
            sys.modules.pop("mathutils", None)
        else:
            sys.modules["mathutils"] = saved


gt = load()


class Vert:
    def __init__(self, x, y, name):
        self.co, self.name = Vector((x, y, 0.0)), name

    def __repr__(self):
        return self.name


class Mesh:
    def __init__(self):
        self.faces, self.n = [], 0

    def face(self, vs):
        self.faces.append(list(vs))
        return vs

    def new_vert(self, co):
        self.n += 1
        return Vert(co[0], co[1], "m%d" % self.n)

    def valences(self):
        nb = defaultdict(set)
        for f in self.faces:
            for k in range(len(f)):
                nb[f[k]].add(f[k - 1])
                nb[f[k - 1]].add(f[k])
        return {v: len(s) for v, s in nb.items()}

    def edge_use(self):
        return Counter(frozenset((f[k], f[k - 1])) for f in self.faces for k in range(len(f)))

    def winding_ok(self):
        directed = Counter((f[k - 1], f[k]) for f in self.faces for k in range(len(f)))
        return all(c == 1 for c in directed.values())


def band(n, groups):
    """A reduction band of `groups` groups between a full row above and a full row below."""
    m = n + 2
    mesh = Mesh()
    up = [Vert(x, 2.0, "u%d" % x) for x in range(m * groups + 1)]
    top = [Vert(x, 1.0, "f%d" % x) for x in range(m * groups + 1)]
    bottom = [Vert(x * m / n, 0.0, "c%d" % x) for x in range(n * groups + 1)]
    down = [Vert(x * m / n, -1.0, "d%d" % x) for x in range(n * groups + 1)]
    gt.ladder(mesh.face, up, top)
    gt.step_reduce(mesh.face, mesh.new_vert, top, bottom, gt.mid_along(), n)
    gt.ladder(mesh.face, bottom, down)
    return mesh, top, bottom


class ReductionBands(unittest.TestCase):
    def test_3to1_poles_are_3_and_6_not_5(self):
        mesh, top, bottom = band(1, 2)
        val = mesh.valences()
        self.assertTrue(all(len(f) == 4 for f in mesh.faces))
        self.assertTrue(mesh.winding_ok())
        self.assertEqual(max(mesh.edge_use().values()), 2)
        for f in top[1:-1]:
            self.assertEqual(val[f], 4, f)                       # f1, f2 keep valence 4
        mids = [v for v in val if v.name.startswith("m")]
        self.assertEqual(sorted(val[v] for v in mids), [3, 3, 3, 3])
        self.assertEqual(val[bottom[1]], 6)                      # shared by two groups, row below
        self.assertEqual((val[bottom[0]], val[bottom[-1]]), (4, 4))

    def test_step_3to1_matches_the_documented_quads(self):
        mesh = Mesh()
        top = [Vert(x, 1.0, "f%d" % x) for x in range(4)]
        bottom = [Vert(0.0, 0.0, "c0"), Vert(3.0, 0.0, "c1")]
        gt.step_3to1(mesh.face, mesh.new_vert, top, bottom, gt.mid_between())
        p, q = mesh.faces[0][2], mesh.faces[1][2]
        f0, f1, f2, f3 = top
        c0, c1 = bottom
        self.assertEqual(mesh.faces, [[f0, f1, p, c0], [f1, f2, q, p], [f2, f3, c1, q], [p, q, c1, c0]])
        self.assertAlmostEqual(p.co.x, 1.0)
        self.assertAlmostEqual(p.co.y, 0.5)

    def test_4to2_and_5to3_are_all_quads_with_two_3_poles_per_group(self):
        for n in (2, 3):
            mesh, top, bottom = band(n, 2)
            val = mesh.valences()
            self.assertTrue(all(len(f) == 4 for f in mesh.faces), n)
            self.assertTrue(mesh.winding_ok(), n)
            self.assertEqual(max(mesh.edge_use().values()), 2, n)
            mids = sorted(val[v] for v in val if v.name.startswith("m"))
            self.assertEqual(mids, [3] * 4 + [4] * (2 * (n + 1) - 4), n)
            self.assertEqual(val[bottom[n]], 6, n)              # the bottom vert two groups share
            self.assertTrue(all(val[c] == 4 for c in bottom[1:n]), n)
            band_faces = len(mesh.faces) - (len(top) - 1) - (len(bottom) - 1)      # minus the rows above and below
            self.assertEqual(band_faces, 2 * (2 * n + 2), n)

    def test_band_patch_has_an_even_border(self):
        for n in (1, 2, 3):
            mesh = Mesh()
            top = [Vert(x, 1.0, "f%d" % x) for x in range(n + 3)]
            bottom = [Vert(x * (n + 2) / n, 0.0, "c%d" % x) for x in range(n + 1)]
            gt.step_reduce(mesh.face, mesh.new_vert, top, bottom, gt.mid_along(), n)
            border = sum(1 for c in mesh.edge_use().values() if c == 1)
            self.assertEqual(border, (n + 2) + n + 2)
            self.assertEqual(border % 2, 0)

    def test_coarse_to_fine_band_needs_both_runs_reversed(self):
        """A second band going coarse -> fine (fine run below, as on the far side of a ring) winds against the first
        unless both of its runs are reversed."""
        for reverse, ok in ((False, False), (True, True)):
            mesh = Mesh()
            fine1 = [Vert(x, 2.0, "f%d" % x) for x in range(7)]
            coarse1 = [Vert(3.0 * x, 1.0, "c%d" % x) for x in range(3)]
            coarse2 = [Vert(3.0 * x, 0.0, "k%d" % x) for x in range(3)]
            fine2 = [Vert(x, -1.0, "g%d" % x) for x in range(7)]
            gt.step_reduce(mesh.face, mesh.new_vert, fine1, coarse1, gt.mid_along(), 1)
            gt.ladder(mesh.face, coarse1, coarse2)
            top, bottom = (fine2[::-1], coarse2[::-1]) if reverse else (fine2, coarse2)
            gt.step_reduce(mesh.face, mesh.new_vert, top, bottom, gt.mid_along(), 1)
            self.assertEqual(mesh.winding_ok(), ok, "reverse=%s" % reverse)

    def test_closed_ring_repeats_its_first_vert(self):
        """Round a pipe, both runs are passed with their first vert repeated at the end: the last group closes the
        ring, so the band's only border is the two rings. Without the repeat the counts are refused."""
        groups = 3
        top = [Vert(2 * math.cos(a), 2 * math.sin(a), "f%d" % k)
               for k, a in enumerate(2 * math.pi * i / (3 * groups) for i in range(3 * groups))]
        bottom = [Vert(math.cos(a), math.sin(a), "c%d" % k)
                  for k, a in enumerate(2 * math.pi * i / groups for i in range(groups))]
        mesh = Mesh()
        gt.step_reduce(mesh.face, mesh.new_vert, top + top[:1], bottom + bottom[:1], gt.mid_along(), 1)
        self.assertTrue(all(len(f) == 4 for f in mesh.faces))
        self.assertTrue(mesh.winding_ok())
        border = {e for e, c in mesh.edge_use().items() if c == 1}
        rings = {frozenset((r[k - 1], r[k])) for r in (top, bottom) for k in range(len(r))}
        self.assertEqual(border, rings)
        with self.assertRaises(AssertionError) as caught:
            gt.step_reduce(Mesh().face, Mesh().new_vert, top, bottom, gt.mid_along(), 1)
        self.assertIn("closed ring", str(caught.exception))

    def test_bad_counts_are_refused(self):
        top = [Vert(x, 1.0, "f%d" % x) for x in range(5)]
        bottom = [Vert(0.0, 0.0, "c0"), Vert(4.0, 0.0, "c1")]
        with self.assertRaises(AssertionError):
            gt.step_3to1(Mesh().face, Mesh().new_vert, top, bottom, gt.mid_between())

    def test_mid_along_follows_the_polyline(self):
        cs = [Vert(0.0, 0.0, "a"), Vert(1.0, 0.0, "b"), Vert(1.0, 1.0, "c")]
        f = Vert(0.75, 1.0, "f")
        co = gt.mid_along()(f, cs, 0.75)                      # 1.5 along a 2-long path: (1, 0.5)
        self.assertAlmostEqual(co.x, (0.75 + 1.0) / 2)
        self.assertAlmostEqual(co.y, (1.0 + 0.5) / 2)


class StationsAndStrips(unittest.TestCase):
    def test_arc_segments_keep_the_sag(self):
        for r, span, tol in [(1.0, 90, 0.0015), (0.25, 180, 0.004), (5.0, 30, 0.008)]:
            n = gt.arc_segments(r, span, tol)
            sag = r * (1 - math.cos(math.radians(span / n) / 2))
            self.assertLessEqual(sag, tol + 1e-12)
            if n > 1:
                sag_fewer = r * (1 - math.cos(math.radians(span / (n - 1)) / 2))
                self.assertGreater(sag_fewer, tol)

    def test_zone_stations_multiple(self):
        st, counts = gt.zone_stations([0.0, 1.0, 1.3, 3.0], 0.2, multiple=3)
        self.assertEqual(sum(counts) % 3, 0)
        self.assertEqual(len(st), sum(counts) + 1)
        self.assertEqual(st[0], 0.0)
        self.assertAlmostEqual(st[-1], 3.0)

    def test_zipper_quads_where_stations_match(self):
        A = [Vert(x / 4.0, 1.0, "a%d" % x) for x in range(5)]
        B = [Vert(x / 6.0, 0.0, "b%d" % x) for x in range(7)]
        for fn in (lambda m: gt.zipper(m.face, A, B), lambda m: gt.zipper_by(m.face, A, B, key=lambda v: v.co.x)):
            mesh = Mesh()
            fn(mesh)
            self.assertEqual(sum(1 for f in mesh.faces if len(f) == 4), 2)   # at x = 0.5 and x = 1
            self.assertTrue(mesh.winding_ok())

    def test_grid_faces_accepts_index_zero(self):
        cols = [{0: 0, 1: 1}, {0: 2, 1: 3}]                   # a wrapper that uses vertex indices
        made = gt.grid_faces(lambda vs: vs, cols, [0, 1])
        self.assertEqual(made, [[0, 2, 3, 1]])


@unittest.skipUnless(np is not None, "numpy not installed")
class ThinPlate(unittest.TestCase):
    nc, nr, h = 12, 9, 0.1

    def setUp(self):
        self.pts = [(j * self.h, i * self.h) for j in range(self.nc) for i in range(self.nr)]
        self.tris = gt.grid_triangles(self.nc, self.nr)

    def fixed(self, field, depth):
        out = {}
        for k, (x, y) in enumerate(self.pts):
            j, i = divmod(k, self.nr)
            if j < depth or j >= self.nc - depth or i < depth or i >= self.nr - depth:
                out[k] = field(x, y)
        return out

    def error(self, field, depth, **kw):
        z = gt.thin_plate_heights(self.pts, self.tris, self.fixed(field, depth), **kw)
        return max(abs(z[k] - field(*p)) for k, p in enumerate(self.pts))

    def test_two_deep_reproduces_plane_and_quadratic_with_numpy(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")                      # numpy 2.x warns on np.cross with 2-vectors
            self.assertLess(self.error(lambda x, y: 0.3 * x - 0.2 * y + 1.0, 2, use_scipy=False), 1e-9)
            self.assertLess(self.error(lambda x, y: x * x + 0.5 * y * y - x * y, 2, use_scipy=False), 1e-9)

    def test_one_deep_does_not(self):
        self.assertGreater(self.error(lambda x, y: x * x + 0.5 * y * y - x * y, 1, use_scipy=False), 1e-3)

    def test_cross2(self):
        self.assertEqual(gt._cross2((1.0, 0.0), (0.0, 1.0)), 1.0)
        self.assertEqual(gt._cross2(np.array([2.0, 1.0]), np.array([1.0, 3.0])), 5.0)

    @unittest.skipUnless(HAVE_SCIPY, "scipy not installed")
    def test_scipy_and_numpy_agree(self):
        field = lambda x, y: math.exp(-((x - 0.5) ** 2 + (y - 0.4) ** 2) * 8)   # not biharmonic
        fixed = self.fixed(field, 2)
        a = gt.thin_plate_heights(self.pts, self.tris, fixed, use_scipy=True)
        b = gt.thin_plate_heights(self.pts, self.tris, fixed, use_scipy=False)
        self.assertLess(max(abs(x - y) for x, y in zip(a, b)), 1e-10)

    @unittest.skipIf(HAVE_SCIPY, "scipy installed")
    def test_requiring_scipy_without_it_raises_and_auto_falls_back(self):
        fixed = self.fixed(lambda x, y: x, 2)
        with self.assertRaises(ImportError):
            gt.thin_plate_heights(self.pts, self.tris, fixed, use_scipy=True)
        z = gt.thin_plate_heights(self.pts, self.tris, fixed)
        self.assertLess(max(abs(z[k] - p[0]) for k, p in enumerate(self.pts)), 1e-9)


if __name__ == "__main__":
    unittest.main()
