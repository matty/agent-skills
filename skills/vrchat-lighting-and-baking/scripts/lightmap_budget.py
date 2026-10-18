"""Plan a Unity lightmap before baking: each renderer's texel scale (footprint) and UV2 padding in texels, the atlas
space its chart box costs, whether everything fits the lightmaps, and the range of Lightmap Resolution (texels per
metre) that satisfies all of it.

Host: plain Python 3.9+, standard library only (no Unity needed).

    python lightmap_budget.py --texels-per-m 20 --max-px 1024 --maps 1 \
        --piece INT_Wall_2x3_A:2x3x0.2:7:0.0167 --piece PROP_Desk_Free_A:5.5:1:0.0167

A piece is NAME:SIZE:COUNT[:GAP_UV[:SCALE[:KIND[:LODS]]]].
  SIZE    surface area in m2 ("14.2"), or box dimensions in metres ("2x3x0.2": surface 2(xy + yz + xz)).
  COUNT   how many renderers use it (placed copies).
  GAP_UV  the smallest gap between the mesh's UV2 charts, in UV units (8 px at 512 = 0.015625). Optional.
  SCALE   Scale In Lightmap (default 1).
  KIND    prop    a free prop, probe-lit when its footprint is under 64 px (the default for a Free-sized piece of a
                  PROBE_LIT_FAMILIES family, PROP or FOL, as in PROP_Desk_Free_A);
          grid    a grid piece: wall, floor, ceiling, facade, ZONE shell (the default otherwise; "shell" is accepted
                  too): always lightmapped and counted, with a note under 64 px;
          lightmap  always lightmapped and counted, no 64 px note: a prop that must change with a light switch;
          probe   always probe-lit, whatever its size (the world spec's lightmap: false).
  LODS    LODs after LOD0 (default 0), each lightmapped in its own atlas space at LOD scale 0.5^n with the piece's
          area: LOD1 and LOD2 make the piece cost 1.3125x its LOD0. A LOD under 64 px gets a note.
Or --json FILE holding a list of {"name", "area_m2" or "size": [x, y, z], "count", "gap_uv", "scale", "kind",
"b", "states", "lightmap", "lods", "lod_lightmap"}; b = the measured chart-box share (0-1] of that mesh's UV2,
states = its lighting-state copies, "lightmap": false = kind probe, "lod_lightmap": false = LOD1+ probe-lit
(Receive Global Illumination = Light Probes: no atlas space). A world-spec piece pastes in unchanged: its
"lightmap_scale" is read as scale, lods and lod_lightmap read the same, and its other keys (collision, tris, desc,
notes) are ignored. Any other key is warned and ignored.

Rules (the vrchat-lighting-and-baking skill; measured in Unity 2022.3.22f1, 2026-10-16 and 2026-10-17):
  Unity packs each renderer's UV2 chart box (the bounding box of all its charts), not its whole 0-1 tile.
  texel scale  footprint_px = texels_per_m x sqrt(area / b) x scale x LOD scale, b = the chart box's share of the
               tile: 0.85 to plan (no UV2 yet), the measured b to check; LOD scale 0.5^n for LODn
  UV2 padding  = gap_uv x footprint_px >= 2 texels, checked at the measured b, else at the worst case b = 1
  a gap to pack = 2 / (texels_per_m x sqrt(area) x scale x LOD scale) (b = 1: 2 texels whatever the packer does)
  atlas cost   = the chart box = (texels_per_m x scale x LOD scale)^2 x area px^2, whatever the UV2 layout
  capacity: sum(cost x count x states) <= 0.65 x max_px^2 x maps; warn above 0.65, error above 0.80
  big boxes: a box whose side (sqrt(cost), near square) is over half the map side cannot share a map with another
             such box (Unity packs by exact geometry): warn when there are more of them than maps
Exit code 0 when the plan has no error (warnings and notes allowed), 1 on a plan error, 2 on bad input.
"""

