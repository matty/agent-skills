"""Plain-Python tests for the image-to-pbr skill's scripts/setup_deepbump.py without the network: the install folder,
the pinned-hash check (with CRLF and LF copies of a .py file hashing alike) and --check on a missing install.

Host: plain Python 3.9+, standard library. Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_image_to_pbr_*.py"
"""

import contextlib
import hashlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "image-to-pbr" / "scripts" / "setup_deepbump.py"


def load():
    spec = importlib.util.spec_from_file_location("setup_deepbump", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SetupDeepBumpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def test_root_from_environment(self):
        old = os.environ.get("IMAGE_TO_PBR_DEEPBUMP")
        try:
            os.environ["IMAGE_TO_PBR_DEEPBUMP"] = "X:/somewhere"
            self.assertEqual(self.m.default_root(), "X:/somewhere")
        finally:
            if old is None:
                os.environ.pop("IMAGE_TO_PBR_DEEPBUMP", None)
            else:
                os.environ["IMAGE_TO_PBR_DEEPBUMP"] = old

    def test_py_hash_ignores_line_endings(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a.py"), os.path.join(d, "b.py")
            Path(a).write_bytes(b"x = 1\r\ny = 2\r\n")
            Path(b).write_bytes(b"x = 1\ny = 2\n")
            self.assertEqual(self.m.file_hash(a), self.m.file_hash(b))
            self.assertEqual(self.m.file_hash(b), hashlib.sha256(b"x = 1\ny = 2\n").hexdigest())

    def test_verify_reports_missing_and_changed(self):
        with tempfile.TemporaryDirectory() as d:
            bad = self.m.verify(d)
            self.assertEqual(len(bad), len(self.m.PINNED))
            Path(d, "utils_inference.py").write_text("tampered\n")
            self.assertTrue(any("utils_inference.py has SHA-256" in b for b in self.m.verify(d)))

    def test_check_on_missing_install(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(self.m.main(["--check", "--root", d]), 1)
        self.assertIn("unavailable", out.getvalue())


if __name__ == "__main__":
    unittest.main()
