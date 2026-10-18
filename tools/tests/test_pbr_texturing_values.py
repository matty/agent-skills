"""Plain-Python tests that pin pbr_check.py's base-colour limits to measured materials (https://physicallybased.info,
linear values read 2026-10-18 and converted to sRGB codes here): real dielectrics from charcoal to snow and real metals
from titanium to silver raise no PROBLEM (charcoal, tyre rubber and titanium get a NOTE), while a lab ultra-black and a
lab white standard fail, as they should in a game texture.

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
        spec = importlib.util.spec_from_file_location("pbr_check_values_under_test", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = keep


pc = load()

# name: linear colour (physicallybased.info, 2026-10-18)
DIELECTRICS = {"Charcoal": (0.02, 0.02, 0.02), "Tire": (0.023, 0.023, 0.023), "Blackboard": (0.039, 0.039, 0.039),
               "Brick": (0.262, 0.095, 0.061), "Gray Card": (0.18, 0.18, 0.18), "Sand": (0.44, 0.386, 0.23074),
               "Concrete": (0.51, 0.51, 0.51), "Marble": (0.83, 0.791, 0.753), "Office Paper": (0.794, 0.834, 0.884),
               "Snow": (0.85, 0.85, 0.85)}
METALS = {"Titanium": (0.441, 0.4, 0.361), "Iron": (0.53, 0.513, 0.494), "Tungsten": (0.537, 0.536, 0.519),
          "Chromium": (0.654, 0.685, 0.701), "Stainless Steel": (0.669, 0.639, 0.598), "Copper": (0.932, 0.623, 0.522),
          "Brass": (0.91, 0.778, 0.423), "Gold": (1.059, 0.773, 0.307), "Aluminum": (0.916, 0.923, 0.924),
          "Silver": (0.991, 0.985, 0.974)}
LAB = {"Musou Black": (0.006, 0.006, 0.006), "Spectralon": (0.99, 0.99, 0.99)}


def srgb(c):
    c = min(max(c, 0.0), 1.0)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def swatch(linear, metal=False, n=16):
    codes = [round(srgb(c) * 255) / 255.0 for c in linear]           # as an 8-bit texture stores it
    px = np.ones((n, n, 4), np.float32)
    px[:, :, :3] = codes
    metallic = np.full((n, n), 1.0 if metal else 0.0, np.float32)
    return pc.judge({"base_color": pc.base_color_stats(px, {"channels": 3}, metallic)})


@unittest.skipUnless(np, "numpy not installed")
class MeasuredMaterials(unittest.TestCase):
    def test_real_dielectrics_pass(self):
        for name, lin in DIELECTRICS.items():
            r = swatch(lin)
            self.assertEqual(r["problems"], [], name)
        for name in ("Charcoal", "Tire"):                            # luma 39 and 42: between 30 and the strict 50
            self.assertTrue(any("strict" in n for n in swatch(DIELECTRICS[name])["notes"]), name)
        self.assertEqual(swatch(DIELECTRICS["Blackboard"])["notes"], [])

    def test_real_metals_pass(self):
        for name, lin in METALS.items():
            self.assertEqual(swatch(lin, metal=True)["problems"], [], name)
        notes = swatch(METALS["Titanium"], metal=True)["notes"]
        self.assertTrue(any("titanium" in n for n in notes), notes)
        self.assertEqual(swatch(METALS["Iron"], metal=True)["notes"], [])

    def test_lab_extremes_fail(self):
        self.assertTrue(any("too dark" in p for p in swatch(LAB["Musou Black"])["problems"]))
        self.assertTrue(any("too bright" in p for p in swatch(LAB["Spectralon"])["problems"]))

    def test_dark_paint_on_metal_fails(self):
        # a metal painted dark grey is a dielectric: metallic 0, not a dark metal
        self.assertTrue(any("metal too dark" in p for p in swatch((0.1, 0.1, 0.1), metal=True)["problems"]))


if __name__ == "__main__":
    unittest.main()
