"""Plain-Python tests that blender-to-unity's export settings agree with themselves: every keyword
scripts/batch_export_fbx.py passes to the FBX exporter (FBX_SETTINGS, the kit and default path modes) is documented
with the same value in references/fbx-export.md, the doc gives no other value for it, and SKILL.md states the
canonical axis and path-mode rules.

Host: plain Python 3.9+, standard library (the script is parsed, not run). Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_export_*.py"
"""

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "blender-to-unity"
SCRIPT = SKILL / "scripts" / "batch_export_fbx.py"
DOC = SKILL / "references" / "fbx-export.md"


def script_settings():
    """FBX_SETTINGS plus the module-level constants, as Python values."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    consts, settings = {}, None
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name == "FBX_SETTINGS":
                call = node.value
                assert isinstance(call, ast.Call) and getattr(call.func, "id", "") == "dict"
                settings = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}
            else:
                try:
                    consts[name] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    return settings, consts


def documented():
    """{keyword: [values]} from every code span of the form keyword=literal in fbx-export.md."""
    out = {}
    for span in re.findall(r"`([^`]+)`", DOC.read_text(encoding="utf-8")):
        m = re.fullmatch(r"(\w+)=(.+)", span.strip())
        if not m:
            continue
        try:
            value = ast.literal_eval(m.group(2))
        except (ValueError, SyntaxError):
            continue
        out.setdefault(m.group(1), []).append(value)
    return out


class ExportSettingsAgree(unittest.TestCase):
    def setUp(self):
        self.settings, self.consts = script_settings()
        self.doc = documented()

    def test_every_script_setting_is_documented_with_its_value(self):
        self.assertIsNotNone(self.settings)
        for key, value in self.settings.items():
            self.assertIn(key, self.doc, "fbx-export.md has no row for %s" % key)
            self.assertEqual(set(map(repr, self.doc[key])), {repr(value)},
                             "%s: script %r, doc %r" % (key, value, self.doc[key]))

    def test_path_modes(self):
        self.assertEqual(self.consts["KIT_PATH_MODE"], "STRIP")
        self.assertIn("STRIP", self.doc.get("path_mode", []))
        self.assertIn(self.consts["PATH_MODE"], self.doc.get("path_mode", []))

    def test_canonical_fbx_values(self):
        canon = dict(axis_forward="-Z", axis_up="Y", apply_scale_options="FBX_SCALE_ALL", use_space_transform=True,
                     bake_space_transform=True, use_tspace=False, colors_type="NONE", use_triangles=True,
                     object_types={"MESH"})
        for key, value in canon.items():
            self.assertEqual(self.settings.get(key), value, key)

    def test_skill_states_the_axis_mapping_and_strip(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("(-x, z, -y)", text)
        self.assertIn("Bake Space Transform on", text)
        self.assertRegex(text, r"Path Mode \| Strip")


BLENDER_CMD = re.compile(r"""\bblender(?:\.exe)?["']?\s+(?:-b|--background)\b""")


def headless_commands():
    """Yield (file:line, command) for every documented headless Blender run in both skills, a command continued on
    indented lines or after a trailing backslash, ^ or ` joined into one."""
    for skill in ("blender-to-unity", "blender-mesh-topology"):
        for path in sorted((ROOT / "skills" / skill).rglob("*")):
            if path.suffix not in (".md", ".py") or "__pycache__" in path.parts:
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines):
                if not BLENDER_CMD.search(line):
                    continue
                cmd, indent, j = line, len(line) - len(line.lstrip()), i + 1
                while j < len(lines) and lines[j].strip() and (
                        len(lines[j]) - len(lines[j].lstrip()) > indent
                        or lines[j - 1].rstrip().endswith(("\\", "^", "`"))):
                    cmd += " " + lines[j].strip()
                    j += 1
                if re.search(r"--python(?:-expr)?\s", cmd):
                    yield "%s:%d" % (path.relative_to(ROOT), i + 1), cmd


class HeadlessCommands(unittest.TestCase):
    def test_every_documented_headless_command_fails_loudly_and_runs_clean(self):
        """Without --python-exit-code 1 a script that raises exits 0; without --factory-startup the user's add-ons and
        preferences load into the run, so it is not the run the skill measured."""
        found = list(headless_commands())
        self.assertGreaterEqual(len(found), 4, "the commands were not found: %s" % found)
        missing = ["%s: %s" % (where, flag) for where, cmd in found
                   for flag in ("--python-exit-code 1", "--factory-startup") if flag not in cmd]
        self.assertEqual(missing, [])


class SharedHelpers(unittest.TestCase):
    def test_mesh_audit_evaluates_like_the_export(self):
        """mesh_audit.py keeps its own copy of the export's _evaluated(): the copies must not drift apart."""
        def functions(path):
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src)
            return {n.name: ast.get_source_segment(src, n) for n in tree.body if isinstance(n, ast.FunctionDef)}
        export = functions(SCRIPT)
        audit = functions(SKILL / "scripts" / "mesh_audit.py")
        for name in ("_layer_paths", "_evaluated"):
            self.assertEqual(export[name], audit[name], name)


if __name__ == "__main__":
    unittest.main()
