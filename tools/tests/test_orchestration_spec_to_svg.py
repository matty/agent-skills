"""Tests for skills/vrchat-world-orchestration/scripts/spec_to_svg.py.

Host: plain Python 3.9+, stdlib unittest; PyYAML is optional (the example-spec test skips without it).
Run from the repo root:  python -B -m unittest discover -s tools/tests -p "test_orchestration_*.py"
"""

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_orchestration_spec_validate import HAVE_YAML, SKILL, study_spec

SCRIPT = SKILL / "scripts" / "spec_to_svg.py"


def run_svg(spec_path, out):
    return subprocess.run([sys.executable, "-B", str(SCRIPT), str(spec_path), "--out", str(out)],
                          capture_output=True, text=True)


class Drawings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.spec = self.dir / "spec.json"
        self.spec.write_text(json.dumps(study_spec()), encoding="utf-8")
        self.out = self.dir / "diagrams"

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_the_drawings_and_removes_stale_ones(self):
        self.out.mkdir()
        for name in ("plan_gone.svg", "elevation_old_wall.svg", "tasks.mmd", "lightmap_budget.txt"):
            (self.out / name).write_text("x", encoding="utf-8")
        res = run_svg(self.spec, self.out)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        names = sorted(p.name for p in self.out.iterdir())
        self.assertEqual(names, ["elevation_study_south_inside.svg", "lightmap_budget.txt", "plan_overview.svg",
                                 "plan_study.svg", "tasks.mmd"])
        self.assertIn("removed", res.stdout)

    def test_drawings_are_ascii_and_carry_their_frame(self):
        self.assertEqual(run_svg(self.spec, self.out).returncode, 0)
        for svg in self.out.glob("*.svg"):
            data = svg.read_bytes()
            self.assertTrue(all(b < 128 for b in data), svg.name)
            head = data[:600].decode("ascii")
            for attr in ("data-px-per-m", "data-origin", "data-frame"):
                self.assertIn(attr, head, svg.name)

    def test_elevation_shows_the_door_opening(self):
        self.assertEqual(run_svg(self.spec, self.out).returncode, 0)
        text = (self.out / "elevation_study_south_inside.svg").read_text(encoding="ascii")
        self.assertIn("door 1.2x2.2", text)
        self.assertIn('data-origin="5,1.2"', text)        # the facade's origin, not the drawing's corner
        # facing north, +X runs to the viewer's left: the door bay (x 1-3) is the right-hand piece
        labels = re.findall(r'>(Wall_2x3_A|Door_2x3_A)<', text)
        self.assertEqual(labels, ["Wall_2x3_A", "Door_2x3_A"])

    def test_window_is_drawn_from_its_sill(self):
        spec = study_spec()
        spec["zones"][0]["rooms"][0]["openings"].append(
            {"type": "window", "at": [3.4, 1], "width": 1.2, "height": 1.0, "sill": 1.0})
        self.spec.write_text(json.dumps(spec), encoding="utf-8")
        self.assertEqual(run_svg(self.spec, self.out).returncode, 0)
        text = (self.out / "elevation_study_south_inside.svg").read_text(encoding="ascii")
        px = float(re.search(r'data-px-per-m="([\d.]+)"', text).group(1))
        frame = [float(v) for v in re.search(r'data-frame="([^"]+)"', text).group(1).split()]
        ground = frame[1] + frame[3]                      # the facade's base line in SVG pixels
        rects = re.findall(r'<rect x="[\d.]+" y="([\d.]+)" width="[\d.]+" height="([\d.]+)" fill="#ffffff" '
                           r'fill-opacity="0.85"', text)
        spans = sorted((round((ground - float(y) - float(h)) / px, 2), round((ground - float(y)) / px, 2))
                       for y, h in rects)
        self.assertEqual(spans, [(0.0, 2.2), (1.0, 2.0)])                # the door from the floor, the window 1-2 m
        self.assertIn("window 1.2x1 sill 1", text)

    def test_a_facade_shows_the_openings_of_rooms_in_other_zones(self):
        spec = study_spec()
        hall = {"id": "hall", "name": "Hall", "kind": "interior", "bounds": [0, -4, 6, 1], "floor_z": 0,
                "placements": [],
                "rooms": [{"id": "hall", "name": "Hall", "bounds": [1, -3, 5, 1], "height": 3,
                           "openings": [{"type": "window", "at": [3.4, 1], "width": 1.2, "height": 1.0,
                                         "sill": 1.0}]}]}
        spec["zones"].append(hall)                                        # its room's north edge is the facade line
        self.spec.write_text(json.dumps(spec), encoding="utf-8")
        self.assertEqual(run_svg(self.spec, self.out).returncode, 0)
        text = (self.out / "elevation_study_south_inside.svg").read_text(encoding="ascii")
        self.assertIn("window 1.2x1 sill 1", text)                        # from the hall zone
        self.assertIn("door 1.2x2.2", text)                               # from the study zone

    def test_missing_opening_at_or_view_pos_does_not_crash(self):
        spec = study_spec()
        del spec["zones"][0]["rooms"][0]["openings"][0]["at"]
        del spec["views"][0]["pos"]
        self.spec.write_text(json.dumps(spec), encoding="utf-8")
        res = run_svg(self.spec, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_a_one_number_piece_takes_its_extents_from_size(self):
        def boxes(text):
            px = float(re.search(r'data-px-per-m="([\d.]+)"', text).group(1))
            out = []
            for pts in re.findall(r'<polygon points="([^"]+)" fill="#', text):
                xy = [tuple(map(float, c.split(","))) for c in pts.split()]
                out.append((round((max(x for x, _ in xy) - min(x for x, _ in xy)) / px, 2),
                            round((max(y for _, y in xy) - min(y for _, y in xy)) / px, 2)))
            return out

        self.assertEqual(run_svg(self.spec, self.out).returncode, 0)
        before = boxes((self.out / "plan_study.svg").read_text(encoding="ascii"))
        spec = study_spec()
        spec["pieces"].append({"name": "INT_Post_3_A", "desc": "post", "collision": "box", "size": [0.2, 0.2, 3]})
        spec["zones"][0]["placements"].append({"ref": "INT_Post_3_A", "pos": [1, 1, 0], "rot": 0})
        self.spec.write_text(json.dumps(spec), encoding="utf-8")
        self.assertEqual(run_svg(self.spec, self.out).returncode, 0)
        after = boxes((self.out / "plan_study.svg").read_text(encoding="ascii"))
        self.assertNotIn((0.2, 0.2), before)
        self.assertIn((0.2, 0.2), after)                                  # a 0.2 m post, not a 3 m beam

    def test_a_side_wall_opening_stays_out_of_the_front_elevation(self):
        spec = study_spec()
        # a door in the study's west wall (x 1), its low end 0.2 m from the elevation's line (y 1.2)
        spec["zones"][0]["rooms"][0]["openings"].append({"type": "door", "at": [1, 1.2], "width": 1.0,
                                                          "height": 2.1})
        self.spec.write_text(json.dumps(spec), encoding="utf-8")
        self.assertEqual(run_svg(self.spec, self.out).returncode, 0)
        text = (self.out / "elevation_study_south_inside.svg").read_text(encoding="ascii")
        self.assertIn("door 1.2x2.2", text)                               # the front's own door
        self.assertNotIn("door 1x2.1", text)                              # used to be drawn in the front
        self.assertIn("door 1x2.1", (self.out / "plan_study.svg").read_text(encoding="ascii"))

    def test_grid_module_must_be_positive(self):
        for module in (0, -1):
            spec = study_spec()
            spec["grid"]["module"] = module
            self.spec.write_text(json.dumps(spec), encoding="utf-8")
            res = subprocess.run([sys.executable, "-B", str(SCRIPT), str(self.spec), "--out", str(self.out)],
                                 capture_output=True, text=True, timeout=60)      # used to loop forever
            self.assertEqual(res.returncode, 1, res.stdout)
            self.assertIn("grid.module must be a positive number", res.stdout)
            self.assertNotIn("Traceback", res.stderr)

    def test_a_drawing_with_a_wrong_type_is_reported_and_the_rest_drawn(self):
        spec = study_spec()
        spec["zones"][0]["rooms"][0]["height"] = "3"                      # the plan prints it as a number
        self.spec.write_text(json.dumps(spec), encoding="utf-8")
        res = run_svg(self.spec, self.out)
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("ERROR plan_study.svg skipped", res.stdout)
        self.assertNotIn("Traceback", res.stderr)
        self.assertTrue((self.out / "elevation_study_south_inside.svg").exists())

    def test_mirrors_are_drawn_on_the_plan(self):
        spec = study_spec()
        spec["zones"][0]["mirrors"] = [{"id": "m1", "pos": [3, 4.8, 1.6], "rot": 0, "size": [1.2, 2.0]}]
        self.spec.write_text(json.dumps(spec), encoding="utf-8")
        self.assertEqual(run_svg(self.spec, self.out).returncode, 0)
        self.assertIn("mirror m1 1.2x2", (self.out / "plan_study.svg").read_text(encoding="ascii"))

    def test_a_spec_without_a_world_name_still_draws(self):
        spec = study_spec()
        del spec["world"]["name"]
        self.spec.write_text(json.dumps(spec), encoding="utf-8")
        res = run_svg(self.spec, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue((self.out / "plan_overview.svg").exists())

    @unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
    def test_example_spec_draws(self):
        res = run_svg(SKILL / "references" / "example-spec.yaml", self.out)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(sorted(p.name for p in self.out.glob("*.svg")),
                         ["elevation_square_north_row.svg", "plan_overview.svg", "plan_square.svg"])


if __name__ == "__main__":
    unittest.main()
