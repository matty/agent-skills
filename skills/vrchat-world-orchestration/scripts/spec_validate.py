"""Validate a world spec (and optionally the pipeline ledger), report lightmap footprints, and draw the ledger's
task graph as Mermaid.

Host: plain Python 3.9+. Reads YAML with PyYAML if it is importable, otherwise only .json files; to get PyYAML
without touching the system Python:  python -m venv .venv && .venv/Scripts/pip install pyyaml  (or bin/pip).

Run from the world folder (the one holding world/, blender/ and export/), with this script's full path:

    python spec_validate.py world/spec.yaml
    python spec_validate.py world/spec.yaml --footprints [world/diagrams/lightmap_budget.txt]
    python spec_validate.py world/spec.yaml --ledger world/ledger.yaml [--mermaid world/diagrams/tasks.mmd]
    python spec_validate.py world/spec.yaml --ledger world/ledger.yaml --draft world/briefs/draft-tasks.yaml
    python spec_validate.py world/spec.yaml --root .        # also check that each view's mockup image exists

Prints one line per finding, ERROR, WARN or NOTE, then a summary. Exit code 1 if there is any ERROR.
A spec with none of grid/families/pieces/zones is an intake-only spec (stage 0): only version, world, tools and the
template's budget ceilings are checked.

What it checks:
  - required sections and fields, the allowed values of every enumerated field, and the type of every value (a
    wrong type is an ERROR naming the field, never a traceback); unknown keys are warned with the nearest known one
    (zones[].lighting_state: did you mean lighting_states?);
  - piece, assembly, family and material names (M_TRIM_ materials allowed in any family); everything lives in one
    blender/MASTER.blend, so a family or assembly `file` other than that (a split KIT or ASM file) is an ERROR and
    one naming MASTER a NOTE (no longer needed); with --ledger, no task writes blender/kits/ or blender/asm/ and the
    ledger records no other intake.blend_layout;
  - piece sizes against the grid (a one-number Size needs `size`); grid.sub_module divides grid.module; grid
    placements on the module (TRIM on the sub-module) in 90-degree turns; every piece in an elevation, placement or
    assembly exists and every piece is used; assemblies that are never placed, and pieces that appear only in an
    elevation (never placed), are warned;
  - zones, rooms, openings and mirror slots (inside their bounds, openings along a room edge, human scale for VR);
  - budgets against the platform targets (pc, quest = the Android build, ios; ios uses the Quest limits and, in a
    per-platform budget, falls back to the quest value); family map_px against the PC maximum (mobile sizes come
    from the Android and iOS import overrides);
  - lightmap capacity: Unity packs each renderer's UV2 chart box, so a lightmapped piece costs
    (texels_per_m x lightmap_scale)^2 x area px^2 whatever its UV2 layout, plus 0.25^n of that for each lightmapped
    LODn; the costs x placements (directly in zones and inside placed assemblies) x the zone's lighting_states are
    summed against budgets.lightmap: warn above 0.65 of the maps' area, error above 0.80. Each piece's footprint,
    texels_per_m x sqrt(area / b) x lightmap_scale px per UV unit with b = 0.85 (the UV2 chart box share, planning
    estimate), sets its UV2 gaps and the 64 px rule: under 64 px a Free PROP or FOL piece (PROBE_LIT_FAMILIES) counts
    as probe-lit (left out, and warned) unless its zone has lighting states; any other piece still counts and gets a
    NOTE. With lighting.baker: bakery the footprint and cost are Bakery's (read from its scripts, not yet measured
    in a bake): a rect of side texels_per_m x sqrt(2 x area x lightmap_scale), costing its square for square UV2
    bounds (twice Progressive's at scale 1, linear in the scale), each lightmapped LOD at its own area, and a footprint
    of (that side - 6) / sqrt(b). --footprints prints each piece's cost, footprint, copies and the fill, for the
    lighting brief; it plans the fill only (stage 6 sizes UV2 gaps from each modelled mesh's real area);
  - lighting states: zones naming one `switch` need the same lighting_states; NOTEs for a probe-lit piece in a zone
    with them (it keeps one state), and for a wall, facade or openings such a zone shares with a zone on another
    switch (or none) on the same storey (a switch changes the light in its zones only);
  - views, interactivity and lighting; world.quality (pc_lead or parity; a NOTE when a pc_lead world gives PC no
    budget of its own); the look section (references, wear, lighting_mood, quality_bar, lead_family, per-material
    albedo_srgb, roughness and metal targets for QA X5 and X8) and each piece's ref and detail list; with --root,
    every reference image exists;
  - with --ledger: unique task ids, known dependencies and gates, no cycles, writes inside the project layout, no
    two tasks that could run at once writing one file (a folder overlaps every file inside it), every task of
    stage 4 or later ordered after gate:spec (stage 5 or later: after gate:greybox; stage 9 or later and every
    texture task but the lead family's and T-TEX-TRIM-LAYOUT: after gate:look), and a warning for a task
    running while a gate it waits for is not approved (except the gate's `reopened_by` task): one already running
    when the gate re-opened finishes, one whose session died goes back to todo. --draft merges a draft task list (a
    bare list, or {tasks: [...]}) into the ledger's tasks first; a draft task replaces the ledger task with the same
    id.
"""

import argparse
import difflib
import json
import math
import os
import re
import sys

NAME_RE = re.compile(r"^([A-Z]{2,5})_[A-Za-z0-9]+_(\d+(?:x\d+){0,2}|Free)_[A-Z]\d?$")
ASM_RE = re.compile(r"^ASM_[A-Za-z0-9]+_[A-Z]\d?$")
FAMILY_RE = re.compile(r"^[A-Z]{2,5}$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")                      # zone and elevation ids name files (plan_<id>.svg)
MAT_RE = re.compile(r"^M_[A-Z]{2,5}_[A-Za-z0-9][A-Za-z0-9_]*$")    # the name part may hold underscores

# Practical targets (the vrchat-world-optimization skill has the reasoning). Hard limit source, re-check it:
# https://creators.vrchat.com/platforms/android/quest-content-optimization/
PLATFORM_LIMITS = {
    "quest": {"world_tris": 250000, "view_tris": 100000, "materials": 25, "setpass": 50, "batches": 150,
              "texture_vram_mb": 150, "map_px": 1024, "lightmap_px": 1024},
    "pc": {"world_tris": 1000000, "view_tris": 300000, "materials": 60, "setpass": 150, "batches": 400,
           "texture_vram_mb": 1500, "map_px": 2048, "lightmap_px": 2048},
}
# Mobile is Android and iOS: "Guidelines that refer to 'Android' or 'Quest' apply to iOS, too"
# (https://creators.vrchat.com/platforms/iOS/, checked 2026-10-17). `quest` is the Android build.
PLATFORM_LIMITS["ios"] = PLATFORM_LIMITS["quest"]
MOBILE = ("quest", "ios")
QUEST_DOWNLOAD_MB = 100      # hard limit for every mobile build (Android and iOS); VRChat's MB is 2^20 bytes
PC_DOWNLOAD_MB = 200         # not an SDK limit: VRChat asks public worlds to "Try to keep your worlds under 200MB"
                             # (https://creators.vrchat.com/worlds/submitting-a-world-to-be-made-public)
BUDGET_KEYS = ("world_tris", "view_tris", "materials", "setpass", "batches", "texture_vram_mb")
HUMAN = {"door_h": 2.1, "door_w": 1.0, "ceiling": 2.6}
TEXTURING = {"tiling", "trim", "atlas", "unique"}
COLLISION = {"box", "mesh", "none"}
ZONE_KINDS = {"exterior", "interior"}
FACINGS = {"north", "south", "east", "west"}
SYNC = {"none", "manual", "continuous"}
BAKERS = {"progressive", "bakery"}
LIGHT_MODES = {"baked", "mixed"}
QUALITY = {"pc_lead", "parity"}       # world.quality: PC gets its own budgets and sources, or ships what mobile ships
WEAR = {"pristine", "lived-in", "weathered", "derelict"}
ALBEDO_SRGB = (30, 240)              # the dielectric base-colour range QA X8 holds every map to (pbr_check.py)
STATUSES = {"todo", "running", "qa", "done", "failed", "escalated", "blocked", "skipped"}
GATE_STATUSES = {"pending", "approved", "changes-requested"}

# Lightmap planning (vrchat-lighting-and-baking owns these numbers):
LIGHTMAP_COVERAGE = 0.85     # b, the UV2 chart box's share of the 0-1 tile, planning estimate. Unity's footprint
                             # (texels per UV unit, which sizes UV2 gaps) is texels_per_m x sqrt(A / b) x Scale In
                             # Lightmap: b 0.79-0.95 measured on the dry run's five renderers, within 0.6% (Unity
                             # 2022.3.22f1, 2026-10-16; the 2 x 3 x 0.2 m wall: b 0.850, 242.8 px). It sets no atlas
                             # cost: Unity packs the chart box, (texels_per_m x Scale In Lightmap)^2 x A px^2 whatever
                             # b is (measured 2026-10-17). UV2 gaps are packed at the worst case b = 1, at stage 6.
LIGHTMAP_PLAN = 0.65         # plan sum(cost x copies x states) <= 0.65 x the maps' area (below every measured spill):
                             # warn above
LIGHTMAP_MAX = 0.80          # error above: a spill to another map is likely. At Lightmap Padding 2 (Unity 2022.3.22f1,
                             # measured 2026-10-17), kit-like mixed sets spilled at 0.79-0.90 of box fill (mean 0.85)
                             # and equal full-tile squares only at 0.97; a larger padding lowers every spill
LOD_COST = 0.25              # LODn gets its own atlas space at texel scale 0.5^n, so it costs 0.25^n of its area
                             # (Unity 2022.3.22f1, measured 2026-10-17: scale 0.995 / 0.492 / 0.250 for LOD0-2)
BAKERY_AREA_FACTOR = 2.0     # lighting.baker bakery (Bakery's ftBuildGraphics.cs as installed in a Unity 2022.3.22f1
BAKERY_INSET_TEXELS = 3      # project, read 2026-10-24, measured in a bake 2026-10-27): a renderer's rect has side
                             # texels_per_m x sqrt(2 x A x Scale In Lightmap) on its UV2 bounds' short side and costs
                             # side^2 x the bounds' aspect (1 to plan), each LOD at its own area with no LOD factor;
                             # the Default atlas packer insets the rect 3 texels on every side
COST_FORMULA = {"progressive": "(texels_per_m x lightmap_scale)^2 x area",
                "bakery": "2 x area x lightmap_scale x texels_per_m^2 (Bakery, square UV2 bounds)"}
MIN_FOOTPRINT_PX = 64        # a Free PROP or FOL piece under it is probe-lit (Receive Global Illumination: Light
                             # Probes) unless its zone has lighting states; any other piece under it only gets a NOTE
                             # (it stays lightmapped)


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


def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def valid_size(size):
    return isinstance(size, list) and len(size) == 3 and all(number(v) and v > 0 for v in size)


