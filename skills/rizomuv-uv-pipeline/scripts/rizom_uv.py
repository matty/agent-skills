"""Unwrap and pack a mesh in RizomUV, fileless: flat arrays in, flat arrays out.

Host: any Python 3.6-3.13 (no bpy; numpy only for unwrap_gated, through uv_metrics.py). Blender users want
blender_rizom.py, which builds the arrays and writes the UV layers for you.

    import sys; sys.dont_write_bytecode = True; sys.path.insert(0, r"<skill>/scripts")
    from rizom_link import rizom_session
    import rizom_uv as ru
    with rizom_session() as link:
        res = ru.unwrap_gated(link, mesh, kind="organic",
                              packs={"uv0": ru.pack_spec(1024),                      # 16 px padding, 8 px margin
                                     "uv2": ru.lightmap_spec(mesh, texels_per_m=20)})  # gaps >= 2 lightmap texels
    res["packs"]["uv0"]["uvw_ids"], res["packs"]["uv0"]["uvw"]   # write back corner by corner
    res["failures"]                                              # {"uv0": [], "uv2": []} when every channel passed

`mesh` is a dict in RizomUV's own Data layout (lists, tuples or numpy arrays; load() converts them):
    sizes    [P]   corner count per polygon (n-gons are fine)
    xyz_ids  [C]   3D vertex index per corner, polygon by polygon
    xyz      [3V]  3D coordinates, flat. In metres if you want texel density in px/m
    uvw_ids  [C]   UV vertex index per corner. A 3D vertex split into several UV vertices is a seam
    uvw      [3U]  seed UV coordinates, flat. Seed with the 3D positions, never zeros: Unfold sizes islands from
                   the seed area
Polygon and corner order are preserved, so the results map straight back onto the source corners.

The technique numbers (padding per map size, the distortion gate, the 2-texel lightmap gap, the lightmap footprint)
are the uv-unwrapping skill's; this module states the same values.
"""

import copy
import math
import os
import re
import sys
import time


def metrics():
    """uv_metrics (needs numpy), imported on first use without leaving a __pycache__ in the skill folder."""
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        import uv_metrics
    finally:
        sys.dont_write_bytecode = keep
    return uv_metrics

# ----------------------------------------------------------------------------------------------- presets
# Chosen by a distortion sweep on RizomUV 2027.0.598 (see ../references/distortion-and-quality.md).
#   - Mosaic (QuasiDevelopable) never splits an island smaller than IslandPolyNBMin, so it must be 1.
#   - QuadLoopCutter overrides Mosaic: leave it out of the organic preset.
#   - Quality is the stretch limiter's threshold: 0.75 cuts only where flattening distorts; 0.9+ shatters.
PRESETS = {
    "hard": {"SharpEdges": {"AngleMin": 40.0}, "PipesCutter": True, "HandleCutter": True,
             "StretchLimiter": {}, "Quality": 0.75, "FlatteningMode": 0},
    "organic": {"SharpEdges": {"AngleMin": 60.0}, "PipesCutter": True, "HandleCutter": True,
                "QuasiDevelopable": {"Developability": 0.8, "IslandPolyNBMin": 1, "FitCones": True,
                                     "AreaMinRatio": 0.01},
                "StretchLimiter": {}, "Quality": 0.75, "FlatteningMode": 0},
    # first-try settings, kept as a comparison point: fails the gate on curved organic pieces
    "baseline_organic": {"SharpEdges": {"AngleMin": 60.0}, "QuadLoopCutter": True, "PipesCutter": True,
                         "HandleCutter": True},
}
UNFOLD = {"unfold_it": 5, "opt_it": 25, "adm": 1.0}

# Tried in order when a piece fails the gate; each step is merged over the preset.
RETRY_LADDER = [
    ("stretch limiter 0.85", {"Quality": 0.85}),
    ("mosaic 0.9", {"QuasiDevelopable": {"Developability": 0.9, "IslandPolyNBMin": 1, "FitCones": True,
                                         "AreaMinRatio": 0.01}, "Quality": 0.85}),
]

# Pack enums, measured on 2027.0.598 by probe_pack_enums.py (0-based in the documented order).
SCALING_AVG_MOVABLE, SCALING_USER = 2, 6
LAYOUT_TRANSLATE_ONLY, LAYOUT_BEST_FIT = 1, 2

# Lightmap footprint (vrchat-lighting-and-baking owns the Unity numbers, uv-unwrapping the UV2 rules). Unity gives a
# renderer's whole 0-1 UV2 tile texels_per_m x sqrt(A / b) x Scale In Lightmap texels on a side, A = its surface
# area in m2, b = the UV2 charts' bounding-box area as a share of the tile (measured on five renderers, Unity
# 2022.3.22f1, 2026-10-16: within 0.6% for b 0.79-0.95). LIGHTMAP_COVERAGE is b's planning estimate (no UV2 yet);
# the gaps are packed for b = 1, the worst case (>= 2 texels, >= 1 to the edge), and checked at the measured b.
# Under 64 px (house guidance): a free prop is probe-lit; a grid piece raises its Scale In Lightmap instead.
LIGHTMAP_COVERAGE = 0.85      # b, the UV2 bounding-box share: planning estimate (the dry-run wall's value)
LIGHTMAP_GAP_TEXELS, LIGHTMAP_EDGE_TEXELS = 2.0, 1.0
LIGHTMAP_MIN_FOOTPRINT_PX = 64
LIGHTMAP_MIN_BOX_FILL = 0.5   # charts' area / their bounding box: Unity lightmaps the whole box (canon, 2026-10-17)
# Bakery (ftBuildGraphics.cs as installed in a Unity 2022.3.22f1 project, read 2026-10-24; references/texel-density.md):
# a rect of side texels_per_m x sqrt(2 x A x Scale In Lightmap) on the UV2 box's short side, no LOD factor; its
# Default atlas packer insets each rect 3 texels (xatlas does not, so packing for the inset holds under both).
LIGHTMAPPERS = ("unity", "bakery")      # whose footprint the lightmap specs use; "progressive" is accepted for unity
BAKERY_AREA_FACTOR = 2.0      # Bakery sums |cross| over the triangles: 2 x the surface area
BAKERY_INSET_TEXELS = 3       # texelPaddingForDefaultAtlasPacker's default
EFFECTIVE_DENSITY_MIN = 0.5   # Bakery: a warning when the charts get under this share of the planned texels per metre
LOD_SCALE = 0.5               # a <Piece>_LOD<n> renderer gets its own lightmap space at 0.5^n of the texel scale
LOD_RE = re.compile(r"_LOD(\d+)(\.\d{3})?$")   # vrchat-world-qa's: <Piece>_LOD<n>, a Blender .001 suffix allowed
LIGHTMAP_FALLBACK_STEPS = 4    # a too-small or failing UV2 is re-packed for 64 px (or 2F), then 2x, 4x, 8x that
PACK_GRID_SLACK_PX = 0.5      # PaddingPerfect pads on the pack's pixel grid: measured gaps up to 0.5 px short

