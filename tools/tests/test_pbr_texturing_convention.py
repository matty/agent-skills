"""Plain-Python tests for pbr_check.py's normal-map convention test on maps shaped like real bakes: an atlas of islands
on a neutral background (hard island borders), the same with smoothed gutters (the diffusion fill bakers write), and
islands that are rotated or mirrored in UV space (their slope fields stay integrable). These are the cases that made a
curl-ratio test call the Substance 3D baker's DirectX default "unclear"; the correlation must stay decisive.

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
SCRIPT = ROOT / "skills" / "pbr-texturing" / "scripts" / "pbr_check.py"


def load():
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("pbr_check_convention_under_test", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = keep


pc = load()


def island_normals(n, seed):
    """OpenGL normals (decoded, rows top to bottom) of a bumpy, bevel-edged square island of n x n pixels."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float64)
    edge = np.minimum.reduce([xx, yy, n - 1 - xx, n - 1 - yy])
    h = -np.clip(1.0 - edge / (0.12 * n), 0.0, None) * 0.08 * n          # a bevel falling off at the border
    for _ in range(4):
        cx, cy, r = rng.uniform(0.2, 0.8, 2).tolist() + [rng.uniform(0.05, 0.12)]
        h += np.exp(-((xx - cx * n) ** 2 + (yy - cy * n) ** 2) / (2 * (r * n) ** 2)) * 0.15 * n
    hx, hy = np.gradient(h, axis=1), -np.gradient(h, axis=0)
    v = np.dstack([-hx, -hy, np.ones_like(h)])
    return v / np.linalg.norm(v, axis=2, keepdims=True)


def atlas(size=512, cells=3, transform=None, blur=0):
    """A cells x cells atlas of islands on a flat (0, 0, 1) background with gaps; transform(k, island) may rotate or
    mirror island k's pixels and vectors together, as a UV island rotated or mirrored in the layout is."""
    out = np.zeros((size, size, 3))
    out[:, :, 2] = 1.0
    step = size // cells
    pad = step // 8
    k = 0
    for r in range(cells):
        for c in range(cells):
            isl = island_normals(step - 2 * pad, seed=k)
            if transform:
                isl = transform(k, isl)
            out[r * step + pad:(r + 1) * step - pad, c * step + pad:(c + 1) * step - pad] = isl
            k += 1
    if blur:                                   # a crude diffusion of everything: box blur, renormalised
        for _ in range(blur):
            out = (out + np.roll(out, 1, 0) + np.roll(out, -1, 0) + np.roll(out, 1, 1) + np.roll(out, -1, 1)) / 5.0
        out /= np.linalg.norm(out, axis=2, keepdims=True)
    return out


def encode8(v):
    return np.round((v + 1.0) / 2.0 * 255.0) / 255.0 * 2.0 - 1.0          # an 8-bit round trip


def rotate90(k, isl):
    """Rotate an island's pixels a quarter turn counter-clockwise; its tangent frame turns with it, so the stored
    vectors are the same surface seen in the rotated UVs: (x, y) of each vector rotates the same way."""
    if k % 2 == 0:
        return isl
    rot = np.rot90(isl, 1, axes=(0, 1)).copy()
    x, y = rot[:, :, 0].copy(), rot[:, :, 1].copy()
    rot[:, :, 0], rot[:, :, 1] = -y, x
    return rot


def mirror_u(k, isl):
    """Mirror an island in U (a mirrored half): pixels flip left-right and the stored X flips with the tangent."""
    if k % 3 != 1:
        return isl
    m = isl[:, ::-1].copy()
    m[:, :, 0] = -m[:, :, 0]
    return m


@unittest.skipUnless(np, "numpy not installed")
class ConventionOnAtlases(unittest.TestCase):
    def verdict(self, v):
        return pc.normal_convention(encode8(v))

    def flipped(self, v):
        f = v.copy()
        f[:, :, 1] = -f[:, :, 1]
        return f

    def test_hard_island_borders(self):
        v = atlas()
        conv, r, _n = self.verdict(v)
        self.assertEqual(conv, "opengl", r)
        self.assertGreater(r, 0.5)
        conv, r, _n = self.verdict(self.flipped(v))
        self.assertEqual(conv, "directx", r)

    def test_smoothed_gutters(self):
        v = atlas(blur=6)
        self.assertEqual(self.verdict(v)[0], "opengl")
        self.assertEqual(self.verdict(self.flipped(v))[0], "directx")

    def test_rotated_and_mirrored_islands(self):
        for t in (rotate90, mirror_u):
            v = atlas(transform=t)
            conv, r, _n = self.verdict(v)
            self.assertEqual(conv, "opengl", "%s: r %s" % (t.__name__, r))
            self.assertEqual(self.verdict(self.flipped(v))[0], "directx", t.__name__)

    def test_r_is_symmetric_under_the_flip(self):
        v = atlas()
        r = self.verdict(v)[1]
        self.assertAlmostEqual(self.verdict(self.flipped(v))[1], -r, places=2)

    def test_straight_grooves_only_are_unclear(self):
        # a height that varies along one axis only has no mixed derivative: nothing to decide on
        n = 256
        x = np.linspace(0, 8 * np.pi, n)
        hx = np.tile(np.cos(x)[None, :], (n, 1)) * 0.5
        v = np.dstack([-hx, np.zeros((n, n)), np.ones((n, n))])
        v /= np.linalg.norm(v, axis=2, keepdims=True)
        self.assertEqual(self.verdict(v)[0], "unclear")

    def test_noise_is_unclear(self):
        rng = np.random.default_rng(9)
        v = np.dstack([rng.normal(0, 0.2, (256, 256)), rng.normal(0, 0.2, (256, 256)), np.ones((256, 256))])
        v /= np.linalg.norm(v, axis=2, keepdims=True)
        conv, r, _n = self.verdict(v)
        self.assertEqual(conv, "unclear", r)
        self.assertLess(abs(r), 0.1)


if __name__ == "__main__":
    unittest.main()