def piece_extent(name, module, families, size=None):
    """(width along X, depth along Y, height along Z) in metres, from the name's Size token; None for Free. A one-number
    Size (EXT_Pillar_3_A) could be a post or a beam, so its extents come from the piece's `size` (None without one)."""
    m = NAME_RE.match(name)
    if not m or m.group(2) == "Free":
        return None
    nums = [int(t) * module for t in m.group(2).split("x")]
    if len(nums) == 1:
        return tuple(float(v) for v in size) if valid_size(size) else None
    fam = families.get(m.group(1)) if isinstance(families, dict) else None
    thick = fam.get("thickness") if isinstance(fam, dict) else None
    if not (number(thick) and thick > 0):
        thick = 0.1 * module                          # (the validator reports a wrong thickness)
    if len(nums) == 3:
        return tuple(nums)
    if len(nums) == 2:
        if m.group(1) == "STR":                       # floor-like: X by Y
            return (nums[0], nums[1], thick)
        return (nums[0], thick, nums[1])              # wall-like: X by Z


def piece_size(name, pc, module, families):
    """(x, y, z) metres: from the Size token for grid pieces (from `size` for a one-number Size), from `size` for Free
    pieces; None without one."""
    size = (pc or {}).get("size")
    ext = piece_extent(name, module, families, size)
    if ext:
        return ext
    return tuple(float(v) for v in size) if is_free(name) and valid_size(size) else None


def box_area(size):
    x, y, z = size
    return 2 * (x * y + y * z + x * z)


def footprint_px(size, texels_per_m, scale=1.0, baker="progressive"):
    """Side of the square a renderer gets in its lightmap per UV unit, for planning, the bounding box's surface standing
    in for the mesh's surface area A. Progressive: texels_per_m x sqrt(A / b) x Scale In Lightmap with b = 0.85.
    Bakery: (texels_per_m x sqrt(2 x A x Scale In Lightmap) - 6) / sqrt(b), its rect less the Default packer's inset
    over square UV2 bounds of that share."""
    if baker == "bakery":
        side = texels_per_m * math.sqrt(BAKERY_AREA_FACTOR * box_area(size) * scale)
        return max(side - 2.0 * BAKERY_INSET_TEXELS, 0.0) / math.sqrt(LIGHTMAP_COVERAGE)
    return texels_per_m * math.sqrt(box_area(size) / LIGHTMAP_COVERAGE) * scale


def box_cost(size, texels_per_m, scale=1.0, baker="progressive"):
    """Atlas cost of one renderer in px^2, the bounding box's surface standing in for A when planning. Progressive:
    Unity packs each renderer's UV2 chart box, whose area is (texels_per_m x Scale In Lightmap)^2 x A whatever the UV2
    layout (Unity 2022.3.22f1, measured 2026-10-17: 24,002 against 24,000 px^2). Bakery: its rect, 2 x A x Scale In
    Lightmap x texels_per_m^2 for square UV2 bounds (oblong bounds cost x their aspect)."""
    if baker == "bakery":
        return BAKERY_AREA_FACTOR * box_area(size) * scale * texels_per_m ** 2
    return (texels_per_m * scale) ** 2 * box_area(size)


def lod_side(level, baker="progressive"):
    """LODn's lightmap texel scale over LOD0's: 0.5^n under Progressive; Bakery sizes each LOD by its own area."""
    return 1.0 if baker == "bakery" else 0.5 ** level


def lod_levels(pc):
    """The LOD levels of a piece that take lightmap space: LOD0, plus LOD1+ unless `lod_lightmap: false` makes them
    probe-lit (which takes them out of the atlas)."""
    lods = pc.get("lods", 0)
    if pc.get("lod_lightmap", True) is False or not (isinstance(lods, int) and not isinstance(lods, bool)
                                                     and lods > 0):
        return [0]
    return list(range(lods + 1))


def lod_factor(pc, baker="progressive"):
    """A piece's atlas cost over its LOD0's: each lightmapped LODn adds LOD_COST^n of an LOD0 of similar area (LOD1
    and LOD2: 1.3125); under Bakery each adds a whole LOD0 (3)."""
    return sum(1.0 if baker == "bakery" else LOD_COST ** n for n in lod_levels(pc))


def uses_counts(asm):
    """[(piece, instances)] inside one assembly: `uses` as {piece: count}, or a list where each entry counts once."""
    uses = asm.get("uses") if isinstance(asm, dict) else None
    if isinstance(uses, dict):
        return [(p, n) for p, n in uses.items() if isinstance(p, str) and number(n) and n > 0]
    counts = {}
    for p in uses if isinstance(uses, list) else []:
        if isinstance(p, str):
            counts[p] = counts.get(p, 0) + 1
    return list(counts.items())


def on_room_edge(rb, at, width, tol=0.5, eps=0.01):
    """True when an opening that starts at `at` and runs `width` m along an edge lies on one of the room's four edges
    (within `tol` m of the edge line, for the wall's thickness)."""
    x, y = at
    along_x = (min(abs(y - rb[1]), abs(y - rb[3])) <= tol and rb[0] - eps <= x and x + width <= rb[2] + eps)
    along_y = (min(abs(x - rb[0]), abs(x - rb[2])) <= tol and rb[1] - eps <= y and y + width <= rb[3] + eps)
    return along_x or along_y


def inside(inner, outer, tol=1e-6):
    return (outer[0] - tol <= inner[0] <= inner[2] <= outer[2] + tol
            and outer[1] - tol <= inner[1] <= inner[3] <= outer[3] + tol)


PLANNING_SECTIONS = ("grid", "families", "pieces", "zones")    # none of them yet: an intake-only spec (stage 0)
REQUIRED_SECTIONS = PLANNING_SECTIONS + ("budgets",)            # budgets may already hold the template's ceilings

# The 64 px probe-lit rule covers Free pieces of these families only (canon, 2026-10-17): ZONE shells and every
# other piece follow the grid-piece rule instead (a NOTE under 64 px; still lightmapped and counted).
PROBE_LIT_FAMILIES = ("PROP", "FOL")

# The keys each level of the spec knows (world-spec.md), plus free-text `desc` and `notes` anywhere. Any other key is
# warned: a misspelt one (zones[].lighting_state) would otherwise be ignored without a word.
FREE_TEXT = ("desc", "notes")
KNOWN_KEYS = {
    "spec": ("version", "world", "tools", "grid", "families", "budgets", "pieces", "assemblies", "zones",
             "elevations", "views", "interactivity", "lighting", "look"),
    "world": ("name", "platforms", "scale", "allow_generated_assets", "mockups", "style", "quality",
              "performance_tier"),
    "tools": ("blender", "blender_mcp", "unity_project", "substance_designer", "substance_painter", "rizomuv",
              "unity_packages", "build_modules"),
    "grid": ("module", "sub_module", "storey_height"),
    "family": ("file", "materials", "texturing", "texel_density", "map_px", "thickness", "detail_map"),   # file: legacy
    "budgets": BUDGET_KEYS + ("download_mb", "piece_tris", "lightmap"),
    "lightmap": ("max_px", "count", "texels_per_m", "min_footprint_px"),
    "piece": ("name", "collision", "tris", "lods", "lod_lightmap", "lightmap", "lightmap_scale", "size", "ref",
              "detail"),
    "look": ("references", "wear", "lighting_mood", "quality_bar", "lead_family", "materials"),
    "look_material": ("ref", "albedo_srgb", "roughness", "metal", "wear"),
    "assembly": ("name", "file", "size", "uses"),                                                         # file: legacy
    "zone": ("id", "name", "kind", "bounds", "floor_z", "placements", "rooms", "lighting_states", "switch",
             "mirrors"),
    "placement": ("ref", "pos", "rot"),
    "room": ("id", "name", "bounds", "height", "openings"),
    "opening": ("type", "at", "width", "height", "sill"),
    "mirror": ("id", "pos", "rot", "size"),
    "elevation": ("id", "zone", "facing", "origin", "courses"),
    "view": ("id", "pos", "target", "lens", "matches"),
    "interactivity": ("id", "sync"),
    "lighting": ("baker", "mode", "light_volumes"),
}
# What a check that assumed the right type raises on a value of the wrong one.
WRONG_TYPE = (TypeError, ValueError, KeyError, IndexError, AttributeError, ZeroDivisionError, OverflowError)


class Guard:
    """A value of the wrong type that gets past the type checks becomes an ERROR naming where it is, never a
    traceback; the checks go on with the next item."""

    def __init__(self, f, where):
        self.f, self.where = f, where

    def __enter__(self):
        return self

    def __exit__(self, kind, exc, tb):
        if kind is None or not issubclass(kind, WRONG_TYPE):
            return False
        self.f.error("%s: a value of the wrong type stopped this check (%s: %s); world-spec.md gives each field's "
                     "type" % (self.where, kind.__name__, exc))
        return True


def is_free(name):
    m = NAME_RE.match(str(name))
    return bool(m) and m.group(2) == "Free"


def is_probe_lit_prop(name):
    """A Free piece of a PROBE_LIT_FAMILIES family: the only kind the 64 px rule makes probe-lit."""
    m = NAME_RE.match(str(name))
    return bool(m) and m.group(2) == "Free" and m.group(1) in PROBE_LIT_FAMILIES


def one_of(v, allowed):
    """v is one of the allowed strings (never raises on a list or a mapping)."""
    return isinstance(v, str) and v in allowed


def numbers(v, n=None):
    """v is a list of numbers, of length n when given."""
    return isinstance(v, list) and (n is None or len(v) == n) and all(number(x) for x in v)


def valid_bounds(b):
    return numbers(b, 4) and b[0] < b[2] and b[1] < b[3]


def dicts_in(v):
    """The mappings in v when v is a list; nothing otherwise."""
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def course_lists(courses):
    """An elevation's courses that are lists."""
    return [c for c in courses if isinstance(c, list)] if isinstance(courses, list) else []


def mapping(parent, key, f, where):
    """parent[key] as a mapping: {} when absent or null; an ERROR (and {}) when it is anything else."""
    v = parent.get(key)
    if v is None:
        return {}
    if not isinstance(v, dict):
        f.error("%s must be a mapping (key: value), got %r" % (where, v))
        return {}
    return v


def entries(parent, key, f, where):
    """The mappings in the list parent[key]: [] when absent or null; an ERROR for anything but a list, and for each
    entry that is not a mapping."""
    v = parent.get(key)
    if v is None:
        return []
    if not isinstance(v, list):
        f.error("%s must be a list, got %r" % (where, v))
        return []
    for i, it in enumerate(v):
        if not isinstance(it, dict):
            f.error("%s: entry %d must be a mapping (key: value), got %r" % (where, i + 1, it))
    return dicts_in(v)


def check_keys(obj, kind, where, f):
    """WARN on each key this level of the spec does not know, with the nearest known one as a hint."""
    known = KNOWN_KEYS[kind] + FREE_TEXT
    for key in obj:
        if key in known:
            continue
        hint = difflib.get_close_matches(str(key), known, n=1, cutoff=0.75)
        if not hint and "state" in str(key).lower():
            hint = ["zones[].lighting_states: lighting states belong to a zone"]
        f.warn("%s: unknown key %r is ignored%s" % (where, key, " (did you mean %s?)" % hint[0] if hint else ""))


def zone_list(spec):
    """The spec's zones that are mappings."""
    return dicts_in(spec.get("zones"))


def placements_of(z):
    """A zone's placements that are mappings naming a piece or an assembly in `ref`."""
    return [pl for pl in dicts_in(z.get("placements")) if isinstance(pl.get("ref"), str)]


def off_right_angle(rot):
    """rot (degrees) is not a multiple of 90, allowing for float noise either side (269.9999999)."""
    r = abs(rot) % 90
    return min(r, 90 - r) > 1e-6