# Directional textures: Pack's Rotate.Initial pre-orients each island, then Rotate.Step 0 keeps it. Measured
# 2026-10-17 on a plank crate (76 grain faces): Step 0 alone left 37 along U and 39 along V; "Horizontal" laid all
# 76 along U (each island's long side), "Vertical" all along V; "Z|+V|X|+U" turns world up to +V (text, decals).
DIRECTIONAL = {"grain": "Horizontal", "upright": "Z|+V|X|+U"}


def resolve_kind(kind):
    """Preset name, case-insensitive. Raises ValueError naming the valid ones."""
    k = str(kind).strip().lower()
    if k not in PRESETS:
        raise ValueError("unknown kind %r: use one of %s" % (kind, ", ".join(sorted(PRESETS))))
    return k


def pack_spec(map_px, pad_px=None, margin_px=None, px_per_unit=None, rotate_step=90.0, device="CPU",
              rotate_initial=None):
    """One packing target. pad_px defaults to map_px / 64 (16 px at 1024: the uv-unwrapping skill's gap, the
    minimum: Polycount's per-shell padding doubled, http://wiki.polycount.com/wiki/Edge_padding) and margin_px
    to half of it (map_px / 128, the tile edge). px_per_unit=None fills the 0-1 tile (per-piece maps); a number
    packs at that texel density instead (texels per mesh unit, i.e. px/m for metre input). rotate_step 90 lets
    the packer turn islands; directional textures go through directional() instead (rotate_initial + rotate_step
    0).
    device: "CPU" (default: leaves the GPU to bakes and everything else) or "FastestGPU" (CUDA)."""
    if device not in ("CPU", "FastestGPU"):
        raise ValueError("device must be 'CPU' or 'FastestGPU', not %r" % (device,))
    pad = max(1, int(round(map_px / 64.0))) if pad_px is None else int(pad_px)
    margin = max(1, int(math.ceil(pad / 2.0))) if margin_px is None else int(margin_px)
    return {"map_px": int(map_px), "pad_px": pad, "margin_px": margin, "px_per_unit": px_per_unit,
            "rotate_step": float(rotate_step), "rotate_initial": rotate_initial, "device": device}


def directional(spec, mode):
    """A copy of a texture spec that keeps a direction: mode "grain" (or True) lays every island's long side along U
    (wood grain, brushed metal), "upright" turns world +Z to +V (text, decals, signage), any other string is passed
    as Pack's Rotate.Initial (an axis map such as "X|+U|Y|+V"). False or None returns the spec unchanged."""
    if not mode:
        return spec
    initial = DIRECTIONAL["grain"] if mode is True else DIRECTIONAL.get(str(mode).lower(), str(mode))
    return dict(spec, rotate_step=0.0, rotate_initial=initial)


def lightmapper_name(name):
    """unity (also "progressive", the world spec's lighting.baker for it) or bakery; raises ValueError otherwise."""
    n = str(name or "unity").strip().lower()
    n = "unity" if n == "progressive" else n
    if n not in LIGHTMAPPERS:
        raise ValueError("lightmapper must be unity (or progressive) or bakery, not %r" % (name,))
    return n


def bakery_side(area_m2, texels_per_m, scale_in_lightmap=1.0):
    """Bakery's rect side on the UV2 box's short side: texels_per_m x sqrt(2 x area x Scale In Lightmap)."""
    return float(texels_per_m) * math.sqrt(BAKERY_AREA_FACTOR * max(float(area_m2), 0.0)
                                           * max(float(scale_in_lightmap), 0.0))


def lightmap_footprint(area_m2, texels_per_m, scale_in_lightmap=1.0, bbox_share=LIGHTMAP_COVERAGE, lightmapper="unity",
                       short_side=None):
    """Side in texels that a lightmapper gives one renderer's whole 0-1 UV2 tile (texels per UV unit). Unity:
    texels_per_m x sqrt(area / b) x Scale In Lightmap, area = the mesh's surface area in m2, b = the UV2 bounding-box
    share of the tile (the planning estimate 0.85 by default; 1 for packing; the measured share for checking). Unity
    2022.3: a 2 x 3 x 0.2 m wall at 60 texels/m with b 0.850 got 242.8 px. Bakery: (bakery_side - 2 x 3) / the box's
    short side in UV (short_side; sqrt(b), a square box, when not given; 1 for packing)."""
    b = min(max(float(bbox_share), 1e-6), 1.0)
    if lightmapper_name(lightmapper) == "bakery":
        short = math.sqrt(b) if short_side is None else min(max(float(short_side), 1e-6), 1.0)
        return max(bakery_side(area_m2, texels_per_m, scale_in_lightmap) - 2.0 * BAKERY_INSET_TEXELS, 0.0) / short
    return float(texels_per_m) * math.sqrt(max(float(area_m2), 0.0) / b) * float(scale_in_lightmap)


def scale_factor(footprint, want_px, lightmapper="unity"):
    """What Scale In Lightmap must be multiplied by to take a footprint (the box filling the tile) to want_px:
    linear under Unity; on the area under Bakery, its inset staying."""
    footprint = max(float(footprint), 1e-9)
    if lightmapper_name(lightmapper) == "bakery":
        return ((want_px + 2.0 * BAKERY_INSET_TEXELS) / (footprint + 2.0 * BAKERY_INSET_TEXELS)) ** 2
    return want_px / footprint


