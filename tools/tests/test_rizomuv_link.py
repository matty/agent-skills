"""Plain-Python tests for the rizomuv-uv-pipeline skill's scripts/rizom_link.py without RizomUV: the version check
that refuses builds too old for headless mode, the short temp folder libzmq needs, port claiming, and what
RizomSession.start() says when the instance exits early or never listens (with a fake process and a fake link),
the deadline that kills an instance from a separate process even while a call holds the GIL, and the file lock
that keeps two Blender jobs off one .blend.

Host: plain Python 3.9+, standard library. Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_rizomuv_*.py"
"""

import os
import socket
import sys
import tempfile
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


rl = load("rizom_link")


class Versions(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(rl.parse_version("2027.0.598.g864535413"), (2027, 0, 598))
        self.assertEqual(rl.parse_version("RizomUV VS RS 2027.0"), (2027, 0))
        self.assertIsNone(rl.parse_version(""))

    def test_headless_needs_2027_0_417(self):
        self.assertEqual(rl.MIN_HEADLESS, (2027, 0, 417))
        for ok in ((2027, 0, 417), (2027, 0, 598), (2027, 1), (2027, 0), (2028, 0, 1), None):
            rl.check_headless_version(ok)                       # unknown build of 2027.0 is allowed to try
        for old in ((2025, 1), (2024, 1, 50), (2027, 0, 416)):
            with self.assertRaises(RuntimeError) as cm:
                rl.check_headless_version(old, "C:/RizomUV/rizomuv.exe")
            self.assertIn("cannot run headless", str(cm.exception))
            self.assertIn("uv-unwrapping", str(cm.exception))

    def test_session_refuses_an_old_install_before_launching(self):
        keep = (rl.find_rizomuv, rl.exe_version, rl.import_link)
        rl.find_rizomuv = lambda exe=None, link_dir=None: ("C:/old/rizomuv.exe", "C:/old/RizomUVLink")
        rl.exe_version = lambda exe: (2025, 1, 12)
        imported = []
        rl.import_link = lambda d: imported.append(d) or (object, RuntimeError)
        try:
            with self.assertRaises(RuntimeError) as cm:
                rl.RizomSession()
            self.assertIn("2025.1.12", str(cm.exception))
            self.assertEqual(imported, [])                      # refused before RizomUVLink is even imported
            self.assertFalse(rl.RizomSession(headless=False).headless)   # with its window, an old build may run
        finally:
            rl.find_rizomuv, rl.exe_version, rl.import_link = keep

    @unittest.skipUnless(os.name == "nt", "Windows file version resource")
    def test_exe_version_reads_the_windows_file_version(self):
        self.assertEqual(len(rl.exe_version(sys.executable) or ()), 3)
        self.assertIsNone(rl.exe_version(__file__))


class TempFolder(unittest.TestCase):
    def test_short_folder_needs_nothing(self):
        self.assertIsNone(rl.zmq_safe_temp("C:\\Users\\me\\AppData\\Local\\Temp\\"))

    def test_long_folder_gets_a_short_one(self):
        with tempfile.TemporaryDirectory() as base:
            short = os.path.join(base, "Temp")
            if len(short) >= rl.MAX_ZMQ_TEMP:
                self.skipTest("the test's own temp folder is too long to stand in for %LOCALAPPDATA%")
            os.makedirs(short)
            keep = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = base
            try:
                self.assertEqual(rl.zmq_safe_temp("C:\\" + "x" * 120), short)
            finally:
                if keep is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = keep

    def test_no_short_folder_is_a_clear_error(self):
        keep = {k: os.environ.pop(k, None) for k in ("LOCALAPPDATA", "SystemRoot")}
        real_isdir = os.path.isdir
        os.path.isdir = lambda p: False if p == "/tmp" else real_isdir(p)
        try:
            with self.assertRaises(RuntimeError) as cm:
                rl.zmq_safe_temp("C:\\" + "x" * 120)
            self.assertIn("TMP and TEMP", str(cm.exception))
        finally:
            os.path.isdir = real_isdir
            for k, v in keep.items():
                if v is not None:
                    os.environ[k] = v

    def test_short_tmp_is_restored(self):
        before = {k: os.environ.get(k) for k in ("TMP", "TEMP")}
        with rl._short_tmp("C:\\short"):
            self.assertEqual(os.environ["TMP"], "C:\\short")
            self.assertEqual(os.environ["TEMP"], "C:\\short")
        self.assertEqual({k: os.environ.get(k) for k in ("TMP", "TEMP")}, before)
        with rl._short_tmp(None):
            self.assertEqual({k: os.environ.get(k) for k in ("TMP", "TEMP")}, before)


class Ports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.keep = (tempfile.tempdir, rl.PORT_RANGE)
        tempfile.tempdir = self.tmp.name                    # lock files go here, not in the user's temp
        rl.PORT_RANGE = (64700, 64720)

    def tearDown(self):
        tempfile.tempdir, rl.PORT_RANGE = self.keep
        self.tmp.cleanup()

    def test_skips_listening_and_bound_ports_and_locked_ones(self):
        held = []
        try:
            a = socket.socket()
            a.bind(("127.0.0.1", 64700))
            a.listen()
            b = socket.socket()
            b.bind(("127.0.0.1", 64703))                    # bound, not listening: port + 1 of 64702
            held += [a, b]
            other = rl._PortLock(64704)
            self.assertTrue(other.acquire())                # another session holds 64704
            lock = rl._claim_port()
            self.assertEqual(lock.port, 64706)
            lock.release()
            other.release()
        finally:
            for s in held:
                s.close()

    def test_explicit_busy_port_is_an_error(self):
        a = socket.socket()
        a.bind(("127.0.0.1", 64710))
        a.listen()
        try:
            with self.assertRaises(RuntimeError):
                rl._claim_port(64710)
        finally:
            a.close()


class FakeProcess:
    def __init__(self, exits_with=None):
        self.pid, self.returncode, self._exit, self.killed = 4242, None, exits_with, False

    def poll(self):
        if self._exit is not None:
            self.returncode = self._exit
        return self.returncode

    def kill(self):
        self.killed, self.returncode = True, -9

    def wait(self, timeout=None):
        return self.returncode


class StartFailures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.keep = (tempfile.tempdir, rl.PORT_RANGE, rl.find_rizomuv, rl.exe_version, rl.import_link,
                     rl.subprocess.Popen, rl._kill_with_host, rl._listening_pids)
        tempfile.tempdir = self.tmp.name
        rl.PORT_RANGE = (64740, 64760)
        rl.find_rizomuv = lambda exe=None, link_dir=None: ("C:/fake/rizomuv.exe", "C:/fake/RizomUVLink")
        rl.exe_version = lambda exe: (2027, 0, 598)

        class Link:
            def TCPPortIsOpen(self, port):
                return False
        rl.import_link = lambda d: (Link, RuntimeError)
        rl._kill_with_host = lambda p: "fake"
        rl._listening_pids = lambda port: None

    def tearDown(self):
        (tempfile.tempdir, rl.PORT_RANGE, rl.find_rizomuv, rl.exe_version, rl.import_link, rl.subprocess.Popen,
         rl._kill_with_host, rl._listening_pids) = self.keep
        self.tmp.cleanup()

    def start(self, proc, timeout=0.3):
        rl.subprocess.Popen = lambda *a, **kw: proc
        s = rl.RizomSession(timeout=timeout)
        with self.assertRaises(RuntimeError) as cm:
            s.start()
        self.assertIsNone(s.lock)                          # the port lock is released on failure
        return str(cm.exception)

    def test_early_exit_names_the_licence_and_the_command_log(self):
        msg = self.start(FakeProcess(exits_with=1))
        self.assertIn("exited before opening port", msg)
        self.assertIn("licence", msg)
        self.assertIn("CommandLog.py", msg)

    def test_a_new_start_forgets_an_old_timeout(self):
        rl.subprocess.Popen = lambda *a, **kw: FakeProcess(exits_with=1)
        s = rl.RizomSession(timeout=0.3)
        s.timed_out = True
        with self.assertRaises(RuntimeError):
            s.start()
        self.assertFalse(s.timed_out)

    def test_never_listening_names_old_builds_and_reserved_ports(self):
        proc = FakeProcess()
        msg = self.start(proc)
        self.assertIn("is running but did not open port", msg)
        self.assertIn("2027.0.417", msg)
        self.assertIn("excludedportrange", msg)
        self.assertTrue(proc.killed)                       # the hung instance is not left behind


HEARTBEAT = ("import sys, time\n"
             "for _ in range(1200):\n"
             "    open(sys.argv[1], 'w').write(repr(time.time()))\n"
             "    time.sleep(0.05)\n")


def hold_the_gil(seconds):
    """A foreign call that keeps the GIL, as RizomUVLink's calls do (ctypes.PyDLL does not release it)."""
    import ctypes
    if os.name == "nt":
        ctypes.PyDLL("kernel32").Sleep(int(seconds * 1000))
    else:
        ctypes.PyDLL(None).usleep(int(seconds * 1e6))


class Deadline(unittest.TestCase):
    """RizomSession.deadline() kills the instance from a separate process, so it acts during a call that holds
    the GIL; a stand-in process writes a heartbeat file every 50 ms, which shows when it died."""

    def setUp(self):
        import subprocess
        self.tmp = tempfile.TemporaryDirectory()
        self.beat = os.path.join(self.tmp.name, "beat")
        self.victim = subprocess.Popen([sys.executable, "-c", HEARTBEAT, self.beat])
        t0 = time.time()
        while not os.path.exists(self.beat) and time.time() - t0 < 10:
            time.sleep(0.05)
        self.s = rl.RizomSession.__new__(rl.RizomSession)
        self.s.process, self.s.timed_out = self.victim, False

    def tearDown(self):
        if self.victim.poll() is None:
            self.victim.kill()
        self.victim.wait(10)
        self.tmp.cleanup()

    def last_beat(self):
        return float(open(self.beat).read() or 0)

    def test_fires_while_a_call_holds_the_gil(self):
        t0 = time.time()
        with self.s.deadline(1.0):
            hold_the_gil(4.0)
        self.assertTrue(self.s.timed_out)
        self.assertIsNotNone(self.victim.poll())
        self.assertLess(self.last_beat() - t0, 2.5)          # killed near 1 s, not when the call returned

    def test_cancelled_when_the_block_ends_in_time(self):
        t0 = time.time()
        with self.s.deadline(5.0):
            time.sleep(0.2)
        self.assertFalse(self.s.timed_out)
        self.assertIsNone(self.victim.poll())
        self.assertLess(time.time() - t0, 3.0)              # leaving the block does not wait for the deadline

    def test_no_limit_starts_nothing(self):
        keep = rl._start_deadline
        rl._start_deadline = lambda *a: self.fail("no deadline process for seconds None or 0")
        try:
            for seconds in (None, 0):
                with self.s.deadline(seconds):
                    pass
        finally:
            rl._start_deadline = keep
        self.assertIsNone(self.victim.poll())

    def test_without_a_python_a_timer_still_acts_between_calls(self):
        keep = rl._python
        rl._python = lambda: None
        try:
            with self.s.deadline(0.3):
                time.sleep(1.5)                             # releases the GIL: the timer can fire
        finally:
            rl._python = keep
        self.assertTrue(self.s.timed_out)
        self.assertIsNotNone(self.victim.poll())


class FileLocks(unittest.TestCase):
    def test_a_second_holder_is_refused_and_can_read_who_holds_it(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scene.blend.rizomuv-lock")
            lock = rl.FileLock(path, offset=1 << 20)
            self.assertTrue(lock.acquire())
            lock.note("pid 1234 on testhost")
            probe = ("import sys; sys.path.insert(0, %r); import rizom_link as rl; l = rl.FileLock(%r, 1 << 20); "
                     "print(l.acquire(), l.holder())" % (str(SCRIPTS), path))
            out = subprocess.run([sys.executable, "-B", "-c", probe], capture_output=True, text=True,
                                 env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")).stdout.strip()
            self.assertEqual(out, "False pid 1234 on testhost")
            lock.release()
            out = subprocess.run([sys.executable, "-B", "-c", probe], capture_output=True, text=True,
                                 env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")).stdout.strip()
            self.assertTrue(out.startswith("True"), out)

    def test_an_unopenable_lock_file_says_so(self):
        lock = rl.FileLock(os.path.join(tempfile.gettempdir(), "no_such_folder_rizomuv", "x.lock"))
        self.assertFalse(lock.acquire())
        self.assertIsNotNone(lock.open_error)


if __name__ == "__main__":
    unittest.main()
