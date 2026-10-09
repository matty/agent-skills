"""Run RizomUV work in N separate processes at once, each with its own private RizomUV instance.

Host: any Python 3.6-3.13 that RizomUVLink supports (Blender's bundled python.exe works; numpy is needed for the
gate, and Blender's Python has it). No bpy.

    import rizom_pool as rp
    res = rp.unwrap_many({"crate": mesh_a, "urn": mesh_b}, kind="hard", workers=3,
                         packs={"uv0": rp.ru.pack_spec(1024, 8, 4), "uv2": rp.ru.pack_spec(128, 4, 2)})
    res["crate"]["packs"]["uv0"]["uvw_ids"], res["crate"]["packs"]["uv0"]["uvw"]

    rp.run_commands([[blender, "-b", "--factory-startup", f, "--python", job] for f in blend_files], workers=3)

    <python> rizom_pool.py --selftest 3        # three workers started at the same instant, each must get its own
                                              # mesh back from its own instance; exit 1 otherwise

Why processes and not threads: each worker opens one session (rizom_link claims a port with an OS lock for the
session's lifetime, starts its own rizomuv.exe and checks the instance answering is that child), so workers can
start at the same moment with no staggering. Threads also get separate sessions, but a stuck command blocks its
thread and Blender's Python is not built for it; processes are the supported pattern. Meshes travel to the
workers as JSON in a temporary folder. A worker restarts its instance after a crash or a per-mesh timeout and
carries on with the rest of its list. Each instance takes a licence token on a floating licence.
"""

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rizom_uv as ru  # noqa: E402
from rizom_link import RizomSession  # noqa: E402

_PRIORITY_FLAGS = {"normal": 0x20, "below_normal": 0x4000, "idle": 0x40}


def _popen_kw(priority):
    if os.name == "nt" and priority in _PRIORITY_FLAGS:
        return {"creationflags": _PRIORITY_FLAGS[priority]}
    return {}


def run_commands(commands, workers=4, timeout=None, priority=None, cwd=None):
    """Run command lines (lists) with at most `workers` at once. Returns [{"cmd", "exit", "seconds", "output"}]
    in input order; "exit" is "TIMEOUT" when a command ran past timeout seconds (it is killed)."""
    priority = priority or os.environ.get("RIZOMUV_PRIORITY") or "normal"
    pending = list(enumerate(commands))
    running, results = {}, [None] * len(commands)
    while pending or running:
        while pending and len(running) < workers:
            i, cmd = pending.pop(0)
            log = tempfile.TemporaryFile()
            p = subprocess.Popen(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 **_popen_kw(priority))
            running[i] = (p, log, time.time(), cmd)
        for i, (p, log, t0, cmd) in list(running.items()):
            code = p.poll()
            if code is None and timeout and time.time() - t0 > timeout:
                p.kill()
                p.wait()
                code = "TIMEOUT"
            if code is not None:
                log.seek(0)
                out = log.read().decode("utf-8", "replace")
                log.close()
                results[i] = {"cmd": cmd, "exit": code, "seconds": round(time.time() - t0, 2), "output": out[-4000:]}
                del running[i]
        time.sleep(0.05)
    return results