def bbox_short_side(uvw_ids, uvw):
    """The short side, in UV, of the bounding box of the UVs the corners use (Bakery maps it onto its rect's side)."""
    used = set(int(i) for i in uvw_ids)
    if not used:
        return 1.0
    us = [float(uvw[3 * i]) for i in used]
    vs = [float(uvw[3 * i + 1]) for i in used]
    return max(min(max(us) - min(us), max(vs) - min(vs)), 1e-9)


def lightmap_warning(footprint_px, who=""):
    """The note for a renderer whose lightmap footprint is under 64 px, or None. Judged on LOD0 only: a
    <Piece>_LOD<n> renderer (n >= 1) follows its piece, as vrchat-world-qa does."""
    if footprint_px >= LIGHTMAP_MIN_FOOTPRINT_PX or lod_level(who) > 0:
        return None
    return ("lightmap footprint %.0f px under %d%s: probe-light it if it is a Free prop (a Free-sized PROP or FOL "
            "piece, not in a zone with lighting states); otherwise raise Scale In Lightmap or texels_per_m"
            % (footprint_px, LIGHTMAP_MIN_FOOTPRINT_PX, (" for %s" % who) if who else ""))


def lod_level(name):
    """n of a <Piece>_LOD<n> name (a Blender .001 suffix allowed; upper case, as vrchat-world-qa reads it), else 0."""
    m = LOD_RE.search(str(name or ""))
    return int(m.group(1)) if m else 0


def lod_scale(name, lightmapper="unity"):
    """The lightmap texel scale Unity gives a <Piece>_LOD<n> renderer: 0.5^n (LOD0 1, LOD1 0.5, LOD2 0.25), each LOD
    in its own atlas space. Measured 2026-10-17, Unity 2022.3.22f1 Progressive GPU: 0.995 / 0.492 / 0.250, whatever
    the LOD transition heights (vrchat-lighting-and-baking owns the number). Bakery sizes each LOD by its own area
    with no LOD factor: 1."""
    return LOD_SCALE ** lod_level(name) if lightmapper_name(lightmapper) == "unity" else 1.0


def lightmap_capacity_px(charts, gap_texels=LIGHTMAP_GAP_TEXELS, edge_texels=LIGHTMAP_EDGE_TEXELS, chart_texels=0.0):
    """The smallest b = 1 footprint (texels on a side) that can hold `charts` charts of chart_texels each on a square
    grid, gap_texels apart and edge_texels from the tile edge: below it 2-texel gaps are impossible whatever the
    packer does. 6 charts: 6 px; measured 2026-10-17 on 2027.0.598, a plank's and a cube's 6 charts overlapped at
    3 and 5 px and packed clean from 7 px. Above it the pack is still graded (pack_lightmap)."""
    k = int(math.ceil(math.sqrt(max(int(charts), 1))))
    return k * chart_texels + (k - 1) * gap_texels + 2.0 * edge_texels


def lightmap_too_small(spec, charts):
    """None when a lightmap_spec's smallest footprint can hold `charts` charts with its gaps, else why not
    ("6 charts need 6 px")."""
    need = lightmap_capacity_px(charts, spec["gap_texels"], spec["edge_texels"])
    return None if spec["packed_for_px"] >= need else "%d charts need %.0f px" % (charts, need)


def lightmap_fallback_spec(spec, px=LIGHTMAP_MIN_FOOTPRINT_PX):
    """spec re-aimed so its smallest b = 1 footprint is px (64): every renderer's scale times px / smallest (Bakery:
    times ((px + 6) / its smallest rect side)^2, as its scale acts on the area)."""
    k = _scale_up(spec, px)
    return lightmap_spec(0.0, spec["texels_per_m"], users={n: (a, s * k) for n, (a, s) in spec["users"].items()},
                         gap_texels=spec["gap_texels"], edge_texels=spec["edge_texels"],
                         rotate_step=spec["rotate_step"], device=spec.get("device", "CPU"),
                         lightmapper=spec.get("lightmapper", "unity"))


def _scale_up(spec, px):
    """The factor on every user's Scale In Lightmap that takes the smallest b = 1 footprint to px."""
    if spec.get("lightmapper") == "bakery":
        return ((float(px) + 2.0 * BAKERY_INSET_TEXELS)
                / min(bakery_side(a, spec["texels_per_m"], s) for a, s in spec["users"].values())) ** 2
    return float(px) / min(lightmap_footprint(a, spec["texels_per_m"], s, 1.0) for a, s in spec["users"].values())


