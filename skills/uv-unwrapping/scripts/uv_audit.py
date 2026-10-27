"""Audit a UV layout in Blender, set texel density, and lay out or pack it with padding given in pixels.

Host: Blender 4.1+ with its bundled numpy (Mesh.corner_normals); tested on Blender 5.2.2. No add-ons, no RizomUV.
The maths (measure, measure_shared, footprint_px, uv_box_share, map_size and the helpers they call) also runs in
plain Python with numpy and no bpy, which is how the repo's tests check it.

    import sys; sys.path.insert(0, r"<skill>/scripts")
    import uv_audit as ua
    st = ua.apply_stack(ob)                                         # modifiers from the top; Triangulate off for now
    if st["hard_surface"]:
        ua.seams_by_angle([ob])                                     # a hard-surface stack: never shade it by angle
    ua.seams_from_hard_edges(objs)                                  # a seam on every hard edge
    ua.apply_stack(ob, keep_mirror=False)                           # just before layout: a Mirror kept live
    ua.layout(objs, map_px=2048, px_per_m=512, bake=True)           # UV0: density, one pack, fit check, +1 U copies
    ua.tile_project(kit_pieces, tile_m=1.0, material="M_EXT_*")     # tiling: phase 0 at each pivot, joints continue
    ua.audit_selected(purpose="unique", map_px=2048, px_per_m=512, baking=True, directional=True)
    ua.audit_selected(purpose="trim", map_px="2048x1024", px_per_m=512, rows=[(0, 128), (128, 192)],
                      material="M_Trim*")                           # one material of a mixed mesh
    ua.pack_lightmap(objs, texels_per_m=20)                         # UV2: 2-texel gaps at any scale; LODs 0.5^n
    ua.audit_selected(texels_per_m=20)                              # UV2 at the footprint of its measured box

Every function works on UV0 (layer=0) unless given another layer ("active": the active map); the lightmap calls
(pack_lightmap, lightmap_footprint, an audit with a lightmap purpose or texels_per_m) default to the second map.
Command line (one line per object; exit code 1 when anything needs a look, 2 for a bad request):
    blender -b --factory-startup --python-exit-code 1 scene.blend --python uv_audit.py -- --objects "KIT_*"
            --purpose unique|tiling|trim|lightmap --map 1024|2048x1024|165.2 [--layer 0|1|name|active]
            [--material "M_Trim*"] [--pad 16] [--td 512]
            [--baking] [--directional] [--text] [--rows 0-128,128-192] [--lightmap-texels 20 --lightmap-scale 1]
            [--lightmapper unity|bakery] [--lod 1] [--shared] [--tile-m 1 --steps 1,3] [--json r.json]

Purposes: unique (own texture or atlas: inside 0-1, no partial overlaps, gap map/64), tiling and trim (may run
outside 0-1 and overlap: distortion, density per island, strip direction and rows), lightmap (inside 0-1, nothing
stacked, charts cut at hard edges, 2 texels between charts at the footprint, LODs at 0.5^n, a note when the charts
fill under half their bounding box). The manual (report fields, every issue, accuracy, side effects) is
references/uv-audit.md.
"""

import fnmatch
import json
import math
import re
import sys

import numpy as np

try:
    import bpy
except ImportError:          # plain Python: measure() and the helpers work, the Blender functions do not
    bpy = None

PURPOSES = ("unique", "tiling", "trim", "lightmap")
# The gate. This skill owns these numbers; rizomuv-uv-pipeline and vrchat-world-qa state the same values.
LIMITS = {"angular_p95": 1.15, "angular_p99": 1.5, "angular_max": 2.0, "area_p95": 0.20, "area_max": 2.0,
          "texel_cv": 0.15}
# The whole-object percentiles hide a small island: a label on 2.5% of a crate stretched 1.45x passed p95 and p99, and
# one on 0.83% stretched 1.95x passed everything but a max that skips slivers. So every island holding at least this
# share of the area (and the uv_text faces together) must meet the p95 limits on its own; area_max (log2, non-sliver
# faces) catches a patch at 2x or 1/2 its island's texel density, which slivers round it had absorbed (measured 5.2.2).
ISLAND_MIN_SHARE = 0.005
# Texel density against a target, as a factor: shared materials (tiling, trim) within 10%, unique and atlas textures
# within 0.8-1.25x of their class; checked on the mean and on every island not marked low-density (a lightmap: the
# mean only). Evenness inside a piece is texel_cv.
TEXEL_BAND = {"unique": (0.8, 1.25), "tiling": (0.9, 1.1), "trim": (0.9, 1.1), "lightmap": (0.8, 1.25)}
SLIVER_QUALITY = 0.02        # 3D triangle quality 4*sqrt(3)*area / sum(edge^2): 1 = equilateral; below this, a sliver
ZERO_UV_SHARE = 0.01         # a triangle with under this share of its island's UV area per 3D area is collapsed
ZERO_UV_PX2 = 1e-3           # a layout mapping under this many square pixels per square metre has collapsed whole
HARD_EDGE_DEG = 0.5          # corner normals further apart than this make an edge hard (a Triangulate with Keep
                             # Normals re-encodes custom normals with 0.006-0.035 deg splits, which are not hard)
UV_EPS = 1e-6                # UVs closer than this are the same UV vertex
RASTER_MIN = 1024            # coverage, overlap and gaps are rasterised at least this many pixels across ...
RASTER_MAX = 2048            # ... and at most this many (a 4096 map is rasterised at half resolution)
MAX_UV_MAPS = 8              # the most UV maps an engine keeps (engine notes)
ELONGATED = 1.5              # orientation check: islands at least this much longer than wide
LIGHTMAP_GAP_TEXELS = 2      # lightmap charts: at least 2 texels apart, 1 texel to the tile edge
LIGHTMAP_HARD_ANGLE = 88.0   # a lightmap chart must not continue across a hard edge or a bend over this (deg)
BEND_MIN_PX2 = 0.01          # ... unless both faces at the bend cover under this many square texels (sub-texel folds)
FOOTPRINT_COVERAGE = 0.85    # b, the UV2 bounding-box share of the 0-1 tile: planning estimate (the dry-run wall's)
LIGHTMAP_BOX_FILL_NOTE = 0.5 # a lightmap audit notes UV2 charts filling less than this share of their bounding box
LIGHTMAP_MIN_FOOTPRINT_PX = 64  # house guidance: a UV2 too small for 2-texel gaps is packed and checked for 64 px
LOD_SCALE = 0.5              # each LOD level halves a renderer's lightmap texel scale (LOD1 0.5, LOD2 0.25; Unity)
LIGHTMAPPERS = ("unity", "bakery")   # whose footprint the lightmap calls use; "progressive" is accepted for unity
BAKERY_AREA_FACTOR = 2.0     # Bakery sizes a renderer by the sum of |cross| over its triangles: 2 x its area
BAKERY_INSET_TEXELS = 3      # Bakery's Default atlas packer insets each rect this much (engine notes)
EFFECTIVE_DENSITY_MIN = 0.5  # Bakery: an issue when the charts get under this share of the planned texels per metre
UNWRAP_MARGIN = 0.001       # unwrap with this margin: at 0, islands that land touching along a seam fuse into one
TILE_PHASE_PX = 0.5          # tile_phase: a tiling face further than this many texels from tile_project's UVs (mod
                             # whole tiles) breaks the pattern at a joint
TILE_AXIS_TIE = 1e-4         # tile_uv: normal components this close to the largest count as a tie (a 45 deg chamfer),
                             # broken Z, then X, then Y, so float32 and float64 normals pick the same plane
EDGE_SLACK_PX = 1e-3         # float noise allowed on the margin to the tile edge (a FRACTION pack is exact)
LOW_DENSITY_ATTR = "uv_low_density"
TEXT_ATTR = "uv_text"        # boolean face attribute: these faces carry text or decals (what text=True checks)
TEXT_UP_ATTR = "uv_text_up"  # optional face vector: the 3D direction the letters' up points to (default world +Z)
SEAM_ANGLE = 30.0            # seams_by_angle: an edge whose faces meet at more than this (deg), like Smooth by Angle
# Modifier types that change topology. Before seams, apply_stack applies the stack from the top down to and including
# the last of them (a Smooth by Angle or anything else above it goes with it), never a lower one alone.
TOPOLOGY_TYPES = frozenset({"ARRAY", "BEVEL", "BOOLEAN", "BUILD", "DECIMATE", "EDGE_SPLIT", "MASK", "MIRROR",
                            "MULTIRES", "REMESH", "SCREW", "SKIN", "SOLIDIFY", "SUBSURF", "WELD", "WIREFRAME"})


# ----------------------------------------------------------------------------------------------- sizes and rules
def map_size(map_px):
    """(width, height) in whole pixels from 1024, 165.2 (a fractional footprint: rounded down), (2048, 1024),
    "2048x1024" or "165.2"."""
    if isinstance(map_px, str):
        w, _, h = map_px.lower().partition("x")
        w, h = float(w), float(h or w)
    elif isinstance(map_px, (tuple, list)):
        w, h = float(map_px[0]), float(map_px[1])
    else:
        w = h = float(map_px)
    w, h = int(math.floor(w + 1e-9)), int(math.floor(h + 1e-9))
    if w < 1 or h < 1:
        raise ValueError("a map must be at least 1 px across, not %r" % (map_px,))
    return w, h


def default_pad(map_px, purpose="unique"):
    """The gap between islands used when none is given: map_px / 64 (16 px at 1024) for a texture, 2 texels for a
    lightmap at its footprint, none for tiling and trim layers (their islands may overlap)."""
    if purpose == "lightmap":
        return float(LIGHTMAP_GAP_TEXELS)
    if purpose in ("tiling", "trim"):
        return None
    return max(map_size(map_px)) / 64.0


def lightmapper_name(name):
    """unity (also "progressive", the world spec's lighting.baker for it) or bakery; raises ValueError otherwise."""
    n = str(name or "unity").strip().lower()
    n = "unity" if n == "progressive" else n
    if n not in LIGHTMAPPERS:
        raise ValueError("lightmapper must be unity (or progressive) or bakery, not %r" % (name,))
    return n


def lod_factor(lod, lightmapper="unity"):
    """The lightmap texel-scale factor of LOD n: Unity's 0.5^n; Bakery sizes each LOD by its own area, so 1."""
    return LOD_SCALE ** int(lod or 0) if lightmapper_name(lightmapper) == "unity" else 1.0


def footprint_px(area_m2, texels_per_m, scale=1.0, coverage=FOOTPRINT_COVERAGE, lightmapper="unity",
                 short_side=None):
    """The lightmap texel scale of a renderer's UV2, in texels per UV unit (the side its whole 0-1 tile would have).
    Unity: texels_per_m x sqrt(area / b) x scale, b (coverage) = the bounding box of ALL its UV2 charts together as a
    share of the tile, scale = the renderer's lightmap scale x LOD_SCALE^n for LOD n. A lightmapper packs only that box
    (Unity 2022.3, measured 2026-10-17), so the atlas cost is (texels_per_m x scale)^2 x area whatever the layout.
    b = 0.85 plans before a UV2 exists; b = 1 is the smallest texel scale (what UV2 gaps are packed for).
    Bakery: a rect of side L = texels_per_m x sqrt(2 x area x scale) on the box's short side (scale = Scale In
    Lightmap, acting on the area, no LOD factor), its Default packer's 3-texel inset taken off: (L - 6) / short_side,
    short_side = the box's short side in UV, sqrt(b) (a square box) when not given; 1 is the smallest texel scale."""
    if lightmapper_name(lightmapper) == "bakery":
        side = texels_per_m * math.sqrt(BAKERY_AREA_FACTOR * max(float(area_m2), 0.0) * max(float(scale), 0.0))
        short = math.sqrt(max(float(coverage), 1e-9)) if short_side is None else max(float(short_side), 1e-9)
        return max(side - 2.0 * BAKERY_INSET_TEXELS, 0.0) / short
    return texels_per_m * math.sqrt(max(float(area_m2), 0.0) / max(float(coverage), 1e-9)) * scale


def scale_factor(footprint, want_px, lightmapper="unity"):
    """How much to multiply Scale In Lightmap by to take a footprint to want_px (with the box filling the tile):
    Unity's is linear, Bakery's acts on the area (and its inset stays)."""
    footprint = max(float(footprint), 1e-9)
    if lightmapper_name(lightmapper) == "bakery":
        return ((want_px + 2.0 * BAKERY_INSET_TEXELS) / (footprint + 2.0 * BAKERY_INSET_TEXELS)) ** 2
    return want_px / footprint


def lightmap_capacity_px(charts, gap_texels=LIGHTMAP_GAP_TEXELS, edge_texels=1.0):
    """The smallest b = 1 footprint (texels on a side) that can hold `charts` charts on a square grid, gap_texels
    apart and edge_texels from the tile edge, even as points: below it 2-texel gaps are impossible whatever the packer
    does (6 charts: 6 px). The same bound as rizomuv-uv-pipeline's."""
    k = int(math.ceil(math.sqrt(max(int(charts), 1))))
    return (k - 1) * gap_texels + 2.0 * edge_texels


def lightmap_small_note(footprint, reason=None, lod=0, lightmapper="unity"):
    """The note for a UV2 whose footprint is under 64 px. reason (from pack_lightmap): why it was packed for 64 px
    instead; without it, the audit's note that it checks the layout as packed for 64 px. The probe-lit advice is
    judged on LOD0 only: a LOD1+ follows its piece. The Scale In Lightmap factor is the lightmapper's."""
    head = ("UV2 packed for %d px: %.1f px is too small for 2-texel gaps (%s)"
            % (LIGHTMAP_MIN_FOOTPRINT_PX, footprint, reason) if reason else
            "lightmap footprint %.1f px is under %d: checked as packed for %d px"
            % (footprint, LIGHTMAP_MIN_FOOTPRINT_PX, LIGHTMAP_MIN_FOOTPRINT_PX))
    if lod:
        return ("%s; LOD%d follows its piece: lightmapped with its LOD0, or probe-lit via lod_lightmap: false"
                % (head, lod))
    return ("%s; probe-light it if it is a Free prop (a Free-sized PROP or FOL piece), else raise its Scale In "
            "Lightmap %.1fx to light it" % (head, scale_factor(footprint, LIGHTMAP_MIN_FOOTPRINT_PX, lightmapper)))


def lod_level(name):
    """n of an object named <Piece>_LOD<n> (a Blender .001 suffix allowed), else 0."""
    m = re.search(r"_LOD(\d+)(\.\d+)?$", name or "")
    return int(m.group(1)) if m else 0


def uv_box_share(uv):
    """b: the bounding box of a whole UV layout (all its charts together, not their own area), clipped to the 0-1
    tile, as a share of the tile."""
    uv = np.asarray(uv, float).reshape(-1, 2)
    if not len(uv):
        return 1.0
    lo, hi = np.clip(uv.min(0), 0, 1), np.clip(uv.max(0), 0, 1)
    return float(max((hi - lo).prod(), 1e-9))


def uv_box_short_side(uv):
    """The short side of that bounding box, clipped to the tile, in UV units (Bakery maps it onto its rect's side)."""
    uv = np.asarray(uv, float).reshape(-1, 2)
    if not len(uv):
        return 1.0
    lo, hi = np.clip(uv.min(0), 0, 1), np.clip(uv.max(0), 0, 1)
    return float(max((hi - lo).min(), 1e-9))


def parse_rows(rows):
    """Trim rows as [(v0_px, v1_px), ...] from "0-128,128-192" or a list of pairs."""
    if not rows:
        return []
    if isinstance(rows, str):
        rows = [tuple(float(x) for x in part.split("-", 1)) for part in rows.split(",") if part.strip()]
    return sorted((float(min(a, b)), float(max(a, b))) for a, b in rows)


