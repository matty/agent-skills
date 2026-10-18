"""Run RizomUV work in N separate processes at once, each with its own private RizomUV instance.

Host: any Python 3.6-3.13 that RizomUVLink supports (Blender's bundled python.exe works; numpy is needed for the
gate, and Blender's Python has it). No bpy.

    import rizom_pool as rp
    res = rp.unwrap_many({"crate": mesh_a, "urn": mesh_b}, kind="hard", workers=3,
                         packs=lambda name, mesh: {"uv0": rp.ru.pack_spec(1024),
                                                   "uv2": rp.ru.lightmap_spec(mesh, texels_per_m=20)},
                         on_result=lambda name, r: print(name, r.get("failures", r.get("error"))))
    res["crate"]["packs"]["uv0"]["uvw_ids"], res["crate"]["packs"]["uv0"]["uvw"]

    rp.run_commands([[blender, "-b", "--factory-startup", "--python-exit-code", "1", f, "--python", job]
                     for f in blend_files], workers=3, check=True)      # raises if any job exited non-zero

    <python> rizom_pool.py --selftest 3        # three workers started at the same instant, each must get its own
                                              # mesh back from its own instance; exit 1 otherwise

How the pool supervises its workers:
  - Each worker is a separate process with one RizomUV session (rizom_link claims a port with an OS lock for the
    session's lifetime, starts its own rizomuv.exe and checks the instance answering is that child), so workers
    can start at the same moment. Threads would also get separate sessions, but a stuck command blocks its thread
    and Blender's Python is not built for it.
  - Workers are tied to this host (Windows Job Object, elsewhere a watchdog): if the host is killed, they die and
    take their RizomUV instances, and licence tokens, with them. An exception or Ctrl+C in the host kills them too.
  - Meshes are handed out one at a time and each result streams back as soon as it is done, so a slow mesh never
    holds up another worker's queue, and a worker that dies loses only the mesh it was on.
  - A worker that cannot start RizomUV (no free licence token, for example) reports it and leaves; the others take
    its share. Keep workers at or below the free licence tokens: 3-4 is plenty.
  - timeout is per mesh. Past it the worker kills its RizomUV, reports the mesh as timed out and restarts; a
    worker silent for timeout + stall_slack seconds is killed. timeout None or 0: no limit.
"""

import collections
import glob
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_KEEP_BYTECODE, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # no __pycache__ in the skill folder
import rizom_uv as ru  # noqa: E402
import rizom_link as rl  # noqa: E402
from rizom_link import RizomSession  # noqa: E402
sys.dont_write_bytecode = _KEEP_BYTECODE

_PRIORITY_FLAGS = {"normal": 0x20, "below_normal": 0x4000, "idle": 0x40}


def _popen_kw(priority):
    if os.name == "nt" and priority in _PRIORITY_FLAGS:
        return {"creationflags": _PRIORITY_FLAGS[priority]}
    return {}


