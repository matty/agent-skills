"""Plain-Python tests for the pbr-texturing skill's scripts/pbr_check.py (shipped identically in vrchat-world-qa): the
PNG reader against every filter type and bit depth, the base-colour, metallic-smoothness and normal-map rules, the
green-channel convention test on height-derived maps, the tiling-seam metric, map pairing and the command line.

Host: plain Python 3.9+ with numpy (the tests skip without it). Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_pbr_*.py"
"""

import contextlib
import importlib.util
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "pbr-texturing" / "scripts" / "pbr_check.py"


def load():
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("pbr_check_under_test", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = keep


pc = load()


def _chunk(t, body):
    return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc_ = abs(p - a), abs(p - b), abs(p - c)
    return a if (pa <= pb and pa <= pc_) else (b if pb <= pc_ else c)


def encode_png(codes, depth=8, colour=None, filters=(0,), interlace=0, palette=None):
    """A PNG from an integer (h, w, ch) array, cycling the given filter types row by row (the encoder side of the
    filters the reader must undo)."""
    a = np.asarray(codes)
    h, w = a.shape[:2]
    ch = 1 if a.ndim == 2 else a.shape[2]
    if colour is None:
        colour = {1: 0, 2: 4, 3: 2, 4: 6}[ch]
    if depth == 16:
        rows = a.astype(">u2").reshape(h, -1).view(np.uint8).reshape(h, -1)
    else:
        rows = a.astype(np.uint8).reshape(h, -1)
    bpp = max(1, ch * depth // 8)
    raw, prev = bytearray(), [0] * rows.shape[1]
    for y in range(h):
        cur, ft = rows[y].tolist(), filters[y % len(filters)]
        out = []
        for i, x in enumerate(cur):
            a_ = cur[i - bpp] if i >= bpp else 0
            b_ = prev[i]
            c_ = prev[i - bpp] if i >= bpp else 0
            pred = [0, a_, b_, (a_ + b_) >> 1, _paeth(a_, b_, c_)][ft]
            out.append((x - pred) & 255)
        raw += bytes([ft]) + bytes(out)
        prev = cur
    body = _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, colour, 0, 0, interlace))
    if palette is not None:
        body += _chunk(b"PLTE", bytes(np.asarray(palette, np.uint8).ravel()))
    return b"\x89PNG\r\n\x1a\n" + body + _chunk(b"IDAT", zlib.compress(bytes(raw))) + _chunk(b"IEND", b"")


def rgba(r, g, b, a=1.0, size=(32, 32)):
    px = np.empty(size + (4,), np.float32)
    px[...] = (r, g, b, a)
    return px


def height_bumps(n=128, seed=3):
    """A smooth height field with round bumps (real mixed-derivative content), rows top to bottom; the same bumps at
    any resolution n (positions, radii and heights scale with it)."""
    rng = np.random.default_rng(seed)
    s = n / 128.0
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float64)
    h = np.zeros((n, n))
    for _ in range(12):
        cx, cy, r = rng.uniform(10, 118) * s, rng.uniform(10, 118) * s, rng.uniform(4, 12) * s
        h += np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r * r)) * rng.uniform(2, 6) * s
    return h


