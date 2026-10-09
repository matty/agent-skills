"""Unwrap and pack a mesh in RizomUV, fileless: flat arrays in, flat arrays out.

Host: any Python 3.6-3.13 (no bpy; numpy only for unwrap_gated, through uv_metrics.py). Blender users want
blender_rizom.py, which builds the arrays and writes the UV layers for you.

    import sys; sys.path.insert(0, r"<skill>/scripts")
    from rizom_link import rizom_session
    import rizom_uv as ru
    with rizom_session() as link:
        res = ru.unwrap_gated(link, mesh, kind="organic",
                              packs={"uv0": ru.pack_spec(1024, 8, 4), "uv2": ru.pack_spec(128, 4, 2)})
    res["packs"]["uv0"]["uvw_ids"], res["packs"]["uv0"]["uvw"]   # write back corner by corner

`mesh` is a dict in RizomUV's own Data layout (lists, tuples or numpy arrays; load() converts them):
    sizes    [P]   corner count per polygon (n-gons are fine)
    xyz_ids  [C]   3D vertex index per corner, polygon by polygon
    xyz      [3V]  3D coordinates, flat. In metres if you want texel density in px/m
    uvw_ids  [C]   UV vertex index per corner. A 3D vertex split into several UV vertices is a seam
    uvw      [3U]  seed UV coordinates, flat. Seed with the 3D positions, never zeros: Unfold sizes islands from
                   the seed area
Polygon and corner order are preserved, so the results map straight back onto the source corners.
"""

import copy
import math
import os
import time

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

# Tried in order when a piece fails the distortion gate; each step is merged over the preset.
RETRY_LADDER = [
    ("stretch limiter 0.85", {"Quality": 0.85}),
    ("mosaic 0.9", {"QuasiDevelopable": {"Developability": 0.9, "IslandPolyNBMin": 1, "FitCones": True,
                                         "AreaMinRatio": 0.01}, "Quality": 0.85}),
]

# Pack enums, measured on 2027.0.598 by probe_pack_enums.py (0-based in the documented order).
SCALING_AVG_MOVABLE, SCALING_USER = 2, 6
LAYOUT_TRANSLATE_ONLY, LAYOUT_BEST_FIT = 1, 2


def resolve_kind(kind):
    """Preset name, case-insensitive. Raises ValueError naming the valid ones."""
    k = str(kind).strip().lower()
    if k not in PRESETS:
        raise ValueError("unknown kind %r: use one of %s" % (kind, ", ".join(sorted(PRESETS))))
    return k