def _purpose(purpose, lightmap=False, texels_per_m=None):
    """The audit's purpose: lightmap=True or a lightmap texel density makes it a lightmap audit; either one given
    with another purpose is a mistake (one of them would be ignored), so it raises."""
    if texels_per_m and purpose not in (None, "lightmap"):
        raise ValueError("texels_per_m (--lightmap-texels) sizes a lightmap audit; it cannot go with purpose %r"
                         % purpose)
    if lightmap and purpose not in (None, "lightmap"):
        raise ValueError("lightmap=True (--lightmap) is a lightmap audit; it cannot go with purpose %r" % purpose)
    p = "lightmap" if (lightmap or texels_per_m) else (purpose or "unique")
    if p not in PURPOSES:
        raise ValueError("purpose must be one of %s, not %r" % (", ".join(PURPOSES), p))
    return p


def _resolve_layer(layer, purpose="unique"):
    """The UV map an audit reads: given as an index or a name; None means 0 (UV0) for a texture and 1 (the second
    map) for a lightmap; "active" means whichever map is active."""
    if layer is None:
        return 1 if purpose == "lightmap" else 0
    if layer == "active":
        return None
    return layer


# ----------------------------------------------------------------------------------------------- mesh data (bpy)
def _layer(me, layer):
    if not me.uv_layers:
        return None
    if layer is None or layer == "active":
        return me.uv_layers.active or me.uv_layers[0]
    if isinstance(layer, int):
        return me.uv_layers[layer] if layer < len(me.uv_layers) else None
    return me.uv_layers.get(layer)


def _face_marks(me, attr, layer_name):
    """Per-face booleans from the face attribute <attr>_<UV map name> (that map only), else <attr> (every map); all
    False when the mesh has neither. attr: uv_low_density or uv_text."""
    at = me.attributes.get("%s_%s" % (attr, layer_name)) if layer_name else None
    if at is None:
        at = me.attributes.get(attr)
    n = len(me.polygons)
    if at is None or at.domain != "FACE" or at.data_type != "BOOLEAN" or len(at.data) != n:
        return np.zeros(n, bool)
    vals = np.zeros(n, bool)
    at.data.foreach_get("value", vals)
    return vals


def _low_faces(me, layer_name):
    return _face_marks(me, LOW_DENSITY_ATTR, layer_name)


def _face_vectors(me, attr, rot):
    """Per-face unit vectors in world space from a FACE / FLOAT_VECTOR attribute (rot: the object's 3x3 matrix);
    None when the mesh has none. Zero vectors stay zero (no direction given)."""
    at = me.attributes.get(attr)
    n = len(me.polygons)
    if at is None or at.domain != "FACE" or at.data_type != "FLOAT_VECTOR" or len(at.data) != n:
        return None
    v = np.empty(n * 3)
    at.data.foreach_get("vector", v)
    v = v.reshape(-1, 3) @ np.asarray(rot, float).T
    ln = np.linalg.norm(v, axis=1)
    return np.where(ln[:, None] > 1e-12, v / np.maximum(ln, 1e-12)[:, None], 0.0)


def _subset(d, keep):
    """The flat arrays d cut down to the polygons where keep is True (vertices are kept whole)."""
    keep = np.asarray(keep, bool)
    lt = d["lt"]
    loop_keep = np.repeat(keep, lt)
    new_lt = lt[keep]
    new_ls = np.concatenate([[0], np.cumsum(new_lt)[:-1]]).astype(np.int64) if len(new_lt) else new_lt.copy()
    loop_map = np.full(len(d["lv"]), -1, np.int64)
    loop_map[loop_keep] = np.arange(int(loop_keep.sum()))
    poly_map = np.full(len(lt), -1, np.int64)
    poly_map[keep] = np.arange(int(keep.sum()))
    tkeep = keep[d["tpoly"]]
    out = dict(d)
    out.update(lv=d["lv"][loop_keep], ls=new_ls, lt=new_lt, uv=d["uv"][loop_keep], cn=d["cn"][loop_keep],
               tri=loop_map[d["tri"][tkeep]], tpoly=poly_map[d["tpoly"][tkeep]])
    for k in ("low", "text", "text_up", "mat_index"):
        if out.get(k) is not None and len(out[k]) == len(lt):
            out[k] = np.asarray(out[k])[keep]
    return out


def _material_faces(d, material):
    """Per polygon: True where its material's name matches material (a name or an fnmatch pattern, case-sensitive)."""
    names = list(d.get("mat_names") or [])
    mi = np.asarray(d.get("mat_index", np.zeros(len(d["ls"]), np.int64)), np.int64)
    if not names:
        return np.zeros(len(mi), bool)
    match = np.array([bool(n) and fnmatch.fnmatchcase(n, material) for n in names], bool)
    return match[np.clip(mi, 0, len(names) - 1)]          # Blender draws an index past the last slot with the last


def _arrays(ob, layer, evaluated=True, need_uv=True):
    """Flat numpy arrays of ob's mesh: world-space positions, corners, polygons, UVs, corner normals, triangles, the
    low-density and text face marks, the text up directions and the material per face. Read from the evaluated mesh
    (modifiers applied, as it exports), so marks and sharpness carried by modifiers count. None when the UV layer is
    missing, unless need_uv is False."""
    if evaluated:
        dg = bpy.context.evaluated_depsgraph_get()
        src = ob.evaluated_get(dg)
        me = src.to_mesh()
        mw = np.array(src.matrix_world)
    else:
        src, me, mw = ob, ob.data, np.array(ob.matrix_world)
    try:
        lay = _layer(me, layer)
        if lay is None and need_uv:
            return None
        nv, nl, npoly = len(me.vertices), len(me.loops), len(me.polygons)
        co = np.empty(nv * 3)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
        lv = np.empty(nl, np.int64)
        me.loops.foreach_get("vertex_index", lv)
        ls = np.empty(npoly, np.int64)
        lt = np.empty(npoly, np.int64)
        me.polygons.foreach_get("loop_start", ls)
        me.polygons.foreach_get("loop_total", lt)
        uv = np.zeros(nl * 2)
        if lay is not None:
            lay.uv.foreach_get("vector", uv)
        cn = np.empty(nl * 3)
        me.corner_normals.foreach_get("vector", cn)
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        tri = np.empty(nt * 3, np.int64)
        me.loop_triangles.foreach_get("loops", tri)
        tpoly = np.empty(nt, np.int64)
        me.loop_triangles.foreach_get("polygon_index", tpoly)
        mi = np.zeros(npoly, np.int64)
        me.polygons.foreach_get("material_index", mi)
        lname = lay.name if lay else None
        return {"co": co, "lv": lv, "ls": ls, "lt": lt, "uv": uv.reshape(-1, 2), "cn": cn.reshape(-1, 3),
                "tri": tri.reshape(-1, 3), "tpoly": tpoly, "layer": lname,
                "layers": [l.name for l in me.uv_layers], "low": _low_faces(me, lname),
                "text": _face_marks(me, TEXT_ATTR, lname), "text_up": _face_vectors(me, TEXT_UP_ATTR, mw[:3, :3]),
                "mat_index": mi, "mat_names": [s.material.name if s.material else "" for s in ob.material_slots]}
    finally:
        if evaluated:
            src.to_mesh_clear()


# ----------------------------------------------------------------------------------------------- maths (no bpy)
def _next_loops(d):
    ls, lt = d["ls"], d["lt"]
    loop = np.arange(len(d["lv"]))
    nxt = loop + 1
    nxt[ls + lt - 1] = ls
    return loop, nxt


def _edges(d):
    """Pairs of polygons across each manifold edge, and whether the UVs and the normals are split there."""
    ls, lt, lv = d["ls"], d["lt"], d["lv"]
    loop, nxt = _next_loops(d)
    poly = np.repeat(np.arange(len(ls)), lt)
    va, vb = lv[loop], lv[nxt]
    key = np.minimum(va, vb) * (len(d["co"]) + 1) + np.maximum(va, vb)
    order = np.argsort(key, kind="stable")
    k = key[order]
    _, first, count = np.unique(k, return_index=True, return_counts=True)
    two = first[count == 2]
    i, j = order[two], order[two + 1]
    lo = np.minimum(va, vb)
    # the corner of each side that sits on the edge's lower vertex, and the one on its higher vertex
    i_lo = np.where(va[i] == lo[i], loop[i], nxt[i])
    i_hi = np.where(va[i] == lo[i], nxt[i], loop[i])
    j_lo = np.where(va[j] == lo[j], loop[j], nxt[j])
    j_hi = np.where(va[j] == lo[j], nxt[j], loop[j])
    uv, cn = d["uv"], d["cn"]
    uv_split = (np.abs(uv[i_lo] - uv[j_lo]).max(1) > UV_EPS) | (np.abs(uv[i_hi] - uv[j_hi]).max(1) > UV_EPS)
    c = math.cos(math.radians(HARD_EDGE_DEG))
    hard = ((cn[i_lo] * cn[j_lo]).sum(1) < c) | ((cn[i_hi] * cn[j_hi]).sum(1) < c)
    return poly[i], poly[j], uv_split, hard, key[i]


def _collapsed(tr, isl_tri, n_isl, s):
    """Per triangle: collapsed in UV. Judged against density, not absolute pixels, so the small faces of a lightmap
    at a few texels per metre are not counted: a triangle whose UV area per 3D area is under ZERO_UV_SHARE of its
    island's, or whose whole island's is under ZERO_UV_SHARE of the layout's, or a whole layout mapped under
    ZERO_UV_PX2 square pixels per square metre (s: pixels per UV unit)."""
    ok, a3, au = tr["ok"], tr["a3"], np.abs(tr["au"])
    if not len(au):
        return np.zeros(0, bool)
    w = a3 * ok
    isl_r = (np.bincount(isl_tri, weights=au * ok, minlength=n_isl)
             / np.maximum(np.bincount(isl_tri, weights=w, minlength=n_isl), 1e-30))
    obj_r = float((au * ok).sum()) / max(float(w.sum()), 1e-30)
    rat = au / np.maximum(a3, 1e-30)
    return ok & ((rat < ZERO_UV_SHARE * isl_r[isl_tri]) | (isl_r[isl_tri] < ZERO_UV_SHARE * obj_r)
                 | (obj_r * s * s < ZERO_UV_PX2))


def _islands(npoly, pa, pb, joined):
    parent = np.arange(npoly)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, b in zip(pa[joined].tolist(), pb[joined].tolist()):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    roots = np.array([find(a) for a in range(npoly)], np.int64)
    _, ids = np.unique(roots, return_inverse=True)
    return ids.astype(np.int64)


def _poly_normals(d):
    """Unit normal per polygon (Newell), from the world-space positions."""
    loop, nxt = _next_loops(d)
    co, lv = d["co"], d["lv"]
    c = np.cross(co[lv[loop]], co[lv[nxt]])
    poly = np.repeat(np.arange(len(d["ls"])), d["lt"])
    n = np.stack([np.bincount(poly, weights=c[:, k], minlength=len(d["ls"])) for k in range(3)], 1)
    return n / np.maximum(np.linalg.norm(n, axis=1), 1e-30)[:, None]


def _triangles(d, aspect=(1.0, 1.0)):
    """Per triangle: 3D area, signed UV area, the singular values of the 3D-to-UV map and the 3D shape quality.
    aspect scales U and V to square pixels for a non-square map ((1, 0.5) for 2048 x 1024)."""
    t = d["tri"]
    P = d["co"][d["lv"][t]]
    U = d["uv"][t] * np.asarray(aspect, float)
    e1, e2 = P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]
    n = np.cross(e1, e2)
    a3 = 0.5 * np.linalg.norm(n, axis=1)
    l1 = np.linalg.norm(e1, axis=1)
    ok = (a3 > 1e-12) & (l1 > 1e-12)
    ell = (e1 ** 2).sum(1) + (e2 ** 2).sum(1) + ((P[:, 2] - P[:, 1]) ** 2).sum(1)
    quality = 4 * math.sqrt(3) * a3 / np.maximum(ell, 1e-300)
    x = e1 / np.where(l1 > 0, l1, 1)[:, None]
    y = np.cross(n, x)
    ny = np.linalg.norm(y, axis=1)
    y /= np.where(ny > 0, ny, 1)[:, None]
    p2x, p2y = (e2 * x).sum(1), (e2 * y).sum(1)        # the triangle in its own plane: (0,0), (l1,0), (p2x,p2y)
    u1, u2 = U[:, 1] - U[:, 0], U[:, 2] - U[:, 0]
    au = 0.5 * (u1[:, 0] * u2[:, 1] - u1[:, 1] * u2[:, 0])
    det_p = l1 * p2y
    det_p = np.where(np.abs(det_p) > 1e-18, det_p, 1.0)
    # J = [u1 u2] @ inverse([[l1, p2x], [0, p2y]]), entries a b / c e
    a = u1[:, 0] * p2y / det_p
    b = (u2[:, 0] * l1 - u1[:, 0] * p2x) / det_p
    c = u1[:, 1] * p2y / det_p
    e = (u2[:, 1] * l1 - u1[:, 1] * p2x) / det_p
    s = 0.5 * (a * a + b * b + c * c + e * e)
    dj = np.abs(a * e - b * c)
    s1 = np.sqrt(s + np.sqrt(np.maximum(s * s - dj * dj, 0)))
    s2 = np.where(s1 > 0, dj / np.maximum(s1, 1e-300), 0.0)      # stable for thin triangles, unlike sqrt(s - root)
    return {"a3": np.where(ok, a3, 0), "au": au, "s1": s1, "s2": s2, "ok": ok, "quality": quality,
            "J": np.stack([np.stack([a, b], 1), np.stack([c, e], 1)], 1), "fx": x, "fy": y,
            "fn": n / np.maximum(np.linalg.norm(n, axis=1), 1e-300)[:, None]}


def _island_ids(d, pa, pb, uv_split, au):
    """Island id per polygon: faces joined across edges whose UVs match. One refinement: an island made of two winding
    halves that lie exactly on top of each other (a Mirror modifier at its defaults, or applied with Merge on: the
    halves meet on the axis with the same UVs) is split into its halves, so it reads as a mirrored stack, not as
    folded faces. Returns (ids, number of islands split that way, per-polygon True on each split island's flipped
    half)."""
    npoly = len(d["ls"])
    isl = _islands(npoly, pa, pb, ~uv_split)
    flipped = np.zeros(npoly, bool)
    if not npoly:
        return isl, 0, flipped
    pa_ = np.bincount(d["tpoly"], weights=au, minlength=npoly)
    psign = np.sign(pa_).astype(np.int64)
    flip = ~uv_split & (psign[pa] * psign[pb] < 0)
    if not flip.any():
        return isl, 0, flipped
    halves = _islands(npoly, pa, pb, ~uv_split & ~flip)
    poly_of_loop = np.repeat(np.arange(npoly), d["lt"])
    parea = np.abs(pa_)
    uv = d["uv"]
    out = isl.copy()
    nxt = int(isl.max()) + 1
    split = 0
    for i in np.unique(isl[pa[flip]]).tolist():
        polys = np.flatnonzero(isl == i)
        subs = np.unique(halves[polys])
        if len(subs) < 2:
            continue
        sides = []
        for sgn in (1, -1):
            ps = polys[psign[polys] == sgn]
            mask = np.zeros(npoly, bool)
            mask[ps] = True
            loops = mask[poly_of_loop]
            sides.append((float(parea[ps].sum()), uv[loops].min(0), uv[loops].max(0)))
        (a1, lo1, hi1), (a2, lo2, hi2) = sides
        size = max(float((hi1 - lo1).max()), float((hi2 - lo2).max()), 1e-9)
        if (abs(a1 - a2) <= 0.05 * max(a1, a2) and np.abs(lo1 - lo2).max() <= 1e-3 * size
                and np.abs(hi1 - hi2).max() <= 1e-3 * size):
            for j in subs.tolist()[1:]:
                out[polys[halves[polys] == j]] = nxt
                nxt += 1
            flipped[polys[psign[polys] < 0]] = True
            split += 1
    _, out = np.unique(out, return_inverse=True)
    return out.astype(np.int64), split, flipped


