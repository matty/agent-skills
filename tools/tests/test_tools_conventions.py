"""Tests for tools/check_conventions.py: the FORBIDDEN patterns flag the known-wrong statements and nothing correct,
module_constant reads frozenset constants, and the brief-vs-QA check catches a task whose checks drifted.

Host: plain Python 3.9+, standard library. Synthetic skill trees are built in a temp folder.
"""

import importlib.util
import re
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load():
    spec = importlib.util.spec_from_file_location("check_conventions_under_test",
                                                  ROOT / "tools" / "check_conventions.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CC = load()


def flagged(text):
    return [why for pat, why in CC.FORBIDDEN if re.search(pat, text, re.M)]


class Forbidden(unittest.TestCase):
    WRONG = [
        'var t = new Tuple<string, int>("a", 1);',
        "System.Tuple<int, int> pair = null;",
        "var p = Tuple.Create(1, 2);",
        "var rows = new List<Tuple<string, int>>();",
        "static Tuple<int, int> Pair() { return default; }",
        "sum(footprint_px^2 x copies) <= 0.65 x max_px^2",
        "capacity = sum(footprint^2) over the pieces",
        "cost = footprint_px^2 x placements x states",
        "(footprint_px)^2 x copies",
        "need += footprint_px(t, a, s) ** 2 * count",
        "each copy costs footprint^2 px",
        "the Profiler reads about twice the GPU size",
        "the Profiler's runtime size reads about double the storage size",
        "(https://wiki.polycount.com/wiki/Edge_padding)",
        "UV2 for every lightmapped piece",
        "mobile renders no realtime light",
        "warn above 0.65, error above 0.75",
    ]
    RIGHT = [
        "var t = (a: 1, b: 2); System.ValueTuple<int, int> v;",
        "Instead of `Tuple` (Unity's ExCSS.Unity also defines `System.Tuple`: CS0433) use `KeyValuePair`",
        "never `System.Tuple` in a snippet",
        "A renderer's chart box costs footprint_px^2 x b = (texels_per_m x Scale In Lightmap x LOD scale)^2 x A",
        "The atlas cost is not the footprint squared: Unity packs each renderer's chart box",
        "sum((texels_per_m x Scale In Lightmap x LOD scale)^2 x A x copies x lighting states)",
        "footprint_px = texels_per_m x sqrt(A / b) x Scale In Lightmap",
        "it can read up to twice the GPU size",
        "Directional mode (about twice the memory)",
        "(http://wiki.polycount.com/wiki/Edge_padding)",
    ]

    def test_wrong_statements_are_flagged(self):
        for text in self.WRONG:
            self.assertTrue(flagged(text), "not flagged: %s" % text)

    def test_correct_statements_pass(self):
        for text in self.RIGHT:
            self.assertEqual(flagged(text), [], "flagged: %s" % text)


class Tree(unittest.TestCase):
    """A throwaway skills tree; CC.ROOT points at it for one test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.keep = CC.ROOT
        CC.ROOT = str(self.tmp)
        CC.FAIL.clear()

    def tearDown(self):
        CC.ROOT = self.keep
        CC.FAIL.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


class ModuleConstant(Tree):
    def test_frozenset_and_set_calls_are_read_without_order(self):
        self.write("s/scripts/a.py", 'TOPOLOGY_TYPES = frozenset({"WELD", "ARRAY"})\nOTHER = set(["B", "A"])\n')
        self.assertEqual(CC.module_constant("s/scripts/a.py", "TOPOLOGY_TYPES"), frozenset({"ARRAY", "WELD"}))
        self.assertEqual(CC.module_constant("s/scripts/a.py", "OTHER"), frozenset({"A", "B"}))

    def test_lod_cost_is_the_scale_squared(self):
        self.assertAlmostEqual(CC.CANON["lod_lightmap_cost"], CC.CANON["lod_lightmap_scale"] ** 2)


QA_ROWS = """# QA

## Checks per task

| Stage | Task | Checks |
|---|---|---|
| 6 | `T-UV-<FAMILY>` | U1-U6 |
| 4 | `T-GREY-<FAMILY>` (a KIT file) | B1 |
| 4 | `T-GREY-MASTER` | B2-B7 |
| Any, after 4 | `T-RENAME-<PIECE>` | M9 (B2-B3 within it), N4-N5 after stage 10 |

## Stage 4

| Id | Check | How |
|---|---|---|
| B1 | x | x |
| U1 | x | x |
| M9 | x | x |
| N4 | x | x |
"""

BRIEFS = """# Briefs

**Stage 4, T-GREY-EXT (kit modeller).** Goal: boxes. Checks: B1. Fallback: none.

**Stage 4, T-GREY-MASTER (integrator).** Goal: MASTER laid out. Checks: B2-B7, with overlays.

**Stage 6, T-UV-EXT (UV artist).** Goal: UVs. Checks: U1-U6, the UV2 audit per mesh. Fallback: Smart UV.

**Any stage after 4, T-RENAME-EXT-DOOR-2X3-A (integrator).** Goal: renamed. Checks: B2-B3, M9 (ids kept), and N4-N5
after stage 10.
"""


class TaskChecks(Tree):
    def setUp(self):
        super().setUp()
        self.write(CC.QA_CHECKLISTS, QA_ROWS)

    def run_check(self, briefs):
        self.write(CC.TASK_BRIEFS, briefs)
        CC.check_task_checks()
        return list(CC.FAIL)

    def test_matching_briefs_pass(self):
        self.assertEqual(self.run_check(BRIEFS), [])

    def test_drifted_checks_fail(self):
        fails = self.run_check(BRIEFS.replace("Checks: B2-B3, M9 (ids kept), and N4-N5", "Checks: B2-B3, and N4-N5"))
        self.assertEqual(len(fails), 1, fails)
        self.assertIn("T-RENAME-EXT-DOOR-2X3-A", fails[0])

    def test_a_task_without_a_qa_row_fails(self):
        fails = self.run_check(BRIEFS.replace("T-UV-EXT", "T-PAINT-EXT"))
        self.assertTrue(any("T-PAINT-EXT has no row" in f for f in fails), fails)

    def test_a_brief_without_checks_fails(self):
        fails = self.run_check(BRIEFS.replace("Checks: B1. ", ""))
        self.assertTrue(any("T-GREY-EXT brief names no Checks" in f for f in fails), fails)

    def test_no_briefs_found_fails(self):
        self.assertTrue(self.run_check("# Briefs\n\nnothing here\n"))


if __name__ == "__main__":
    unittest.main()
