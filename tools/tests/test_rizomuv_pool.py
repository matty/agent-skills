"""Plain-Python tests for the rizomuv-uv-pipeline skill's scripts/rizom_pool.py supervision, with fake workers that
speak the pool's protocol but never start RizomUV: results streamed per mesh, a worker that cannot start, a
worker that hangs or crashes, timeout None and 0, an empty batch, and children killed when the host goes away.

Host: plain Python 3.9+, standard library. Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_rizomuv_*.py"
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "rizomuv-uv-pipeline" / "scripts"


def load(name):
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True            # never leave a __pycache__ in the skill
    try:
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        return __import__(name)
    finally:
        sys.dont_write_bytecode = keep


rp = load("rizom_pool")

# A worker that follows rizom_pool's protocol. Its behaviour is the argv item before the job file:
#   ok | slow | hang:<index> | crash:<index> | nostart:<n> (the first n workers to start fail to start)
FAKE_WORKER = textwrap.dedent(r'''
    import json, os, sys, time
    kind, job = sys.argv[1], json.load(open(sys.argv[2], encoding="utf-8"))
    out = sys.stdout
    def emit(o):
        out.write(json.dumps(o) + "\n"); out.flush()
    if kind.startswith("nostart:"):
        for slot in range(int(kind.split(":")[1])):
            try:
                os.close(os.open(os.path.join(job["dir"], "fail_%d" % slot), os.O_CREAT | os.O_EXCL))
                emit({"event": "start_failed", "error": "no licence token (fake)"})
                sys.exit(3)
            except FileExistsError:
                pass
    emit({"event": "ready", "port": 61000 + os.getpid() % 1000, "pid": os.getpid(), "rizomuv": "fake"})
    while True:
        line = sys.stdin.readline().strip()
        if not line or line == "quit":
            break
        i = int(line)
        if kind == "hang:%d" % i:
            time.sleep(3600)
        if kind == "crash:%d" % i:
            os._exit(5)
        if kind == "slow":
            time.sleep(0.2)
        item = json.load(open(os.path.join(job["dir"], "mesh_%d.json" % i), encoding="utf-8"))
        emit({"event": "result", "index": i, "result": {"corners": len(item["mesh"]["uvw_ids"]),
              "kind": item["kind"], "packs": item["packs"], "timeout": job["timeout"],
              "worker": {"port": 0, "pid": os.getpid(), "rizomuv": "fake"}}})
''')


class Pool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.keep = tempfile.tempdir
        tempfile.tempdir = self.tmp.name                    # pool folders go here, not in the user's temp
        self.fake = os.path.join(self.tmp.name, "fake_worker.py")
        with open(self.fake, "w", encoding="utf-8") as fh:
            fh.write(FAKE_WORKER)
        self.meshes = {"m%d" % i: rp._box(i % 3 + 1) for i in range(7)}

    def tearDown(self):
        tempfile.tempdir = self.keep
        self.tmp.cleanup()

    def run_pool(self, behaviour="ok", **kw):
        stats = {}
        kw.setdefault("workers", 3)
        res = rp.unwrap_many(self.meshes, worker_cmd=[sys.executable, "-B", self.fake, behaviour], stats=stats, **kw)
        return res, stats

    def assert_all_good(self, res, but=()):
        for n, m in self.meshes.items():
            if n in but:
                continue
            self.assertNotIn("error", res[n], n)
            self.assertEqual(res[n]["corners"], len(m["uvw_ids"]), n)       # its own mesh came back

    def test_results_stream_back_per_mesh(self):
        seen = []
        res, stats = self.run_pool(on_result=lambda n, r: seen.append(n), start_together=True)
        self.assert_all_good(res)
        self.assertEqual(sorted(seen), sorted(self.meshes))
        self.assertEqual(len(stats["workers"]), 3)
        self.assertEqual(sum(w["meshes"] for w in stats["workers"].values()), 7)
        self.assertTrue(all("index" in r["worker"] for r in res.values()))
        self.assertEqual(os.listdir(self.tmp.name), ["fake_worker.py"])      # the pool folder is removed

    def test_timeout_none_and_zero_mean_no_limit(self):
        for t in (None, 0):
            res, _ = self.run_pool(timeout=t)
            self.assert_all_good(res)
            self.assertTrue(all(r["timeout"] is None for r in res.values()))

    def test_empty_batch_starts_nothing(self):
        stats = {}
        self.assertEqual(rp.unwrap_many({}, worker_cmd=[sys.executable, "-B", self.fake], stats=stats), {})
        self.assertEqual(stats["workers"], {})

    def test_a_worker_that_cannot_start_leaves_its_share_to_the_others(self):
        res, stats = self.run_pool("nostart:1", start_together=True)
        self.assert_all_good(res)
        self.assertEqual(len(stats["start_errors"]), 1)
        self.assertEqual(len(stats["workers"]), 2)

    def test_no_worker_starting_reports_every_mesh(self):
        res, stats = self.run_pool("nostart:9")
        self.assertTrue(all("no RizomUV worker could take this mesh" in r["error"] for r in res.values()))
        self.assertIn("no licence token", res["m0"]["error"])

    def test_a_hung_worker_is_killed_and_costs_only_its_mesh(self):
        res, stats = self.run_pool("hang:2", timeout=0.5, stall_slack=0.5)
        self.assertIn("timed out", res["m2"]["error"])
        self.assert_all_good(res, but=("m2",))

    def test_a_crashed_worker_costs_only_its_mesh_and_is_replaced(self):
        res, stats = self.run_pool("crash:1", workers=1)
        self.assertIn("exited (code 5) while unwrapping", res["m1"]["error"])
        self.assert_all_good(res, but=("m1",))
        self.assertEqual(len(stats["workers"]), 2)                           # the replacement

    def test_per_mesh_packs(self):
        res, _ = self.run_pool(packs=lambda name, mesh: {
            "uv0": rp.ru.pack_spec(1024), "uv2": rp.ru.lightmap_spec(mesh, 20, users={name: (1.0, 1.0)})})
        self.assert_all_good(res)
        for n in self.meshes:
            self.assertEqual(list(res[n]["packs"]["uv2"]["users"]), [n])          # each mesh got its own spec
        res, _ = self.run_pool(packs={"uv0": rp.ru.pack_spec(512)})
        self.assertTrue(all(r["packs"]["uv0"]["map_px"] == 512 for r in res.values()))

    def test_a_bad_gate_or_kind_fails_before_any_worker_starts(self):
        with self.assertRaises(TypeError):
            rp.unwrap_many(self.meshes, worker_cmd=[sys.executable, "-B", self.fake, "ok"], gate=1.3)
        with self.assertRaises(ValueError):
            rp.unwrap_many(self.meshes, kind="organik", worker_cmd=[sys.executable, "-B", self.fake, "ok"])
        self.assertEqual(os.listdir(self.tmp.name), ["fake_worker.py"])

    def test_per_mesh_kind(self):
        res, _ = self.run_pool(kind=lambda name, mesh: "Organic" if name in ("m1", "m4") else "hard")
        self.assert_all_good(res)
        self.assertEqual({n: r["kind"] for n, r in res.items()},
                         {n: "organic" if n in ("m1", "m4") else "hard" for n in self.meshes})


class Commands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def sleeper(self, seconds):
        return [sys.executable, "-c", "import os, sys, time; open(os.path.join(sys.argv[1], str(os.getpid())), 'w')"
                ".close(); time.sleep(%s)" % seconds, self.tmp.name]

    def pids(self, n, wait=20):
        t0 = time.time()
        while time.time() - t0 < wait:
            got = [int(f) for f in os.listdir(self.tmp.name) if f.isdigit()]
            if len(got) >= n:
                return got
            time.sleep(0.05)
        self.fail("children did not start")

    @staticmethod
    def alive(pid):
        if os.name == "nt":
            import ctypes
            k32 = ctypes.WinDLL("kernel32")
            h = k32.OpenProcess(0x1000, False, pid)
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
            k32.CloseHandle(h)
            return bool(ok) and code.value == 259
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def test_timeout_none_zero_and_a_real_limit(self):
        for t in (None, 0):
            r = rp.run_commands([[sys.executable, "-c", "print('hi')"]], timeout=t)
            self.assertEqual((r[0]["exit"], r[0]["ok"]), (0, True))
        r = rp.run_commands([self.sleeper(30)], timeout=0.5)
        self.assertEqual((r[0]["exit"], r[0]["ok"]), ("TIMEOUT", False))

    def test_failures_are_reported(self):
        cmds = [[sys.executable, "-c", "print('fine')"],
                [sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"]]
        r = rp.run_commands(cmds)
        self.assertEqual([x["ok"] for x in r], [True, False])
        with self.assertRaises(RuntimeError) as cm:
            rp.run_commands(cmds, check=True)
        self.assertIn("1 of 2 command(s) failed", str(cm.exception))
        self.assertIn("exited 3", str(cm.exception))
        self.assertIn("boom", str(cm.exception))

    def test_children_are_killed_when_the_caller_raises(self):
        def tick(running, done):
            if len([f for f in os.listdir(self.tmp.name) if f.isdigit()]) >= 2:
                raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            rp.run_commands([self.sleeper(60), self.sleeper(60)], workers=2, on_tick=tick)
        time.sleep(0.5)
        self.assertEqual([p for p in self.pids(2) if self.alive(p)], [])

    @unittest.skipUnless(os.name == "nt", "the Job Object tie is Windows; elsewhere a watchdog polls every second")
    def test_children_die_with_a_killed_host(self):
        host = subprocess.Popen([sys.executable, "-B", "-c",
                                 "import sys; sys.path.insert(0, %r); import rizom_pool as rp; "
                                 "rp.run_commands([%r, %r], workers=2)" % (str(SCRIPTS), self.sleeper(60),
                                                                          self.sleeper(60))],
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        try:
            pids = self.pids(2)
            host.kill()
            host.wait()
            t0 = time.time()
            while any(self.alive(p) for p in pids) and time.time() - t0 < 5:
                time.sleep(0.1)
            self.assertEqual([p for p in pids if self.alive(p)], [])
        finally:
            if host.poll() is None:
                host.kill()


if __name__ == "__main__":
    unittest.main()
