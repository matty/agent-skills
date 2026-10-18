"""Fuzz-style test for skills/vrchat-world-orchestration/scripts/spec_validate.py and spec_to_svg.py: every value
of a spec, set to a value of the wrong type, must come back as findings, drawings and problem lines, never as an
exception (the round-4 review found tracebacks on plausible slips such as `min_footprint_px: "64"`).

Host: plain Python 3.9+, stdlib unittest.
Run from the repo root:  python -B -m unittest discover -s tools/tests -p "test_orchestration_*.py"
"""

import copy
import importlib.util
import sys
import tempfile
import unittest

from test_orchestration_spec_validate import SKILL, SV, study_spec

WRONG = (None, "2", 2.5, [], {}, True, -1, 0)


def load_svg():
    sys.dont_write_bytecode = True                     # never leave __pycache__ in the skill folder
    spec = importlib.util.spec_from_file_location("orchestration_spec_to_svg", SKILL / "scripts" / "spec_to_svg.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SVG = load_svg()


def fuzz_spec():
    """The study spec plus what it lacks: an assembly, a mirror, lighting states and a second zone with a room."""
    spec = study_spec()
    spec["assemblies"] = [{"name": "ASM_WallRun_A", "file": "blender/asm/ASM_WallRun_A.blend", "size": [4, 0.2, 3],
                           "uses": {"INT_Wall_2x3_A": 2}}]
    spec["zones"][0]["lighting_states"] = 2
    spec["budgets"]["lightmap"]["count"] = 2                     # two states double the fill
    spec["zones"][0]["mirrors"] = [{"id": "m1", "pos": [3, 4.8, 1.6], "rot": 0, "size": [1.2, 2.0]}]
    spec["zones"].append({"id": "hall", "name": "Hall", "kind": "interior", "bounds": [0, -5, 6, 1], "floor_z": 0,
                          "placements": [{"ref": "ASM_WallRun_A", "pos": [1, -4, 0], "rot": 0}],
                          "rooms": [{"id": "hall", "name": "Hall", "bounds": [1, -4, 5, 1], "height": 3,
                                     "openings": [{"type": "window", "at": [3.4, 1], "width": 1.2, "height": 1.0,
                                                   "sill": 1.0}]}]})
    return spec


def paths(node, prefix=()):
    """Every key path in node, through the first two entries of each list."""
    yield prefix
    if isinstance(node, dict):
        for key, value in node.items():
            yield from paths(value, prefix + (key,))
    elif isinstance(node, list):
        for i, value in enumerate(node[:2]):
            yield from paths(value, prefix + (i,))


class WrongTypes(unittest.TestCase):
    def test_every_value_of_the_wrong_type_is_reported_not_raised(self):
        base = fuzz_spec()
        f = SV.Findings()
        SV.check_spec(base, f)
        self.assertEqual((f.errors, f.warnings), (0, 0), f.items)        # clean, so the mutations make the errors
        failures, count = [], 0
        with tempfile.TemporaryDirectory() as out:
            for path in paths(base):
                if not path:
                    continue
                for value in WRONG:
                    spec = copy.deepcopy(base)
                    node = spec
                    for key in path[:-1]:
                        node = node[key]
                    node[path[-1]] = value
                    count += 1
                    try:
                        f = SV.Findings()
                        SV.footprint_report(SV.check_spec(spec, f))
                        SVG.render(spec, out)
                    except Exception as exc:  # noqa: BLE001 - catching everything is the point of this test
                        failures.append("%s = %r: %s: %s" % (".".join(map(str, path)), value, type(exc).__name__,
                                                             exc))
        self.assertGreater(count, 1000)
        self.assertEqual(failures, [], "\n".join(failures[:20]))


if __name__ == "__main__":
    unittest.main()
