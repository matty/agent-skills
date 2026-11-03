"""Plain-Python tests for the pbr-texturing skill's scripts/toolbag_bake.py without Marmoset Toolbag: the job it
builds (map names, metres, FBX only, textures), the command it launches, how run_job() reads a result, a failed job
and a timeout (with a fake launcher standing in for toolbag.exe), and where it looks for Toolbag.

Host: plain Python 3.9+, standard library. Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_pbr_texturing_toolbag.py"
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "pbr-texturing" / "scripts"


def load(name):
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True            # never leave a __pycache__ in the skill
    try:
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        return __import__(name)
    finally:
        sys.dont_write_bytecode = keep


tb = load("toolbag_bake")


def fake_toolbag(result=None, write_maps=True, never=False):
    """A launcher that does what toolbag_job.py would: read the job, write the maps and the result file."""
    calls = []

    def launch(cmd):
        calls.append(cmd)
        if never:
            return
        job_path, res_path = cmd[-2], cmd[-1]
        with open(job_path, encoding="utf-8") as f:
            job = json.load(f)
        res = {"ok": True, "version": 5033, "maps": {}, "warnings": [], "error": None, "seconds": 0.2}
        if not job.get("probe") and write_maps:
            for m, p in tb.expected_paths(job).items():
                open(p, "wb").close()
                res["maps"][m] = p
        res.update(result or {})
        with open(res_path, "w", encoding="utf-8") as f:
            json.dump(res, f)
    launch.calls = calls
    return launch


class Job(unittest.TestCase):
    def test_build(self):
        job = tb.build_job("low.fbx", "high.fbx", "out", "T_X", maps=("normal", "curvature", "basecolor"),
                           size="2048x1024", cage_out=0.08, textures={"*": {"basecolor": "a.png"}})
        self.assertEqual(job["toolbag_maps"], {"normal": "normal", "curvature": "curve", "basecolor": "albedo"})
        self.assertEqual(job["suffixes"]["basecolor"], "BaseColor")
        self.assertEqual((job["width"], job["height"]), (2048, 1024))
        self.assertEqual(job["cage_in"], 0.08)                      # defaults to the outward push
        self.assertTrue(os.path.isabs(job["highs"][0]))
        self.assertTrue(os.path.isabs(job["textures"]["*"]["basecolor"]))

    def test_cage_required(self):
        with self.assertRaises(ValueError) as cm:
            tb.build_job("low.fbx", ["high.fbx"], "out", "T_X")
        self.assertIn("automatic cage", str(cm.exception))

    def test_glb_refused(self):
        with self.assertRaises(ValueError) as cm:
            tb.build_job("low.fbx", ["high.glb"], "out", "T_X", cage_out=0.05)
        self.assertIn(".glb is not read", str(cm.exception))

    def test_unknown_map_and_texture(self):
        with self.assertRaises(ValueError):
            tb.build_job("l.fbx", ["h.fbx"], "o", "T", maps=("bentnormal",), cage_out=0.1)
        with self.assertRaises(ValueError):
            tb.build_job("l.fbx", ["h.fbx"], "o", "T", cage_out=0.1, textures={"M": {"normal": "n.png"}})

    def test_expected_paths(self):
        job = tb.build_job("l.fbx", ["h.fbx"], "out", "T_X", maps=("ao",), cage_out=0.1)
        self.assertEqual(os.path.basename(tb.expected_paths(job)["ao"]), "T_X_AO.png")


class Run(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.job = tb.build_job("l.fbx", ["h.fbx"], self.out, "T_X", maps=("normal", "ao"), cage_out=0.1)

    def test_success(self):
        launch = fake_toolbag()
        res = tb.run_job(self.job, exe="toolbag.exe", launcher=launch, timeout=5, poll=0.01)
        self.assertTrue(res["ok"])
        self.assertEqual(set(res["maps"]), {"normal", "ao"})
        self.assertIn("wall_seconds", res)
        cmd = launch.calls[0]
        self.assertEqual(cmd[:3], ["toolbag.exe", "-hide", tb.JOB_SCRIPT])
        self.assertEqual(len(cmd), 5)

    def test_job_error_raises_with_detail(self):
        launch = fake_toolbag({"ok": False, "error": "Traceback: no Low group"}, write_maps=False)
        with self.assertRaises(RuntimeError) as cm:
            tb.run_job(self.job, exe="toolbag.exe", launcher=launch, timeout=5, poll=0.01)
        self.assertIn("no Low group", str(cm.exception))

    def test_timeout(self):
        with self.assertRaises(TimeoutError):
            tb.run_job(self.job, exe="toolbag.exe", launcher=fake_toolbag(never=True), timeout=0.2, poll=0.02)

    def test_probe(self):
        self.assertEqual(tb.probe("toolbag.exe", launcher=fake_toolbag(), timeout=5), 5033)

    def test_bake_report(self):
        keep = tb.run_job
        try:
            tb.run_job = lambda job, **k: keep(job, launcher=fake_toolbag(), timeout=5, poll=0.01, exe="tb")
            res = tb.bake("l.fbx", ["h.fbx"], self.out, "T_Y", maps=("normal",), cage_out=0.05)
        finally:
            tb.run_job = keep
        self.assertEqual(res["report"]["baker"], "toolbag")
        self.assertTrue(res["normal"].endswith("T_Y_Normal.png"))


class Find(unittest.TestCase):
    def test_env_first(self):
        d = tempfile.mkdtemp()
        exe = os.path.join(d, "toolbag.exe")
        open(exe, "wb").close()
        self.assertEqual(tb.find_toolbag(paths=(), env={"TOOLBAG_EXE": exe}), exe)

    def test_default_paths(self):
        d = tempfile.mkdtemp()
        exe = os.path.join(d, "toolbag.exe")
        open(exe, "wb").close()
        if tb.shutil.which("toolbag") is None:
            self.assertEqual(tb.find_toolbag(paths=(os.path.join(d, "missing.exe"), exe), env={}), exe)
            self.assertIsNone(tb.find_toolbag(paths=(), env={}))


if __name__ == "__main__":
    unittest.main()