import argparse
import difflib
import json
import math
import re
import sys

COVERAGE = 0.85          # UV2 chart-box share, planning estimate (the dry run's 2 x 3 x 0.2 m wall: 0.850 -> 243 px)
PLAN_FILL = 0.65         # plan the chart boxes to this share of the lightmap area: warn above
ERROR_FILL = 0.80        # error above (canon, 2026-10-17)
MIN_PADDING_TEXELS = 2.0
PROBE_LIT_BELOW_PX = 64.0    # house guidance (no published source): free props under it are probe-lit
MOBILE_MAX_PX = 1024     # one bake serves every platform: 1024 whenever the world ships to Quest or iOS
PC_MAX_PX = 2048         # the PC cap (vrchat-world-optimization's budgets)
LOD_SCALE = 0.5          # LODn is lightmapped at 0.5^n of LOD0's texel scale (measured 0.995 / 0.492 / 0.250)
PLAN_KEYS = ("name", "area_m2", "size", "count", "gap_uv", "scale", "kind", "b", "states", "lightmap", "lods",
             "lod_lightmap")
SPEC_KEYS = ("lightmap_scale", "collision", "tris", "desc", "notes")   # world-spec piece keys: lightmap_scale = scale
PROBE_LIT_FAMILIES = ("PROP", "FOL")    # Free-sized pieces of these families default to prop; ZONE and the rest to grid

FREE_RE = re.compile(r"^([A-Z]{2,5})_[A-Za-z0-9]+_Free_[A-Z]\d?$")
KINDS = ("prop", "grid", "lightmap", "probe")
ALIASES = {"shell": "grid"}
SCAN_STEP = 0.1          # texels per metre between the window's sample points
SCAN_MAX = 300.0


def surface_area(size):
    """Area in m2 from a number, or from box dimensions [x, y, z]."""
    if isinstance(size, (int, float)) and not isinstance(size, bool):
        area = float(size)
    elif isinstance(size, (list, tuple)) and len(size) == 3:
        x, y, z = (float(v) for v in size)
        if min(x, y, z) < 0:
            raise ValueError("box dimensions must not be negative: %r" % (size,))
        area = 2.0 * (x * y + y * z + x * z)
    else:
        raise ValueError("size must be an area or [x, y, z], got %r" % (size,))
    if not area > 0:
        raise ValueError("surface area must be above 0, got %r" % (size,))
    return area


def footprint_px(texels_per_m, area_m2, scale=1.0, b=COVERAGE, lod=0):
    """Texel scale: pixels per UV unit (the side of the renderer's scaled 0-1 tile)."""
    return texels_per_m * math.sqrt(area_m2 / b) * scale * LOD_SCALE ** lod


def box_cost_px2(texels_per_m, area_m2, scale=1.0, lod=0):
    """Atlas space of one renderer: its UV2 chart box, whatever the UV2 layout."""
    return (texels_per_m * scale * LOD_SCALE ** lod) ** 2 * area_m2


def pack_gap_uv(texels_per_m, area_m2, scale=1.0, lod=0):
    """UV2 gap that keeps 2 texels at the worst case b = 1."""
    return MIN_PADDING_TEXELS / (texels_per_m * math.sqrt(area_m2) * scale * LOD_SCALE ** lod)


def default_kind(name):
    """prop for a Free-sized piece of a PROBE_LIT_FAMILIES family, grid for everything else."""
    m = FREE_RE.match(name)
    return "prop" if m and m.group(1) in PROBE_LIT_FAMILIES else "grid"


def whole(value, what, name, low):
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise ValueError("%s: %s must be a whole number of at least %d" % (name, what, low))
    return value