def runs_along_x(rb, ax, ay):
    """An opening whose `at` is nearer the room's south or north edge than its west or east edge runs along X."""
    return min(abs(ay - rb[1]), abs(ay - rb[3])) <= min(abs(ax - rb[0]), abs(ax - rb[2]))


def opening_line(rb, o):
    """The wall line an opening runs along, as a flat rectangle [x0, y0, x1, y1]."""
    ax, ay = o["at"]
    w = o.get("width", 1) if number(o.get("width", 1)) else 1
    return [ax, ay, ax + w, ay] if runs_along_x(rb, ax, ay) else [ax, ay, ax, ay + w]


def rect_gap(a, b):
    """Distance between two axis-aligned rectangles [x0, y0, x1, y1]: 0 when they touch or overlap."""
    return math.hypot(max(a[0] - b[2], b[0] - a[2], 0.0), max(a[1] - b[3], b[1] - a[3], 0.0))


def platform_value(val, p):
    """A budget's value for platform p: one number for every platform, or a mapping per platform in which ios falls
    back to the quest value (the two mobile builds share the Quest targets). None when there is none."""
    if not isinstance(val, dict):
        return val
    v = val.get(p)
    if v is None and p == "ios":
        v = val.get("quest")
    return v


def check_world(world, f):
    """Check the intake answers in `world`; return the known platforms."""
    check_keys(world, "world", "world", f)
    name = world.get("name")
    if name is None or name == "":
        f.error("world.name missing: the drawings and the ledger use it")
    elif not isinstance(name, str):
        f.error("world.name must be the world's name as text, got %r" % (name,))
    platforms = world.get("platforms") or []
    if not isinstance(platforms, list):
        platforms = [platforms]
    unknown = [p for p in platforms if not one_of(p, PLATFORM_LIMITS)]
    if not platforms or unknown:
        hint = " (the Android build is `quest`)" if "android" in [str(p).lower() for p in unknown] else ""
        f.error("world.platforms must list pc, quest and/or ios, got %r%s" % (platforms, hint))
    if world.get("scale", "full") not in ("full", "small"):
        f.error("world.scale must be full or small")
    if world.get("allow_generated_assets") not in (True, False):
        f.error("world.allow_generated_assets must be true or false (ask the user at intake)")
    if "mockups" in world and world["mockups"] not in (True, False):
        f.error("world.mockups must be true or false")
    if "performance_tier" in world:
        f.note("world.performance_tier is no longer used: world.platforms and budgets set the targets")
    if world.get("quality") is not None and not one_of(world.get("quality"), QUALITY):
        f.error("world.quality must be pc_lead or parity (asked at intake), got %r" % (world.get("quality"),))
    return [p for p in platforms if one_of(p, PLATFORM_LIMITS)]


def check_quality(world, platforms, budgets, f):
    """world.quality against the platforms and budgets (planning specs): a PC-lead world gives PC its own budgets."""
    q = world.get("quality")
    cross = "pc" in platforms and any(p in MOBILE for p in platforms)
    if q is None:
        if cross:
            f.note("world.quality is not set, so parity is assumed: the PC build ships what the mobile builds ship. "
                   "Intake asks pc_lead or parity (world-spec.md)")
        return
    if q == "pc_lead" and not cross:
        f.note("world.quality pc_lead only matters in a world that ships to pc and to quest or ios")
    elif q == "pc_lead":
        shared = [k for k in BUDGET_KEYS if k in budgets and not isinstance(budgets[k], dict)]
        if shared and len(shared) == len([k for k in BUDGET_KEYS if k in budgets]):
            f.note("world.quality is pc_lead, but every budget is one number for all platforms, so the PC build is "
                   "held to the mobile budgets: give PC its own value ({pc: ..., quest: ...}, world-spec.md)")


def image_list(v):
    """v is an image path or a list of them."""
    return isinstance(v, str) and v != "" or isinstance(v, list) and bool(v) and all(isinstance(x, str) and x
                                                                                     for x in v)


def check_look(spec, families, pieces, root, f):
    """The art direction texturing and QA judge against (X5, X8, L7, the look gate)."""
    look = spec.get("look")
    if look is None:
        f.note("look missing: texturing and QA (X5, X8, L7) judge against world.style alone; give references, wear, "
               "lighting_mood, lead_family and per-material targets (world-spec.md, Look)")
        return
    if not isinstance(look, dict):
        f.error("look must be a mapping: references, wear, lighting_mood, quality_bar, lead_family, materials")
        return
    check_keys(look, "look", "look", f)
    paths = []
    for key in ("references", "quality_bar"):
        v = look.get(key)
        if v is None:
            continue
        if not (isinstance(v, list) and all(isinstance(x, str) and x for x in v)):
            f.error("look.%s must be a list of image paths" % key)
        else:
            paths += [("look.%s" % key, p) for p in v]
    if look.get("wear") is not None and not one_of(look.get("wear"), WEAR):
        f.error("look.wear must be one of %s" % ", ".join(sorted(WEAR)))
    if look.get("lighting_mood") is not None and not isinstance(look.get("lighting_mood"), str):
        f.error("look.lighting_mood must be text: colour temperatures, contrast, time of day")
    lead = look.get("lead_family")
    if lead is not None and lead not in families:
        f.error("look.lead_family %r is not in families: the family textured first, before the look gate" % (lead,))
    known = {m for fam in families.values() if isinstance(fam, dict)
             for m in (fam.get("materials") if isinstance(fam.get("materials"), list) else []) if isinstance(m, str)}
    for name, t in mapping(look, "materials", f, "look.materials").items():
        where = "look.materials.%s" % name
        if name not in known:
            f.error("%s: not a material any family lists" % where)
        if not isinstance(t, dict):
            f.error("%s must be a mapping: ref, albedo_srgb, roughness, metal, wear" % where)
            continue
        check_keys(t, "look_material", where, f)
        if "ref" in t:
            if not image_list(t["ref"]):
                f.error("%s.ref must be an image path or a list of them" % where)
            else:
                paths += [(where + ".ref", p) for p in ([t["ref"]] if isinstance(t["ref"], str) else t["ref"])]
        a = t.get("albedo_srgb")
        if a is not None:
            if not (numbers(a, 2) and 0 <= a[0] < a[1] <= 255):
                f.error("%s.albedo_srgb must be [low, high] sRGB luma, 0-255 (the dielectric median)" % where)
            elif a[0] < ALBEDO_SRGB[0] or a[1] > ALBEDO_SRGB[1]:
                f.warn("%s.albedo_srgb %s reaches outside %d-%d, the dielectric range QA X8 holds every base colour to"
                       % (where, a, ALBEDO_SRGB[0], ALBEDO_SRGB[1]))
        r = t.get("roughness")
        if r is not None and not (numbers(r, 2) and 0 <= r[0] < r[1] <= 1):
            f.error("%s.roughness must be [low, high] between 0 and 1 (the median roughness)" % where)
        if "metal" in t and t["metal"] not in (True, False):
            f.error("%s.metal must be true or false" % where)
        if "wear" in t and not isinstance(t["wear"], str):
            f.error("%s.wear must be text" % where)
    for name, pc in pieces.items():
        if image_list(pc.get("ref")):
            paths += [("piece %s ref" % name, p) for p in ([pc["ref"]] if isinstance(pc["ref"], str) else pc["ref"])]
    if root:
        for where, p in paths:
            if not os.path.exists(os.path.join(root, p)):
                f.warn("%s: %s does not exist yet" % (where, p))


def check_tools(tools, f):
    check_keys(tools, "tools", "tools", f)
    if not tools.get("blender"):
        f.error("tools.blender (the Blender CLI path) is missing; find it at intake or ask the user")
    elif not isinstance(tools["blender"], str):
        f.error("tools.blender must be the Blender CLI path, got %r" % (tools["blender"],))
    if not tools.get("unity_project"):
        f.warn("tools.unity_project is not set; stages 10-13 need it")
    elif not isinstance(tools["unity_project"], str):
        f.error("tools.unity_project must be the Unity project's path, got %r" % (tools["unity_project"],))
    if "blender_mcp" in tools and tools["blender_mcp"] not in (True, False):
        f.error("tools.blender_mcp must be true or false (is the Blender MCP connected?)")


def check_budgets(budgets, platforms, families, f):
    """Budgets against every platform's targets: one number for all platforms, or a mapping per platform."""
    check_keys(budgets, "budgets", "budgets", f)
    for key in BUDGET_KEYS:
        val = budgets.get(key)
        if val is None:
            f.error("budgets.%s missing" % key)
            continue
        for p in platforms:
            v = platform_value(val, p)
            label = "budgets.%s%s" % (key, ".%s" % p if isinstance(val, dict) else "")
            if isinstance(val, dict) and p == "ios" and "ios" not in val and v is not None:
                label += " (the quest value)"
            if v is None:
                f.error("%s missing (%s is in world.platforms%s)"
                        % (label, p, "; ios falls back to quest" if p == "ios" else ""))
            elif not number(v) or v <= 0:
                f.error("%s must be a positive number, got %r" % (label, v))
            elif v > PLATFORM_LIMITS[p][key]:
                f.error("%s = %s is looser than the %s target %s" % (label, v, p, PLATFORM_LIMITS[p][key]))
    lm = budgets.get("lightmap")
    lm_px = lm.get("max_px", 0) if isinstance(lm, dict) else 0     # (check_lightmap reports a wrong lightmap)
    for p in platforms:
        if number(lm_px) and lm_px > PLATFORM_LIMITS[p]["lightmap_px"]:
            f.error("budgets.lightmap.max_px %s exceeds the %s target %d" % (lm_px, p,
                                                                            PLATFORM_LIMITS[p]["lightmap_px"]))
    dl = budgets.get("download_mb")
    if dl is not None and not isinstance(dl, dict):
        f.error("budgets.download_mb must map each platform to its MB budget, e.g. {pc: 200, quest: 100}")
        dl = None
    dl = dl or {}
    for p in platforms:
        v = platform_value(dl, p)
        if p in MOBILE:
            if v is None:
                f.error("budgets.download_mb.%s missing (%s is in world.platforms; hard limit %d MB%s)"
                        % (p, p, QUEST_DOWNLOAD_MB, "; ios falls back to quest" if p == "ios" else ""))
            elif not number(v) or v <= 0:
                f.error("budgets.download_mb.%s must be a positive number of MB, got %r" % (p, v))
            elif v > QUEST_DOWNLOAD_MB:
                f.error("budgets.download_mb.%s = %s is over the %d MB hard limit" % (p, v, QUEST_DOWNLOAD_MB))
        elif v is not None and (not number(v) or v <= 0):
            f.error("budgets.download_mb.%s must be a positive number of MB, got %r" % (p, v))
        elif number(v) and v > PC_DOWNLOAD_MB:
            f.warn("budgets.download_mb.pc = %s: VRChat asks public worlds to stay under %d MB" % (v, PC_DOWNLOAD_MB))
    piece_tris = budgets.get("piece_tris")
    if piece_tris is None:
        piece_tris = {}
    if not isinstance(piece_tris, dict):
        f.error("budgets.piece_tris must map each family code to its per-piece triangle budget, e.g. {EXT: 800}, "
                "got %r" % (piece_tris,))
        return
    for code, v in piece_tris.items():
        per_platform = isinstance(v, dict) and v and all(number(x) and x > 0 for x in v.values())
        if not (number(v) and v > 0) and not per_platform:
            f.error("budgets.piece_tris.%s must be a number of triangles (or one per platform), got %r" % (code, v))
    for code in families:
        if code not in piece_tris:
            f.warn("budgets.piece_tris has no entry for family %s" % code)