def lightmap_spec(mesh_or_area, texels_per_m, scale_in_lightmap=1.0, users=None, gap_texels=LIGHTMAP_GAP_TEXELS,
                  edge_texels=LIGHTMAP_EDGE_TEXELS, rotate_step=90.0, device="CPU", lod=0, lightmapper="unity"):
    """Packing target for a lightmap UV: gaps >= gap_texels and an edge >= edge_texels at the worst case b = 1,
    i.e. gap in UV = 2 / (texels_per_m x sqrt(area) x scale), so they hold whatever bounding box the packer makes.
    users={name: (area_m2, scale_in_lightmap)} lists every renderer of a shared mesh (each at its own placed size
    and Scale In Lightmap): the pack is made for the smallest. Packs at map_px = max(128, next_pow2(that b = 1
    footprint)) with padding and margin in those pixels, plus the 0.5 px PaddingPerfect can lose. Grade the result
    with layer_report(), which measures b and checks the gaps in texels at every user's real footprint. lod=n (or
    lod_scale(name) in a user's scale) packs a <Piece>_LOD<n> mesh at 0.5^n of the footprint: larger gaps in UV.
    lightmapper="bakery": Bakery's footprint with the box filling the tile, texels_per_m x sqrt(2 x area x scale) - 6
    (its Default packer's inset; xatlas has none, so the gaps hold under both), and no LOD factor (lod is ignored)."""
    lm = lightmapper_name(lightmapper)
    if users is None:
        area = mesh_area(mesh_or_area) if isinstance(mesh_or_area, dict) else float(mesh_or_area)
        users = {"": (area, scale_in_lightmap * (LOD_SCALE ** int(lod) if lm == "unity" else 1.0))}
    users = {str(k): (float(a), float(s)) for k, (a, s) in users.items()}
    if min(lightmap_footprint(a, texels_per_m, s, 1.0) for a, s in users.values()) <= 0:
        raise ValueError("lightmap footprint is 0: give the mesh area in m2, texels_per_m > 0 and a scale > 0")
    feet = {k: lightmap_footprint(a, texels_per_m, s, 1.0, lm) for k, (a, s) in users.items()}
    foot = min(feet.values())
    if lm == "bakery":
        foot = max(foot, 0.5)                 # a rect of 6 texels or less keeps nothing: pack_lightmap's fallback
    map_px = max(128, 2 ** int(math.ceil(math.log2(foot))))
    pad = int(math.ceil(gap_texels * map_px / foot + PACK_GRID_SLACK_PX))
    margin = int(math.ceil(edge_texels * map_px / foot + PACK_GRID_SLACK_PX))
    spec = pack_spec(map_px, pad, margin, rotate_step=rotate_step, device=device)
    spec.update({"lightmap": True, "texels_per_m": float(texels_per_m), "users": users, "lightmapper": lm,
                 "packed_for_px": round(foot, 2), "gap_texels": float(gap_texels), "edge_texels": float(edge_texels)})
    return spec


def _footprints(spec, b=1.0, short_side=None):
    """Every user's footprint at a box share b (Bakery: and the box's short side)."""
    lm = spec.get("lightmapper", "unity")
    return {n: lightmap_footprint(a, spec["texels_per_m"], s, b, lm, short_side) for n, (a, s) in spec["users"].items()}


def layer_report(mesh, uvw_ids, uvw, spec, region_angle=None):
    """uv_metrics.report() of one packed layer, graded the way its spec asked. A texture: padding and margin in map
    pixels. A lightmap_spec: b is measured (bbox_share), each user's footprint is texels_per_m x sqrt(A / b) x
    scale, and the gaps and edge are checked strictly in texels at the smallest of them; the report adds
    footprint_px (the first user), footprints_px (every user) and graded_at_px. region_angle: the attempt's
    SharpEdges.AngleMin, for the fragmentation count against planar regions (uv_metrics.planar_regions)."""
    um = metrics()
    if not spec.get("lightmap"):
        extra = {} if region_angle is None else {"region_angle": region_angle}
        rep = um.report(mesh, uvw_ids, uvw, spec["map_px"], pad_px=spec["pad_px"], margin_px=spec["margin_px"],
                        **extra)
        floor = um.coverage_floor(rep)
        rep["warnings"] = []
        if not spec.get("px_per_unit") and rep["coverage"] < um.MIN_FILL_COVERAGE:
            if rep["islands"] > um.FILL_COVERAGE_MAX_ISLANDS:
                rep["warnings"].append(
                    "many islands: coverage %.3f with %d islands, the map/64 gaps take the tile: accept it, or reduce "
                    "surface detail first" % (rep["coverage"], rep["islands"]))
            elif floor <= rep["coverage"]:
                rep["warnings"].append(
                    "thin piece: coverage %.3f is about what its shape allows (%.2f): a square tile cannot hold it "
                    "better; pack it at a texel density or put it on a trim" % (rep["coverage"],
                                                                               rep["shape_coverage_limit"]))
        seam_note = um.visible_seam_warning(rep["seams"])         # advisory: where the cuts are, not distortion
        if seam_note:
            rep["warnings"].append(seam_note)
        return rep
    lm = spec.get("lightmapper", "unity")
    inside = in_unit_tile(uvw)
    b = um.bbox_share(uvw_ids, uvw) if inside else 1.0
    short = (bbox_short_side(uvw_ids, uvw) if inside else 1.0) if lm == "bakery" else None
    feet = _footprints(spec, b, short)
    smallest = min(feet.values())
    rep = um.report(mesh, uvw_ids, uvw, smallest, pad_px=spec["gap_texels"], margin_px=spec["edge_texels"],
                    pad_tol_px=0.0)
    fill = min(1.0, rep["coverage"] / b) if b > 0 else 0.0
    eff, low = _density(spec, feet, _areas(mesh, uvw_ids, uvw)[1], fill)
    rep.update({"bbox_share": round(b, 4), "footprint_px": round(next(iter(feet.values())), 2),
                "footprints_px": {k: round(v, 2) for k, v in feet.items()}, "graded_at_px": round(smallest, 2),
                "box_fill": round(fill, 3), "effective_texels_per_m": eff, "lightmapper": lm})
    if short is not None:
        rep["bbox_short_side"] = round(short, 4)
    rep["warnings"] = [w for w in (lightmap_warning(v, k) for k, v in feet.items()) if w]
    if low:
        rep["warnings"].append(low)
    elif fill < LIGHTMAP_MIN_BOX_FILL and smallest >= LIGHTMAP_MIN_FOOTPRINT_PX:   # smaller: 2-texel gaps dominate
        rep["warnings"].append("lightmap charts fill %.0f%% of their box: %s lightmaps the whole box, so the empty "
                               "part costs texels" % (100 * fill, "Bakery" if lm == "bakery" else "Unity"))
    return rep


