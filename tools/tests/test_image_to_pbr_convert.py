"""Plain-Python tests for the image-to-pbr skill's scripts/image_to_pbr.py: PNG round trips, the per-axis seam
measure, repeat detection and the feathered whole-period crop, the base-colour range, the normal map's OpenGL
convention, and a full conversion of a synthetic pattern that does not tile vertically.

Host: plain Python 3.9+ with numpy (the tests skip without it). Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_image_to_pbr_*.py"
"""

import importlib.util
import json
import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "image-to-pbr" / "scripts" / "image_to_pbr.py"


def load():
    spec = importlib.util.spec_from_file_location("image_to_pbr", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pattern(h, w, period_y, period_x, seed=1):
    """A colour pattern repeating every period_x columns and period_y rows, with non-repeating fine noise."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    a = np.stack([0.5 + 0.3 * np.sin(2 * np.pi * x / period_x) * np.cos(2 * np.pi * y / period_y),
                  0.4 + 0.2 * np.cos(2 * np.pi * (x / period_x + y / period_y)),
                  0.3 + 0.2 * np.sin(2 * np.pi * y / period_y)], -1)
    a += np.random.default_rng(seed).normal(0, 0.02, a.shape)
    return np.clip(a, 0, 1)


def write_c2pa_png(path, rgb):
    """An 8-bit RGB PNG with a caBX chunk before IDAT, as a C2PA-signed PNG has."""
    h, w = rgb.shape[:2]
    raw = b"".join(b"\x00" + (np.clip(rgb[y], 0, 1) * 255).round().astype(np.uint8).tobytes() for y in range(h))

    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"caBX", b"\x00" * 16) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@unittest.skipIf(np is None, "numpy not installed")
class ImageToPbrTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def test_png_round_trip_8_and_16_bit(self):
        a = np.random.default_rng(0).random((5, 7, 3)).astype(np.float32)
        with tempfile.TemporaryDirectory() as d:
            for bits, tol in ((8, 0.5 / 255 + 1e-6), (16, 0.5 / 65535 + 1e-6)):
                p = os.path.join(d, "t%d.png" % bits)
                self.m.write_png(p, a, bits)
                px, info = self.m.load(p)
                self.assertEqual(info["bits"], bits)
                self.assertLessEqual(float(np.abs(px[..., :3] - a).max()), tol)

    def test_seam_ratios_per_axis(self):
        tiles_x = pattern(200, 240, 50, 60)            # 240 = 4 x 60 columns; 200 rows hold 4 x 50 rows
        self.assertLess(max(self.m.seam_ratios(tiles_x)), 1.5)
        cut = pattern(230, 240, 50, 60)               # 230 is not a multiple of 50: a top-bottom seam
        lr, tb = self.m.seam_ratios(cut)
        self.assertLess(lr, 1.5)
        self.assertGreater(tb, 1.5)
        self.assertTrue(self.m.seam_visible(cut))
        self.assertFalse(self.m.seam_visible(tiles_x))

    def test_fit_period_and_feathered_crop_tile(self):
        a = pattern(230, 240, 50, 60)
        start, length, score = self.m.fit_period(self.m.luma(a), 0)
        self.assertEqual(length % 50, 0)
        self.assertLess(score, 0.6)
        out = self.m.crop_wrap(a, 0, start, length)
        self.assertEqual(out.shape[0], length)
        self.assertFalse(self.m.seam_visible(out))

    def test_fit_period_none_without_a_repeat(self):
        noise = np.random.default_rng(3).random((128, 128))
        self.assertIsNone(self.m.fit_period(self.m.blur(noise, 3, wrap=False), 0))

    def test_base_colour_into_dielectric_range(self):
        dark = np.full((64, 64, 3), 0.02, np.float32)
        dark[:32] = 0.98
        bc, stats = self.m.base_colour(dark, 0, True)
        y = self.m.luma(bc) * 255
        self.assertGreaterEqual(float(y.min()), 30 - 0.5)
        self.assertLessEqual(float(y.max()), 240 + 0.5)

    def test_normal_is_opengl(self):
        # height rising down the image (with rows): the surface faces up the image, so green > 0.5 (OpenGL Y+)
        h = np.tile(np.sin(np.linspace(0, 2 * np.pi, 64, endpoint=False))[:, None], (1, 64)).astype(np.float32)
        n, _ = self.m.normal_map(h, 20)
        rising = slice(2, 14)                          # sin rising near the top rows
        self.assertGreater(float(n[rising, :, 1].mean()), 0.5)
        self.assertAlmostEqual(float(n[rising, :, 0].mean()), 0.5, places=3)

    def test_convert_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "pattern.png")
            write_c2pa_png(src, pattern(300, 256, 64, 64))
            r = self.m.convert(src, os.path.join(d, "out"), "RUG", "Test", "fabric", make_tileable_=True,
                               preview=True)
            self.assertEqual(r["problems"], [])
            self.assertTrue(r["measured"]["tiles"])
            self.assertEqual(r["tileable_px"][1] % 64, 0)
            for role in ("BaseColor", "Normal", "Height", "Roughness", "AO", "MetallicSmoothness"):
                self.assertTrue(os.path.isfile(r["maps"][role]["path"]), role)
                self.assertFalse(r["maps"][role]["seam_visible"], role)
            with open(r["source_record"], encoding="utf-8") as f:
                side = json.load(f)
            self.assertTrue(side["c2pa_manifest_in_source"])
            self.assertEqual(side["px"], [256, 300])
            self.assertEqual([t for t, _ in self.m.png_chunks(r["maps"]["BaseColor"]["path"])],
                             ["IHDR", "IDAT", "IEND"])

    def test_height_from_normals_round_trip(self):
        y, x = np.mgrid[0:128, 0:128].astype(np.float32)
        h = (np.sin(2 * np.pi * x / 32) + np.cos(2 * np.pi * y / 64)).astype(np.float32)
        n, _ = self.m.normal_map(h, 20)
        back = self.m.height_from_normals(n, wrap=True)
        self.assertGreater(float(np.corrcoef(back.ravel(), h.ravel())[0, 1]), 0.99)

    def test_scale_normals_hits_tilt_and_flips(self):
        h = self.m.blur(np.random.default_rng(2).random((128, 128)).astype(np.float32), 2)
        n, _ = self.m.normal_map(h, 10)
        s, _ = self.m.scale_normals(n, 30)
        tilt = np.degrees(np.arccos(np.clip(s[..., 2] * 2 - 1, -1, 1)))
        self.assertAlmostEqual(float(np.percentile(tilt, 90)), 30, delta=0.5)
        f, _ = self.m.scale_normals(n, 30, flip=True)
        self.assertLess(float(np.corrcoef(f[..., 0].ravel(), s[..., 0].ravel())[0, 1]), -0.99)

    def _fake_deepbump(self, d, body):
        """A DeepBump folder whose module_color_to_normals prints DeepBump's U+2192 arrow, then runs body."""
        src = os.path.join(d, "DeepBump")
        os.makedirs(src)
        with open(os.path.join(src, "module_color_to_normals.py"), "w", encoding="utf-8") as f:
            f.write("import numpy as np\n\ndef apply(img, overlap, cb):\n    print('DeepBump Color \\u2192 Normals')\n"
                    "    " + body + "\n")
        return d

    def test_deepbump_plumbing_with_a_fake(self):
        import sys
        rgb = pattern(64, 64, 32, 32)
        with tempfile.TemporaryDirectory() as d:
            root = self._fake_deepbump(d, "out = np.full((3,) + img.shape[1:], 0.5); out[2] = 1.0; return out")
            n, rec = self.m.run_deepbump(rgb, root, python=sys.executable)
            self.assertEqual(n.shape, (64, 64, 3))
            self.assertAlmostEqual(float(n[..., 2].mean()), 1.0, places=5)
        with tempfile.TemporaryDirectory() as d:
            root = self._fake_deepbump(d, "raise RuntimeError('model exploded')")
            with self.assertRaisesRegex(self.m.DeepBumpUnavailable, "model exploded"):
                self.m.run_deepbump(rgb, root, python=sys.executable)

    def test_missing_deepbump_falls_back_and_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "p.png")
            self.m.write_png(src, pattern(128, 128, 64, 64))
            nowhere = os.path.join(d, "nowhere")
            r = self.m.convert(src, os.path.join(d, "a"), "INT", "Stone", "stone", deepbump=nowhere)
            self.assertEqual(r["normal_source"], "builtin")
            self.assertTrue(any("DeepBump unavailable" in n for n in r["notes"]))
            self.assertEqual(r["problems"], [])
            r = self.m.convert(src, os.path.join(d, "b"), "INT", "Stone", "stone", normals="deepbump",
                               deepbump=nowhere)
            self.assertTrue(any("DeepBump unavailable" in p for p in r["problems"]))
            r = self.m.convert(src, os.path.join(d, "c"), "RUG", "Wool", "fabric", deepbump=nowhere)
            self.assertTrue(any("skips DeepBump" in n for n in r["notes"]))

    def test_cli_rejects_bad_names(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "p.png")
            self.m.write_png(src, pattern(64, 64, 32, 32))
            self.assertEqual(self.m.main([src, "--out", d, "--family", "rug", "--name", "X"]), 2)


if __name__ == "__main__":
    unittest.main()
