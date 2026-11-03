"""Bake mesh maps with Marmoset Toolbag from outside it: find toolbag.exe, write a job, run toolbag_job.py inside
Toolbag with -hide, wait for its result file, and check the files it wrote.

Measured with Toolbag 5.0.3.3 on Windows 11, RTX 3090 Ti, 2026-11-03 (references/baking.md, Route C):
- `toolbag.exe -hide <script.py> <args>` runs the script with sys.argv = ['toolbag', <args>...]; the launch returns
  before the script ends, so this waits on the result file the job writes; `mset.quit(code)` closes Toolbag.
  Inside Toolbag `__file__` is not defined: paths come in through argv. Toolbag needs a logged-in desktop session.
- Highs and lows go in as FBX (the kit export settings). A .glb is not read: the quick loader skips it and
  mset.importModel reports "not found". FBX textures do not arrive either: the job assigns each high material's
  texture files explicitly (job["textures"]).
- The cage offsets are in scene units, and an FBX scene is in centimetres: give metres here, the job converts. The
  automatic cage did not enclose 6 cm bumps on the 1 m test cube (they baked as crescents); 8 cm did.
- Normal maps come out OpenGL (Y+) with MikkT tangents, 16-bit PNGs as <outputPath stem>_<suffix>.png.

Host: plain Python 3.9+, standard library. Import as a module, or the command line:
    python toolbag_bake.py --low low.fbx --high high.fbx --out bake --name T_PROP_Crate_Free_A
        --maps normal,ao,curvature --size 2048 --cage 0.08 [--cage-in 0.08] [--ao-distance 0.2] [--samples 16]
        [--margin 16] [--texture Material_0:basecolor=high_basecolor.png] [--exe <toolbag.exe>] [--timeout 600]
    python toolbag_bake.py --probe        # is Toolbag usable here? prints its version
Toolbag's quick loader groups meshes by name: the low's FBX object must be <stem>_low and each high FBX (one object
per file) <stem>_high, with one stem. bake_maps.py --engine toolbag names them for you.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from bakers import MAP_SUFFIX  # noqa: E402  (one table of file suffixes for every baker)

JOB_SCRIPT = os.path.join(HERE, "toolbag_job.py")
DEFAULT_PATHS = (r"C:/Program Files/Marmoset/Toolbag 5/toolbag.exe",
                 r"C:/Program Files/Marmoset/Toolbag 4/toolbag.exe")

# Our map names -> Toolbag's default map suffix (BakerMap.suffix after resetSuffix(), measured on 5.0.3.3). The job
# picks maps by this suffix and renames the output to bakers.MAP_SUFFIX.
TOOLBAG_MAPS = {"normal": "normal", "ao": "ao", "curvature": "curve", "thickness": "thickness", "height": "height",
                "basecolor": "albedo", "roughness": "roughness", "metallic": "metalness"}
TEXTURE_MAPS = ("basecolor", "roughness", "metallic")    # textures a high material can carry into a transfer bake


def find_toolbag(paths=DEFAULT_PATHS, env=None):
    """toolbag.exe: the TOOLBAG_EXE environment variable, then PATH, then the default install folders; None when not
    found (then ask the user where Toolbag is)."""
    env = os.environ if env is None else env
    p = env.get("TOOLBAG_EXE")
    if p and os.path.isfile(p):
        return p
    hit = shutil.which("toolbag")
    if hit:
        return hit
    for p in paths:
        if os.path.isfile(p):
            return p
    return None


def _size(size):
    if isinstance(size, int):
        return size, size
    if isinstance(size, str):
        parts = size.lower().split("x")
        return (int(parts[0]), int(parts[-1]))
    w, h = size
    return int(w), int(h)


def build_job(low, highs, out_dir, name, maps=("normal", "ao", "curvature"), size=2048, bits=16, samples=16,
              margin=16, cage_out=None, cage_in=None, ao_distance=None, textures=None, ignore_backfaces=True):
    """A job dict for toolbag_job.py. low: the low-poly FBX (object named <stem>_low); highs: FBX files; cage_out and
    cage_in: how far rays start outside and reach inside the low, in metres (required: the automatic cage misses
    protruding detail); ao_distance: AO ray length in metres (None: Toolbag's unlimited); textures: {material name or
    "*": {"basecolor" | "roughness" | "metallic": png}} for a transfer bake. Raises ValueError on a bad job."""
    maps = tuple(maps)
    bad = [m for m in maps if m not in TOOLBAG_MAPS]
    if bad:
        raise ValueError("Toolbag route has no map %s (have %s)" % (", ".join(bad), ", ".join(TOOLBAG_MAPS)))
    if cage_out is None or cage_out <= 0:
        raise ValueError("cage_out (metres) is required: Toolbag's automatic cage does not enclose protruding detail")
    if bits not in (8, 16, 32):
        raise ValueError("bits must be 8, 16 or 32")
    highs = [highs] if isinstance(highs, str) else list(highs)
    if not highs:
        raise ValueError("no high-poly files")
    for p in [low] + highs:
        if not str(p).lower().endswith(".fbx"):
            raise ValueError("%s: Toolbag's bake route takes FBX (a .glb is not read)" % p)
    w, h = _size(size)
    tex = {}
    for mat, entry in (textures or {}).items():
        for m, p in entry.items():
            if m not in TEXTURE_MAPS:
                raise ValueError("texture %s for %s: only %s transfer" % (m, mat, ", ".join(TEXTURE_MAPS)))
            tex.setdefault(mat, {})[m] = os.path.abspath(p)
    return {"low": os.path.abspath(low), "highs": [os.path.abspath(p) for p in highs],
            "out_dir": os.path.abspath(out_dir), "name": name, "maps": list(maps),
            "toolbag_maps": {m: TOOLBAG_MAPS[m] for m in maps}, "suffixes": {m: MAP_SUFFIX[m] for m in maps},
            "width": w, "height": h, "bits": bits, "samples": int(samples), "margin": int(margin),
            "cage_out": float(cage_out), "cage_in": float(cage_out if cage_in is None else cage_in),
            "ao_distance": None if ao_distance is None else float(ao_distance), "textures": tex,
            "ignore_backfaces": bool(ignore_backfaces)}


def expected_paths(job):
    """{map: path} toolbag_job.py writes for a job."""
    return {m: os.path.join(job["out_dir"], "%s_%s.png" % (job["name"], job["suffixes"][m])) for m in job["maps"]}


def _launch(cmd):
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_job(job, exe=None, timeout=600, work_dir=None, launcher=None, poll=0.5):
    """Run one job in Toolbag and return its result dict ({"ok", "maps", "seconds", "version", "warnings", "error",
    "wall_seconds"}). launcher(cmd) starts the process (tests pass a fake). Raises RuntimeError when Toolbag is not
    found or the job reports an error, TimeoutError when no result arrives in `timeout` seconds."""
    exe = exe or find_toolbag()
    if launcher is None and not exe:
        raise RuntimeError("toolbag.exe not found: set TOOLBAG_EXE or pass exe")
    own = work_dir is None
    work_dir = work_dir or tempfile.mkdtemp(prefix="tbjob_")
    tag = uuid.uuid4().hex[:8]
    job_path = os.path.join(work_dir, "job_%s.json" % tag)
    res_path = os.path.join(work_dir, "result_%s.json" % tag)
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job, f, indent=1)
    if job.get("out_dir"):
        os.makedirs(job["out_dir"], exist_ok=True)
    cmd = [exe or "toolbag", "-hide", JOB_SCRIPT, job_path, res_path]
    t0 = time.time()
    (launcher or _launch)(cmd)
    res = None
    while time.time() - t0 < timeout:
        if os.path.isfile(res_path):
            try:
                with open(res_path, encoding="utf-8") as f:
                    res = json.load(f)
                break
            except ValueError:                        # written but not finished: the job renames it into place
                pass
        time.sleep(poll)
    if res is None:
        raise TimeoutError("no result from Toolbag after %ds (a licence or crash dialog? a locked session?); job %s"
                           % (timeout, job_path))
    res["wall_seconds"] = round(time.time() - t0, 2)
    if own:
        shutil.rmtree(work_dir, ignore_errors=True)
    if not res.get("ok"):
        raise RuntimeError("Toolbag job failed: %s" % (res.get("error") or "no detail"))
    return res


def probe(exe=None, timeout=90, launcher=None):
    """Run an empty job: returns Toolbag's version when a script ran in it (licence active, desktop session)."""
    res = run_job({"probe": True}, exe=exe, timeout=timeout, launcher=launcher)
    return res.get("version")


