"""Validate a world spec (and optionally the pipeline ledger), and draw the ledger's task graph as Mermaid.

Host: plain Python 3.9+. Reads YAML with PyYAML if it is importable, otherwise only .json files; to get PyYAML
without touching the system Python:  python -m venv .venv && .venv/Scripts/pip install pyyaml  (or bin/pip).

    python spec_validate.py world/spec.yaml
    python spec_validate.py world/spec.yaml --ledger world/ledger.yaml [--mermaid world/diagrams/tasks.mmd]
    python spec_validate.py world/spec.yaml --root <project>      # also check that referenced files exist

Prints one line per finding, ERROR, WARN or NOTE, then a summary. Exit code 1 if there is any ERROR.
A spec with none of grid/families/budgets/pieces/zones is an intake-only spec (stage 0): only version, world and
tools are checked.
What it checks: required fields and types; piece, assembly, family and material names; piece sizes against the
grid; that every piece in an elevation, placement or assembly exists and every piece is used; zones, rooms and
openings (inside their bounds, human scale for VR); budgets against the platform targets; views; and for the
ledger, unique task ids, known dependencies, no cycles, and no two tasks that could run at once writing one file.
"""

import argparse
import json
import math
import os
import re
import sys

NAME_RE = re.compile(r"^([A-Z]{2,5})_[A-Za-z0-9]+_(\d+(?:x\d+){0,2}|Free)_[A-Z]\d?$")
ASM_RE = re.compile(r"^ASM_[A-Za-z0-9]+_[A-Z]\d?$")
FAMILY_RE = re.compile(r"^[A-Z]{2,5}$")

# Practical targets (the vrchat-world-optimization skill has the reasoning). Hard limit source, re-check it:
# https://creators.vrchat.com/platforms/android/quest-content-optimization/
PLATFORM_LIMITS = {
    "quest": {"world_tris": 250000, "view_tris": 100000, "materials": 25, "setpass": 50, "batches": 150,
              "texture_vram_mb": 150, "map_px": 1024, "lightmap_px": 1024},
    "pc": {"world_tris": 1000000, "view_tris": 300000, "materials": 60, "setpass": 150, "batches": 400,
           "texture_vram_mb": 1500, "map_px": 2048, "lightmap_px": 2048},
}
QUEST_DOWNLOAD_MB = 100      # hard limit
HUMAN = {"door_h": 2.1, "door_w": 1.0, "ceiling": 2.6}
TEXTURING = {"tiling", "trim", "atlas", "unique"}
STATUSES = {"todo", "running", "qa", "done", "failed", "escalated", "blocked", "skipped"}


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    if path.lower().endswith(".json"):
        return json.loads(text)
    try:
        import yaml
    except ImportError:
        sys.exit("PyYAML is not installed: make a venv and pip install pyyaml, or pass a .json file")
    return yaml.safe_load(text)


class Findings:
    def __init__(self):
        self.items = []

    def error(self, msg):
        self.items.append(("ERROR", msg))

    def warn(self, msg):
        self.items.append(("WARN", msg))

    def note(self, msg):
        self.items.append(("NOTE", msg))

    @property
    def errors(self):
        return sum(1 for k, _ in self.items if k == "ERROR")

    @property
    def warnings(self):
        return sum(1 for k, _ in self.items if k == "WARN")


def piece_extent(name, module, families):
    """(width along X, depth along Y, height along Z) in metres, from the name's Size token; None for Free."""
    m = NAME_RE.match(name)
    if not m or m.group(2) == "Free":
        return None
    nums = [int(t) * module for t in m.group(2).split("x")]
    thick = (families.get(m.group(1)) or {}).get("thickness", 0.1 * module)
    if len(nums) == 3:
        return tuple(nums)
    if len(nums) == 2:
        if m.group(1) == "STR":                       # floor-like: X by Y
            return (nums[0], nums[1], thick)
        return (nums[0], thick, nums[1])              # wall-like: X by Z
    return (nums[0], thick, thick)


def inside(inner, outer, tol=1e-6):
    return (outer[0] - tol <= inner[0] <= inner[2] <= outer[2] + tol
            and outer[1] - tol <= inner[1] <= inner[3] <= outer[3] + tol)


PLANNING_SECTIONS = ("grid", "families", "budgets", "pieces", "zones")


