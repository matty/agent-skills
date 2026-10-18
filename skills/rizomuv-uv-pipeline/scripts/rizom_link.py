"""Find, launch and always close RizomUV instances through RizomUVLink: one private instance per session.

Host: any Python 3.6-3.13 (plain CPython, Blender's bundled Python, another DCC). No bpy, no numpy.
Needs RizomUV 2027.0.417+ for headless mode (checked before launching); RizomUVLink ships inside the install.

    import sys; sys.dont_write_bytecode = True; sys.path.insert(0, r"<skill>/scripts")
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
  - libzmq 4.3.4 (inside RizomUV and RizomUVLink) puts a socket file under the temp folder and aborts the whole
    process when that path is too long: RizomUV exits at start, and the host (Blender included) dies inside
    Connect. Measured 2026-10-17 on 2027.0.598: a 79-character temp folder worked, 115 crashed. A session whose
    temp folder is longer than MAX_ZMQ_TEMP gives RizomUV and its link object a short one (zmq_safe_temp()).

Overrides: RIZOMUV_EXE (the executable; on Linux the AppDir's AppRun) and RIZOMUVLINK_DIR (the RizomUVLink
folder), or pass exe= / link_dir=. Run this file directly to print what it finds and launch/quit once:
    python rizom_link.py
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
MIN_HEADLESS = (2027, 0, 417)  # -hl: https://github.com/RemiArq/RizomUVLink README "Version requirements"
MAX_ZMQ_TEMP = 90             # characters; libzmq's socket path must fit 108 (see the module docstring)
_PRIORITY = {"normal": (0x00000020, 0), "below_normal": (0x00004000, 5), "idle": (0x00000040, 15)}
_REG_VERSION = {}             # exe -> (major, minor) from its registry key


def _version_key(path):
    return [int(n) for n in re.findall(r"\d+", path)]


def parse_version(text):
    """(2027, 0, 598) from '2027.0.598.g864535413', (2027, 0) from 'RizomUV 2027.0'; None when no digits."""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(text or ""))
    if not m:
        return None
    return tuple(int(g) for g in m.groups() if g is not None)


def version_text(v):
    return ".".join(str(n) for n in v) if v else "unknown"


# ----------------------------------------------------------------------------------------------- discovery
def _registry_exes():
    """Windows: [((major, minor), exe)] for every 'RizomUV VS RS <major>.<minor>' install under HKLM, newest first.
    The registered value is the executable path without its .exe (measured on 2027.0), so it is added."""
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
    return sorted(found, reverse=True)


def _candidates():
    system = platform.system()
    if system == "Windows":
        for ver, exe in _registry_exes():
            _REG_VERSION[exe.replace("\\", "/")] = ver
            yield exe
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


def _linux_launchable(exe):
    """Inside an extracted or mounted AppImage the bare usr/bin/rizomuv has no rpath: launch the AppDir's AppRun
    (RizomUVLink.py does the same). Returns the path to launch."""
    if platform.system() != "Linux":
        return exe
    here = os.path.dirname(os.path.abspath(exe))
    app_dir = os.path.dirname(os.path.dirname(here))
    if os.path.basename(exe).lower() == "rizomuv" and os.path.isfile(os.path.join(app_dir, "AppRun")):
        return os.path.join(app_dir, "AppRun")
    return exe


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
                     os.path.join(os.path.dirname(here), "Resources", "RizomUVLink"),  # macOS bundle
                     os.path.join(here, "usr", "bin", "RizomUVLink")):                 # Linux AppDir (AppRun)
            if os.path.isdir(cand):
                link_dir = cand
                break
    if not link_dir or not os.path.isfile(os.path.join(link_dir, "RizomUVLink.py")):
        where = ("%s points to %s" % (link_source, link_dir)) if link_source else "not found next to %s" % exe
        raise RuntimeError("RizomUVLink package (RizomUVLink.py) missing: %s. Set RIZOMUVLINK_DIR or pass "
                           "link_dir= to the RizomUVLink folder of the install." % where)
    return _linux_launchable(exe).replace("\\", "/"), link_dir.replace("\\", "/")


def exe_version(exe):
    """Version of a RizomUV executable without starting it: the Windows file version (2027.0.598 for the 2027
    release), the macOS bundle's CFBundleShortVersionString, else the registry key it came from; None if unknown."""
    exe = exe.replace("\\", "/")
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            ver = ctypes.WinDLL("version")
            size = ver.GetFileVersionInfoSizeW(exe, None)
            if size:
                buf = ctypes.create_string_buffer(size)
                if ver.GetFileVersionInfoW(exe, 0, size, buf):
                    ptr, n = ctypes.c_void_p(), wintypes.UINT()
                    if ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(n)) and n.value >= 52:
                        ms, ls = struct.unpack_from("II", ctypes.string_at(ptr.value, 52), 8)
                        return (ms >> 16, ms & 0xFFFF, ls >> 16)
        except (OSError, AttributeError, ValueError):
            pass
    elif platform.system() == "Darwin" and ".app/" in exe:
        try:
            import plistlib
            with open(exe.split(".app/")[0] + ".app/Contents/Info.plist", "rb") as fh:
                return parse_version(plistlib.load(fh).get("CFBundleShortVersionString"))
        except (OSError, ValueError):
            pass
    return _REG_VERSION.get(exe)