def _wpct(v, w, q):
    if not len(v) or w.sum() <= 0:
        return float("nan")
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return float(v[o][min(np.searchsorted(c, q * c[-1]), len(v) - 1)])


def _boxes(d, isl_poly, n_isl):
    """Per island: lowest and highest UV (two (n, 2) arrays)."""
    lo = np.full((n_isl, 2), np.inf)
    hi = np.full((n_isl, 2), -np.inf)
    if n_isl:
        isl_loop = np.repeat(isl_poly, d["lt"])
        np.minimum.at(lo, isl_loop, d["uv"])
        np.maximum.at(hi, isl_loop, d["uv"])
    return lo, hi


def _tile_check(lo, hi):
    """Per island: inside the 0-1 tile ("home"). Also counts islands that leave it without being a whole-tile copy
    of a home island (the +1 U copies of a stack before a bake): those do not fit."""
    if not len(lo):
        return np.zeros(0, bool), 0
    t = np.floor(lo + UV_EPS)
    home = (t == 0).all(1) & (hi <= 1 + UV_EPS).all(1)
    hb = np.c_[lo[home], hi[home]]
    off = 0
    for i in np.flatnonzero(~home).tolist():
        if (np.floor(hi[i] - UV_EPS) == t[i]).all() and len(hb):
            key = np.r_[lo[i] - t[i], hi[i] - t[i]]
            if (np.abs(hb - key).max(1) <= 1e-4).any():
                continue
        off += 1
    return home, off


def _orientation(d, isl_poly, n_isl, aspect):
    """Per island: elongated (the principal axes of its UV corners differ by ELONGATED or more), and whether its long
    axis runs closer to V than to U. For a directional texture (grain, trim strips) the long side runs along U."""
    if not n_isl:
        z = np.zeros(0, bool)
        return z, z
    isl_loop = np.repeat(isl_poly, d["lt"])
    uv = d["uv"] * np.asarray(aspect, float)
    cnt = np.maximum(np.bincount(isl_loop, minlength=n_isl), 1).astype(float)
    mu = np.stack([np.bincount(isl_loop, weights=uv[:, k], minlength=n_isl) / cnt for k in (0, 1)], 1)
    du = uv - mu[isl_loop]
    sxx = np.bincount(isl_loop, weights=du[:, 0] ** 2, minlength=n_isl)
    syy = np.bincount(isl_loop, weights=du[:, 1] ** 2, minlength=n_isl)
    sxy = np.bincount(isl_loop, weights=du[:, 0] * du[:, 1], minlength=n_isl)
    half = 0.5 * (sxx + syy)
    rad = np.sqrt(np.maximum(0.25 * (sxx - syy) ** 2 + sxy ** 2, 0))
    long_, short = half + rad, np.maximum(half - rad, 0)
    elong = (long_ > 0) & (long_ >= ELONGATED ** 2 * short)
    theta = 0.5 * np.arctan2(2 * sxy, sxx - syy)                  # the long axis' angle from U
    return elong, elong & (np.abs(np.sin(theta)) > np.abs(np.cos(theta)))


def _raster_scale(w, h):
    """Raster pixels per texture pixel: small maps are supersampled up to RASTER_MIN across, big ones capped."""
    m = float(max(w, h))
    return min(max(1.0, RASTER_MIN / m), RASTER_MAX / m)


def _raster(d, island_of_tri, rw, rh, tris):
    """Island id per raster pixel (-1 empty, the last island drawn wins), pixels claimed by two different islands per
    island pair, the pixels each island covers, and which pixels were claimed twice."""
    grid = np.full((rh, rw), -1, np.int64)
    hit = np.zeros((rh, rw), bool)
    clash = {}
    cover = np.zeros(int(island_of_tri.max()) + 1 if len(island_of_tri) else 0, np.int64)
    U = d["uv"][d["tri"]] * np.array([rw, rh], float) - 0.5          # pixel centres at integer coordinates
    for t in tris:
        p = U[t]
        x0, y0 = (np.floor(p.min(0)) + 1).astype(int)
        x1, y1 = np.floor(p.max(0)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, rw - 1), min(y1, rh - 1)
        if x1 < x0 or y1 < y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        (ax, ay), (bx, by), (cx, cy) = p
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12:
            continue
        w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
        w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w0 + w1 <= 1 + 1e-9)
        ys, xs = gy[inside], gx[inside]
        isl = int(island_of_tri[t])
        cover[isl] += len(ys)
        prev = grid[ys, xs]
        other = (prev >= 0) & (prev != isl)
        if other.any():
            hit[ys[other], xs[other]] = True
            for o in np.unique(prev[other]).tolist():
                key = (min(o, isl), max(o, isl))
                clash[key] = clash.get(key, 0) + int(np.count_nonzero(prev[other] == o))
        grid[ys, xs] = isl
    return grid, clash, cover, hit


def _min_gap(grid, limit_px):
    """Smallest centre-to-centre distance (raster pixels) between pixels of two different islands, if it is below
    limit_px; else None. Border pixel centres sit up to a pixel inside their island, so a reported gap is real and a
    pass can be up to 2 raster pixels short (references/uv-audit.md, Accuracy)."""
    hgt, wid = grid.shape
    pad = np.pad(grid, 1, constant_values=-1)
    c = pad[1:-1, 1:-1]
    edge = (c >= 0) & ((pad[:-2, 1:-1] != c) | (pad[2:, 1:-1] != c) | (pad[1:-1, :-2] != c) | (pad[1:-1, 2:] != c))
    ys, xs = np.nonzero(edge)        # the pixel of an island nearest another island is always on its border
    ids = grid[ys, xs]
    r = int(math.ceil(limit_px))
    # half the offsets suffice: the closest pair is found from whichever of its two border pixels sees the other
    offs = sorted((math.hypot(dx, dy), dx, dy) for dx in range(-r, r + 1) for dy in range(0, r + 1)
                  if (dy > 0 or dx > 0) and 0 < math.hypot(dx, dy) < limit_px)
    for dist, dx, dy in offs:
        y, x = ys + dy, xs + dx
        ok = (y >= 0) & (y < hgt) & (x >= 0) & (x < wid)
        other = grid[y[ok], x[ok]]
        if np.any((other >= 0) & (other != ids[ok])):
            return dist
    return None


def _stacked(n, pa_px, pb_px):
    small = max(min(pa_px, pb_px), 1)
    return n / small > 0.9 and abs(int(pa_px) - int(pb_px)) <= 0.1 * small


def measure(d, name="mesh", map_px=None, pad_px=None, px_per_m=None, purpose="unique", baking=False, raster=True,
            directional=False, rows=None, texels_per_m=None, lightmap_scale=1.0, text=False, lod=0,
            lightmapper="unity"):
    """Measure one UV layer given as flat arrays (what _arrays returns: co, lv, ls, lt, uv, cn, tri, tpoly, and
    optionally layer, layers, low, text, text_up). No bpy. map_px None: 1024 for a texture; for a lightmap, the
    footprint of its measured UV2 bounding box at texels_per_m x lightmap_scale x LOD_SCALE^lod (lightmapper
    "bakery": Bakery's footprint, see footprint_px). text=True checks the faces marked as text (d["text"]) and
    raises when none is. Returns a report dict whose "issues" list is empty when nothing needs a look and whose
    "notes" are worth a look; references/uv-audit.md lists every field."""
    purpose = _purpose(purpose, texels_per_m=texels_per_m)
    lightmapper = lightmapper_name(lightmapper)
    planned_scale = float(lightmap_scale)                    # Scale In Lightmap as set, for the density gate
    lightmap_scale = planned_scale * lod_factor(lod, lightmapper)
    text = bool(text) and purpose != "lightmap"              # lightmaps carry no text
    npoly = len(d["ls"])
    bad_uv = ~np.isfinite(np.asarray(d["uv"], float)).all(axis=1) if len(d["uv"]) else np.zeros(0, bool)
    if bad_uv.any():                                         # NaN or inf (a broken import or script): measured as 0,
        d = dict(d, uv=np.where(bad_uv[:, None], 0.0, d["uv"]))   # reported, and the other objects still audited
    tmark = d.get("text")
    tmark = np.asarray(tmark, bool) if tmark is not None and len(tmark) == npoly else np.zeros(npoly, bool)
    if text and not tmark.any():
        raise ValueError("text=True checks the text faces only: mark the text faces with uv_text (a boolean face "
                         "attribute, True on the faces that carry text or decals)")
    lightmap_fp = fp_exact = None
    if map_px is None:
        if purpose == "lightmap":
            if not texels_per_m:
                raise ValueError("a lightmap audit needs map_px (the footprint) or texels_per_m (and lightmap_scale)")
            b = uv_box_share(d["uv"])
            fp = footprint_px(float(_triangles(d)["a3"].sum()), texels_per_m, lightmap_scale, b, lightmapper,
                              uv_box_short_side(d["uv"]) if lightmapper == "bakery" else None)
            # too small for 2-texel gaps (under 64 px): the UV2 is packed and checked for 64 px, with a note
            graded = max(fp, float(LIGHTMAP_MIN_FOOTPRINT_PX))
            lightmap_fp = {"footprint_px": round(fp, 1), "uv2_box_share": round(b, 4), "graded_at_px": round(graded, 1),
                           "lightmapper": lightmapper}
            map_px, fp_exact = graded, fp
        else:
            map_px = 1024
    w, h = map_size(map_px)
    s = float(max(w, h))
    aspect = (w / s, h / s)
    if pad_px is None:
        pad_px = default_pad((w, h), purpose)
    pa, pb, uv_split, hard, _key = _edges(d)
    tr = _triangles(d, aspect)
    isl_poly, mirror_stacks, _flipped = _island_ids(d, pa, pb, uv_split, tr["au"])
    n_isl = int(isl_poly.max()) + 1 if npoly else 0
    isl_tri = isl_poly[d["tpoly"]]
    ok, w3, au = tr["ok"], tr["a3"], tr["au"]
    zero_uv = _collapsed(tr, isl_tri, n_isl, s)
    good = ok & ~zero_uv
    ang = np.where(tr["s2"] > 0, tr["s1"] / np.maximum(tr["s2"], 1e-300), 1e6)
    ratio = tr["s1"] * tr["s2"]                                  # UV area / 3D area per triangle
    # orientation per island: flipped triangles are a fold unless the whole island is mirrored
    neg = au < 0
    wg = w3 * good
    neg_area = np.bincount(isl_tri, weights=wg * neg, minlength=n_isl)
    tot_area = np.bincount(isl_tri, weights=wg, minlength=n_isl)
    mirrored = neg_area > 0.5 * np.maximum(tot_area, 1e-30)
    fold = good & (neg != mirrored[isl_tri])
    # distortion inside islands
    isl_ratio = (np.bincount(isl_tri, weights=ratio * wg, minlength=n_isl)
                 / np.maximum(np.bincount(isl_tri, weights=wg, minlength=n_isl), 1e-30))
    area_dev = np.abs(np.log2(np.maximum(ratio, 1e-30) / np.maximum(isl_ratio[isl_tri], 1e-30)))
    shaped = good & (tr["quality"] >= SLIVER_QUALITY)
    # texel density per island, px per metre. Faces marked uv_low_density were lowered on purpose: left out of the
    # mean, the spread and the per-island band, and reported on their own.
    low_p = d.get("low")
    low_p = np.asarray(low_p, bool) if low_p is not None and len(low_p) == npoly else np.zeros(npoly, bool)
    low = low_p[d["tpoly"]]
    seen = good & ~low
    td_isl = s * np.sqrt(np.maximum(isl_ratio, 0))
    td_mean = s * math.sqrt(float(np.abs(au[seen]).sum()) / max(float(w3[seen].sum()), 1e-30))
    wi = np.bincount(isl_tri, weights=w3 * seen, minlength=n_isl)
    td_cv = (float(np.sqrt(np.average((td_isl - td_mean) ** 2, weights=wi))) / td_mean
             if td_mean > 0 and wi.sum() > 0 else float("nan"))
    lowg = good & low
    off_density = 0
    if px_per_m and purpose in ("unique", "tiling", "trim"):
        lo_b, hi_b = TEXEL_BAND[purpose]
        f = td_isl / float(px_per_m)
        off_density = int(np.count_nonzero((wi > 0) & ((f < lo_b - 1e-6) | (f > hi_b + 1e-6))))
    # each island on its own, and the text faces together: the gate's p95 limits per group (ISLAND_MIN_SHARE)
    tot_w = float(wg.sum())
    island_rows = []
    if n_isl and tot_w > 0:
        order = np.argsort(isl_tri, kind="stable")
        cuts = np.searchsorted(isl_tri[order], np.arange(n_isl + 1))
        for i in np.flatnonzero(tot_area >= ISLAND_MIN_SHARE * tot_w):
            m = order[cuts[i]:cuts[i + 1]]
            m = m[good[m]]
            a95 = _wpct(ang[m], w3[m], 0.95)
            d95 = _wpct(area_dev[m], w3[m], 0.95)
            if a95 > LIMITS["angular_p95"] or d95 > LIMITS["area_p95"]:
                island_rows.append((int(i), float(tot_area[i]) / tot_w, a95, d95))
    island_rows.sort(key=lambda r: -max(r[2] / LIMITS["angular_p95"], 1.0 + r[3]))
    tg = good & tmark[d["tpoly"]]
    text_p95 = _wpct(ang[tg], w3[tg], 0.95) if tg.any() else None
    even = shaped & ~low
    area_max = float(area_dev[even].max()) if even.any() else 0.0
    # text and decals, on the faces marked uv_text only: per island, where the letters' up (uv_text_up, default world
    # +Z) goes in UV (+V within 45 deg passes), and whether the marked faces are mirrored
    text_isl = np.bincount(isl_poly, weights=tmark.astype(float), minlength=n_isl) > 0
    text_mirrored = text_not_up = text_flat = 0
    if text and n_isl:
        ttri = tmark[d["tpoly"]] & good
        up = np.tile([0.0, 0.0, 1.0], (len(ttri), 1))
        tu = d.get("text_up")
        if tu is not None and len(tu) == npoly:
            tu = np.asarray(tu, float)[d["tpoly"]]
            given = np.linalg.norm(tu, axis=1) > 0.5
            up[given] = tu[given]
        ul = np.stack([(tr["fx"] * up).sum(1), (tr["fy"] * up).sum(1)], 1)    # up in each triangle's own frame
        duv = np.einsum("nij,nj->ni", tr["J"], ul)
        wv = w3 * ttri * (np.abs((tr["fn"] * up).sum(1)) < 0.9)                 # faces the up direction lies along
        su = np.bincount(isl_tri, weights=duv[:, 0] * wv, minlength=n_isl)
        sv = np.bincount(isl_tri, weights=duv[:, 1] * wv, minlength=n_isl)
        has = np.bincount(isl_tri, weights=wv, minlength=n_isl) > 0
        text_not_up = int(np.count_nonzero(has & ~(sv > np.abs(su))))
        text_flat = int(np.count_nonzero(text_isl & ~has))
        tneg = np.bincount(isl_tri, weights=w3 * ttri * neg, minlength=n_isl)
        ttot = np.bincount(isl_tri, weights=w3 * ttri, minlength=n_isl)
        text_mirrored = int(np.count_nonzero((ttot > 0) & (tneg > 0.5 * ttot)))
    # bounds: the 0-1 tile, and the margin to its edge measured on the islands inside it
    uv = d["uv"]
    lo, hi = _boxes(d, isl_poly, n_isl)
    outside = float(np.mean((uv < -UV_EPS) | (uv > 1 + UV_EPS))) if len(uv) else 0.0
    home, off_tile = _tile_check(lo, hi)
    hl = home[np.repeat(isl_poly, d["lt"])] if n_isl else np.zeros(len(uv), bool)
    margin = (round(min(float(uv[hl, 0].min()) * w, float(1 - uv[hl, 0].max()) * w,
                        float(uv[hl, 1].min()) * h, float(1 - uv[hl, 1].max()) * h), 2) + 0.0
              if hl.any() else None)
    # strip direction and trim rows; islands holding text faces follow the text rule instead of the grain rule
    elong, along_v = _orientation(d, isl_poly, n_isl, aspect)
    along_v = along_v & ~text_isl
    rows = parse_rows(rows)
    across_rows = []
    if rows and n_isl:
        t = np.floor(lo[:, 1] + UV_EPS)
        v0, v1 = (lo[:, 1] - t) * h, (hi[:, 1] - t) * h
        for i in range(n_isl):
            if not any(v0[i] >= a - 0.5 and v1[i] <= b + 0.5 for a, b in rows):
                across_rows.append(i)
    # lightmap charts across hard edges or sharp bends. A fold between faces under a hundredth of a texel each (a
    # triangulated bevel-corner quad at a lightmap's few texels per metre) cannot smear a texel: not counted.
    pn = _poly_normals(d)
    bend = np.degrees(np.arccos(np.clip((pn[pa] * pn[pb]).sum(1), -1.0, 1.0))) if len(pa) else np.zeros(0)
    poly_px2 = np.bincount(d["tpoly"], weights=np.abs(au), minlength=npoly) * s * s
    tiny = poly_px2 < BEND_MIN_PX2
    folded = (bend > LIGHTMAP_HARD_ANGLE) & ~(tiny[pa] | tiny[pb]) if len(pa) else np.zeros(0, bool)
    chart_bends = int(np.count_nonzero(~uv_split & (hard | folded)))
    rep = {"object": name, "layer": d.get("layer"), "layers": d.get("layers", []), "purpose": purpose,
           "map_px": [w, h], "pad_px": pad_px, "faces": npoly, "islands": n_isl,
           "angular_p95": round(_wpct(ang[good], w3[good], 0.95), 3),
           "angular_p99": round(_wpct(ang[good], w3[good], 0.99), 3),
           "angular_max": round(float(ang[shaped].max()) if shaped.any() else
                                (float(ang[good].max()) if good.any() else float("nan")), 2),
           "area_p95": round(_wpct(area_dev[good], w3[good], 0.95), 3),
           "area_max": round(area_max, 3),
           "islands_distorted": len(island_rows),
           "worst_islands": [{"island": i, "area_share": round(sh, 4), "angular_p95": round(a, 3),
                              "area_p95": round(dv, 3)} for i, sh, a, dv in island_rows[:5]],
           "text_angular_p95": None if text_p95 is None else round(text_p95, 3),
           "folded_faces": int(len(np.unique(d["tpoly"][fold]))), "mirrored_islands": int(mirrored.sum()),
           "mirror_stacks": int(mirror_stacks),
           "zero_area_uv_faces": int(len(np.unique(d["tpoly"][zero_uv]))),
           "outside_0_1": round(outside, 4), "islands_off_tile": int(off_tile),
           "texel_px_per_m": round(td_mean, 1), "texel_cv": round(td_cv, 3),
           "texel_island_range": ([round(float(td_isl[wi > 0].min()), 1), round(float(td_isl[wi > 0].max()), 1)]
                                  if (wi > 0).any() else None),
           "islands_off_density": off_density,
           "low_density_faces": int(low_p.sum()),
           "low_density_px_per_m": (round(s * math.sqrt(float(np.abs(au[lowg]).sum())
                                                         / max(float(w3[lowg].sum()), 1e-30)), 1)
                                    if lowg.any() else None),
           "hard_edges_not_seams": int(np.count_nonzero(hard & ~uv_split)),
           "chart_bends": chart_bends,
           "elongated_islands": int(elong.sum()), "elongated_along_v": int(along_v.sum()),
           "islands_across_rows": len(across_rows),
           "text_faces": int(tmark.sum()), "text_islands_mirrored": text_mirrored,
           "text_islands_not_upright": text_not_up, "text_islands_flat": text_flat,
           "margin_px": margin,
           # per island: pixel box [x0, y0, x1, y1] (whole-tile offsets kept) and px/m (None when all marked low)
           "island_boxes_px": [[round(float(lo[i, 0] * w), 1), round(float(lo[i, 1] * h), 1),
                                round(float(hi[i, 0] * w), 1), round(float(hi[i, 1] * h), 1)] for i in range(n_isl)],
           "island_px_per_m": [round(float(td_isl[i]), 1) if wi[i] > 0 else None for i in range(n_isl)]}
    if lightmap_fp:
        rep.update(lightmap_fp)
    rep["notes"] = []
    low_density = None
    if purpose == "lightmap":
        # a lightmapper packs the charts' bounding box: empty space inside it costs texels (Unity 2022.3, measured;
        # Bakery maps the box onto a rect sized by the surface area, so the same holds)
        box = uv_box_share(uv)
        charts = float(np.abs(au[good]).sum())
        fill = min(1.0, charts / max(box, 1e-12))
        eff = None
        if texels_per_m and lightmapper == "bakery" and fp_exact is not None:
            eff = fp_exact * math.sqrt(charts / max(float(w3.sum()), 1e-30))   # footprint x sqrt(UV area / area)
        elif texels_per_m:
            eff = texels_per_m * lightmap_scale * math.sqrt(fill)
        rep.update({"lod": int(lod or 0), "uv2_box_fill": round(fill, 4),
                    "effective_texels_per_m": round(eff, 2) if eff is not None else None})
        fp = rep.get("footprint_px")
        # Bakery: the density planned for it, texels_per_m x its linear scale sqrt(Scale In Lightmap), at most 1
        planned = texels_per_m * min(1.0, math.sqrt(planned_scale)) if texels_per_m else None
        if (fp if fp is not None else float(max(w, h))) < LIGHTMAP_MIN_FOOTPRINT_PX:
            if fp is not None:                                     # under 64 px the fallback governs, not the fill
                rep["notes"].append(lightmap_small_note(fp, lod=int(lod or 0), lightmapper=lightmapper))
        elif lightmapper == "bakery" and eff is not None and eff < EFFECTIVE_DENSITY_MIN * planned:
            low_density = ("effective lightmap density %.1f texels/m, under half the %g planned (Bakery sizes the UV2 "
                           "by its area and bounds; its charts fill %.0f%% of their bounding box): pack them to fill "
                           "it, or raise Scale In Lightmap and pack again for the larger footprint"
                           % (eff, round(planned, 2), 100 * fill))
        elif fill < LIGHTMAP_BOX_FILL_NOTE:
            rep["notes"].append("UV2 charts fill %.0f%% of their bounding box: the empty space costs lightmap "
                                "texels%s; pack the charts to fill their box (any aspect ratio)"
                                % (100 * fill, (" (effective %.1f texels/m)" % rep["effective_texels_per_m"])
                                   if texels_per_m else ""))
    if raster and len(d["tri"]) and purpose in ("unique", "lightmap"):
        k = _raster_scale(w, h)
        rw, rh = max(1, int(round(w * k))), max(1, int(round(h * k)))
        grid, clash, px, hit = _raster(d, isl_tri, rw, rh, np.flatnonzero(good))
        alias = np.arange(max(n_isl, 1))
        stacked = partial = 0
        for (a, b), n in sorted(clash.items()):
            if _stacked(n, px[a], px[b]):
                stacked += 1
                ra, rb = alias[a], alias[b]
                alias[alias == max(ra, rb)] = min(ra, rb)
            else:
                partial += 1
        rep.update({"coverage": round(float((grid >= 0).mean()), 4), "overlap_px": round(float(hit.sum()) / k / k, 1),
                    "stacked_island_pairs": stacked, "overlapping_island_pairs": partial, "raster_scale": k})
        if pad_px:
            # exactly stacked copies share their pixels on purpose: each stack is one island for the gap check
            grid = np.where(grid >= 0, alias[np.maximum(grid, 0)], -1)
            gap = _min_gap(grid, pad_px * k)
            rep["padding_ok"] = gap is None
            rep["min_gap_px"] = None if gap is None else round(gap / k, 2)
    rep["issues"] = _issues(rep, purpose, pad_px, px_per_m, baking, directional, text)
    if not npoly:
        rep["issues"].insert(0, "no faces: nothing to audit (an empty or vertex-only mesh)")
    if bad_uv.any():
        rep["issues"].insert(0, "%d UV corners are not numbers (NaN or inf): re-unwrap" % int(bad_uv.sum()))
    if low_density:
        rep["issues"].append(low_density)
    return rep


