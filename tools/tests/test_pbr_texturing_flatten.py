"""Plain-Python tests for the pbr-texturing skill's scripts/tile_flatten.py: tile-scale variation removed from colour,
grey, packed and normal maps while the detail stays, channel count and bit depth kept, roles from file names, and
the command line's refusals.

Host: plain Python 3.9+ with numpy (the tests skip without it). Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_pbr_*.py"
"""

import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "pbr-texturing" / "scripts"


def load():
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("tile_flatten_under_test", SCRIPTS / "tile_flatten.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = keep


tf = load() if np is not None else None


def blotched(n=256, seed=7, k=0.3):
    """A seamless noise tile with one soft dark patch per tile (what makes a repeat read as a grid)."""
    rng = np.random.default_rng(seed)
    g = tf.pc._blur_wrap(rng.normal(0.0, 1.0, (n, n)), 1.0 / 256)
    g = g / g.std() * 0.12
    yy, xx = np.mgrid[0:n, 0:n]
    blob = np.exp(-((xx - 64.0) ** 2 + (yy - 64.0) ** 2) / (2 * 40.0 ** 2))
    px = np.ones((n, n, 4), np.float32)
    for c, base in enumerate((0.45, 0.4, 0.35)):
        px[:, :, c] = np.clip((base + g) * (1.0 - k * blob), 0, 1)
    return px, blob


@unittest.skipUnless(np, "numpy not installed")
class Flatten(unittest.TestCase):
    def test_colour_patch_removed_detail_kept(self):
        px, _ = blotched()
        before = tf.pc.tile_uniformity(px, "BaseColor")["lf"]
        flat = tf.flatten(px, "colour")
        after = tf.pc.tile_uniformity(flat, "BaseColor")["lf"]
        self.assertGreater(before, tf.pc.PBR_LIMITS["tile_lf_problem"])
        self.assertLess(after, tf.pc.PBR_LIMITS["tile_lf_note"])
        detail = lambda p: float(np.abs(np.diff(p[:, :, 1], axis=1)).mean())
        self.assertAlmostEqual(detail(flat) / detail(px), 1.0, delta=0.15)
        self.assertAlmostEqual(float(flat[:, :, :3].mean()), float(px[:, :, :3].mean()), delta=0.02)
        half = tf.pc.tile_uniformity(tf.flatten(px, "colour", keep=0.5), "BaseColor")["lf"]
        self.assertTrue(after < half < before, (after, half, before))

    def test_grey_packed_and_normal(self):
        px, blob = blotched()
        grey = np.repeat(px[:, :, 1:2], 4, axis=2)
        grey[:, :, 3] = 1.0
        flat = tf.flatten(grey, "grey")
        sd = lambda a: float(tf.pc._blur_wrap(a.astype(np.float64), 0.125).std())
        self.assertLess(sd(flat[:, :, 0]), sd(grey[:, :, 0]) / 3)
        np.testing.assert_array_equal(flat[:, :, 0], flat[:, :, 2])
        packed = np.zeros_like(px)
        packed[:, :, 0] = (blob > 0.5).astype(np.float32)                    # binary metal stays as it is
        packed[:, :, 3] = 0.5 + 0.2 * blob
        out = tf.flatten(packed, "packed")
        np.testing.assert_array_equal(out[:, :, 0], packed[:, :, 0])
        self.assertLess(tf.pc.tile_uniformity(out, "MetallicSmoothness")["lf_smoothness"],
                        tf.pc.PBR_LIMITS["tile_lf_smoothness"])
        n = 128
        x = np.linspace(0, 2 * np.pi, n, endpoint=False)
        h = np.tile(4.0 * np.sin(x)[None, :], (n, 1))
        v = np.dstack([-np.gradient(h, axis=1), np.zeros((n, n)), np.ones((n, n))])
        v /= np.linalg.norm(v, axis=2, keepdims=True)
        nm = np.ones((n, n, 4), np.float32)
        nm[:, :, :3] = v * 0.5 + 0.5
        out = tf.flatten(nm, "normal")
        self.assertLess(tf.pc.tile_uniformity(out, "Normal")["lf_tilt_deg"], 0.5)
        lengths = np.linalg.norm(out[:, :, :3] * 2 - 1, axis=2)
        self.assertLess(float(np.abs(lengths - 1).max()), 0.01)

    def test_roles(self):
        self.assertEqual(tf.role_of("x/T_EXT_Ground_BaseColor.png"), "colour")
        self.assertEqual(tf.role_of("forest_ground_04_1k_NormalGL.png"), "normal")
        self.assertEqual(tf.role_of("T_EXT_Ground_MetallicSmoothness.png"), "packed")
        self.assertEqual(tf.role_of("forest_ground_04_1k_Roughness.png"), "grey")
        self.assertIsNone(tf.role_of("notes.png"))

    def test_cli_keeps_format_and_refuses(self):
        px, _ = blotched(n=64)
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "T_EXT_Ground_Height.png")
            tf.write_png(src, px, channels=1, depth=16)
            col = os.path.join(d, "T_EXT_Ground_BaseColor.png")
            tf.write_png(col, px, channels=3, depth=8)
            out = os.path.join(d, "flat")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(tf.main([os.path.join(d, "T_*.png"), "--out", out]), 0)
            self.assertEqual(tf.pc.png_header(os.path.join(out, "T_EXT_Ground_Height.png"))[2:4], (16, 0))
            self.assertEqual(tf.pc.png_header(os.path.join(out, "T_EXT_Ground_BaseColor.png"))[2:4], (8, 2))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(tf.main([src, "--out", d]), 1)                  # never over its own source
                tf.write_png(os.path.join(d, "notes.png"), px)
                self.assertEqual(tf.main([os.path.join(d, "notes.png"), "--out", out]), 1)
                self.assertEqual(tf.main([os.path.join(d, "missing_*.png"), "--out", out]), 2)
            self.assertIn("refusing to overwrite", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