def check_grid(grid, f):
    """The grid's module and trim step: (module, sub_module or None, whether TRIM placements can be checked)."""
    check_keys(grid, "grid", "grid", f)
    module = grid.get("module")
    if not number(module) or module <= 0:
        f.error("grid.module must be a positive number of metres")
        module = 1.0
    if "storey_height" in grid and not (number(grid["storey_height"]) and grid["storey_height"] > 0):
        f.error("grid.storey_height must be a positive number of metres")
    sub = grid.get("sub_module")
    if sub is None:
        return module, None, True
    if not number(sub) or sub <= 0:
        f.error("grid.sub_module must be a positive number of metres (the step TRIM pieces are placed on)")
        return module, None, False
    steps = module / sub
    if abs(steps - round(steps)) > 1e-6:
        f.error("grid.sub_module %g m must divide grid.module %g m into whole steps (at a 1 m module: 0.5, 0.25, 0.2, "
                "0.125 or 0.1), or trims on module lines fall off it" % (sub, module))
        return module, None, False
    return module, sub, True


def check_families(families, module, sub_module, f):
    for code, fam in families.items():
        if not FAMILY_RE.match(str(code)):
            f.error("family code %r must be 2-5 capitals" % code)
        fam = {} if fam is None else fam
        if not isinstance(fam, dict):
            f.error("family %s must be a mapping of its settings (file, materials, texturing...), got %r"
                    % (code, fam))
            continue
        with Guard(f, "family %s" % code):
            check_keys(fam, "family", "family %s" % code, f)
            mats = fam.get("materials")
            mats = [] if mats is None else mats
            if not isinstance(mats, list):
                f.error("family %s materials must be a list of 1-3 material names, got %r" % (code, mats))
                mats = []
            if not 1 <= len(mats) <= 3:
                f.warn("family %s has %d materials; aim for 1-3 per family" % (code, len(mats)))
            for mname in mats:
                if not MAT_RE.match(str(mname)):
                    f.error("material %s in family %s should be named M_%s_<Name> (letters, digits and underscores)"
                            % (mname, code, code))
                elif not str(mname).startswith(("M_%s_" % code, "M_TRIM_")):
                    f.error("material %s is listed in family %s but named for another family: M_%s_<Name>, or a "
                            "shared M_TRIM_ material" % (mname, code, code))
            if not one_of(fam.get("texturing"), TEXTURING):
                f.error("family %s texturing must be one of %s" % (code, "/".join(sorted(TEXTURING))))
            check_legacy_file(fam, "family %s" % code, f)
            td = fam.get("texel_density")
            if not number(td) or td <= 0:
                f.error("family %s needs texel_density (px per metre on UV0)" % code)
            th = fam.get("thickness")
            if "thickness" in fam and not (number(th) and th > 0):
                f.error("family %s thickness must be a positive number of metres" % code)
            elif number(th) and th >= module:
                # A Size names only axes of one module or more; anything thinner is thickness and is skipped.
                f.warn("family %s thickness %g m is one module (%g m) or more: no axis of its pieces is thin, so each "
                       "needs a three-number Size (WxDxH)" % (code, th, module))
            if fam.get("detail_map", False) not in (True, False):
                f.error("family %s detail_map must be true or false (a close-range detail map on its materials)"
                        % code)
            mp = fam.get("map_px")
            if not number(mp) or mp <= 0:
                f.error("family %s needs map_px (texture size in pixels)" % code)
            elif mp > PLATFORM_LIMITS["pc"]["map_px"]:
                # The source size: mobile builds get 1024 or less from the Android and iOS import overrides (stage 10).
                f.error("family %s map_px %s exceeds the PC maximum %d (mobile sizes come from the Android and iOS "
                        "import overrides, not the source)" % (code, mp, PLATFORM_LIMITS["pc"]["map_px"]))
    if sub_module and "TRIM" in families:
        for code, fam in families.items():
            th = fam.get("thickness") if isinstance(fam, dict) else None
            if code != "TRIM" and number(th) and th > 0 and abs(th / sub_module - round(th / sub_module)) > 1e-6:
                f.warn("family %s thickness %g m is not a multiple of grid.sub_module %g m: TRIM pieces on its inner "
                       "faces would land off the sub-module grid (QA A3)" % (code, th, sub_module))


def check_pieces(spec, families, module, f):
    """The piece list; returns {name: piece} for every well-named piece."""
    pieces = {}
    for pc in entries(spec, "pieces", f, "pieces"):
        name = str(pc.get("name", ""))
        m = NAME_RE.match(name)
        if not m:
            f.error("piece %r does not follow <FAMILY>_<Type>_<Size>_<Variant>" % name)
            continue
        if name in pieces:
            f.error("piece %s listed twice" % name)
        pieces[name] = pc
        with Guard(f, "piece %s" % name):
            check_keys(pc, "piece", "piece %s" % name, f)
            if m.group(1) not in families:
                f.error("piece %s: family %s is not in families" % (name, m.group(1)))
            if not one_of(pc.get("collision", "box"), COLLISION):
                f.error("piece %s: collision must be box, mesh or none" % name)
            if pc.get("lightmap", True) not in (True, False):
                f.error("piece %s: lightmap must be true or false (false = probe-lit)" % name)
            if "tris" in pc and not (number(pc["tris"]) and pc["tris"] > 0):
                f.error("piece %s: tris must be a number of triangles" % name)
            if "lods" in pc and not (isinstance(pc["lods"], int) and not isinstance(pc["lods"], bool)
                                     and pc["lods"] >= 0):
                f.error("piece %s: lods must be a whole number of LODs after LOD0" % name)
            if pc.get("lod_lightmap", True) not in (True, False):
                f.error("piece %s: lod_lightmap must be true or false (false = LOD1+ probe-lit)" % name)
            scale = pc.get("lightmap_scale", 1)
            if not number(scale) or scale <= 0:
                f.error("piece %s: lightmap_scale (Unity's Scale In Lightmap) must be a positive number" % name)
            if "ref" in pc and not image_list(pc["ref"]):
                f.error("piece %s: ref must be an image path or a list of them (the references it is modelled to)"
                        % name)
            det = pc.get("detail")
            if det is not None and not (isinstance(det, list) and all(isinstance(x, str) and x for x in det)):
                f.error('piece %s: detail must be a list of features with their sizes, e.g. ["sill: 60 mm '
                        'projection, 50 mm thick"]' % name)
            size = pc.get("size")
            nums = [] if m.group(2) == "Free" else m.group(2).split("x")
            if size is not None and not valid_size(size):
                f.error("piece %s: size must be [x, y, z] in metres" % name)
            elif len(nums) == 1 and size is None:
                f.error("piece %s: a one-number Size is ambiguous (a post or a beam): give size: [x, y, z] in metres"
                        % name)
            elif len(nums) == 1:
                whole = [v / module for v in size if v >= module - 1e-9]
                if [int(round(v)) for v in whole] != [int(nums[0])] or any(abs(v - round(v)) > 0.01 for v in whole):
                    f.warn("piece %s: size %s does not match its Size token %s (its one axis of a module or more, in "
                           "whole modules)" % (name, size, nums[0]))
            elif size is not None and nums:
                f.note("piece %s: size is ignored for a two- or three-number Size (the token gives the extents)"
                       % name)
    return pieces


MASTER_FILE = "blender/master.blend"      # normalised (_norm): the one Blender file every piece and assembly lives in


def check_legacy_file(obj, where, f):
    """`file` on a family or assembly is left over from specs that allowed separate KIT and ASM files."""
    if "file" not in obj:
        return
    if _norm(str(obj.get("file") or "")) == MASTER_FILE:
        f.note("%s: file is no longer needed (everything lives in blender/MASTER.blend); remove it" % where)
    else:
        f.error("%s: file %r: this pipeline keeps every piece and assembly in blender/MASTER.blend, never in a "
                "separate KIT or ASM file; remove file" % (where, obj.get("file")))


def check_layout(ledger, f):
    """Everything lives in blender/MASTER.blend: no split layout recorded, no task writing a KIT or ASM file."""
    chosen = (ledger.get("intake") or {}).get("blend_layout")
    if chosen not in (None, "single"):
        f.error("ledger intake.blend_layout is %r: this pipeline keeps everything in blender/MASTER.blend (separate KIT "
                "and ASM files are not supported); remove blend_layout" % (chosen,))
    for t in ledger.get("tasks") or []:
        if not isinstance(t, dict):
            continue
        for w in t.get("writes") or []:
            if _norm(w).startswith(("blender/kits/", "blender/asm/")):
                f.error("task %s writes %s, but pieces and assemblies live in blender/MASTER.blend (a long task "
                        "works on blender/work/<task id>/)" % (t.get("id"), w))


def check_assemblies(spec, pieces, f):
    """The assembly list; returns {name: assembly}."""
    asms = {}
    for a in entries(spec, "assemblies", f, "assemblies"):
        name = str(a.get("name", ""))
        if not ASM_RE.match(name):
            f.error("assembly %r does not follow ASM_<Name>_<Variant>" % name)
        asms[name] = a
        with Guard(f, "assembly %s" % name):
            check_keys(a, "assembly", "assembly %s" % name, f)
            check_legacy_file(a, "assembly %s" % name, f)
            uses = a.get("uses")
            if isinstance(uses, dict):
                for u, n in uses.items():
                    if not (isinstance(n, int) and not isinstance(n, bool) and n > 0):
                        f.error("assembly %s: uses.%s must be a whole number of instances" % (name, u))
            elif isinstance(uses, list) and uses:
                f.note("assembly %s: uses is a list, so the lightmap check counts each entry once per placement; "
                       "write {piece: count} to count repeats" % name)
            else:
                f.error("assembly %s needs uses: {piece: count}" % name)
                uses = []
            for u in uses:
                if not isinstance(u, str) or u not in pieces:
                    f.error("assembly %s uses unknown piece %s" % (name, u))
            if not numbers(a.get("size"), 3):
                f.warn("assembly %s has no size [x, y, z]; plans will draw it as a point" % name)
    return asms


def check_placement(zid, pl, b, pieces, asms, grid, used, f):
    """One placement: a known ref, a position inside the zone, and grid pieces on the grid in 90-degree turns."""
    module, sub_module, sub_ok = grid
    ref = pl.get("ref")
    check_keys(pl, "placement", "zone %s placement of %s" % (zid, ref), f)
    if not isinstance(ref, str) or (ref not in pieces and ref not in asms):
        f.error("zone %s places unknown %s" % (zid, ref))
        if not isinstance(ref, str):
            return
    used.add(ref)
    pos = pl.get("pos")
    if not (numbers(pos) and len(pos) in (2, 3)):
        f.error("zone %s: %s needs pos: [x, y, z] in metres, got %r" % (zid, ref, pos))
        return
    rot = pl.get("rot", 0)
    if not number(rot):
        f.error("zone %s: %s rot must be degrees about Z, got %r" % (zid, ref, rot))
        rot = None
    if not (b[0] <= pos[0] <= b[2] and b[1] <= pos[1] <= b[3]):
        f.warn("zone %s: %s placed at %s, outside the zone" % (zid, ref, pos[:2]))
    m = NAME_RE.match(ref) if ref in pieces else None
    if not m or m.group(2) == "Free":
        return                                         # Free pieces and assemblies are exempt from the grid
    # QA blocks on these (B4, A3): grid pieces on the module, TRIM pieces on the sub-module, turned in 90-degree steps.
    trim = m.group(1) == "TRIM"
    if trim and not sub_ok:
        return                                         # grid.sub_module is wrong (reported): nothing to check against
    step = sub_module if trim and sub_module else module
    if rot is not None and off_right_angle(rot):
        f.error("zone %s: grid piece %s rotated %s deg (grid pieces turn in 90-degree steps)" % (zid, ref, rot))
    if any(abs(v / step - round(v / step)) > 1e-6 for v in pos[:2]):
        hint = " (TRIM pieces go on grid.sub_module, which the spec does not set)" if trim and not sub_module else ""
        f.error("zone %s: grid piece %s at %s is off the %s m %s%s"
                % (zid, ref, pos[:2], step, "sub-module" if step != module else "grid", hint))