def bake(low, highs, out_dir, name, exe=None, timeout=600, **kw):
    """build_job + run_job; returns {map: path, "report": {...}} like bake_maps.bake()."""
    job = build_job(low, highs, out_dir, name, **kw)
    res = run_job(job, exe=exe, timeout=timeout)
    out = dict(res["maps"])
    out["report"] = {"baker": "toolbag", "version": res.get("version"), "seconds": res.get("seconds"),
                     "wall_seconds": res.get("wall_seconds"), "size": [job["width"], job["height"]],
                     "cage_out_m": job["cage_out"], "cage_in_m": job["cage_in"], "warnings": res.get("warnings", [])}
    return out


def _parse_textures(items):
    tex = {}
    for it in items or ():
        mat, _, rest = it.partition(":")
        m, _, path = rest.partition("=")
        if not (mat and m and path):
            raise ValueError("--texture wants MATERIAL:MAP=PATH, got %r" % it)
        tex.setdefault(mat, {})[m] = path
    return tex


def main(argv):
    ap = argparse.ArgumentParser(prog="toolbag_bake.py", description=__doc__.split("\n")[0])
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--low")
    ap.add_argument("--high", action="append")
    ap.add_argument("--out", default=".")
    ap.add_argument("--name")
    ap.add_argument("--maps", default="normal,ao,curvature")
    ap.add_argument("--size", default="2048")
    ap.add_argument("--bits", type=int, default=16)
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--margin", type=int, default=16)
    ap.add_argument("--cage", type=float, help="metres rays start outside the low")
    ap.add_argument("--cage-in", type=float, help="metres rays reach inside the low (default: --cage)")
    ap.add_argument("--ao-distance", type=float)
    ap.add_argument("--texture", action="append", help="MATERIAL:MAP=PATH (MATERIAL * for every high material)")
    ap.add_argument("--exe")
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args(argv)
    try:
        if a.probe:
            print("[toolbag] version %s" % probe(a.exe, timeout=a.timeout))
            return 0
        if not (a.low and a.high):
            ap.error("--low and --high are required (or --probe)")
        res = bake(a.low, a.high, a.out, a.name or os.path.splitext(os.path.basename(a.low))[0],
                   exe=a.exe, timeout=a.timeout, maps=[m.strip() for m in a.maps.split(",") if m.strip()],
                   size=a.size, bits=a.bits, samples=a.samples, margin=a.margin, cage_out=a.cage,
                   cage_in=a.cage_in, ao_distance=a.ao_distance, textures=_parse_textures(a.texture))
    except (ValueError, RuntimeError, TimeoutError) as ex:
        print("[toolbag] %s" % ex)
        return 1
    for m, p in res.items():
        if m != "report":
            print("[toolbag] %s -> %s" % (m, p))
    print("[toolbag] report %s" % json.dumps(res["report"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