def check_headless_version(version, exe="RizomUV"):
    """Raise RuntimeError when a known version is too old for headless mode (needs 2027.0.417+)."""
    if version and tuple(version) < MIN_HEADLESS[:len(version)]:
        raise RuntimeError(
            "RizomUV %s at %s cannot run headless: -hl needs %s or later (RizomUV 2027 shipped 8 Oct 2026). An "
            "older build shows a usage box nobody can dismiss and never opens its port. Upgrade it, pass "
            "headless=False to drive it with its window, or unwrap with the uv-unwrapping skill (Blender only)."
            % (version_text(version), exe, version_text(MIN_HEADLESS)))


def import_link(link_dir):
    """Import RizomUVLink from link_dir. Returns (CRizomUVLink, CZEx). Explains unsupported Pythons."""
    if link_dir not in sys.path:
        sys.path.insert(0, link_dir)
    ver = "%d.%d" % sys.version_info[:2]
    try:
        from RizomUVLink import CRizomUVLink, CZEx  # noqa: E402  (picks the binary for this Python)
    except ImportError as ex:
        raise RuntimeError(
            "RizomUVLink from %s cannot load under Python %s (%s). RizomUV 2027's package has compiled modules for "
            "Python 3.6-3.13 on Windows and 3.9-3.13 on Linux and macOS (an older RizomUV ships fewer). Run under a "
            "supported Python, for example Blender's bundled one: <blender>/<version>/python/bin/python.exe on "
            "Windows, or inside Blender itself." % (link_dir, ver, ex)) from None
    return CRizomUVLink, CZEx


# ----------------------------------------------------------------------------------------------- temp folder
def _temp_dir():
    """The temp folder libzmq will use: GetTempPathW on Windows (normalised, as libzmq sees it), else TMPDIR."""
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.WinDLL("kernel32").GetTempPathW(1024, buf):
                return buf.value
        except OSError:
            pass
    return tempfile.gettempdir()


def zmq_safe_temp(current=None, limit=MAX_ZMQ_TEMP):
    """None when the temp folder is short enough for libzmq, else a short writable folder to use instead
    (%LOCALAPPDATA%\\Temp, %SystemRoot%\\Temp or /tmp). Raises RuntimeError when there is none."""
    current = _temp_dir() if current is None else current
    if len(current) <= limit:
        return None
    for cand in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp") if os.environ.get("LOCALAPPDATA") else "",
                 os.path.join(os.environ.get("SystemRoot", ""), "Temp") if os.environ.get("SystemRoot") else "",
                 "/tmp"):
        if cand and len(cand) + 1 <= limit and os.path.isdir(cand) and os.access(cand, os.W_OK):
            return cand
    raise RuntimeError("the temp folder %s is %d characters long; RizomUV's libzmq aborts the process above about "
                       "%d. Set TMP and TEMP to a shorter folder." % (current, len(current), limit))


