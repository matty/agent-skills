"""Plain-Python tests for the rizomuv-uv-pipeline skill's scripts/rizom_uv.py: packing defaults (UV0 padding,
lightmap footprint and gaps), input checks, and unwrap_gated's retry ladder, gate merge and time budget against a
fake RizomUV link (tools/tests/rizomuv_fake_link.py). No RizomUV, no licence, no Blender.

Host: plain Python 3.9+; the unwrap_gated tests need numpy (they skip without it). Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_rizomuv_*.py"
"""

import math
import sys
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "rizomuv-uv-pipeline" / "scripts"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rizomuv_fake_link import FakeLink, box_mesh  # noqa: E402


def load(name):
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True            # never leave a __pycache__ in the skill
    try:
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        return __import__(name)
    finally:
        sys.dont_write_bytecode = keep


class PackSpec(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ru = load("rizom_uv")

    def test_uv0_padding_defaults_to_map_over_64_and_half_to_the_edge(self):
        for map_px, pad, margin in ((512, 8, 4), (1024, 16, 8), (2048, 32, 16), (4096, 64, 32)):
            s = self.ru.pack_spec(map_px)
            self.assertEqual((s["pad_px"], s["margin_px"]), (pad, margin), map_px)

    def test_explicit_padding_is_taken_as_given(self):
        s = self.ru.pack_spec(1024, 24)                       # map/64 is the minimum gap; more is allowed
        self.assertEqual((s["pad_px"], s["margin_px"]), (24, 12))
        with self.assertRaises(ValueError):
            self.ru.pack_spec(1024, device="GPU")

    def test_lightmap_footprint_uses_the_uv2_bounding_box_share(self):
        wall = 2 * (2 * 3) + 2 * (2 * 0.2) + 2 * (3 * 0.2)          # 2 x 3 x 0.2 m wall, 14 m2
        self.assertEqual(self.ru.LIGHTMAP_COVERAGE, 0.85)              # planning estimate of b
        self.assertAlmostEqual(self.ru.lightmap_footprint(wall, 60), 243.5, delta=0.8)   # Unity: 242.8 px at b 0.850
        self.assertAlmostEqual(self.ru.lightmap_footprint(wall, 60, 1.0, 1.0), 60 * math.sqrt(wall), delta=1e-9)
        self.assertAlmostEqual(self.ru.lightmap_footprint(wall, 60, 0.5, 0.85), 243.5 / 2, delta=0.4)

    def test_lightmap_gaps_hold_two_texels_whatever_the_bounding_box(self):
        self.assertEqual(self.ru.LIGHTMAP_MIN_FOOTPRINT_PX, 64)
        for area in (0.05, 0.25, 1.0, 2.0, 6.0, 14.0, 40.0, 200.0):
            for tpm in (5, 10, 20, 40, 60):
                for scale in (0.25, 1.0, 2.0):
                    s = self.ru.lightmap_spec(area, tpm, scale)
                    foot = self.ru.lightmap_footprint(area, tpm, scale, 1.0)        # b = 1: the worst case
                    self.assertAlmostEqual(s["packed_for_px"], foot, delta=0.006)      # rounded to 0.01 px
                    worst_gap = (s["pad_px"] - self.ru.PACK_GRID_SLACK_PX) * foot / s["map_px"]
                    worst_edge = (s["margin_px"] - self.ru.PACK_GRID_SLACK_PX) * foot / s["map_px"]
                    self.assertGreaterEqual(worst_gap, 2.0 - 1e-9, (area, tpm, scale, s))
                    self.assertGreaterEqual(worst_edge, 1.0 - 1e-9, (area, tpm, scale, s))

    def test_shared_mesh_is_packed_for_its_smallest_renderer(self):
        users = {"full": (6.0, 1.0), "half": (1.5, 1.0), "dim": (6.0, 0.25)}
        s = self.ru.lightmap_spec(6.0, 20, users=users)
        self.assertAlmostEqual(s["packed_for_px"], 20 * math.sqrt(6.0) * 0.25, places=2)   # "dim" is the smallest
        self.assertEqual(set(s["users"]), set(users))

    def test_warning_names_props_and_grid_pieces(self):
        self.assertIsNone(self.ru.lightmap_warning(64.0))
        w = self.ru.lightmap_warning(40.0, "KIT_Wall")
        self.assertIn("probe-light it if it is a Free prop (a Free-sized PROP or FOL piece, not in a zone with "
                      "lighting states)", w)
        self.assertIn("otherwise raise Scale In Lightmap or texels_per_m", w)
        self.assertIn("KIT_Wall", w)
        self.assertIsNone(self.ru.lightmap_warning(40.0, "KIT_Wall_LOD1"))     # LOD1+ follow their piece

    def test_lightmap_spec_is_graded_by_layer_report_not_report_args(self):
        with self.assertRaises(ValueError):
            self.ru.report_args(self.ru.lightmap_spec(1.0, 20))
        self.assertEqual(self.ru.report_args(self.ru.pack_spec(1024)), {"map_px": 1024, "pad_px": 16, "margin_px": 8})

    def test_lightmap_spec_takes_a_mesh_or_an_area(self):
        self.assertAlmostEqual(self.ru.mesh_area(box_mesh(2.0)), 24.0)
        self.assertEqual(self.ru.lightmap_spec(box_mesh(2.0), 20)["packed_for_px"],
                         self.ru.lightmap_spec(24.0, 20)["packed_for_px"])

    def test_directional_modes(self):
        base = self.ru.pack_spec(1024)
        self.assertIs(self.ru.directional(base, False), base)
        self.assertIs(self.ru.directional(base, None), base)
        for mode, initial in ((True, "Horizontal"), ("grain", "Horizontal"), ("GRAIN", "Horizontal"),
                              ("upright", "Z|+V|X|+U"), ("X|+U|Y|+V", "X|+U|Y|+V"), ("Vertical", "Vertical")):
            s = self.ru.directional(base, mode)
            self.assertEqual((s["rotate_step"], s["rotate_initial"]), (0.0, initial), mode)

    def test_texture_size(self):
        self.assertEqual(self.ru.texture_size(512, 2.0), 1024)
        self.assertEqual(self.ru.texture_size(512, 0.01), 64)
        self.assertEqual(self.ru.texture_size(1024, 100.0), 2048)            # capped

    def test_normalise_rejects_bad_meshes(self):
        good = box_mesh()
        self.ru.normalise(good)
        for bad in (dict(good, sizes=[]), dict(good, sizes=[2] + good["sizes"][1:]),
                    dict(good, xyz_ids=good["xyz_ids"][:-1]), dict(good, xyz=good["xyz"][:-1]),
                    dict(good, xyz=[float("nan")] + good["xyz"][1:]), dict(good, xyz=[0.0] * len(good["xyz"]))):
            with self.assertRaises(ValueError):
                self.ru.normalise(bad)


@unittest.skipUnless(np is not None, "numpy is not installed")
class Gated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ru = load("rizom_uv")

    def test_clean_cube_passes_on_the_first_attempt(self):
        res = self.ru.unwrap_gated(FakeLink(), box_mesh(), "hard",
                                   {"uv0": self.ru.pack_spec(1024), "uv2": self.ru.lightmap_spec(box_mesh(), 20)})
        self.assertEqual(res["gate_failures"], [])
        self.assertEqual(res["attempt"], "preset hard")
        self.assertTrue(res["packs"]["uv0"]["fits"] and res["packs"]["uv2"]["fits"])
        self.assertEqual(res["report"]["overlap_px"], 0)

    def test_ladder_climbs_until_the_gate_passes(self):
        link = FakeLink(stretch=lambda auto: 1.5 if auto.get("Quality") == 0.75 else 1.0)
        res = self.ru.unwrap_gated(link, box_mesh(), "hard")
        self.assertEqual([a["attempt"] for a in res["attempts"]], ["preset hard", "stretch limiter 0.85"])
        self.assertTrue(res["attempts"][0]["gate_failures"])
        self.assertEqual(res["gate_failures"], [])

    def test_partial_gate_loosens_one_key_and_keeps_the_rest(self):
        link = FakeLink(stretch=lambda auto: 1.3)
        res = self.ru.unwrap_gated(link, box_mesh(), "hard", gate={"angular_p95": 1.4}, ladder=[])
        self.assertEqual(res["gate_failures"], [])
        link = FakeLink(stretch=lambda auto: 1.3)
        res = self.ru.unwrap_gated(link, box_mesh(), "hard", gate={"angular_p95": 1.4, "angular_max": 1.2},
                                   ladder=[])
        self.assertTrue(any(f.startswith("angular_max") for f in res["gate_failures"]))

    def test_every_attempt_failing_keeps_the_least_distorted(self):
        stretch = {0.75: 1.9, 0.85: 1.6}
        mosaic_09 = lambda auto: "QuasiDevelopable" in auto and auto["QuasiDevelopable"]["Developability"] == 0.9
        link = FakeLink(stretch=lambda auto: stretch.get(auto.get("Quality"), 1.6) + (0.1 if mosaic_09(auto) else 0))
        res = self.ru.unwrap_gated(link, box_mesh(), "hard")
        self.assertEqual(len(res["attempts"]), 3)
        self.assertEqual(res["attempt"], "stretch limiter 0.85")
        self.assertTrue(res["gate_failures"])
        self.assertEqual(link.calls[-1], "Load")                # the chosen layout reloaded for a stretch map

    def test_overflowing_density_tries_organic_then_stops(self):
        link = FakeLink()
        res = self.ru.unwrap_gated(link, box_mesh(), "hard", {"uv0": self.ru.pack_spec(256, px_per_unit=5000.0)})
        self.assertFalse(res["packs"]["uv0"]["fits"])
        self.assertEqual([(a["attempt"], a["fits"]) for a in res["attempts"]],
                         [("preset hard", False), ("organic preset", False)])
        res = self.ru.unwrap_gated(FakeLink(), box_mesh(), "organic",
                                   {"uv0": self.ru.pack_spec(256, px_per_unit=5000.0)})
        self.assertEqual(len(res["attempts"]), 1)                # nothing else to try

    def test_a_hard_pack_that_does_not_fit_takes_the_organic_preset(self):
        link = FakeLink(overflow=lambda auto: "QuasiDevelopable" not in auto)   # a bevel ring joined under hard
        res = self.ru.unwrap_gated(link, box_mesh(), "hard", {"uv0": self.ru.pack_spec(1024, px_per_unit=300)})
        self.assertEqual([(a["attempt"], a["fits"]) for a in res["attempts"]],
                         [("preset hard", False), ("organic preset", True)])
        self.assertEqual(res["attempt"], "organic preset")
        self.assertTrue(res["packs"]["uv0"]["fits"])
        self.assertEqual(res["gate_failures"], [])

    def test_texel_density_pack_lands_on_target(self):
        res = self.ru.unwrap_gated(FakeLink(), box_mesh(), "hard", {"uv0": self.ru.pack_spec(1024, px_per_unit=300)})
        self.assertTrue(res["packs"]["uv0"]["fits"])
        self.assertAlmostEqual(res["packs"]["uv0"]["px_per_unit"], 300.0, delta=1.0)

    def test_time_budget_keeps_the_best_attempt_instead_of_starting_another(self):
        link = FakeLink(stretch=lambda auto: 1.5)
        res = self.ru.unwrap_gated(link, box_mesh(), "hard", time_budget=1e-9)
        self.assertEqual(len([a for a in res["attempts"] if "skipped" not in a]), 1)
        self.assertIn("skipped", res["attempts"][-1])

    def test_low_coverage_goes_to_the_organic_preset(self):
        link = FakeLink(coverage=lambda auto: 1.0 if "QuasiDevelopable" in auto else 0.3)
        res = self.ru.unwrap_gated(link, box_mesh(), "hard")
        self.assertTrue(any(f.startswith("coverage") for f in res["attempts"][0]["gate_failures"]))
        self.assertEqual([a["attempt"] for a in res["attempts"]], ["preset hard", "organic preset"])
        self.assertEqual(res["gate_failures"], [])
        self.assertGreaterEqual(res["report"]["coverage"], 0.35)

    def test_coverage_floor_only_for_filled_texture_packs(self):
        link = FakeLink(coverage=lambda auto: 0.3)
        res = self.ru.unwrap_gated(link, box_mesh(), "organic", ladder=[])
        self.assertTrue(any(f.startswith("coverage") for f in res["gate_failures"]))
        res = self.ru.unwrap_gated(FakeLink(), box_mesh(), "hard", {"uv0": self.ru.pack_spec(1024, px_per_unit=100)})
        self.assertFalse(any(f.startswith("coverage") for f in res["gate_failures"]))     # density decides it

    def test_lightmap_channel_is_graded_at_its_measured_footprints(self):
        spec = self.ru.lightmap_spec(box_mesh(), 20, users={"KIT_Box": (6.0, 1.0), "KIT_Box_half": (1.5, 1.0)})
        res = self.ru.unwrap_gated(FakeLink(), box_mesh(), "hard", {"uv0": self.ru.pack_spec(1024), "uv2": spec})
        rep = res["reports"]["uv2"]
        b = rep["bbox_share"]
        self.assertTrue(0 < b <= 1)
        self.assertAlmostEqual(rep["footprints_px"]["KIT_Box"], 20 * math.sqrt(6.0 / b), delta=0.02)
        self.assertAlmostEqual(rep["graded_at_px"], 20 * math.sqrt(1.5 / b), delta=0.02)
        self.assertEqual(res["failures"]["uv2"], [])
        self.assertEqual(rep["padding_pairs_below_min"], 0)
        self.assertTrue(rep["margin_ok"])
        self.assertTrue(any("KIT_Box_half" in w for w in rep["warnings"]))      # 41 px: under 64

    def test_lightmap_too_small_for_its_charts_is_packed_for_64_px(self):
        self.assertEqual(self.ru.lightmap_capacity_px(1), 2.0)
        self.assertEqual(self.ru.lightmap_capacity_px(6), 6.0)          # 3 x 3 grid: 2 gaps of 2 + 2 edges of 1
        self.assertEqual(self.ru.lightmap_capacity_px(16), 8.0)
        tiny = self.ru.lightmap_spec(box_mesh(), 20, users={"KIT_Plank": (0.441, 1.0), "KIT_Plank_small": (0.11, 0.5)})
        self.assertIsNone(self.ru.lightmap_too_small(self.ru.lightmap_spec(box_mesh(), 20), 6))
        self.assertEqual(self.ru.lightmap_too_small(tiny, 6), "6 charts need 6 px")
        link = FakeLink()
        res = self.ru.unwrap_gated(link, box_mesh(), "hard", {"uv0": self.ru.pack_spec(1024), "uv2": tiny})
        rep = res["reports"]["uv2"]
        self.assertTrue(res["packs"]["uv2"]["fits"])
        self.assertEqual(res["failures"]["uv2"], [])                     # a valid UV2, for 64 px
        self.assertIn("lightmap UV packed for 64 px: KIT_Plank_small gets 3.3 px, too small for 2-texel gaps",
                      rep["fallback"])
        self.assertIn("6 charts need 6 px", rep["fallback"])
        self.assertIn("probe-light it (a Free prop, or a LOD via lod_lightmap: false), or raise its Scale In "
                      "Lightmap 19.3x", rep["fallback"])
        self.assertGreaterEqual(rep["graded_at_px"], 64.0)
        self.assertLess(rep["footprints_px"]["KIT_Plank_small"], 64.0)    # the real footprints stay in the report
        self.assertEqual(rep["packed_for_px"], 64.0)
        self.assertEqual(len(link.packs), 2)

    def test_a_failing_pack_under_64_px_falls_back(self):
        calls = []

        def first_lightmap_pack_overlaps(params):
            if params["MapResolution"] != 128:
                return False
            calls.append(1)
            return len(calls) == 1
        link = FakeLink(overlap=first_lightmap_pack_overlaps)
        res = self.ru.unwrap_gated(link, box_mesh(), "hard",
                                   {"uv0": self.ru.pack_spec(1024), "uv2": self.ru.lightmap_spec(box_mesh(), 20)})
        self.assertEqual(res["failures"]["uv2"], [])
        self.assertIn("its pack failed them", res["reports"]["uv2"]["fallback"])

    def test_a_fallback_that_fails_climbs_until_one_passes(self):
        link = FakeLink(overlap=lambda params: params["MapResolution"] == 128)    # 64 and 128 px both fail
        res = self.ru.unwrap_gated(link, box_mesh(), "hard",
                                   {"uv0": self.ru.pack_spec(1024), "uv2": self.ru.lightmap_spec(box_mesh(), 20)})
        rep = res["reports"]["uv2"]
        self.assertEqual(res["failures"]["uv2"], [])                     # 49 px: a note, the UV2 is written
        self.assertTrue(rep["fallback_ok"])
        self.assertIn("lightmap UV packed for 256 px", rep["fallback"])
        self.assertIn("probe-lit only, or raise its Scale In Lightmap 5.2x", rep["fallback"])

    def test_an_overlapping_lightmap_fails_even_though_it_fits(self):
        link = FakeLink(overlap=lambda params: params["MapResolution"] == 128)
        res = self.ru.unwrap_gated(link, box_mesh(), "hard",
                                   {"uv0": self.ru.pack_spec(1024), "uv2": self.ru.lightmap_spec(box_mesh(), 40)})
        self.assertTrue(res["packs"]["uv2"]["fits"])                     # 98 px fails, 196 px passes:
        self.assertTrue(res["reports"]["uv2"]["fallback_ok"])               # written, but a REVIEW
        self.assertIn("2-texel gaps fit only at 196 px, not its 98 px", res["failures"]["uv2"][0])
        link = FakeLink(overlap=lambda params: True)                     # nothing passes up to 4096 px
        res = self.ru.unwrap_gated(link, box_mesh(), "hard",
                                   {"uv0": self.ru.pack_spec(1024), "uv2": self.ru.lightmap_spec(box_mesh(), 40)})
        self.assertNotIn("fallback_ok", res["reports"]["uv2"])
        self.assertTrue(any(f.startswith("overlap") for f in res["failures"]["uv2"]), res["failures"]["uv2"])

    def test_lod_levels_halve_the_footprint(self):
        ru = self.ru
        self.assertEqual([ru.lod_level(n) for n in ("KIT_Wall_LOD1", "KIT_Wall_LOD2.001", "kit_wall_lod2", "KIT_Wall",
                                                     "KIT_LODge")], [1, 2, 0, 0, 0])    # vrchat-world-qa's LOD_RE
        self.assertEqual(ru.lod_scale("KIT_Wall_LOD2"), 0.25)
        lod0, lod1 = ru.lightmap_spec(box_mesh(), 40), ru.lightmap_spec(box_mesh(), 40, lod=1)
        self.assertAlmostEqual(lod1["packed_for_px"], lod0["packed_for_px"] / 2, delta=0.01)
        gap = lambda s: s["pad_px"] / s["map_px"]                        # gap in UV
        self.assertGreaterEqual(gap(lod1), 2 * (2.0 / lod0["packed_for_px"]))   # 2 texels at half the footprint
        self.assertGreater(gap(lod1), gap(lod0))

    def test_lightmap_report_has_its_box_fill(self):
        res = self.ru.unwrap_gated(FakeLink(), box_mesh(), "hard",
                                   {"uv0": self.ru.pack_spec(1024), "uv2": self.ru.lightmap_spec(box_mesh(), 40)})
        rep = res["reports"]["uv2"]
        self.assertTrue(0 < rep["box_fill"] <= 1)
        self.assertAlmostEqual(rep["box_fill"], min(1.0, rep["coverage"] / rep["bbox_share"]), places=2)

    def test_directional_spec_reaches_pack(self):
        link = FakeLink()
        self.ru.unwrap_gated(link, box_mesh(), "hard", {"uv0": self.ru.directional(self.ru.pack_spec(1024), "grain")})
        self.assertEqual(link.packs[0]["Rotate"], {"Step": 0.0, "Initial": "Horizontal"})
        link = FakeLink()
        self.ru.unwrap_gated(link, box_mesh(), "hard", {"uv0": self.ru.pack_spec(1024)})
        self.assertEqual(link.packs[0]["Rotate"], {"Step": 90.0})


if __name__ == "__main__":
    unittest.main()
