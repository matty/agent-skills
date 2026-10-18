"""blender-unity-placement-sync: the skill's docs and its scripts name the same flags, calls and exit codes.

Host: plain Python 3.9+, standard library. Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_placement_docs.py"
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "blender-unity-placement-sync"
SCRIPTS = SKILL / "scripts"


class PlacementDocs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        cls.docs = cls.skill + "".join(p.read_text(encoding="utf-8") for p in sorted((SKILL / "references").glob("*.md")))
        cls.merge = (SCRIPTS / "placement_merge.py").read_text(encoding="utf-8")
        cls.export = (SCRIPTS / "export_placements.py").read_text(encoding="utf-8")
        cls.cs = (SCRIPTS / "unity" / "Editor" / "PlacementSync.cs").read_text(encoding="utf-8")

    def test_every_command_line_flag_is_documented(self):
        for name, src in (("placement_merge.py", self.merge), ("export_placements.py", self.export)):
            for flag in re.findall(r'add_argument\("(--[a-z-]+)"', src):
                self.assertTrue(flag in self.docs, "%s %s is not in SKILL.md or references/" % (name, flag))

    def test_every_documented_flag_exists(self):
        flags = set(re.findall(r'add_argument\("(--[a-z-]+)"', self.merge + self.export))
        flags |= {"--factory-startup", "--python-exit-code", "--python"}       # Blender's own
        named = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", self.skill))
        self.assertEqual(sorted(named - flags), [], "SKILL.md names flags no script has")

    def test_every_unity_call_is_documented(self):
        calls = re.findall(r"public static string (\w+)\(", self.cs)
        self.assertEqual(sorted(calls), ["Apply", "Check", "Dump"])
        for call in calls:
            self.assertIn("PlacementSyncTool.%s(" % call, self.docs)

    def test_merge_exit_codes_are_documented(self):
        table = (SKILL / "references" / "merge-rules.md").read_text(encoding="utf-8")
        for code in ("0", "1", "2", "3", "4"):
            self.assertRegex(table, r"\| merge \| %s \|" % code)
        for code in ("0", "2", "3"):
            self.assertIn("merge exit %s" % code if code != "0" else "exit code", self.skill)
        self.assertRegex(self.merge, r"return 2 if unresolved else \(3 if blocked else 0\)")

    def test_headless_commands_propagate_script_errors(self):
        self.assertIn("--python-exit-code 1", self.skill)

    def test_axis_conversion_and_export_settings_are_stated(self):
        self.assertIn("(-x, z, -y)", self.skill)
        for text in ("-Z Forward", "Y Up", "FBX All", "Use Space Transform on", "Path Mode Strip"):
            self.assertIn(text, self.skill)


if __name__ == "__main__":
    unittest.main()