def _issues(r, purpose, pad_px, px_per_m, baking, directional=False, text=False):
    out = []
    if len(r["layers"]) > MAX_UV_MAPS:
        out.append("%d UV maps (engines keep at most %d)" % (len(r["layers"]), MAX_UV_MAPS))
    for key, msg in (("angular_p95", "angular stretch p95 %.2f"), ("angular_p99", "angular stretch p99 %.2f"),
                     ("angular_max", "a face stretched %.1fx (folded, collapsed or squashed UVs)"),
                     ("area_p95", "uneven density inside islands (area p95 %.2f)")):
        if r[key] == r[key] and r[key] > LIMITS[key]:
            out.append(msg % r[key])
    if r.get("area_max", 0) > LIMITS["area_max"]:
        out.append("a patch at %.1fx or 1/%.1f its island's texel density (area max %.2f): it reads blurred or "
                   "oversharp against the rest" % (2 ** (r["area_max"] / 2), 2 ** (r["area_max"] / 2), r["area_max"]))
    if r.get("islands_distorted"):
        w = r["worst_islands"][0]
        out.append("%d island(s) stretched on their own, which the whole-object numbers hide (worst: island %d, %.1f%% "
                   "of the area, angular p95 %.2f, area p95 %.2f)" % (r["islands_distorted"], w["island"],
                                                                      100 * w["area_share"], w["angular_p95"],
                                                                      w["area_p95"]))
    if r.get("text_angular_p95") is not None and r["text_angular_p95"] > LIMITS["angular_p95"]:
        out.append("text faces stretched (angular p95 %.2f): letters read squashed" % r["text_angular_p95"])
    if r["folded_faces"]:
        out.append("%d folded faces" % r["folded_faces"])
    if r["zero_area_uv_faces"]:
        out.append("%d faces with zero UV area" % r["zero_area_uv_faces"])
    if purpose == "lightmap" and r["outside_0_1"] > 0:
        out.append("UVs outside 0-1")
    if purpose == "unique" and r["islands_off_tile"]:
        out.append("%d islands leave the 0-1 tile (they do not fit)" % r["islands_off_tile"])
    if r.get("overlapping_island_pairs"):
        out.append("%d island pairs partly overlap" % r["overlapping_island_pairs"])
    if purpose == "lightmap" and r.get("stacked_island_pairs"):
        out.append("%d stacked island pairs in a lightmap" % r["stacked_island_pairs"])
    if baking and purpose == "unique" and r.get("stacked_island_pairs"):
        out.append("%d stacked island pairs inside 0-1 at bake time: keep one copy there, the rest +1 in U "
                   "(layout(bake=True))" % r["stacked_island_pairs"])
    if pad_px and r.get("padding_ok") is False:
        out.append("islands %.1f px apart (< %g)" % (r["min_gap_px"], pad_px))
    if (pad_px and purpose in ("unique", "lightmap") and r["margin_px"] is not None and not r["islands_off_tile"]
            and r["margin_px"] < pad_px / 2.0 - EDGE_SLACK_PX):
        out.append("%.2f px from the tile edge (< %g)" % (r["margin_px"], pad_px / 2.0))
    if text and r.get("text_islands_mirrored"):
        out.append("%d text islands are mirrored: their text reads backwards" % r["text_islands_mirrored"])
    if text and r.get("text_islands_not_upright"):
        out.append("%d text islands do not have the letters' up (uv_text_up, default 3D +Z) on +V: the text is turned"
                   % r["text_islands_not_upright"])
    if text and r.get("text_islands_flat"):
        out.append("%d text islands lie across their up direction (flat text): give their faces a uv_text_up"
                   % r["text_islands_flat"])
    if purpose == "lightmap" and r.get("chart_bends"):
        out.append("%d edges inside lightmap charts are hard or bend more than %g deg: cut the charts there"
                   % (r["chart_bends"], LIGHTMAP_HARD_ANGLE))
    if (directional or purpose == "trim") and r.get("elongated_along_v"):
        out.append("%d long islands run along V: grain or a trim strip should run along U" % r["elongated_along_v"])
    if r.get("islands_across_rows"):
        out.append("%d islands cross a trim row edge" % r["islands_across_rows"])
    if r["texel_cv"] == r["texel_cv"] and r["texel_cv"] > LIMITS["texel_cv"]:
        out.append("texel density varies between islands (cv %.2f)" % r["texel_cv"])
    if r.get("low_density_px_per_m") and r["texel_px_per_m"] and r["low_density_px_per_m"] > 0.9 * r["texel_px_per_m"]:
        out.append("%d faces marked low-density are not lowered (%.0f px/m vs %.0f)"
                   % (r["low_density_faces"], r["low_density_px_per_m"], r["texel_px_per_m"]))
    if px_per_m:
        lo_b, hi_b = TEXEL_BAND[purpose]
        f = r["texel_px_per_m"] / float(px_per_m)
        if not lo_b - 1e-6 <= f <= hi_b + 1e-6:
            out.append("texel density %.0f px/m, target %g (%.2f-%.2fx for %s)"
                       % (r["texel_px_per_m"], px_per_m, lo_b, hi_b, purpose))
        if r.get("islands_off_density"):
            out.append("%d islands outside %.2f-%.2fx of %g px/m" % (r["islands_off_density"], lo_b, hi_b, px_per_m))
    if baking and r["hard_edges_not_seams"]:
        out.append("%d hard edges not on a UV seam" % r["hard_edges_not_seams"])
    return out


def measure_shared(named, map_px=1024, pad_px=None, purpose="unique"):
    """Several layers on one texture, given as [(name, arrays), ...]: overlaps and gaps between islands of different
    objects, which the per-object measure cannot see. Stacked copies count as one island. Tiling and trim layers may
    overlap, so nothing is checked for them. No bpy."""
    purpose = _purpose(purpose)
    w, h = map_size(map_px)
    s = float(max(w, h))
    if pad_px is None:
        pad_px = default_pad((w, h), purpose)
    rep = {"objects": [n for n, _d in named], "purpose": purpose, "map_px": [w, h], "pad_px": pad_px, "issues": []}
    if purpose in ("tiling", "trim"):
        rep["note"] = "tiling and trim layers may overlap: nothing to check between objects"
        return rep
    uvs, tris, isl, owner = [], [], [], []
    base = nisl = 0
    for k, (_name, d) in enumerate(named):
        pa, pb, uv_split, _hard, _key = _edges(d)
        tr = _triangles(d, (w / s, h / s))
        ids, _split, _flip = _island_ids(d, pa, pb, uv_split, tr["au"])
        n = int(ids.max()) + 1 if len(ids) else 0
        keep = np.flatnonzero(tr["ok"] & ~_collapsed(tr, ids[d["tpoly"]], n, s))
        uvs.append(d["uv"])
        tris.append(d["tri"][keep] + base)
        isl.append(ids[d["tpoly"][keep]] + nisl)
        owner += [k] * n
        nisl += n
        base += len(d["uv"])
    if not tris or not sum(len(t) for t in tris):
        rep["issues"].append("no UV data")
        return rep
    dd = {"uv": np.concatenate(uvs), "tri": np.concatenate(tris)}
    isl_tri = np.concatenate(isl)
    k = _raster_scale(w, h)
    rw, rh = max(1, int(round(w * k))), max(1, int(round(h * k)))
    grid, clash, px, _hit = _raster(dd, isl_tri, rw, rh, np.arange(len(dd["tri"])))
    alias = np.arange(max(nisl, 1))
    across = 0
    for (a, b), n in sorted(clash.items()):
        if _stacked(n, px[a], px[b]):
            ra, rb = alias[a], alias[b]
            alias[alias == max(ra, rb)] = min(ra, rb)
        elif owner[a] != owner[b]:
            across += 1
    rep["coverage"] = round(float((grid >= 0).mean()), 4)
    rep["overlapping_pairs_between_objects"] = across
    if across:
        rep["issues"].append("%d island pairs of different objects overlap" % across)
    if pad_px:
        grid = np.where(grid >= 0, alias[np.maximum(grid, 0)], -1)
        gap = _min_gap(grid, pad_px * k)
        rep["min_gap_px"] = None if gap is None else round(gap / k, 2)
        if gap is not None:
            rep["issues"].append("islands %.1f px apart (< %g) across the shared layout" % (gap / k, pad_px))
    return rep