def normalise(p, default_states=1):
    """Validate one piece dict and fill in its defaults; raises ValueError on bad input."""
    if not isinstance(p, dict):
        raise ValueError("each piece must be an object, got %r" % (p,))
    name = p.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("a piece has no name: %r" % (p,))
    if "area_m2" not in p and "size" not in p:
        raise ValueError("%s: give area_m2 or size [x, y, z]" % name)
    area = surface_area(p["area_m2"] if "area_m2" in p else p.get("size"))
    count = whole(p.get("count", 1), "count", name, 1)
    if "scale" in p and "lightmap_scale" in p and float(p["scale"]) != float(p["lightmap_scale"]):
        raise ValueError("%s: scale and lightmap_scale (both Scale In Lightmap) disagree" % name)
    scale = float(p.get("scale", p.get("lightmap_scale", 1.0)))
    if not scale > 0:
        raise ValueError("%s: scale must be above 0" % name)
    gap = p.get("gap_uv")
    if gap is not None:
        gap = float(gap)
        if not 0 < gap < 0.5:
            raise ValueError("%s: gap_uv must be between 0 and 0.5 UV units" % name)
    kind = p.get("kind") or default_kind(name)
    kind = ALIASES.get(kind, kind)
    if kind not in KINDS:
        raise ValueError("%s: kind must be prop, grid, lightmap or probe" % name)
    if p.get("lightmap") is False:
        kind = "probe"
    b = p.get("b")
    if b is not None:
        b = float(b)
        if not 0 < b <= 1:
            raise ValueError("%s: b (UV2 chart-box share) must be in (0, 1]" % name)
    states = whole(p.get("states", default_states), "states", name, 1)
    lods = whole(p.get("lods", 0), "lods after LOD0", name, 0)
    lod_lightmap = p.get("lod_lightmap", True)
    if not isinstance(lod_lightmap, bool):
        raise ValueError("%s: lod_lightmap must be true or false (false = LOD1+ probe-lit)" % name)
    return {"name": name, "area": area, "count": count, "scale": scale, "gap": gap, "kind": kind, "b": b,
            "states": states, "lods": lods, "lod_lightmap": lod_lightmap,
            "unknown": [k for k in p if k not in PLAN_KEYS + SPEC_KEYS]}


def key_warnings(pieces):
    """One warning per unknown key, with the nearest known key as a hint (as the world spec's validator does)."""
    out = []
    for p in pieces:
        for key in p["unknown"]:
            hint = difflib.get_close_matches(str(key), PLAN_KEYS + SPEC_KEYS, n=1, cutoff=0.75)
            out.append("%s: unknown key %r is ignored%s" % (p["name"], key,
                                                             " (did you mean %s?)" % hint[0] if hint else ""))
    return out


def parse_piece(text):
    parts = text.split(":")
    if len(parts) < 3 or len(parts) > 7:
        raise ValueError("piece %r is not NAME:SIZE:COUNT[:GAP_UV[:SCALE[:KIND[:LODS]]]]" % text)
    try:
        dims = [float(v) for v in parts[1].lower().split("x")]
        count = int(parts[2])
    except ValueError:
        raise ValueError("piece %r: SIZE and COUNT must be numbers" % text)
    if len(dims) not in (1, 3):
        raise ValueError("piece %r: SIZE is an area or x by y by z" % text)
    piece = {"name": parts[0], "size": dims[0] if len(dims) == 1 else dims, "count": count}
    try:
        if len(parts) > 3 and parts[3]:
            piece["gap_uv"] = float(parts[3])
        if len(parts) > 4 and parts[4]:
            piece["scale"] = float(parts[4])
        if len(parts) > 6 and parts[6]:
            piece["lods"] = int(parts[6])
    except ValueError:
        raise ValueError("piece %r: GAP_UV, SCALE and LODS must be numbers" % text)
    if len(parts) > 5 and parts[5]:
        piece["kind"] = parts[5].lower()
    return piece