def check_spec(spec, f, root=None):
    for key in ("version", "world"):
        if key not in spec:
            f.error("missing top-level '%s'" % key)
    # Stage 0 writes only world and tools; the planning task fills the rest. Check what intake owns and stop,
    # rather than reporting every planning section as missing.
    intake_only = not any(key in spec for key in PLANNING_SECTIONS)
    if not intake_only:
        for key in PLANNING_SECTIONS:
            if key not in spec:
                f.error("missing top-level '%s'" % key)
    world = spec.get("world") or {}
    platforms = world.get("platforms") or []
    if not platforms or any(p not in PLATFORM_LIMITS for p in platforms):
        f.error("world.platforms must list pc and/or quest, got %r" % platforms)
    if world.get("scale", "full") not in ("full", "small"):
        f.error("world.scale must be full or small")
    if world.get("allow_generated_assets") not in (True, False):
        f.error("world.allow_generated_assets must be true or false (ask the user at intake)")
    tools = spec.get("tools") or {}
    if not tools.get("blender"):
        f.error("tools.blender (the Blender CLI path) is missing; find it at intake or ask the user")
    if not tools.get("unity_project"):
        f.warn("tools.unity_project is not set; stages 10-13 need it")
    if intake_only:
        f.note("intake-only spec (no %s yet): checked version, world and tools; the planning task fills the rest"
               % "/".join(PLANNING_SECTIONS))
        return
    module = (spec.get("grid") or {}).get("module")
    if not isinstance(module, (int, float)) or module <= 0:
        f.error("grid.module must be a positive number of metres")
        module = 1.0

    families = spec.get("families") or {}
    for code, fam in families.items():
        if not FAMILY_RE.match(code):
            f.error("family code %r must be 2-5 capitals" % code)
        fam = fam or {}
        mats = fam.get("materials") or []
        if not 1 <= len(mats) <= 3:
            f.warn("family %s has %d materials; aim for 1-3 per family" % (code, len(mats)))
        for mname in mats:
            if not re.match(r"^M_%s_[A-Za-z0-9]+$" % code, mname):
                f.error("material %s in family %s should be named M_%s_<Name>" % (mname, code, code))
        if fam.get("texturing") not in TEXTURING:
            f.error("family %s texturing must be one of %s" % (code, "/".join(sorted(TEXTURING))))
        if not fam.get("file", "").endswith(".blend"):
            f.error("family %s needs a KIT .blend file path" % code)
        for p in platforms:
            if fam.get("map_px", 0) > PLATFORM_LIMITS[p]["map_px"]:
                f.error("family %s map_px %s exceeds the %s maximum %d" % (code, fam.get("map_px"), p,
                                                                          PLATFORM_LIMITS[p]["map_px"]))

    pieces = {}
    for pc in spec.get("pieces") or []:
        name = pc.get("name", "")
        m = NAME_RE.match(name)
        if not m:
            f.error("piece %r does not follow <FAMILY>_<Type>_<Size>_<Variant>" % name)
            continue
        if name in pieces:
            f.error("piece %s listed twice" % name)
        if m.group(1) not in families:
            f.error("piece %s: family %s is not in families" % (name, m.group(1)))
        if pc.get("collision", "box") not in ("box", "mesh", "none"):
            f.error("piece %s: collision must be box, mesh or none" % name)
        pieces[name] = pc
    asms = {}
    for a in spec.get("assemblies") or []:
        name = a.get("name", "")
        if not ASM_RE.match(name):
            f.error("assembly %r does not follow ASM_<Name>_<Variant>" % name)
        for u in a.get("uses") or []:
            if u not in pieces:
                f.error("assembly %s uses unknown piece %s" % (name, u))
        if not (isinstance(a.get("size"), list) and len(a["size"]) == 3):
            f.warn("assembly %s has no size [x, y, z]; plans will draw it as a point" % name)
        asms[name] = a

    used = set()
    for a in asms.values():
        used.update(a.get("uses") or [])
    budgets = spec.get("budgets") or {}
    for key in ("world_tris", "view_tris", "materials", "setpass", "batches", "texture_vram_mb"):
        if key not in budgets:
            f.error("budgets.%s missing" % key)
    for p in platforms:
        lim = PLATFORM_LIMITS[p]
        for key in ("world_tris", "view_tris", "materials", "setpass", "batches", "texture_vram_mb"):
            if key in budgets and budgets[key] > lim[key]:
                f.error("budgets.%s = %s is looser than the %s target %s" % (key, budgets[key], p, lim[key]))
        lm = (budgets.get("lightmap") or {}).get("max_px", 0)
        if lm > lim["lightmap_px"]:
            f.error("budgets.lightmap.max_px %s exceeds the %s target %d" % (lm, p, lim["lightmap_px"]))
    if "quest" in platforms:
        dl = (budgets.get("download_mb") or {}).get("quest")
        if dl is None:
            f.error("budgets.download_mb.quest missing (quest is in world.platforms; hard limit %d MB)"
                    % QUEST_DOWNLOAD_MB)
        elif dl > QUEST_DOWNLOAD_MB:
            f.error("budgets.download_mb.quest = %s is over the %d MB hard limit" % (dl, QUEST_DOWNLOAD_MB))
    piece_tris = budgets.get("piece_tris") or {}
    for code in families:
        if code not in piece_tris:
            f.warn("budgets.piece_tris has no entry for family %s" % code)

    zone_ids = set()
    for z in spec.get("zones") or []:
        zid = z.get("id")
        if not zid or zid in zone_ids:
            f.error("zone id %r missing or duplicated" % zid)
        zone_ids.add(zid)
        b = z.get("bounds")
        if not (isinstance(b, list) and len(b) == 4 and b[0] < b[2] and b[1] < b[3]):
            f.error("zone %s bounds must be [x0, y0, x1, y1] with x0 < x1, y0 < y1" % zid)
            continue
        for pl in z.get("placements") or []:
            ref = pl.get("ref")
            if ref not in pieces and ref not in asms:
                f.error("zone %s places unknown %s" % (zid, ref))
            used.add(ref)
            pos = pl.get("pos") or [0, 0, 0]
            if not (b[0] <= pos[0] <= b[2] and b[1] <= pos[1] <= b[3]):
                f.warn("zone %s: %s placed at %s, outside the zone" % (zid, ref, pos[:2]))
            if ref in pieces and not NAME_RE.match(ref).group(2) == "Free":
                if abs(pl.get("rot", 0)) % 90 > 1e-6:
                    f.warn("zone %s: grid piece %s rotated %s deg (not a multiple of 90)" % (zid, ref, pl.get("rot")))
                if any(abs(v / module - round(v / module)) > 1e-6 for v in pos[:2]):
                    f.warn("zone %s: grid piece %s at %s is off the %s m grid" % (zid, ref, pos[:2], module))
        for r in z.get("rooms") or []:
            rb = r.get("bounds")
            if not (isinstance(rb, list) and len(rb) == 4):
                f.error("room %s/%s needs bounds" % (zid, r.get("id")))
                continue
            if not inside(rb, b):
                f.error("room %s/%s lies outside its zone" % (zid, r.get("id")))
            if r.get("height", 99) < HUMAN["ceiling"]:
                f.error("room %s/%s ceiling %s m is under %s m" % (zid, r.get("id"), r.get("height"),
                                                                 HUMAN["ceiling"]))
            for o in r.get("openings") or []:
                if o.get("type") == "door":
                    if o.get("height", 0) < HUMAN["door_h"] or o.get("width", 0) < HUMAN["door_w"]:
                        f.error("room %s/%s door %sx%s m is smaller than %sx%s m"
                                % (zid, r.get("id"), o.get("width"), o.get("height"), HUMAN["door_w"],
                                   HUMAN["door_h"]))
                at = o.get("at") or [0, 0]
                if not (rb[0] - 0.5 <= at[0] <= rb[2] + 0.5 and rb[1] - 0.5 <= at[1] <= rb[3] + 0.5):
                    f.error("room %s/%s opening at %s is not on the room's edge" % (zid, r.get("id"), at))

    for e in spec.get("elevations") or []:
        if e.get("zone") not in zone_ids:
            f.error("elevation %s: unknown zone %s" % (e.get("id"), e.get("zone")))
        if e.get("facing") not in ("north", "south", "east", "west"):
            f.error("elevation %s: facing must be north, south, east or west" % e.get("id"))
        widths = []
        for ci, course in enumerate(e.get("courses") or []):
            w = 0.0
            for name in course:
                used.add(name)
                if name not in pieces:
                    f.error("elevation %s course %d: unknown piece %s" % (e.get("id"), ci, name))
                    continue
                ext = piece_extent(name, module, families)
                if ext is None:
                    f.error("elevation %s: %s is Free; elevations take grid pieces only" % (e.get("id"), name))
                    continue
                w += ext[0]
            widths.append(w)
        if len(set(round(w, 6) for w in widths)) > 1:
            f.warn("elevation %s: courses have different widths %s m" % (e.get("id"), widths))

    for name in pieces:
        if name not in used:
            f.warn("piece %s is never placed, used in an assembly or shown in an elevation" % name)

    for v in spec.get("views") or []:
        for key in ("id", "pos", "target"):
            if key not in v:
                f.error("view %r missing %s" % (v.get("id"), key))
        if root and v.get("matches") and not os.path.exists(os.path.join(root, v["matches"])):
            f.warn("view %s: %s does not exist yet" % (v.get("id"), v["matches"]))
    if world.get("mockups") and not spec.get("views"):
        f.warn("mockups are on but no views are defined to compare them against")
    check_lightmap(spec, pieces, module, families, f)
    return pieces, asms