def check_room(zid, r, b, f):
    """One room: bounds inside the zone, human ceiling height, openings of human size along its edges."""
    rid = r.get("id")
    where = "room %s/%s" % (zid, rid)
    check_keys(r, "room", where, f)
    rb = r.get("bounds")
    if not numbers(rb, 4):
        f.error("room %s/%s needs bounds" % (zid, rid))
        return
    if not inside(rb, b):
        f.error("room %s/%s lies outside its zone" % (zid, rid))
    height = r.get("height", 99)
    if not number(height):
        f.error("%s: height must be the ceiling height in metres" % where)
    elif height < HUMAN["ceiling"]:
        f.error("room %s/%s ceiling %s m is under %s m" % (zid, rid, height, HUMAN["ceiling"]))
    for i, o in enumerate(entries(r, "openings", f, "%s openings" % where)):
        check_keys(o, "opening", "%s opening %d" % (where, i + 1), f)
        at = o.get("at")
        if not numbers(at, 2):
            f.error("room %s/%s: an opening needs at: [x, y], its low end on the room edge" % (zid, rid))
            continue
        width, high = o.get("width"), o.get("height")
        if not (number(width) and width > 0 and number(high) and high > 0):
            f.error("%s opening at %s: width and height must be positive numbers of metres" % (where, at))
            continue
        if o.get("type") == "door" and (high < HUMAN["door_h"] or width < HUMAN["door_w"]):
            f.error("room %s/%s door %sx%s m is smaller than %sx%s m"
                    % (zid, rid, width, high, HUMAN["door_w"], HUMAN["door_h"]))
        sill = o.get("sill", 0)
        if not number(sill) or sill < 0:
            f.error("room %s/%s opening at %s: sill must be its bottom's height above the floor in metres "
                    "(0 for a door)" % (zid, rid, at))
        if not on_room_edge(rb, at, width):
            f.error("room %s/%s opening at %s, %s m wide, does not run along one of the room's edges (at is "
                    "its low end: smaller x on a south or north edge, smaller y on a west or east edge)"
                    % (zid, rid, at, width))


def check_mirror(zid, mi, b, mirror_ids, f):
    """One mirror slot (T-UNITY-SETUP places a VRC Mirror Reflection there): id, centre, facing and size."""
    mid = mi.get("id")
    where = "zone %s mirror %s" % (zid, mid)
    check_keys(mi, "mirror", where, f)
    if not (isinstance(mid, str) and mid) or mid in mirror_ids:
        f.error("zone %s: mirror id %r missing or duplicated" % (zid, mid))
    else:
        mirror_ids.add(mid)
    pos = mi.get("pos")
    if not numbers(pos, 3):
        f.error("%s: pos must be [x, y, z], the mirror's centre in metres" % where)
    elif not (b[0] <= pos[0] <= b[2] and b[1] <= pos[1] <= b[3]):
        f.warn("%s at %s is outside the zone" % (where, pos[:2]))
    if not number(mi.get("rot", 0)):
        f.error("%s: rot must be degrees about Z (its face looks along -Y at rot 0)" % where)
    size = mi.get("size")
    if not (numbers(size, 2) and all(v > 0 for v in size)):
        f.error("%s: size must be [width, height] in metres" % where)


def check_zones(spec, pieces, asms, grid, used, f):
    """Zones with their placements, rooms, openings and mirrors; returns the zone ids."""
    zone_ids, mirror_ids = set(), set()
    for z in entries(spec, "zones", f, "zones"):
        zid = z.get("id")
        if not (isinstance(zid, str) and ID_RE.match(zid)) or zid in zone_ids:
            f.error("zone id %r missing or duplicated, or not a name of letters, digits, _ and - (it names "
                    "plan_<id>.svg)" % (zid,))
        else:
            zone_ids.add(zid)
        with Guard(f, "zone %s" % (zid,)):
            check_keys(z, "zone", "zone %s" % (zid,), f)
            if "kind" in z and not one_of(z["kind"], ZONE_KINDS):
                f.error("zone %s: kind must be exterior or interior" % zid)
            states = z.get("lighting_states", 1)
            if not (isinstance(states, int) and not isinstance(states, bool) and states >= 1):
                f.error("zone %s: lighting_states must be a whole number, 1 or more (a baked copy per state of a "
                        "light players switch)" % zid)
            if "switch" in z and not (isinstance(z["switch"], str) and ID_RE.match(z["switch"])):
                f.error("zone %s: switch must be a name of letters, digits, _ and - (the light switch its lighting "
                        "states follow)" % zid)
            elif "switch" in z and zone_states(z) < 2:
                f.warn("zone %s: switch %s does nothing without lighting_states of 2 or more" % (zid, z["switch"]))
            if "floor_z" in z and not number(z["floor_z"]):
                f.error("zone %s: floor_z must be the floor's height in metres" % zid)
            b = z.get("bounds")
            if not valid_bounds(b):
                f.error("zone %s bounds must be [x0, y0, x1, y1] with x0 < x1, y0 < y1" % zid)
                continue
            for i, pl in enumerate(entries(z, "placements", f, "zone %s placements" % zid)):
                with Guard(f, "zone %s placement %d" % (zid, i + 1)):
                    check_placement(zid, pl, b, pieces, asms, grid, used, f)
            for r in entries(z, "rooms", f, "zone %s rooms" % zid):
                with Guard(f, "room %s/%s" % (zid, r.get("id"))):
                    check_room(zid, r, b, f)
            for mi in entries(z, "mirrors", f, "zone %s mirrors" % zid):
                with Guard(f, "zone %s mirror %s" % (zid, mi.get("id"))):
                    check_mirror(zid, mi, b, mirror_ids, f)
    by_switch = {}
    for z in zone_list(spec):
        if zone_switch(z):
            by_switch.setdefault(zone_switch(z), []).append(z)
    for sw, zs in sorted(by_switch.items(), key=lambda kv: str(kv[0])):
        states = sorted({zone_states(z) for z in zs})
        if len(states) > 1:
            f.error("zones %s share switch %s but have %s lighting states: one switch has one set of states"
                    % (", ".join(str(z.get("id")) for z in zs), sw, " and ".join(str(s) for s in states)))
    return zone_ids


def check_elevations(spec, pieces, families, module, zone_ids, used, f):
    ids = set()
    for e in entries(spec, "elevations", f, "elevations"):
        eid = e.get("id")
        where = "elevation %s" % (eid,)
        if not (isinstance(eid, str) and ID_RE.match(eid)) or eid in ids:
            f.error("elevation id %r missing or duplicated, or not a name of letters, digits, _ and - (it names "
                    "elevation_<id>.svg)" % (eid,))
        else:
            ids.add(eid)
        with Guard(f, where):
            check_keys(e, "elevation", where, f)
            if not one_of(e.get("zone"), zone_ids):
                f.error("elevation %s: unknown zone %s" % (eid, e.get("zone")))
            if not one_of(e.get("facing"), FACINGS):
                f.error("elevation %s: facing must be north, south, east or west" % eid)
            origin = e.get("origin")
            if not (isinstance(origin, list) and len(origin) >= 2 and all(number(v) for v in origin)):
                f.error("elevation %s needs origin: [x, y, z], the facade's bottom-left seen from the front" % eid)
            courses = e.get("courses")
            courses = [] if courses is None else courses
            if not isinstance(courses, list):
                f.error("%s: courses must be a list of courses, each a list of piece names" % where)
                courses = []
            widths = []
            for ci, course in enumerate(courses):
                if not isinstance(course, list):
                    f.error("%s course %d must be a list of piece names" % (where, ci))
                    continue
                w = 0.0
                for name in course:
                    if not isinstance(name, str):
                        f.error("%s course %d: %r is not a piece name" % (where, ci, name))
                        continue
                    used.add(name)
                    if name not in pieces:
                        f.error("elevation %s course %d: unknown piece %s" % (eid, ci, name))
                        continue
                    ext = piece_extent(name, module, families, pieces[name].get("size"))
                    if ext is None:
                        if is_free(name):
                            f.error("elevation %s: %s is Free; elevations take grid pieces only" % (eid, name))
                        continue
                    w += ext[0]
                widths.append(w)
            if len(set(round(w, 6) for w in widths)) > 1:
                f.warn("elevation %s: courses have different widths %s m" % (eid, widths))


def check_views(spec, world, root, f):
    views, ids = entries(spec, "views", f, "views"), set()
    for v in views:
        vid = v.get("id")
        where = "view %s" % (vid,)
        if not (isinstance(vid, str) and vid) or vid in ids:
            f.error("view id %r missing or duplicated" % (vid,))
        else:
            ids.add(vid)
        with Guard(f, where):
            check_keys(v, "view", where, f)
            for key in ("pos", "target"):
                if key not in v:
                    f.error("view %r missing %s" % (vid, key))
                elif not numbers(v[key], 3):
                    f.error("%s: %s must be [x, y, z] in metres" % (where, key))
            if "lens" in v and not (number(v["lens"]) and v["lens"] > 0):
                f.error("view %s: lens must be a focal length in mm" % v.get("id"))
            match = v.get("matches")
            if match is not None and not isinstance(match, str):
                f.error("%s: matches must be the mockup's path, or null" % where)
            elif root and match and not os.path.exists(os.path.join(root, match)):
                f.warn("view %s: %s does not exist yet" % (v.get("id"), match))
    if world.get("mockups") and not views:
        f.warn("mockups are on but no views are defined to compare them against")


def check_interactivity(spec, f):
    ids = set()
    for it in entries(spec, "interactivity", f, "interactivity"):
        iid = it.get("id")
        with Guard(f, "interactivity %s" % (iid,)):
            check_keys(it, "interactivity", "interactivity %s" % (iid,), f)
            if not (isinstance(iid, str) and iid) or iid in ids:
                f.error("interactivity id %r missing or duplicated (each one names a T-UDON-<id> task)" % (iid,))
            else:
                ids.add(iid)
            if not one_of(it.get("sync"), SYNC):
                f.error("interactivity %s: sync must be none, manual or continuous" % iid)
            if not it.get("desc"):
                f.warn("interactivity %s has no desc: the Udon brief needs the behaviour in words" % iid)