def fill_advice(pieces, rows, max_px, mobile):
    """What can bring the fill down, given the platform, the lighting states and what is lightmapped now."""
    adv = ["lower texels/m (before the UV2 is packed: after, it shrinks the gaps)"]
    if max_px < (MOBILE_MAX_PX if mobile else PC_MAX_PX):
        adv.append("raise Max Lightmap Size (up to %d)" % (MOBILE_MAX_PX if mobile else PC_MAX_PX))
    adv.append("allow more lightmaps")
    switched = any(p["states"] > 1 for p in pieces)
    if any(r["kind"] == "prop" and r["status"] != "probe-lit" for r in rows):
        adv.append("make small free props that do not change with the switch probe-lit" if switched
                   else "make small free props probe-lit")
    if any(r["status"] == "lod" for r in rows):
        adv.append("make LOD1+ probe-lit (lod_lightmap: false)")
    if switched:
        adv.append("put only the pieces the switched light changes into the state copies")
    return ", ".join(adv)


def evaluate(pieces, texels_per_m, max_px, maps=1, mobile=False):
    """Plan at one texels_per_m. pieces: normalised dicts. Returns (rows, summary)."""
    rows, errors, warnings, notes = [], [], [], []
    need = 0.0
    big, big_names = 0, []      # chart boxes over half the map side, and which pieces they come from
    for p in pieces:
        fp = footprint_px(texels_per_m, p["area"], p["scale"], p["b"] or COVERAGE)
        fp_check = footprint_px(texels_per_m, p["area"], p["scale"], p["b"] or 1.0)
        row = {"name": p["name"], "kind": p["kind"], "count": p["count"], "states": p["states"],
               "area_m2": p["area"], "footprint_px": fp, "cost_px2": 0.0, "padding_texels": None,
               "pack_gap_uv": pack_gap_uv(texels_per_m, p["area"], p["scale"]), "status": "lightmap"}
        if p["kind"] == "probe" or (p["kind"] == "prop" and fp < PROBE_LIT_BELOW_PX):
            row["status"] = "probe-lit"
            if p["kind"] == "prop":
                warnings.append("%s: footprint %.0f px < %.0f: probe-lit free prop (Contribute GI on, Receive Global "
                                "Illumination = Light Probes)" % (p["name"], fp, PROBE_LIT_BELOW_PX))
            rows.append(row)
            continue
        if p["kind"] == "grid" and fp < PROBE_LIT_BELOW_PX:
            row["status"] = "small"
            notes.append("%s: grid piece at %.0f px < %.0f: still lightmapped and counted; raise its Scale In "
                         "Lightmap where its lighting detail matters" % (p["name"], fp, PROBE_LIT_BELOW_PX))
        copies = p["count"] * p["states"]
        row["cost_px2"] = box_cost_px2(texels_per_m, p["area"], p["scale"]) * copies
        need += row["cost_px2"]
        if p["gap"] is not None:
            row["padding_texels"] = p["gap"] * fp_check
            if row["padding_texels"] < MIN_PADDING_TEXELS:
                row["status"] = "padding"
                errors.append("%s: UV2 gaps are %.2f texels at %.0f px (b %s; need %.0f): pack gaps of %.4f UV, or "
                              "raise texels/m or Scale In Lightmap"
                              % (p["name"], row["padding_texels"], fp_check,
                                 "%.2f" % p["b"] if p["b"] else "1 worst case", MIN_PADDING_TEXELS, row["pack_gap_uv"]))
        rows.append(row)
        small_lods = []
        for n in range(p["lods"] + 1):
            side = math.sqrt(box_cost_px2(texels_per_m, p["area"], p["scale"], n))
            if n and not p["lod_lightmap"]:
                side = 0.0
            if side > max_px / 2.0:
                big += copies
                big_names.append("%s%s %.0f px" % (p["name"], " LOD%d" % n if n else "", side))
            if not n:
                continue
            lod = {"name": "%s LOD%d" % (p["name"], n), "kind": p["kind"], "count": p["count"],
                   "states": p["states"], "area_m2": p["area"], "cost_px2": side * side * copies,
                   "footprint_px": footprint_px(texels_per_m, p["area"], p["scale"], p["b"] or COVERAGE, n),
                   "padding_texels": None, "pack_gap_uv": pack_gap_uv(texels_per_m, p["area"], p["scale"], n),
                   "status": "lod" if p["lod_lightmap"] else "probe-lit"}
            need += lod["cost_px2"]
            rows.append(lod)
            if p["lod_lightmap"] and lod["footprint_px"] < PROBE_LIT_BELOW_PX:
                small_lods.append(lod)
        if small_lods:
            notes.append("%s: %s under %.0f px: make LOD1+ probe-lit (lod_lightmap: false), or keep them lightmapped "
                         "and pack their UV2 gaps (up to %.4f UV)"
                         % (p["name"], ", ".join("%s at %.0f px" % (r["name"].rsplit(" ", 1)[1], r["footprint_px"])
                                                 for r in small_lods),
                            PROBE_LIT_BELOW_PX, small_lods[-1]["pack_gap_uv"]))
    have = float(max_px) * float(max_px) * maps
    fill = need / have
    if mobile and max_px > MOBILE_MAX_PX:
        errors.append("Max Lightmap Size %d in a world that ships to Quest or iOS: one bake serves every platform, "
                      "so use %d" % (max_px, MOBILE_MAX_PX))
    advice = fill_advice(pieces, rows, max_px, mobile)
    if fill > ERROR_FILL:
        errors.append("fill %.3f of %d x %d px is past the %.2f limit: %s"
                      % (fill, maps, max_px, ERROR_FILL, advice))
    elif fill > PLAN_FILL:
        warnings.append("fill %.3f is over the %.2f plan: it may spill to another map; check Lighting > Baked "
                        "Lightmaps after the bake" % (fill, PLAN_FILL))
    if big > maps:
        warnings.append("%d chart boxes are over half the %d px map side (%s): two near-square boxes that size cannot "
                        "share a map, so they need %d maps, not %d; lower texels/m or Scale In Lightmap, split the "
                        "mesh, or allow more lightmaps" % (big, max_px, ", ".join(big_names), big, maps))
    summary = {"texels_per_m": texels_per_m, "max_px": max_px, "maps": maps, "need_px2": need, "have_px2": have,
               "fill": fill, "big_boxes": big, "errors": errors, "warnings": warnings, "notes": notes,
               "advice": advice}
    return rows, summary


