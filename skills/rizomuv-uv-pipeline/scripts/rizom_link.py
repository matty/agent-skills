"""Find, launch and always close RizomUV instances through RizomUVLink: one private instance per session.

Host: any Python 3.6-3.13 (plain CPython, Blender's bundled Python, another DCC). No bpy, no numpy.
Needs RizomUV 2027.0.417+ for headless mode; RizomUVLink ships inside the RizomUV install.

    import sys; sys.path.insert(0, r"<skill>/scripts")
    from rizom_link import rizom_session
    with rizom_session() as link:              # headless; the instance is always closed, even on error
        print(link.RizomUVVersion(), link.port, link.session.pid)

Rules that keep concurrent work safe (each one was broken once):
  - One session per process at a time is the normal case; several sessions in one process are fine when used
    from ONE thread. Never share a link between threads, and never open sessions from several threads: the link
    protocol is one client per port, and crossed replies come back without an error.
  - Sessions in separate processes are safe at any moment: each claims a port with an OS lock held for the whole
    session, starts its own rizomuv.exe on it, and checks that the process answering on that port is that child.
    RizomUVLink's own RunRizomUV is not used, because a launcher that loses its port lock waits for and
    connects to the winner's instance.
  - The instance dies with the host: on Windows it is put in a Job Object that kills it when the host process
    goes away (crash, kill, batch timeout); elsewhere a small watchdog process does the same.
  - close() sends Quit and waits for the process to exit, killing it after a grace period.
  - priority="below_normal" (or "idle") starts the instance at a lower CPU priority, for batches that share
    the machine with interactive work. Default: RIZOMUV_PRIORITY, else "normal".

Overrides: RIZOMUV_EXE (the executable) and RIZOMUVLINK_DIR (the RizomUVLink folder), or pass exe= / link_dir=.
Run this file directly to print what it finds and launch/quit once:  python rizom_link.py
"""

import contextlib
import glob
import os
import platform
import re
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

PORT_RANGE = (61000, 64998)   # above RunRizomUV's upward scan from 49152, so other tools rarely collide
PORT_STEP = 2                 # an instance can also bind port + 1 (change notifications)
QUIT_GRACE_S = 10.0
_PRIORITY = {"normal": (0x00000020, 0), "below_normal": (0x00004000, 5), "idle": (0x00000040, 15)}


def _version_key(path):
    return [int(n) for n in re.findall(r"\d+", path)]


# ----------------------------------------------------------------------------------------------- discovery
def _registry_exes():
    """Windows: every 'RizomUV VS RS <major>.<minor>' install under HKLM, newest first. The registered value
    is the executable path without its .exe (measured on 2027.0), so the extension is added when missing."""
    try:
        import winreg
    except ImportError:
        return []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\Rizom Lab")
    except OSError:
        return []
    found = []
    with root:
        i = 0
        while True:
            try:
                name = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            m = re.fullmatch(r"RizomUV VS RS ([0-9]+)\.([0-9]+)", name)
            if not m:
                continue
            try:
                with winreg.OpenKey(root, name) as key:
                    value = winreg.QueryValue(key, "rizomuv.exe")
            except OSError:
                continue
            if value and not value.lower().endswith(".exe"):
                value += ".exe"
            found.append(((int(m.group(1)), int(m.group(2))), value))
    return [exe for _, exe in sorted(found, reverse=True)]


def _candidates():
    system = platform.system()
    if system == "Windows":
        yield from _registry_exes()
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), r"C:\Program Files"):
            yield from sorted(glob.glob(os.path.join(base, "Rizom Lab", "RizomUV *", "rizomuv.exe")),
                              key=_version_key, reverse=True)
    elif system == "Darwin":
        for app in sorted(glob.glob("/Applications/RizomUV*.app"), key=_version_key, reverse=True):
            stem = os.path.splitext(os.path.basename(app))[0]
            yield os.path.join(app, "Contents", "MacOS", stem)
    else:
        import shutil
        for name in ("rizomuv", "RizomUV"):
            hit = shutil.which(name)
            if hit:
                yield hit


