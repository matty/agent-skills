"""Which mesh-map baker to use, and the output gate every baker's maps pass.

Three bakers can bake mesh maps from a high poly (references/baking.md): Marmoset Toolbag (Route C,
toolbag_bake.py), the Substance 3D baker CLI (Route A, run by hand from the documented command) and Blender Cycles
(Route B, bake_maps.py). detect_bakers() probes which of them work on this machine, choose_baker() picks one for a
job, and check_outputs() is the gate their maps all pass, so a texture set baked by any of them is interchangeable:
the requested size, 16-bit normal and height maps, an OpenGL tangent-space normal map, and the T_<Piece>_<Map>.png
names.

The rule (references/baking.md, "Choosing a baker"):
1. detect what works, never assume it (a Toolbag install proves nothing until a script ran in it);
2. the project's choice wins when it fits the job (the world spec's tools.mesh_baker, the user's word over it);
   with none (or "auto"), MESH_BAKERS order: toolbag, substance, cycles;
3. the job filters first: an unattended run (no desktop session) cannot use Toolbag; a baker that lacks a map
   (or has not been measured for it) is skipped; thin parts prefer a baker with a native ignore-back-faces switch
   over Cycles' slow resolver when no baker was chosen;
4. one baker per texture set or atlas: a set already baked with one keeps it.

Host: plain Python 3.9+, standard library (check_outputs reads the normal map's convention with numpy when it is
installed and notes when it is not). Import as a module:
    import bakers
    available = bakers.detect_bakers()
    name, reason, order = bakers.choose_baker(("normal", "ao"), available, preference="toolbag")
    gate = bakers.check_outputs({"normal": "T_PROP_Crate_Free_A_Normal.png"}, (2048, 2048))
Command line (prints what works and what would be chosen):
    python bakers.py --maps normal,ao,basecolor [--prefer toolbag] [--unattended] [--thin-parts] [--no-probe]
"""

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

MESH_BAKERS = ("toolbag", "substance", "cycles")     # CANON mesh_bakers; the order is the default preference

# Maps each baker has been measured to produce (references/baking.md). The Substance baker's TextureTransfer is not
# measured, so a job that transfers a high's material never goes to it.
BAKER_MAPS = {
    "toolbag": frozenset(("normal", "ao", "curvature", "thickness", "height", "basecolor", "roughness", "metallic")),
    "substance": frozenset(("normal", "ao", "curvature", "thickness", "height")),
    "cycles": frozenset(("normal", "ao", "curvature", "basecolor", "roughness", "metallic")),
}
NEEDS_DESKTOP = frozenset(("toolbag",))              # a window, even with -hide; no service, scheduled task or SSH
NATIVE_BACKFACES = frozenset(("toolbag", "substance"))
DRIVEN = frozenset(("toolbag", "cycles"))            # bakers bake_maps.py --engine runs itself

# File suffixes, shared with bake_maps.py's MAP_SUFFIX: <name>_<Suffix>.png
MAP_SUFFIX = {"normal": "Normal", "ao": "AO", "curvature": "Curvature", "thickness": "Thickness",
              "height": "Height", "basecolor": "BaseColor", "roughness": "Roughness", "metallic": "Metallic"}
SIXTEEN_BIT = frozenset(("normal", "height"))

SUBSTANCE_DEFAULTS = (r"C:/Program Files/Adobe/Adobe Substance 3D Designer/substance3d_baker.exe",)


def _sibling(name):
    """Import a script from this folder (toolbag_bake, pbr_check) without leaving a __pycache__ in the skill."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        return __import__(name)
    finally:
        sys.dont_write_bytecode = keep


def _ok(entry):
    return bool(entry.get("ok")) if isinstance(entry, dict) else bool(entry)


def find_substance_baker(paths=SUBSTANCE_DEFAULTS):
    """The Substance 3D baker: on PATH first, then Designer's default install folder; None when not found."""
    hit = shutil.which("substance3d_baker")
    if hit:
        return hit
    for p in paths:
        if os.path.isfile(p):
            return p
    return None