def is_clean(rows, summary):
    """No error, the fill within the plan, and no more boxes over half the map side than maps. Notes (grid pieces
    and LODs under 64 px) never make a plan unclean."""
    return not summary["errors"] and summary["fill"] <= PLAN_FILL and summary["big_boxes"] <= summary["maps"]


def intervals(flags, values):
    out, start, prev = [], None, None
    for ok, v in zip(flags, values):
        if ok and start is None:
            start = v
        if not ok and start is not None:
            out.append((start, prev))
            start = None
        prev = v
    if start is not None:
        out.append((start, prev))
    return out


def window(pieces, max_px, maps=1):
    """Texels/m ranges, from every piece re-planned at every sample: (clean, workable). Clean: no error, fill
    <= 0.65 and no more boxes over half the map side than maps. Workable: no error. The mobile map-size rule is left
    out: it does not depend on texels/m."""
    values = [round(SCAN_STEP * i, 1) for i in range(1, int(SCAN_MAX / SCAN_STEP) + 1)]
    clean, ok = [], []
    for t in values:
        rows, s = evaluate(pieces, t, max_px, maps)
        ok.append(not s["errors"])
        clean.append(is_clean(rows, s))
    return intervals(clean, values), intervals(ok, values)


def plan(pieces, texels_per_m, max_px, maps=1, states=1, mobile=False):
    """Validate, evaluate at texels_per_m, and add the texels/m windows. Raises ValueError on bad input."""
    if not texels_per_m > 0:
        raise ValueError("texels per metre must be above 0")
    if isinstance(max_px, bool) or not isinstance(max_px, int) or max_px < 1:
        raise ValueError("max_px must be a whole number of at least 1")
    if isinstance(maps, bool) or not isinstance(maps, int) or maps < 1:
        raise ValueError("maps must be a whole number of at least 1")
    if not isinstance(pieces, list) or not pieces:
        raise ValueError("pieces must be a non-empty list")
    norm = [normalise(p, states) for p in pieces]
    rows, summary = evaluate(norm, texels_per_m, max_px, maps, mobile)
    summary["warnings"] = key_warnings(norm) + summary["warnings"]
    summary["window_clean"], summary["window_ok"] = window(norm, max_px, maps)
    return rows, summary