LIGHTMAP_COVERAGE = 0.85    # share of a renderer's UV2 square its charts fill: measured 2026-10-16 (walls 2x3x0.2 m
                            # got 243 px at 60 texels/m, 113 px at 28; formula with 0.85 gives 243 and 114)
LIGHTMAP_PACK = 0.75        # share of a lightmap that per-renderer rectangles fill before Unity spills to a second
                            # map: measured 2026-10-16 at about 0.78 (16 renderers in one 512 map, Unity 2022.3,
                            # no rotation)


def lightmap_footprints(spec, pieces, module, families):
    """{piece: footprint side in lightmap pixels} for each lightmapped grid piece, from budgets.lightmap.texels_per_m:
    Unity gives each renderer a square of about texels_per_m x sqrt(surface area / coverage) pixels."""
    tpm = ((spec.get("budgets") or {}).get("lightmap") or {}).get("texels_per_m")
    out = {}
    if not tpm:
        return out
    for name, pc in pieces.items():
        if pc.get("lightmap") is False:
            continue                                   # probe-lit
        ext = piece_extent(name, module, families) or pc.get("size")
        if not ext:
            continue
        x, y, z = ext
        area = 2 * (x * y + y * z + x * z)
        out[name] = tpm * math.sqrt(area / LIGHTMAP_COVERAGE)
    return out


