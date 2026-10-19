"""Plain-Python tests for 3d-form-design's scripts/form_spec.py: every template passes with no failing problem, and
each failing rule fires on a spec broken for it (a floating part, a primitive box, flat or bevelled upholstery, an
undecided part, a bevelled contact edge, a bevel over the material's size or a quarter of the part, tiers out of
order or all equal, a key dimension out of range, missing anatomy), the 2 px floor per display, check_build against
built sizes (missing, short count, wrong size, rotated) and the CLI's exit code.

Host: plain Python 3.9+, standard library. Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_form_design_*.py"
"""

import copy
import glob
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "3d-form-design"
SCRIPT = SKILL / "scripts" / "form_spec.py"


def load():
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("form_spec_under_test", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = keep


fs = load()
TEMPLATES = sorted(glob.glob(str(SKILL / "templates" / "*.json")))


def failing(spec):
    return [k for k, _ in fs.validate(spec) if not k.startswith("warn_")]


def keys(spec):
    return [k for k, _ in fs.validate(spec)]


def table():
    return fs.load(str(SKILL / "templates" / "dining_table.json"))


def part(spec, name):
    return next(p for p in spec["parts"] if p["name"] == name)


class Templates(unittest.TestCase):
    def test_every_template_passes(self):
        self.assertGreaterEqual(len(TEMPLATES), 5)
        for path in TEMPLATES:
            with self.subTest(template=os.path.basename(path)):
                spec = fs.load(path)
                self.assertEqual(fs.validate(spec), [])
                self.assertIn(spec["type"], fs.TYPE_RULES)


class Rules(unittest.TestCase):
    def test_floating_part(self):
        s = table()
        part(s, "apron_long")["attach_to"] = "nothing"
        self.assertIn("floating_part", failing(s))
        s = table()
        part(s, "leg")["attach_to"] = "top"
        self.assertIn("floating_part", failing(s))     # nothing reaches the floor any more

    def test_primitive_box(self):
        s = table()
        part(s, "leg")["shape"] = {}
        self.assertIn("primitive_box", failing(s))
        part(s, "leg")["shape"] = {"box_ok": "square Parsons legs"}
        self.assertNotIn("primitive_box", failing(s))
        self.assertNotIn("warn_untapered_leg", keys(s))
        # a board is fine as a box
        self.assertNotIn("primitive_box", failing(table()))

    def test_upholstery(self):
        s = fs.load(str(SKILL / "templates" / "sofa.json"))
        c = part(s, "seat_cushion")
        c["shape"] = {}
        c["build"] = "box"
        k = failing(s)
        self.assertIn("flat_upholstery", k)
        self.assertIn("upholstery_build", k)
        s = fs.load(str(SKILL / "templates" / "sofa.json"))
        part(s, "arm")["edges"] = [{"where": "front top edge", "tier": "secondary"}]
        self.assertIn("soft_bevelled", failing(s))

    def test_edges(self):
        s = table()
        part(s, "leg")["edges"] = []
        self.assertIn("edges_undecided", failing(s))
        s = table()
        part(s, "leg")["edges"].append({"where": "foot edges on the floor", "tier": "secondary"})
        self.assertIn("contact_bevelled", failing(s))
        s = table()
        part(s, "leg")["edges"].append({"where": "outer corner", "tier": "primary", "mm": 12})
        k = failing(s)
        self.assertIn("over_material", k)       # wood tops out at 6 mm
        s = table()
        part(s, "apron_long")["edges"] = [{"where": "lower outer edge", "tier": "primary", "mm": 6}]
        self.assertIn("over_cap", failing(s))    # a quarter of 22 mm is 5.5
        s = table()
        part(s, "leg")["edges"] = [{"where": "corners", "tier": "secondary"}]
        self.assertIn("warn_no_sharp_edge", keys(s))
        s = table()
        part(s, "leg")["edges"][0]["tier"] = "huge"
        self.assertIn("edge_tier", failing(s))

    def test_tiers(self):
        s = table()
        s["bevel_tiers_mm"] = {"primary": 2, "secondary": 3, "small": 1}
        self.assertIn("tier_order", failing(s))
        s["bevel_tiers_mm"] = {"primary": 3, "secondary": 3, "small": 3}
        self.assertIn("one_bevel_width", failing(s))

    def test_floor(self):
        s = table()
        self.assertAlmostEqual(fs.floor_mm(s), 2 * 1.5 * 1000 / 1150, places=6)
        s["view"]["display"] = "screen1080"
        self.assertAlmostEqual(fs.floor_mm(s), 3.2075, places=3)
        s["view"]["usual_m"] = 4.0
        self.assertIn("warn_under_floor", keys(s))   # 3 mm edges seen from 4 m on a screen

    def test_key_dims_and_anatomy(self):
        s = table()
        s["key_dims"]["height"] = 900
        self.assertIn("key_dim_range", failing(s))
        s = table()
        del s["key_dims"]["overhang"]
        self.assertIn("warn_key_dim", keys(s))
        s = table()
        s["parts"] = [p for p in s["parts"] if p["role"] != "apron"]
        self.assertIn("missing_anatomy", failing(s))
        s = table()
        s["type"] = "hat_stand"
        self.assertIn("warn_type", keys(s))

    def test_malformed(self):
        s = table()
        del s["parts"]
        self.assertIn("missing_field", failing(s))
        s = table()
        part(s, "leg")["size"] = [60, 60]
        self.assertIn("part_size", failing(s))
        s = table()
        part(s, "leg")["made"] = "unobtainium"
        self.assertIn("part_made", failing(s))


class Build(unittest.TestCase):
    def test_check_build(self):
        s = table()
        built = {"top": (1800, 900, 25), "leg": (60, 60, 725), "leg.001": (60, 60, 725), "leg.002": (60, 60, 725),
                 "leg.003": (60, 725, 60), "apron_long": (1580, 22, 90), "apron_long.001": (1580, 22, 91),
                 "apron_short": (680, 22, 90), "apron_short.001": (680, 22, 90)}
        self.assertEqual(fs.check_build(s, built), [])        # rotated leg and a 1 mm slip are fine
        b = dict(built)
        del b["top"]
        self.assertIn("part_missing", [k for k, _ in fs.check_build(s, b)])
        b = dict(built)
        del b["leg.003"]
        self.assertIn("part_count", [k for k, _ in fs.check_build(s, b)])
        b = dict(built)
        b["leg"] = (60, 60, 760)
        self.assertIn("part_size", [k for k, _ in fs.check_build(s, b)])


class Cli(unittest.TestCase):
    def test_exit_codes(self):
        run = subprocess.run([sys.executable, "-B", str(SCRIPT), TEMPLATES[0]], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("spec ok", run.stdout)
        s = table()
        part(s, "leg")["attach_to"] = "nothing"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(s, fh)
            run = subprocess.run([sys.executable, "-B", str(SCRIPT), path], capture_output=True, text=True)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("floating_part", run.stdout)


if __name__ == "__main__":
    unittest.main()