def unwrap_many(meshes, kind="hard", packs=None, workers=4, gate=None, timeout=600.0, python=None, priority=None):
    """Unwrap {name: mesh} in `workers` processes (round-robin split). Returns {name: result} where a result is
    rizom_uv.unwrap_gated's dict (unwrap_and_pack's when numpy is missing) plus "worker", or {"error": ...}."""
    names = list(meshes)
    workers = max(1, min(int(workers), len(names)))
    packs = packs or {"uv0": ru.pack_spec(1024, 8, 4)}
    tmp = tempfile.mkdtemp(prefix="rizom_pool_")
    try:
        cmds, outs = [], []
        for w in range(workers):
            chunk = names[w::workers]
            job = os.path.join(tmp, "job_%d.json" % w)
            out = os.path.join(tmp, "out_%d.json" % w)
            with open(job, "w", encoding="utf-8") as fh:
                json.dump({"kind": kind, "packs": packs, "gate": gate, "timeout": timeout, "priority": priority,
                           "worker": w, "meshes": {n: ru.normalise(meshes[n]) for n in chunk}}, fh)
            cmds.append([python or sys.executable, os.path.abspath(__file__), "--worker", job, out])
            outs.append(out)
        runs = run_commands(cmds, workers=workers, timeout=timeout * max(1, math.ceil(len(names) / workers)) + 120,
                            priority=priority)
        result = {}
        for w, (out, run) in enumerate(zip(outs, runs)):
            if os.path.isfile(out):
                with open(out, encoding="utf-8") as fh:
                    result.update(json.load(fh))
            for n in names[w::workers]:
                result.setdefault(n, {"error": "worker %d exited %s without a result: %s"
                                      % (w, run["exit"], run["output"][-600:])})
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _worker(job_path, out_path):
    with open(job_path, encoding="utf-8") as fh:
        job = json.load(fh)
    try:
        import uv_metrics  # noqa: F401  (numpy present: use the gate)
        gated = True
    except ImportError:
        gated = False
    session = RizomSession(priority=job.get("priority"))
    session.start()
    out = {}
    try:
        for name, mesh in job["meshes"].items():
            try:
                if not session.alive():
                    session.restart()
                with session.deadline(job.get("timeout")):
                    if gated:
                        r = ru.unwrap_gated(session.link, mesh, job["kind"], job["packs"], gate=job.get("gate"))
                    else:
                        r = ru.unwrap_and_pack(session.link, mesh, job["kind"], job["packs"])
                r["worker"] = {"index": job["worker"], "port": session.port, "pid": session.pid,
                               "rizomuv": session.version}
                out[name] = r
            except Exception as ex:  # noqa: BLE001  (one bad mesh costs that mesh, not the worker)
                out[name] = {"error": ("timed out; " if session.timed_out else "") + "%s: %s" % (type(ex).__name__, ex)}
                if session.timed_out or not session.alive() or isinstance(ex, session.CZEx):
                    session.restart()
    finally:
        session.close()
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(out, fh)


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
    meshes = {"box1": _box(1), "box2": _box(2), "box3": _box(3), "box4": _box(4)}
    names = list(meshes)[:max(1, workers)]
    t = time.perf_counter()
    res = unwrap_many({n: meshes[n] for n in names}, kind="hard", workers=workers, timeout=120)
    ok = True
    seen_ports, seen_pids = set(), set()
    for n in names:
        r = res[n]
        if "error" in r:
            print("  FAIL %s: %s" % (n, r["error"]))
            ok = False
            continue
        sent, back = len(meshes[n]["uvw_ids"]), len(r["packs"]["uv0"]["uvw_ids"])
        w = r["worker"]
        seen_ports.add(w["port"])
        seen_pids.add(w["pid"])
        good = sent == back and r["packs"]["uv0"]["fits"]
        ok &= good
        print("  %s %s: corners sent %d, back %d, worker %d port %d pid %d, islands %d"
              % ("PASS" if good else "FAIL", n, sent, back, w["index"], w["port"], w["pid"], r["islands"]))
    distinct = len(seen_ports) == len(names) and len(seen_pids) == len(names)
    print("  %s every worker had its own instance (%d ports, %d pids)" % ("PASS" if distinct else "FAIL",
                                                                        len(seen_ports), len(seen_pids)))
    print("POOL SELFTEST", "PASSED" if ok and distinct else "FAILED", "in %.1f s" % (time.perf_counter() - t))
    return 0 if ok and distinct else 1


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--worker":
        _worker(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        sys.exit(_selftest(int(sys.argv[2]) if len(sys.argv) > 2 else 3))
    else:
        print(__doc__)
