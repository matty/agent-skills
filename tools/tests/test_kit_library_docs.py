"""blender-kit-library: SKILL.md and its references document what scripts/kit_library.py does, and the two shipped
copies are identical.

Host: plain Python 3.9+, standard library (reads the script with ast; bpy is not needed). Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_kit_library_docs.py"
"""

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "blender-kit-library"
SCRIPT = SKILL / "scripts" / "kit_library.py"
COPY = ROOT / "skills" / "vrchat-world-orchestration" / "scripts" / "kit_library.py"


def functions(tree):
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}


class KitLibraryDocs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = SCRIPT.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.src)
        cls.doc = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        cls.docs = cls.doc + "".join(p.read_text(encoding="utf-8") for p in sorted((SKILL / "references").glob("*.md")))

    def test_copies_are_identical(self):
        self.assertEqual(SCRIPT.read_bytes(), COPY.read_bytes(),
                         "copy skills/blender-kit-library/scripts/kit_library.py over the orchestration copy")

    def test_every_public_function_is_in_the_skill(self):
        missing = [name for name in functions(self.tree) if "%s(" % name not in self.docs]
        self.assertEqual(missing, [], "SKILL.md and its references do not document these kit_library functions")

    def test_every_function_the_skill_calls_exists(self):
        named = set(re.findall(r"`(\w+)\(", self.docs)) - {"open", "exec"}
        known = set(functions(self.tree)) | {"Library.reload", "reload"}
        unknown = sorted(n for n in named if n not in known and n.islower() and "_" in n)
        self.assertEqual(unknown, [], "SKILL.md calls functions kit_library.py does not have")

    def test_cli_flags_are_documented(self):
        flags = set(re.findall(r'"(--[a-z-]+)"', self.src.split("def _main")[1]))
        flags |= set(re.findall(r'"(--[a-z-]+)"', self.src.split("def _work_cli")[1].split("def _main")[0]))
        self.assertEqual(flags, {"--audit", "--module", "--json", "--relink", "--files", "--renamed", "--snapshot",
                                 "--changes", "--checkout", "--integrate", "--names", "--materials", "--force"})
        for flag in flags - {"--force"}:                       # --force is for the user to choose, not advertised
            self.assertIn(flag, self.docs)

    def test_material_pattern_is_canonical_and_documented(self):
        value = next(n.value for n in self.tree.body
                     if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "MAT_RE")
        self.assertEqual(ast.literal_eval(value.args[0]), r"^M_[A-Z]{2,5}_[A-Za-z0-9][A-Za-z0-9_]*$")
        self.assertIn(r"`^M_[A-Z]{2,5}_[A-Za-z0-9][A-Za-z0-9_]*$`", self.doc)
        pattern = re.compile(ast.literal_eval(value.args[0]))
        self.assertTrue(pattern.match("M_EXT_Brick") and pattern.match("M_TRIM_Sheet_01"))
        self.assertFalse(pattern.match("M_EXT_Brick.001") or pattern.match("M_ext_Brick") or pattern.match("Brick"))

    def test_size_token_skips_axes_under_one_module(self):
        self.assertIn("e > 1.0 - GRID_TOL", self.src)
        self.assertIn("any axis under one module is thickness", self.doc)
        self.assertNotIn("half a module", self.doc)

    def test_every_headless_command_returns_script_errors(self):
        for text, name in ((self.docs, "SKILL.md and references"), (self.src, "kit_library.py")):
            for line in text.splitlines():
                if "blender -b --" in line:                                  # a command, not a mention
                    self.assertIn("--python-exit-code 1", line, "%s: %s" % (name, line.strip()))

    def test_audit_needs_a_module(self):
        fn = functions(self.tree)["audit_kit"]
        self.assertEqual(fn.args.args[0].arg, "module")
        self.assertEqual(len(fn.args.defaults), len(fn.args.args) - 1, "audit_kit's module must have no default")

    def test_kit_status_values_match(self):
        order = next(ast.literal_eval(n.value) for n in self.tree.body
                     if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "STATUS_ORDER")
        self.assertEqual(order, ("grey", "modelled", "uv", "textured", "exported"))
        self.assertRegex(self.doc, r"`kit_status`.*" + r".*".join("`%s`" % s for s in order))

    def test_one_assembly_per_asm_file(self):
        self.assertIn("blender/asm/ASM_<Name>_<Variant>.blend", self.doc)

    def test_single_master_is_the_default(self):
        self.assertIn("`single` (**default**)", self.doc)
        self.assertIn("Never pick `split` on your own", self.doc)
        layout = next(ast.literal_eval(n.value) for n in self.tree.body
                      if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "LAYOUT_PROP")
        self.assertIn("`%s`" % layout, self.doc)

    def test_save_without_backups(self):
        self.assertIn("save_version = 0", self.src)
        self.assertIn("save_file()", self.doc)


if __name__ == "__main__":
    unittest.main()