def check_lighting(spec, platforms, f):
    lighting = spec.get("lighting")
    if lighting is None:
        f.warn("lighting missing: stage 11 needs baker and mode")
        return
    if not isinstance(lighting, dict):
        f.error("lighting must be a mapping: baker, mode, light_volumes, notes")
        return
    check_keys(lighting, "lighting", "lighting", f)
    if not one_of(lighting.get("baker"), BAKERS):
        f.error("lighting.baker must be progressive or bakery")
    mode = lighting.get("mode", "baked")
    if not one_of(mode, LIGHT_MODES):
        f.error("lighting.mode must be baked or mixed")
    elif mode == "mixed" and any(p in MOBILE for p in platforms):
        f.error("lighting.mode mixed: a cross-platform world shares one bake, and Quest/iOS show no realtime "
                "shadows (Standard Lite takes the main directional light unshadowed; Lightmapped takes none): keep "
                "every light Baked (mode: baked)")
    if "light_volumes" in lighting and lighting["light_volumes"] not in (True, False):
        f.error("lighting.light_volumes must be true or false (true only when the package is installed)")


def zone_switch(z):
    """The light switch a zone's lighting states follow: its `switch`, or its own id; None without lighting states.
    Zones with one switch change together; different switches are independent."""
    if zone_states(z) < 2:
        return None
    sw = z.get("switch")
    return sw if isinstance(sw, str) and sw else z.get("id")


def zone_floor(z):
    fz = z.get("floor_z", 0)
    return fz if number(fz) else 0


def piece_rect(pl, pieces, asms, module, families):
    """The plan rectangle [x0, y0, x1, y1] a grid piece or an assembly covers at its placement; None for Free pieces
    and anything without a size."""
    ref = pl["ref"]
    if ref in asms:
        size = asms[ref].get("size")
        ext = size if numbers(size, 3) else None
    elif ref in pieces and not is_free(ref):
        ext = piece_extent(ref, module, families, pieces[ref].get("size"))
    else:
        ext = None
    pos, rot = pl.get("pos"), pl.get("rot", 0)
    if not ext or not (numbers(pos) and len(pos) >= 2) or not number(rot):
        return None
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    pts = [(pos[0] + x * c - y * s, pos[1] + x * s + y * c)
           for x, y in ((0, 0), (ext[0], 0), (ext[0], ext[1]), (0, ext[1]))]
    return [min(q[0] for q in pts), min(q[1] for q in pts), max(q[0] for q in pts), max(q[1] for q in pts)]


def along_edge(r, zb, tol=0.5):
    """A plan rectangle lies on zone bounds zb's edge: within tol of an edge line, longer along it than across, with
    at least half its length on the edge; or its centre is inside the zone. A slab or a wall that only touches the
    edge with an end or a corner does not count."""
    if zb[0] < (r[0] + r[2]) / 2 < zb[2] and zb[1] < (r[1] + r[3]) / 2 < zb[3]:
        return True
    w, h = r[2] - r[0], r[3] - r[1]
    for y in (zb[1], zb[3]):                           # south and north edges run along X
        if w > h and max(r[1] - y, y - r[3], 0) <= tol and min(r[2], zb[2]) - max(r[0], zb[0]) >= w / 2:
            return True
    for x in (zb[0], zb[2]):                           # west and east edges run along Y
        if h > w and max(r[0] - x, x - r[2], 0) <= tol and min(r[3], zb[3]) - max(r[1], zb[1]) >= h / 2:
            return True
    return False


def check_lighting_states(spec, pieces, asms, module, families, f, tol=0.5):
    """NOTEs for zones with lighting states (world-spec.md, Lightmap check). A probe-lit piece there keeps one state.
    And a switch changes the light in its zones only, so every piece it changes is placed in one of them: noted where
    a zone on another switch (or none), on the same storey, places a facade or wall along a switched zone's edge, or
    faces its openings. A piece two switches light is split, or planned per combination of states."""
    grid = spec.get("grid") if isinstance(spec.get("grid"), dict) else {}
    storey = grid.get("storey_height")
    storey = storey if number(storey) and storey > 0 else HUMAN["ceiling"]
    zones = [z for z in zone_list(spec) if valid_bounds(z.get("bounds"))]
    for z in zones:
        n, sw = zone_states(z), zone_switch(z)
        if not sw:
            continue
        zid = z.get("id")
        probe_lit = set()
        for pl in placements_of(z):
            inner = [pl["ref"]] if pl["ref"] in pieces else [p for p, _ in uses_counts(asms.get(pl["ref"]))]
            probe_lit.update(p for p in inner if p in pieces and pieces[p].get("lightmap") is False)
        for p in sorted(probe_lit):
            f.note("piece %s is probe-lit (lightmap: false) in zone %s, which has %d lighting states: it will not "
                   "change with the switch (one light probe set serves every state); drop lightmap: false if it "
                   "must" % (p, zid, n))
        for w in zones:
            wsw = zone_switch(w)
            if (w is z or wsw == sw or rect_gap(z["bounds"], w["bounds"]) > tol
                    or abs(zone_floor(z) - zone_floor(w)) >= storey - 1e-6):
                continue                               # the same switch, apart, or a storey apart
            refs = set()
            for pl in placements_of(w):
                r = piece_rect(pl, pieces, asms, module, families)
                if r and along_edge(r, z["bounds"], tol):
                    refs.add(pl["ref"])
            opens = sum(1 for r in dicts_in(z.get("rooms")) if numbers(r.get("bounds"), 4)
                        for o in dicts_in(r.get("openings")) if numbers(o.get("at"), 2)
                        and rect_gap(opening_line(r["bounds"], o), w["bounds"]) <= tol)
            wid, refs = w.get("id"), ", ".join(sorted(refs))
            if refs and wsw:
                f.note("zone %s (switch %s) places %s on the edge of zone %s (switch %s): a piece two switches light "
                       "is split, a wall face or a ceiling per room, or planned per combination of states with "
                       "vrchat-lighting-and-baking (world-spec.md, Lightmap check)" % (wid, wsw, refs, zid, sw))
            elif refs:
                f.note("zone %s places %s on the edge of zone %s, which has %d lighting states (switch %s): a switch "
                       "changes the light in its zones only, so a piece it changes, such as a facade the two zones "
                       "share, is placed in %s, or the state copies miss it (world-spec.md, Lightmap check)"
                       % (wid, refs, zid, n, sw, zid))
            elif opens:
                f.note("zone %s has %d lighting states and %d opening(s) of its rooms face zone %s: the switched light "
                       "falls through them, but only %s gets state copies, so a piece of %s that must change with it "
                       "belongs in %s (world-spec.md, Lightmap check)" % (zid, n, opens, wid, zid, wid, zid))


def check_spec(spec, f, root=None):
    """Check a spec. Returns what the lightmap report needs (empty for an intake-only spec)."""
    if not isinstance(spec, dict):
        f.error("the spec is not a YAML mapping")
        return {}
    check_keys(spec, "spec", "the spec's top level", f)
    for key in ("version", "world"):
        if key not in spec:
            f.error("missing top-level '%s'" % key)
    version = spec.get("version")
    if "version" in spec and not (isinstance(version, int) and not isinstance(version, bool) and version == 1):
        f.error("version must be 1, got %r" % (version,))
    # Stage 0 writes world and tools (and keeps the template's budget ceilings); the planning task fills the rest.
    # Check what intake owns and stop, rather than reporting every planning section as missing.
    intake_only = not any(key in spec for key in PLANNING_SECTIONS)
    if not intake_only:
        for key in REQUIRED_SECTIONS:
            if key not in spec:
                f.error("missing top-level '%s'" % key)
    world = mapping(spec, "world", f, "world")
    platforms = []
    with Guard(f, "world"):
        platforms = check_world(world, f)
    with Guard(f, "tools"):
        check_tools(mapping(spec, "tools", f, "tools"), f)
    budgets = mapping(spec, "budgets", f, "budgets")
    if intake_only:
        if budgets:
            with Guard(f, "budgets"):
                check_budgets(budgets, platforms, {}, f)
        f.note("intake-only spec (no %s yet): checked version, world, tools and budgets; the planning task fills "
               "the rest" % "/".join(PLANNING_SECTIONS))
        return {}
    grid = (1.0, None, True)
    with Guard(f, "grid"):
        grid = check_grid(mapping(spec, "grid", f, "grid"), f)
    module = grid[0]
    families = mapping(spec, "families", f, "families")
    check_families(families, module, grid[1], f)
    pieces = check_pieces(spec, families, module, f)
    asms = check_assemblies(spec, pieces, f)
    used = set()
    for a in asms.values():
        used.update(p for p, _ in uses_counts(a))
    with Guard(f, "budgets"):
        check_budgets(budgets, platforms, families, f)
    zone_ids = check_zones(spec, pieces, asms, grid, used, f)
    check_elevations(spec, pieces, families, module, zone_ids, used, f)

    for name in pieces:
        if name not in used:
            f.warn("piece %s is never placed, used in an assembly or shown in an elevation" % name)
    placed_refs = {pl["ref"] for z in zone_list(spec) for pl in placements_of(z)}
    for name in asms:
        if name not in placed_refs:
            f.warn("assembly %s is never placed in a zone: nothing puts it in MASTER, and its pieces are not in the "
                   "lightmap fill" % name)
    placed = placement_counts(spec, pieces, asms)
    for e in dicts_in(spec.get("elevations")):
        names = {n for course in course_lists(e.get("courses")) for n in course if isinstance(n, str)}
        only = sorted(n for n in names if n in pieces and n not in placed)
        if only:
            f.warn("elevation %s: %s never placed (in a zone, or in a placed assembly), so MASTER will not hold them "
                   "and the lightmap fill leaves them out: place the facade in zones[].placements"
                   % (e.get("id"), ", ".join(only)))

    with Guard(f, "world.quality"):
        check_quality(world, platforms, budgets, f)
    with Guard(f, "look"):
        check_look(spec, families, pieces, root, f)
    check_views(spec, world, root, f)
    check_interactivity(spec, f)
    with Guard(f, "lighting"):
        check_lighting(spec, platforms, f)
    with Guard(f, "lighting states"):
        check_lighting_states(spec, pieces, asms, module, families, f)

    lm = budgets.get("lightmap")
    ctx = {"pieces": pieces, "asms": asms, "module": module, "families": families,
           "lightmap": lm if isinstance(lm, dict) else {}}
    with Guard(f, "budgets.lightmap"):
        ctx.update(check_lightmap(spec, pieces, asms, module, families, f))
    return ctx


def lightmap_footprints(pieces, module, families, tpm, baker="progressive"):
    """{piece: footprint side in lightmap pixels} for each lightmapped piece with a known size, at tpm texels per metre
    (grid pieces from their Size token, Free pieces and one-number Sizes from `size`), the baker's footprint."""
    out = {}
    for name, pc in pieces.items():
        if pc.get("lightmap") is False:
            continue                                   # probe-lit
        size = piece_size(name, pc, module, families)
        if not size:
            continue
        scale = pc.get("lightmap_scale", 1)
        out[name] = footprint_px(size, tpm, scale if number(scale) and scale > 0 else 1, baker)
    return out


def zone_states(z):
    """A zone's lighting states: 1, or a baked copy per state of a light players switch there."""
    st = (z or {}).get("lighting_states", 1)
    return st if isinstance(st, int) and not isinstance(st, bool) and st >= 1 else 1


def placement_rows(spec, pieces, asms):
    """[(zone id, piece, instances, lighting states)] over every zone's placements, assemblies expanded."""
    rows = []
    for z in zone_list(spec):
        states = zone_states(z)
        for pl in placements_of(z):
            ref = pl["ref"]
            if ref in pieces:
                rows.append((z.get("id"), ref, 1, states))
            elif ref in asms:
                for piece, n in uses_counts(asms[ref]):
                    if piece in pieces:
                        rows.append((z.get("id"), piece, n, states))
    return rows