def tile_uv(p, n, tile_m):
    """tile_project's box projection: UVs for positions p (k, 3) in the piece's own axes (metres from its pivot,
    scale applied) on a face whose normal in those axes is n. The normal's largest component picks the plane (within
    TILE_AXIS_TIE of it counts as a tie, broken Z, then X, then Y); U runs to the right seen from the front of the face
    and V up (Z on walls, +Y on floors and ceilings), one tile per tile_m metres, phase 0 at the pivot. Pieces whose
    pivots sit on a grid whose step is a whole number of tiles therefore continue the pattern across every joint,
    whatever their size, and walls whatever their turn about Z; a floor or ceiling turned about Z turns its pattern
    with it, so tiling floors and ceilings are placed unturned (or turned by the texture's own symmetry)."""
    p = np.asarray(p, float).reshape(-1, 3)
    n = np.asarray(n, float)
    a = np.abs(n)
    ax = next(k for k in (2, 0, 1) if a[k] >= a.max() - TILE_AXIS_TIE)
    s = 1.0 if n[ax] >= 0 else -1.0
    if ax == 0:
        u, v = s * p[:, 1], p[:, 2]
    elif ax == 1:
        u, v = -s * p[:, 0], p[:, 2]
    else:
        u, v = s * p[:, 0], p[:, 1]
    return np.stack([u, v], axis=1) / float(tile_m)


def tile_steps_issues(tile_m, steps):
    """Issues for placement steps (metres: the grid module along walls and floors, the storey height up them) that
    are not whole numbers of tiles: a piece placed one step along restarts the pattern part-way through a tile."""
    out = []
    for step in steps or ():
        r = float(step) / float(tile_m)
        if r < 1.0 - 1e-6 or abs(r - round(r)) > 1e-6:
            out.append("placement step %g m is not a whole number of %g m tiles (%.3g): the pattern jumps at every "
                       "joint; use a tile that divides the step, or place the family only on multiples of the tile"
                       % (step, tile_m, r))
    return out


def tile_phase(d, tile_m, map_px, frame=None, steps=None, limit_px=TILE_PHASE_PX, offset=(0.0, 0.0, 0.0)):
    """How far a tiling layout sits from tile_project's, per face, in texels after whole tiles are taken off (the
    pattern only needs to agree mod 1). d: the flat arrays (_arrays); frame: (R, t), the piece's rotation (unit
    columns) and pivot, to bring world positions into its own axes (None: d's positions already are). A face off by
    more than limit_px breaks the pattern where it meets a neighbour; one that fits with U negated is reported as
    mirrored (the pattern reads backwards and its joints show as a mirror line). offset: a phase variant's, as
    given to tile_project."""
    w, h = map_size(map_px)
    co = np.asarray(d["co"], float)
    if frame is not None:
        rot, t = frame
        if np.linalg.det(np.asarray(rot, float)) < 0:
            return {"tile_m": float(tile_m), "faces": int(len(d["ls"])), "phase_px_max": None, "off_faces": None,
                    "mirrored_faces": None, "issues": tile_steps_issues(tile_m, steps) + [
                        "the object is mirrored (negative scale): apply its scale, then tile_project"]}
        co = (co - np.asarray(t, float)) @ np.asarray(rot, float)
    normals = _poly_normals(dict(d, co=co))
    co = co + np.asarray(offset, float)
    exp = np.empty((len(d["lv"]), 2))
    for f in range(len(d["ls"])):
        sl = slice(int(d["ls"][f]), int(d["ls"][f] + d["lt"][f]))
        exp[sl] = tile_uv(co[d["lv"][sl]], normals[f], tile_m)
    scale = np.array([w, h], float)

    def off(e):
        # per face: the first corner's offset mod 1 (the phase), and how far each other corner's offset differs from
        # it, not mod 1 (a wrong scale or a mirror; on whole-tile corners a mirrored U still lands on whole numbers)
        if not len(d["ls"]):
            return np.zeros(0)
        delta = d["uv"] - e
        first = delta[np.repeat(d["ls"], d["lt"])]
        phase = np.abs(first - np.round(first)) * scale
        spread = np.abs(delta - first) * scale
        return np.maximum.reduceat(np.maximum(phase, spread).max(axis=1), d["ls"])

    err = off(exp)
    mir = off(exp * np.array([-1.0, 1.0]))
    bad = err > limit_px
    mirrored = bad & (mir <= limit_px)
    issues = tile_steps_issues(tile_m, steps)
    if mirrored.any():
        issues.append("%d tiling faces mirrored against tile_project (U reads backwards): re-project with "
                      "tile_project" % int(mirrored.sum()))
    if (bad & ~mirrored).any():
        issues.append("%d of %d tiling faces off tile_project's scale and phase by up to %.1f px (limit %.1f): the "
                      "pattern jumps where they meet a neighbour; re-project with tile_project(tile_m=%g)"
                      % (int((bad & ~mirrored).sum()), len(err), float(err[bad & ~mirrored].max()), limit_px, tile_m))
    return {"tile_m": float(tile_m), "faces": int(len(err)), "phase_px_max": round(float(err.max()), 3) if len(err)
            else 0.0, "off_faces": int(bad.sum()), "mirrored_faces": int(mirrored.sum()), "issues": issues}


# ----------------------------------------------------------------------------------------------- audit (bpy)
def audit(ob, layer=None, map_px=None, pad_px=None, px_per_m=None, purpose=None, baking=False, lightmap=False,
          directional=False, rows=None, texels_per_m=None, lightmap_scale=1.0, text=False, material=None, lod=None,
          evaluated=True, raster=True, lightmapper="unity", tile_m=None, steps=None, tile_offset=(0.0, 0.0, 0.0)):
    """Measure one object's UV map on the evaluated mesh in world space; changes nothing. purpose: unique (default),
    tiling, trim or lightmap; lightmap=True or texels_per_m makes it a lightmap audit, and either with another
    purpose raises. layer: index or name; by default 0 (UV0), or 1 for a lightmap; "active" for the active map.
    map_px: 1024 (default for textures), (2048, 1024), "2048x1024" or a footprint (fractions round down); for a
    lightmap without map_px, the footprint of the layer's measured bounding box at texels_per_m x lightmap_scale.
    baking: the layer takes a baked normal map (hard edges on seams, one copy of a stack in 0-1). directional: the
    texture has a grain: long islands must run along U. text: check the faces marked uv_text (not mirrored, the
    letters' up on +V); raises when none is marked. material: only the faces whose material name matches (a name or
    an fnmatch pattern), for a mesh that mixes tiling, trim and unique materials; raises when no face matches.
    lod: the LOD level of a lightmap audit (texel scale x LOD_SCALE^lod); None reads it from a <Piece>_LOD<n> name.
    lightmapper: whose footprint a lightmap audit uses, "unity" (default; "progressive") or "bakery" (Bakery's
    area-based rect, no LOD factor, and an issue when the charts get under half the planned texels per metre).
    rows: trim rows in pixels, [(v0, v1), ...] or "0-128,128-192". tile_m (purpose tiling): also check every face
    against tile_project's scale and phase (tile_phase: a kit piece's pattern continues across joints), and steps
    (metres: grid module, storey height) for being whole numbers of tiles; tile_offset: a phase variant's offset."""
    purpose = _purpose(purpose, lightmap, texels_per_m)
    if tile_m is not None and purpose != "tiling":
        raise ValueError("tile_m checks a tiling layout: pass purpose='tiling'")
    layer = _resolve_layer(layer, purpose)
    if ob.mode == "EDIT":
        ob.update_from_editmode()
    d = _arrays(ob, layer, evaluated)
    if d is None:
        return {"object": ob.name, "layer": layer, "purpose": purpose, "issues": ["no such UV layer"],
                "layers": [l.name for l in ob.data.uv_layers]}
    if material:
        keep = _material_faces(d, material)
        if not keep.any():
            raise ValueError("%s has no faces with a material matching %r" % (ob.name, material))
        d = _subset(d, keep)
    rep = measure(d, ob.name, map_px=map_px, pad_px=pad_px, px_per_m=px_per_m, purpose=purpose, baking=baking,
                  raster=raster, directional=directional, rows=rows, texels_per_m=texels_per_m,
                  lightmap_scale=lightmap_scale, text=text,
                  lod=(lod if lod is not None else lod_level(ob.name)) if purpose == "lightmap" else 0,
                  lightmapper=lightmapper)
    if material:
        rep["material"] = material
    if tile_m is not None:
        m = np.array(ob.matrix_world)
        rot = m[:3, :3] / np.maximum(np.linalg.norm(m[:3, :3], axis=0), 1e-12)
        tp = tile_phase(d, tile_m, map_px or 1024, frame=(rot, m[:3, 3]), steps=steps, offset=tile_offset)
        rep["tile_phase"] = {k: v for k, v in tp.items() if k != "issues"}
        rep["issues"] = list(rep.get("issues", [])) + tp["issues"]
    return rep


def has_material(ob, material):
    """True when one of ob's material slots holds a material whose name matches material (name or fnmatch pattern)."""
    return any(s.material and fnmatch.fnmatchcase(s.material.name, material) for s in ob.material_slots)


def line(r):
    if "angular_p95" not in r:
        return "  CHECK  %-28s %s" % (r["object"], "; ".join(r["issues"]))
    return ("  %s  %-28s %-12s %-8s %4d isl  cov %s  ang p95 %.3f  area p95 %.3f  %6.0f px/m  %s%s"
            % ("CHECK" if r["issues"] else "OK   ", r["object"], str(r["layer"])[:12], r["purpose"], r["islands"],
               r.get("coverage", "-"), r["angular_p95"], r["area_p95"], r["texel_px_per_m"],
               "; ".join(r["issues"]) or "no issues",
               "".join("  NOTE: %s" % n for n in r.get("notes", []))))


def has_text_faces(ob):
    """True when ob's mesh has a face marked uv_text (or uv_text_<UV map name>)."""
    for at in ob.data.attributes:
        if ((at.name == TEXT_ATTR or (at.name.startswith(TEXT_ATTR + "_") and at.name != TEXT_UP_ATTR))
                and at.domain == "FACE" and at.data_type == "BOOLEAN" and len(at.data)):
            vals = np.zeros(len(at.data), bool)
            at.data.foreach_get("value", vals)
            if vals.any():
                return True
    return False


def audit_objects(objects, report_path=None, **kw):
    """audit() per mesh, one printed line each. material=...: meshes without that material are skipped. text=True
    checks the meshes that have faces marked uv_text, and raises when none has."""
    objects = [o for o in objects if o.type == "MESH"
               and not (kw.get("material") and not has_material(o, kw["material"]))]
    marked = {o.name for o in objects if kw.get("text") and has_text_faces(o)}
    if kw.get("text") and objects and not marked:
        raise ValueError("text=True checks the text faces only: mark the text faces with uv_text (a boolean face "
                         "attribute); no mesh here has one")
    reps = []
    for ob in objects:
        r = audit(ob, **dict(kw, text=ob.name in marked))
        reps.append(r)
        print(line(r))
    if report_path:
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(reps, fh, indent=1)
    return reps


def audit_selected(**kw):
    return audit_objects([o for o in bpy.context.selected_objects if o.type == "MESH"], **kw)


def audit_shared(objects, layer=None, map_px=1024, pad_px=None, purpose="unique", evaluated=True, material=None):
    """Several objects on one texture (a shared atlas): overlaps and gaps between their islands, which the
    per-object audit cannot see. material: only faces with a matching material. Returns a report dict with
    "issues"."""
    layer = _resolve_layer(layer, _purpose(purpose))
    named = []
    for o in objects:
        if o.type != "MESH":
            continue
        d = _arrays(o, layer, evaluated)
        if d is not None and material:
            keep = _material_faces(d, material)
            d = _subset(d, keep) if keep.any() else None
        if d is not None:
            named.append((o.name, d))
    return measure_shared(named, map_px=map_px, pad_px=pad_px, purpose=purpose)


def lightmap_footprint(ob, texels_per_m, scale=1.0, coverage=FOOTPRINT_COVERAGE, measured=False, layer=1, lod=None,
                       lightmapper="unity"):
    """The lightmap texel scale of this object's UV2 in texels per UV unit, rounded down: footprint_px of its
    world-space surface area (evaluated mesh). coverage is b, the bounding box of all its UV2 charts as a share of the
    tile: 0.85 plans before a UV2 exists, 1.0 gives the smallest scale (what pack_lightmap packs for); measured=True
    reads b (and, for Bakery, the box's short side) from the object's lightmap UV (layer, default the second UV map).
    lod: its LOD level (Unity: scale x LOD_SCALE^lod, each LOD in its own lightmap space; Bakery: no factor); None
    reads it from a <Piece>_LOD<n> name. lightmapper: "unity" (default; "progressive") or "bakery"."""
    d = _arrays(ob, layer if measured else None, evaluated=True, need_uv=measured)
    if d is None:
        raise ValueError("%s has no UV layer %r to measure" % (ob.name, layer))
    b = uv_box_share(d["uv"]) if measured else coverage
    short = uv_box_short_side(d["uv"]) if measured else None
    scale = scale * lod_factor(lod if lod is not None else lod_level(ob.name), lightmapper)
    return max(1, int(math.floor(footprint_px(float(_triangles(d)["a3"].sum()), texels_per_m, scale, b, lightmapper,
                                              short) + 1e-9)))


# ----------------------------------------------------------------------------------------------- changes (bpy)
def hard_surface_stack(ob):
    """True when ob carries a hard-surface normals stack: a Weighted Normal modifier (route B), a Bevel with Harden
    Normals (route A), or custom normals already in the mesh (a stack applied earlier). Such a piece is never shaded
    by angle again: seam it with seams_by_angle. Check it before apply_stack (apply_stack does)."""
    return (any(m.type == "WEIGHTED_NORMAL" for m in ob.modifiers)
            or any(m.type == "BEVEL" and m.harden_normals for m in ob.modifiers)
            or bool(getattr(ob.data, "has_custom_normals", False)))


def _smooth_by_angle(m):
    return m.type == "NODES" and m.node_group is not None and "Smooth by Angle" in m.node_group.name


def _changes_topology(m):
    """TOPOLOGY_TYPES, and any Geometry Nodes modifier but Smooth by Angle (a node tree can rebuild the mesh)."""
    return m.type in TOPOLOGY_TYPES or (m.type == "NODES" and not _smooth_by_angle(m))