def check_lightmap(spec, pieces, module, families, f):
    """Do the placed lightmapped pieces fit budgets.lightmap at its texels_per_m, each with room for its UV2 padding?"""
    lm = (spec.get("budgets") or {}).get("lightmap") or {}
    tpm = lm.get("texels_per_m")
    if not tpm:
        f.warn("budgets.lightmap.texels_per_m missing: without it nobody can check that the placed pieces fit the "
               "lightmap budget, or size each piece's UV2 padding (stage 6) for the footprint it will get")
        return
    side = lightmap_footprints(spec, pieces, module, families)
    counts = {}
    for z in spec.get("zones") or []:
        for pl in z.get("placements") or []:
            if pl.get("ref") in side:
                counts[pl["ref"]] = counts.get(pl["ref"], 0) + 1
    need = sum(side[n] ** 2 * c for n, c in counts.items())
    have = (lm.get("max_px") or 0) ** 2 * (lm.get("count") or 1) * LIGHTMAP_PACK
    if have and need > have:
        f.error("lightmaps: the placed lightmapped pieces need about %d px^2 at %g texels/m, the budget gives %d "
                "(%s x %s px): lower texels_per_m, raise the budget, or make small pieces probe-lit (lightmap: false)"
                % (need, tpm, have, lm.get("count", 1), lm.get("max_px")))
    small = lm.get("min_footprint_px", 64)
    for n in sorted(counts):
        if side[n] < small:
            f.warn("piece %s gets about %d lightmap px at %g texels/m (< %d): make it probe-lit (lightmap: false) or "
                   "plan its UV2 padding for it" % (n, side[n], tpm, small))


