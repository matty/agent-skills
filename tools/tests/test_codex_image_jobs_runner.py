"""Tests for skills/codex-image-jobs/scripts/codex_image.py against a fake Codex: each case is a bug from a real run.

Host: plain Python 3.9+, standard library. Spends no Codex quota; builds a fake CODEX_HOME in a temp folder.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "codex-image-jobs" / "scripts" / "codex_image.py"
PNG = b"\x89PNG\r\n\x1a\n" + b"own" + b"IEND\xaeB`\x82"
DECOY = b"\x89PNG\r\n\x1a\n" + b"decoy" + b"IEND\xaeB`\x82"

FAKE = textwrap.dedent("""\
    import json, os, sys, time
    from pathlib import Path
    home = Path(os.environ["CODEX_HOME"])
    mode = os.environ["FAKE_MODE"]
    (home / "argv.json").write_text(json.dumps(sys.argv[1:]))
    if mode == "silent":
        time.sleep(60)
    (home / "stdin.txt").write_text(sys.stdin.read())  # blocks forever if the runner leaves stdin open
    print(json.dumps({"type": "thread.started", "thread_id": "own"}), flush=True)
    if mode == "noimage":
        print("boom", flush=True)
        sys.exit(1)
    if mode == "hang":
        time.sleep(60)
    # another session's image, written first and rewritten later, so it is the newest in the shared folder
    other = home / "generated_images" / "other"
    other.mkdir(parents=True)
    logs = home / "sessions" / "2026" / "11" / "04"
    logs.mkdir(parents=True)
    call = "imagegen({prompt:'x'})" if mode == "dropref" else "imagegen({num_last_images_to_include:1})"
    if mode != "nolog":
        (logs / "rollout-t-own.jsonl").write_text(json.dumps(
            {"payload": {"type": "custom_tool_call", "name": "exec", "input": "tools.image_gen__" + call}}) + "\\n")
    own = home / "generated_images" / "own"
    own.mkdir(parents=True)
    time.sleep(0.05)
    (other / "exec-2.png").write_bytes(bytes.fromhex(os.environ["FAKE_DECOY"]))
    time.sleep(0.05)
    (own / "exec-1.png").write_bytes(bytes.fromhex(os.environ["FAKE_PNG"]))
    time.sleep(0.05)
    (other / "exec-2.png").write_bytes(bytes.fromhex(os.environ["FAKE_DECOY"]))
    if mode == "retry":
        time.sleep(60)
""")


class Runner(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        fake_py = self.tmp / "fake_codex.py"
        fake_py.write_text(FAKE, encoding="utf-8")
        if os.name == "nt":
            self.bin = self.tmp / "codex.cmd"
            self.bin.write_text('@"%s" "%s" %%*\n' % (sys.executable, fake_py), encoding="utf-8")
        else:
            self.bin = self.tmp / "codex"
            self.bin.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, fake_py), encoding="utf-8")
            self.bin.chmod(self.bin.stat().st_mode | stat.S_IEXEC)
        self.out = self.tmp / "out" / "result.png"
        self.ref = self.tmp / "ref.jpg"
        self.ref.write_bytes(b"jpeg")

    def run_it(self, mode, *extra, timeout=30):
        env = dict(os.environ, CODEX_HOME=str(self.home), CODEX_BIN=str(self.bin), FAKE_MODE=mode,
                   FAKE_PNG=PNG.hex(), FAKE_DECOY=DECOY.hex())
        start = time.monotonic()
        done = subprocess.run([sys.executable, "-B", str(SCRIPT), "a prompt", str(self.out), "--poll", "0.05", *extra],
                              env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        return done, time.monotonic() - start

    def test_prompt_goes_on_stdin_and_stdin_is_closed(self):
        done, _ = self.run_it("ok")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("a prompt", (self.home / "stdin.txt").read_text())
        self.assertEqual(json.loads((self.home / "argv.json").read_text())[-2:], ["--", "-"])

    def test_takes_own_session_image_not_newest_in_shared_folder(self):
        done, _ = self.run_it("ok")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.out.read_bytes(), PNG)
        self.assertEqual(done.stdout.strip(), str(self.out.resolve()))

    def test_stops_codex_after_the_first_image(self):
        done, took = self.run_it("retry")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertLess(took, 25)

    def test_no_session_times_out_quickly(self):
        done, took = self.run_it("silent", "--start-timeout", "1")
        self.assertEqual(done.returncode, 124)
        self.assertLess(took, 25)

    def test_session_without_image_times_out(self):
        done, took = self.run_it("hang", "--timeout", "1")
        self.assertEqual(done.returncode, 124)
        self.assertLess(took, 25)

    def test_failed_run_reports_and_writes_nothing(self):
        done, _ = self.run_it("noimage")
        self.assertEqual(done.returncode, 2)
        self.assertIn("boom", done.stderr)
        self.assertFalse(self.out.exists())

    def test_failed_run_never_reports_a_stale_output_as_new(self):
        self.out.parent.mkdir()
        self.out.write_bytes(b"old")
        done, _ = self.run_it("noimage", "--force")
        self.assertEqual(done.returncode, 2)
        self.assertEqual(self.out.read_bytes(), b"old")

    def test_existing_output_needs_force(self):
        self.out.parent.mkdir()
        self.out.write_bytes(b"old")
        done, _ = self.run_it("ok")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.out.read_bytes(), b"old")

    def test_refuses_to_overwrite_its_reference(self):
        self.out.parent.mkdir()
        self.out.write_bytes(b"src")
        done, _ = self.run_it("ok", "--ref", str(self.out), "--force")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.out.read_bytes(), b"src")

    def test_instruction_names_the_reference_parameter(self):
        done, _ = self.run_it("ok", "--ref", str(self.ref))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("num_last_images_to_include:1", (self.home / "stdin.txt").read_text())
        self.assertEqual(self.out.read_bytes(), PNG)

    def test_dropped_reference_is_refused(self):
        done, _ = self.run_it("dropref", "--ref", str(self.ref))
        self.assertEqual(done.returncode, 3)
        self.assertFalse(self.out.exists())

    def test_missing_log_warns_but_saves(self):
        done, _ = self.run_it("nolog", "--ref", str(self.ref))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("check the reference", done.stderr)


if __name__ == "__main__":
    unittest.main()