def pack_spec(map_px, pad_px, margin_px, px_per_unit=None, rotate_step=90.0, device="CPU"):
    """One packing target. px_per_unit=None fills the 0-1 tile (best for lightmaps and per-piece maps);
    a number packs at that texel density instead (texels per mesh unit, i.e. px/m for metre input).
    device: "CPU" (default: deterministic, leaves the GPU to bakes and everything else) or "FastestGPU" (CUDA)."""
    if device not in ("CPU", "FastestGPU"):
        raise ValueError("device must be 'CPU' or 'FastestGPU', not %r" % (device,))
    return {"map_px": int(map_px), "pad_px": int(pad_px), "margin_px": int(margin_px),
            "px_per_unit": px_per_unit, "rotate_step": float(rotate_step), "device": device}


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
    link.Optimize(dict(common, Iterations=opt_it, Mix=1, AngleDistanceMix=adm))


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
    density)."""
    # A fileless load leaves the islands in no tile, and Pack then silently does nothing.
    link.IslandGroups({"Mode": "DistributeInTilesEvenly", "WorkingSet": "Visible"})
    params = {"RootGroup": "RootGroup", "WorkingSet": "Visible", "ProcessTileSelection": False, "RecursionDepth": 1,
              "Translate": True, "UsePixelUnit": True, "PaddingSizePx": spec["pad_px"],
              "MarginSizePx": spec["margin_px"], "MapResolution": spec["map_px"], "Strategy": "PaddingPerfect",
              "Rotate": {"Step": spec["rotate_step"]}, "Device": spec.get("device", "CPU")}
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

    RizomUV grades LINEAR scale (UV length / 3D length). Its neutral must be the layout's mean linear ratio,
    or the whole map comes out one flat colour. Measured colours: red = UV smaller than neutral (fewer texels
    per metre), blue = UV larger (more texels per metre), saturating at neutral / band and x band.
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


def lightmap_footprint(area_m2, texels_per_m, scale_in_lightmap=1.0, lo=64, hi=1024):
    """Power-of-two lightmap rectangle for one renderer (Unity/Bakery packs each renderer separately)."""
    need = math.sqrt(area_m2) * texels_per_m * scale_in_lightmap
    return int(min(hi, max(lo, 2 ** math.ceil(math.log2(max(need, 1.0))))))


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
    """One unwrap, then each pack in order on the same islands (e.g. a texture UV then a lightmap UV)."""
    packs = packs or {"uv0": pack_spec(1024, 8, 4)}
    t = time.perf_counter()
    islands = unwrap(link, mesh, auto or PRESETS[resolve_kind(kind)], **dict(UNFOLD, **unfold_kw))
    out = {"islands": islands, "packs": {}}
    for name, spec in packs.items():
        out["packs"][name] = pack(link, mesh, spec)
    out["seconds"] = round(time.perf_counter() - t, 3)
    return out


def unwrap_gated(link, mesh, kind="hard", packs=None, gate=None, ladder=None, auto=None, **unfold_kw):
    """Unwrap, pack the FIRST channel and grade it against the distortion gate, climbing the retry ladder on a
    failure. The chosen attempt is the first that passes, else the least distorted (fewest failures, then lowest
    angular p95) with "gate_failures" filled in so the piece goes to review instead of being accepted silently.
    The chosen first-channel layout is then reloaded and the other channels are packed from exactly its
    islands, so every channel and any later stretch map show the attempt that is returned.
    Returns {"islands", "packs", "distortion", "gate_failures", "attempt", "attempts", "seconds"}."""
    import uv_metrics as um  # numpy; only needed here

    t = time.perf_counter()
    gate = um.GATE if gate is None else gate
    ladder = RETRY_LADDER if ladder is None else ladder
    packs = packs or {"uv0": pack_spec(1024, 8, 4)}
    first_name = next(iter(packs))
    base = auto or PRESETS[resolve_kind(kind)]
    attempts = [("preset " + (kind if auto is None else "custom"), base)]
    attempts += [(label, _merge(base, step)) for label, step in ladder]
    best, log = None, []
    for label, params in attempts:
        islands = unwrap(link, mesh, params, **dict(UNFOLD, **unfold_kw))
        first = pack(link, mesh, packs[first_name])
        dist = um.distortion(mesh, first["uvw_ids"], first["uvw"])
        fails = um.check_gate(dist, gate)
        log.append({"attempt": label, "islands": islands, "gate_failures": fails,
                    "angular_p95": dist["angular_p95"]})
        cand = {"islands": islands, "first": first, "distortion": dist, "gate_failures": fails, "attempt": label}
        if best is None or (len(fails), dist["angular_p95"]) < (len(best["gate_failures"]),
                                                                 best["distortion"]["angular_p95"]):
            best = cand
        if not fails:
            break
    out = {"islands": best["islands"], "packs": {first_name: best["first"]}, "distortion": best["distortion"],
           "gate_failures": best["gate_failures"], "attempt": best["attempt"], "attempts": log}
    rest = [n for n in packs if n != first_name]
    if rest or best["attempt"] != log[-1]["attempt"]:
        load_layout(link, mesh, best["first"]["uvw_ids"], best["first"]["uvw"])   # RizomUV now holds the choice
        for name in rest:
            out["packs"][name] = pack(link, mesh, packs[name])
        if rest:
            load_layout(link, mesh, best["first"]["uvw_ids"], best["first"]["uvw"])
    out["seconds"] = round(time.perf_counter() - t, 3)
    return out