def _density(spec, feet, uv_area, fill):
    """Every user's effective lightmap density, footprint x sqrt(the layout's UV area / its surface area), in texels
    per metre, and under Bakery the warning when a user at 64 px or more gets under half the density planned for it
    (texels_per_m x sqrt(its Scale In Lightmap), at most texels_per_m), or None."""
    eff, low = {}, []
    for n, (a, s) in spec["users"].items():
        eff[n] = feet[n] * math.sqrt(max(uv_area, 0.0) / a) if a > 0 else 0.0
        planned = spec["texels_per_m"] * min(1.0, math.sqrt(s))
        if (spec.get("lightmapper") == "bakery" and feet[n] >= LIGHTMAP_MIN_FOOTPRINT_PX
                and eff[n] < EFFECTIVE_DENSITY_MIN * planned):
            low.append("%s%.1f texels/m of %g planned" % (n + " " if n else "", eff[n], round(planned, 2)))
    warn = None
    if low:
        warn = ("lightmap charts fill %.0f%% of their box: effective density %s, under half (Bakery sizes the UV2 by "
                "its area and bounds): pack the charts to fill their bounds, or raise Scale In Lightmap and pack "
                "again for the larger footprint" % (100 * fill, "; ".join(low)))
    return {n: round(v, 2) for n, v in eff.items()}, warn


def pack_lightmap(link, mesh, spec, charts):
    """Pack and grade a lightmap channel; returns (pack, report, failures). When the smallest renderer's b = 1
    footprint F cannot hold the charts with 2-texel gaps (lightmap_too_small) or its pack fails them, the UV2 is
    re-packed for a larger footprint until one passes: 64 px when F is under 64, else 2F, then 2x, 4x and 8x that
    (LIGHTMAP_FALLBACK_STEPS, lightmap_fallback_spec). Every render mesh so keeps a valid UV2, and the note says
    what it is for: a probe-lit piece, or Scale In Lightmap raised by the factor given. Under 64 px that is a note
    (failures []); at 64 px or more the piece is meant to be lightmapped, so the failure stays and the line says
    REVIEW, with the UV2 written ("fallback_ok"). The report's footprints stay the real ones; "fallback" holds the
    note. If no step passes, the layer is returned failed (not written), still with its real footprints and notes."""
    foot = spec["packed_for_px"]
    reason = lightmap_too_small(spec, charts)
    if reason is None:
        p = pack(link, mesh, spec)
        rep = layer_report(mesh, p["uvw_ids"], p["uvw"], spec)
        fails = layer_failures(rep, spec)
        if not fails:
            return p, rep, fails
        reason = "its pack failed them"
    start = float(LIGHTMAP_MIN_FOOTPRINT_PX) if foot < LIGHTMAP_MIN_FOOTPRINT_PX else 2.0 * foot
    last = None
    for step in range(LIGHTMAP_FALLBACK_STEPS):
        target = start * 2 ** step
        fb = lightmap_fallback_spec(spec, target)
        if lightmap_too_small(fb, charts) is None:
            p = pack(link, mesh, fb)
            rep = layer_report(mesh, p["uvw_ids"], p["uvw"], fb)
            last = (p, rep, layer_failures(rep, fb))
            if not last[2]:
                break
    else:
        why = "no lightmap UV holds 2-texel gaps up to %.0f px" % target
        if last is None:                          # no step holds the charts: nothing packed
            p, rep, fails = {"uvw_ids": None, "uvw": None, "px_per_unit": 0.0, "fits": False}, {}, [why]
        else:
            p, rep, fails = last
        b = rep.get("bbox_share") or 1.0
        real = _footprints(spec, b, rep.get("bbox_short_side"))
        rep.update({"footprint_px": round(next(iter(real.values())), 2), "fallback": why,
                    "footprints_px": {n: round(v, 2) for n, v in real.items()}})
        rep["warnings"] = [w for w in (lightmap_warning(v, n) for n, v in real.items()) if w]
        if p["uvw_ids"] is not None:              # the effective density at the real footprints
            rep["effective_texels_per_m"], low = _density(spec, real, _areas(mesh, p["uvw_ids"], p["uvw"])[1],
                                                          rep.get("box_fill", 0.0))
            rep["warnings"] += [low] if low else []
        return p, rep, fails
    p, rep, _ = last
    b = rep["bbox_share"] or 1.0
    real = _footprints(spec, b, rep.get("bbox_short_side"))
    feet = _footprints(spec)
    who = min(feet, key=feet.get)
    k = _scale_up(spec, target) if spec.get("lightmapper") == "bakery" else target / foot
    if foot < LIGHTMAP_MIN_FOOTPRINT_PX and target <= LIGHTMAP_MIN_FOOTPRINT_PX:
        advice = ("probe-light it (a Free prop, or a LOD via lod_lightmap: false), or raise its Scale In Lightmap "
                  "%.1fx" % k)
    elif foot < LIGHTMAP_MIN_FOOTPRINT_PX:
        advice = "probe-lit only, or raise its Scale In Lightmap %.1fx" % k
    else:
        advice = "raise its Scale In Lightmap %.1fx, or probe-light it if it is a Free prop" % k
    subject = ("%s gets %.1f px" % (who, foot)) if who else ("its %.1f px" % foot)
    note = ("lightmap UV packed for %.0f px: %s, too small for 2-texel gaps (%s): %s"
            % (target, subject, reason, advice))
    rep.update({"footprint_px": round(next(iter(real.values())), 2),
                "footprints_px": {n: round(v, 2) for n, v in real.items()}, "fallback": note, "fallback_ok": True,
                "packed_for_px": fb["packed_for_px"],
                "pack": {"map_px": fb["map_px"], "pad_px": fb["pad_px"], "margin_px": fb["margin_px"]}})
    rep["effective_texels_per_m"], low = _density(spec, real, _areas(mesh, p["uvw_ids"], p["uvw"])[1],
                                                  rep.get("box_fill", 0.0))       # at the real footprints
    rep["warnings"] = [w for w in (lightmap_warning(v, n) for n, v in real.items()) if w] + [note] + (
        [low] if low else [])
    fails = [] if foot < LIGHTMAP_MIN_FOOTPRINT_PX else [
        "2-texel gaps fit only at %.0f px, not its %.0f px (%s)" % (target, foot, reason)]
    return p, rep, fails


def layer_failures(rep, spec, gate=None, first=False):
    """Failures of one layer_report(): the first texture channel on the distortion gate, its layout and, for a
    filled pack, the coverage floor (lowered for long thin pieces); any other channel (a lightmap among them) on
    its layout only."""
    um = metrics()
    fill = not spec.get("lightmap") and not spec.get("px_per_unit")
    return um.grade(rep, gate, distortion=first, min_coverage=um.MIN_FILL_COVERAGE if (first and fill) else None)