def placement_counts(spec, pieces, asms):
    """{piece: instances} over every zone's placements, counting the contents of each placed assembly."""
    counts = {}
    for _, piece, n, _ in placement_rows(spec, pieces, asms):
        counts[piece] = counts.get(piece, 0) + n
    return counts


def check_lightmap(spec, pieces, asms, module, families, f):
    """Do the placed lightmapped pieces fit budgets.lightmap at its texels_per_m, each with room for its UV2 gaps?"""
    budgets = spec.get("budgets") if isinstance(spec.get("budgets"), dict) else {}
    lm = budgets.get("lightmap")
    if lm is not None and not isinstance(lm, dict):
        f.error("budgets.lightmap must be a mapping (max_px, count, texels_per_m), got %r" % (lm,))
        return {}
    lm = lm or {}
    check_keys(lm, "lightmap", "budgets.lightmap", f)
    tpm = lm.get("texels_per_m")
    if tpm is None:
        f.warn("budgets.lightmap.texels_per_m missing: without it nobody can check that the placed pieces fit the "
               "lightmap budget, or size each piece's UV2 gaps (stage 6) for the footprint it will get")
        return {}
    if not number(tpm) or tpm <= 0:
        f.error("budgets.lightmap.texels_per_m must be a positive number (Unity's Lightmap Resolution, texels per "
                "metre), got %r: the lightmap check waits for it" % (tpm,))
        return {}
    lighting = spec.get("lighting") if isinstance(spec.get("lighting"), dict) else {}
    baker = "bakery" if lighting.get("baker") == "bakery" else "progressive"
    if baker == "bakery":
        f.note("lighting.baker is bakery: this lightmap check plans with Bakery's footprint and cost as read from its "
               "scripts, not yet measured in a bake: 2 x A x lightmap_scale x texels_per_m^2 px^2 per renderer for "
               "square UV2 bounds, each lightmapped LOD at its own area; the fill thresholds were measured with "
               "Unity's packer and are assumed for Bakery's. Oblong UV2 bounds cost x their aspect: re-plan those "
               "with vrchat-lighting-and-baking's lightmap_budget.py --lightmapper bakery, and pack UV2s with "
               "lightmapper='bakery' at stage 6")
    small = lm.get("min_footprint_px", MIN_FOOTPRINT_PX)
    if not number(small) or small <= 0:
        f.error("budgets.lightmap.min_footprint_px must be a positive number of pixels (default %d), got %r"
                % (MIN_FOOTPRINT_PX, small))
        small = MIN_FOOTPRINT_PX
    side = lightmap_footprints(pieces, module, families, tpm, baker)
    cost = {}                                          # px^2 per placed instance, its lightmapped LODs included
    for n in side:
        scale = pieces[n].get("lightmap_scale", 1)
        cost[n] = (box_cost(piece_size(n, pieces[n], module, families), tpm, scale if number(scale) and scale > 0
                            else 1, baker) * lod_factor(pieces[n], baker))
    counts, counted, switched = {}, {}, set()
    need = 0.0
    for _, n, k, states in placement_rows(spec, pieces, asms):
        counts[n] = counts.get(n, 0) + k
        if states > 1:
            switched.add(n)
        if n not in side or (is_probe_lit_prop(n) and side[n] < small and states == 1):
            continue                                   # no size, or a small Free prop: probe-lit, no lightmap space
        # vrchat-lighting-and-baking: box cost x copies x lighting states. In a zone with lighting states every
        # piece that changes with the switch stays lightmapped in each copy, small props included.
        counted[n] = counted.get(n, 0) + k * states
        need += cost[n] * k * states
    for n in sorted(counts):
        if pieces[n].get("lightmap") is False:
            continue                                   # probe-lit by the spec (noted when its zone has states)
        if n not in side:
            if is_free(n):                             # (a one-number Size without `size` is already an error)
                f.warn("piece %s is lightmapped but Free with no size: it is left out of the lightmap check (add "
                       "size: [x, y, z] in metres, or lightmap: false for a probe-lit prop)" % n)
        elif side[n] >= small:
            continue
        elif is_probe_lit_prop(n) and n not in switched:
            f.warn("Free prop %s gets about %d lightmap px at %g texels/m (< %d), so it counts as probe-lit and is "
                   "left out of the capacity sum: set lightmap: false (in Unity, Receive Global Illumination: Light "
                   "Probes, still Contribute GI)" % (n, side[n], tpm, small))
        elif is_probe_lit_prop(n):
            f.note("Free prop %s gets about %d lightmap px at %g texels/m (< %d), but its zone has lighting states: "
                   "it changes with the switch, so it stays lightmapped in each copy" % (n, side[n], tpm, small))
        else:
            # A NOTE, never a warning: facades at the lighting skill's 6-10 texels/m sit under 64 px by design.
            what = ("Free %s piece %s (only Free PROP and FOL pieces turn probe-lit)" % (n.split("_")[0], n)
                    if is_free(n) else "grid piece %s" % n)
            f.note("%s gets about %d lightmap px at %g texels/m (< %d): it stays lightmapped and counts in the fill; "
                   "raise its lightmap_scale or the world's texels_per_m if it needs more texels"
                   % (what, side[n], tpm, small))
    maps = lm.get("count", 1)
    if not (isinstance(maps, int) and not isinstance(maps, bool) and maps >= 1):
        f.error("budgets.lightmap.count must be a whole number of lightmaps, 1 or more (got %r)" % (maps,))
        maps = 1
    max_px = lm.get("max_px")
    if max_px is None:
        f.warn("budgets.lightmap.max_px missing: the lightmap capacity check is skipped")
        max_px = 0
    elif not number(max_px) or max_px <= 0:
        f.error("budgets.lightmap.max_px must be a positive number of pixels (got %r)" % (max_px,))
        max_px = 0
    area = max_px ** 2 * maps
    fill = need / area if area else 0.0
    # Unity packs chart boxes by exact geometry: two near-square boxes over half the map side cannot share a map (the
    # same rule as vrchat-lighting-and-baking's lightmap_budget.py). A box's side is about sqrt(its cost).
    big, big_names = 0, []
    for n in sorted(counted):
        scale = pieces[n].get("lightmap_scale", 1)
        side0 = math.sqrt(box_cost(piece_size(n, pieces[n], module, families), tpm,
                                   scale if number(scale) and scale > 0 else 1, baker))
        for level in lod_levels(pieces[n]):
            if max_px and side0 * lod_side(level, baker) > max_px / 2.0:
                big += counted[n]
                big_names.append("%s%s %.0f px x %d" % (n, " LOD%d" % level if level else "",
                                                        side0 * lod_side(level, baker), counted[n]))
    if big > maps:
        f.warn("lightmap chart boxes: %d are over half the %s px map side (%s): two near-square boxes that size cannot "
               "share a map, so they need %d maps, not %s; lower texels_per_m or lightmap_scale, split the piece, or "
               "add maps (budgets.lightmap.count)" % (big, max_px, ", ".join(big_names), big, maps))
    if area and fill > LIGHTMAP_MAX:
        f.error("lightmaps: the placed lightmapped pieces need about %d px^2 at %g texels/m (%s per renderer, "
                "lightmapped LODs included, x copies x lighting states), %.0f%% "
                "of %s x %s px (above %d%% a spill to another map is likely). Before stage 6: lower texels_per_m or "
                "add a map "
                "(budgets.lightmap.count). Once UV2 is packed: add a map, or make small Free props or LOD1+ "
                "(lod_lightmap: false) probe-lit; never lower texels_per_m (the packed UV2 gaps were sized for it)"
                % (need, tpm, COST_FORMULA[baker], 100 * fill, maps, max_px, 100 * LIGHTMAP_MAX))
    elif area and fill > LIGHTMAP_PLAN:
        f.warn("lightmaps: the placed lightmapped pieces fill about %.0f%% of %s x %s px at %g texels/m (plan for "
               "%d%% or less; kit-like sets spilled to another map at 79-90%% with Lightmap Padding 2)"
               % (100 * fill, maps, max_px, tpm, 100 * LIGHTMAP_PLAN))
    return {"texels_per_m": tpm, "baker": baker, "side": side, "cost": cost, "counts": counts, "counted": counted,
            "need": need,
            "area": area, "fill": fill, "maps": maps, "max_px": max_px, "small": small, "big_boxes": big}


def footprint_report(ctx):
    """Lines of the --footprints table: per piece its planning cost, footprint and placements. It plans the lightmap
    fill only: UV2 gaps are sized at stage 6 from each modelled mesh's real surface area, which an opening or an open
    shell makes much smaller than the bounding box's (the example door bay: 11.04 m2 against 15.00)."""
    if not ctx.get("pieces"):
        return ["no pieces yet (intake-only spec)"]
    if not ctx.get("texels_per_m"):
        return ["no budgets.lightmap.texels_per_m: no footprints to report"]
    lm, side, counts, counted = ctx["lightmap"], ctx["side"], ctx["counts"], ctx["counted"]
    cost = ctx.get("cost", {})
    small = ctx.get("small", MIN_FOOTPRINT_PX)
    bakery = ctx.get("baker") == "bakery"
    lines = ["Lightmap fill at %g texels/m (%s), budget %s x %s px. This table plans the lightmap fill only."
             % (ctx["texels_per_m"], "Bakery's Texels Per Unit" if bakery else "Unity's Lightmap Resolution",
                ctx["maps"], lm.get("max_px")),
             "cost = 2 x A x lightmap_scale x texels_per_m^2 px^2 per renderer, A = the bounding box's surface: "
             "Bakery's rect for square UV2 bounds (oblong bounds cost x their aspect), whatever the charts fill; "
             "lightmapped LODs add 1 each, each at its own area (lods)" if bakery else
             "cost = (texels_per_m x lightmap_scale)^2 x A px^2 per renderer, A = the bounding box's surface: Unity "
             "packs each renderer's UV2 chart box, whatever its UV2 layout; lightmapped LODs add 0.25^n each (lods)",
             ("footprint = (texels_per_m x sqrt(2 x A x lightmap_scale) - 6) / sqrt(b) px per UV unit, b = %.2f (UV2 "
              "bounds share, square, planning estimate): it sets the UV2 gaps, which stage 6 sizes from each "
              "modelled mesh's real area: --map = floor(texels_per_m x sqrt(2 x A_mesh x lightmap_scale) - 6), no LOD "
              "factor, gap = 2 / --map" if bakery else
              "footprint = texels_per_m x sqrt(A / b) x lightmap_scale px per UV unit, b = %.2f (UV2 chart box share, "
              "planning estimate): it sets the UV2 gaps, which stage 6 sizes from each modelled mesh's real area: "
              "--map = floor(texels_per_m x sqrt(A_mesh) x lightmap_scale x 0.5^n for LODn), gap = 2 / --map")
             % LIGHTMAP_COVERAGE,
             "copies = placements x the zone's lighting_states; px^2 = cost x lods x copies",
             "%-28s %-16s %8s %6s %5s %10s %7s %7s %11s" % ("piece", "size m", "box m2", "scale", "lods", "footprint",
                                                          "placed", "copies", "px^2")]
    for name in sorted(ctx["pieces"]):
        pc = ctx["pieces"][name]
        n = counts.get(name, 0)
        if pc.get("lightmap") is False:
            lines.append("%-28s probe-lit (lightmap: false), placed %d" % (name, n))
            continue
        if name not in side:
            lines.append("%-28s no size: not counted (add size: [x, y, z]), placed %d" % (name, n))
            continue
        size = piece_size(name, pc, ctx["module"], ctx["families"])
        scale = pc.get("lightmap_scale", 1)
        scale = scale if number(scale) and scale > 0 else 1
        px = side[name]
        copies = counted.get(name, 0)
        note = ""
        if px < small and is_probe_lit_prop(name) and not copies and n:
            note = "  < %d px: probe-lit, not counted (set lightmap: false)" % small
        elif px < small and is_probe_lit_prop(name):
            note = "  < %d px, but in a zone with lighting states: stays lightmapped in each copy" % small
        elif px < small:
            note = "  < %d px: raise lightmap_scale or texels_per_m" % small
        if pc.get("lod_lightmap") is False and lod_factor(dict(pc, lod_lightmap=True)) > 1:
            note += "  LOD1+ probe-lit (lod_lightmap: false): T-LIGHT sets their Receive GI to Light Probes"
        lines.append("%-28s %-16s %8.2f %6.2f %5.2f %10.1f %7d %7d %11s%s"
                     % (name, " x ".join("%g" % v for v in size), box_area(size), scale,
                        lod_factor(pc, ctx.get("baker", "progressive")), px, n, copies,
                        "{:,}".format(int(round(cost.get(name, 0) * copies))) if copies else "-", note))
    if ctx["area"]:
        lines.append("total %s px^2 of %s (%s x %s^2): %.1f%% fill; plan <= %d%%, error above %d%%"
                     % ("{:,}".format(int(round(ctx["need"]))), "{:,}".format(int(ctx["area"])),
                        ctx["maps"], ctx["max_px"], 100 * ctx["fill"], 100 * LIGHTMAP_PLAN,
                        100 * LIGHTMAP_MAX))
    else:
        lines.append("total %s px^2; no budgets.lightmap.max_px, so no fill to report"
                     % "{:,}".format(int(round(ctx["need"]))))
    return lines


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
    p = str(path).replace("\\", "/").strip().lower()
    while p.startswith("./"):
        p = p[2:]
    return p