@contextlib.contextmanager
def _short_tmp(short):
    """Point TMP/TEMP (and TMPDIR if set) at `short` while the block runs (libzmq reads it when the link object
    makes its sockets), then put them back."""
    if not short:
        yield
        return
    keys = [k for k in ("TMP", "TEMP", "TMPDIR") if k != "TMPDIR" or k in os.environ]
    saved = {k: os.environ.get(k) for k in keys}
    try:
        for k in keys:
            os.environ[k] = short
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ----------------------------------------------------------------------------------------------- ports
class FileLock:
    """OS lock on one byte of a file (at offset), held until release() or the holder's death: the OS frees it
    then, so a crashed holder never leaves a stale lock. acquire() returns False when another process holds it;
    open_error is set when the file could not even be opened (a read-only folder, for example)."""

    def __init__(self, path, offset=0):
        self.path, self.offset = path, offset
        self.handle = self.open_error = None

    def acquire(self):
        try:
            self.handle = open(self.path, "a+b")
        except OSError as ex:
            self.open_error = ex
            return False
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(self.offset)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.handle.close()
            self.handle = None
            return False

    def note(self, text):
        """Write text at the start of the held lock file (who holds it); with offset > 0 others can read it."""
        if self.handle is not None:
            self.handle.seek(0)
            self.handle.truncate()
            self.handle.write(text.encode("utf-8"))
            self.handle.flush()

    def holder(self):
        """The text the current holder wrote with note(), or "" if it cannot be read."""
        try:
            with open(self.path, "rb") as fh:
                return fh.read(min(self.offset, 4096)).decode("utf-8", "replace").strip()
        except OSError:
            return ""

    def release(self):
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(self.offset)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self.handle.close()
        self.handle = None


class _PortLock(FileLock):
    """OS file lock on one port, held for a whole session and released by the OS if the holder dies."""

    def __init__(self, port):
        FileLock.__init__(self, os.path.join(tempfile.gettempdir(), "rizomuv_skill_port_%d.lock" % port))
        self.port = port


def _port_in_use(port):
    """True when port or port + 1 cannot serve a new instance: something accepts connections on it, or it
    cannot be bound on 127.0.0.1 (in use, or reserved: netsh int ipv4 show excludedportrange protocol=tcp)."""
    for p in (port, port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", p)) == 0:
                return True
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
            except OSError:
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
_JOBS = []   # job handles stay open while their process may live: closing one kills what it holds


def _kill_with_host(proc):
    """Tie proc to this host process. Windows: Job Object with KILL_ON_JOB_CLOSE (the handle is kept in _JOBS
    and on proc._rizom_job). Elsewhere, or if that fails: a watchdog process that kills proc when this host
    disappears. Returns what was used: "job" or "watchdog"."""
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
            try:
                proc._rizom_job = job
            except AttributeError:
                pass
            return "job"
        except OSError:
            pass
    _start_watchdog(proc.pid)
    return "watchdog"


def _release_job(proc):
    """Close proc's job handle (kills anything still in the job, children included) and forget it."""
    job = getattr(proc, "_rizom_job", None)
    if not job:
        return
    try:
        import ctypes
        ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(job))
    except OSError:
        pass
    if job in _JOBS:
        _JOBS.remove(job)
    proc._rizom_job = None


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