def apply_stack(ob, keep_mirror=True, add_triangulate=False):
    """Step 1 of UV work on a modelled piece: apply its modifier stack from the top, in stack order, down to and
    including the last modifier that changes topology (TOPOLOGY_TYPES or a Geometry Nodes modifier other than Smooth
    by Angle; a Smooth by Angle or anything else above it goes with it), never a lower one alone, so the normals stay
    as designed. The stack is built Mirror / Array, Smooth by Angle, Bevel, Triangulate, Weighted Normal. Run it
    before applying the object's scale: a live Bevel's width is in object space. It stops at the stack's Triangulate,
    which stays unapplied and off in the viewport until after layout (turn it back on then); a Weighted Normal below
    stays live. keep_mirror=True keeps the Mirrors at the end of that run live (nothing but Mirrors changes topology
    below them): their halves share UVs through seams and unwrap. Call again with keep_mirror=False just before
    layout to apply them, first in the stack by then. A Mirror with a Bevel or other topology change below it is
    applied in the first run; its halves get unique UVs. add_triangulate=True gives a piece without a Triangulate one
    (Minimum Vertices 4, Keep Normals on) directly above any Weighted Normal, off until after layout.
    Returns {"hard_surface", "shading_designed", "applied", "mirrors_live", "triangulate"}: hard_surface (checked
    before anything is applied) means seams_by_angle and never shading by angle again; shading_designed means the
    piece's sharp edges were set already (a stack, a Smooth by Angle, or sharp edges marked): do not re-shade it."""
    if ob.type != "MESH":
        raise ValueError("%s is not a mesh" % ob.name)
    hard = hard_surface_stack(ob)
    sharp = ob.data.attributes.get("sharp_edge")
    marked = False
    if sharp is not None and sharp.domain == "EDGE" and len(sharp.data):
        vals = np.zeros(len(sharp.data), bool)
        sharp.data.foreach_get("value", vals)
        marked = bool(vals.any())
    designed = hard or marked or any(_smooth_by_angle(m) for m in ob.modifiers)
    mods = list(ob.modifiers)
    tri_i = next((i for i, m in enumerate(mods) if m.type == "TRIANGULATE"), len(mods))
    below = [m.name for m in mods[tri_i + 1:] if _changes_topology(m)]
    if below:
        raise ValueError("%s: %s sits below the Triangulate; move it above the Triangulate (a Mirror or Array goes "
                         "first in the stack, above the Bevel), then call again" % (ob.name, ", ".join(below)))
    topo = [i for i in range(tri_i) if _changes_topology(mods[i])]
    live = []
    while keep_mirror and topo and mods[topo[-1]].type == "MIRROR":
        live.insert(0, mods[topo.pop()].name)
    last = topo[-1] if topo else -1
    off = [m.name for m in mods[:last + 1] if not m.show_viewport]
    if off:
        raise ValueError("%s: %s is off in the viewport; turn it on or delete it, then call again"
                         % (ob.name, ", ".join(off)))
    if last >= 0 and ob.data.shape_keys:
        raise ValueError("%s has shape keys: Blender cannot apply its modifiers" % ob.name)
    if last >= 0 and ob.data.users > 1:
        raise ValueError("%s shares its mesh with %d other objects: apply on a single-user copy (Object > Relations > "
                         "Make Single User > Object & Data, on this one), point the others at its mesh (ob.data = "
                         "this.data) and remove their applied modifiers, then call again"
                         % (ob.name, ob.data.users - 1))
    applied = []
    was_edit = bpy.context.mode == "EDIT_MESH"
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob],
                                   selected_editable_objects=[ob]):
        if was_edit:
            bpy.ops.object.mode_set(mode="OBJECT")
        for _ in range(last + 1):
            name = ob.modifiers[0].name
            bpy.ops.object.modifier_apply(modifier=name)
            if ob.modifiers and ob.modifiers[0].name == name:
                raise ValueError("%s: Blender did not apply %s" % (ob.name, name))
            applied.append(name)
        tri = next((m for m in ob.modifiers if m.type == "TRIANGULATE"), None)
        if tri is None and add_triangulate:
            tri = ob.modifiers.new("Triangulate", "TRIANGULATE")
            tri.min_vertices, tri.keep_custom_normals = 4, True
            wn = next((i for i, m in enumerate(ob.modifiers) if m.type == "WEIGHTED_NORMAL"), None)
            if wn is not None:
                bpy.ops.object.modifier_move_to_index(modifier=tri.name, index=wn)
        if was_edit:
            bpy.ops.object.mode_set(mode="EDIT")
    if tri is not None:
        tri.show_viewport = False
    return {"hard_surface": hard, "shading_designed": designed, "applied": applied, "mirrors_live": live,
            "triangulate": tri.name if tri is not None else None}


def _edge_index(me, keys):
    """Indices into me.edges of the edges given as vertex-pair keys (min * (nv + 1) + max), as _edges returns."""
    ev = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    ekey = ev.min(1) * (len(me.vertices) + 1) + ev.max(1)
    order = np.argsort(ekey)
    if not len(order):
        return np.zeros(0, np.int64)
    pos = np.minimum(np.searchsorted(ekey[order], keys), len(order) - 1)
    return order[pos[ekey[order][pos] == keys]]


def _mark_seams(me, idx, clear=False):
    seam = np.zeros(len(me.edges), bool)
    if not clear:
        me.edges.foreach_get("use_seam", seam)
    seam[idx] = True
    me.edges.foreach_set("use_seam", seam)
    me.update()


def seams_from_hard_edges(objects, clear=False):
    """Mark a seam on every hard edge (where the corner normals split) of each mesh: the rule for meshes that take
    a baked normal map. Hardness comes from the evaluated mesh when its topology matches the mesh's own, so a Smooth
    by Angle modifier (what Shade Auto Smooth adds) or a live Weighted Normal counts; with a modifier that changes
    the topology, from the mesh itself (apply_stack first). On a plain mesh shade smooth by angle first: when flat
    shaded every edge is hard; a hard-surface stack is never re-shaded (seams_by_angle). Angle-based sharpness misses
    soft bevels and never opens a closed tube; place those seams by hand. clear=True first removes all seams.
    Returns {object name: hard edges found}."""
    out = {}
    was_edit = bpy.context.mode == "EDIT_MESH"
    if was_edit:
        bpy.ops.object.mode_set(mode="OBJECT")      # edge data written in Edit Mode is lost on the next toggle
    for ob in [o for o in objects if o.type == "MESH"]:
        me = ob.data
        d = _arrays(ob, None, evaluated=True, need_uv=False)
        if len(d["co"]) != len(me.vertices) or len(d["lv"]) != len(me.loops) or len(d["ls"]) != len(me.polygons):
            d = _arrays(ob, None, evaluated=False, need_uv=False)
        _pa, _pb, _uv_split, hard, key = _edges(d)
        idx = _edge_index(me, key[hard])
        _mark_seams(me, idx, clear)
        out[ob.name] = int(len(idx))
    if was_edit:
        bpy.ops.object.mode_set(mode="EDIT")
    return out


def seams_by_angle(objects, angle=SEAM_ANGLE):
    """Mark a seam on every edge whose two faces meet at more than angle degrees, read from the mesh itself: what
    mesh.edges_select_sharp(sharpness=radians(angle)) then mesh.mark_seam() do, without touching the selection or the
    normals. The seam rule for a piece with a hard-surface stack (hard_surface_stack), which keeps its own sharp
    edges and is never shaded by angle again; follow it with seams_from_hard_edges. It finds seam places, not hard
    edges. Returns {object name: edges seamed}."""
    out = {}
    was_edit = bpy.context.mode == "EDIT_MESH"
    if was_edit:
        bpy.ops.object.mode_set(mode="OBJECT")
    for ob in [o for o in objects if o.type == "MESH"]:
        me = ob.data
        d = _arrays(ob, None, evaluated=False, need_uv=False)
        pa, pb, _uv_split, _hard, key = _edges(d)
        pn = np.empty(len(me.polygons) * 3)
        me.polygons.foreach_get("normal", pn)
        pn = pn.reshape(-1, 3)
        idx = _edge_index(me, key[(pn[pa] * pn[pb]).sum(1) < math.cos(math.radians(angle))])
        _mark_seams(me, idx)
        out[ob.name] = int(len(idx))
    if was_edit:
        bpy.ops.object.mode_set(mode="EDIT")
    return out


def _edit(objects):
    """Enter edit mode on exactly these mesh objects with every face selected; returns the previous state."""
    prev = (bpy.context.view_layer.objects.active, [o for o in bpy.context.selected_objects], bpy.context.mode)
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    return prev


def _restore(prev):
    bpy.ops.object.mode_set(mode="OBJECT")
    active, selected, mode = prev
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in selected:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active
    if mode == "EDIT_MESH" and active is not None and active.type == "MESH":
        bpy.ops.object.mode_set(mode="EDIT")


def _set_active_layer(ob, layer):
    lay = _layer(ob.data, layer)
    if lay is None:
        raise ValueError("%s has no UV layer %r" % (ob.name, layer))
    ob.data.uv_layers.active = lay
    return lay


def _square(map_px, what):
    w, h = map_size(map_px)
    if w != h:
        raise ValueError("%s takes a square map (%dx%d given): Blender packs into a square tile" % (what, w, h))
    return w


def _uv_get(lay, nl):
    uv = np.empty(nl * 2)
    lay.uv.foreach_get("vector", uv)
    return uv.reshape(-1, 2)


def _hide_others(o, keep):
    """Hide every face not kept (and the edges and vertices only they use) so an operator sees the kept faces only;
    returns the previous hide flags for _unhide. Object Mode only."""
    me = o.data
    prev = []
    for coll in (me.vertices, me.edges, me.polygons):
        h = np.zeros(len(coll), bool)
        coll.foreach_get("hide", h)
        prev.append(h)
    lv = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", lv)
    lt = np.array([p.loop_total for p in me.polygons], np.int64)
    shown_v = np.zeros(len(me.vertices), bool)
    shown_v[lv[np.repeat(keep, lt)]] = True
    le =np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("edge_index", le)
    shown_e = np.zeros(len(me.edges), bool)
    shown_e[le[np.repeat(keep, lt)]] = True
    for coll, shown, h in zip((me.vertices, me.edges, me.polygons), (shown_v, shown_e, keep), prev):
        coll.foreach_set("hide", h | ~shown)
    return prev


def _unhide(o, prev):
    for coll, h in zip((o.data.vertices, o.data.edges, o.data.polygons), prev):
        coll.foreach_set("hide", h)
    o.data.update()


def pack(objects, map_px=1024, pad_px=None, layer=0, scale=True, rotate=False, rotate_method="CARDINAL",
         together=False, shape="CONCAVE", keep_stacks=False, material=None):
    """Pack each object's UV map (UV0 unless layer says otherwise) into the 0-1 tile with pad_px pixels between
    islands (default map_px / 64) and half of it to the tile edge: Blender's FRACTION margin puts margin at the edge
    and twice it between islands (measured on 5.2.2), so margin = pad_px / (2 * map_px). scale=False keeps island
    sizes (a set texel density). rotate=False (the default) keeps every island's orientation: right for directional
    textures (grain, text, decals); rotate=True with CARDINAL (90-degree steps) for straightened strips of
    non-directional textures and for lightmaps, rotate_method="ANY" only for organic non-directional islands.
    keep_stacks=True packs exactly stacked islands as one (Blender's merge_overlap merges every overlapping island,
    so separate the others first: layout() does). together=True packs all objects into one tile (an atlas).
    material: only the faces whose material name matches (a name or a pattern) are packed; the others keep their UVs
    where they are, overlapping the packed tile (right for a bake atlas of one material, which the others never
    sample), and objects without it are skipped. Restores the active UV layer, the selection, the hidden faces and
    the mode. Square maps only."""
    size = _square(map_px, "pack()")
    if pad_px is None:
        pad_px = size / 64.0
    objects = [o for o in objects if o.type == "MESH"]
    was_edit = bpy.context.mode == "EDIT_MESH"
    if material and bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")                 # mesh data reads empty in Edit Mode
    keeps = {o.name: _keep_faces(o, material) for o in objects}
    if material:
        objects = [o for o in objects if keeps[o.name].any()]
    groups = [objects] if together else [[o] for o in objects]
    for group in groups:
        if not group:
            continue
        prev_layers = [(o, o.data.uv_layers.active_index) for o in group]
        prev, hidden = None, []
        try:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            for o in group:
                _set_active_layer(o, layer)
                if keeps[o.name] is not None:
                    hidden.append((o, _hide_others(o, keeps[o.name])))
            prev = _edit(group)
            bpy.ops.uv.select_all(action="SELECT")
            bpy.ops.uv.pack_islands(udim_source="CLOSEST_UDIM", rotate=rotate, rotate_method=rotate_method,
                                    scale=scale, merge_overlap=keep_stacks, margin_method="FRACTION",
                                    margin=pad_px / (2.0 * size), shape_method=shape)
        finally:
            if hidden and bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            for o, h in hidden:
                _unhide(o, h)
            if prev is not None:
                _restore(prev)
            for o, i in prev_layers:
                o.data.uv_layers.active_index = i
    act = bpy.context.view_layer.objects.active
    if was_edit and bpy.context.mode == "OBJECT" and act is not None and act.type == "MESH":
        bpy.ops.object.mode_set(mode="EDIT")


def _lightmap_pack_fails(ob, layer_name, size):
    """True when the lightmap layer, read at size px, spills, collapses, overlaps or misses its gaps or edge."""
    d = _arrays(ob, layer_name, evaluated=False)
    r = measure(d, ob.name, map_px=size, pad_px=LIGHTMAP_GAP_TEXELS, purpose="lightmap")
    return bool(r["outside_0_1"] or r["zero_area_uv_faces"] or r.get("overlapping_island_pairs")
                or r.get("padding_ok") is False
                or (r["margin_px"] is not None and r["margin_px"] < 1.0 - EDGE_SLACK_PX))


def pack_lightmap(objects, texels_per_m, scale=1.0, layer=1, rotate=True, lod=None, notes=None, lightmapper="unity"):
    """Pack each object's lightmap UV (the second UV map unless layer says otherwise) so its charts stay at least 2
    texels apart, and 1 texel from the tile edge, whatever texel scale the lightmapper gives it: the worst case is a
    chart box that fills the tile (b = 1), so it packs at lightmap_footprint(coverage=1.0) px with a 2 px gap, and
    the packed charts fill their box. scale: the renderer's lightmap scale, one number or {object name: scale}. lod:
    the LOD level (each LOD packs for its own footprint, x LOD_SCALE^n); None reads it from each <Piece>_LOD<n> name.
    lightmapper "bakery": packs for Bakery's footprint with the box filling the tile, texels_per_m x sqrt(2 x area x
    scale) - 6 (its Default packer's inset; xatlas has none, so the gaps hold under both), no LOD factor; a linear
    factor s on Bakery's texel scale needs scale s^2.
    A footprint too small for 2-texel gaps (under lightmap_capacity_px for its charts, or under 64 px where the pack
    misses them) is packed for 64 px instead, never left to spill: a valid UV2 for a probe-lit prop or LOD, or once
    its Scale In Lightmap is raised. The note is printed and, given a dict, stored in notes[object name]. Rotation is
    on: lightmaps have no direction. Returns {object name: the size it packed for, px}."""
    out = {}
    lightmapper = lightmapper_name(lightmapper)
    for ob in [o for o in objects if o.type == "MESH"]:
        sc = scale.get(ob.name, 1.0) if isinstance(scale, dict) else scale
        size = lightmap_footprint(ob, texels_per_m, sc, coverage=1.0, lod=lod, lightmapper=lightmapper)
        lay = _layer(ob.data, layer)
        if lay is None:
            raise ValueError("%s has no UV layer %r" % (ob.name, layer))
        charts = len(_island_boxes(ob, lay)[1])
        lname = lay.name                                     # a layer reference does not survive the pack's mode switch
        need = lightmap_capacity_px(charts)
        reason = None
        if size < need:
            reason = "%d charts need %.0f px" % (charts, need)
        else:
            pack([ob], map_px=size, pad_px=LIGHTMAP_GAP_TEXELS, layer=layer, rotate=rotate)
            if size < LIGHTMAP_MIN_FOOTPRINT_PX and _lightmap_pack_fails(ob, lname, size):
                reason = "the pack at %d px missed them" % size
        if reason:
            pack([ob], map_px=LIGHTMAP_MIN_FOOTPRINT_PX, pad_px=LIGHTMAP_GAP_TEXELS, layer=layer, rotate=rotate)
            note = lightmap_small_note(size, reason, lod if lod is not None else lod_level(ob.name), lightmapper)
            print("  NOTE   %s: %s" % (ob.name, note))
            if notes is not None:
                notes[ob.name] = note
            size = LIGHTMAP_MIN_FOOTPRINT_PX
        out[ob.name] = size
    return out