def report_args(spec):
    """uv_metrics.report() keyword arguments for a texture spec (map pixels). A lightmap_spec is graded at its
    measured bounding box instead: use layer_report()."""
    if spec.get("lightmap"):
        raise ValueError("a lightmap spec is graded at the layout's measured bounding box: use layer_report()")
    return {"map_px": spec["map_px"], "pad_px": spec["pad_px"], "margin_px": spec["margin_px"]}


# ----------------------------------------------------------------------------------------------- input
def _ints(a):
    return [int(x) for x in (a.tolist() if hasattr(a, "tolist") else a)]


def _floats(a):
    return [float(x) for x in (a.tolist() if hasattr(a, "tolist") else a)]


def normalise(mesh):
    """A copy of mesh with plain Python ints and floats (RizomUV rejects numpy and float32 values), checked.
    Raises ValueError with what is wrong."""
    try:
        m = {"sizes": _ints(mesh["sizes"]), "xyz_ids": _ints(mesh["xyz_ids"]), "xyz": _floats(mesh["xyz"]),
             "uvw_ids": _ints(mesh["uvw_ids"]), "uvw": _floats(mesh["uvw"])}
    except KeyError as ex:
        raise ValueError("mesh is missing %s (needs sizes, xyz_ids, xyz, uvw_ids, uvw)" % ex) from None
    if not m["sizes"]:
        raise ValueError("the mesh has no polygons")
    if min(m["sizes"]) < 3:
        raise ValueError("a polygon has fewer than 3 corners")
    corners = sum(m["sizes"])
    if len(m["xyz_ids"]) != corners or len(m["uvw_ids"]) != corners:
        raise ValueError("corner counts disagree: sizes sum %d, xyz_ids %d, uvw_ids %d"
                         % (corners, len(m["xyz_ids"]), len(m["uvw_ids"])))
    if len(m["xyz"]) % 3 or len(m["uvw"]) % 3:
        raise ValueError("xyz and uvw must be flat triples")
    if max(m["xyz_ids"]) >= len(m["xyz"]) // 3 or max(m["uvw_ids"]) >= len(m["uvw"]) // 3 \
            or min(m["xyz_ids"]) < 0 or min(m["uvw_ids"]) < 0:
        raise ValueError("a corner index points outside xyz or uvw")
    if not all(math.isfinite(x) for x in m["xyz"]) or not all(math.isfinite(x) for x in m["uvw"]):
        raise ValueError("xyz or uvw contains NaN or infinity")
    if not _any_area(m):
        raise ValueError("every polygon has zero 3D area: the mesh is degenerate")
    return m


def _any_area(m):
    """True as soon as one polygon has a non-zero 3D area (cheap on normal meshes)."""
    xyz, xid, c = m["xyz"], m["xyz_ids"], 0
    for n in m["sizes"]:
        sub = {"sizes": [n], "xyz_ids": xid[c:c + n], "xyz": xyz, "uvw_ids": [0] * n, "uvw": [0.0, 0.0, 0.0]}
        if _areas(sub, sub["uvw_ids"], sub["uvw"])[0] > 0:
            return True
        c += n
    return False


# ----------------------------------------------------------------------------------------------- commands
def load(link, mesh):
    """Fileless load (validated and converted first). A failed Load returns {"Error": ...}; raise on it."""
    m = normalise(mesh)
    r = link.Load({"Data.PolySizes": m["sizes"], "Data.PolyXYZIDs": m["xyz_ids"], "Data.CoordsXYZ": m["xyz"],
                   "Data.PolyUVWIDs": m["uvw_ids"], "Data.CoordsUVW": m["uvw"]})
    if isinstance(r, dict) and "Error" in r:
        raise RuntimeError("RizomUV Load failed: %s" % (r["Error"],))
    return m


def load_layout(link, mesh, uvw_ids, uvw):
    """Load the mesh with a given UV layout (islands come from its UV topology): to pack another channel from
    the same islands, or to export a stretch map of exactly that layout."""
    return load(link, dict(mesh, uvw_ids=uvw_ids, uvw=uvw))


def cut_auto(link, auto):
    """Auto-seam on top of the seams already in the seed topology, cut, then clear the edge selection."""
    link.Select({"PrimType": "Edge", "WorkingSet": "Visible", "Select": True, "ResetBefore": True, "Auto": auto})
    link.Cut({"PrimType": "Edge", "WorkingSet": "Visible"})
    link.Select({"PrimType": "Edge", "WorkingSet": "Visible", "DeSelect": True, "All": True})


def unfold(link, unfold_it=5, opt_it=25, adm=1.0):
    common = {"PrimType": "Island", "WorkingSet": "Visible", "BorderIntersections": True, "TriangleFlips": True}
    link.Unfold(dict(common, Iterations=unfold_it))
    link.Optimize(dict(common, Iterations=opt_it, Mix=1.0, AngleDistanceMix=adm))


def island_count(link):
    return int(link.Count("Lib.Mesh.Islands"))


def save(link):
    """Current UVs as (uvw_ids per corner, flat uvw coords)."""
    d = link.Save({"Data": True})["Data"]
    return list(d["PolyUVWIDs"]), list(d["CoordsUVW"])