def _overlap(na, nb):
    """The same path, or one is a folder holding the other (with or without its trailing slash)."""
    a, b = na.rstrip("/"), nb.rstrip("/")
    return a == b or b.startswith(a + "/") or a.startswith(b + "/")


def _shared_writes(wa, wb):
    """Paths two tasks both write: the same path, or a folder that holds the other's path."""
    shared = set()
    for a in wa:
        for b in wb:
            na, nb = _norm(a), _norm(b)
            if _overlap(na, nb):
                shared.add(a if len(na.rstrip("/")) <= len(nb.rstrip("/")) else b)
    return shared


def as_ledger(data, f, what):
    """A ledger mapping from a ledger file or a bare task list (a draft)."""
    if isinstance(data, list):
        return {"tasks": data}
    if isinstance(data, dict):
        return data
    f.error("%s is neither a ledger mapping nor a task list" % what)
    return {}


def merge_draft(ledger, draft, f):
    """The ledger with the draft's tasks merged in: a draft task replaces the ledger task with the same id (a re-draft
    after the kit plan or a gate's changes), and a new id is added."""
    tasks = list(ledger.get("tasks") or [])
    index = {t.get("id"): i for i, t in enumerate(tasks) if isinstance(t, dict) and t.get("id")}
    seen, replaced = set(), []
    for t in draft.get("tasks") or []:
        tid = t.get("id") if isinstance(t, dict) else None
        if tid in index and tid not in seen:
            tasks[index[tid]] = t
            replaced.append(tid)
        else:
            tasks.append(t)                            # a new id; a repeat inside the draft is reported as a duplicate
        seen.add(tid)
    if replaced:
        f.note("the draft replaces %d ledger task(s) with the same id: %s" % (len(replaced), ", ".join(replaced)))
    return dict(ledger, tasks=tasks)


def task_list(t, key, f=None, tid=None):
    """A task's list field (`deps`, `writes`): a lone string counts as one item, with an ERROR naming the field when f
    is given, rather than being read one character at a time; any other non-list counts as empty."""
    v = t.get(key)
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if f is not None:
        f.error("task %s: %s must be a list, got %r%s"
                % (tid, key, v, ": write [%s]" % v if isinstance(v, str) else ""))
    return [v] if isinstance(v, str) else []


def check_ledger(ledger, f):
    tasks = [t for t in ledger.get("tasks") or [] if isinstance(t, dict)]
    gates = ledger.get("gates") or {}
    for g, gv in gates.items():
        if (gv or {}).get("status", "pending") not in GATE_STATUSES:
            f.error("gate %s status %r not one of %s" % (g, (gv or {}).get("status"), "/".join(sorted(GATE_STATUSES))))
    ids, deps_of, writes_of = {}, {}, {}
    for t in tasks:
        tid = t.get("id")
        if not tid or tid in ids:
            f.error("task id %r missing or duplicated" % tid)
            continue
        ids[tid] = t
        deps_of[tid], writes_of[tid] = task_list(t, "deps", f, tid), task_list(t, "writes", f, tid)
        for key in ("stage", "role", "status"):
            if key not in t:
                f.error("task %s missing %s" % (tid, key))
        if t.get("status") not in STATUSES:
            f.error("task %s status %r not one of %s" % (tid, t.get("status"), "/".join(sorted(STATUSES))))
        if t.get("qa") is False:
            f.warn("task %s has qa: false; every build task gets a QA pass (false only for a task that builds "
                   "nothing, such as a skill test)" % tid)
        if not writes_of[tid]:
            f.warn("task %s has no writes: list the files and folders it alone may write" % tid)
    deps = {}
    for tid, t in ids.items():
        deps[tid] = []
        for d in deps_of[tid]:
            d = str(d)
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
    reach = {}

    def gates_before(tid, stack=()):
        """The gates a task waits for, directly or through its dependencies (and through a gate's `after` tasks)."""
        if tid in reach:
            return reach[tid]
        out = set()
        for d in deps_of[tid]:
            d = str(d)
            if d.startswith("gate:") and d[5:] in gates:
                out.add(d[5:])
                for a in (gates[d[5:]] or {}).get("after") or []:
                    if a in ids and a not in stack:
                        out |= gates_before(a, stack + (tid,))
            elif d in ids and d not in stack:
                out |= gates_before(d, stack + (tid,))
        reach[tid] = out
        return out

    for tid, t in ids.items():
        if t.get("status") in ("done", "skipped") or not number(t.get("stage")):
            continue
        for gate, first in (("spec", 4), ("greybox", 5), ("look", 9)):
            if gate in gates and t["stage"] >= first and gate not in gates_before(tid):
                f.warn("task %s (stage %s) does not wait for gate:%s, directly or through its dependencies: it could "
                       "start before the user approves the %s gate" % (tid, t["stage"], gate, gate))
        # only the lead family's texturing runs before the look gate (the trim layout comes before UVs)
        if ("look" in gates and str(tid).startswith("T-TEX-") and tid != "T-TEX-TRIM-LAYOUT"
                and tid not in ((gates["look"] or {}).get("after") or []) and "look" not in gates_before(tid)):
            f.warn("task %s does not wait for gate:look: only the lead family's texturing (the gate's `after`) runs "
                   "before the user approves the look" % tid)
    if "look" not in gates and any(str(t).startswith("T-TEX-") and t != "T-TEX-TRIM-LAYOUT" for t in ids):
        f.note("no look gate: add gates.look after the lead family's T-TEX task, and make the other T-TEX tasks and "
               "every T-EXP task wait for it (ledger.md)")
    for tid, t in ids.items():
        if t.get("status") != "running":
            continue
        waiting = ["gate:%s" % g for g in sorted(gates_before(tid))
                   if (gates.get(g) or {}).get("status", "pending") != "approved"
                   and (gates.get(g) or {}).get("reopened_by") != tid]
        if waiting:
            f.warn("task %s is running, but %s, which it waits for, %s not approved: a task already running when "
                   "the gate re-opened finishes (its dependants stay held); one whose session died goes back to todo, "
                   "same attempt, until the user approves; never dispatch a task under a gate that is not approved"
                   % (tid, " and ".join(waiting), "is" if len(waiting) == 1 else "are"))
    for tid, t in ids.items():
        for w in writes_of[tid]:
            if not _norm(w).startswith(WRITE_ROOTS):
                f.warn("task %s writes %s, outside the project layout (%s)" % (tid, w, ", ".join(WRITE_ROOTS)))
    order = sorted(ids)
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            shared = _shared_writes(writes_of[a], writes_of[b])
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
        if not isinstance(t, dict) or not t.get("id"):
            continue
        nid = re.sub(r"\W", "_", t["id"])
        lines.append('  %s["%s<br/>S%s %s<br/>%s"]' % (nid, t["id"], t.get("stage", "?"), t.get("role", ""),
                                                       t.get("status", "")))
        lines.append("  style %s fill:%s,color:#fff" % (nid, colour.get(t.get("status"), "#616161")))
        for d in task_list(t, "deps"):
            d = str(d)
            src = "gate_" + d[5:] if d.startswith("gate:") else re.sub(r"\W", "_", d)
            lines.append("  %s --> %s" % (src, nid))
    for g, gv in (ledger.get("gates") or {}).items():
        for d in (gv or {}).get("after") or []:
            lines.append("  %s --> gate_%s" % (re.sub(r"\W", "_", d), g))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec")
    ap.add_argument("--ledger", help="the pipeline ledger, to check its task graph")
    ap.add_argument("--draft", help="draft tasks (a list, or {tasks: [...]}) merged into the ledger before checking")
    ap.add_argument("--mermaid", help="write the ledger's task graph here")
    ap.add_argument("--footprints", nargs="?", const="-", metavar="FILE",
                    help="print each piece's planning lightmap footprint, copies and the fill, or write the table "
                         "to FILE")
    ap.add_argument("--root", help="project folder, to check that each view's mockup image exists")
    a = ap.parse_args()
    if (a.draft or a.mermaid) and not a.ledger:
        ap.error("--draft and --mermaid need --ledger")
    f = Findings()
    ctx = {}
    with Guard(f, "the spec"):
        ctx = check_spec(load(a.spec), f, a.root)
    if a.ledger:
        ledger = as_ledger(load(a.ledger), f, a.ledger)
        with Guard(f, "the ledger"):
            if a.draft:
                ledger = merge_draft(ledger, as_ledger(load(a.draft), f, a.draft), f)
            check_ledger(ledger, f)
            check_layout(ledger, f)
            if a.mermaid:
                os.makedirs(os.path.dirname(os.path.abspath(a.mermaid)), exist_ok=True)
                with open(a.mermaid, "w", encoding="utf-8") as out:
                    out.write(mermaid(ledger))
                print("wrote %s" % a.mermaid)
    if a.footprints:
        lines = ["no footprints: the spec has values of the wrong type (see the errors)"]
        with Guard(f, "--footprints"):
            lines = footprint_report(ctx)
        if a.footprints == "-":
            print("\n".join(lines))
        else:
            os.makedirs(os.path.dirname(os.path.abspath(a.footprints)), exist_ok=True)
            with open(a.footprints, "w", encoding="utf-8") as out:
                out.write("\n".join(lines) + "\n")
            print("wrote %s" % a.footprints)
    for kind, msg in f.items:
        print("%-5s %s" % (kind, msg))
    print("%d error(s), %d warning(s)" % (f.errors, f.warnings))
    sys.exit(1 if f.errors else 0)


if __name__ == "__main__":
    main()