def corner_misfit(P, Q):
    """Per corner, how far Q[i] lies from P[i] after the best rotation and translation of P onto Q (no mirroring, no
    scaling). Near 0 everywhere when Q is a moved and turned copy of P listed in the same corner order."""
    P, Q = np.asarray(P, float), np.asarray(Q, float)
    A, B = P - P.mean(0), Q - Q.mean(0)
    U, _S, Vt = np.linalg.svd(A.T @ B)
    d = 1.0 if np.linalg.det(Vt.T @ U.T) >= 0 else -1.0
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T                  # q = R p for column vectors
    return np.linalg.norm(A @ R.T - B, axis=1)


def turn_islands(objects, map_px=1024, layer=0, material=None):
    """Turn every long island whose long side runs along V by 90 deg about its centre, so it runs along U: the trim
    strips that no single GEOMETRY axis lays along U (tube strips, rings). The turn is made in square pixels of
    map_px, so a strip on a non-square sheet ("2048x1024") stays undistorted. material: only the faces whose material
    name matches (a name or a pattern): on a mesh that also has tiling faces, turn the trim strips alone. Check a
    profiled strip's top side afterwards and turn it 180 deg more if it faces the wrong way. Leaves Edit Mode while
    it writes. Returns {object name: islands turned}."""
    w, h = map_size(map_px)
    s = float(max(w, h))
    aspect = np.array([w / s, h / s])
    out = {}
    was_edit = bpy.context.mode == "EDIT_MESH"
    if was_edit:
        bpy.ops.object.mode_set(mode="OBJECT")
    try:
        for ob in [o for o in objects if o.type == "MESH"]:
            lay = _layer(ob.data, layer)
            if lay is None:
                raise ValueError("%s has no UV layer %r" % (ob.name, layer))
            full = _arrays(ob, lay.name, evaluated=False)
            keep = _material_faces(full, material) if material else np.ones(len(full["ls"]), bool)
            if not keep.any():
                out[ob.name] = 0                                         # no face with that material: untouched
                continue
            d = _subset(full, keep) if material else full
            pa, pb, uv_split, _hard, _key = _edges(d)
            isl = _islands(len(d["ls"]), pa, pb, ~uv_split)
            n = int(isl.max()) + 1 if len(isl) else 0
            _elong, along_v = _orientation(d, isl, n, tuple(aspect))
            isl_loop = np.repeat(isl, d["lt"])
            p = d["uv"] * aspect
            cnt = np.maximum(np.bincount(isl_loop, minlength=n), 1)
            c = np.stack([np.bincount(isl_loop, weights=p[:, k], minlength=n) / cnt for k in (0, 1)], 1)[isl_loop]
            sel = along_v[isl_loop] if n else np.zeros(len(p), bool)
            q = p.copy()
            q[sel, 0] = c[sel, 0] - (p[sel, 1] - c[sel, 1])
            q[sel, 1] = c[sel, 1] + (p[sel, 0] - c[sel, 0])
            uv = full["uv"].copy()
            uv[np.repeat(keep, full["lt"])] = q / aspect                 # the other faces' UVs are left as they were
            lay.uv.foreach_set("vector", uv.ravel())
            ob.data.update()
            out[ob.name] = int(along_v.sum())
    finally:
        if was_edit:
            bpy.ops.object.mode_set(mode="EDIT")
    return out


def pair_faces(ob, src_faces, offset, tol=None):
    """The faces of a copy, in src_faces' order: for each source face, the face whose centre sits at its centre +
    offset (object space, metres). For copies whose faces are not one contiguous index range, as an Array's are once
    a Bevel below it is applied: stack_faces(ob, src, pair_faces(ob, src, (0, 0, step))). tol defaults to 1/1000 of
    the source faces' size; raises when a face has no partner."""
    me = ob.data
    cen = np.empty(len(me.polygons) * 3)
    me.polygons.foreach_get("center", cen)
    cen = cen.reshape(-1, 3)
    src = np.asarray(list(src_faces), np.int64)
    if tol is None:
        tol = 1e-3 * max(float(np.linalg.norm(cen[src].max(0) - cen[src].min(0))), 1e-3)
    want = cen[src] + np.asarray(offset, float)
    out = []
    for f, p in zip(src.tolist(), want):
        dist = np.linalg.norm(cen - p, axis=1)
        j = int(np.argmin(dist))
        if dist[j] > tol:
            raise ValueError("face %d has no copy at offset %s (nearest centre %.3g m away)" % (f, tuple(offset),
                                                                                                dist[j]))
        out.append(j)
    return out


STACK_REFUSED = ("the likely causes: a mirrored copy (stack mirrored halves with a live Mirror modifier instead), a "
                 "scaled copy (even 1.001x), or faces re-ordered after duplicating (Array copies once a Bevel below "
                 "them is applied: pair them with pair_faces; a Bevel applied after a bmesh duplicate; a Triangulate: "
                 "stack before triangulating)")


def stack_faces(ob, src_faces, dst_faces, layer=0):
    """Stack a duplicated part exactly on its source: copy the UVs of src_faces onto dst_faces face by face and
    corner by corner, in order (a part duplicated from another keeps its face and corner order; it may be moved and
    turned). Raises, writing nothing, when the copy's corners do not follow the source's after a move and a turn:
    a mirrored or scaled copy, or faces re-ordered after duplicating (a Triangulate, or a Bevel applied after a bmesh
    duplicate), so stack before triangulating. Call once per copy. Leaves Edit Mode while it writes. Returns the
    number of faces written."""
    if len(src_faces) != len(dst_faces):
        raise ValueError("%d source faces for %d copies: %s" % (len(src_faces), len(dst_faces), STACK_REFUSED))
    was_edit = bpy.context.mode == "EDIT_MESH"
    if was_edit:
        bpy.ops.object.mode_set(mode="OBJECT")
    try:
        me = ob.data
        lay = _layer(me, layer)
        if lay is None:
            raise ValueError("%s has no UV layer %r" % (ob.name, layer))
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        lv = np.empty(len(me.loops), np.int64)
        me.loops.foreach_get("vertex_index", lv)
        src_l, dst_l = [], []
        for a, b in zip(src_faces, dst_faces):
            pa, pb = me.polygons[a], me.polygons[b]
            if pa.loop_total != pb.loop_total:
                raise ValueError("face %d has %d corners, its copy %d has %d: %s"
                                 % (a, pa.loop_total, b, pb.loop_total, STACK_REFUSED))
            src_l += range(pa.loop_start, pa.loop_start + pa.loop_total)
            dst_l += range(pb.loop_start, pb.loop_start + pb.loop_total)
        P, Q = co[lv[src_l]], co[lv[dst_l]]
        off = corner_misfit(P, Q)
        # 1/10000 of the part's size, plus float32 rounding of coordinates far from the origin
        tol = 1e-4 * float(np.linalg.norm(P.max(0) - P.min(0))) + 1e-6 * max(1.0, float(np.abs(co).max()))
        if (off > tol).any():
            i = int(np.argmax(off > tol))
            k = 0
            for a, b in zip(src_faces, dst_faces):
                n = me.polygons[a].loop_total
                if i < k + n:
                    raise ValueError("face %d is not a moved and turned copy of face %d corner by corner (%.3g m off); "
                                     "%s" % (b, a, off[i], STACK_REFUSED))
                k += n
        uv = _uv_get(lay, len(me.loops))
        uv[dst_l] = uv[src_l]
        lay.uv.foreach_set("vector", uv.ravel())
        me.update()
    finally:
        if was_edit:
            bpy.ops.object.mode_set(mode="EDIT")
    return len(dst_faces)


def _scale_density(d, target, aspect, per_island):
    """New UVs for flat arrays d: every island at target UV units per metre (per_island) or the whole object scaled
    by one factor. Islands whose faces are all marked low-density take the object's factor, keeping their size
    relative to the rest. Returns (uv, area-weighted mean factor)."""
    npoly = len(d["ls"])
    pa, pb, uv_split, _hard, _key = _edges(d)
    isl = _islands(npoly, pa, pb, ~uv_split)
    n = int(isl.max()) + 1 if npoly else 0
    tr = _triangles(d, aspect)
    it = isl[d["tpoly"]]
    a3 = np.bincount(it, weights=tr["a3"], minlength=n)
    au = np.bincount(it, weights=np.abs(tr["au"]), minlength=n)
    low = d.get("low")
    low = np.asarray(low, bool) if low is not None and len(low) == npoly else np.zeros(npoly, bool)
    marked = (np.bincount(isl, weights=(~low).astype(float), minlength=n) == 0) & (np.bincount(isl, minlength=n) > 0)
    unm = ~marked & (au > 0)
    big = (target / math.sqrt(au[unm].sum() / max(a3[unm].sum(), 1e-30))) if unm.any() else 1.0
    if per_island:
        f = np.where(au > 0, target / np.sqrt(np.maximum(au, 1e-30) / np.maximum(a3, 1e-30)), 1.0)
        f[marked] = big
    else:
        f = np.full(n, big)
    isl_loop = np.repeat(isl, d["lt"])
    uv = d["uv"].copy()
    corners = np.maximum(np.bincount(isl_loop, minlength=n), 1)
    centre = np.stack([np.bincount(isl_loop, weights=uv[:, k], minlength=n) / corners for k in (0, 1)], 1)
    uv = centre[isl_loop] + (uv - centre[isl_loop]) * f[isl_loop][:, None]
    return uv, round(float(np.average(f, weights=np.maximum(a3, 1e-30))), 4) if n else 1.0


def set_texel_density(objects, px_per_m, map_px, layer=0, per_island=True, pack_after=True, pad_px=None,
                      keep_stacks=False, rotate=False, material=None):
    """Scale UV islands (UV0 unless layer says otherwise) so the surface gets px_per_m texels per metre on a map_px
    texture, measured in world space on the evaluated mesh. per_island=True also evens islands out (like Average
    Islands Scale); islands whose faces are all marked uv_low_density keep their size relative to the rest.
    pack_after=True then packs with scale=False and keep_stacks / rotate as given. material: only the faces whose
    material name matches (a name or a pattern; the others keep their UVs), with pack_after=False: on a mesh that
    mixes trim and tiling, scale the trim strips alone. layout() is the safer call: it also separates non-stacked
    islands before a stack-keeping pack and checks the fit. Leaves Edit Mode while it writes (edit-mode data would
    overwrite the UVs) and restores the active UV layer. Returns {object name: area-weighted mean factor}."""
    w, h = map_size(map_px)
    s = float(max(w, h))
    if pack_after and material:
        raise ValueError("set_texel_density(material=...) scales those faces only; a pack moves every face: pass "
                         "pack_after=False and place the islands yourself")
    if pack_after:
        _square((w, h), "set_texel_density(pack_after=True)")
    objects = [o for o in objects if o.type == "MESH"]
    was_edit = bpy.context.mode == "EDIT_MESH"
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    out = {}
    for ob in objects:
        prev = ob.data.uv_layers.active_index
        lay = _set_active_layer(ob, layer)
        try:
            d = _arrays(ob, lay.name, evaluated=True)
            if len(d["uv"]) != len(ob.data.loops):
                raise ValueError("%s: its modifiers change its corners: apply the stack from the top first "
                                 "(apply_stack; apply_stack(keep_mirror=False) for a Mirror kept live) and keep the "
                                 "Triangulate off in the viewport until after layout" % ob.name)
            if material:
                keep = _material_faces(d, material)
                if not keep.any():
                    out[ob.name] = None                                # no face with that material: untouched
                    continue
                sub, out[ob.name] = _scale_density(_subset(d, keep), px_per_m / s, (w / s, h / s), per_island)
                uv = d["uv"].copy()
                uv[np.repeat(keep, d["lt"])] = sub                     # the other faces' UVs are left as they were
            else:
                uv, out[ob.name] = _scale_density(d, px_per_m / s, (w / s, h / s), per_island)
            lay.uv.foreach_set("vector", uv.ravel())
            ob.data.update()
        finally:
            ob.data.uv_layers.active_index = prev
    if pack_after:
        pack(objects, map_px=(w, h), pad_px=pad_px, layer=layer, scale=False, keep_stacks=keep_stacks, rotate=rotate)
    if was_edit and bpy.context.view_layer.objects.active is not None:
        bpy.ops.object.mode_set(mode="EDIT")
    return out


def tile_project(objects, tile_m, layer=0, material=None, offset=(0.0, 0.0, 0.0)):
    """Tiling UVs for kit pieces that continue across joints: a box projection from each piece's own axes, one tile
    per tile_m metres (map_px / px_per_m), phase 0 at its pivot, U to the right seen from the front of each face and
    V up (tile_uv). Replaces Cube Projection for kits: bpy.ops.uv.cube_project centres the projection on the
    selection's bounds (Blender 5.2.2: a 1 m wall started at U 0.375 and a 2 m wall at 0.25 with cube_size 4), so
    pieces of different sizes start out of phase. Positions are the mesh's own with the object's scale applied (apply
    scale first; a pivot off the grid shifts the pattern; a negative scale is refused). material: only faces whose
    material matches (a name or pattern), the rest keep their UVs. offset (metres, the piece's axes): a phase variant,
    projected as if the piece stood that far along (k x module for the copy placed k modules into a longer tile).
    Each face's plane comes from its own positions (Newell, float64), as tile_phase reads it. Writes the mesh data, so
    apply the stack first (apply_stack). Returns {object name: faces written}."""
    objects = [o for o in objects if o.type == "MESH"]
    neg = [o.name for o in objects if min(o.scale) < 0]
    if neg:
        raise ValueError("tile_project: %s mirrored by a negative scale: apply the scale first (the projection reads "
                         "each piece's own axes)" % ", ".join(neg))
    was_edit = bpy.context.mode == "EDIT_MESH"
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    out = {}
    for ob in objects:
        me = ob.data
        if layer == 0 and not me.uv_layers:
            me.uv_layers.new(name="UVMap")
        prev = me.uv_layers.active_index
        lay = _set_active_layer(ob, layer)
        try:
            keep = _keep_faces(ob, material)
            sc = np.array(ob.scale, float)
            co = np.empty(len(me.vertices) * 3)
            me.vertices.foreach_get("co", co)
            co = co.reshape(-1, 3) * sc + np.asarray(offset, float)
            uv = _uv_get(lay, len(me.loops))
            n = 0
            for p in me.polygons:
                if keep is not None and not keep[p.index]:
                    continue
                corners = list(range(p.loop_start, p.loop_start + p.loop_total))
                vs = [me.loops[i].vertex_index for i in corners]
                q = co[vs]
                normal = np.cross(q, np.roll(q, -1, axis=0)).sum(axis=0)          # Newell, as tile_phase
                uv[corners] = tile_uv(q, normal, tile_m)
                n += 1
            lay.uv.foreach_set("vector", uv.ravel())
            me.update()
            out[ob.name] = n
        finally:
            me.uv_layers.active_index = prev
    if was_edit and bpy.context.view_layer.objects.active is not None:
        bpy.ops.object.mode_set(mode="EDIT")
    return out


def _island_boxes(ob, lay, keep=None):
    """Islands of the mesh's own layer: id per corner, bounding boxes, unsigned and signed UV areas, UVs. keep: per
    polygon, only those faces (the corners and UVs returned are theirs; write back with _write_uv)."""
    d = _arrays(ob, lay.name, evaluated=False)
    if keep is not None:
        d = _subset(d, keep)
    pa, pb, uv_split, _hard, _key = _edges(d)
    isl = _islands(len(d["ls"]), pa, pb, ~uv_split)
    n = int(isl.max()) + 1 if len(isl) else 0
    au = _triangles(d)["au"]
    it = isl[d["tpoly"]]
    signed = np.bincount(it, weights=au, minlength=n)
    area = np.bincount(it, weights=np.abs(au), minlength=n)
    lo, hi = _boxes(d, isl, n)
    return np.repeat(isl, d["lt"]), lo, hi, area, signed, d["uv"]


