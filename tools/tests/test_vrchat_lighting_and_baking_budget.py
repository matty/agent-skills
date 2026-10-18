"""Tests for skills/vrchat-lighting-and-baking/scripts/lightmap_budget.py (plain Python, stdlib only).

Run from the repo root: python -B -m unittest discover -s tools/tests -p "test_*.py"
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "vrchat-lighting-and-baking" / "scripts" / "lightmap_budget.py"

spec = importlib.util.spec_from_file_location("lightmap_budget", SCRIPT)
lb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lb)

GAP_8_AT_512 = 8 / 512
GAP_4_AT_512 = 4 / 512

# the dry run's one-room world (Unity 2022.3.22f1, 2026-10-16): one 1024 map at 60 texels/m fitted
DRY_RUN = [
    {"name": "INT_Wall_2x3_A", "size": [2, 3, 0.2], "count": 7, "gap_uv": GAP_8_AT_512},
    {"name": "INT_Door_2x3_A", "area_m2": 14.22, "count": 1, "gap_uv": GAP_8_AT_512},
    {"name": "STR_Floor_2x2_A", "size": [2, 2, 0.1], "count": 4, "gap_uv": GAP_8_AT_512},
    {"name": "STR_Ceiling_2x2_A", "size": [2, 2, 0.1], "count": 4, "gap_uv": GAP_8_AT_512},
    {"name": "PROP_Desk_Free_A", "area_m2": 5.5, "count": 1, "gap_uv": GAP_8_AT_512},
    {"name": "PROP_LightSwitch_Free_A", "area_m2": 0.02, "count": 1},
]

# a 6 x 5 x 3 m room with single-mesh walls and two small props (the round-2 reviewer's case)
ROOM = [
    {"name": "INT_Wall_6x3_A", "size": [6, 3, 0.2], "count": 2, "gap_uv": GAP_4_AT_512},
    {"name": "INT_Wall_5x3_A", "size": [5, 3, 0.2], "count": 2, "gap_uv": GAP_4_AT_512},
    {"name": "STR_Floor_6x5_A", "size": [6, 5, 0.2], "count": 2, "gap_uv": GAP_4_AT_512},
    {"name": "PROP_Desk_Free_A", "area_m2": 5.5, "count": 1, "gap_uv": 0.03},
    {"name": "PROP_Door_Free_A", "area_m2": 4.2, "count": 1, "gap_uv": 0.03},
]


def clean_at(pieces, t, max_px, maps=1):
    rows, s = lb.evaluate([lb.normalise(p) for p in pieces], t, max_px, maps)
    return lb.is_clean(rows, s), s


class Constants(unittest.TestCase):
    def test_canonical_values(self):
        self.assertEqual(lb.COVERAGE, 0.85)
        self.assertEqual(lb.PLAN_FILL, 0.65)
        self.assertEqual(lb.ERROR_FILL, 0.80)
        self.assertEqual(lb.MIN_PADDING_TEXELS, 2.0)
        self.assertEqual(lb.PROBE_LIT_BELOW_PX, 64.0)


class Footprint(unittest.TestCase):
    def test_box_area(self):
        self.assertAlmostEqual(lb.surface_area([2, 3, 0.2]), 14.0)
        self.assertAlmostEqual(lb.surface_area(8.8), 8.8)

    def test_measured_wall_planning_b(self):
        # 2 x 3 x 0.2 m wall at 60 texels/m got 242.8 px; its UV2 bounding-box share was 0.850
        self.assertAlmostEqual(lb.footprint_px(60, 14.0), 243, delta=1.0)

    def test_measured_desk_with_its_b(self):
        # the desk's measured b (0.952) predicts 144 px; Unity gave it 143.4
        self.assertAlmostEqual(lb.footprint_px(60, 5.501, 1.0, 0.952), 143.4, delta=1.5)

    def test_pack_gap_keeps_two_texels_at_b_1(self):
        g = lb.pack_gap_uv(60, 5.5)
        self.assertAlmostEqual(g * lb.footprint_px(60, 5.5, 1.0, 1.0), 2.0, places=9)

    def test_scale_in_lightmap(self):
        self.assertAlmostEqual(lb.footprint_px(60, 14.0, 0.5), lb.footprint_px(60, 14.0) / 2)


class Kinds(unittest.TestCase):
    def test_kind_from_name_and_explicit(self):
        self.assertEqual(lb.normalise({"name": "PROP_Desk_Free_A", "area_m2": 5})["kind"], "prop")
        self.assertEqual(lb.normalise({"name": "INT_Wall_2x3_A", "area_m2": 14})["kind"], "grid")
        self.assertEqual(lb.normalise({"name": "anything", "area_m2": 1})["kind"], "grid")
        self.assertEqual(lb.normalise({"name": "x", "area_m2": 1, "kind": "shell"})["kind"], "grid")
        self.assertEqual(lb.normalise({"name": "PROP_Chair_Free_A", "area_m2": 1, "kind": "lightmap"})["kind"],
                         "lightmap")
        self.assertEqual(lb.normalise({"name": "INT_Wall_2x3_A", "area_m2": 14, "kind": "prop"})["kind"], "prop")
        self.assertEqual(lb.normalise({"name": "x", "area_m2": 1, "lightmap": False})["kind"], "probe")

    def test_free_props_only_in_probe_lit_families(self):
        self.assertEqual(lb.PROBE_LIT_FAMILIES, ("PROP", "FOL"))
        self.assertEqual(lb.normalise({"name": "PROP_Chair_Free_A", "area_m2": 1})["kind"], "prop")
        self.assertEqual(lb.normalise({"name": "FOL_Bush_Free_A", "area_m2": 1})["kind"], "prop")
        # a Free-sized ZONE shell is a grid piece: lightmapped and counted however small
        self.assertEqual(lb.normalise({"name": "ZONE_Courtyard_Free_A", "area_m2": 1})["kind"], "grid")
        rows, s = lb.plan([{"name": "ZONE_Courtyard_Free_A", "size": [15, 15, 0.5], "count": 1}], 2, 1024)
        self.assertEqual(rows[0]["status"], "small")
        self.assertGreater(s["need_px2"], 0)

    def test_small_grid_piece_is_a_note_and_stays_counted(self):
        # a modular room at 15 texels/m: 2 x 3 x 0.2 m walls come to about 61 px
        rows, s = lb.plan([{"name": "INT_Wall_2x3_A", "size": [2, 3, 0.2], "count": 8}], 15, 1024)
        self.assertEqual(rows[0]["status"], "small")
        self.assertGreater(s["need_px2"], 0)
        self.assertTrue(any("grid piece" in n for n in s["notes"]))
        self.assertFalse(s["warnings"] or s["errors"])
        self.assertTrue(any(lo <= 15 <= hi for lo, hi in s["window_clean"]))

    def test_outdoor_kit_at_table_densities_is_clean(self):
        # facades and roofs at the table's 6-10 texels/m sit under 64 px: notes only, never an unclean window
        pieces = [{"name": "GRD_Ground_10x10_A", "size": [10, 10, 0.2], "count": 4},
                  {"name": "EXT_Facade_4x4_A", "size": [4, 4, 0.2], "count": 12},
                  {"name": "EXT_Roof_4x4_A", "size": [4, 4, 0.2], "count": 6}]
        for t in (4, 6, 8):
            rows, s = lb.plan(pieces, t, 1024)
            self.assertFalse(s["errors"] or s["warnings"], t)
            self.assertTrue(any(lo <= t <= hi for lo, hi in s["window_clean"]), t)

    def test_lightmap_kind_for_switched_props(self):
        # a 15 px chair that must change with a light switch: counted, no 64 px note, the window stays clean
        rows, s = lb.plan([{"name": "PROP_Chair_Free_A", "area_m2": 0.3, "count": 10, "kind": "lightmap"}], 4, 512,
                          states=2)
        self.assertEqual(rows[0]["status"], "lightmap")
        self.assertGreater(s["need_px2"], 0)
        self.assertFalse(s["notes"] or s["warnings"] or s["errors"])
        self.assertTrue(any(lo <= 4 <= hi for lo, hi in s["window_clean"]))

    def test_small_prop_is_probe_lit_and_left_out(self):
        rows, s = lb.plan([{"name": "PROP_Switch_Free_A", "area_m2": 0.02, "count": 50}], 60, 512)
        self.assertEqual(rows[0]["status"], "probe-lit")
        self.assertEqual(s["need_px2"], 0.0)
        self.assertFalse(s["errors"])

    def test_probe_kind_always_probe_lit(self):
        rows, s = lb.plan([{"name": "big", "area_m2": 50, "kind": "probe", "gap_uv": 0.001}], 60, 1024)
        self.assertEqual(rows[0]["status"], "probe-lit")
        self.assertFalse(s["errors"])


class Plan(unittest.TestCase):
    def test_padding_error_reproduces_dry_run(self):
        # like the dry run's first bake: walls at about 113 px (28 texels/m) with 8 px @ 512 gaps
        rows, s = lb.plan([{"name": "wall", "size": [2, 3, 0.2], "count": 8, "gap_uv": GAP_8_AT_512}], 28, 512)
        self.assertEqual(rows[0]["status"], "padding")
        self.assertLess(rows[0]["padding_texels"], 2.0)
        self.assertTrue(s["errors"])

    def test_measured_b_relaxes_the_check(self):
        piece = {"name": "desk", "area_m2": 5.5, "kind": "grid", "gap_uv": 0.0136}
        rows, s = lb.plan([piece], 62, 1024)                      # b = 1 worst case: 1.98 texels
        self.assertEqual(rows[0]["status"], "padding")
        rows, s = lb.plan([dict(piece, b=0.95)], 62, 1024)        # measured b: 2.03 texels
        self.assertEqual(rows[0]["status"], "lightmap")

    def test_thresholds(self):
        def fill_for(fill):
            area = fill * 1024 ** 2 / 20.0 ** 2      # 20 texels/m: the chart box costs 20^2 x area = fill x 1024^2
            return lb.plan([{"name": "p", "area_m2": area, "count": 1}], 20, 1024)[1]
        self.assertFalse(fill_for(0.64)["errors"] or fill_for(0.64)["warnings"])
        self.assertTrue(fill_for(0.70)["warnings"] and not fill_for(0.70)["errors"])
        fit = fill_for(0.779)                     # 16 equal full-tile squares (box = tile) fitted one map at 0.779
        self.assertFalse(fit["errors"])
        self.assertTrue(fill_for(0.85)["errors"])

    def test_dry_run_final_bake_is_workable(self):
        # in chart-box terms the dry run's final 1024 bake filled about 0.65 (0.77 counted as whole tiles)
        rows, s = lb.plan(DRY_RUN, 60, 1024)
        self.assertFalse(s["errors"])
        self.assertAlmostEqual(s["fill"], 0.646, delta=0.005)
        self.assertTrue(any(lo <= 60 <= hi for lo, hi in s["window_ok"]))

    def test_box_cost_ignores_the_uv2_layout(self):
        # Unity packs the chart box: (texels/m x scale)^2 x area, whatever b is (measured 24,002 vs 24,000 px^2)
        a = lb.plan([{"name": "w", "area_m2": 14, "b": 0.5}], 20, 1024)[1]["need_px2"]
        b = lb.plan([{"name": "w", "area_m2": 14, "b": 1.0}], 20, 1024)[1]["need_px2"]
        self.assertAlmostEqual(a, b)
        self.assertAlmostEqual(a, 20 ** 2 * 14)
        self.assertAlmostEqual(lb.box_cost_px2(20, 14, 1.0, 0), lb.footprint_px(20, 14, 1.0, 0.5) ** 2 * 0.5)

    def test_lods_add_quarter_cost_each(self):
        base = lb.plan([{"name": "s", "area_m2": 28, "count": 3}], 20, 1024)[1]["need_px2"]
        rows, s = lb.plan([{"name": "s", "area_m2": 28, "count": 3, "lods": 2}], 20, 1024)
        self.assertAlmostEqual(s["need_px2"], base * (1 + 0.25 + 0.0625))
        lod_rows = [r for r in rows if r["status"] == "lod"]
        self.assertEqual([r["name"] for r in lod_rows], ["s LOD1", "s LOD2"])
        self.assertAlmostEqual(lod_rows[0]["footprint_px"], rows[0]["footprint_px"] / 2)
        self.assertAlmostEqual(lod_rows[1]["pack_gap_uv"], rows[0]["pack_gap_uv"] * 4)

    def test_lods_read_as_in_the_world_spec(self):
        # same fields and factor as vrchat-world-orchestration's spec_validate: lods 2 = 1.3125x, lod_lightmap false = 1x
        base = lb.plan([{"name": "s", "area_m2": 28}], 20, 1024)[1]["need_px2"]
        two = lb.plan([{"name": "s", "area_m2": 28, "lods": 2}], 20, 1024)[1]["need_px2"]
        self.assertAlmostEqual(two / base, 1.3125)
        rows, s = lb.plan([{"name": "s", "area_m2": 28, "lods": 2, "lod_lightmap": False}], 20, 1024)
        self.assertAlmostEqual(s["need_px2"], base)
        self.assertEqual([r["status"] for r in rows], ["lightmap", "probe-lit", "probe-lit"])
        self.assertNotIn("lod_lightmap: false", s["advice"])
        none = lb.plan([{"name": "s", "area_m2": 28, "lods": 2, "kind": "probe"}], 20, 1024)
        self.assertEqual(none[1]["need_px2"], 0.0)
        for bad in ({"lods": -1}, {"lods": 1.5}, {"lod_lightmap": 0}, {"lod_lightmap": "no"}):
            with self.assertRaises(ValueError):
                lb.plan([dict({"name": "s", "area_m2": 28}, **bad)], 20, 1024)

    def test_boxes_over_half_the_map_side(self):
        # two near-square boxes over half the map side cannot share one map, whatever the fill (exact geometry)
        area = (520 / 20.0) ** 2                  # a 520 px box at 20 texels/m
        rows, s = lb.plan([{"name": "big", "area_m2": area, "count": 2}], 20, 1024)
        self.assertLess(s["fill"], 0.65)
        self.assertEqual(s["big_boxes"], 2)
        self.assertTrue(any("over half the 1024 px map side" in w for w in s["warnings"]))
        self.assertFalse(lb.is_clean(rows, s))
        self.assertFalse(any(lo <= 20 <= hi for lo, hi in s["window_clean"]))
        self.assertTrue(any(lo <= 19.6 <= hi for lo, hi in s["window_clean"]))   # 509.6 px: they fit
        one = lb.plan([{"name": "big", "area_m2": area}, {"name": "w", "area_m2": 14, "count": 4}], 20, 1024)[1]
        self.assertFalse(any("over half" in w for w in one["warnings"]))
        self.assertFalse(any("over half" in w for w in lb.plan([{"name": "big", "area_m2": area, "count": 2}],
                                                                 20, 1024, maps=2)[1]["warnings"]))
        lod = lb.plan([{"name": "big", "area_m2": (1100 / 20.0) ** 2, "lods": 1}], 20, 1024)[1]   # 1100 + 550 px
        self.assertEqual(lod["big_boxes"], 2)

    def test_small_lods_get_a_note(self):
        rows, s = lb.plan([{"name": "PROP_Tree_Free_A", "area_m2": 60, "lods": 2}], 6, 1024)
        # a Free prop at 50 px is probe-lit whole, LODs included: no LOD rows and no LOD advice
        self.assertFalse([r for r in rows if r["status"] == "lod"])
        self.assertNotIn("lod_lightmap: false", s["advice"])
        rows, s = lb.plan([{"name": "SHELL", "area_m2": 60, "lods": 2}], 6, 1024)
        note = [n for n in s["notes"] if "lod_lightmap: false" in n]
        self.assertEqual(len(note), 1)
        self.assertIn("LOD1 at 25 px, LOD2 at 13 px", note[0])
        self.assertIn("make LOD1+ probe-lit (lod_lightmap: false)", s["advice"])
        rows, s = lb.plan([{"name": "SHELL", "area_m2": 60, "lods": 2, "lod_lightmap": False}], 6, 1024)
        self.assertFalse([n for n in s["notes"] if "lod_lightmap" in n])
        rows, s = lb.plan([{"name": "SHELL", "area_m2": 60, "lods": 1}], 20, 1024)    # LOD1 84 px
        self.assertFalse([n for n in s["notes"] if "lod_lightmap" in n])

    def test_spec_keys(self):
        spec = {"name": "INT_Wall_2x3_A", "desc": "plain wall", "notes": "", "collision": "box", "tris": 12,
                "lods": 1, "lod_lightmap": True, "lightmap": True, "lightmap_scale": 2, "size": [2, 3, 0.2]}
        s = lb.plan([spec], 20, 1024)[1]
        same = lb.plan([{"name": "INT_Wall_2x3_A", "size": [2, 3, 0.2], "scale": 2, "lods": 1}], 20, 1024)[1]
        self.assertAlmostEqual(s["need_px2"], same["need_px2"])
        self.assertAlmostEqual(s["need_px2"], (20 * 2) ** 2 * 14 * 1.25)
        self.assertFalse([w for w in s["warnings"] if "unknown key" in w])
        self.assertAlmostEqual(lb.plan([dict(spec, scale=2)], 20, 1024)[1]["need_px2"], s["need_px2"])
        with self.assertRaises(ValueError):
            lb.plan([dict(spec, scale=1)], 20, 1024)
        bad = lb.plan([{"name": "w", "area_m2": 14, "scael": 2, "colour": "red"}], 20, 1024)[1]
        keys = [w for w in bad["warnings"] if "unknown key" in w]
        self.assertEqual(keys, ["w: unknown key 'scael' is ignored (did you mean scale?)",
                                "w: unknown key 'colour' is ignored"])
        self.assertAlmostEqual(bad["need_px2"], 20 ** 2 * 14)    # the misspelt scale is not applied
        with self.assertRaises(ValueError):
            lb.plan([{"name": "free", "collision": "box"}], 20, 1024)

    def test_states_multiply_capacity(self):
        one = lb.plan([{"name": "w", "area_m2": 14, "count": 4}], 20, 1024)[1]["need_px2"]
        two = lb.plan([{"name": "w", "area_m2": 14, "count": 4}], 20, 1024, states=2)[1]["need_px2"]
        self.assertAlmostEqual(two, 2 * one)

    def test_maps_above_one(self):
        one = lb.plan([{"name": "w", "area_m2": 14, "count": 20}], 60, 1024, maps=1)[1]["fill"]
        two = lb.plan([{"name": "w", "area_m2": 14, "count": 20}], 60, 1024, maps=2)[1]["fill"]
        self.assertAlmostEqual(two, one / 2)

    def test_fill_advice_fits_mobile_and_states(self):
        big = [{"name": "w", "area_m2": 14, "count": 40}, {"name": "PROP_Box_Free_A", "area_m2": 5, "count": 10}]
        pc = " ".join(lb.plan(big, 60, 1024)[1]["errors"])
        self.assertIn("raise Max Lightmap Size", pc)
        mobile = " ".join(lb.plan(big, 60, 1024, mobile=True)[1]["errors"])
        self.assertNotIn("raise Max Lightmap Size", mobile)
        pc_cap = " ".join(lb.plan(big * 3, 60, 2048)[1]["errors"])
        self.assertIn("past the", pc_cap)
        self.assertNotIn("raise Max Lightmap Size", pc_cap)
        switched = " ".join(lb.plan(big, 60, 1024, states=2, mobile=True)[1]["errors"])
        self.assertIn("do not change with the switch", switched)
        self.assertIn("state copies", switched)

    def test_mobile_map_size(self):
        s = lb.plan([{"name": "w", "area_m2": 14}], 20, 2048, mobile=True)[1]
        self.assertTrue(any("ships to Quest or iOS" in e for e in s["errors"]))
        self.assertFalse(lb.plan([{"name": "w", "area_m2": 14}], 20, 1024, mobile=True)[1]["errors"])


class Window(unittest.TestCase):
    """The texels/m window must hold for every piece once re-planned there, props crossing 64 px included."""

    def check_window(self, pieces, max_px, maps=1):
        rows, s = lb.plan(pieces, 20, max_px, maps)
        for lo, hi in s["window_clean"]:
            for t in (lo, (lo + hi) / 2, hi):
                ok, _ = clean_at(pieces, t, max_px, maps)
                self.assertTrue(ok, "window %s-%s fails at %s" % (lo, hi, t))
            for t in (lo - lb.SCAN_STEP, hi + lb.SCAN_STEP):
                if lb.SCAN_STEP <= t <= lb.SCAN_MAX:
                    ok, _ = clean_at(pieces, round(t, 1), max_px, maps)
                    self.assertFalse(ok, "just outside %s-%s still clean at %s" % (lo, hi, t))
        return s

    def test_room_window_consistent(self):
        s = self.check_window(ROOM, 1024)
        self.assertTrue(s["window_clean"])

    def test_props_crossing_64_px_are_counted(self):
        # the desk and door cross 64 px at about 25 and 29 texels/m; their fill must count above that
        s = self.check_window(ROOM, 1024)
        hi = max(h for _, h in s["window_clean"])
        _, at_hi = clean_at(ROOM, hi, 1024)
        self.assertLessEqual(at_hi["fill"], lb.PLAN_FILL)

    def test_no_window_reported_as_empty(self):
        pieces = [{"name": "wall", "size": [2, 3, 0.2], "count": 8, "gap_uv": GAP_8_AT_512},
                  {"name": "slab", "size": [2, 2, 0.1], "count": 8, "gap_uv": GAP_8_AT_512}]
        s = self.check_window(pieces, 512)
        self.assertEqual(s["window_clean"], [])


class CommandLine(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run([sys.executable, "-B", str(SCRIPT)] + list(args), capture_output=True, text=True)

    def test_piece_syntax_scale_and_kind(self):
        ok = self.run_script("--texels-per-m", "60", "--max-px", "2048",
                             "--piece", "INT_Wall_2x3_A:2x3x0.2:7:0.02:0.5",
                             "--piece", "PROP_Box_Free_A:2:1:0.05::shell",
                             "--piece", "PROP_Cup_Free_A:0.05:4::1:lightmap",
                             "--piece", "PROP_Statue_Free_A:28:1:::grid:2")
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn("122px", ok.stdout)                 # 243.5 x 0.5
        self.assertIn("grid", ok.stdout.splitlines()[2])
        self.assertIn("lightmap", ok.stdout.splitlines()[3])
        self.assertIn("PROP_Statue_Free_A LOD2", ok.stdout)

    def test_bad_input_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj = Path(tmp) / "object.json"
            obj.write_text(json.dumps({"name": "x", "area_m2": 1}), encoding="utf-8")
            noname = Path(tmp) / "noname.json"
            noname.write_text(json.dumps([{"area_m2": 1}]), encoding="utf-8")
            broken = Path(tmp) / "broken.json"
            broken.write_text("[{", encoding="utf-8")
            cases = [
                ["--texels-per-m", "60", "--max-px", "1024", "--piece", "broken"],
                ["--texels-per-m", "60", "--max-px", "1024", "--piece", "a:1:1:0"],
                ["--texels-per-m", "60", "--max-px", "1024", "--piece", "a:1:-2"],
                ["--texels-per-m", "-5", "--max-px", "1024", "--piece", "a:1:1"],
                ["--texels-per-m", "60", "--max-px", "1024", "--piece", "a:1:1:0.01:1:wall"],
                ["--texels-per-m", "60", "--max-px", "1024", "--json", str(obj)],
                ["--texels-per-m", "60", "--max-px", "1024", "--json", str(noname)],
                ["--texels-per-m", "60", "--max-px", "1024", "--json", str(broken)],
                ["--max-px", "1024", "--piece", "a:1:1"],
            ]
            for args in cases:
                res = self.run_script(*args)
                self.assertEqual(res.returncode, 2, "%s -> %d\n%s%s" % (args, res.returncode, res.stdout, res.stderr))

    def test_no_window_line_uses_the_same_advice(self):
        res = self.run_script("--texels-per-m", "28", "--max-px", "1024", "--mobile", "--states", "2",
                              "--piece", "INT_Wall_2x3_A:2x3x0.2:40:0.001")
        self.assertIn("No texels/m works", res.stdout)
        self.assertNotIn("raise Max Lightmap Size", res.stdout)

    def test_probe_lit_rows_not_multiplied_by_states(self):
        res = self.run_script("--texels-per-m", "10", "--max-px", "1024", "--states", "2",
                              "--piece", "PROP_Chair_Free_A:0.3:60")
        row = [l for l in res.stdout.splitlines() if l.startswith("PROP_Chair_Free_A")][0]
        self.assertIn(" 60 ", row)
        self.assertIn("probe-lit", row)

    def test_json_spec_piece_and_unknown_key(self):
        spec = {"name": "INT_Wall_2x3_A", "desc": "plain wall", "collision": "box", "tris": 12, "lods": 1,
                "lod_lightmap": True, "lightmap": True, "lightmap_scale": 2, "size": [2, 3, 0.2], "count": 3}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pieces.json"
            path.write_text(json.dumps([spec, {"name": "slab", "area_m2": 8.8, "sacle": 2}]), encoding="utf-8")
            res = self.run_script("--texels-per-m", "20", "--max-px", "1024", "--json", str(path))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("WARN  slab: unknown key 'sacle' is ignored (did you mean scale?)", res.stdout)
        self.assertEqual(res.stdout.count("unknown key"), 1)
        self.assertIn("fill 0.083 ", res.stdout)          # ((20 x 2)^2 x 14 x 1.25 x 3 + 20^2 x 8.8) / 1024^2

    def test_json_input_and_plan_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pieces.json"
            path.write_text(json.dumps([{"name": "slab", "size": [2, 2, 0.1], "count": 8,
                                         "gap_uv": GAP_8_AT_512}]), encoding="utf-8")
            res = self.run_script("--texels-per-m", "28", "--max-px", "512", "--json", str(path))
            self.assertEqual(res.returncode, 1, res.stdout)
            self.assertIn("padding", res.stdout)


if __name__ == "__main__":
    unittest.main()