def detect_bakers(probe_toolbag=True, toolbag_exe=None, substance_exe=None, run=subprocess.run, timeout=90):
    """{baker: {"ok": bool, "path": str or None, "detail": str}} for every baker in MESH_BAKERS. Toolbag counts only
    when a probe script ran inside it (licence active, desktop session present); probe_toolbag=False reports a found
    install as ok without running it (say so to the user). Cycles is Blender itself: always ok."""
    out = {}
    toolbag_bake = _sibling("toolbag_bake")
    exe = toolbag_exe or toolbag_bake.find_toolbag()
    if not exe:
        out["toolbag"] = {"ok": False, "path": None, "detail": "toolbag.exe not found (PATH, TOOLBAG_EXE, Program Files)"}
    elif not probe_toolbag:
        out["toolbag"] = {"ok": True, "path": exe, "detail": "found, not probed"}
    else:
        try:
            ver = toolbag_bake.probe(exe, timeout=timeout)
            out["toolbag"] = {"ok": True, "path": exe, "detail": "probe ran, version %s" % ver}
        except Exception as ex:                       # a licence dialog, no desktop, a crash: all mean "not usable"
            out["toolbag"] = {"ok": False, "path": exe, "detail": "probe failed: %s" % ex}
    sb = substance_exe or find_substance_baker()
    if not sb:
        out["substance"] = {"ok": False, "path": None, "detail": "substance3d_baker not found"}
    else:
        try:
            r = run([sb, "--help"], capture_output=True, timeout=timeout)
            out["substance"] = {"ok": r.returncode == 0, "path": sb, "detail": "--help exit %s" % r.returncode}
        except Exception as ex:
            out["substance"] = {"ok": False, "path": sb, "detail": "--help failed: %s" % ex}
    out["cycles"] = {"ok": True, "path": None, "detail": "Blender Cycles (always available)"}
    return out


def choose_baker(maps, available, preference=None, unattended=False, thin_parts=False, atlas_baker=None,
                 driven_only=False):
    """(baker, reason, order): the baker for a job, a one-line reason, and the full order to fall back along.
    maps: the maps the job needs; available: detect_bakers() output (or {name: bool}); preference: the project's
    choice (tools.mesh_baker) or None / "auto"; unattended: no desktop session; thin_parts: parts close to other
    surfaces; atlas_baker: the baker a texture set was already baked with; driven_only: only bakers bake_maps.py runs
    itself (toolbag, cycles). Raises ValueError when no baker fits, saying why each was dropped."""
    maps = set(maps)
    if preference in ("", "auto"):
        preference = None
    if preference is not None and preference not in MESH_BAKERS:
        raise ValueError("unknown baker %r (one of %s or auto)" % (preference, ", ".join(MESH_BAKERS)))
    dropped, cands = [], []
    for b in MESH_BAKERS:
        if not _ok(available.get(b, False)):
            dropped.append("%s: not available" % b)
        elif unattended and b in NEEDS_DESKTOP:
            dropped.append("%s: needs a desktop session" % b)
        elif not maps <= BAKER_MAPS[b]:
            dropped.append("%s: no %s" % (b, ", ".join(sorted(maps - BAKER_MAPS[b]))))
        elif driven_only and b not in DRIVEN:
            dropped.append("%s: not run by bake_maps.py (references/baking.md Route A)" % b)
        else:
            cands.append(b)
    if not cands:
        raise ValueError("no baker fits: " + "; ".join(dropped))
    if atlas_baker in cands:
        first, reason = atlas_baker, "texture set already baked with %s (one baker per set)" % atlas_baker
    elif preference in cands:
        first, reason = preference, "project baker (tools.mesh_baker: %s)" % preference
    elif thin_parts and any(b in NATIVE_BACKFACES for b in cands):
        first = next(b for b in cands if b in NATIVE_BACKFACES)
        reason = "thin parts: %s ignores back faces natively" % first
    else:
        first = cands[0]
        reason = "first available in the default order (%s)" % ", ".join(MESH_BAKERS)
    if preference is not None and preference not in cands:
        reason += "; %s dropped (%s)" % (preference, next(d.split(": ", 1)[1] for d in dropped
                                                          if d.startswith(preference + ":")))
    order = [first] + [b for b in cands if b != first]
    return first, reason, order


