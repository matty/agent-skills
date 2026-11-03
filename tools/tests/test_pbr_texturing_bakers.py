"""Plain-Python tests for the pbr-texturing skill's scripts/bakers.py: which baker choose_baker() picks (the project's
choice, the default order, an unattended run, maps a baker lacks, thin parts, one baker per texture set) and why,
detect_bakers() with fake installs, and the output gate check_outputs() every baker's maps pass.

Host: plain Python 3.9+, standard library. Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_pbr_texturing_bakers.py"
"""

import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "pbr-texturing" / "scripts"


def load(name):
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True            # never leave a __pycache__ in the skill
    try:
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        return __import__(name)
    finally:
        sys.dont_write_bytecode = keep


bk = load("bakers")
tb = load("toolbag_bake")

ALL = {"toolbag": True, "substance": True, "cycles": True}


def write_png(path, w, h, bits=16, channels=3):
    """A flat grey PNG of the given size and depth (only the header matters to the gate without numpy)."""
    ctype = {1: 0, 3: 2, 4: 6}[channels]
    px = (b"\x80\x00" if bits == 16 else b"\x80") * channels * w
    raw = b"".join(b"\x00" + px for _ in range(h))

    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, bits, ctype, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Choose(unittest.TestCase):
    def test_default_order(self):
        name, reason, order = bk.choose_baker(["normal", "ao"], ALL)
        self.assertEqual(name, "toolbag")
        self.assertEqual(order, ["toolbag", "substance", "cycles"])
        self.assertIn("default order", reason)

    def test_auto_is_no_preference(self):
        self.assertEqual(bk.choose_baker(["normal"], ALL, preference="auto")[0], "toolbag")

    def test_project_choice_wins(self):
        name, reason, order = bk.choose_baker(["normal"], ALL, preference="cycles")
        self.assertEqual(name, "cycles")
        self.assertIn("tools.mesh_baker: cycles", reason)
        self.assertEqual(order[0], "cycles")

    def test_unavailable_choice_falls_to_order_and_says_why(self):
        name, reason, _ = bk.choose_baker(["normal"], {"toolbag": False, "substance": True, "cycles": True},
                                          preference="toolbag")
        self.assertEqual(name, "substance")
        self.assertIn("toolbag dropped (not available)", reason)

    def test_unattended_drops_toolbag(self):
        name, _, order = bk.choose_baker(["normal"], ALL, preference="toolbag", unattended=True)
        self.assertEqual(name, "substance")
        self.assertNotIn("toolbag", order)

    def test_transfer_maps_skip_substance(self):
        name, _, order = bk.choose_baker(["normal", "basecolor"], {"toolbag": False, "substance": True,
                                                                   "cycles": True})
        self.assertEqual((name, order), ("cycles", ["cycles"]))

    def test_thin_parts_prefer_native_backfaces(self):
        avail = {"toolbag": False, "substance": True, "cycles": True}
        self.assertEqual(bk.choose_baker(["normal"], avail, thin_parts=True)[0], "substance")
        # the project's choice still wins
        self.assertEqual(bk.choose_baker(["normal"], avail, preference="cycles", thin_parts=True)[0], "cycles")

    def test_one_baker_per_texture_set(self):
        name, reason, _ = bk.choose_baker(["normal"], ALL, preference="toolbag", atlas_baker="cycles")
        self.assertEqual(name, "cycles")
        self.assertIn("one baker per set", reason)

    def test_driven_only(self):
        _, _, order = bk.choose_baker(["normal"], ALL, driven_only=True)
        self.assertEqual(order, ["toolbag", "cycles"])

    def test_detect_output_accepted(self):
        avail = {"toolbag": {"ok": False}, "substance": {"ok": False}, "cycles": {"ok": True}}
        self.assertEqual(bk.choose_baker(["normal"], avail)[0], "cycles")

    def test_nothing_fits(self):
        with self.assertRaises(ValueError) as cm:
            bk.choose_baker(["thickness"], {"toolbag": False, "substance": False, "cycles": True})
        self.assertIn("cycles: no thickness", str(cm.exception))

    def test_unknown_preference(self):
        with self.assertRaises(ValueError):
            bk.choose_baker(["normal"], ALL, preference="xnormal")

    def test_bakers_tuple(self):
        self.assertEqual(bk.MESH_BAKERS, ("toolbag", "substance", "cycles"))
        for b in bk.MESH_BAKERS:
            self.assertIn("normal", bk.BAKER_MAPS[b])


class Detect(unittest.TestCase):
    def setUp(self):
        self.keep = tb.find_toolbag

    def tearDown(self):
        tb.find_toolbag = self.keep

    def test_nothing_installed(self):
        tb.find_toolbag = lambda *a, **k: None
        out = bk.detect_bakers(substance_exe=None, run=None)
        if bk.find_substance_baker() is None:
            self.assertFalse(out["substance"]["ok"])
        self.assertFalse(out["toolbag"]["ok"])
        self.assertTrue(out["cycles"]["ok"])

    def test_found_not_probed(self):
        out = bk.detect_bakers(probe_toolbag=False, toolbag_exe="C:/tb/toolbag.exe", substance_exe="sb.exe",
                               run=lambda cmd, **k: SimpleNamespace(returncode=0))
        self.assertTrue(out["toolbag"]["ok"])
        self.assertIn("not probed", out["toolbag"]["detail"])
        self.assertTrue(out["substance"]["ok"])

    def test_substance_that_fails(self):
        out = bk.detect_bakers(probe_toolbag=False, toolbag_exe="tb", substance_exe="sb.exe",
                               run=lambda cmd, **k: SimpleNamespace(returncode=3))
        self.assertFalse(out["substance"]["ok"])

    def test_probe_failure_means_unusable(self):
        keep = tb.probe
        try:
            def boom(*a, **k):
                raise TimeoutError("no result")
            tb.probe = boom
            out = bk.detect_bakers(toolbag_exe="tb.exe", substance_exe="sb", run=lambda c, **k: SimpleNamespace(
                returncode=0))
            self.assertFalse(out["toolbag"]["ok"])
            self.assertIn("probe failed", out["toolbag"]["detail"])
        finally:
            tb.probe = keep


class Gate(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def png(self, name, w=8, h=8, bits=16):
        p = os.path.join(self.dir, name)
        write_png(p, w, h, bits)
        return p

    def test_passes(self):
        g = bk.check_outputs({"normal": self.png("T_A_Normal.png"), "ao": self.png("T_A_AO.png", bits=8)}, (8, 8),
                             convention=False)
        self.assertTrue(g["ok"], g)

    def test_wrong_size(self):
        g = bk.check_outputs({"ao": self.png("T_A_AO.png", 4, 8)}, (8, 8), convention=False)
        self.assertIn("ao: 4x8, asked 8x8", g["problems"])

    def test_eight_bit_normal(self):
        g = bk.check_outputs({"normal": self.png("T_A_Normal.png", bits=8)}, (8, 8), convention=False)
        self.assertFalse(g["ok"])
        self.assertIn("16", g["problems"][0])

    def test_missing_and_misnamed(self):
        g = bk.check_outputs({"normal": os.path.join(self.dir, "none.png"), "ao": self.png("T_A_ao.png")}, (8, 8),
                             convention=False)
        self.assertEqual(len(g["problems"]), 2)
        self.assertTrue(any("does not end in _AO" in p for p in g["problems"]))


if __name__ == "__main__":
    unittest.main()