def _json_safe(obj):
    """NaN and infinity to None (strict JSON), recursively."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _kill(p):
    """Kill a child and everything in its job (its RizomUV included)."""
    try:
        if p.poll() is None:
            p.kill()
        p.wait(10)
    except Exception:  # noqa: BLE001
        pass
    rl._release_job(p)


# ----------------------------------------------------------------------------------------------- command lines
def run_commands(commands, workers=4, timeout=None, priority=None, cwd=None, on_tick=None, check=False):
    """Run command lines (lists) with at most `workers` at once. Returns [{"cmd", "exit", "ok", "seconds",
    "output"}] in input order; "exit" is "TIMEOUT" when a command ran past timeout seconds (it is killed; None or
    0: no limit), "ok" is True only for exit code 0. check=True raises RuntimeError naming every failed command
    after all have run. Blender jobs need --python-exit-code 1 to exit non-zero on a Python error, and a job's FAIL
    or REVIEW lines never set its exit code: read its report. Children are tied to this host and killed if this call
    raises (Ctrl+C included). on_tick(running, done) is called on every poll."""
    priority = priority or os.environ.get("RIZOMUV_PRIORITY") or "normal"
    pending = list(enumerate(commands))
    running, results = {}, [None] * len(commands)
    try:
        while pending or running:
            while pending and len(running) < max(1, int(workers)):
                i, cmd = pending.pop(0)
                log = tempfile.TemporaryFile()
                p = subprocess.Popen(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     **_popen_kw(priority))
                rl._kill_with_host(p)
                running[i] = (p, log, time.time(), cmd)
            for i, (p, log, t0, cmd) in list(running.items()):
                code = p.poll()
                if code is None and timeout and time.time() - t0 > timeout:
                    _kill(p)
                    code = "TIMEOUT"
                if code is not None:
                    log.seek(0)
                    out = log.read().decode("utf-8", "replace")
                    log.close()
                    rl._release_job(p)
                    results[i] = {"cmd": cmd, "exit": code, "ok": code == 0, "seconds": round(time.time() - t0, 2),
                                  "output": out[-4000:]}
                    del running[i]
            if on_tick:
                on_tick(len(running), sum(r is not None for r in results))
            time.sleep(0.05)
    finally:
        for p, log, _, _ in running.values():
            _kill(p)
            log.close()
    failed = [r for r in results if not r["ok"]]
    if check and failed:
        raise RuntimeError("%d of %d command(s) failed: %s" % (len(failed), len(results), "; ".join(
            "%s exited %s: %s" % (" ".join(str(c) for c in r["cmd"])[:120], r["exit"], r["output"][-300:].strip())
            for r in failed)))
    return results


# ----------------------------------------------------------------------------------------------- meshes
class _Worker:
    def __init__(self, wid, argv, priority, events):
        self.wid, self.busy, self.sent_at, self.ready, self.info = wid, None, None, False, {}
        self.err = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.err,
                                     universal_newlines=True, bufsize=1, **_popen_kw(priority))
        rl._kill_with_host(self.proc)
        threading.Thread(target=self._read, args=(events,), daemon=True).start()

    def _read(self, events):
        for line in self.proc.stdout:
            events.put((self.wid, line))
        events.put((self.wid, None))

    def send(self, text):
        try:
            self.proc.stdin.write(text + "\n")
            self.proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def stderr_tail(self, n=600):
        try:
            self.err.seek(0)
            return self.err.read().decode("utf-8", "replace")[-n:]
        except (OSError, ValueError):
            return ""

    def close(self):
        try:
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
        _kill(self.proc)
        self.err.close()


def unwrap_many(meshes, kind="hard", packs=None, workers=4, gate=None, timeout=600.0, python=None, priority=None,
                on_result=None, stall_slack=120.0, worker_cmd=None, stats=None, start_together=False):
    """Unwrap {name: mesh} in up to `workers` processes, handing meshes out one at a time. Returns {name: result}
    where a result is rizom_uv.unwrap_gated's dict (unwrap_and_pack's when numpy is missing) plus "worker" (index,
    port, pid, RizomUV version), or {"error": ...}. on_result(name, result) is called as each mesh finishes.
    timeout: seconds per mesh (None or 0: no limit). kind and packs are one value for every mesh, or a function
    (name, mesh) -> value for per-mesh settings, such as each mesh's own preset and lightmap footprint:
        kind=lambda name, mesh: kinds.get(name, "hard"),
        packs=lambda name, mesh: {"uv0": ru.pack_spec(1024), "uv2": ru.lightmap_spec(mesh, texels_per_m=20)}
    The pool sees plain meshes only: Blender objects' properties (rizom_kind, rizom_directional,
    rizom_lightmap_scale), the refusals (linked meshes, modifiers), the OK / REVIEW / FAIL lines, the report and
    writing the layers back are blender_rizom's; for one .blend, one blender_rizom.unwrap_objects call does all of
    that.
    stats (a dict) receives "workers" {index: ready info and mesh count} and "start_errors". start_together=True
    holds the meshes until every worker has started or failed (the self-test uses it; normally the first worker
    ready starts at once). worker_cmd: argv that starts a worker, the job file path is appended (tests use a fake)."""
    names = list(meshes)
    stats = {} if stats is None else stats
    stats.update({"workers": {}, "start_errors": []})
    if not names:
        return {}
    packs = packs or {"uv0": ru.pack_spec(1024)}
    if not callable(kind):
        kind = ru.resolve_kind(kind)                 # a typo fails here, not once per mesh
    if gate is not None:                             # a bad gate fails here, not once per mesh in every worker
        try:
            ru.metrics().merge_gate(gate)
        except ImportError:
            if not isinstance(gate, dict):
                raise TypeError("gate must be a dict of thresholds such as {'angular_p95': 1.2}, not %r" % (gate,))
    _remove_stale_dirs()
    tmp = tempfile.mkdtemp(prefix="rizom_pool_")
    owner = _dir_lock(tmp)
    results, pool, events = {}, {}, queue.Queue()
    try:
        for i, n in enumerate(names):
            with open(os.path.join(tmp, "mesh_%d.json" % i), "w", encoding="utf-8") as fh:
                json.dump({"mesh": ru.normalise(meshes[n]),
                           "kind": ru.resolve_kind(kind(n, meshes[n]) if callable(kind) else kind),
                           "packs": packs(n, meshes[n]) if callable(packs) else packs}, fh)
        job = os.path.join(tmp, "job.json")
        with open(job, "w", encoding="utf-8") as fh:
            json.dump({"gate": gate, "timeout": timeout or None, "priority": priority, "dir": tmp}, fh)
        argv = list(worker_cmd or [python or sys.executable, "-B", os.path.abspath(__file__), "--worker"]) + [job]
        pending = collections.deque(range(len(names)))
        want = max(1, min(int(workers), len(names)))
        start_errors, spawned = stats["start_errors"], 0
        for _ in range(want):
            pool[spawned] = _Worker(spawned, argv, priority, events)
            spawned += 1
        holding = [bool(start_together)]

        def release_hold():
            if holding[0] and all(w.ready or w.info.get("start_failed") for w in pool.values()):
                holding[0] = False
                for w in list(pool.values()):
                    if w.ready and w.busy is None:
                        feed(w)

        def done(i, res):
            if names[i] not in results:
                results[names[i]] = res
                if on_result:
                    on_result(names[i], res)

        def feed(w):
            if pending:
                w.busy, w.sent_at = pending.popleft(), time.time()
                if not w.send(str(w.busy)):
                    pending.appendleft(w.busy)
                    w.busy = None
            else:
                w.send("quit")

        while len(results) < len(names):
            try:
                wid, line = events.get(timeout=0.5)
            except queue.Empty:
                wid, line = None, ""
            w = pool.get(wid)
            if w is not None and line is None:                       # the worker's output ended: it exited
                w.proc.wait()
                if w.busy is not None:
                    done(w.busy, {"error": "worker %d exited (code %s) while unwrapping this mesh: %s"
                                  % (wid, w.proc.returncode, w.stderr_tail())})
                    w.busy = None
                if not w.ready and not w.info.get("start_failed"):
                    start_errors.append("worker %d exited (code %s) before starting RizomUV: %s"
                                        % (wid, w.proc.returncode, w.stderr_tail()))
                was_ready = w.ready
                w.close()
                del pool[wid]
                if pending and was_ready and spawned < 2 * want:      # a crash, not a start failure: replace it
                    pool[spawned] = _Worker(spawned, argv, priority, events)
                    spawned += 1
                release_hold()
            elif w is not None and line.strip().startswith("{"):
                try:
                    msg = json.loads(line)
                except ValueError:
                    msg = {}
                ev = msg.get("event")
                if ev == "ready":
                    w.ready, w.info = True, msg
                    stats["workers"][wid] = {"port": msg.get("port"), "pid": msg.get("pid"),
                                             "rizomuv": msg.get("rizomuv"), "meshes": 0}
                    if holding[0]:
                        release_hold()
                    else:
                        feed(w)
                elif ev == "start_failed":
                    w.info["start_failed"] = True
                    start_errors.append("worker %d: %s" % (wid, msg.get("error")))
                    release_hold()
                elif ev == "result" and w.busy == msg.get("index"):
                    res = msg.get("result") or {"error": "empty result"}
                    if isinstance(res.get("worker"), dict):
                        res["worker"]["index"] = wid
                    if wid in stats["workers"]:
                        stats["workers"][wid]["meshes"] += 1
                    done(w.busy, res)
                    w.busy = None
                    feed(w)
            if timeout:                                               # stalled workers
                for w in list(pool.values()):
                    if w.busy is not None and time.time() - w.sent_at > timeout + stall_slack:
                        done(w.busy, {"error": "timed out: worker %d silent for %d s, killed" % (w.wid, time.time()
                                                                                                 - w.sent_at)})
                        w.busy = None
                        _kill(w.proc)
            if not pool:                                              # nobody left to do the rest
                why = "; ".join(start_errors[-3:]) or "every worker exited"
                for i in list(pending):
                    done(i, {"error": "no RizomUV worker could take this mesh: %s" % why})
                pending.clear()
        return results
    finally:
        for w in pool.values():
            w.close()
        owner.release()
        shutil.rmtree(tmp, ignore_errors=True)


def _dir_lock(path):
    """Hold an OS lock on <path>/owner.lock while the folder is in use (released by the OS if this host dies)."""
    lock = rl._PortLock(0)
    lock.path = os.path.join(path, "owner.lock")
    lock.acquire()
    return lock


def _remove_stale_dirs():
    """Delete pool folders left by a host that was killed (their owner lock is free); live ones keep theirs."""
    for d in glob.glob(os.path.join(tempfile.gettempdir(), "rizom_pool_*")):
        try:
            if not os.path.isdir(d) or time.time() - os.path.getmtime(d) < 60:   # a run that is just starting
                continue
        except OSError:
            continue
        lock = rl._PortLock(0)
        lock.path = os.path.join(d, "owner.lock")
        if lock.acquire():
            lock.release()
            shutil.rmtree(d, ignore_errors=True)


def _worker(job_path):
    """Worker side of unwrap_many: one RizomUV session, mesh indices on stdin, one JSON line per event on stdout."""
    proto = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    os.dup2(2, 1)                  # anything else printed (RizomUVLink, warnings) goes to stderr, not the protocol
    sys.stdout = sys.stderr

    def emit(obj):
        proto.write(json.dumps(_json_safe(obj)) + "\n")
        proto.flush()

    with open(job_path, encoding="utf-8") as fh:
        job = json.load(fh)
    try:
        ru.metrics()                              # numpy present: use the gate
        gated = True
    except ImportError:
        gated = False
    try:
        session = RizomSession(priority=job.get("priority"))
        session.start()
    except Exception as ex:  # noqa: BLE001
        emit({"event": "start_failed", "error": "%s: %s" % (type(ex).__name__, ex)})
        sys.exit(3)
    emit({"event": "ready", "port": session.port, "pid": session.pid, "rizomuv": session.version})
    try:
        while True:
            line = sys.stdin.readline().strip()
            if not line or line == "quit":
                break
            i = int(line)
            try:
                with open(os.path.join(job["dir"], "mesh_%d.json" % i), encoding="utf-8") as fh:
                    item = json.load(fh)
                mesh, kind, packs = item["mesh"], item["kind"], item["packs"]
                session.timed_out = False            # an earlier mesh's timeout is not this one's
                if not session.alive():
                    session.restart()
                with session.deadline(job.get("timeout")):
                    if gated:
                        r = ru.unwrap_gated(session.link, mesh, kind, packs, gate=job.get("gate"),
                                            time_budget=0.8 * job["timeout"] if job.get("timeout") else None)
                    else:
                        r = ru.unwrap_and_pack(session.link, mesh, kind, packs)
                r["worker"] = {"port": session.port, "pid": session.pid, "rizomuv": session.version}
            except Exception as ex:  # noqa: BLE001  (one bad mesh costs that mesh, not the worker)
                r = {"error": ("timed out; " if session.timed_out else "") + "%s: %s" % (type(ex).__name__, ex)}
                if session.timed_out or not session.alive() or isinstance(ex, session.CZEx):
                    try:
                        session.restart()
                    except Exception as rex:  # noqa: BLE001
                        emit({"event": "result", "index": i, "result": r})
                        emit({"event": "start_failed", "error": "restart failed: %s" % rex})
                        sys.exit(3)
            emit({"event": "result", "index": i, "result": r})
    finally:
        session.close()


# ----------------------------------------------------------------------------------------------- self-test
def _box(n_side=1):
    """A unit box, n_side x n_side quads per face; seed UVs = 3D positions, no seams."""
    verts, idx = [], {}

    def v(p):
        k = tuple(round(c, 9) for c in p)
        if k not in idx:
            idx[k] = len(verts)
            verts.append(k)
        return idx[k]
    sizes, ids = [], []
    for axis in range(3):
        for sign in (0.0, 1.0):
            for i in range(n_side):
                for j in range(n_side):
                    quad = []
                    for a, b in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)):
                        p = [0.0, 0.0, 0.0]
                        p[axis] = sign
                        p[(axis + 1) % 3], p[(axis + 2) % 3] = a / n_side, b / n_side
                        quad.append(v(p))
                    if sign == 0.0:
                        quad.reverse()
                    sizes.append(4)
                    ids += quad
    xyz = [c for p in verts for c in p]
    return {"sizes": sizes, "xyz_ids": ids, "xyz": xyz, "uvw_ids": list(ids), "uvw": list(xyz)}


def _selftest(workers):
    """Workers started at the same instant must each get their own instance (distinct ports and PIDs), and every
    mesh must come back with its own corner count from the instance of the worker that took it."""
    names = ["box%d" % (i + 1) for i in range(2 * max(1, workers))]
    meshes = {n: _box(i % 4 + 1) for i, n in enumerate(names)}
    t = time.perf_counter()
    stats = {}
    res = unwrap_many(meshes, kind="hard", workers=workers, timeout=120, stats=stats, start_together=True)
    ok = True
    for n in names:
        r = res[n]
        if "error" in r:
            print("  FAIL %s: %s" % (n, r["error"]))
            ok = False
            continue
        sent, back = len(meshes[n]["uvw_ids"]), len(r["packs"]["uv0"]["uvw_ids"])
        w = r["worker"]
        own = stats["workers"].get(w.get("index"), {})
        good = (sent == back and r["packs"]["uv0"]["fits"] and not r.get("gate_failures")
                and (own.get("port"), own.get("pid")) == (w["port"], w["pid"]))
        ok &= good
        print("  %s %s: corners sent %d, back %d, worker %s port %d pid %d, islands %d %s"
              % ("PASS" if good else "FAIL", n, sent, back, w.get("index"), w["port"], w["pid"], r["islands"],
                 r.get("gate_failures") or ""))
    ready = stats["workers"].values()
    ports, pids = {w["port"] for w in ready}, {w["pid"] for w in ready}
    distinct = len(ready) == workers and len(ports) == len(pids) == workers
    print("  %s %d workers started together, each on its own instance (%d ports, %d pids)%s"
          % ("PASS" if distinct else "FAIL", len(ready), len(ports), len(pids),
             ("; " + "; ".join(stats["start_errors"])) if stats["start_errors"] else ""))
    print("POOL SELFTEST", "PASSED" if ok and distinct else "FAILED", "in %.1f s" % (time.perf_counter() - t))
    return 0 if ok and distinct else 1


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--worker":
        _worker(sys.argv[2])
    elif len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        sys.exit(_selftest(int(sys.argv[2]) if len(sys.argv) > 2 else 3))
    else:
        print(__doc__)