def find_rizomuv(exe=None, link_dir=None):
    """Return (exe, link_dir) for the newest RizomUV install, or raise RuntimeError saying what was tried."""
    source = "exe argument" if exe else ("RIZOMUV_EXE" if os.environ.get("RIZOMUV_EXE") else None)
    exe = exe or os.environ.get("RIZOMUV_EXE")
    if exe:
        if not os.path.isfile(exe):
            raise RuntimeError("RizomUV executable from %s does not exist: %s" % (source, exe))
    else:
        tried = []
        for cand in _candidates():
            tried.append(cand)
            if os.path.isfile(cand):
                exe = cand
                break
        if not exe:
            raise RuntimeError("RizomUV executable not found (registry, Program Files, /Applications, PATH). "
                               "Set RIZOMUV_EXE or pass exe=. Tried: %s" % (tried or "nothing found to try"))
    link_source = "link_dir argument" if link_dir else ("RIZOMUVLINK_DIR" if os.environ.get("RIZOMUVLINK_DIR")
                                                        else None)
    link_dir = link_dir or os.environ.get("RIZOMUVLINK_DIR")
    if not link_dir:
        here = os.path.dirname(exe)
        for cand in (os.path.join(here, "RizomUVLink"),                               # Windows, Linux usr/bin
                     os.path.join(os.path.dirname(here), "Resources", "RizomUVLink")):  # macOS bundle
            if os.path.isdir(cand):
                link_dir = cand
                break
    if not link_dir or not os.path.isfile(os.path.join(link_dir, "RizomUVLink.py")):
        where = ("%s points to %s" % (link_source, link_dir)) if link_source else "not found next to %s" % exe
        raise RuntimeError("RizomUVLink package (RizomUVLink.py) missing: %s. Set RIZOMUVLINK_DIR or pass "
                           "link_dir= to the RizomUVLink folder of the install." % where)
    return exe.replace("\\", "/"), link_dir.replace("\\", "/")


def import_link(link_dir):
    """Import RizomUVLink from link_dir. Returns (CRizomUVLink, CZEx). Explains unsupported Pythons."""
    if link_dir not in sys.path:
        sys.path.insert(0, link_dir)
    ver = "%d.%d" % sys.version_info[:2]
    try:
        from RizomUVLink import CRizomUVLink, CZEx  # noqa: E402  (picks the binary for this Python)
    except ImportError as ex:
        raise RuntimeError(
            "RizomUVLink cannot load under Python %s (%s). It ships compiled modules for Python 3.6-3.13 only "
            "(see %s). Run under a supported Python, for example Blender's bundled one: "
            "<blender>/<version>/python/bin/python.exe on Windows, or inside Blender itself."
            % (ver, ex, link_dir)) from None
    return CRizomUVLink, CZEx


# ----------------------------------------------------------------------------------------------- ports
class _PortLock:
    """OS file lock on one port, held for a whole session and released by the OS if the holder dies."""

    def __init__(self, port):
        self.port = port
        self.path = os.path.join(tempfile.gettempdir(), "rizomuv_skill_port_%d.lock" % port)
        self.handle = None

    def acquire(self):
        try:
            self.handle = open(self.path, "a+b")
        except OSError:
            return False
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.handle.close()
            self.handle = None
            return False

    def release(self):
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self.handle.close()
        self.handle = None