def fmt_windows(ws):
    return ", ".join("%.1f-%.1f" % w for w in ws) if ws else "none"


def report(rows, summary, out=sys.stdout):
    out.write("%-26s %-8s %5s %8s %9s %10s %8s %9s  %s\n" % ("piece", "kind", "count", "area m2", "footprint",
                                                           "cost px2", "padding", "pack gap", "status"))
    for r in rows:
        pad = "-" if r["padding_texels"] is None else "%.2f" % r["padding_texels"]
        out.write("%-26s %-8s %5d %8.2f %7.0fpx %10.0f %8s %9.4f  %s\n"
                  % (r["name"][:26], r["kind"], r["count"] * (1 if r["status"] == "probe-lit" else r["states"]),
                     r["area_m2"], r["footprint_px"], r["cost_px2"], pad, r["pack_gap_uv"], r["status"]))
    s = summary
    out.write("\nfill %.3f of %d x %d px in chart boxes (plan <= %.2f, error > %.2f)\n"
              % (s["fill"], s["maps"], s["max_px"], PLAN_FILL, ERROR_FILL))
    out.write("texels/m windows, every piece re-planned at each value: clean (no error, fill <= %.2f, boxes fit "
              "beside each other) %s; workable (no error) %s\n"
              % (PLAN_FILL, fmt_windows(s["window_clean"]), fmt_windows(s["window_ok"])))
    if not s["window_ok"]:
        out.write("No texels/m works with these UV2 gaps: re-pack each mesh with its pack gap at the texels/m you "
                  "choose; to free lightmap space: %s\n" % s["advice"])
    for n in s["notes"]:
        out.write("NOTE  %s\n" % n)
    for w in s["warnings"]:
        out.write("WARN  %s\n" % w)
    for e in s["errors"]:
        out.write("ERROR %s\n" % e)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--texels-per-m", type=float, required=True, help="Lightmap Resolution (texels per metre)")
    ap.add_argument("--max-px", type=int, required=True, help="Max Lightmap Size (512, 1024, 2048)")
    ap.add_argument("--maps", type=int, default=1, help="lightmaps the plan allows (default 1)")
    ap.add_argument("--states", type=int, default=1, help="lighting states: copies of every piece (default 1)")
    ap.add_argument("--mobile", action="store_true", help="the world ships to Quest or iOS (max 1024)")
    ap.add_argument("--piece", action="append", default=[],
                    help="NAME:SIZE:COUNT[:GAP_UV[:SCALE[:KIND[:LODS]]]] (repeat)")
    ap.add_argument("--json", help="JSON file with a list of pieces")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        pieces = [parse_piece(t) for t in a.piece]
        if a.json:
            with open(a.json, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("the JSON file must hold a list of pieces")
            pieces += data
        if a.states < 1:
            raise ValueError("--states must be at least 1")
        rows, summary = plan(pieces, a.texels_per_m, a.max_px, a.maps, a.states, a.mobile)
    except (ValueError, TypeError, KeyError, OSError) as e:
        sys.stderr.write("lightmap_budget: %s\n" % e)
        return 2
    report(rows, summary)
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