def _keep_faces(ob, material):
    """Per polygon of ob's mesh: True where its material matches material (a name or pattern); None for every face."""
    if not material:
        return None
    return _material_faces(_arrays(ob, None, evaluated=False, need_uv=False), material)


def _write_uv(o, lay, uv, keep=None):
    """Write UVs for the kept faces' corners (all corners when keep is None) and leave the others as they were."""
    if keep is not None:
        full = _uv_get(lay, len(o.data.loops))
        full[np.repeat(keep, [p.loop_total for p in o.data.polygons])] = uv
        uv = full
    lay.uv.foreach_set("vector", np.asarray(uv, float).ravel())
    o.data.update()


def _split_long(o, lay, max_m, keep=None):
    """Cut every island longer than max_m metres (along its box's long axis, in the world-space size its own UV
    density gives) into equal pieces by face centre, and move piece j along that axis by j x (the island's length +
    1), so the pack places each piece on its own. Translation only: no piece is rotated or scaled, so the tangent
    frame stays. Copies of a stack are cut and moved alike, so they stay stacked. Returns the islands cut."""
    d = _arrays(o, lay.name, evaluated=False)
    if keep is not None:
        d = _subset(d, keep)
    npoly = len(d["ls"])
    if not npoly:
        return 0
    pa, pb, uv_split, _hard, _key = _edges(d)
    isl = _islands(npoly, pa, pb, ~uv_split)
    n = int(isl.max()) + 1
    tr = _triangles(d)
    it = isl[d["tpoly"]]
    a3 = np.bincount(it, weights=tr["a3"], minlength=n)
    au = np.bincount(it, weights=np.abs(tr["au"]), minlength=n)
    lo, hi = _boxes(d, isl, n)
    ext = hi - lo
    axis = (ext[:, 1] > ext[:, 0]).astype(np.int64)
    span = ext[np.arange(n), axis]
    length_m = span / np.maximum(np.sqrt(np.maximum(au, 1e-30) / np.maximum(a3, 1e-30)), 1e-30)
    pieces = np.where((au > 0) & (a3 > 0) & (length_m > max_m), np.ceil(length_m / max_m - 1e-6), 1).astype(np.int64)
    if (pieces <= 1).all():
        return 0
    uv = d["uv"].copy()
    centre = np.add.reduceat(uv, d["ls"], axis=0) / d["lt"][:, None]
    ax = axis[isl]
    t = (centre[np.arange(npoly), ax] - lo[isl, ax]) / np.maximum(span[isl], 1e-30)
    j = np.clip((t * pieces[isl]).astype(np.int64), 0, pieces[isl] - 1)
    shift = np.zeros((npoly, 2))
    shift[np.arange(npoly), ax] = j * (span[isl] + 1.0)
    _write_uv(o, lay, uv + np.repeat(shift, d["lt"], axis=0), keep)
    return int((pieces > 1).sum())


def _stack_groups(lo, hi, area):
    """Islands with the same shape, position (whole-tile offsets ignored) and area: each group is one stack."""
    t = np.floor(lo + UV_EPS)
    key = np.c_[lo - t, hi - t]
    groups, done = [], np.zeros(len(lo), bool)
    for i in range(len(lo)):
        if done[i]:
            continue
        m = (~done & (np.abs(key - key[i]).max(1) <= 1e-5)
             & (np.abs(area - area[i]) <= 1e-3 * max(area[i], 1e-12)))
        idx = np.flatnonzero(m)
        done[idx] = True
        groups.append(idx)
    return groups, t


def _bake_offsets(o, lay, faces=None):
    """For a bake: all but one copy of each stack exactly +1 in U (the copy kept inside 0-1 is not mirrored), then
    the flipped half of every island folded onto itself (mirrored halves joined on an axis, as a Mirror modifier
    applied with Merge on leaves them) +1 in U, face corner by face corner. faces: per polygon, only those. Returns
    (copies moved, halves moved)."""
    isl_loop, lo, hi, area, signed, uv = _island_boxes(o, lay, faces)
    stacks, _t = _stack_groups(lo, hi, area)
    shift = np.zeros_like(lo)
    moved = 0
    for g in stacks:
        if len(g) < 2:
            continue
        upright = [i for i in g.tolist() if signed[i] > 0]
        keep = upright[0] if upright else int(g[0])
        for i in g.tolist():
            if i != keep:
                shift[i, 0] = 1.0
                moved += 1
    if moved:
        _write_uv(o, lay, uv + shift[isl_loop], faces)
    d = _arrays(o, lay.name, evaluated=False)
    if faces is not None:
        d = _subset(d, faces)
    pa, pb, uv_split, _hard, _key = _edges(d)
    ids, _split, flipped = _island_ids(d, pa, pb, uv_split, _triangles(d)["au"])
    halves = 0
    if flipped.any():
        umax = np.maximum.reduceat(d["uv"][:, 0], d["ls"]) if len(d["ls"]) else np.zeros(0)
        sel = flipped & (umax <= 1 + UV_EPS)                    # only halves still inside the tile
        if sel.any():
            uv2 = d["uv"].copy()
            uv2[np.repeat(sel, d["lt"]), 0] += 1.0
            _write_uv(o, lay, uv2, faces)
            halves = int(len(np.unique(ids[sel])))
    return moved, halves


def layout(objects, map_px, px_per_m=None, pad_px=None, layer=0, directional=True, rotate_method="CARDINAL",
           bake=False, together=False, material=None, max_island_m=None):
    """Step 8 of the order of work, its parts in their only safe order, on a UV map (UV0 unless layer says
    otherwise) already unwrapped, straightened, oriented and stacked (identical parts placed exactly on one copy,
    faces lowered on purpose marked):
      1. density: every island to px_per_m, marked islands kept relative to the rest (px_per_m=None: sizes as they
         are, and the pack scales everything to fill the tile);
      2. stacks found by shape (copies already moved by whole tiles count) and every stack moved clear of the
         others, so the pack merges true stacks only;
      3. one pack: stacks kept, sizes kept when px_per_m is set, rotation off when directional (else rotate_method);
      4. fit check: fits=False when any island ends outside 0-1 (never a silent spill);
      5. bake=True: all but one copy of each stack, and the flipped half of each island folded onto itself (a Mirror
         modifier applied with Merge on), moved exactly +1 in U.
    material: only the faces whose material name matches (a name or a pattern) take part in every step; the others
    keep their UVs, and objects without it are skipped. With together=True: one material's faces of several meshes
    packed into a shared bake atlas, without the other materials taking space they never use.
    max_island_m: before the pack, islands longer than this many metres are cut into pieces that pack on their own,
    moved but never turned or scaled (a long sofa shell otherwise caps the whole atlas's scale). For a bake atlas
    only: each cut is a UV seam, which the bake's margin (dilation) covers, but a tiling or hand-painted texture
    would show it.
    Square maps only. Restores the active UV layer and the mode. Returns {object name: {"factor", "fits",
    "islands", "stacks", "copies_moved", "mirror_halves_moved", "islands_cut"}}."""
    size = _square(map_px, "layout()")
    objects = [o for o in objects if o.type == "MESH"]
    was_edit = bpy.context.mode == "EDIT_MESH"
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    keeps = {o.name: _keep_faces(o, material) for o in objects}
    if material:
        objects = [o for o in objects if keeps[o.name].any()]
    prev = [(o, o.data.uv_layers.active_index) for o in objects]
    out = {o.name: {"factor": None, "islands_cut": 0} for o in objects}
    try:
        if px_per_m and objects:
            for name, f in set_texel_density(objects, px_per_m, size, layer=layer, pack_after=False,
                                             material=material).items():
                out[name]["factor"] = f
        groups = [objects] if together else [[o] for o in objects]
        for group in groups:
            if not group:
                continue
            boxes = []
            for o in group:
                lay = _layer(o.data, layer)
                if lay is None:
                    raise ValueError("%s has no UV layer %r" % (o.name, layer))
                if max_island_m:
                    out[o.name]["islands_cut"] = _split_long(o, lay, max_island_m, keeps[o.name])
                isl_loop, lo, hi, area, _signed, uv = _island_boxes(o, lay, keeps[o.name])
                stacks, t = _stack_groups(lo, hi, area)
                boxes.append((o, lay, isl_loop, lo, hi, uv, stacks, t))
            # each stack (or single island) gets its own cell of a square grid, far enough apart that nothing but a
            # true stack overlaps; a grid keeps coordinates small, so float32 UVs keep their precision
            step = math.ceil(max([float((b[4] - b[3]).max()) for b in boxes if len(b[3])] or [1.0])) + 1.0
            cols = max(1, int(math.ceil(math.sqrt(sum(len(b[6]) for b in boxes)))))
            slot = 0
            for o, lay, isl_loop, lo, hi, uv, stacks, t in boxes:
                shift = np.zeros_like(lo)
                for g in stacks:
                    shift[g] = -t[g] + step * np.array([slot % cols, slot // cols], float)
                    slot += 1
                _write_uv(o, lay, uv + shift[isl_loop], keeps[o.name])
            pack(group, map_px=size, pad_px=pad_px, layer=layer, scale=not px_per_m, rotate=not directional,
                 rotate_method=rotate_method, keep_stacks=True, together=together, material=material)
        for o in objects:
            lay = _layer(o.data, layer)
            keep = keeps[o.name]
            uv = _uv_get(lay, len(o.data.loops))
            if keep is not None:
                uv = uv[np.repeat(keep, [p.loop_total for p in o.data.polygons])]
            if len(uv):
                t0 = np.floor(uv.min(0) + UV_EPS)        # a packer that chose another tile: bring it home
                if t0.any():
                    uv = uv - t0
                    _write_uv(o, lay, uv, keep)
            out[o.name]["fits"] = bool(not len(uv) or (uv.min() >= -UV_EPS and uv.max() <= 1 + UV_EPS))
            _isl_loop, lo, hi, area, _signed, _uv = _island_boxes(o, lay, keep)
            stacks, _t = _stack_groups(lo, hi, area)
            moved, halves = _bake_offsets(o, lay, keep) if bake else (0, 0)
            out[o.name].update({"islands": int(len(lo)), "stacks": int(sum(len(g) > 1 for g in stacks)),
                                "copies_moved": moved, "mirror_halves_moved": halves})
    finally:
        for o, i in prev:
            o.data.uv_layers.active_index = i
        if was_edit and bpy.context.view_layer.objects.active is not None:
            bpy.ops.object.mode_set(mode="EDIT")
    return out


# ----------------------------------------------------------------------------------------------- command line
def _main(argv):
    """The command line. Exit code 0: no issues; 1: something needs a look; 2: a request that cannot be audited
    (no mesh matched, a lightmap without a footprint or texels per metre, --lightmap or texels per metre with
    another purpose, --text with no face marked uv_text, a bad map size)."""
    try:
        return _run(argv)
    except ValueError as e:
        print("uv_audit: %s" % e)
        return 2


def _run(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="uv_audit.py", description="Audit a UV layer of every matching mesh.")
    ap.add_argument("--objects", default="*", help="name pattern (case-sensitive fnmatch), default every mesh")
    ap.add_argument("--layer", default=None, help="UV map index or name; default 0 (UV0), or 1 for a lightmap; "
                    "'active' for the active map")
    ap.add_argument("--purpose", choices=PURPOSES, default=None, help="what the layer is for (default unique)")
    ap.add_argument("--lightmap", action="store_true", help="same as --purpose lightmap")
    ap.add_argument("--map", default=None, help="texture size in pixels: 1024 (default), or 2048x1024 for a "
                    "non-square map; for a lightmap, the footprint (fractions round down), or leave it out and give "
                    "--lightmap-texels")
    ap.add_argument("--pad", type=float, default=None, help="gap between islands in pixels (default map/64; 2 for a "
                    "lightmap; none for tiling and trim)")
    ap.add_argument("--td", type=float, default=None, help="target texel density, px per metre")
    ap.add_argument("--baking", action="store_true", help="the layer takes a baked normal map or AO")
    ap.add_argument("--directional", action="store_true", help="the texture has a direction: long islands along U")
    ap.add_argument("--text", action="store_true", help="check the faces marked uv_text: not mirrored, the letters' "
                    "up (uv_text_up, default 3D +Z) on +V")
    ap.add_argument("--material", default=None, help="only the faces whose material name matches (a name or a "
                    "pattern); meshes without it are skipped")
    ap.add_argument("--rows", default=None, help="trim rows in pixels, e.g. 0-128,128-192: islands must stay in one")
    ap.add_argument("--lightmap-texels", type=float, default=None, help="lightmap texels per metre: a lightmap audit "
                    "(of the second UV map unless --layer says otherwise) at the footprint of its measured UV2 box")
    ap.add_argument("--lightmap-scale", type=float, default=1.0, help="the renderer's lightmap scale (default 1)")
    ap.add_argument("--lod", type=int, default=None, help="LOD level for a lightmap audit (texel scale x 0.5^n); "
                    "default: read from each object's <Piece>_LOD<n> name, else 0")
    ap.add_argument("--lightmapper", default="unity", help="whose footprint a lightmap audit uses: unity (default; "
                    "progressive is the same) or bakery")
    ap.add_argument("--tile-m", type=float, default=None, help="tiling: the tile's size in metres (map / px per m): "
                    "every face checked against tile_project's scale and phase, so kit pieces continue at joints")
    ap.add_argument("--steps", default=None, help="with --tile-m: placement steps in metres, e.g. 1,3 (grid module, "
                    "storey height): each must be a whole number of tiles")
    ap.add_argument("--tile-offset", default=None, help="with --tile-m: a phase variant's offset in metres, x,y,z "
                    "(as given to tile_project)")
    ap.add_argument("--json", default=None, help="write the full reports here")
    ap.add_argument("--shared", action="store_true", help="the matched objects share one texture (an atlas): also "
                    "check overlaps and gaps between them")
    a = ap.parse_args(argv)
    layer = int(a.layer) if a.layer is not None and a.layer.isdigit() else a.layer
    purpose = _purpose(a.purpose, a.lightmap, a.lightmap_texels)
    map_px = map_size(a.map) if a.map else None
    if purpose == "lightmap" and not map_px and not a.lightmap_texels:
        raise ValueError("a lightmap audit needs --map <footprint px> or --lightmap-texels")
    obs = [o for o in bpy.data.objects if o.type == "MESH" and fnmatch.fnmatchcase(o.name, a.objects)]
    if not obs:
        raise ValueError("no mesh matched --objects %r (the pattern is case-sensitive)" % a.objects)
    if a.material:
        obs = [o for o in obs if has_material(o, a.material)]
        if not obs:
            raise ValueError("no mesh matched --objects %r has a material matching --material %r"
                             % (a.objects, a.material))
    reps = audit_objects(obs, report_path=a.json, layer=layer, map_px=map_px, pad_px=a.pad, px_per_m=a.td,
                         purpose=purpose, baking=a.baking, directional=a.directional, rows=a.rows,
                         texels_per_m=a.lightmap_texels, lightmap_scale=a.lightmap_scale, text=a.text, lod=a.lod,
                         material=a.material, lightmapper=lightmapper_name(a.lightmapper), tile_m=a.tile_m,
                         steps=[float(x) for x in a.steps.split(",")] if a.steps else None,
                         tile_offset=tuple(float(x) for x in a.tile_offset.split(",")) if a.tile_offset
                         else (0.0, 0.0, 0.0))
    bad = any(r["issues"] for r in reps)
    if a.shared:
        sh = audit_shared(obs, layer=layer, map_px=map_px or 1024, pad_px=a.pad, purpose=purpose,
                          material=a.material)
        print("  %-6s shared layout of %d objects: cov %s  %s" % ("OK" if not sh["issues"] else "CHECK",
              len(sh["objects"]), sh.get("coverage"), "; ".join(sh["issues"]) or sh.get("note", "no issues")))
        bad = bad or bool(sh["issues"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []))
