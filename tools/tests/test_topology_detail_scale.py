"""Plain-Python tests for blender-mesh-topology's scripts/detail_scale.py: pixels per metre, texel classes and their
band edges, the stereo relief rule (about 0.014 d^2 m at 20 ppd), the narrowest feature width, ppd scaling and the CLI.

Host: plain Python 3.9+, standard library. Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_topology_*.py"
"""

import importlib.util
import math
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "blender-mesh-topology" / "scripts" / "detail_scale.py"


def load():
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("detail_scale_under_test", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = keep


ds = load()


class PxPerM(unittest.TestCase):
    def test_1150_over_d_at_20_ppd(self):
        self.assertEqual(ds.PX_PER_M_AT_1M, 1150)
        self.assertAlmostEqual(ds.px_per_m(1.0), 1150.0)
        self.assertAlmostEqual(ds.px_per_m(2.0), 575.0)
        self.assertAlmostEqual(ds.px_per_m(0.5), 2300.0)

    def test_scales_with_ppd(self):
        self.assertAlmostEqual(ds.px_per_m(1.0, ppd=25), 1437.5)
        self.assertAlmostEqual(ds.px_per_m(3.0, ppd=25) / ds.px_per_m(3.0), 1.25)

    def test_rejects_bad_input(self):
        for bad in (0.0, -1.0):
            with self.assertRaises(ValueError):
                ds.px_per_m(bad)
        with self.assertRaises(ValueError):
            ds.px_per_m(1.0, ppd=0)


class TexelClasses(unittest.TestCase):
    def test_table_shape(self):
        self.assertEqual(ds.TEXEL_CLASSES,
                         ((2048, 0.0), (1024, 0.75), (512, 1.5), (256, 3.0), (128, 6.0), (64, 12.0)))
        starts = [s for _, s in ds.TEXEL_CLASSES]
        self.assertEqual(starts, sorted(starts))

    def test_band_edges(self):
        cases = [(0.0, 2048), (0.3, 2048), (0.749, 2048), (0.75, 1024), (1.0, 1024), (1.499, 1024), (1.5, 512),
                 (2.999, 512), (3.0, 256), (5.99, 256), (6.0, 128), (11.99, 128), (12.0, 64), (100.0, 64)]
        for d, want in cases:
            self.assertEqual(ds.texel_class(d), want, "d = %g" % d)

    def test_each_class_gives_two_thirds_at_its_near_edge(self):
        for px, start in ds.TEXEL_CLASSES[1:]:
            self.assertGreaterEqual(px / ds.px_per_m(start), 2.0 / 3.0 - 1e-3, "T%d at %g m" % (px, start))
            self.assertLess(px / ds.px_per_m(start), 0.7, "T%d is far more than its near edge needs" % px)

    def test_higher_ppd_steps_up_sooner(self):
        self.assertEqual(ds.texel_class(1.6), 512)
        self.assertEqual(ds.texel_class(1.6, ppd=25), 1024)     # 1.6 m at 25 ppd needs what 1.28 m does at 20
        self.assertEqual(ds.texel_class(0.9, ppd=25), 2048)
        self.assertEqual(ds.texel_class(14.0, ppd=25), 128)     # 11.2 m at 20 ppd
        self.assertEqual(ds.texel_class(15.0, ppd=25), 64)

    def test_rejects_negative_distance(self):
        with self.assertRaises(ValueError):
            ds.texel_class(-0.5)


class StereoRelief(unittest.TestCase):
    def test_about_0014_d_squared(self):
        self.assertAlmostEqual(ds.stereo_relief_m(1.0), math.radians(1) / 20 / 0.063, places=12)
        self.assertAlmostEqual(ds.stereo_relief_m(1.0), 0.0139, places=4)     # 1.4 cm at 1 m
        self.assertAlmostEqual(ds.stereo_relief_m(2.0), 0.0554, places=4)     # 5.5 cm at 2 m
        self.assertAlmostEqual(ds.stereo_relief_m(0.5), 0.00346, places=5)    # 3.5 mm at 0.5 m
        for d in (0.3, 1.0, 4.0, 9.0):
            self.assertAlmostEqual(ds.stereo_relief_m(d) / (d * d), ds.stereo_relief_m(1.0), places=12)

    def test_ppd_and_ipd(self):
        self.assertAlmostEqual(ds.stereo_relief_m(1.0, ppd=25), ds.stereo_relief_m(1.0) * 20 / 25, places=12)
        self.assertAlmostEqual(ds.stereo_relief_m(1.0, ipd=0.07), ds.stereo_relief_m(1.0) * 0.063 / 0.07, places=12)
        with self.assertRaises(ValueError):
            ds.stereo_relief_m(1.0, ipd=0)
        with self.assertRaises(ValueError):
            ds.stereo_relief_m(0)


class MinWidth(unittest.TestCase):
    def test_two_pixels(self):
        self.assertAlmostEqual(ds.min_width_m(1.0), 2 / 1150.0)
        self.assertAlmostEqual(ds.min_width_m(5.0) * 1000, 8.70, places=2)
        self.assertAlmostEqual(ds.min_width_m(3.0, px=1) * 1000, 2.61, places=2)

    def test_width_times_px_per_m_is_px(self):
        for d in (0.5, 1.0, 2.5, 10.0):
            for ppd in (20, 25):
                self.assertAlmostEqual(ds.min_width_m(d, 2, ppd) * ds.px_per_m(d, ppd), 2.0)


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(SCRIPT)] + list(args), capture_output=True, text=True)

    def test_table(self):
        p = self.run_cli("0.5", "1", "2", "5", "10")
        self.assertEqual(p.returncode, 0, p.stderr)
        lines = p.stdout.splitlines()
        self.assertIn("relief mm", lines[0])
        rows = [ln.split() for ln in lines[1:6]]
        self.assertEqual([r[2] for r in rows], ["T2048", "T1024", "T512", "T256", "T128"])
        self.assertEqual(rows[1][:2], ["1.00", "1150"])
        self.assertEqual(rows[1][3], "13.9")
        self.assertEqual(rows[1][4], "1.7")
        self.assertIn("at 20 ppd", lines[-1])

    def test_ppd_option(self):
        p = self.run_cli("1.6", "--ppd", "25")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("T1024", p.stdout)
        self.assertIn("at 25 ppd", p.stdout)

    def test_bad_distance_is_an_argument_error(self):
        p = self.run_cli("0")
        self.assertEqual(p.returncode, 2)
        self.assertIn("distance must be above 0 m", p.stderr)


if __name__ == "__main__":
    unittest.main()