def pack(link, mesh, spec):
    """Pack the visible islands into the 0-1 tile. Returns {"uvw_ids", "uvw", "px_per_unit", "fits"}.

    Fill mode keeps one texel density across islands (no Scaling.Mix) and best-fits the layout to the tile.
    Texel-density mode uses USER_SPECIFIED scale = px_per_unit / map_px with Optimization "None" (the default
    "Fill" rescales the whole layout to the tile, losing any absolute scale) and translate-only layout
    (BEST_FIT would rescale again). USER_SPECIFIED, not TEXEL_DENSITY: the latter reads per 100 mesh units.
    If the islands cannot fit at that density, RizomUV leaves them where they were and reports nothing:
    "fits" is False then, and the caller must not use the layout (split the piece, raise map_px or lower the
    density). "fits" says only that the layout is in the tile at the asked scale: uv_metrics.grade() checks
    overlap, padding and margin."""
    # A fileless load leaves the islands in no tile, and Pack then silently does nothing.
    link.IslandGroups({"Mode": "DistributeInTilesEvenly", "WorkingSet": "Visible"})
    rotate = {"Step": spec["rotate_step"]}
    if spec.get("rotate_initial"):
        rotate["Initial"] = spec["rotate_initial"]               # pre-orient each island (directional textures)
    params = {"RootGroup": "RootGroup", "WorkingSet": "Visible", "ProcessTileSelection": False, "RecursionDepth": 1,
              "Translate": True, "UsePixelUnit": True, "PaddingSizePx": spec["pad_px"],
              "MarginSizePx": spec["margin_px"], "MapResolution": spec["map_px"], "Strategy": "PaddingPerfect",
              "Rotate": rotate, "Device": spec.get("device", "CPU")}
    want = None
    if spec.get("px_per_unit"):
        want = spec["px_per_unit"] / spec["map_px"]
        params["Scaling"] = {"Mode": SCALING_USER, "SpecifiedScale": want, "Optimization": "None"}
        params["LayoutScalingMode"] = LAYOUT_TRANSLATE_ONLY
    else:
        params["Scaling"] = {"Mode": SCALING_AVG_MOVABLE}
        params["LayoutScalingMode"] = LAYOUT_BEST_FIT
    link.Pack(params)
    ids, uvw = save(link)
    ratio = linear_ratio(mesh, ids, uvw)
    fits = in_unit_tile(uvw) and (want is None or abs(ratio / want - 1.0) < 0.02)
    return {"uvw_ids": ids, "uvw": uvw, "px_per_unit": ratio * spec["map_px"], "fits": fits}