def _reachable(graph, start):
    seen, stack = set(), [start]
    while stack:
        for nxt in graph.get(stack.pop(), []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


# Where a task may write: the project layout's top folders, the Unity project's Assets and ProjectSettings, and the
# live editors.
WRITE_ROOTS = ("world/", "blender/", "export/", "assets/", "projectsettings/", "@")


def _norm(path):
    p = path.replace("\\", "/").strip().lower()
    while p.startswith("./"):
        p = p[2:]
    return p


def _shared_writes(wa, wb):
    """Paths two tasks both write: the same path, or a folder (trailing /) that holds the other's path."""
    shared = set()
    for a in wa:
        for b in wb:
            na, nb = _norm(a), _norm(b)
            if (na == nb or (na.endswith("/") and nb.startswith(na))
                    or (nb.endswith("/") and na.startswith(nb))):
                shared.add(a if len(na) <= len(nb) else b)
    return shared


def check_ledger(ledger, f):
    tasks = ledger.get("tasks") or []
    gates = ledger.get("gates") or {}
    ids = {}
    for t in tasks:
        tid = t.get("id")
        if not tid or tid in ids:
            f.error("task id %r missing or duplicated" % tid)
            continue
        ids[tid] = t
        for key in ("stage", "role", "status"):
            if key not in t:
                f.error("task %s missing %s" % (tid, key))
        if t.get("status") not in STATUSES:
            f.error("task %s status %r not one of %s" % (tid, t.get("status"), "/".join(sorted(STATUSES))))
        if t.get("role") != "qa" and not t.get("qa", True):
            f.warn("task %s has qa: false; every build task should get a QA pass" % tid)
    deps = {}
    for tid, t in ids.items():
        deps[tid] = []
        for d in t.get("deps") or []:
            if d.startswith("gate:"):
                if d[5:] not in gates:
                    f.error("task %s depends on unknown gate %s" % (tid, d))
                else:
                    # A gate opens only after its `after` tasks, so depending on it orders the task after them.
                    deps[tid].extend(a for a in (gates[d[5:]] or {}).get("after") or [] if a in ids)
            elif d not in ids:
                f.error("task %s depends on unknown task %s" % (tid, d))
            else:
                deps[tid].append(d)
    for g, gv in gates.items():
        for d in (gv or {}).get("after") or []:
            if d not in ids:
                f.note("gate %s waits on %s, which is not in the ledger yet" % (g, d))
    for tid in ids:
        if tid in _reachable(deps, tid):
            f.error("dependency cycle through task %s" % tid)
    for tid, t in ids.items():
        for w in t.get("writes") or []:
            if not _norm(w).startswith(WRITE_ROOTS):
                f.warn("task %s writes %s, outside the project layout (%s)" % (tid, w, ", ".join(WRITE_ROOTS)))
    order = sorted(ids)
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            shared = _shared_writes(ids[a].get("writes") or [], ids[b].get("writes") or [])
            if shared and a not in _reachable(deps, b) and b not in _reachable(deps, a):
                f.error("tasks %s and %s can run at once and both write %s (one writer per file: add a dependency)"
                        % (a, b, ", ".join(sorted(shared))))
    return ids, deps


def mermaid(ledger):
    colour = {"done": "#2e7d32", "running": "#1565c0", "qa": "#6a1b9a", "failed": "#c62828",
              "escalated": "#c62828", "blocked": "#ef6c00", "todo": "#616161", "skipped": "#9e9e9e"}
    lines = ["flowchart TD"]
    for g, gv in (ledger.get("gates") or {}).items():
        st = (gv or {}).get("status", "pending")
        lines.append('  gate_%s{{"GATE %s<br/>%s"}}' % (g, g, st))
        lines.append("  style gate_%s fill:%s,color:#fff" % (g, "#2e7d32" if st == "approved" else "#ef6c00"))
    for t in ledger.get("tasks") or []:
        nid = re.sub(r"\W", "_", t["id"])
        lines.append('  %s["%s<br/>S%s %s<br/>%s"]' % (nid, t["id"], t.get("stage", "?"), t.get("role", ""),
                                                       t.get("status", "")))
        lines.append("  style %s fill:%s,color:#fff" % (nid, colour.get(t.get("status"), "#616161")))
        for d in t.get("deps") or []:
            src = "gate_" + d[5:] if d.startswith("gate:") else re.sub(r"\W", "_", d)
            lines.append("  %s --> %s" % (src, nid))
    for g, gv in (ledger.get("gates") or {}).items():
        for d in (gv or {}).get("after") or []:
            lines.append("  %s --> gate_%s" % (re.sub(r"\W", "_", d), g))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec")
    ap.add_argument("--ledger")
    ap.add_argument("--mermaid", help="write the ledger's task graph here")
    ap.add_argument("--root", help="project folder, to check referenced files exist")
    a = ap.parse_args()
    f = Findings()
    check_spec(load(a.spec), f, a.root)
    if a.ledger:
        ledger = load(a.ledger)
        check_ledger(ledger, f)
        if a.mermaid:
            os.makedirs(os.path.dirname(os.path.abspath(a.mermaid)), exist_ok=True)
            with open(a.mermaid, "w", encoding="utf-8") as out:
                out.write(mermaid(ledger))
            print("wrote %s" % a.mermaid)
    for kind, msg in f.items:
        print("%-5s %s" % (kind, msg))
    print("%d error(s), %d warning(s)" % (f.errors, f.warnings))
    sys.exit(1 if f.errors else 0)


if __name__ == "__main__":
    main()
