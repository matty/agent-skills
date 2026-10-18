"""Tests for tools/lint_skills.py: the frontmatter must parse as YAML the way Codex and the Agent Skills spec read it.

Host: plain Python 3.9+, standard library (PyYAML used when installed). Builds throwaway repos in a temp folder.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINT = ROOT / "tools" / "lint_skills.py"


def run_lint(skill_md, readme_row=True, files=()):
    """Lint a throwaway repo holding one skill: its SKILL.md, plus `files` (paths inside the skill)."""
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "tools").mkdir()
        shutil.copy(LINT, tmp / "tools" / "lint_skills.py")
        (tmp / "skills" / "demo-skill").mkdir(parents=True)
        (tmp / "skills" / "demo-skill" / "SKILL.md").write_bytes(skill_md.encode("utf-8"))
        for rel in files:
            (tmp / "skills" / "demo-skill" / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp / "skills" / "demo-skill" / rel).write_text("# %s\n" % rel, encoding="utf-8")
        (tmp / "README.md").write_text("| `demo-skill` | demo |\n" if readme_row else "", encoding="utf-8")
        p = subprocess.run([sys.executable, "-B", str(tmp / "tools" / "lint_skills.py")],
                           capture_output=True, text=True)
        return p.returncode, p.stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


GOOD = "---\nname: demo-skill\ndescription: Demo stage - a kit, piece; for export see other-skill.\n---\n\n# Demo\n"


class Frontmatter(unittest.TestCase):
    def test_valid_plain_description_passes(self):
        code, out = run_lint(GOOD)
        self.assertEqual(code, 0, out)

    def test_colon_space_in_a_plain_description_fails(self):
        # the 2026-10-17 regression: "stage: a kit" is not a valid plain YAML value
        code, out = run_lint(GOOD.replace("stage - a kit", "stage: a kit"))
        self.assertEqual(code, 1, out)
        self.assertIn("demo-skill/SKILL.md", out)

    def test_quoted_description_with_colon_passes(self):
        code, out = run_lint(GOOD.replace("description: Demo stage - a kit, piece; for export see other-skill.",
                                          'description: "Demo stage: a kit, piece."'))
        self.assertEqual(code, 0, out)

    def test_angle_brackets_fail(self):
        code, out = run_lint(GOOD.replace("a kit", "<FAMILY>_<Type>"))
        self.assertEqual(code, 1, out)

    def test_crlf_is_warned(self):
        code, out = run_lint(GOOD.replace("\n", "\r\n"))
        self.assertIn("CRLF", out)

    def test_missing_readme_row_fails(self):
        code, out = run_lint(GOOD, readme_row=False)
        self.assertEqual(code, 1, out)


class Links(unittest.TestCase):
    """Relative Markdown links must resolve, outside code, with the names the Linux CI sees (exact case, no Windows
    trimming of trailing dots), so a run on Windows agrees with the ubuntu job."""

    def test_link_like_text_in_inline_code_passes(self):
        # blender-kit-library's SKILL.md: `ns["new_piece"](...)` read as a link to "...", which only Windows resolves
        code, out = run_lint(GOOD + 'Then call `ns["new_piece"](...)` and so on.\n')
        self.assertEqual(code, 0, out)

    def test_link_like_text_in_a_fenced_block_passes(self):
        code, out = run_lint(GOOD + '```python\nns["place"](...)\nf = d["x"](arg)\n```\n')
        self.assertEqual(code, 0, out)

    def test_link_to_an_existing_file_passes(self):
        code, out = run_lint(GOOD + "Details: [guide](references/guide.md).\n", files=["references/guide.md"])
        self.assertEqual(code, 0, out)

    def test_broken_link_fails(self):
        code, out = run_lint(GOOD + "Details: [guide](references/missing.md).\n")
        self.assertEqual(code, 1, out)
        self.assertIn("links to references/missing.md", out)

    def test_link_to_dots_fails_on_every_os(self):
        # Windows trims "..." to the folder itself; ubuntu has no such file
        code, out = run_lint(GOOD + "See [this](...).\n")
        self.assertEqual(code, 1, out)
        self.assertIn("links to ...", out)

    def test_wrong_case_fails_on_every_os(self):
        code, out = run_lint(GOOD + "Details: [guide](references/Guide.md).\n", files=["references/guide.md"])
        self.assertEqual(code, 1, out)
        self.assertIn("links to references/Guide.md", out)

    def test_local_reference_with_wrong_case_fails(self):
        code, out = run_lint(GOOD + "Run `scripts/Tool.py`.\n", files=["scripts/tool.py"])
        self.assertEqual(code, 1, out)
        self.assertIn("names scripts/Tool.py", out)


if __name__ == "__main__":
    unittest.main()