def stretch_map(link, mesh, path, size=768, band=1.25):
    """RizomUV's own stretch grading of the layout it holds now, as a PNG. Returns the neutral used.

    RizomUV grades LINEAR scale (UV length / 3D length): measured 2026-10-17 on 2027.0.598, where a neutral of
    sqrt(UV area / 3D area) gives a grey map and the area ratio (what RasterExport's docstring describes) a map
    saturated blue. Its neutral must be the layout's mean linear ratio, or the whole map comes out one flat colour.
    Measured colours: red = UV smaller than neutral (fewer texels per metre), blue = UV larger (more texels per
    metre), saturating at neutral / band and x band.
    The path is made absolute and its folder created; RizomUV writes nothing for a relative path or a missing
    folder, so the file is checked afterwards."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.isfile(path):
        os.remove(path)
    ids, uvw = save(link)
    neutral = linear_ratio(mesh, ids, uvw)
    link.RasterExport({"WorkingSet": "Visible", "FilePath": path.replace("\\", "/"), "Width": float(size),
                       "Height": float(size), "PolygonColorMode": "Stretches", "AASamples": 4,
                       "EdgeColorMode": "Color", "EdgeColor": [0.1, 0.1, 0.1], "BackgroundColor": [0.12, 0.12, 0.12],
                       "Stretches": {"Neutral": neutral, "Min": neutral / band, "Max": neutral * band,
                                     "Saturation": 1.0}})
    if not os.path.isfile(path):
        raise RuntimeError("RizomUV did not write the stretch map %s" % path)
    return neutral


# ----------------------------------------------------------------------------------------------- helpers
def _areas(mesh, uvw_ids, uvw):
    """Total exact polygon area in 3D (Newell) and in UV (shoelace); concave polygons are handled."""
    xyz, xid, sizes = mesh["xyz"], mesh["xyz_ids"], mesh["sizes"]
    a2 = a3 = 0.0
    c = 0
    for n in sizes:
        o = 3 * xid[c]
        ox, oy, oz = xyz[o], xyz[o + 1], xyz[o + 2]
        nx = ny = nz = 0.0
        s = 0.0
        for k in range(n):
            i, j = c + k, c + (k + 1) % n
            pi, pj = 3 * xid[i], 3 * xid[j]
            x1, y1, z1 = xyz[pi] - ox, xyz[pi + 1] - oy, xyz[pi + 2] - oz
            x2, y2, z2 = xyz[pj] - ox, xyz[pj + 1] - oy, xyz[pj + 2] - oz
            nx += y1 * z2 - z1 * y2
            ny += z1 * x2 - x1 * z2
            nz += x1 * y2 - y1 * x2
            ui, uj = 3 * uvw_ids[i], 3 * uvw_ids[j]
            s += uvw[ui] * uvw[uj + 1] - uvw[uj] * uvw[ui + 1]
        a3 += math.sqrt(nx * nx + ny * ny + nz * nz) / 2
        a2 += abs(s) / 2
        c += n
    return a3, a2


def mesh_area(mesh):
    """Total 3D surface area of a mesh dict (in m2 for metre input)."""
    return _areas(mesh, mesh["xyz_ids"], [0.0] * (3 * (max(mesh["xyz_ids"]) + 1)))[0]


def linear_ratio(mesh, uvw_ids, uvw):
    """Mesh-wide sqrt(UV area / 3D area): the UV length per unit of 3D length."""
    a3, a2 = _areas(mesh, uvw_ids, uvw)
    return math.sqrt(a2 / a3) if a3 > 0 and math.isfinite(a2) else 0.0


def in_unit_tile(uvw, eps=1e-6):
    us, vs = uvw[0::3], uvw[1::3]
    if not all(math.isfinite(x) for x in us) or not all(math.isfinite(x) for x in vs):
        return False
    return min(us) >= -eps and min(vs) >= -eps and max(us) <= 1 + eps and max(vs) <= 1 + eps


def texture_size(px_per_m, area_m2, coverage=0.65, cap=2048, floor=64):
    """Power-of-two map size that holds area_m2 of surface at px_per_m, given the expected packing coverage."""
    need = px_per_m * math.sqrt(area_m2 / coverage)
    return int(min(cap, max(floor, 2 ** math.ceil(math.log2(max(need, 1.0))))))


def _merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in extra.items():
        out[k] = copy.deepcopy(v)
    return out


# ----------------------------------------------------------------------------------------------- pipelines
def unwrap(link, mesh, auto, unfold_it=5, opt_it=25, adm=1.0):
    """Load, auto-seam, unfold and optimise. Leaves the result in RizomUV; returns the island count."""
    load(link, mesh)
    cut_auto(link, auto)
    unfold(link, unfold_it, opt_it, adm)
    return island_count(link)


def unwrap_and_pack(link, mesh, kind="hard", packs=None, auto=None, **unfold_kw):
    """One unwrap, then each pack in order on the same islands (e.g. a texture UV then a lightmap UV).
    No grading: unwrap_gated is the graded version."""
    packs = packs or {"uv0": pack_spec(1024)}
    t = time.perf_counter()
    islands = unwrap(link, mesh, auto or PRESETS[resolve_kind(kind)], **dict(UNFOLD, **unfold_kw))
    out = {"islands": islands, "packs": {}}
    for name, spec in packs.items():
        out["packs"][name] = pack(link, mesh, spec)
    out["seconds"] = round(time.perf_counter() - t, 3)
    return out


def unwrap_gated(link, mesh, kind="hard", packs=None, gate=None, ladder=None, auto=None, time_budget=None,
                 **unfold_kw):
    """Unwrap, pack the FIRST channel and grade it (layer_report / layer_failures: the distortion gate, a partial
    gate merged over uv_metrics.GATE; the layout: in the tile, no overlap, padding and margin as asked, no flips;
    and for a filled pack the coverage floor), climbing the retry ladder on a failure. When the hard preset covers
    too little (one sprawling island: 1-segment chamfered boxes measured 0.10-0.22, where the ladder's steps did not
    help and the organic preset gave 0.53-0.75) or its texel-density pack does not fit (a bevel ring joined into one
    long island: a 2.4 m bevelled strip did not fit 2048 px at 512 px/m, the organic preset fitted), the organic
    preset is tried next; any other attempt that does not fit ends the ladder. The chosen attempt is the first that
    passes, else the least failing (fitting first, then fewest failures, then lowest angular p95). With time_budget
    (seconds), no new attempt starts once the slowest attempt so far would overrun it.
    The chosen first-channel layout is then reloaded and the other channels are packed from exactly its islands
    and graded on their layout (a lightmap_spec at its measured footprints), so every channel and any later stretch
    map show the attempt that is returned. A lightmap channel goes through pack_lightmap (packed for 64 px when its
    own footprint is too small for 2-texel gaps).
    Returns {"islands", "packs", "reports", "failures", "gate_failures", "report", "distortion", "attempt",
    "attempts", "seconds"}: reports and failures per channel; gate_failures, report and distortion are the first
    channel's."""
    t = time.perf_counter()
    ladder = RETRY_LADDER if ladder is None else ladder
    packs = packs or {"uv0": pack_spec(1024)}
    first_name = next(iter(packs))
    first_spec = packs[first_name]
    base = auto or PRESETS[resolve_kind(kind)]
    queue = [("preset " + (resolve_kind(kind) if auto is None else "custom"), base)]
    queue += [(label, _merge(base, step)) for label, step in ladder]
    organic_next = auto is None and resolve_kind(kind) == "hard"
    best, log, slowest = None, [], 0.0
    while queue:
        label, params = queue.pop(0)
        if best is not None and time_budget and (time.perf_counter() - t) + slowest > time_budget:
            log.append({"attempt": label, "skipped": "time budget %g s" % time_budget})
            break
        t0 = time.perf_counter()
        islands = unwrap(link, mesh, params, **dict(UNFOLD, **unfold_kw))
        first = pack(link, mesh, first_spec)
        rep = layer_report(mesh, first["uvw_ids"], first["uvw"], first_spec,
                           region_angle=params.get("SharpEdges", {}).get("AngleMin"))
        fails = layer_failures(rep, first_spec, gate, first=True)
        dist = rep["distortion"]
        slowest = max(slowest, time.perf_counter() - t0)
        log.append({"attempt": label, "islands": islands, "gate_failures": fails,
                    "angular_p95": dist["angular_p95"], "coverage": rep["coverage"], "fits": first["fits"]})
        cand = {"islands": islands, "first": first, "report": rep, "gate_failures": fails, "attempt": label}
        rank = (not first["fits"], len(fails), dist["angular_p95"])
        if best is None or rank < best["rank"]:
            best = dict(cand, rank=rank)
        if first["fits"] and not fails:
            break
        if organic_next and (not first["fits"] or any(f.startswith("coverage") for f in fails)):
            queue.insert(0, ("organic preset", PRESETS["organic"]))     # the hard cut joined a bevel or chamfer
            organic_next = False                                        # ring into one island; the ladder keeps it
            continue
        if not first["fits"]:                       # the ladder's steps cannot make an overflowing density fit
            break
    last = [a for a in log if "skipped" not in a][-1]["attempt"]
    out = {"islands": best["islands"], "packs": {first_name: best["first"]},
           "reports": {first_name: best["report"]}, "failures": {first_name: best["gate_failures"]},
           "distortion": best["report"]["distortion"], "report": best["report"],
           "gate_failures": best["gate_failures"], "attempt": best["attempt"], "attempts": log}
    rest = [n for n in packs if n != first_name]
    if rest or best["attempt"] != last:
        load_layout(link, mesh, best["first"]["uvw_ids"], best["first"]["uvw"])   # RizomUV now holds the choice
        for name in rest:
            spec = packs[name]
            if spec.get("lightmap"):
                p, rep, fails = pack_lightmap(link, mesh, spec, best["islands"])
            else:
                p = pack(link, mesh, spec)
                rep = layer_report(mesh, p["uvw_ids"], p["uvw"], spec)
                fails = layer_failures(rep, spec)                    # graded whether or not it fits
            out["packs"][name], out["reports"][name], out["failures"][name] = p, rep, fails
        if rest:
            load_layout(link, mesh, best["first"]["uvw_ids"], best["first"]["uvw"])
    out["seconds"] = round(time.perf_counter() - t, 3)
    return out