def normal_map_from_height(h, green=+1.0, red=+1.0):
    """OpenGL tangent-space normals of z = h: X right, Y up the image (rows run down), encoded to 0-1."""
    hx = np.gradient(h, axis=1)            # d/dx, x along the row
    hy = -np.gradient(h, axis=0)           # d/dy, y up the image
    n = np.dstack([-hx * red, -hy * green, np.ones_like(h)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    px = np.ones(h.shape + (4,), np.float32)
    px[:, :, :3] = (n + 1.0) / 2.0
    return px


def quantise(px, depth=8):
    m = 255.0 if depth == 8 else 65535.0
    return np.round(px * m) / m


@unittest.skipUnless(np, "numpy not installed")
class PngReader(unittest.TestCase):
    def roundtrip(self, codes, depth=8, filters=(0,), **kw):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.png")
            with open(p, "wb") as f:
                f.write(encode_png(codes, depth, filters=filters, **kw))
            return pc.read_png(p)

    def test_every_filter_8_and_16_bit(self):
        rng = np.random.default_rng(0)
        for ch in (1, 2, 3, 4):
            for depth in (8, 16):
                top = 255 if depth == 8 else 65535
                codes = rng.integers(0, top + 1, size=(9, 7, ch))
                px, (got_ch, got_depth) = self.roundtrip(codes, depth, filters=(0, 1, 2, 3, 4))
                self.assertEqual((got_ch, got_depth), (ch, depth))
                want = pc._rgba(codes.astype(np.float32) / top, ch)
                np.testing.assert_array_equal(px, want, err_msg="ch %d depth %d" % (ch, depth))

    def test_palette(self):
        pal = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
        idx = np.array([[0, 1, 2], [2, 1, 0]])
        px, (ch, depth) = self.roundtrip(idx, colour=3, palette=pal, filters=(1, 4))
        self.assertEqual((ch, depth), (3, 8))
        np.testing.assert_array_equal(px[0, 1, :3], [0.0, 1.0, 0.0])
        np.testing.assert_array_equal(px[1, 0, :3], [0.0, 0.0, 1.0])

    def test_interlaced_refused(self):
        with self.assertRaises(ValueError):
            self.roundtrip(np.zeros((4, 4, 3), int), interlace=1)

    def test_header_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.png")
            with open(p, "wb") as f:
                f.write(encode_png(np.full((4, 6, 3), 128), 8))
            self.assertEqual(pc.png_header(p)[:4], (6, 4, 8, 2))
            px, info = pc.load(p)
            self.assertEqual(info["size"], [6, 4])
            self.assertEqual((info["channels"], info["loader"]), (3, "png"))

    def test_write_png_roundtrip(self):
        src = quantise(np.random.default_rng(1).random((5, 8, 4)).astype(np.float32))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "w.png")
            pc.write_png(p, src)
            px, (ch, depth) = pc.read_png(p)
        self.assertEqual((ch, depth), (4, 8))
        np.testing.assert_allclose(px, src, atol=1e-6)


@unittest.skipUnless(np, "numpy not installed")
class BaseColour(unittest.TestCase):
    INFO3 = {"channels": 3}

    def judged(self, px, metallic=None, info=None, targets=None):
        r = {"base_color": pc.base_color_stats(px, info or self.INFO3, metallic)}
        return pc.judge(r, targets)

    def test_mid_grey_passes(self):
        r = self.judged(rgba(0.5, 0.5, 0.5))
        self.assertEqual((r["problems"], r["notes"]), ([], []))
        self.assertAlmostEqual(r["base_color"]["dielectric_luma_p50"], 127.5, places=0)

    def test_too_dark_too_bright_and_strict_note(self):
        self.assertIn("too dark", self.judged(rgba(0.08, 0.08, 0.08))["problems"][0])          # 20 sRGB
        self.assertIn("too bright", self.judged(rgba(0.98, 0.98, 0.98))["problems"][0])        # 250 sRGB
        r = self.judged(rgba(40 / 255.0, 40 / 255.0, 40 / 255.0))
        self.assertEqual(r["problems"], [])
        self.assertIn("strict", r["notes"][0])

    def test_specks_under_the_percentile_pass(self):
        px = rgba(0.5, 0.5, 0.5, size=(100, 100))
        px[0, :5] = (0.0, 0.0, 0.0, 1.0)                                                      # 0.05% black specks
        self.assertEqual(self.judged(px)["problems"], [])

    def test_saturated_colour_uses_luma(self):
        self.assertEqual(self.judged(rgba(0.85, 0.12, 0.10))["problems"], [])                  # red paint, luma ~67

    def test_metal_judged_on_its_own_pixels(self):
        px = rgba(0.5, 0.5, 0.5, size=(10, 10))
        px[:, 5:] = (0.6, 0.6, 0.6, 1.0)                                                       # 153 sRGB metal
        metallic = np.zeros((10, 10), np.float32)
        metallic[:, 5:] = 1.0
        r = self.judged(px, metallic)
        self.assertAlmostEqual(r["base_color"]["metal_share"], 0.5)
        self.assertTrue(any("metal too dark" in p for p in r["problems"]))
        px[:, 5:] = (0.8, 0.78, 0.75, 1.0)                                                     # ~199 sRGB metal
        self.assertEqual(self.judged(px, metallic)["problems"], [])

    def test_cutout_pixels_left_out(self):
        px = rgba(0.5, 0.5, 0.5, size=(10, 10))
        px[:, :6] = (0.0, 0.0, 0.0, 0.0)                                                       # transparent, black
        r = self.judged(px, info={"channels": 4})
        self.assertEqual(r["base_color"]["pixels"], 40)
        self.assertEqual(r["problems"], [])
        self.assertTrue(r["base_color"]["opacity_used"])

    def test_target_range(self):
        r = self.judged(rgba(0.5, 0.5, 0.5), targets={"albedo_srgb": [60, 110]})
        self.assertIn("off target", r["problems"][0])
        self.assertEqual(self.judged(rgba(0.35, 0.35, 0.35), targets={"albedo_srgb": [60, 110]})["problems"], [])


@unittest.skipUnless(np, "numpy not installed")
class MetallicSmoothness(unittest.TestCase):
    def judged(self, px, ch=4, targets=None):
        return pc.judge({"metallic_smoothness": pc.metallic_smoothness_stats(px, {"channels": ch})}, targets)

    def varied(self, metal=0.0, n=40):
        px = rgba(metal, 0.0, 0.0, 0.5, size=(n, n))
        px[:, :, 3] = np.linspace(0.3, 0.7, n)[None, :]
        return px

    def test_binary_metal_passes(self):
        px = self.varied()
        px[:, :20, 0] = 1.0
        self.assertEqual(self.judged(px)["problems"], [])

    def test_grey_metal(self):
        px = self.varied()
        px[:10, :, 0] = 0.5                                                                    # 25% grey metal
        self.assertIn("not binary", self.judged(px)["problems"][0])
        px = self.varied()
        px[:2, :, 0] = 0.5                                                                     # 5%: a note
        r = self.judged(px)
        self.assertEqual(r["problems"], [])
        self.assertIn("greys", r["notes"][0])

    def test_no_alpha_is_a_problem(self):
        self.assertIn("no alpha", self.judged(rgba(0.0, 0.0, 0.0), ch=3)["problems"][0])

    def test_uniform_and_mirror_notes(self):
        self.assertIn("uniform", self.judged(rgba(0.0, 0.0, 0.0, 0.4))["notes"][0])
        self.assertTrue(any("mirror" in n for n in self.judged(rgba(0.0, 0.0, 0.0, 0.99))["notes"]))

    def test_targets(self):
        px = self.varied()                                                                     # roughness 0.3-0.7
        self.assertEqual(self.judged(px, targets={"roughness": [0.4, 0.6]})["problems"], [])
        self.assertIn("off target", self.judged(px, targets={"roughness": [0.7, 0.9]})["problems"][0])
        px[:, :, 0] = 1.0
        self.assertIn("metal where", self.judged(px, targets={"metal": False})["problems"][0])


@unittest.skipUnless(np, "numpy not installed")
class NormalMaps(unittest.TestCase):
    def judged(self, px):
        return pc.judge({"normal": pc.normal_stats(px)})

    def test_flat_map_is_unclear_but_valid(self):
        px = quantise(rgba(0.5, 0.5, 1.0, size=(64, 64)))
        r = self.judged(px)
        self.assertEqual(r["problems"], [])
        self.assertEqual(r["normal"]["convention"], "unclear")
        self.assertAlmostEqual(r["normal"]["length_mean"], 1.0, places=2)

    def test_opengl_bake_detected(self):
        for depth in (8, 16):
            px = quantise(normal_map_from_height(height_bumps()), depth)
            r = self.judged(px)
            self.assertEqual(r["normal"]["convention"], "opengl", "depth %d: %s" % (depth, r["normal"]))
            self.assertEqual(r["problems"], [])

    def test_directx_and_flipped_red_detected(self):
        for kw in ({"green": -1.0}, {"red": -1.0}):
            px = quantise(normal_map_from_height(height_bumps(), **kw))
            r = self.judged(px)
            self.assertEqual(r["normal"]["convention"], "directx", "%s: %s" % (kw, r["normal"]))
            self.assertTrue(any("DirectX" in p for p in r["problems"]))

    def test_inverted_height_still_reads_opengl(self):
        # both channels flipped is a valid surface (dents for bumps): integrability cannot tell, by design
        px = quantise(normal_map_from_height(-height_bumps()))
        self.assertEqual(self.judged(px)["normal"]["convention"], "opengl")

    def test_large_map_pooled(self):
        px = quantise(normal_map_from_height(height_bumps(n=1536)))                            # pooled to 768
        self.assertEqual(pc.normal_convention(px[:, :, :3] * 2 - 1)[0], "opengl")
        flipped = quantise(normal_map_from_height(height_bumps(n=1536), green=-1.0))
        self.assertEqual(pc.normal_convention(flipped[:, :, :3] * 2 - 1)[0], "directx")

    def test_not_a_normal_map(self):
        r = self.judged(rgba(0.5, 0.4, 0.3))                                                   # an albedo
        self.assertTrue(any("mean length" in p for p in r["problems"]))

    def test_pointing_inwards(self):
        px = rgba(0.5, 0.5, 1.0, size=(20, 20))
        px[:5, :, 2] = 0.0                                                                     # z = -1 on a quarter
        self.assertTrue(any("into the surface" in p for p in self.judged(px)["problems"]))

    def test_lean_note(self):
        n = np.array([0.3, 0.0, 0.954])
        px = rgba(*((n + 1) / 2))
        self.assertTrue(any("leans" in m for m in self.judged(px)["notes"]))


@unittest.skipUnless(np, "numpy not installed")
class TilingAndSizes(unittest.TestCase):
    def test_tile_seam(self):
        x = np.linspace(0, 2 * np.pi, 64, endpoint=False)
        periodic = rgba(0.5, 0.5, 0.5, size=(64, 64))
        periodic[:, :, 0] = 0.5 + 0.3 * np.cos(x)[None, :]                                     # wraps at a crest
        periodic[:, :, 1] = 0.5 + 0.3 * np.cos(x)[:, None]
        ts = pc.tile_seam(periodic)
        self.assertLessEqual(max(ts["ratio_x"], ts["ratio_y"]), 1.0)
        # seamless, but the wrap falls on the steepest step of the gradient: the documented legitimate ~1.6
        periodic[:, :, 0] = 0.5 + 0.3 * np.sin(x)[None, :]
        self.assertAlmostEqual(pc.tile_seam(periodic)["ratio_x"], 1.57, delta=0.03)
        ramp = rgba(0.5, 0.5, 0.5, size=(64, 64))
        ramp[:, :, 0] = np.linspace(0.1, 0.9, 64)[None, :]                                     # jumps at the wrap
        self.assertGreater(pc.tile_seam(ramp)["ratio_x"], 10)

    def test_composite(self):
        c = pc.composite_3x3(rgba(0.5, 0.5, 0.5, size=(40, 30)))
        self.assertEqual(c.shape, (120, 90, 4))
        self.assertEqual(pc.composite_3x3(rgba(0.5, 0.5, 0.5, size=(1024, 1024)), max_px=2048).shape[0], 1536)

    def test_sizes(self):
        r = pc.judge({"sizes": {"BaseColor": {"size": [1000, 1024]}, "Normal": {"size": [2048, 2048]}},
                      "map_px": 1024})
        self.assertTrue(any("power of two" in p for p in r["problems"]))
        self.assertTrue(any("larger than map_px" in p for p in r["problems"]))


@unittest.skipUnless(np, "numpy not installed")
class FilesAndCli(unittest.TestCase):
    def test_material_key(self):
        self.assertEqual(pc.material_key("x/T_EXT_Brick_Dark_BaseColor.png"),
                         ("M_EXT_Brick_Dark", "BaseColor", "T_EXT_Brick_Dark"))
        self.assertEqual(pc.material_key("T_PROP_Atlas01_MetallicSmoothness.png")[1], "MetallicSmoothness")
        self.assertEqual(pc.material_key("T_PROP_Crate_AlbedoTransparency.png")[1], "BaseColor")
        self.assertEqual(pc.material_key("T_EXT_Brick_Occlusion.png")[1], "occlusion")
        self.assertEqual(pc.material_key("brick.png"), (None, None, "brick"))

    def write(self, d, name, px, ch=4):
        with open(os.path.join(d, name), "wb") as f:
            f.write(encode_png(np.round(px[:, :, :ch] * 255).astype(int), 8))
        return os.path.join(d, name)

    def set_of_maps(self, d, base=0.5, metal=0.0, green=1.0):
        bc = self.write(d, "T_EXT_Brick_BaseColor.png", rgba(base, base, base, size=(64, 64)), ch=3)
        ms = rgba(metal, 0.0, 0.0, 0.5, size=(64, 64))
        ms[:, :, 3] = np.linspace(0.2, 0.6, 64)[None, :]
        ms = self.write(d, "T_EXT_Brick_MetallicSmoothness.png", ms)
        nm = self.write(d, "T_EXT_Brick_Normal.png", normal_map_from_height(height_bumps(n=64), green=green), ch=3)
        return [bc, ms, nm]

    def test_check_files_groups_by_material(self):
        with tempfile.TemporaryDirectory() as d:
            paths = self.set_of_maps(d) + [self.write(d, "notes.png", rgba(0.5, 0.5, 0.5, size=(4, 4)))]
            res = pc.check_files(paths, map_px=1024)
        self.assertEqual(len(res), 2)
        brick = res[0]
        self.assertEqual(brick["material"], "M_EXT_Brick")
        self.assertEqual(sorted(brick["maps"]), ["BaseColor", "MetallicSmoothness", "Normal"])
        self.assertEqual(brick["problems"], [], brick)
        self.assertEqual(brick["normal"]["convention"], "opengl")
        self.assertIn("not checked", res[1]["notes"][0])

    def test_cli_exit_codes_and_json(self):
        with tempfile.TemporaryDirectory() as d:
            self.set_of_maps(d, base=0.05, green=-1.0)                                          # too dark, DirectX
            out = os.path.join(d, "r.json")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = pc.main([os.path.join(d, "T_*.png"), "--json", out, "--tiling", "--out", d])
            self.assertEqual(code, 1)
            text = buf.getvalue()
            self.assertIn("PROBLEM M_EXT_Brick: base colour too dark", text)
            self.assertIn("DirectX", text)
            with open(out, encoding="utf-8") as f:
                res = json.load(f)
            self.assertTrue(os.path.isfile(res[0]["tile_seam"]["BaseColor"]["composite"]))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pc.main([os.path.join(d, "nothing_*.png")]), 2)

    def test_cli_targets(self):
        with tempfile.TemporaryDirectory() as d:
            self.set_of_maps(d)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = pc.main([os.path.join(d, "T_*.png"), "--targets",
                                json.dumps({"M_EXT_Brick": {"albedo_srgb": [60, 100], "metal": False}})])
            self.assertEqual(code, 1)
            self.assertIn("off target", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