def _normal_convention(path):
    """("opengl" | "directx" | "unclear", r) via pbr_check.py, or (None, note) without numpy."""
    try:
        import numpy  # noqa: F401
    except ImportError:
        return None, "numpy not installed: convention not read"
    pbr_check = _sibling("pbr_check")
    px, _ = pbr_check.load(path)
    n = px[:, :, :3] * 2.0 - 1.0
    conv, r, _count = pbr_check.normal_convention(n)
    return conv, r


def check_outputs(paths, size, bits=16, convention=True):
    """The gate every baker's maps pass. paths {map: file}; size (width, height). Returns {"ok", "problems", "notes"}:
    a missing file, a size other than asked, a normal or height map under 16 bits (when bits is 16), a file name
    without its _<Suffix>, and a normal map read as DirectX (a flat or straight-groove map is "unclear": noted, not
    failed)."""
    pbr_check = _sibling("pbr_check")
    w, h = size
    problems, notes = [], []
    for m, p in sorted(paths.items()):
        if not p or not os.path.isfile(p):
            problems.append("%s: no file at %s" % (m, p))
            continue
        head = pbr_check.png_header(p)
        if head is None:
            problems.append("%s: %s is not a PNG" % (m, os.path.basename(p)))
            continue
        if (head[0], head[1]) != (w, h):
            problems.append("%s: %dx%d, asked %dx%d" % (m, head[0], head[1], w, h))
        if bits >= 16 and m in SIXTEEN_BIT and head[2] < 16:
            problems.append("%s: %d-bit, normal and height maps ship at 16" % (m, head[2]))
        suffix = MAP_SUFFIX.get(m)
        if suffix and not os.path.splitext(os.path.basename(p))[0].endswith("_" + suffix):
            problems.append("%s: %s does not end in _%s" % (m, os.path.basename(p), suffix))
        if m == "normal" and convention:
            conv, r = _normal_convention(p)
            if conv is None:
                notes.append("normal: %s" % r)
            elif conv == "directx":
                problems.append("normal: reads as DirectX (r %.2f); Blender and Unity need OpenGL" % r)
            elif conv == "unclear":
                notes.append("normal: convention unclear (r %.2f): too little curved detail to read" % r)
    return {"ok": not problems, "problems": problems, "notes": notes}


def main(argv):
    ap = argparse.ArgumentParser(prog="bakers.py", description=__doc__.split("\n")[0])
    ap.add_argument("--maps", default="normal,ao,curvature")
    ap.add_argument("--prefer", help="the project's baker (tools.mesh_baker): %s or auto" % ", ".join(MESH_BAKERS))
    ap.add_argument("--unattended", action="store_true", help="no desktop session (CI, a scheduled task, SSH)")
    ap.add_argument("--thin-parts", action="store_true")
    ap.add_argument("--no-probe", action="store_true", help="report a found Toolbag without running a script in it")
    a = ap.parse_args(argv)
    avail = detect_bakers(probe_toolbag=not a.no_probe)
    for b in MESH_BAKERS:
        print("[bakers] %-9s %s  %s" % (b, "ok  " if avail[b]["ok"] else "no  ", avail[b]["detail"]))
    try:
        name, reason, order = choose_baker([m.strip() for m in a.maps.split(",") if m.strip()], avail,
                                           preference=a.prefer, unattended=a.unattended, thin_parts=a.thin_parts)
    except ValueError as ex:
        print("[bakers] %s" % ex)
        return 1
    print("[bakers] use %s: %s (fallback order %s)" % (name, reason, " > ".join(order)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
