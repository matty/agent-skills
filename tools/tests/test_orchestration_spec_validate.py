"""Tests for skills/vrchat-world-orchestration/scripts/spec_validate.py.

Host: plain Python 3.9+, stdlib unittest; PyYAML is optional (the YAML file tests skip without it).
Run from the repo root:  python -B -m unittest discover -s tools/tests -p "test_orchestration_*.py"
"""

import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "vrchat-world-orchestration"
SCRIPT = SKILL / "scripts" / "spec_validate.py"
DRY_RUN_SPEC = Path(r"F:\Projects\Unity\agent-skills-sandbox\world-dryrun\world\spec.yaml")

try:
    import yaml  # noqa: F401
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False


def load_module():
    sys.dont_write_bytecode = True                     # never leave __pycache__ in the skill folder
    spec = importlib.util.spec_from_file_location("orchestration_spec_validate", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SV = load_module()


def study_spec():
    """The 2026-10-16 dry run's sealed 4 x 4 x 3 m study, trimmed, with a sized desk at 50 texels/m: it is clean."""
    placements = [{"ref": r, "pos": p, "rot": rot} for r, p, rot in (
        ("INT_Door_2x3_A", [1, 1, 0], 0), ("INT_Wall_2x3_A", [3, 1, 0], 0),
        ("INT_Wall_2x3_A", [5, 5, 0], 180), ("INT_Wall_2x3_A", [3, 5, 0], 180),
        ("INT_Wall_2x3_A", [5, 1, 0], 90), ("INT_Wall_2x3_A", [5, 3, 0], 90),
        ("INT_Wall_2x3_A", [1, 5, 0], 270), ("INT_Wall_2x3_A", [1, 3, 0], 270))]
    for x, y in ((1, 1), (3, 1), (1, 3), (3, 3)):
        placements.append({"ref": "STR_Floor_2x2_A", "pos": [x, y, -0.1], "rot": 0})
        placements.append({"ref": "STR_Ceiling_2x2_A", "pos": [x, y, 3], "rot": 0})
    placements += [{"ref": "PROP_Desk_Free_A", "pos": [3, 4.35, 0], "rot": 0},
                   {"ref": "PROP_LightSwitch_Free_A", "pos": [3.25, 1.2, 1.2], "rot": 180}]
    # a 1 m tile (512 px at 512 px/m) divides the 1 m module and the 3 m storey; the dry run's 2 m tile would jump at
    # every other joint (the tile_phase rule)
    family = {"file": "blender/kits/KIT_World.blend", "texturing": "tiling", "texel_density": 512, "map_px": 512}
    return {
        "version": 1,
        "world": {"name": "Study", "platforms": ["pc", "quest"], "scale": "small", "allow_generated_assets": False,
                  "mockups": False, "style": "Abandoned Victorian study"},
        "tools": {"blender": "C:/blender/blender.exe", "blender_mcp": False, "unity_project": "C:/Unity/Study"},
        "grid": {"module": 1.0, "sub_module": 0.25, "storey_height": 3.0},
        "families": {
            "INT": dict(family, materials=["M_INT_Wallpaper"], thickness=0.2),
            "STR": dict(family, materials=["M_STR_Boards"], thickness=0.1),
            "PROP": dict(family, materials=["M_PROP_Atlas01"], texturing="atlas"),
        },
        "budgets": {"world_tris": 10000, "view_tris": 10000, "materials": 5, "setpass": 10, "batches": 30,
                    "texture_vram_mb": 20, "download_mb": {"pc": 20, "quest": 15},
                    "piece_tris": {"INT": 300, "STR": 50, "PROP": 2500},
                    "lightmap": {"max_px": 1024, "count": 1, "texels_per_m": 50}},
        "pieces": [
            {"name": "INT_Wall_2x3_A", "desc": "wall bay", "collision": "box"},
            {"name": "INT_Door_2x3_A", "desc": "door bay", "collision": "box"},
            {"name": "STR_Floor_2x2_A", "desc": "floor slab", "collision": "box"},
            {"name": "STR_Ceiling_2x2_A", "desc": "ceiling slab", "collision": "none"},
            {"name": "PROP_Desk_Free_A", "desc": "desk", "collision": "box", "size": [1.4, 0.7, 0.78]},
            {"name": "PROP_LightSwitch_Free_A", "desc": "switch", "collision": "box", "lightmap": False},
        ],
        "assemblies": [],
        "zones": [{"id": "study", "name": "Study", "kind": "interior", "bounds": [0, 0, 6, 6], "floor_z": 0,
                   "placements": placements,
                   "rooms": [{"id": "study", "name": "Study", "bounds": [1, 1, 5, 5], "height": 3,
                              "openings": [{"type": "door", "at": [1.4, 1], "width": 1.2, "height": 2.2}]}]}],
        "elevations": [{"id": "study_south_inside", "zone": "study", "facing": "north", "origin": [5, 1.2, 0],
                        "courses": [["INT_Wall_2x3_A", "INT_Door_2x3_A"]]}],
        "views": [{"id": "study_entry", "pos": [2, 1.8, 1.7], "target": [3, 4.4, 0.9], "lens": 24, "matches": None}],
        "interactivity": [{"id": "light_switch", "desc": "Toggle the room light for everyone", "sync": "manual"}],
        "lighting": {"baker": "progressive", "mode": "baked", "light_volumes": False},
    }


def run(spec):
    f = SV.Findings()
    ctx = SV.check_spec(spec, f)
    return f, ctx


def messages(f, kind):
    return [m for k, m in f.items if k == kind]


def run_cli(*args, cwd=None):
    return subprocess.run([sys.executable, "-B", str(SCRIPT)] + [str(a) for a in args], cwd=cwd,
                          capture_output=True, text=True)


class SpecChecks(unittest.TestCase):
    def test_study_fixture_is_clean(self):
        f, ctx = run(study_spec())
        self.assertEqual(f.errors, 0, f.items)
        self.assertEqual(f.warnings, 0, f.items)

    def test_ios_is_a_platform_with_the_quest_limits(self):
        spec = study_spec()
        spec["world"]["platforms"] = ["pc", "quest", "ios"]
        spec["budgets"]["download_mb"]["ios"] = 15
        f, _ = run(spec)
        self.assertEqual(f.errors, 0, f.items)
        spec["budgets"]["materials"] = 30
        f, _ = run(spec)
        errors = messages(f, "ERROR")
        self.assertTrue(any("quest target 25" in m for m in errors), errors)
        self.assertTrue(any("ios target 25" in m for m in errors), errors)

    def test_ios_falls_back_to_quest_in_per_platform_budgets(self):
        spec = study_spec()
        spec["world"]["platforms"] = ["pc", "quest", "ios"]
        spec["budgets"]["setpass"] = {"pc": 100, "quest": 40}            # no ios key: quest's value applies
        f, _ = run(spec)                                                  # download_mb has no ios key either
        self.assertEqual(f.errors, 0, f.items)
        spec["budgets"]["setpass"] = {"pc": 100, "quest": 60}            # quest's value is too loose for both
        errors = messages(run(spec)[0], "ERROR")
        self.assertTrue(any("setpass.quest = 60" in m for m in errors), errors)
        self.assertTrue(any("setpass.ios (the quest value) = 60" in m for m in errors), errors)
        spec = study_spec()
        spec["world"]["platforms"] = ["pc", "ios"]
        spec["budgets"]["download_mb"] = {"pc": 20}                       # neither ios nor quest
        errors = messages(run(spec)[0], "ERROR")
        self.assertTrue(any("download_mb.ios missing" in m and "falls back to quest" in m for m in errors), errors)

    def test_family_map_px_is_checked_against_the_pc_maximum_only(self):
        spec = study_spec()
        spec["world"]["platforms"] = ["pc", "quest", "ios"]
        spec["families"]["INT"]["texturing"] = "atlas"                    # a tiling 4 m tile fails the tile rule
        spec["families"]["INT"]["map_px"] = 2048                          # mobile gets 1024 from import overrides
        self.assertEqual(run(spec)[0].errors, 0)
        spec["families"]["INT"]["map_px"] = 4096
        self.assertTrue(any("PC maximum 2048" in m for m in messages(run(spec)[0], "ERROR")))

    def test_material_names(self):
        # Canon material_re: ^M_[A-Z]{2,5}_[A-Za-z0-9][A-Za-z0-9_]*$, plus the family's own prefix
        self.assertEqual(SV.MAT_RE.pattern, r"^M_[A-Z]{2,5}_[A-Za-z0-9][A-Za-z0-9_]*$")
        spec = study_spec()
        spec["families"]["INT"]["materials"] = ["M_INT_Wallpaper_Dark"]           # underscores in the name part
        self.assertEqual(run(spec)[0].errors, 0)
        for bad, needle in (("M_INT_Wallpaper.001", "should be named"), ("M_STR_Boards", "named for another family")):
            spec["families"]["INT"]["materials"] = [bad]
            self.assertTrue(any(needle in m for m in messages(run(spec)[0], "ERROR")), bad)

    def test_family_thickness_of_a_module_or_more_is_warned(self):
        # Canon: a Size names axes of one module or more; anything thinner is thickness and is skipped.
        spec = study_spec()
        spec["grid"]["module"] = 0.5
        spec["families"]["INT"]["thickness"] = 0.5
        warnings = messages(run(spec)[0], "WARN")
        self.assertTrue(any("family INT thickness 0.5 m is one module" in m for m in warnings), warnings)
        spec["families"]["INT"]["thickness"] = 0.3                        # under one module: a thin axis
        warnings = messages(run(spec)[0], "WARN")
        self.assertFalse(any("thickness" in m for m in warnings), warnings)

    def test_tiling_tile_divides_the_grid_steps(self):
        spec = study_spec()
        spec["families"]["INT"]["map_px"] = 1024                          # a 2 m tile on a 1 m grid, 3 m storeys
        errors = messages(run(spec)[0], "ERROR")
        self.assertTrue(any("family INT: its 2 m tile" in m and "grid.module 1 m" in m and "storey_height 3 m" in m
                            for m in errors), errors)
        self.assertTrue(any("family INT: its 2 m tile" in m and "map_px 512 or 256 or 128" in m for m in errors),
                        errors)
        spec["families"]["INT"]["map_px"] = 256                           # 0.5 m divides both
        self.assertEqual(run(spec)[0].errors, 0)
        spec["families"]["INT"]["map_px"] = 1024
        spec["grid"]["storey_height"] = 3.5                               # a 1 m tile no longer divides the storey
        errors = messages(run(spec)[0], "ERROR")
        self.assertTrue(any("family INT: its 2 m tile" in m and "map_px 256 or 128)" in m for m in errors), errors)
        spec["grid"]["storey_height"] = 2.8                               # no power-of-two tile divides 2.8 m
        errors = messages(run(spec)[0], "ERROR")
        self.assertTrue(any("family INT" in m and "no power-of-two map" in m for m in errors), errors)
        spec["grid"]["storey_height"] = 3.0
        spec["families"]["INT"]["map_px"] = 1024
        spec["grid"]["storey_height"] = 4.0
        spec["families"]["INT"]["tile_phase"] = "variants"                # a 2 m tile: 2 variants on a 1 m grid
        res = run(spec)[0]
        self.assertFalse(any("family INT" in m for m in messages(res, "ERROR")), messages(res, "ERROR"))
        self.assertTrue(any("2 phase variants" in m for m in messages(res, "NOTE")), messages(res, "NOTE"))
        spec["grid"]["storey_height"] = 3.0                               # 3 m is not a whole number of 2 m tiles
        self.assertTrue(any("tile_phase variants needs" in m for m in messages(run(spec)[0], "ERROR")))
        spec["families"]["INT"]["tile_phase"] = "world_uv"
        res = run(spec)[0]
        self.assertFalse(any("family INT" in m for m in messages(res, "ERROR")))
        self.assertTrue(any("world-space UV shader" in m for m in messages(res, "NOTE")))
        spec["families"]["INT"]["tile_phase"] = "free"
        self.assertTrue(any("tile_phase must be one of" in m for m in messages(run(spec)[0], "ERROR")))

    def test_tiling_placements_continue_the_world_pattern(self):
        """Each tiling piece is projected with phase 0 at its pivot, so the validator checks every placement against
        the world tile grid: a floor turned 90 deg (unless the family's turn_symmetry allows it), a wall 3 cm up, and
        a phase variant facing +Y in the slot x mod tile picks (it is the pivot's distance along its own +X)."""
        spec = study_spec()
        zone = spec["zones"][0]["placements"]
        zone.append({"ref": "STR_Floor_2x2_A", "pos": [1, 3, -0.1], "rot": 90})
        zone.append({"ref": "INT_Wall_2x3_A", "pos": [3, 3, 0.03], "rot": 0})
        errors = messages(run(spec)[0], "ERROR")
        self.assertTrue(any("STR_Floor_2x2_A turned 90" in m for m in errors), errors)
        self.assertTrue(any("INT_Wall_2x3_A at [3, 3, 0.03] sits 0.0 px along it and 15.4 px up" in m
                            for m in errors), errors)
        spec["families"]["STR"]["turn_symmetry"] = 90
        errors = messages(run(spec)[0], "ERROR")
        self.assertFalse(any("turned" in m for m in errors), errors)
        spec["families"]["STR"]["turn_symmetry"] = 45
        self.assertTrue(any("turn_symmetry must be" in m for m in messages(run(spec)[0], "ERROR")))
        spec = study_spec()
        spec["grid"]["storey_height"] = 4.0
        spec["families"]["INT"].update(map_px=2048, tile_phase="variants")       # a 4 m tile on a 1 m grid
        spec["pieces"] += [{"name": "INT_Bay_1x3_P%d" % k, "desc": "bay", "collision": "box"} for k in range(4)]
        # facing +Y (rot 180): the old rule k = x mod 4 picks P3 at x = 3 and P2 at x = 2; along its own +X the
        # pivot is at s = -x, so k = (-x) mod 4: P1 and P2
        spec["zones"][0]["placements"] = [{"ref": "INT_Bay_1x3_P3", "pos": [3, 5, 0], "rot": 180},
                                          {"ref": "INT_Bay_1x3_P1", "pos": [2, 5, 0], "rot": 180}]
        errors = [m for m in messages(run(spec)[0], "ERROR") if "tile grid" in m]
        self.assertEqual(len(errors), 2, errors)
        spec["zones"][0]["placements"] = [{"ref": "INT_Bay_1x3_P1", "pos": [3, 5, 0], "rot": 180},     # -3 mod 4
                                          {"ref": "INT_Bay_1x3_P2", "pos": [2, 5, 0], "rot": 180},
                                          {"ref": "INT_Bay_1x3_P1", "pos": [5, 3, 0], "rot": 90}]      # s = y: P3
        errors = [m for m in messages(run(spec)[0], "ERROR") if "tile grid" in m]
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("INT_Bay_1x3_P1 at [5, 3, 0]", errors[0])

    def test_bake_is_a_flag(self):
        spec = study_spec()
        spec["pieces"][0]["bake"] = True
        self.assertEqual(run(spec)[0].errors, 0)
        spec["pieces"][0]["bake"] = "yes"
        self.assertTrue(any("bake must be true or false" in m for m in messages(run(spec)[0], "ERROR")))

    def test_world_name_is_required(self):
        spec = study_spec()
        del spec["world"]["name"]
        self.assertTrue(any("world.name missing" in m for m in messages(run(spec)[0], "ERROR")))

    def test_lightmap_without_max_px_is_warned(self):
        spec = study_spec()
        del spec["budgets"]["lightmap"]["max_px"]
        f, ctx = run(spec)
        self.assertTrue(any("max_px missing" in m for m in messages(f, "WARN")), f.items)
        self.assertEqual(ctx["area"], 0)

    def test_unplaced_assembly_and_elevation_only_pieces_are_warned(self):
        spec = study_spec()
        spec["assemblies"] = [{"name": "ASM_WallRun_A", "file": "blender/asm/ASM_WallRun_A.blend",
                               "size": [4, 0.2, 3], "uses": {"INT_Wall_2x3_A": 2}}]
        warnings = messages(run(spec)[0], "WARN")
        self.assertTrue(any("ASM_WallRun_A is never placed" in m for m in warnings), warnings)
        spec = study_spec()
        spec["zones"][0]["placements"] = [p for p in spec["zones"][0]["placements"]
                                          if p["ref"] != "INT_Door_2x3_A"]
        warnings = messages(run(spec)[0], "WARN")
        self.assertTrue(any(m.startswith("elevation study_south_inside: INT_Door_2x3_A never placed")
                            for m in warnings), warnings)

    def test_opening_sill(self):
        spec = study_spec()
        spec["zones"][0]["rooms"][0]["openings"].append(
            {"type": "window", "at": [5, 2], "width": 1.2, "height": 1.4, "sill": 0.9})
        self.assertEqual(run(spec)[0].errors, 0)
        spec["zones"][0]["rooms"][0]["openings"][-1]["sill"] = -1
        self.assertTrue(any("sill must be" in m for m in messages(run(spec)[0], "ERROR")))

    def test_unknown_platform_is_an_error_not_a_crash(self):
        spec = study_spec()
        spec["world"]["platforms"] = ["pc", "android"]
        f, _ = run(spec)                                  # used to raise KeyError
        errors = messages(f, "ERROR")
        self.assertTrue(any("world.platforms" in m and "quest" in m for m in errors), errors)

    def test_opening_must_run_along_a_room_edge(self):
        for at, width, ok in (([1.4, 1], 1.2, True), ([3, 3], 1.2, False), ([4.2, 1], 1.2, False),
                              ([5, 2], 1.2, True), ([5.2, 2], 1.2, True), ([5.6, 2], 1.2, False)):
            spec = study_spec()
            spec["zones"][0]["rooms"][0]["openings"] = [{"type": "door", "at": at, "width": width, "height": 2.2}]
            f, _ = run(spec)
            edge_errors = [m for m in messages(f, "ERROR") if "edges" in m]
            self.assertEqual(not edge_errors, ok, (at, f.items))

    def test_assembly_contents_count_in_the_lightmap_check(self):
        direct = study_spec()
        direct["zones"][0]["placements"] = [{"ref": "INT_Wall_2x3_A", "pos": [x, 1, 0], "rot": 0}
                                            for x in (0, 2)] * 4
        grouped = study_spec()
        grouped["assemblies"] = [{"name": "ASM_WallRun_A", "file": "blender/asm/ASM_WallRun_A.blend",
                                  "size": [8, 0.2, 3], "uses": {"INT_Wall_2x3_A": 4}}]
        grouped["zones"][0]["placements"] = [{"ref": "ASM_WallRun_A", "pos": [0, y, 0], "rot": 0} for y in (1, 3)]
        _, ctx_direct = run(direct)
        f, ctx_grouped = run(grouped)
        self.assertEqual(ctx_grouped["counts"].get("INT_Wall_2x3_A"), 8)
        self.assertAlmostEqual(ctx_grouped["need"], ctx_direct["need"], places=3)
        grouped["budgets"]["lightmap"]["texels_per_m"] = 200
        f, _ = run(grouped)
        self.assertTrue(any(m.startswith("lightmaps:") for m in messages(f, "ERROR")), f.items)

    def test_uses_as_a_list_counts_each_entry_once(self):
        spec = study_spec()
        spec["assemblies"] = [{"name": "ASM_WallRun_A", "file": "blender/asm/ASM_WallRun_A.blend",
                               "size": [4, 0.2, 3], "uses": ["INT_Wall_2x3_A", "INT_Wall_2x3_A"]}]
        spec["zones"][0]["placements"] = [{"ref": "ASM_WallRun_A", "pos": [1, 1, 0], "rot": 0}]
        f, ctx = run(spec)
        self.assertEqual(ctx["counts"].get("INT_Wall_2x3_A"), 2)
        self.assertTrue(any("uses is a list" in m for m in messages(f, "NOTE")), f.items)

    def test_assembly_file_is_named_after_the_assembly(self):
        spec = study_spec()
        spec["assemblies"] = [{"name": "ASM_WallRun_A", "file": "blender/asm/ASM_WallRun.blend",
                               "size": [4, 0.2, 3], "uses": {"INT_Wall_2x3_A": 2}}]
        f, _ = run(spec)
        self.assertTrue(any("one assembly per ASM file" in m for m in messages(f, "ERROR")), f.items)

    def single_spec(self):
        spec = study_spec()
        for fam in spec["families"].values():
            fam["file"] = "blender/MASTER.blend"
        spec["assemblies"] = [{"name": "ASM_WallRun_A", "file": "blender/MASTER.blend", "size": [4, 0.2, 3],
                               "uses": {"INT_Wall_2x3_A": 2}}]
        spec["zones"][0]["placements"].append({"ref": "ASM_WallRun_A", "pos": [1, 5, 0], "rot": 0})
        return spec

    def test_single_layout_puts_everything_in_master(self):
        f, ctx = run(self.single_spec())
        self.assertEqual(ctx.get("layout"), "single")
        self.assertFalse([m for m in messages(f, "ERROR") if "MASTER" in m or "assembly" in m], f.items)
        self.assertEqual(run(study_spec())[1].get("layout"), "split")

    def test_mixed_layout_is_an_error(self):
        spec = self.single_spec()
        spec["families"]["PROP"]["file"] = "blender/kits/KIT_Props.blend"
        f, ctx = run(spec)
        self.assertIsNone(ctx.get("layout"))
        self.assertTrue(any("mix blender/MASTER.blend" in m for m in messages(f, "ERROR")), f.items)

    def test_layout_against_the_ledger(self):
        f = SV.Findings()
        SV.check_layout({"intake": {}, "tasks": []}, "single", f)
        self.assertTrue(any("blend_layout is not set" in m for m in messages(f, "WARN")), f.items)
        f = SV.Findings()
        SV.check_layout({"intake": {"blend_layout": "split"}, "tasks": []}, "single", f)
        self.assertTrue(any("records the split layout" in m for m in messages(f, "ERROR")), f.items)
        f = SV.Findings()
        SV.check_layout({"intake": {"blend_layout": "single"},
                         "tasks": [{"id": "T-GREY-WORLD", "writes": ["blender/kits/KIT_World.blend"]}]}, "single", f)
        self.assertTrue(any("T-GREY-WORLD writes blender/kits" in m for m in messages(f, "WARN")), f.items)
        f = SV.Findings()
        SV.check_layout({"intake": {"blend_layout": "single"},
                         "tasks": [{"id": "T-GREY-WORLD", "writes": ["blender/MASTER.blend"]}]}, "single", f)
        self.assertEqual(f.items, [])

    def test_lightmapped_free_piece_without_size_is_warned(self):
        spec = study_spec()
        del spec["pieces"][4]["size"]
        f, ctx = run(spec)
        self.assertTrue(any("PROP_Desk_Free_A" in m and "no size" in m for m in messages(f, "WARN")), f.items)
        self.assertNotIn("PROP_Desk_Free_A", ctx["side"])
        spec["pieces"][4]["lightmap"] = False             # probe-lit: nothing to say
        f, ctx = run(spec)
        self.assertFalse(any("PROP_Desk_Free_A" in m for m in messages(f, "WARN")), f.items)

    def test_footprint_formula_matches_the_measured_wall(self):
        # measured 2026-10-16, Unity 2022.3.22f1: a 2 x 3 x 0.2 m wall (UV2 bounding-box share b 0.850) got 242.8 px
        self.assertAlmostEqual(SV.footprint_px((2, 0.2, 3), 60), 242.8, delta=1.0)
        self.assertAlmostEqual(SV.footprint_px((2, 0.2, 3), 60, 2.0), 487.0, delta=1.0)

    def test_lightmap_scale_enters_the_footprint(self):
        spec = study_spec()
        spec["pieces"][0]["lightmap_scale"] = 2
        _, ctx = run(spec)
        self.assertAlmostEqual(ctx["side"]["INT_Wall_2x3_A"], 2 * ctx["side"]["INT_Door_2x3_A"], places=6)

    def test_bakery_plans_with_its_own_footprint_and_cost(self):
        # Bakery (ftBuildGraphics.cs, read 2026-10-24, issue #10): a rect of side texels_per_m x sqrt(2 x A x scale);
        # the footprint takes the Default packer's 3-texel inset off each side; the rect costs 2 x A x scale x
        # texels_per_m^2 for square UV2 bounds (twice Progressive's at scale 1, linear in the scale), each LOD at its
        # own area
        size = (2, 0.2, 3)                                                  # a 14 m2 box
        self.assertAlmostEqual(SV.box_cost(size, 60, 1, "bakery"), 2 * SV.box_cost(size, 60), places=6)
        self.assertAlmostEqual(SV.box_cost(size, 60, 4, "bakery"), 4 * SV.box_cost(size, 60, 1, "bakery"), places=6)
        self.assertAlmostEqual(SV.footprint_px(size, 60, 1, "bakery"), (60 * math.sqrt(28) - 6) / math.sqrt(0.85),
                               places=6)
        self.assertAlmostEqual(SV.lod_factor({"lods": 2}, "bakery"), 3.0)
        self.assertAlmostEqual(SV.lod_factor({"lods": 2, "lod_lightmap": False}, "bakery"), 1.0)
        spec = study_spec()
        f, before = run(spec)
        self.assertEqual(before["baker"], "progressive")
        self.assertFalse([m for m in messages(f, "NOTE") if "lighting.baker is bakery" in m])
        spec["lighting"]["baker"] = "bakery"
        f, ctx = run(spec)
        self.assertEqual(ctx["baker"], "bakery")
        self.assertAlmostEqual(ctx["need"], 2 * before["need"], places=3)   # scale 1, no LODs, nothing probe-lit
        self.assertAlmostEqual(ctx["side"]["INT_Wall_2x3_A"], SV.footprint_px(size, 50, 1, "bakery"), places=6)
        notes = [m for m in messages(f, "NOTE") if "lighting.baker is bakery" in m]
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("not yet measured in a bake", notes[0])
        self.assertIn("--lightmapper bakery", notes[0])
        self.assertEqual(f.warnings, 0, f.items)                         # the clean spec stays clean
        lines = SV.footprint_report(ctx)
        self.assertTrue(lines[0].startswith("Lightmap fill at 50 texels/m (Bakery's Texels Per Unit)"), lines[0])
        self.assertTrue(any(ln.startswith("cost = 2 x A x lightmap_scale x texels_per_m^2") for ln in lines), lines)
        spec["pieces"][0]["lods"] = 2                                     # the seven walls, LOD1 and LOD2 lightmapped
        _, lods = run(spec)
        self.assertAlmostEqual(lods["need"] - ctx["need"], 7 * 2 * SV.box_cost(size, 50, 1, "bakery"), places=3)

    def test_lightmap_fill_thresholds(self):
        # Canon: on box cost, warn above 0.65 of the maps' area (below every spill measured at Lightmap Padding 2)
        # and error above 0.80, where a spill is likely (kit-like sets spilled at 0.79-0.90).
        for tpm, fill, kind in ((50, 0.447, None), (60, 0.644, None), (61, 0.666, "WARN"), (66, 0.780, "WARN"),
                                (67, 0.803, "ERROR")):
            spec = study_spec()
            spec["budgets"]["lightmap"]["texels_per_m"] = tpm
            f, ctx = run(spec)
            self.assertAlmostEqual(ctx["fill"], fill, places=2)
            lightmap = [k for k, m in f.items if m.startswith("lightmaps:")]
            self.assertEqual(lightmap, [kind] if kind else [], (tpm, f.items))

    def test_small_free_prop_is_probe_lit_and_left_out(self):
        # Canon (vrchat-lighting-and-baking, 2026-10-17): under 64 px a FREE PROP is probe-lit, no lightmap space.
        _, before = run(study_spec())
        spec = study_spec()
        spec["pieces"][5]["lightmap"] = True
        spec["pieces"][5]["size"] = [0.08, 0.03, 0.12]
        f, ctx = run(spec)
        self.assertTrue(any("Free prop PROP_LightSwitch_Free_A" in m and "probe-lit" in m
                            for m in messages(f, "WARN")), f.items)
        self.assertLess(ctx["side"]["PROP_LightSwitch_Free_A"], 64)
        self.assertAlmostEqual(ctx["need"], before["need"], places=6)

    def test_small_grid_piece_is_told_to_raise_its_scale_and_still_counts(self):
        # Canon: a GRID piece under 64 px is never made probe-lit; it is warned and stays in the fill.
        spec = study_spec()
        spec["budgets"]["lightmap"]["texels_per_m"] = 15                  # the lighting skill's interior range
        f, ctx = run(spec)
        wall = ctx["side"]["INT_Wall_2x3_A"]
        self.assertLess(wall, 64)                                         # about 61 px
        notes, warnings = messages(f, "NOTE"), messages(f, "WARN")
        self.assertTrue(any(m.startswith("grid piece INT_Wall_2x3_A") and "lightmap_scale" in m for m in notes),
                        notes)                                            # a NOTE: a clean spec stays 0 warnings
        self.assertFalse(any("INT_Wall_2x3_A" in m for m in warnings), warnings)
        self.assertFalse(any("INT_Wall_2x3_A" in m and "probe-lit" in m for m in notes), notes)
        self.assertGreaterEqual(ctx["need"], 7 * SV.box_cost((2, 0.2, 3), 15))

    def test_enumerated_fields(self):
        spec = study_spec()
        spec["interactivity"].append({"id": "light_switch", "desc": "again", "sync": "sometimes"})
        spec["zones"][0]["kind"] = "outside"
        spec["lighting"]["mode"] = "mixed"
        errors = messages(run(spec)[0], "ERROR")
        for needle in ("duplicated", "sync must be", "kind must be", "lighting.mode mixed"):
            self.assertTrue(any(needle in m for m in errors), (needle, errors))
        pc_only = study_spec()
        pc_only["world"]["platforms"] = ["pc"]
        pc_only["lighting"]["mode"] = "mixed"
        self.assertEqual(run(pc_only)[0].errors, 0)

    def test_budgets_per_platform(self):
        spec = study_spec()
        spec["budgets"]["setpass"] = {"pc": 100, "quest": 40}
        self.assertEqual(run(spec)[0].errors, 0)
        spec["budgets"]["setpass"] = {"pc": 100}
        self.assertTrue(any("setpass.quest missing" in m for m in messages(run(spec)[0], "ERROR")))
        spec["budgets"]["setpass"] = {"pc": 200, "quest": 40}
        self.assertTrue(any("setpass.pc = 200" in m for m in messages(run(spec)[0], "ERROR")))

    def test_lighting_states_multiply_the_fill(self):
        # vrchat-lighting-and-baking: box cost x copies x lighting states
        _, one = run(study_spec())
        spec = study_spec()
        spec["zones"][0]["lighting_states"] = 2
        f, two = run(spec)
        self.assertAlmostEqual(two["need"], 2 * one["need"], places=3)
        self.assertEqual(two["counted"]["INT_Wall_2x3_A"], 14)          # 7 walls x 2 states
        spec["zones"][0]["lighting_states"] = 0
        self.assertTrue(any("lighting_states must be" in m for m in messages(run(spec)[0], "ERROR")))

    def test_a_small_prop_in_a_zone_with_lighting_states_stays_lightmapped(self):
        spec = study_spec()
        spec["pieces"][5]["lightmap"] = True
        spec["pieces"][5]["size"] = [0.08, 0.03, 0.12]                    # the switch: a few px
        _, ctx = run(spec)
        self.assertNotIn("PROP_LightSwitch_Free_A", ctx["counted"])       # one state: probe-lit
        spec["zones"][0]["lighting_states"] = 2
        f, ctx = run(spec)
        self.assertEqual(ctx["counted"]["PROP_LightSwitch_Free_A"], 2)    # counted in each copy
        self.assertFalse(any("PROP_LightSwitch_Free_A" in m for m in messages(f, "WARN")), f.items)
        self.assertTrue(any("PROP_LightSwitch_Free_A" in m and "lighting states" in m for m in messages(f, "NOTE")))

    def test_a_one_number_size_needs_size(self):
        spec = study_spec()
        spec["pieces"].append({"name": "INT_Post_3_A", "desc": "corner post", "collision": "box"})
        spec["zones"][0]["placements"].append({"ref": "INT_Post_3_A", "pos": [1, 1, 0], "rot": 0})
        self.assertTrue(any("one-number Size is ambiguous" in m for m in messages(run(spec)[0], "ERROR")))
        spec["pieces"][-1]["size"] = [0.2, 0.2, 3]
        f, ctx = run(spec)
        self.assertEqual(f.errors, 0, f.items)
        self.assertEqual(SV.piece_extent("INT_Post_3_A", 1.0, spec["families"], [0.2, 0.2, 3]), (0.2, 0.2, 3.0))
        self.assertIsNone(SV.piece_extent("INT_Post_3_A", 1.0, spec["families"]))
        self.assertIn("INT_Post_3_A", ctx["side"])
        spec["pieces"][-1]["size"] = [0.2, 0.2, 2]                          # the token says 3 modules
        self.assertTrue(any("does not match its Size token" in m for m in messages(run(spec)[0], "WARN")))

    def test_trim_materials_are_allowed_in_any_family(self):
        spec = study_spec()
        spec["families"]["INT"]["materials"] = ["M_INT_Wallpaper", "M_TRIM_Sheet01"]
        self.assertEqual(run(spec)[0].errors, 0)

    def test_grid_placements_off_the_grid_are_errors(self):
        # QA blocks on these (B4, A3), so the validator must too; Free pieces and assemblies are exempt.
        spec = study_spec()
        spec["zones"][0]["placements"][1]["pos"] = [3.5, 1, 0]
        spec["zones"][0]["placements"][2]["rot"] = 45
        errors = messages(run(spec)[0], "ERROR")
        self.assertTrue(any("off the 1.0 m grid" in m for m in errors), errors)
        self.assertTrue(any("rotated 45 deg" in m for m in errors), errors)
        spec = study_spec()
        spec["zones"][0]["placements"][-1]["pos"] = [3.37, 1.23, 1.2]    # the Free switch: anywhere
        self.assertEqual(run(spec)[0].errors, 0)

    def test_trim_pieces_go_on_the_sub_module(self):
        spec = study_spec()
        spec["families"]["TRIM"] = {"file": "blender/kits/KIT_World.blend", "materials": ["M_TRIM_Sheet01"],
                                    "texturing": "trim", "texel_density": 512, "map_px": 1024}
        spec["budgets"]["piece_tris"]["TRIM"] = 100
        spec["pieces"].append({"name": "TRIM_Skirting_2_A", "desc": "skirting", "collision": "none"})
        # on the south wall's inner face, y 1.2 (the 0.2 m INT wall stands on y 1)
        spec["zones"][0]["placements"].append({"ref": "TRIM_Skirting_2_A", "pos": [3, 1.2, 0], "rot": 0})
        errors = messages(run(spec)[0], "ERROR")                          # 1.2 is off a 0.25 m sub-module
        self.assertTrue(any("TRIM_Skirting_2_A at [3, 1.2] is off the 0.25 m sub-module" in m for m in errors),
                        errors)
        spec["grid"]["sub_module"] = 0.1                                  # divides the 0.2 m thickness
        self.assertFalse(any("sub-module" in m for m in messages(run(spec)[0], "ERROR")))

    def test_family_thickness_and_the_trim_sub_module(self):
        spec = study_spec()
        spec["families"]["TRIM"] = {"file": "blender/kits/KIT_World.blend", "materials": ["M_TRIM_Sheet01"],
                                    "texturing": "trim", "texel_density": 512, "map_px": 1024}
        spec["budgets"]["piece_tris"]["TRIM"] = 100
        spec["grid"]["sub_module"] = 0.25                                 # INT is 0.2 m thick: not a multiple
        warnings = messages(run(spec)[0], "WARN")
        self.assertTrue(any("family INT thickness 0.2 m is not a multiple of grid.sub_module" in m
                            for m in warnings), warnings)
        spec["grid"]["sub_module"] = 0.1
        warnings = messages(run(spec)[0], "WARN")
        self.assertFalse(any("not a multiple of grid.sub_module" in m for m in warnings), warnings)

    def test_lightmap_count_and_max_px_are_validated(self):
        for key, value, needle in (("count", "2", "count must be a whole number"),
                                   ("count", 0, "count must be a whole number"),
                                   ("max_px", "1024", "max_px must be a positive number")):
            spec = study_spec()
            spec["budgets"]["lightmap"][key] = value
            f, _ = run(spec)                                              # no TypeError
            self.assertTrue(any(needle in m for m in messages(f, "ERROR")), (key, value, f.items))

    def test_realtime_wording(self):
        spec = study_spec()
        spec["lighting"]["mode"] = "mixed"
        errors = " ".join(messages(run(spec)[0], "ERROR"))
        self.assertIn("Standard Lite takes the main directional light unshadowed", errors)
        self.assertNotIn("renders no realtime", errors)

    def test_atlas_cost_is_the_chart_box(self):
        # Canon (Unity 2022.3.22f1, measured 2026-10-17): Unity packs each renderer's UV2 chart box, so a renderer
        # costs (texels_per_m x Scale In Lightmap)^2 x A px^2 whatever its UV2 layout: the old footprint squared, over
        # by 1 / b. The footprint itself (it sets the UV2 gaps) is unchanged.
        self.assertAlmostEqual(SV.box_cost((2, 0.2, 3), 60), 60 ** 2 * 14, places=6)
        self.assertAlmostEqual(SV.box_cost((2, 0.2, 3), 60), SV.footprint_px((2, 0.2, 3), 60) ** 2 * 0.85, places=3)
        self.assertAlmostEqual(SV.box_cost((2, 0.2, 3), 60, 2.0), 4 * SV.box_cost((2, 0.2, 3), 60), places=6)
        _, ctx = run(study_spec())
        area = 8 * 14 + 8 * 8.8 + 2 * (1.4 * 0.7 + 0.7 * 0.78 + 1.4 * 0.78)   # walls, slabs, desk
        self.assertAlmostEqual(ctx["need"], 50 ** 2 * area, places=3)

    def test_lightmapped_lods_add_a_quarter_per_level(self):
        # Canon: LODn gets its own atlas space at texel scale 0.5^n, so it costs 0.25^n of its area (LOD1 + LOD2:
        # about 31% more); LOD1+ set to Light Probes leave the atlas.
        spec = study_spec()
        _, before = run(spec)
        spec["pieces"][0]["lods"] = 2                                     # the seven walls
        f, ctx = run(spec)
        self.assertEqual(f.errors, 0, f.items)
        self.assertAlmostEqual(ctx["need"] - before["need"], 7 * SV.box_cost((2, 0.2, 3), 50) * 0.3125, places=3)
        self.assertAlmostEqual(SV.lod_factor(spec["pieces"][0]), 1.3125)
        spec["pieces"][0]["lod_lightmap"] = False                         # LOD1+ probe-lit
        self.assertAlmostEqual(run(spec)[1]["need"], before["need"], places=3)
        spec["pieces"][0]["lod_lightmap"] = "no"
        self.assertTrue(any("lod_lightmap must be true or false" in m for m in messages(run(spec)[0], "ERROR")))

    def test_switches_storeys_and_real_edges(self):
        # Round 5, the cottage: a switch per storey; zones compare switches, skip pairs a storey apart, and a piece
        # must run along the edge (not touch it with a corner or an end) to be noted.
        spec = study_spec()
        spec["budgets"]["lightmap"]["count"] = 2
        spec["elevations"], spec["views"] = [], []

        def wall(ref, x, y, rot, z=0):
            return {"ref": ref, "pos": [x, y, z], "rot": rot}

        def zone(zid, bounds, floor, placements, states=1, **extra):
            return dict({"id": zid, "name": zid, "kind": "interior", "bounds": bounds, "floor_z": floor,
                         "lighting_states": states, "placements": placements, "rooms": []}, **extra)

        lounge = zone("lounge", [2, 4, 8, 10], 0, [wall("INT_Wall_2x3_A", 2, 4, 0)], states=2)
        lounge["rooms"] = [{"id": "lounge", "name": "Lounge", "bounds": [2, 4.2, 8, 10], "height": 3,
                            "openings": [{"type": "door", "at": [4.4, 4.2], "width": 1.2, "height": 2.2}]}]
        garden = zone("garden", [0, 0, 12, 4], 0, [wall("INT_Door_2x3_A", 4, 4, 0)], kind="exterior")
        kitchen = zone("kitchen", [8, 4, 12, 10], 0, [
            wall("INT_Door_2x3_A", 8, 6, 90),                             # the wall the two rooms share
            wall("INT_Wall_2x3_A", 8, 4, 0),                              # runs away from the edge: touches a corner
            {"ref": "STR_Floor_2x2_A", "pos": [8, 4, -0.1], "rot": 0}])   # a slab whose side meets the edge
        bedroom = zone("bedroom", [2, 4, 8, 10], 3, [wall("INT_Wall_2x3_A", 2, 4, 0, 3)], states=2)
        spec["zones"] = [garden, lounge, kitchen, bedroom]
        f, _ = run(spec)
        self.assertEqual(f.errors, 0, f.items)
        notes = [m for m in messages(f, "NOTE") if "Lightmap check" in m]
        self.assertTrue(any(m.startswith("zone garden places INT_Door_2x3_A on the edge of zone lounge")
                            for m in notes), notes)
        self.assertTrue(any(m.startswith("zone kitchen places INT_Door_2x3_A on the edge of zone lounge")
                            for m in notes), notes)                       # the door wall only: no slab, no corner
        self.assertFalse(any("bedroom" in m for m in notes), notes)       # a storey above the garden and the kitchen
        kitchen["lighting_states"] = 2                                    # its own switch: independent
        notes = [m for m in messages(run(spec)[0], "NOTE") if "Lightmap check" in m]
        self.assertTrue(any("zone kitchen (switch kitchen) places INT_Door_2x3_A on the edge of zone lounge (switch "
                            "lounge): a piece two switches light is split" in m for m in notes), notes)
        kitchen["switch"] = "lounge"                                      # one switch for both rooms
        notes = [m for m in messages(run(spec)[0], "NOTE") if "Lightmap check" in m]
        self.assertFalse(any("kitchen" in m for m in notes), notes)
        kitchen["lighting_states"] = 3
        errors = messages(run(spec)[0], "ERROR")
        self.assertTrue(any("share switch lounge but have 2 and 3 lighting states" in m for m in errors), errors)

    def test_lod_lightmap_false_is_flagged_in_the_footprints_table(self):
        spec = study_spec()
        spec["pieces"][0].update(lods=2, lod_lightmap=False)
        _, ctx = run(spec)
        row = [line for line in SV.footprint_report(ctx) if line.startswith("INT_Wall_2x3_A")][0]
        self.assertIn("LOD1+ probe-lit (lod_lightmap: false): T-LIGHT sets their Receive GI to Light Probes", row)
        self.assertIn(" 1.00 ", row)                                      # no LOD cost

    def test_chart_boxes_over_half_the_map_side_cannot_share_a_map(self):
        # Parity with lightmap_budget.py: a near-square chart box over half the map side (side = sqrt(box cost))
        # cannot share a map with another such box, so there can be no more of them than maps.
        spec = study_spec()
        spec["pieces"].append({"name": "PROP_Stage_Free_A", "desc": "stage", "collision": "box", "size": [6, 6, 3],
                               "lods": 1})
        spec["zones"][0]["placements"] += [{"ref": "PROP_Stage_Free_A", "pos": [3, 3, 0], "rot": 0}] * 2
        f, ctx = run(spec)                                                # 50 x sqrt(144) = 600 px > 512, twice
        warnings = [m for m in messages(f, "WARN") if m.startswith("lightmap chart boxes:")]
        self.assertEqual(len(warnings), 1, f.items)
        self.assertIn("2 are over half the 1024 px map side (PROP_Stage_Free_A 600 px x 2)", warnings[0])
        self.assertEqual(ctx["big_boxes"], 2)                             # LOD1, at 300 px, is not big
        spec["budgets"]["lightmap"]["count"] = 2
        f, _ = run(spec)
        self.assertFalse(any(m.startswith("lightmap chart boxes:") for m in messages(f, "WARN")), f.items)

    def test_only_free_prop_and_fol_pieces_turn_probe_lit(self):
        # Canon (round 4): the 64 px rule covers Free pieces of PROBE_LIT_FAMILIES only; a ZONE shell gets the
        # grid-piece NOTE, stays lightmapped and counts.
        self.assertEqual(SV.PROBE_LIT_FAMILIES, ("PROP", "FOL"))
        spec = study_spec()
        spec["families"]["ZONE"] = dict(spec["families"]["STR"], materials=["M_ZONE_Shell"], texturing="unique")
        spec["budgets"]["piece_tris"]["ZONE"] = 500
        spec["pieces"] += [
            {"name": "ZONE_Niche_Free_A", "desc": "small unique shell", "collision": "mesh", "size": [0.3, 0.3, 0.3]},
            {"name": "PROP_Chair_Free_A", "desc": "chair", "collision": "box", "size": [0.3, 0.3, 0.5]}]
        spec["zones"][0]["placements"] += [{"ref": "ZONE_Niche_Free_A", "pos": [2, 4.5, 0], "rot": 0},
                                           {"ref": "PROP_Chair_Free_A", "pos": [3, 3.6, 0], "rot": 0}]
        f, ctx = run(spec)
        self.assertLess(ctx["side"]["ZONE_Niche_Free_A"], 64)
        self.assertLess(ctx["side"]["PROP_Chair_Free_A"], 64)
        self.assertEqual(ctx["counted"].get("ZONE_Niche_Free_A"), 1)      # lightmapped and counted
        self.assertNotIn("PROP_Chair_Free_A", ctx["counted"])             # probe-lit
        notes, warnings = messages(f, "NOTE"), messages(f, "WARN")
        self.assertTrue(any(m.startswith("Free ZONE piece ZONE_Niche_Free_A") for m in notes), notes)
        self.assertFalse(any("ZONE_Niche_Free_A" in m for m in warnings), warnings)
        self.assertTrue(any("Free prop PROP_Chair_Free_A" in m and "probe-lit" in m for m in warnings), warnings)

    def test_unknown_keys_are_warned_with_a_hint(self):
        spec = study_spec()
        spec["zones"][0]["lighting_state"] = 2
        spec["lighting"]["states"] = 2
        spec["pieces"][0]["lightmapscale"] = 2
        f, ctx = run(spec)
        warnings = messages(f, "WARN")
        for needle in ("zone study: unknown key 'lighting_state' is ignored (did you mean lighting_states?)",
                       "lighting: unknown key 'states' is ignored (did you mean zones[].lighting_states",
                       "piece INT_Wall_2x3_A: unknown key 'lightmapscale' is ignored (did you mean lightmap_scale?)"):
            self.assertTrue(any(needle in m for m in warnings), (needle, warnings))
        _, clean = run(study_spec())
        self.assertAlmostEqual(ctx["need"], clean["need"], places=6)     # ignored: one state, scale 1

    def test_wrong_types_are_errors_not_tracebacks(self):
        cases = ((("budgets", "lightmap", "min_footprint_px"), None, "min_footprint_px must be a positive number"),
                 (("budgets", "lightmap", "min_footprint_px"), "64", "min_footprint_px must be a positive number"),
                 (("families", "INT", "thickness"), None, "family INT thickness must be a positive number"),
                 (("budgets", "piece_tris"), 800, "budgets.piece_tris must map each family code"),
                 (("families", "INT", "texturing"), ["tiling", "trim"], "family INT texturing must be one of"),
                 (("budgets", "lightmap", "texels_per_m"), "12", "texels_per_m must be a positive number"),
                 (("budgets", "lightmap", "texels_per_m"), 0, "texels_per_m must be a positive number"),
                 (("zones", 0, "placements", 1, "pos"), "3, 1", "pos: [x, y, z] in metres"),
                 (("version",), "1", "version must be 1"))
        for path, value, needle in cases:
            spec = study_spec()
            node = spec
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
            f, _ = run(spec)                                              # used to raise, or to say "missing"
            self.assertTrue(any(needle in m for m in messages(f, "ERROR")), (path, value, f.items))
            self.assertFalse(any("texels_per_m missing" in m for m in messages(f, "WARN")), (path, value))

    def test_sub_module_divides_the_module(self):
        spec = study_spec()
        spec["grid"]["sub_module"] = 0.3
        self.assertTrue(any("must divide grid.module" in m for m in messages(run(spec)[0], "ERROR")))
        spec["grid"]["sub_module"] = "0.25"
        self.assertTrue(any("grid.sub_module must be a positive number" in m
                            for m in messages(run(spec)[0], "ERROR")))
        spec = study_spec()
        del spec["grid"]["sub_module"]
        spec["families"]["TRIM"] = {"file": "blender/kits/KIT_World.blend", "materials": ["M_TRIM_Sheet01"],
                                    "texturing": "trim", "texel_density": 512, "map_px": 1024}
        spec["budgets"]["piece_tris"]["TRIM"] = 100
        spec["pieces"].append({"name": "TRIM_Skirting_2_A", "desc": "skirting", "collision": "none"})
        spec["zones"][0]["placements"].append({"ref": "TRIM_Skirting_2_A", "pos": [3, 1.2, 0], "rot": 0})
        errors = messages(run(spec)[0], "ERROR")
        self.assertTrue(any("off the 1.0 m grid (TRIM pieces go on grid.sub_module" in m for m in errors), errors)

    def test_rotation_float_noise_is_a_right_angle(self):
        spec = study_spec()
        spec["zones"][0]["placements"][4]["rot"] = 89.9999999
        spec["zones"][0]["placements"][6]["rot"] = 270.0000001
        self.assertEqual(run(spec)[0].errors, 0)

    def test_a_switch_changes_the_light_in_one_zone(self):
        def edge_notes(spec):
            return [m for m in messages(run(spec)[0], "NOTE") if "Lightmap check" in m]

        spec = study_spec()
        spec["zones"][0]["lighting_states"] = 2
        spec["budgets"]["lightmap"]["count"] = 2                          # two states double the fill
        self.assertEqual(edge_notes(spec), [])                            # one zone: nothing shared
        street = {"id": "street", "name": "Street", "kind": "exterior", "bounds": [0, -6, 6, 1], "floor_z": 0,
                  "placements": [], "rooms": []}
        spec["zones"].append(street)
        notes = edge_notes(spec)                                          # the study's door opens onto the street
        self.assertTrue(any("1 opening(s) of its rooms face zone street" in m for m in notes), notes)
        front = [pl for pl in spec["zones"][0]["placements"]
                 if pl["ref"].startswith("INT_") and pl["pos"][:2] in ([1, 1], [3, 1])]
        spec["zones"][0]["placements"] = [pl for pl in spec["zones"][0]["placements"] if pl not in front]
        street["placements"] = front                                      # the front wall placed in the street
        f, ctx = run(spec)
        self.assertEqual(f.errors, 0, f.items)
        self.assertTrue(any("zone street places INT_Door_2x3_A, INT_Wall_2x3_A on the edge of zone study" in m
                            for m in messages(f, "NOTE")), f.items)
        self.assertEqual(ctx["counted"]["INT_Door_2x3_A"], 1)             # the copies miss the street's front
        street.update(lighting_states=2, switch="study")                  # one switch for both zones
        self.assertEqual(edge_notes(spec), [])

    def test_a_probe_lit_piece_in_a_switched_zone_is_noted(self):
        spec = study_spec()
        self.assertFalse(any("will not change with the switch" in m for m in messages(run(spec)[0], "NOTE")))
        spec["zones"][0]["lighting_states"] = 2
        notes = messages(run(spec)[0], "NOTE")
        self.assertTrue(any(m.startswith("piece PROP_LightSwitch_Free_A is probe-lit (lightmap: false) in zone "
                                         "study") and "will not change with the switch" in m for m in notes), notes)

    def test_mirror_slots(self):
        spec = study_spec()
        spec["zones"][0]["mirrors"] = [{"id": "study_mirror", "pos": [3, 4.8, 1.6], "rot": 0, "size": [1.2, 2.0]}]
        f, _ = run(spec)
        self.assertEqual((f.errors, f.warnings), (0, 0), f.items)
        spec["zones"][0]["mirrors"].append({"id": "study_mirror", "pos": [9, 4.8, 1.6], "size": [1.2],
                                            "colour": "silver"})
        f, _ = run(spec)
        errors, warnings = messages(f, "ERROR"), messages(f, "WARN")
        for needle in ("mirror id 'study_mirror' missing or duplicated", "size must be [width, height]"):
            self.assertTrue(any(needle in m for m in errors), (needle, errors))
        for needle in ("is outside the zone", "unknown key 'colour'"):
            self.assertTrue(any(needle in m for m in warnings), (needle, warnings))

    def test_quality_tier(self):
        spec = study_spec()
        notes = messages(run(spec)[0], "NOTE")
        self.assertTrue(any("world.quality is not set, so parity is assumed" in m for m in notes), notes)
        spec["world"]["quality"] = "best"
        self.assertTrue(any("world.quality must be pc_lead or parity" in m for m in messages(run(spec)[0], "ERROR")))
        spec["world"]["quality"] = "pc_lead"                 # every budget one number: PC is held to mobile's
        f = run(spec)[0]
        self.assertEqual((f.errors, f.warnings), (0, 0), f.items)
        self.assertTrue(any("held to the mobile budgets" in m for m in messages(f, "NOTE")), f.items)
        spec["budgets"]["texture_vram_mb"] = {"pc": 600, "quest": 20}
        self.assertFalse(any("held to the mobile budgets" in m for m in messages(run(spec)[0], "NOTE")))
        spec["world"]["platforms"] = ["pc"]
        self.assertTrue(any("pc_lead only matters" in m for m in messages(run(spec)[0], "NOTE")))

    def test_look_section(self):
        spec = study_spec()
        self.assertTrue(any(m.startswith("look missing") for m in messages(run(spec)[0], "NOTE")))
        spec["look"] = {"references": ["world/refs/study_01.jpg"], "wear": "weathered",
                        "lighting_mood": "2700 K lamps, dim blue moonlight", "lead_family": "INT",
                        "materials": {"M_INT_Wallpaper": {"ref": "world/refs/paper.jpg", "albedo_srgb": [70, 140],
                                                          "roughness": [0.6, 0.9], "metal": False,
                                                          "wear": "faded where the sun reaches"}}}
        spec["pieces"][0]["ref"] = ["world/refs/wall_bay.jpg"]
        spec["pieces"][0]["detail"] = ["skirting: 150 mm high, 20 mm proud", "picture rail at 2.1 m"]
        spec["families"]["INT"]["detail_map"] = True
        f = run(spec)[0]
        self.assertEqual((f.errors, f.warnings), (0, 0), f.items)
        self.assertFalse(any(m.startswith("look missing") for m in messages(f, "NOTE")))
        spec["look"]["wear"] = "grimy"
        spec["look"]["lead_family"] = "EXT"
        spec["look"]["materials"]["M_EXT_Brick"] = {"albedo_srgb": [140, 70]}
        spec["look"]["materials"]["M_INT_Wallpaper"].update(roughness=[0.9, 0.6], metal="no", colour="red")
        spec["pieces"][0]["detail"] = "skirting"
        spec["pieces"][1]["ref"] = 3
        spec["families"]["STR"]["detail_map"] = "yes"
        f = run(spec)[0]
        errors = messages(f, "ERROR")
        for needle in ("look.wear must be one of", "look.lead_family 'EXT' is not in families",
                       "look.materials.M_EXT_Brick: not a material any family lists",
                       "look.materials.M_EXT_Brick.albedo_srgb must be [low, high]",
                       "look.materials.M_INT_Wallpaper.roughness must be [low, high]",
                       "look.materials.M_INT_Wallpaper.metal must be true or false",
                       "piece INT_Wall_2x3_A: detail must be a list", "piece INT_Door_2x3_A: ref must be an image path",
                       "family STR detail_map must be true or false"):
            self.assertTrue(any(needle in m for m in errors), (needle, errors))
        self.assertTrue(any("unknown key 'colour'" in m for m in messages(f, "WARN")), f.items)

    def test_look_targets_outside_the_pbr_range_and_missing_images(self):
        spec = study_spec()
        spec["look"] = {"references": ["world/refs/missing.jpg"],
                        "materials": {"M_STR_Boards": {"albedo_srgb": [20, 120]}}}
        warnings = messages(run(spec)[0], "WARN")
        self.assertTrue(any("reaches outside 30-240" in m for m in warnings), warnings)
        with tempfile.TemporaryDirectory() as d:
            f = SV.Findings()
            SV.check_spec(spec, f, root=d)
            self.assertTrue(any("look.references: world/refs/missing.jpg does not exist yet" in m
                                for m in messages(f, "WARN")), f.items)

    def test_intake_only_spec(self):
        spec = {k: v for k, v in study_spec().items() if k in ("version", "world", "tools")}
        f, ctx = run(spec)
        self.assertEqual((f.errors, f.warnings), (0, 0), f.items)
        self.assertEqual(ctx, {})
        spec["budgets"] = {"world_tris": 500000}           # template ceilings are checked at stage 0 too
        errors = messages(run(spec)[0], "ERROR")
        self.assertTrue(any("world_tris = 500000" in m for m in errors), errors)


class LedgerChecks(unittest.TestCase):
    def ledger(self, *tasks):
        return {"gates": {}, "tasks": [dict({"stage": 10, "role": "unity-integrator", "status": "todo"}, **t)
                                       for t in tasks]}

    def test_folder_without_trailing_slash_overlaps_its_files(self):
        led = self.ledger({"id": "T-A", "writes": ["Assets/World/Kits/INT"]},
                          {"id": "T-B", "writes": ["Assets/World/Kits/INT/Wall/Wall.prefab"]})
        f = SV.Findings()
        SV.check_ledger(led, f)
        self.assertTrue(any("T-A and T-B" in m for m in messages(f, "ERROR")), f.items)
        led["tasks"][1]["deps"] = ["T-A"]
        f = SV.Findings()
        SV.check_ledger(led, f)
        self.assertEqual(f.errors, 0, f.items)

    def test_qa_null_is_not_qa_false(self):
        f = SV.Findings()
        SV.check_ledger(self.ledger({"id": "T-A", "writes": ["@unity"], "qa": None}), f)
        self.assertFalse(any("qa: false" in m for m in messages(f, "WARN")), f.items)
        f = SV.Findings()
        SV.check_ledger(self.ledger({"id": "T-A", "writes": ["@unity"], "qa": False}), f)
        self.assertTrue(any("qa: false" in m for m in messages(f, "WARN")), f.items)

    def test_a_bare_task_list_is_a_ledger(self):
        f = SV.Findings()
        led = SV.as_ledger([{"id": "T-A", "stage": 4, "role": "kit-modeller", "status": "todo",
                             "writes": ["blender/kits/KIT_World.blend"]}], f, "draft")
        SV.check_ledger(led, f)
        self.assertEqual(f.errors, 0, f.items)

    def gated(self, grey_deps, mod_deps):
        task = {"role": "x", "status": "todo"}
        return {"gates": {"spec": {"status": "pending", "after": ["T-PLAN-01"]},
                          "greybox": {"status": "pending", "after": ["T-GREY-MASTER"]}},
                "tasks": [dict(task, id="T-PLAN-01", stage=2, deps=[], writes=["world/spec.yaml"]),
                          dict(task, id="T-GREY-WORLD", stage=4, deps=grey_deps, writes=["blender/kits/K.blend"]),
                          dict(task, id="T-GREY-MASTER", stage=4, deps=["T-GREY-WORLD"], writes=["blender/M.blend"]),
                          dict(task, id="T-MOD-WORLD", stage=5, deps=mod_deps, writes=["blender/kits/K.blend"]),
                          dict(task, id="T-UV-WORLD", stage=6, deps=["T-MOD-WORLD"], writes=["blender/kits/K.blend"])]}

    def test_gate_dependencies(self):
        f = SV.Findings()
        SV.check_ledger(self.gated(["gate:spec"], ["gate:greybox"]), f)
        self.assertEqual((f.errors, f.warnings), (0, 0), f.items)
        f = SV.Findings()                                  # plain task deps: the order holds, the gates are bypassed
        SV.check_ledger(self.gated(["gate:spec"], ["T-GREY-MASTER"]), f)
        warnings = messages(f, "WARN")
        self.assertEqual(sorted(m.split(",")[0] for m in warnings),
                         ["task T-MOD-WORLD (stage 5) does not wait for gate:greybox",
                          "task T-UV-WORLD (stage 6) does not wait for gate:greybox"])
        f = SV.Findings()
        SV.check_ledger(self.gated(["T-PLAN-01"], ["gate:greybox"]), f)
        warnings = messages(f, "WARN")
        for needle in ("T-GREY-WORLD (stage 4) does not wait for gate:spec",
                       "T-GREY-MASTER (stage 4) does not wait for gate:spec"):
            self.assertTrue(any(m.startswith("task " + needle) for m in warnings), (needle, warnings))
        self.assertFalse(any("gate:greybox" in m for m in warnings), warnings)

    def looked(self, other_tex_deps, exp_deps):
        task = {"role": "x", "status": "todo"}
        return {"gates": {"look": {"status": "pending", "after": ["T-TEX-INT"]}},
                "tasks": [dict(task, id="T-TEX-TRIM-LAYOUT", stage=7, deps=[], writes=["blender/substance/TRIM/"]),
                          dict(task, id="T-TEX-INT", stage=7, deps=["T-TEX-TRIM-LAYOUT"],
                               writes=["blender/textures/INT/"]),
                          dict(task, id="T-TEX-STR", stage=7, deps=other_tex_deps, writes=["blender/textures/STR/"]),
                          dict(task, id="T-EXP-INT", stage=9, deps=exp_deps, writes=["export/fbx/INT/"])]}

    def test_look_gate_holds_the_other_families_and_the_export(self):
        f = SV.Findings()
        SV.check_ledger(self.looked(["gate:look"], ["T-TEX-INT", "gate:look"]), f)
        self.assertEqual((f.errors, f.warnings), (0, 0), f.items)
        f = SV.Findings()                                  # the lead family itself and the trim layout never wait
        SV.check_ledger(self.looked(["T-TEX-INT"], ["T-TEX-INT"]), f)
        warnings = messages(f, "WARN")
        self.assertEqual(sorted(m.split(":")[0] for m in warnings),
                         ["task T-EXP-INT (stage 9) does not wait for gate", "task T-TEX-STR does not wait for gate"])
        led = self.looked([], ["T-TEX-INT"])
        del led["gates"]["look"]
        f = SV.Findings()
        SV.check_ledger(led, f)
        self.assertTrue(any(m.startswith("no look gate") for m in messages(f, "NOTE")), f.items)

    def test_a_running_task_under_a_gate_that_is_not_approved_is_warned(self):
        led = self.gated(["gate:spec"], ["gate:greybox"])
        led["gates"]["spec"]["status"] = "approved"
        led["tasks"][1]["status"] = "running"                             # T-GREY-WORLD
        f = SV.Findings()
        SV.check_ledger(led, f)
        self.assertEqual(f.warnings, 0, f.items)
        led["gates"]["spec"]["status"] = "pending"                        # the gate re-opened
        f = SV.Findings()
        SV.check_ledger(led, f)
        warnings = messages(f, "WARN")                                   # one rule: it finishes; crashed, todo
        self.assertTrue(any("T-GREY-WORLD is running, but gate:spec" in m and "re-opened finishes" in m
                            and "goes back to todo, same attempt" in m for m in warnings), warnings)
        led["gates"]["spec"]["reopened_by"] = "T-GREY-WORLD"              # the task that re-opened it may run
        f = SV.Findings()
        SV.check_ledger(led, f)
        self.assertEqual(f.warnings, 0, f.items)

    def test_a_string_where_a_list_belongs_is_one_error(self):
        led = self.gated(["gate:spec"], ["gate:greybox"])
        led["tasks"][4]["deps"] = "T-MOD-WORLD"                           # a string, not [T-MOD-WORLD]
        led["tasks"][2]["writes"] = "blender/M.blend"
        f = SV.Findings()
        SV.check_ledger(led, f)
        errors = messages(f, "ERROR")
        self.assertEqual(errors, ["task T-GREY-MASTER: writes must be a list, got 'blender/M.blend': write "
                                  "[blender/M.blend]",
                                  "task T-UV-WORLD: deps must be a list, got 'T-MOD-WORLD': write [T-MOD-WORLD]"])

    def test_a_redraft_replaces_ledger_tasks_with_the_same_id(self):
        led = self.gated(["gate:spec"], ["gate:greybox"])
        draft = {"tasks": [dict(led["tasks"][1], title="re-drafted"),
                           {"id": "T-TEX-WORLD", "stage": 7, "role": "x", "status": "todo", "deps": ["T-UV-WORLD"],
                            "writes": ["blender/kits/K.blend"]}]}
        f = SV.Findings()
        merged = SV.merge_draft(led, draft, f)
        SV.check_ledger(merged, f)
        self.assertEqual(f.errors, 0, f.items)
        self.assertTrue(any("replaces 1 ledger task" in m and "T-GREY-WORLD" in m for m in messages(f, "NOTE")))
        self.assertEqual(len(merged["tasks"]), 6)
        self.assertEqual(merged["tasks"][1]["title"], "re-drafted")


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.spec = self.dir / "spec.json"
        self.spec.write_text(json.dumps(study_spec()), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        p = self.dir / name
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_draft_as_a_bare_list_merges_into_the_ledger(self):
        ledger = self.write("ledger.json", {"gates": {"spec": {"status": "approved", "after": ["T-PLAN-01"]}},
                                            "tasks": [{"id": "T-PLAN-01", "stage": 2, "role": "planner",
                                                       "status": "done", "writes": ["world/spec.yaml"]}]})
        grey = {"id": "T-GREY-WORLD", "stage": 4, "role": "kit-modeller", "status": "todo", "deps": ["gate:spec"],
                "writes": ["blender/kits/KIT_World.blend"]}
        master = {"id": "T-GREY-MASTER", "stage": 4, "role": "integrator", "status": "todo", "deps": ["gate:spec"],
                  "writes": ["blender/MASTER.blend", "blender/kits/KIT_World.blend"]}
        draft = self.write("draft.json", [grey, master])
        res = run_cli(self.spec, "--ledger", ledger, "--draft", draft)
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("T-GREY-MASTER and T-GREY-WORLD can run at once", res.stdout)
        master["deps"] = ["T-GREY-WORLD"]
        draft = self.write("draft.json", {"tasks": [grey, master]})
        res = run_cli(self.spec, "--ledger", ledger, "--draft", draft, "--mermaid", self.dir / "tasks.mmd")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("T_GREY_WORLD --> T_GREY_MASTER", (self.dir / "tasks.mmd").read_text(encoding="utf-8"))

    def test_draft_and_mermaid_need_a_ledger(self):
        res = run_cli(self.spec, "--draft", self.spec)
        self.assertEqual(res.returncode, 2)

    def test_root_checks_the_mockup_images(self):
        spec = study_spec()
        spec["views"][0]["matches"] = "world/mockups/study_entry.png"
        path = self.write("spec_mock.json", spec)
        res = run_cli(path, "--root", self.dir)
        self.assertIn("study_entry: world/mockups/study_entry.png does not exist yet", res.stdout)
        (self.dir / "world" / "mockups").mkdir(parents=True)
        (self.dir / "world" / "mockups" / "study_entry.png").write_bytes(b"png")
        res = run_cli(path, "--root", self.dir)
        self.assertNotIn("does not exist", res.stdout)

    def test_footprints_table(self):
        res = run_cli(self.spec, "--footprints")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        wall = [line for line in res.stdout.splitlines() if line.startswith("INT_Wall_2x3_A")]
        self.assertEqual(len(wall), 1, res.stdout)
        self.assertIn("202.9", wall[0])                   # 50 x sqrt(14 / 0.85)
        # The table plans the fill only: UV2 gaps come from each modelled mesh's real area at stage 6.
        self.assertIn("This table plans the lightmap fill only", res.stdout)
        self.assertNotIn("UV2 gap", res.stdout.splitlines()[3])               # no packing columns in the table
        self.assertIn("probe-lit", res.stdout)            # the switch
        out = self.dir / "diagrams" / "lightmap_budget.txt"
        res = run_cli(self.spec, "--footprints", out)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("% fill", out.read_text(encoding="utf-8"))


@unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
class ShippedFiles(unittest.TestCase):
    def test_templates_validate(self):
        res = run_cli(SKILL / "templates" / "spec.yaml", "--ledger", SKILL / "templates" / "ledger.yaml")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("0 error(s), 0 warning(s)", res.stdout)
        self.assertIn("intake-only", res.stdout)

    def test_example_spec_validates_clean(self):
        res = run_cli(SKILL / "references" / "example-spec.yaml", "--footprints")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("0 error(s), 0 warning(s)", res.stdout)
        self.assertIn("TRIM_Cornice_2x1_A", res.stdout)

    @unittest.skipUnless(DRY_RUN_SPEC.exists(), "the 2026-10-16 dry run's spec is not on this machine")
    def test_dry_run_spec_passes_with_its_known_warnings(self):
        res = run_cli(DRY_RUN_SPEC)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("PROP_Desk_Free_A is lightmapped but Free with no size", res.stdout)
        # 63% at box cost (Unity packs chart boxes, measured 2026-10-17); the old footprint-squared sum said 74%
        self.assertNotIn("lightmaps:", res.stdout)
        self.assertIn("0 error(s), 1 warning(s)", res.stdout)


if __name__ == "__main__":
    unittest.main()