def _python():
    """A Python interpreter for helper processes: sys.executable when it is one (Blender's bundled python.exe
    is), else one next to this interpreter, else None (some hosts' sys.executable is the host itself)."""
    for exe in (sys.executable, getattr(sys, "_base_executable", None),
                os.path.join(sys.prefix, "python.exe"), os.path.join(sys.prefix, "bin", "python3")):
        if exe and os.path.basename(exe).lower().startswith("python") and os.path.isfile(exe):
            return exe
    return None


def _start_watchdog(child_pid):
    flags = 0x00000008 | 0x08000000 if os.name == "nt" else 0   # DETACHED_PROCESS | CREATE_NO_WINDOW
    subprocess.Popen([_python() or sys.executable, "-c", _WATCHDOG, str(os.getpid()), str(child_pid)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags, close_fds=True)


_DEADLINE = r"""
import os, sys, threading
pid, seconds = int(sys.argv[1]), float(sys.argv[2])
cancelled = threading.Event()
def wait_for_eof():
    try:
        sys.stdin.buffer.read()                            # EOF: the host left the block, or died
    except Exception:
        pass
    cancelled.set()
threading.Thread(target=wait_for_eof, daemon=True).start()
if cancelled.wait(seconds):
    os._exit(0)                                            # no finalisation: the reader thread is blocked
if os.name == "nt":
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    h = k32.OpenProcess(0x0001, False, pid)                # PROCESS_TERMINATE
    if h:
        k32.TerminateProcess(h, 1)
        k32.CloseHandle(h)
else:
    import signal
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
os._exit(3)
"""


def _start_deadline(pid, seconds):
    """A separate process that kills pid after seconds unless its stdin is closed first (exit code 3 when it
    fired). It runs outside this interpreter, so it acts even while a RizomUVLink call holds the GIL, which a
    threading.Timer cannot. Returns the Popen, or None when no Python interpreter was found to run it."""
    exe = _python()
    if exe is None:
        return None
    try:
        return subprocess.Popen([exe, "-I", "-S", "-c", _DEADLINE, str(pid), repr(float(seconds))],
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=0x08000000 if os.name == "nt" else 0, close_fds=True)
    except OSError:
        return None


def command_log(version=None):
    """Where RizomUV writes its command log, which also records what a headless instance answered to a dialog:
    <Documents>/RizomUV/<major>/logs/CommandLog.py."""
    docs = None
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.WinDLL("shell32").SHGetFolderPathW(None, 5, None, 0, buf) == 0:   # CSIDL_PERSONAL
                docs = buf.value
        except OSError:
            pass
    docs = docs or os.path.join(os.path.expanduser("~"), "Documents")
    major = str(version[0]) if version else "<major>"
    return os.path.join(docs, "RizomUV", major, "logs", "CommandLog.py")


def _exit_reason(code):
    if code in (1073741845, -1073741819, 3221225477, 3):       # 0x40000015 abort, access violation, abort()
        return ("it aborted at start (exit %s): a temp folder too long for its libzmq is handled here, so check "
                "the command log" % code)
    return "exit code %s" % code


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
        self.exe_version = exe_version(self.exe)
        if headless:
            check_headless_version(self.exe_version, self.exe)
        self.CRizomUVLink, self.CZEx = import_link(self.link_dir)
        self.headless, self.timeout, self.want_port = headless, float(timeout), port
        self.iconized, self.background = iconized, background
        self.link = self.process = self.lock = None
        self.port = self.version = self.build = None
        self.tied_by = None
        self.timed_out = False

    @property
    def pid(self):
        return self.process.pid if self.process else None

    def start(self):
        self.timed_out = False                 # a new instance: an earlier deadline no longer applies
        short = zmq_safe_temp()
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
        if short:
            extra["env"] = dict(os.environ, TMP=short, TEMP=short)
            if "TMPDIR" in os.environ:
                extra["env"]["TMPDIR"] = short
        try:
            # RizomUV's console chatter would flood the host's output; its command log stays in
            # <Documents>/RizomUV/<major>/logs/CommandLog.py
            self.process = subprocess.Popen(args, cwd=os.path.dirname(self.exe), stdin=subprocess.DEVNULL,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra)
            self.tied_by = _kill_with_host(self.process)
            with _short_tmp(short):
                link = self.CRizomUVLink()      # its sockets are made here: libzmq reads the temp folder now
            deadline = time.time() + self.timeout
            while not link.TCPPortIsOpen(self.port):
                if self.process.poll() is not None:
                    raise RuntimeError(
                        "RizomUV exited before opening port %d: %s. Usual causes: no licence (a headless instance "
                        "answers the licence dialog 'no' and exits: start it once with its window), a command-line "
                        "flag this build does not know, or not a RizomUV executable (%s). What it said is at the end "
                        "of %s." % (self.port, _exit_reason(self.process.returncode), self.exe,
                                    command_log(self.exe_version)))
                if time.time() > deadline:
                    raise RuntimeError(
                        "RizomUV (PID %d) is running but did not open port %d within %.0f s. Usual causes: a build "
                        "older than %s does not know -hl and shows a usage box nobody can dismiss; the port is "
                        "reserved (netsh int ipv4 show excludedportrange protocol=tcp); a first launch slowed by "
                        "antivirus (raise timeout=); no logged-in desktop session (a service, a scheduled task, SSH). "
                        "See %s." % (self.process.pid, self.port, self.timeout, version_text(MIN_HEADLESS),
                                     command_log(self.exe_version)))
                time.sleep(0.1)
            owners = _listening_pids(self.port)
            if owners is not None and owners and self.process.pid not in owners:
                raise RuntimeError("port %d is answered by PID %s, not by the instance this session started "
                                   "(PID %d)" % (self.port, sorted(owners), self.process.pid))
            link.Connect(self.port)
            link.port = self.port
            self.version = link.RizomUVVersion()     # round trip: the instance has finished starting
            self.build = parse_version(self.version)
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
        if self.process is not None:
            _release_job(self.process)
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
        self.timed_out is True. Restart the session before using it again. seconds None or 0: no limit.
        The deadline runs in a separate process: a RizomUVLink call holds the GIL for its whole length (measured
        2026-10-17: a 2 s threading.Timer fired only when a 158 s auto-seam returned), so no thread of this
        process can interrupt it. With no Python interpreter to start, a timer is used, which acts only between
        commands."""
        self.timed_out = False
        if not seconds or self.process is None:
            yield
            return
        dog = _start_deadline(self.process.pid, seconds)
        timer = None
        if dog is None:
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
            if timer is not None:
                timer.cancel()
            if dog is not None:
                try:
                    dog.stdin.close()                   # cancels it unless it has already fired
                except OSError:
                    pass
                try:
                    code = dog.wait(10)
                except subprocess.TimeoutExpired:
                    dog.kill()
                    code = None
                if code == 3:
                    self.timed_out = True


@contextlib.contextmanager
def rizom_session(headless=True, exe=None, link_dir=None, timeout=120.0, port=None, priority=None):
    """Start one private RizomUV instance, yield its connected link, and always close it.

    The link carries .port and .session (pid, version, build, restart(), deadline()). One instance serves any
    number of meshes: launching costs about 2 s (5-9 s with three starting together), most commands on small
    meshes take milliseconds. Each instance takes a licence token on a floating licence."""
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
    print("file ver ", version_text(exe_version(exe)), "(headless needs %s+)" % version_text(MIN_HEADLESS))
    print("temp     ", _temp_dir(), "-> RizomUV gets %s" % (zmq_safe_temp() or "the same"))
    t = time.perf_counter()
    with rizom_session() as link:
        print("version  ", link.RizomUVVersion(), "launched in %.1f s" % (time.perf_counter() - t))
        print("port     ", link.port, "pid", link.session.pid, "tied to host by", link.session.tied_by)
    print("quit ok")