def _port_in_use(port):
    """True when anything accepts connections on 127.0.0.1:port or the next port."""
    for p in (port, port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", p)) == 0:
                return True
    return False


def _claim_port(port=None):
    """Lock a free port (and port + 1) for this session. Returns the held _PortLock."""
    ports = [port] if port else range(PORT_RANGE[0], PORT_RANGE[1], PORT_STEP)
    for p in ports:
        lock = _PortLock(p)
        if not lock.acquire():
            continue
        if _port_in_use(p):
            lock.release()
            continue
        return lock
    if port:
        raise RuntimeError("port %d is locked by another session or already in use" % port)
    raise RuntimeError("no free port in %d-%d for RizomUV" % PORT_RANGE)


def _listening_pids(port):
    """Windows: PIDs listening on a TCP port (IPv4 and IPv6). None where this cannot be checked."""
    if os.name != "nt":
        return None
    import ctypes
    iphlp = ctypes.WinDLL("iphlpapi")
    pids = set()
    for family, row_size, port_off, pid_off in ((2, 24, 8, 20), (23, 56, 20, 52)):
        size = ctypes.c_ulong(0)
        iphlp.GetExtendedTcpTable(None, ctypes.byref(size), False, family, 3, 0)   # 3 = OWNER_PID_LISTENER
        buf = ctypes.create_string_buffer(size.value + 1024)
        size = ctypes.c_ulong(len(buf))
        if iphlp.GetExtendedTcpTable(buf, ctypes.byref(size), False, family, 3, 0) != 0:
            continue
        n = struct.unpack_from("I", buf, 0)[0]
        for i in range(n):
            base = 4 + row_size * i
            raw_port = struct.unpack_from("I", buf, base + port_off)[0]
            if socket.ntohs(raw_port & 0xFFFF) == port:
                pids.add(struct.unpack_from("I", buf, base + pid_off)[0])
    return pids


# ----------------------------------------------------------------------------------------------- lifetime
_JOBS = []   # job handles stay open for the host's lifetime: closing one kills what it holds


def _kill_with_host(proc):
    """Tie proc to this host process. Windows: Job Object with KILL_ON_JOB_CLOSE. Elsewhere, or if that
    fails: a watchdog process that kills proc when this host disappears. Returns what was used."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
            k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
            k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            k32.CloseHandle.argtypes = (wintypes.HANDLE,)

            class _Basic(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class _Extended(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", ctypes.c_uint64 * 6),
                            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
            job = k32.CreateJobObjectW(None, None)
            if not job:
                raise OSError(ctypes.get_last_error(), "CreateJobObject")
            info = _Extended()
            info.BasicLimitInformation.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise OSError(ctypes.get_last_error(), "SetInformationJobObject")
            h = k32.OpenProcess(0x0100 | 0x0001, False, proc.pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
            if not h:
                raise OSError(ctypes.get_last_error(), "OpenProcess")
            try:
                if not k32.AssignProcessToJobObject(job, h):
                    raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject")
            finally:
                k32.CloseHandle(h)
            _JOBS.append(job)
            return "job"
        except OSError:
            pass
    _start_watchdog(proc.pid)
    return "watchdog"


_WATCHDOG = r"""
import os, sys, time
host, child = int(sys.argv[1]), int(sys.argv[2])
def alive(pid):
    if os.name == "nt":
        import ctypes
        k32 = ctypes.WinDLL("kernel32")
        h = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259              # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
while alive(child):
    if not alive(host):
        if os.name == "nt":
            import subprocess
            subprocess.run(["taskkill", "/PID", str(child), "/F"], capture_output=True)
        else:
            import signal
            os.kill(child, signal.SIGKILL)
        break
    time.sleep(1.0)
"""


def _start_watchdog(child_pid):
    flags = 0x00000008 | 0x08000000 if os.name == "nt" else 0   # DETACHED_PROCESS | CREATE_NO_WINDOW
    subprocess.Popen([sys.executable, "-c", _WATCHDOG, str(os.getpid()), str(child_pid)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags, close_fds=True)


# ----------------------------------------------------------------------------------------------- session
class RizomSession:
    """One private RizomUV instance: start(), link, restart(), close(), alive(), deadline(seconds)."""

    def __init__(self, headless=True, exe=None, link_dir=None, timeout=120.0, port=None, iconized=False,
                 background=False, priority=None):
        priority = (priority or os.environ.get("RIZOMUV_PRIORITY") or "normal").lower()
        if priority not in _PRIORITY:
            raise ValueError("priority must be one of %s, not %r" % (sorted(_PRIORITY), priority))
        self.priority = priority
        self.exe, self.link_dir = find_rizomuv(exe, link_dir)
        self.CRizomUVLink, self.CZEx = import_link(self.link_dir)
        self.headless, self.timeout, self.want_port = headless, float(timeout), port
        self.iconized, self.background = iconized, background
        self.link = self.process = self.lock = None
        self.port = self.version = None
        self.tied_by = None
        self.timed_out = False

    @property
    def pid(self):
        return self.process.pid if self.process else None

    def start(self):
        self.lock = _claim_port(self.want_port)
        self.port = self.lock.port
        args = [self.exe, "-id", str(self.port)]
        if self.headless:
            args.append("-hl")
        else:
            args += (["-i"] if self.iconized else []) + (["-bg"] if self.background else [])
        win_class, nice = _PRIORITY[self.priority]
        extra = {"creationflags": win_class} if os.name == "nt" else (
            {"preexec_fn": lambda: os.nice(nice)} if nice else {})
        try:
            # RizomUV's console chatter would flood the host's output; its command log stays in
            # <Documents>/RizomUV/<major>/logs/CommandLog.py
            self.process = subprocess.Popen(args, cwd=os.path.dirname(self.exe), stdin=subprocess.DEVNULL,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra)
            self.tied_by = _kill_with_host(self.process)
            link = self.CRizomUVLink()
            deadline = time.time() + self.timeout
            while not link.TCPPortIsOpen(self.port):
                if self.process.poll() is not None:
                    raise RuntimeError("RizomUV exited with code %s before opening port %d (bad command line, "
                                       "no licence, or not a RizomUV executable: %s)"
                                       % (self.process.returncode, self.port, self.exe))
                if time.time() > deadline:
                    raise RuntimeError("RizomUV did not open port %d within %.1f s (first launch after an "
                                       "install can be slow: raise timeout=)" % (self.port, self.timeout))
                time.sleep(0.1)
            owners = _listening_pids(self.port)
            if owners is not None and owners and self.process.pid not in owners:
                raise RuntimeError("port %d is answered by PID %s, not by the instance this session started "
                                   "(PID %d)" % (self.port, sorted(owners), self.process.pid))
            link.Connect(self.port)
            link.port = self.port
            self.version = link.RizomUVVersion()     # round trip: the instance has finished starting
            link.session = self
            self.link = link
        except BaseException:
            self._kill()
            raise
        return self.link

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def close(self, grace=QUIT_GRACE_S):
        """Quit, wait for the process to exit (kill after grace seconds), release the port."""
        if self.process is None:
            return
        if self.alive() and self.link is not None:
            try:
                self.link.Quit({})
            except Exception:  # noqa: BLE001  (the connection drops as the instance exits)
                pass
            try:
                self.process.wait(grace)
            except subprocess.TimeoutExpired:
                pass
        self._kill()

    def _kill(self):
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.kill()
                self.process.wait(10)
            except Exception:  # noqa: BLE001
                pass
        if self.lock is not None:
            self.lock.release()
        self.link = self.lock = None

    def restart(self):
        self.close(grace=2.0)
        self.process = None
        return self.start()

    @contextlib.contextmanager
    def deadline(self, seconds):
        """Kill the instance if the block runs longer than seconds; the blocked call then raises, and
        self.timed_out is True. Restart the session before using it again."""
        self.timed_out = False
        if not seconds:
            yield
            return

        def fire():
            self.timed_out = True
            if self.process is not None and self.process.poll() is None:
                self.process.kill()
        timer = threading.Timer(seconds, fire)
        timer.daemon = True
        timer.start()
        try:
            yield
        finally:
            timer.cancel()


@contextlib.contextmanager
def rizom_session(headless=True, exe=None, link_dir=None, timeout=120.0, port=None, priority=None):
    """Start one private RizomUV instance, yield its connected link, and always close it.

    The link carries .port and .session (pid, version, restart(), deadline()). One instance serves any number
    of meshes: launching costs about 2 s, most commands on small meshes take milliseconds. Each instance takes a
    licence token on a floating licence."""
    session = RizomSession(headless=headless, exe=exe, link_dir=link_dir, timeout=timeout, port=port,
                           priority=priority)
    session.start()
    try:
        yield session.link
    finally:
        session.close()


if __name__ == "__main__":
    exe, link_dir = find_rizomuv()
    print("exe      ", exe)
    print("link_dir ", link_dir)
    t = time.perf_counter()
    with rizom_session() as link:
        print("version  ", link.RizomUVVersion(), "launched in %.1f s" % (time.perf_counter() - t))
        print("port     ", link.port, "pid", link.session.pid, "tied to host by", link.session.tied_by)
    print("quit ok")
