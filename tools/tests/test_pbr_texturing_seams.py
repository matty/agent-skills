"""Plain-Python tests for the pbr-texturing skill's scripts/texture_seams.py: the sampling and verdict maths that need
no Blender (wrapped bilinear samples, the inward step, MikkTSpace shading, the two-tier verdict and the busy-texture
baseline, the length-weighted summary). The mesh side runs in tools/tests/blender/test_pbr_texturing_seams.py.

Host: plain Python 3.9+ with numpy (the tests skip without it). Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_pbr_*.py"
"""

import importlib.util
import sys
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "pbr-texturing" / "scripts" / "texture_seams.py"


def load():
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("texture_seams_under_test", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = keep


@unittest.skipUnless(np, "numpy not installed")
class SeamMaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ts = load()

    def test_sample_wraps_like_repeat(self):
        img = np.zeros((4, 4, 3))
        img[:, 0] = 1.0
        s = self.ts.sample(img, [(0.0, 0.5), (1.0, 0.5), (0.125, 0.5), (3.125, -2.5)])
        np.testing.assert_allclose(s[:, 0], [0.5, 0.5, 1.0, 1.0])              # whole tiles away: the same texel

    def test_inward_points_into_the_face(self):
        np.testing.assert_allclose(self.ts.inward((0, 0), (1, 0), (0.5, 0.5), (4, 4)), (0, 0.25))
        np.testing.assert_allclose(self.ts.inward((0, 0), (1, 0), (0.5, -0.5), (4, 8)), (0, -0.125))
        self.assertIsNone(self.ts.inward((0.2, 0.2), (0.2, 0.2), (0.5, 0.5), (4, 4)))

    def test_shade_mikktspace(self):
        t, n = [(1, 0, 0)], [(0, 0, 1)]
        np.testing.assert_allclose(self.ts.shade([(0.5, 0.5, 1.0)], t, [1.0], n), [(0, 0, 1)], atol=1e-12)
        np.testing.assert_allclose(self.ts.shade([(0.5, 1.0, 0.5)], t, [1.0], n), [(0, 1, 0)], atol=1e-12)
        np.testing.assert_allclose(self.ts.shade([(0.5, 1.0, 0.5)], t, [-1.0], n), [(0, -1, 0)], atol=1e-12)

    def test_verdict_tiers_floor_and_baseline(self):
        v = self.ts.verdict
        self.assertEqual(v([0.1], [0.01], "color"), (10.0, True, True))
        self.assertEqual(v([0.025], [0.01], "color")[1:], (False, True))
        self.assertEqual(v([0.005], [0.001], "color")[1:], (False, False))      # under the colour floor
        self.assertEqual(v([0.1], [0.01], "color", base=0.05)[1], False)        # a busy texture lifts the bar
        ratio, shows, look = v([10.0], [0.2], "normal")
        self.assertTrue(shows and ratio == 10.0)                                 # inner floored at 2 / 2 = 1 deg
        self.assertEqual(v([1.5], [0.1], "normal")[1:], (False, False))         # under the 2 deg floor

    def test_baseline(self):
        checker = np.dstack([np.tile([[0.0, 1.0], [1.0, 0.0]], (4, 4))] * 3)
        self.assertGreater(self.ts.baseline(checker, "color"), 0.9)
        self.assertEqual(self.ts.baseline(checker, "normal"), 0.0)
        self.assertEqual(self.ts.baseline(np.full((8, 8, 3), 0.5), "color"), 0.0)

    def test_summary_weights_by_length(self):
        rows = [(1.0, np.zeros(3), np.array([0.1]), np.array([0.01]), False),     # shows
                (3.0, np.ones(3), np.array([0.011]), np.array([0.01]), False),    # clean
                (2.0, np.ones(3), np.array([0.5]), np.array([0.01]), True)]       # a fold: reported apart
        r = self.ts.summarise(rows, "color")
        self.assertEqual((r["edges"], r["seam_m"], r["visible_m"], r["folds_m"]), (2, 4.0, 1.0, 2.0))
        self.assertEqual(r["ratio_p50"], 1.1)
        self.assertEqual(len(r["worst"]), 1)


if __name__ == "__main__":
    unittest.main()
