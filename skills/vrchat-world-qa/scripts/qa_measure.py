"""Read-only measurements for world QA: kit pieces, assemblies, placements, linking, images, UV data and FBX
re-imports, plus review renders (orthographic, perspective, textured, wireframe), SVG overlays and image statistics.

Host: Blender 4.1+ (bpy and its bundled numpy), no add-ons beyond the bundled FBX importer; tested on Blender 5.2.2.
Changes nothing in the file and never saves it.

Command line (open the file read-only; one JSON report, one summary line per piece, a PROBLEM line per failure).
Always pass --python-exit-code 1: without it a crash still exits 0. Any run that opens a .blend or imports FBX needs
--module (the spec's grid.module; there is no default). A measuring run prints a "[qa] role ..." line; a run without
it, or without its JSON, did not finish.
    blender -b --factory-startup KIT_Arch_Exterior.blend --python-exit-code 1 --python qa_measure.py --
            --module 1.0 --expect-status modelled --piece-tris '{"EXT": 800, "EXT_Door_2x3_A": 400}' --json kit.json
    blender -b --factory-startup MASTER.blend --python-exit-code 1 --python qa_measure.py -- --module 1.0
            --sub-module 0.25 --expect-status textured --compare-placements stage5_master.json --json master.json
    blender -b --factory-startup --python-exit-code 1 --python qa_measure.py -- --module 1.0
            --import-fbx "export/fbx/EXT/*.fbx" --json fbx.json     # quote the glob: qa_measure expands it in any shell
    blender -b --factory-startup KIT_Arch_Exterior.blend --python-exit-code 1 --python qa_measure.py -- --module 1.0
            --lightmap-texels 20 --lightmap-scale '{"EXT_Trim_2_A": 0.5}' --probe-lit "PROP_*_Free_*"
            --texel-map 1024 --json uv.json         # UV2 charts, overlaps and gaps in texels; UV0 density
            [--lightmapper bakery]                  # the spec's lighting.baker: Bakery's footprint and density gate
    blender -b --factory-startup MASTER.blend --python-exit-code 1 --python qa_measure.py -- --module 1.0 --render top
            --center 15 13 --extent 30 27 --clip 2 --png plan.png --overlay world/diagrams/plan_square.svg
    blender -b --factory-startup MASTER.blend --python-exit-code 1 --python qa_measure.py -- --module 1.0 --render back
            --center 3 1.2 1.5 --extent 4 3 --clip 3 --png inside_south.png   # --clip hides the wall behind you
    blender -b --factory-startup KIT_Arch_Exterior.blend --python-exit-code 1 --python qa_measure.py -- --module 1.0
            --isolate EXT_Door_2x3_A --render front --center 1 0.1 1.5 --extent 2.4 3.4 --px-per-m 200 --clip 0.05
            --wire --png door_section.png     # a section at y 0.05 (centre minus clip): faces sealed inside show (M3)
    blender -b --factory-startup MASTER.blend --python-exit-code 1 --python qa_measure.py -- --module 1.0
            --view 2 1.8 1.7 3 4.4 0.9 24 --png view.png --hide-collection REF --color texture --light flat
    blender -b --factory-startup KIT_Arch_Exterior.blend --python-exit-code 1 --python qa_measure.py -- --module 1.0
            --isolate EXT_Door_2x3_A --view 3 -3 2.5 1 0.15 1.5 35 --png door.png --wire   # one piece, wireframe
    blender -b --factory-startup MASTER.blend --python-exit-code 1 --python qa_measure.py -- --module 1.0
            --view 2 1.8 1.7 3 4.4 0.9 24 --png look.png --hide-collection REF --light lookdev   # materials (X5)
    blender -b --factory-startup --python-exit-code 1 --python qa_measure.py -- --image-stats dark.png --gain 4
    blender -b --factory-startup --python-exit-code 1 --python qa_measure.py -- --tile-seam T_EXT_Brick_BaseColor.png
    blender -b --factory-startup --python-exit-code 1 --python qa_measure.py -- --pbr "blender/textures/EXT/*.png"
            --map-px 1024 --pbr-targets '{"M_EXT_Brick": {"albedo_srgb": [60, 150], "metal": false}}'   # X8
    blender -b --factory-startup --python-exit-code 1 --python qa_measure.py -- --pbr "textures/EXT/*.png"
            --pbr-tiling   # X4: seams along part of an edge, tile-scale variation (--pbr-trim for a trim sheet)

Renders leave out collision shells (*_COL) and every LOD but LOD0 (*_LOD1, *_LOD2...), in the file and inside
collection instances: --lod n shows LOD n instead, --show-collision shows the shells, --hide-object hides more by
name (globs), --isolate shows one collection only (every KIT piece sits at the origin). --light flat and studio are
Workbench (base colour only); --light lookdev is EEVEE with each material's own nodes (roughness, metallic and normal
maps), a grey world, the scene's lights hidden and one key light 45 deg above, behind the camera's left (LOOKDEV).

File role, from the file name or --role: KIT_* kit, ASM_* asm, MASTER* master; --import-fbx makes it fbx. A single
MASTER (scene["kit_layout"] == "single", blender-kit-library's default) holds the pieces under KIT, the assemblies
under ASM (both excluded from the view layer) and the layout under MASTER: its pieces get the kit checks and its
layout the placement checks. A split MASTER or ASM file must hold no local piece collection; a split MASTER no local
assembly; an ASM file exactly the one assembly named after the file. With no .blend open and no --import-fbx (a blank
session), the scene is not measured.

From a live Blender (Blender MCP execute_blender_code), without saving:
    ns = {"__file__": r"<skill>/scripts/qa_measure.py"}     # pbr() finds pbr_check.py beside it through __file__
    exec(open(ns["__file__"], encoding="utf-8").read(), ns)
    rep = ns["measure"](module=1.0)                  # dict, fields below
    ns["problems"](rep, piece_tris={"EXT": 800}, expect_status="modelled")
    ns["pbr"](["T_EXT_Brick_BaseColor.png", "T_EXT_Brick_Normal.png"], map_px=1024)

Report fields. File: file, role, layout (single or null), layout_problems, module, sub_module, lightmapper,
libraries [{path, relative, found}], unnamed_collections,
local_assemblies, local_assembly_offsets {name: [x, y, z]}, images [{image, filepath, relative, packed, missing,
size, channels, colorspace, alpha_mode, materials}], linked_pieces [{piece, library, kit_status, tris,
instance_offset}], placements [{object, asset, kind (grid, free, asm, other), linked, id, pos, rot_z, rot_xy_ok,
mirrored (negative scale, read as the unmirrored placement: a PROBLEM on a tiling piece, else a note), scale_ok,
on_grid, right_angle, tile_phase (with --families: u_px, v_px, turn_deg, tile_m, px_per_m, horizontal; a wall's v_px
against the walls of its family its box touches, with v_abs_px and v_against), assembly (the ASM_ collection holding
it in a single MASTER, else null: compare only
those with null against the zones' placements)}], appended, shadowing_linked, ref_meshes, stray_meshes, problems, notes (advisory:
LOD0 footprints under 64 px, where only a Free PROP or FOL piece is told to become probe-lit; UV2 box fill under 0.5
at a footprint of 64 px or more, unless Bakery's density gate already makes it a PROBLEM),
linked_assembly_offsets {name: [x, y, z]}; optional fbx_folded_materials, placement_changes (matched by placement id
first; an id that vanished or changed is listed), tile_seam, image_stats and renders [{image, size, mean, min, max,
luma_p1, luma_p50, luma_p99, clipped_share, crushed_share, coverage}], pbr (one entry per material from pbr_check.py:
material, maps, base_color, metallic_smoothness, normal, problems, notes; its problems also go into problems, as
"pbr <material>: ...", and its notes into notes).
Per piece (pieces[]): piece, kit_status, instance_offset, transform_issues, lod0_tris, has_collision,
coplanar_overlaps, coplanar_overlap_examples, bad_materials, bounds_m, extent_modules, size_ok and pivot_ok (grid
pieces), free_pivot (Free pieces), objects, a dict keyed by object name: {tris, ngons, edges_over_2_faces,
boundary_edges, loose_verts, loose_edges, islands (connected parts), area_m2, uv_layers, uv {layer: {bounds, area}},
uv2_bbox_share (the UV2 charts' bounding-box share of the 0-1 tile), uv2_short_side (that box's short side in UV),
uv2_box_fill (the charts' area over that box's), uv2_charts, uv2_overlaps (chart pairs), uv2_min_gap_uv,
uv2_edge_margin_uv, lightmap_px (with --lightmap-texels: TPM x sqrt(area_m2 / uv2_bbox_share, or 0.85 before UV2
exists) x Scale In Lightmap x 0.5^n for a *_LOD<n> mesh; with --lightmapper bakery, (TPM x sqrt(2 x area_m2 x Scale
In Lightmap) - 6) / uv2_short_side, sqrt(0.85) before UV2 exists, no LOD factor) and uv2_min_gap_texels,
uv2_edge_margin_texels at it, effective_texels_per_m (lightmap_px x sqrt(UV2 area / area_m2), the texels per metre
the surface gets) and, under Bakery, effective_texels_min (0.5 x TPM x min(1, sqrt(Scale In Lightmap)): under it at
64 px or more is a PROBLEM), uv0_px_per_m, uv0_px_per_m_range and uv0_texel_cv (with
--texel-map), materials}. Pieces are measured as they export: one in an excluded or viewport-disabled collection, or
disabled itself, is enabled while it is measured and restored afterwards.
Deeper checks belong to the specialist skills: UV distortion, padding and texel density (uv-unwrapping), topology
flow and joint matching (blender-mesh-topology), export settings (blender-to-unity).
"""

import contextlib
import fnmatch
import glob
import json
import math
import os
import re
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.geometry import tessellate_polygon

NAME_RE = re.compile(r"^([A-Z]{2,5})_[A-Za-z0-9]+_(\d+(?:x\d+){0,2}|Free)_[A-Z]\d?$")
ASM_RE = re.compile(r"^ASM_[A-Za-z0-9]+_[A-Z]\d?$")
MAT_RE = re.compile(r"^M_[A-Z]{2,5}_[A-Za-z0-9][A-Za-z0-9_]*$")   # catches "Material.001" or "wood"
COPY_RE = re.compile(r"^(.*)\.\d{3}$")                            # Blender's name for a second datablock
COL_RE = re.compile(r"_COL(\.\d{3})?$")
LOD_RE = re.compile(r"_LOD(\d+)(\.\d{3})?$")
EPS = 1e-4
STATUS_ORDER = ("grey", "modelled", "uv", "textured", "exported")   # collection custom property kit_status
LIGHTMAP_COVERAGE = 0.85   # planning estimate of b, the UV2 charts' bounding-box share of the 0-1 tile, before UV2
                           # exists; a measured UV2 uses its own b (Unity 2022.3.22f1, fitted 2026-10-16)
MIN_FOOTPRINT_PX = 64      # house guidance: a Free prop under it is probe-lit; a grid piece raises its scale instead
UV2_BOX_FILL_NOTE = 0.5    # a NOTE when UV2 charts fill less of their bounding box than this, at a footprint of
                           # MIN_FOOTPRINT_PX or more (U6; uv-unwrapping's audit)
PROBE_LIT_FAMILIES = ("PROP", "FOL")   # a Free prop is a Free-sized piece of these families; ZONE shells and every
                                       # other family follow the grid-piece rule (lightmapped, a note under 64 px)
UV2_LAYOUT_ALL_LODS = True    # the UV2 layout checks (0-1, overlaps, gaps) cover LOD1+ too, each at its own footprint
LOD_LIGHTMAP_SCALE = 0.5      # the Progressive Lightmapper gives LODn its own atlas space at 0.5^n of LOD0's texel
                              # scale (Unity's GetLightmapLODLevelScale; measured 0.995, 0.492, 0.250 for LOD0-2,
                              # independent of the LOD transition heights, Unity 2022.3.22f1, 2026-10-17)
LIGHTMAPPERS = ("unity", "bakery")   # whose footprint --lightmap-texels uses; "progressive" is accepted for unity
BAKERY_AREA_FACTOR = 2.0      # Bakery sizes a renderer by the sum of |cross| over its triangles, 2 x its area, and
BAKERY_INSET_TEXELS = 3       # its Default atlas packer insets each rect 3 texels (ftBuildGraphics.cs as installed
                              # in a Unity 2022.3.22f1 project, read 2026-10-24; not measured in a bake)
EFFECTIVE_DENSITY_MIN = 0.5   # Bakery: a PROBLEM when a mesh of MIN_FOOTPRINT_PX or more gets under this share of the
                              # texels per metre planned for it (U4; uv-unwrapping's audit applies the same gate)
TRIM_FAMILY = "TRIM"       # placed on grid.sub_module (--sub-module), as the pipeline's spec validator checks it
GRID_TOL_M = 1e-4          # a grid placement within this many metres of the grid is on it (0.1 mm, any module)
TILE_PHASE_TEXELS = 0.5    # a tiling placement further than this off its family's tile grid shows a jump at joints
FREE_SCALE_BAND = (0.8, 1.25)   # an evenly scaled Free prop or assembly keeps its texel density within the unique
                                # band; scale 2 halves its texels per metre against the kit's
FLOOR_FAMILY = "STR"       # a two-number Size in this family is a floor tile (X by Y), as the spec validator reads it
                           # (also any family the spec marks floor: true, read through --families)
CONTACT_TOL_M = 1e-3       # two placements' boxes this close touch: a joint where a tiling pattern must continue
PHASE_VARIANT_RE = re.compile(r"_P(\d)$")
ROLES = ("kit", "asm", "master", "fbx")


def _identity(mw):
    return all(abs(mw[i][j] - (1.0 if i == j else 0.0)) < EPS for i in range(4) for j in range(4))


def _vec(v):
    return [round(float(x), 4) for x in v]


def _nonzero(v):
    return any(abs(x) > EPS for x in v)


def _is_ref(coll):
    return coll.name == "REF" or coll.name.startswith("REF_")


def _in_ref(ob):
    return any(_is_ref(c) for c in ob.users_collection)


def lightmapper_name(name):
    """unity (also "progressive", the world spec's lighting.baker for it) or bakery; raises ValueError otherwise."""
    n = str(name or "unity").strip().lower()
    n = "unity" if n == "progressive" else n
    if n not in LIGHTMAPPERS:
        raise ValueError("lightmapper must be unity (or progressive) or bakery, not %r" % (name,))
    return n


def lightmap_footprint(area_m2, texels_per_m, scale=1.0, lod=0, share=None, short_side=None, lightmapper="unity"):
    """A mesh's lightmap footprint in texels per UV unit (the side its whole 0-1 tile would have). share: its UV2
    charts' bounding-box share b of the tile, short_side: that box's short side in UV (None before UV2 exists: b =
    LIGHTMAP_COVERAGE, a square box). Unity: texels_per_m x sqrt(A / b) x Scale In Lightmap x 0.5^lod. Bakery: a rect
    of side L = texels_per_m x sqrt(2 x A x Scale In Lightmap) on the box's short side, its Default packer's 3-texel
    inset taken off, (L - 6) / short_side, and no LOD factor (each LOD is sized by its own area)."""
    if lightmapper_name(lightmapper) == "bakery":
        side = texels_per_m * math.sqrt(BAKERY_AREA_FACTOR * max(area_m2, 0.0) * max(scale, 0.0))
        short = short_side or math.sqrt(LIGHTMAP_COVERAGE)
        return max(side - 2.0 * BAKERY_INSET_TEXELS, 0.0) / short
    return (texels_per_m * math.sqrt(max(area_m2, 0.0) / (share or LIGHTMAP_COVERAGE)) * scale
            * LOD_LIGHTMAP_SCALE ** lod)


def _density_low(st):
    """Bakery's effective-density gate (U4): a mesh with a footprint of MIN_FOOTPRINT_PX or more whose UV2 charts get
    under effective_texels_min texels per metre."""
    eff, low = st.get("effective_texels_per_m"), st.get("effective_texels_min")
    return eff is not None and low is not None and (st.get("lightmap_px") or 0) >= MIN_FOOTPRINT_PX and eff < low


def _is_lod0_name(name):
    m = LOD_RE.search(name)
    return m is None or int(m.group(1)) == 0


def _is_lod0(ob):
    return _is_lod0_name(ob.name)


def _single_layout(scene, local, local_pieces):
    """A single MASTER: where its pieces and assemblies sit. Returns (assembly of each object, problems)."""
    roots = {n: next((c for c in local if c.name == n), None) for n in ("KIT", "ASM", "MASTER")}
    out = ["no %s collection in a single MASTER" % n for n, c in roots.items() if c is None]
    under = {n: set(c.children_recursive) if c else set() for n, c in roots.items()}
    out += ["%s: piece outside KIT in a single MASTER" % c.name for c in local_pieces if c not in under["KIT"]]
    out += ["%s: assembly outside ASM in a single MASTER" % c.name for c in local
            if ASM_RE.match(c.name) and c not in under["ASM"]]
    for n in ("KIT", "ASM"):
        if roots[n] is None:
            continue
        for path in _layer_paths(bpy.context.view_layer.layer_collection, roots[n]):
            if not any(lc.exclude for lc in path[1:]):
                out.append("%s is in the view layer: its pieces show at the origin of the layout (exclude it)" % n)
                break
    owner = {}
    for c in local:
        if ASM_RE.match(c.name):
            for ob in c.all_objects:
                owner.setdefault(ob.name, c.name)
    return owner, out


def file_role(path):
    """kit, asm or master from a .blend file name (KIT_*, ASM_*, MASTER*); None for anything else."""
    base = os.path.basename(path or "")
    if base.startswith("KIT_"):
        return "kit"
    if base.startswith("ASM_"):
        return "asm"
    if base.upper().startswith("MASTER"):
        return "master"
    return None


def _uv_data(me, world_areas, texel_map=None):
    """Per UV layer of an evaluated mesh: bounds [umin, vmin, umax, vmax] and total UV area. With texel_map (the
    texture's size in px), UV0's texel density in px/m overall and its 5th-95th percentile over faces, leaving out
    faces marked uv_low_density (or uv_low_density_<layer>), as uv-unwrapping's audit does."""
    import numpy as np
    out, extra = {}, {}
    n, nf = len(me.loops), len(me.polygons)
    if not n or not nf:
        return out, extra
    starts = np.empty(nf, np.int32)
    totals = np.empty(nf, np.int32)
    me.polygons.foreach_get("loop_start", starts)
    me.polygons.foreach_get("loop_total", totals)
    nxt = np.arange(1, n + 1)
    nxt[starts + totals - 1] = starts                  # each polygon's last corner wraps to its first
    for i, layer in enumerate(me.uv_layers):
        uv = np.empty(n * 2, np.float32)
        layer.uv.foreach_get("vector", uv)
        uv = uv.reshape(-1, 2).astype(np.float64)
        cross = uv[:, 0] * uv[nxt, 1] - uv[nxt, 0] * uv[:, 1]
        face_uv = np.abs(np.add.reduceat(cross, starts)) / 2.0
        out[layer.name] = {"bounds": _vec((*uv.min(0), *uv.max(0))), "area": round(float(face_uv.sum()), 6)}
        if i == 0 and texel_map:
            keep = (np.asarray(world_areas) > 1e-6) & ~_low_mask(me, layer.name)
            wa = np.asarray(world_areas)[keep]
            if wa.size:
                per_face = texel_map * np.sqrt(face_uv[keep] / wa)
                extra["uv0_px_per_m"] = round(float(texel_map * math.sqrt(face_uv[keep].sum() / wa.sum())), 1)
                extra["uv0_px_per_m_range"] = [round(float(np.percentile(per_face, q)), 1) for q in (5, 95)]
    return out, extra


def _union_find(n):
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        parent[find(a)] = find(b)
    return find, union


def _mesh_islands(bm):
    """Connected pieces of geometry (faces joined through shared edges)."""
    find, union = _union_find(len(bm.faces))
    for e in bm.edges:
        fs = e.link_faces
        for f in fs[1:]:
            union(fs[0].index, f.index)
    return len({find(f.index) for f in bm.faces})


def _same_uv_edge(e, uvl, eps=1e-6):
    """Do the two faces of a manifold edge give it the same UVs (no seam)?"""
    l1, l2 = e.link_loops[0], e.link_loops[1]
    a1, b1 = l1[uvl].uv, l1.link_loop_next[uvl].uv
    a2, b2 = l2[uvl].uv, l2.link_loop_next[uvl].uv
    if l1.vert == l2.vert:                             # the two faces run the edge the same way (flipped normals)
        return (a1 - a2).length < eps and (b1 - b2).length < eps
    return (a1 - b2).length < eps and (b1 - a2).length < eps


def _uv_signs(bm, uvl):
    """Each face's UV winding in its loop order: 1, -1, or 0 for a face with no UV area."""
    out = []
    for f in bm.faces:
        pts = [l[uvl].uv for l in f.loops]
        a = sum(pts[i - 1].x * pts[i].y - pts[i].x * pts[i - 1].y for i in range(len(pts)))
        out.append(0 if abs(a) < 1e-12 else (1 if a > 0 else -1))
    return out


def _folds(e, sign):
    """Do the two faces of a manifold edge lie on the same side of it in UV (a fold)? Faces that run the edge in
    opposite directions (their normals agree) fold when their UV windings differ; faces that run it the same way (one
    of them flipped) fold when the windings agree. A face with no UV area never counts."""
    l1, l2 = e.link_loops[0], e.link_loops[1]
    s1, s2 = sign[l1.face.index], sign[l2.face.index]
    if not s1 or not s2:
        return False
    return s1 == s2 if l1.vert == l2.vert else s1 != s2


def _uv_charts(bm, uvl):
    """Chart (UV island) id of each face: faces joined through edges whose UVs agree on both sides, except where the
    two faces fold over that edge in UV. A fold, or the two halves of a Mirror modifier at its defaults (merged on
    the axis with the same UVs, stacked on each other), becomes separate charts, so the pair test counts the overlap;
    uv-unwrapping's audit splits mirrored stacks the same way."""
    sign = _uv_signs(bm, uvl)
    find, union = _union_find(len(bm.faces))
    for e in bm.edges:
        if len(e.link_faces) == 2 and _same_uv_edge(e, uvl) and not _folds(e, sign):
            union(e.link_faces[0].index, e.link_faces[1].index)
    return [find(f.index) for f in bm.faces]


def _low_mask(me, layer_name):
    """Faces marked uv_low_density (or uv_low_density_<layer>): lowered on purpose, left out of density figures."""
    import numpy as np
    nf = len(me.polygons)
    low = np.zeros(nf, bool)
    for attr in ("uv_low_density", "uv_low_density_" + layer_name):
        a = me.attributes.get(attr)
        if a is not None and a.domain == "FACE" and a.data_type == "BOOLEAN" and len(a.data) == nf:
            m = np.zeros(nf, bool)
            a.data.foreach_get("value", m)
            low |= m
    return low


def _texel_cv(bm, uvl, areas, low, texel_map):
    """Texel-density spread between UV0 islands, as uv-unwrapping's audit defines texel_cv: each island's px/m
    against the mean, weighted by the island's surface area, divided by the mean."""
    charts = _uv_charts(bm, uvl)
    uv_area, world = {}, {}
    for f in bm.faces:
        if low[f.index] or areas[f.index] <= 1e-9:
            continue
        pts = [l[uvl].uv for l in f.loops]
        a = abs(sum(pts[i].x * pts[(i + 1) % len(pts)].y - pts[(i + 1) % len(pts)].x * pts[i].y
                    for i in range(len(pts)))) / 2.0
        c = charts[f.index]
        uv_area[c] = uv_area.get(c, 0.0) + a
        world[c] = world.get(c, 0.0) + areas[f.index]
    total_w = sum(world.values())
    if total_w <= 0:
        return None
    mean = texel_map * math.sqrt(sum(uv_area.values()) / total_w)
    if mean <= 0:
        return None
    var = sum(w * (texel_map * math.sqrt(uv_area[c] / w) - mean) ** 2 for c, w in world.items()) / total_w
    return round(math.sqrt(var) / mean, 3)


def _seg_distances(pts, segs):
    """Distance from each 2D point to each segment: (len(pts), len(segs))."""
    import numpy as np
    a, b = segs[:, 0][None], segs[:, 1][None]
    p = pts[:, None]
    ab = b - a
    t = np.clip(((p - a) * ab).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-30), 0.0, 1.0)
    return np.linalg.norm(p - (a + t[..., None] * ab), axis=-1)


def _min_distance(sa, sb, cells=250000):
    """Smallest distance between two sets of 2D segments ((n, 2, 2) arrays): every endpoint of each set against the
    other set's segments, exact for outlines that do not cross. Chunked so long outlines stay within memory."""
    best = math.inf
    for pts, segs in ((sa.reshape(-1, 2), sb), (sb.reshape(-1, 2), sa)):
        step = max(1, cells // max(1, len(segs)))
        for k in range(0, len(pts), step):
            best = min(best, float(_seg_distances(pts[k:k + step], segs).min()))
    return best


def _chart_triangles(polys):
    """A chart's faces as triangles, with each triangle's box as an (n, 4) array [umin, vmin, umax, vmax]."""
    import numpy as np
    tris = [t for poly in polys for t in _triangles(poly)]
    arr = np.array(tris, float).reshape(-1, 3, 2)
    return tris, np.concatenate([arr.min(1), arr.max(1)], 1)


def _charts_overlap(a, b, cells=1000000):
    """Does a triangle of chart a overlap a triangle of chart b with area? a, b: _chart_triangles results. Only
    triangle pairs whose boxes overlap are tested."""
    import numpy as np
    (ta, ba), (tb, bb) = a, b
    if not len(ta) or not len(tb):
        return False
    step = max(1, cells // len(tb))
    for k in range(0, len(ta), step):
        bk = ba[k:k + step]
        hit = ((bk[:, None, 0] < bb[None, :, 2]) & (bb[None, :, 0] < bk[:, None, 2])
               & (bk[:, None, 1] < bb[None, :, 3]) & (bb[None, :, 1] < bk[:, None, 3]))
        for i, j in zip(*np.nonzero(hit)):
            if _tri_overlap(ta[k + int(i)], tb[int(j)]):
                return True
    return False


def _uv2_layout(bm, uvl):
    """The lightmap layer's charts: how many, how many pairs overlap, the smallest gap between two charts and the
    smallest distance to the tile edge, in UV units (exact edge-to-edge distances between chart outlines). Sort and
    sweep by box: a pair whose boxes are farther apart than the smallest gap so far is never measured."""
    import numpy as np
    charts = _uv_charts(bm, uvl)
    ids = sorted(set(charts))
    polys, segs = {c: [] for c in ids}, {c: [] for c in ids}
    for f in bm.faces:
        pts = [tuple(l[uvl].uv) for l in f.loops]
        polys[charts[f.index]].append(pts)
        for l in f.loops:
            e = l.edge
            if len(e.link_faces) == 2 and charts[e.link_faces[0].index] == charts[e.link_faces[1].index] \
                    and _same_uv_edge(e, uvl):
                continue                               # inside the chart
            segs[charts[f.index]].append((tuple(l[uvl].uv), tuple(l.link_loop_next[uvl].uv)))
    all_uv = np.array([p for c in ids for poly in polys[c] for p in poly], float).reshape(-1, 2)
    out = {"uv2_charts": len(ids), "uv2_overlaps": 0, "uv2_min_gap_uv": None,
           "uv2_edge_margin_uv": round(float(min(all_uv.min(), (1.0 - all_uv).min())), 5) if len(all_uv) else None}
    boxes = []
    for c in ids:
        p = np.array([q for poly in polys[c] for q in poly], float).reshape(-1, 2)
        boxes.append((float(p[:, 0].min()), float(p[:, 1].min()), float(p[:, 0].max()), float(p[:, 1].max()), c))
    boxes.sort()                                       # by umin
    seg_arr = {c: np.array(segs[c], float).reshape(-1, 2, 2) for c in ids}
    tris = {}
    gap = math.inf
    for i, (ax0, ay0, ax1, ay1, ca) in enumerate(boxes):
        for bx0, by0, bx1, by1, cb in boxes[i + 1:]:
            if bx0 - ax1 >= gap:
                break                                  # every later chart starts at least this far to the right
            if bx0 < ax1 and ax0 < bx1 and by0 < ay1 and ay0 < by1:      # the boxes overlap: test the triangles
                for c in (ca, cb):
                    if c not in tris:
                        tris[c] = _chart_triangles(polys[c])
                if _charts_overlap(tris[ca], tris[cb]):
                    out["uv2_overlaps"] += 1
                    gap = 0.0
                    continue
            box_gap = math.hypot(max(0.0, bx0 - ax1, ax0 - bx1), max(0.0, by0 - ay1, ay0 - by1))
            if box_gap < gap and len(seg_arr[ca]) and len(seg_arr[cb]):
                gap = min(gap, _min_distance(seg_arr[ca], seg_arr[cb]))   # never below the boxes' own gap
    out["uv2_min_gap_uv"] = round(gap, 5) if gap != math.inf else None
    return out


def _mesh_data(ob, depsgraph, want_faces=False, texel_map=None):
    """Counts for one mesh object on its evaluated mesh (modifiers applied, as it exports), in world space. With
    want_faces, also its faces as (label, normal, [corner positions]) for the coplanar-overlap test."""
    ev = ob.evaluated_get(depsgraph)
    me = ev.to_mesh()
    faces = []
    try:
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.transform(ob.matrix_world)
        bm.normal_update()
        bm.faces.index_update()
        areas = [f.calc_area() for f in bm.faces]
        st = {
            "tris": sum(len(f.verts) - 2 for f in bm.faces),
            "ngons": sum(1 for f in bm.faces if len(f.verts) > 4),
            "edges_over_2_faces": sum(1 for e in bm.edges if len(e.link_faces) > 2),
            "boundary_edges": sum(1 for e in bm.edges if len(e.link_faces) == 1),
            "loose_verts": sum(1 for v in bm.verts if not v.link_edges),
            "loose_edges": sum(1 for e in bm.edges if not e.link_faces),
            "area_m2": round(sum(areas), 4),
        }
        if want_faces:
            faces = [("%s:%d" % (ob.name, f.index), f.normal.copy(), [v.co.copy() for v in f.verts])
                     for f in bm.faces]
        st["islands"] = _mesh_islands(bm)
        st["uv_layers"] = len(me.uv_layers)            # on the evaluated mesh, as it exports: a modifier can drop them
        st["uv"], extra = _uv_data(me, areas, texel_map)
        st.update(extra)
        uvs = bm.loops.layers.uv
        if texel_map and len(uvs) >= 1:
            st["uv0_texel_cv"] = _texel_cv(bm, uvs[0], areas, _low_mask(me, me.uv_layers[0].name), texel_map)
        if len(uvs) >= 2:
            st.update(_uv2_layout(bm, uvs[1]))
        bm.free()
    finally:
        ev.to_mesh_clear()
    st["materials"] = [s.material.name if s.material else None for s in ob.material_slots]
    return st, faces


# ---- coplanar overlapping faces: duplicates, z-fighting faces, zero-thickness doubles ------------------------------

def _triangles(poly):
    """A 2D polygon as triangles, concave ones included (Blender's tessellator); zero-area triangles left out."""
    if len(poly) == 3:
        tris = [tuple(poly)]
    else:
        tris = [(poly[a], poly[b], poly[c])
                for a, b, c in tessellate_polygon([[Vector((x, y, 0.0)) for x, y in poly]])]
    return [tr for tr in tris if abs((tr[1][0] - tr[0][0]) * (tr[2][1] - tr[0][1])
                                     - (tr[1][1] - tr[0][1]) * (tr[2][0] - tr[0][0])) > 1e-14]


def _tri_overlap(t1, t2, eps=1e-7):
    """Separating-axis test: do two triangles overlap by more than eps along every edge normal? Triangles that only
    share an edge, touch at a corner or lie along one line do not."""
    for tri in (t1, t2):
        for i in range(3):
            (x1, y1), (x2, y2) = tri[i], tri[(i + 1) % 3]
            nx, ny = y1 - y2, x2 - x1
            length = math.hypot(nx, ny)
            if length == 0.0:
                continue
            p1 = [(nx * x + ny * y) / length for x, y in t1]
            p2 = [(nx * x + ny * y) / length for x, y in t2]
            if min(max(p1), max(p2)) - max(min(p1), min(p2)) <= eps:
                return False
    return True


def _overlap2d(p, q):
    """Do two coplanar polygons overlap with area? Sharing only an edge or a corner does not count; partial overlaps
    along shared lines do."""
    tq = _triangles(q)
    return any(_tri_overlap(a, b) for a in _triangles(p) for b in tq)


def coplanar_overlaps(faces):
    """Pairs of faces (labels) that lie in one plane (to 0.1 mm) and overlap with area, facing the same way or
    opposite ways: duplicated faces, z-fighting faces, zero-thickness doubles. faces: (label, normal, [Vector])."""
    buckets = {}
    for label, n, pts in faces:
        if n.length < 0.5 or len(pts) < 3:
            continue                                   # degenerate face
        k = max(range(3), key=lambda i: abs(n[i]))
        nn = n if n[k] > 0 else -n
        key = (round(nn.x, 3), round(nn.y, 3), round(nn.z, 3), round(nn.dot(pts[0]), 4))
        a, b = [i for i in range(3) if i != k]
        p2 = [(p[a], p[b]) for p in pts]
        xs, ys = [p[0] for p in p2], [p[1] for p in p2]
        buckets.setdefault(key, []).append((label, p2, (min(xs), min(ys), max(xs), max(ys))))
    pairs = []
    for group in buckets.values():
        group.sort(key=lambda t: t[2][0])
        for i, (li, pi, bi) in enumerate(group):
            for lj, pj, bj in group[i + 1:]:
                if bj[0] >= bi[2] - 1e-6:
                    break                              # sorted by min x: nothing later overlaps face i in x
                if bj[1] >= bi[3] - 1e-6 or bj[3] <= bi[1] + 1e-6:
                    continue
                if _overlap2d(pi, pj):
                    pairs.append((li, lj))
    return pairs


# ---- pieces -------------------------------------------------------------------------------------------------------

def _bounds(objs):
    lo, hi = Vector((math.inf,) * 3), Vector((-math.inf,) * 3)
    for ob in objs:
        for c in ob.bound_box:
            p = ob.matrix_world @ Vector(c)
            lo, hi = Vector(map(min, lo, p)), Vector(map(max, hi, p))
    return lo, hi


def free_pivot(lo, hi, tol=0.01):
    """Which Free-piece pivot the bounds show: floor_centre (props), top_centre (ceiling-mounted), back_face_centre
    (wall-mounted: back face at y 0, front towards -Y), or None (another pivot, such as a door hinge: read the desc)."""
    def centred(i):
        return abs(lo[i] + hi[i]) <= tol
    if centred(0) and centred(1) and abs(lo[2]) <= tol:
        return "floor_centre"
    if centred(0) and centred(1) and abs(hi[2]) <= tol:
        return "top_centre"
    if centred(0) and centred(2) and abs(hi[1]) <= tol:
        return "back_face_centre"
    return None


def _floor_like(code, nums, families=None):
    """True when a two-number Size is a floor tile laid flat (X by Y): family STR, or one the spec marks floor: true
    (a plank floor, terrain chunks)."""
    fam = (families or {}).get(code)
    return nums == 2 and (code == FLOOR_FAMILY or (isinstance(fam, dict) and fam.get("floor") is True))


def measure_piece(coll, module, depsgraph, lightmap_texels=None, lightmap_scale=1.0, texel_map=None,
                  lightmapper="unity", families=None):
    """lightmap_scale: Scale In Lightmap, one number or {piece: scale} (the spec's pieces[].lightmap_scale; others 1).
    lightmapper: whose footprint lightmap_px is, unity or bakery (lightmap_footprint). families: the spec's, for which
    two-number Sizes are floors (floor: true): their Size is X by Y, and Z is thickness or relief (a terrain chunk's
    pivot sits at its datum, with ground above and below it)."""
    lightmapper = lightmapper_name(lightmapper)
    m = NAME_RE.match(coll.name)
    if isinstance(lightmap_scale, dict):
        lightmap_scale = float(lightmap_scale.get(coll.name, 1.0))
    objs = list(coll.all_objects)
    render = [o for o in objs if o.type == "MESH" and not COL_RE.search(o.name)]
    lod0 = [o for o in render if _is_lod0(o)]
    rep = {"piece": coll.name, "kit_status": coll.get("kit_status"), "instance_offset": _vec(coll.instance_offset),
           "objects": {}, "transform_issues": [], "has_collision": any(COL_RE.search(o.name) for o in objs)}
    faces = []
    for ob in objs:
        if not _identity(ob.matrix_world):
            rep["transform_issues"].append(ob.name)
        if ob.type == "MESH":
            st, f = _mesh_data(ob, depsgraph, want_faces=any(ob is o for o in lod0), texel_map=texel_map)
            layers = list(st["uv"].values())
            if len(layers) >= 2:                       # UV2: its charts' bounding-box share of the 0-1 tile
                u0, v0, u1, v1 = layers[1]["bounds"]
                wu, wv = max(0.0, min(1.0, u1) - max(0.0, u0)), max(0.0, min(1.0, v1) - max(0.0, v0))
                st["uv2_bbox_share"] = round(wu * wv, 4)
                st["uv2_short_side"] = round(min(wu, wv), 4)     # Bakery maps it onto its rect's side
                if st["uv2_bbox_share"] > 0:                 # the charts' area over their box's (uv-unwrapping's)
                    st["uv2_box_fill"] = round(min(1.0, layers[1]["area"] / st["uv2_bbox_share"]), 4)
            if lightmap_texels and not COL_RE.search(ob.name) and st["area_m2"] > 0:   # faces only: no wire helpers
                lod = LOD_RE.search(ob.name)
                px = lightmap_footprint(st["area_m2"], lightmap_texels, lightmap_scale, int(lod.group(1)) if lod else 0,
                                        st.get("uv2_bbox_share"), st.get("uv2_short_side"), lightmapper)
                st["lightmap_px"] = round(px, 1)
                for k in ("min_gap", "edge_margin"):                     # UV2 distances in texels at the footprint
                    if st.get("uv2_%s_uv" % k) is not None:
                        st["uv2_%s_texels" % k] = round(st["uv2_%s_uv" % k] * st["lightmap_px"], 2)
                if len(layers) >= 2:      # the texels per metre the surface gets: footprint x sqrt(UV2 area / area)
                    st["effective_texels_per_m"] = round(px * math.sqrt(layers[1]["area"] / st["area_m2"]), 2)
                    if lightmapper == "bakery":       # half the density planned: its linear scale sqrt(S), at most 1
                        st["effective_texels_min"] = round(EFFECTIVE_DENSITY_MIN * lightmap_texels
                                                           * min(1.0, math.sqrt(lightmap_scale)), 2)
            rep["objects"][ob.name] = st
            faces += f
    rep["lod0_tris"] = sum(rep["objects"][o.name]["tris"] for o in lod0)
    pairs = coplanar_overlaps(faces)
    rep["coplanar_overlaps"] = len(pairs)
    rep["coplanar_overlap_examples"] = ["%s / %s" % p for p in pairs[:5]]
    rep["bad_materials"] = sorted({n for st in rep["objects"].values() for n in st["materials"]
                                   if n and not MAT_RE.match(n)})
    if render:
        lo, hi = _bounds(render)
        rep["bounds_m"] = [round(v, 4) for v in (*lo, *hi)]
        ext = [(hi[i] - lo[i]) / module for i in range(3)]
        rep["extent_modules"] = [round(e, 3) for e in ext]
        if m and m.group(2) != "Free":
            want = [int(t) for t in m.group(2).split("x")]
            if _floor_like(m.group(1), len(want), families):
                grid = ext[:2]                              # X by Y; Z is a slab's thickness or a terrain's relief
                rep["pivot_ok"] = all(abs(v) <= 0.01 for v in lo[:2]) and (ext[2] >= 1.0 - 0.01 or abs(lo[2]) <= 0.01)
            else:
                grid = [e for e in ext if e >= 1.0 - 0.01]     # an axis under one module is thickness: not in Size
                rep["pivot_ok"] = all(abs(v) <= 0.01 for v in lo)
            rep["size_ok"] = [round(e) for e in grid] == want and all(abs(e - round(e)) <= 0.01 for e in grid)
        else:
            rep["free_pivot"] = free_pivot(lo, hi)
    return rep


def _clear_factory_scene():
    """In an unsaved session (factory startup), drop the default cube, camera and light so they do not read as
    stray meshes or an unnamed collection. Nothing is saved, so nothing is lost."""
    if bpy.data.filepath:
        return
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for c in list(bpy.data.collections):
        if c.library is None and not c.objects and not c.children:
            bpy.data.collections.remove(c)


def import_fbx(paths):
    """Import FBX files the way E2-E4 need: bake_space_transform=True (without it Blender puts the Y-up conversion on
    the object as a 90 deg X rotation even for a correct file). Each file's objects go into a collection named after
    the file (the piece name), so measure() treats them as pieces. A material the importer copies because an earlier
    file brought one of the same name (<name>.001) is folded back onto <name>: kit pieces share their family's
    materials, and the copy is the importer's doing, not the file's. Returns (collection names, [(copy, base)])."""
    _clear_factory_scene()
    names, folded = [], []
    for path in paths:
        before = set(bpy.data.objects)
        had = {m.name for m in bpy.data.materials}
        bpy.ops.import_scene.fbx(filepath=os.path.abspath(path), bake_space_transform=True)
        coll = bpy.data.collections.new(os.path.splitext(os.path.basename(path))[0])
        bpy.context.scene.collection.children.link(coll)
        copies = set()
        for ob in set(bpy.data.objects) - before:
            for c in list(ob.users_collection):
                c.objects.unlink(ob)
            coll.objects.link(ob)
            for slot in ob.material_slots:
                mat = slot.material
                m = COPY_RE.match(mat.name) if mat is not None else None
                if m and m.group(1) in had and mat.name not in had:
                    slot.material = bpy.data.materials[m.group(1)]
                    copies.add(mat.name)
        for name in sorted(copies):
            mat = bpy.data.materials.get(name)
            folded.append((name, COPY_RE.match(name).group(1)))
            if mat is not None and mat.users == 0:
                bpy.data.materials.remove(mat)
        names.append(coll.name)
    return names, folded


def _evaluated_tris(coll, depsgraph):
    """LOD0 triangles of a collection's render meshes, evaluated like measure_piece (base mesh if not evaluated)."""
    total = 0
    for o in coll.all_objects:
        if o.type != "MESH" or COL_RE.search(o.name) or not _is_lod0(o):
            continue
        ev = o.evaluated_get(depsgraph)
        me = ev.to_mesh()
        try:
            total += sum(len(p.vertices) - 2 for p in me.polygons)
        finally:
            ev.to_mesh_clear()
    return total


def _library_entry(lib):
    parent = getattr(lib, "parent", None)
    try:
        path = bpy.path.abspath(lib.filepath, library=parent) if parent else bpy.path.abspath(lib.filepath)
    except TypeError:
        path = bpy.path.abspath(lib.filepath)
    return {"path": lib.filepath, "relative": lib.filepath.startswith("//"), "found": os.path.exists(path)}


def _layer_paths(lc, coll, path=()):
    path = path + (lc,)
    if lc.collection == coll:
        yield path
    for child in lc.children:
        yield from _layer_paths(child, coll, path)


@contextlib.contextmanager
def _evaluated(colls):
    """Make every object in colls evaluated by the view layer while it is measured, then restore everything (nothing
    is saved). Measured on Blender 5.2.2: objects or collections disabled in viewports, excluded collections and
    collections outside the scene are not evaluated, so they would be measured without their modifiers; blender-to-
    unity's exporter enables them the same way, so this measures what ships. Hidden with H, or in a collection hidden
    with the eye, is evaluated anyway."""
    scene, vl = bpy.context.scene, bpy.context.view_layer
    undo = []
    try:
        for coll in colls:
            if coll not in scene.collection.children_recursive:
                scene.collection.children.link(coll)
                undo.append(lambda c=coll: scene.collection.children.unlink(c))
            for path in list(_layer_paths(vl.layer_collection, coll)):
                lcs, stack = list(path[1:]), [path[-1]]
                while stack:
                    lc = stack.pop()
                    lcs.append(lc)
                    stack.extend(lc.children)
                for lc in lcs:
                    if lc.exclude:
                        lc.exclude = False
                        undo.append(lambda lc=lc: setattr(lc, "exclude", True))
                    if lc.collection.hide_viewport:
                        lc.collection.hide_viewport = False
                        undo.append(lambda c=lc.collection: setattr(c, "hide_viewport", True))
            for ob in coll.all_objects:
                if ob.hide_viewport:
                    ob.hide_viewport = False
                    undo.append(lambda ob=ob: setattr(ob, "hide_viewport", True))
        vl.update()
        yield
    finally:
        for fn in reversed(undo):
            fn()
        vl.update()


def placement_overlaps(depsgraph, scene=None):
    """Faces of two different placements that lie in one plane, overlap with area and face the same way: z-fighting
    between placed pieces (an engaged capital flush with the wall it stands against), which no per-piece check sees.
    End caps pressed together at a joint face opposite ways, are hidden, and are not counted; so are faces pressed
    against a third placement's face (an engaged column's foot and the wall's both on the floor slab) and faces down
    at the lowest level of the layout (both on the ground). LOD0 render meshes of every collection instance in the
    scene, in world space. Returns [[placement, placement, face pairs]]."""
    scene = scene or bpy.context.scene
    faces, normals = [], {}
    for inst in depsgraph.object_instances:
        ob, top = inst.object, inst.parent
        if not inst.is_instance or top is None or ob.type != "MESH" or COL_RE.search(ob.name) or not _is_lod0(ob):
            continue
        me, mw = ob.data, inst.matrix_world.copy()
        nm = mw.to_3x3().inverted().transposed()
        for p in me.polygons:
            label = (top.name, len(faces))
            n = (nm @ p.normal).normalized()
            normals[label] = n
            faces.append((label, n, [mw @ me.vertices[v].co for v in p.vertices]))
    pairs = coplanar_overlaps(faces)
    pressed = {}                                   # face: placements whose opposite-facing face lies on it
    for a, b in pairs:
        if a[0] != b[0] and normals[a].dot(normals[b]) < 0:
            pressed.setdefault(a, set()).add(b[0])
            pressed.setdefault(b, set()).add(a[0])
    ground = min((min(p.z for p in pts) for _l, _n, pts in faces), default=0.0)
    lowest = {f[0]: min(p.z for p in f[2]) for f in faces}
    counts = {}
    for a, b in pairs:
        if a[0] == b[0] or normals[a].dot(normals[b]) <= 0:
            continue
        if (pressed.get(a, set()) | pressed.get(b, set())) - {a[0], b[0]}:
            continue                               # both against a third placement's face: hidden
        if normals[a].z < -0.99 and abs(lowest[a] - ground) < GRID_TOL_M and abs(lowest[b] - ground) < GRID_TOL_M:
            continue                               # feet on the ground
        key = tuple(sorted((a[0], b[0])))
        counts[key] = counts.get(key, 0) + 1
    return [[a, b, n] for (a, b), n in sorted(counts.items())]


def tile_phase(pos, rot_z, tile_m, px_per_m, module=1.0, k=0, horizontal=False, turn_symmetry=360.0):
    """How far one placement of a tiling family's piece sits off the world tile grid, in texels (tile_project puts
    phase 0 at each piece's pivot). A wall: along its own +X, (s - k x module) mod tile with s the pivot's distance
    along that axis (k: its phase variant, 0 for a plain piece), and up, z mod tile (measure() then judges up only
    against the walls it touches). A floor or ceiling (horizontal): its pattern's origin, the pivot less its variant's
    offset (k = kx + n x ky, n the tile in modules, along its own +X and +Y), x and y mod tile, and its turn about Z
    (its pattern turns with it) modulo the texture's own turn symmetry. {"u_px", "v_px", "turn_deg"}."""
    off = lambda v: round(min(v % tile_m, tile_m - v % tile_m) * px_per_m, 2)
    a = math.radians(rot_z)
    c, s_ = math.cos(a), math.sin(a)
    if horizontal:
        n = max(1, int(round(tile_m / module)))
        kx, ky = (k % n) * module, (k // n) * module
        r = rot_z % turn_symmetry
        return {"u_px": off(pos[0] - kx * c + ky * s_), "v_px": off(pos[1] - kx * s_ - ky * c),
                "turn_deg": round(min(r, turn_symmetry - r), 3)}
    s = c * pos[0] + s_ * pos[1]
    return {"u_px": off(s - k * module), "v_px": off(pos[2]), "turn_deg": 0.0}


def _tiling(families, name, module, extents=None):
    """(tile m, px per m, variant k, horizontal, turn symmetry) for a grid piece of a tiling family whose tile_phase
    is grid or variants (families: the spec's), else None. horizontal: measured extents thin in Z and a module or more
    in X and Y (a kerb or a step's nosing runs along X like a wall), or else a floor-like two-number Size."""
    m = NAME_RE.match(name)
    fam = (families or {}).get(m.group(1)) if m else None
    if not isinstance(fam, dict) or fam.get("texturing") != "tiling":
        return None
    td, mp, phase = fam.get("texel_density"), fam.get("map_px"), fam.get("tile_phase", "grid")
    if phase not in ("grid", "variants") or not (td and mp):
        return None
    var = PHASE_VARIANT_RE.search(name) if phase == "variants" else None
    if extents:
        horizontal = (extents[2] < min(extents[0], extents[1]) and extents[2] < module
                      and min(extents[0], extents[1]) >= module * 0.99)
    else:
        horizontal = _floor_like(m.group(1), m.group(2).count("x") + 1, families)
    return (float(mp) / float(td), float(td), int(var.group(1)) if var else 0, horizontal,
            float(fam.get("turn_symmetry", 360)))


def _place_box(pl, bounds, module, families=None):
    """World [lo, hi] of a grid placement: its piece's measured local bounds (a piece in this file), else its Size token
    (zero thickness), mirrored, turned about Z and moved to its position; None when neither is known."""
    b = bounds.get(pl["asset"])
    if b is None:
        m = NAME_RE.match(pl["asset"])
        if not m or m.group(2) == "Free":
            return None
        nums = [int(v) * module for v in m.group(2).split("x")]
        if len(nums) == 3:
            ext = nums
        elif len(nums) == 2:
            ext = [nums[0], nums[1], 0.0] if _floor_like(m.group(1), 2, families) else [nums[0], 0.0, nums[1]]
        else:
            return None
        b = [0.0, 0.0, 0.0] + ext
    a = math.radians(pl["rot_z"])
    c, s = math.cos(a), math.sin(a)
    mx = -1.0 if pl.get("mirrored") else 1.0
    pts = [(pl["pos"][0] + c * mx * x - s * y, pl["pos"][1] + s * mx * x + c * y, pl["pos"][2] + z)
           for x in (b[0], b[3]) for y in (b[1], b[4]) for z in (b[2], b[5])]
    return [min(q[k] for q in pts) for k in range(3)], [max(q[k] for q in pts) for k in range(3)]


def wall_contacts(places, bounds, module, families=None, tol=CONTACT_TOL_M):
    """Judge a tiling wall's courses (its V phase) against the walls of its family it touches, not against world z: a
    raised stage or a mezzanine whose walls meet only each other starts its courses at its own floor. Each wall's
    tile_phase gets v_abs_px (z mod tile, as placed), v_px (the largest offset against a wall whose box touches its
    own, 0 when it touches none) and v_against (the walls it is off against). In place."""
    walls = [(i, _place_box(p, bounds, module, families)) for i, p in enumerate(places)
             if p.get("tile_phase") and not p["tile_phase"]["horizontal"]]
    walls = [(i, box) for i, box in walls if box]
    for i, _box in walls:
        tp = places[i]["tile_phase"]
        tp["v_abs_px"], tp["v_px"], tp["v_against"] = tp["v_px"], 0.0, []
    for x in range(len(walls)):
        i, (lo_i, hi_i) = walls[x]
        ti = places[i]["tile_phase"]
        fam_i = NAME_RE.match(places[i]["asset"]).group(1)
        for y in range(x + 1, len(walls)):
            j, (lo_j, hi_j) = walls[y]
            tj = places[j]["tile_phase"]
            if NAME_RE.match(places[j]["asset"]).group(1) != fam_i or abs(ti["tile_m"] - tj["tile_m"]) > 1e-6:
                continue
            if any(lo_i[k] > hi_j[k] + tol or lo_j[k] > hi_i[k] + tol for k in range(3)):
                continue
            dz = (places[i]["pos"][2] - places[j]["pos"][2]) % ti["tile_m"]
            d = round(min(dz, ti["tile_m"] - dz) * ti["px_per_m"], 2)
            for a, b in ((i, j), (j, i)):
                tp = places[a]["tile_phase"]
                tp["v_px"] = max(tp["v_px"], d)
                if d > TILE_PHASE_TEXELS:
                    tp["v_against"].append(places[b]["object"])


def measure(module=1.0, scene=None, role=None, lightmap_texels=None, lightmap_scale=1.0, sub_module=None,
            texel_map=None, lightmapper="unity", families=None):
    """Everything qa_measure reports about the open file. sub_module: the grid step for TRIM placements. lightmapper:
    the spec's lighting.baker, unity ("progressive") or bakery, whose footprint lightmap_px is. families: the spec's
    families ({code: {texturing, map_px, texel_density, tile_phase, turn_symmetry, scale_range}}): each placement of a
    tiling family's piece gets its tile_phase against the world grid (U7), and a Free piece its family's scale_range
    (default FREE_SCALE_BAND) as the even scale it may take."""
    lightmapper = lightmapper_name(lightmapper)
    scene = scene or bpy.context.scene
    role = role or file_role(bpy.data.filepath)
    local = [c for c in bpy.data.collections if c.library is None]
    local_pieces = [c for c in local if NAME_RE.match(c.name)]
    with _evaluated(local_pieces):            # pieces excluded or disabled in the outliner, measured as they export
        dg = bpy.context.evaluated_depsgraph_get()
        pieces = [measure_piece(c, module, dg, lightmap_texels, lightmap_scale, texel_map, lightmapper, families)
                  for c in sorted(local_pieces, key=lambda c: c.name)]
    dg = bpy.context.evaluated_depsgraph_get()
    linked_names = {c.name for c in bpy.data.collections if c.library is not None}
    places = []
    for ob in scene.objects:
        if ob.instance_type == "COLLECTION" and ob.instance_collection is not None:
            coll = ob.instance_collection
            mw = ob.matrix_world
            mirrored = mw.to_3x3().determinant() < 0
            if mirrored:                          # read it as the unmirrored placement, mirrored in its own X
                mw = mw @ Matrix.Diagonal((-1.0, 1.0, 1.0, 1.0))
            loc, rot, scale = mw.decompose()
            rm = rot.to_matrix()
            x_axis, z_axis = rm @ Vector((1, 0, 0)), rm @ Vector((0, 0, 1))
            rz = math.degrees(math.atan2(x_axis.y, x_axis.x))
            m = NAME_RE.match(coll.name)
            kind = ("asm" if ASM_RE.match(coll.name) else "grid" if m and m.group(2) != "Free"
                    else "free" if m else "other")
            step = sub_module if (sub_module and m and m.group(1) == TRIM_FAMILY) else module
            r90 = (rz + 360.0) % 90.0
            ext = next((p.get("extent_modules") for p in pieces if p["piece"] == coll.name), None)
            tl = (_tiling(families, coll.name, module, [e * module for e in ext] if ext else None)
                  if kind == "grid" else None)
            fam = (families or {}).get(m.group(1)) if m else None
            band = fam.get("scale_range") if isinstance(fam, dict) else None
            places.append({
                "object": ob.name, "asset": coll.name, "kind": kind, "linked": coll.library is not None,
                "id": ob.get("placement_id"), "pos": [round(v, 4) for v in loc], "rot_z": round(rz, 3),
                "rot_xy_ok": z_axis.z > 1.0 - 1e-6, "mirrored": mirrored,
                "scale_ok": all(abs(s - 1.0) < EPS for s in scale),
                "scale": [round(s, 4) for s in scale],
                # X and Y only, heights are checked against the spec. Grid pieces must be on the grid at 90 deg
                # steps; for assemblies the two values are data only (A3 compares them with the spec instead).
                "on_grid": (all(abs(v - round(v / step) * step) < GRID_TOL_M for v in loc[:2])
                            if kind in ("grid", "asm") else None),
                "right_angle": (min(r90, 90.0 - r90) < 1e-2 if kind in ("grid", "asm") else None),
                "tile_phase": (dict(tile_phase(loc, (rz + 360.0) % 360.0, tl[0], tl[1], module, tl[2], tl[3], tl[4]),
                                    tile_m=round(tl[0], 4), px_per_m=tl[1], horizontal=tl[3]) if tl else None),
                "scale_band": (list(band) if band else list(FREE_SCALE_BAND)) if kind in ("free", "asm") else None,
            })
    wall_contacts(places, {p["piece"]: p["bounds_m"] for p in pieces if p.get("bounds_m")}, module, families)
    single = scene.get("kit_layout") == "single"
    owner, layout_problems = _single_layout(scene, local, local_pieces) if single else ({}, [])
    for p in places:
        p["assembly"] = owner.get(p["object"])
    used_locally = {p["asset"] for p in places if not p["linked"]} if not single else set()
    owned = {o.name for c in local_pieces for o in c.all_objects}
    return {
        "file": bpy.data.filepath,
        "role": role,
        "layout": "single" if single else None,
        "layout_problems": layout_problems,
        "module": module,
        "sub_module": sub_module,
        "lightmapper": lightmapper,
        "libraries": [_library_entry(lib) for lib in bpy.data.libraries],
        "pieces": pieces,
        # local collections holding meshes under a name that is neither a piece nor an assembly (REF aside)
        "unnamed_collections": sorted(c.name for c in local if not NAME_RE.match(c.name) and not ASM_RE.match(c.name)
                                      and not _is_ref(c) and any(o.type == "MESH" for o in c.objects)),
        "local_assemblies": sorted(c.name for c in local if ASM_RE.match(c.name)),
        "local_assembly_offsets": {c.name: _vec(c.instance_offset) for c in local if ASM_RE.match(c.name)},
        "images": measure_images(),
        # In MASTER or an ASM file: what each linked piece currently is, as loaded from its KIT file.
        "linked_assembly_offsets": {c.name: _vec(c.instance_offset) for c in bpy.data.collections
                                    if c.library is not None and ASM_RE.match(c.name)},
        "linked_pieces": [{"piece": c.name, "library": c.library.filepath, "kit_status": c.get("kit_status"),
                           "tris": _evaluated_tris(c, dg), "instance_offset": _vec(c.instance_offset)}
                          for c in sorted(bpy.data.collections, key=lambda c: c.name)
                          if c.library is not None and NAME_RE.match(c.name)],
        "placements": places,
        "placement_overlaps": placement_overlaps(dg, scene) if places else [],
        # a kit-named local collection that is also placed here is a copy, not a link (in a single MASTER, the norm)
        "appended": sorted(n for n in used_locally if NAME_RE.match(n) or ASM_RE.match(n)),
        "shadowing_linked": sorted(c.name for c in local if (NAME_RE.match(c.name) or ASM_RE.match(c.name))
                                   and c.name in linked_names),
        # REF: scale figures and other review aids a MASTER may hold (never exported); everything else local is stray
        "ref_meshes": sorted(o.name for o in scene.objects if o.type == "MESH" and o.library is None
                             and o.name not in owned and _in_ref(o)),
        "stray_meshes": sorted(o.name for o in scene.objects
                               if o.type == "MESH" and o.library is None and o.name not in owned and not _in_ref(o)),
    }


def measure_images():
    """Every image a material in this file uses: path (relative or not), packed, missing (did not load), size,
    channels, colour space, alpha mode, and which materials use it. For X2/X3."""
    users, found = {}, {}
    for mat in bpy.data.materials:
        if mat.node_tree is None:
            continue
        for n in mat.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image is not None:
                found[n.image.name_full] = n.image
                users.setdefault(n.image.name_full, set()).add(mat.name)
    out = []
    for name, mats in sorted(users.items()):
        im = found[name]
        size = list(im.size)
        out.append({"image": name, "filepath": im.filepath, "relative": im.filepath.startswith("//"),
                    "packed": im.packed_file is not None,
                    "missing": im.source in ("FILE", "SEQUENCE", "TILED") and im.packed_file is None
                    and size[0] == 0,
                    "size": size, "channels": im.channels, "colorspace": im.colorspace_settings.name,
                    "alpha_mode": im.alpha_mode, "materials": sorted(mats)})
    return out


def tile_seam(path):
    """Seam metric for a tiling texture (X4): the mean colour step across the wrap edges against the mean step
    between neighbouring pixels inside the tile, per axis. Ratios near or below 1 mean no visible seam."""
    import numpy as np
    im = bpy.data.images.load(os.path.abspath(path), check_existing=False)
    try:
        w, h = im.size
        px = np.empty(w * h * 4, np.float32)
        im.pixels.foreach_get(px)
        a = px.reshape(h, w, 4)[:, :, :3]
        inner_x = float(np.abs(np.diff(a, axis=1)).mean())
        inner_y = float(np.abs(np.diff(a, axis=0)).mean())
        edge_x = float(np.abs(a[:, 0] - a[:, -1]).mean())
        edge_y = float(np.abs(a[0] - a[-1]).mean())
        return {"image": path, "size": [w, h], "edge_x": round(edge_x, 5), "inner_x": round(inner_x, 5),
                "ratio_x": round(edge_x / max(inner_x, 1e-9), 2), "edge_y": round(edge_y, 5),
                "inner_y": round(inner_y, 5), "ratio_y": round(edge_y / max(inner_y, 1e-9), 2)}
    finally:
        bpy.data.images.remove(im)


def image_stats(path, gain=None):
    """Mean, min and max of an image's RGB channels on the 0-255 scale (fully transparent pixels left out), luma
    percentiles (Rec. 709 weights on the stored values: p1, p50, p99), the share of pixels with any channel at
    CLIPPED_CODE or more (clipped_share) and with luma at CRUSHED_LUMA or less (crushed_share), and the share of pixels
    at least half opaque (coverage), for judging dark renders and final looks by number: an image viewer may
    auto-level them. With gain, a brightened copy is saved next to it as <name>_x<gain>.png to judge seams and leaks
    on. Works on any PNG, Unity renders included."""
    import numpy as np
    src = os.path.abspath(path)
    im = bpy.data.images.load(src, check_existing=False)
    try:
        w, h = im.size
        px = np.empty(w * h * 4, np.float32)
        im.pixels.foreach_get(px)
        a = px.reshape(-1, 4)
        rgb = a[a[:, 3] > 0.0][:, :3]
        lum = (rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)) * 255.0 if rgb.size else rgb

        def pct(q):
            return round(float(np.percentile(lum, q)), 1) if rgb.size else None

        out = {"image": path, "size": [w, h],
               "mean": round(float(rgb.mean()) * 255.0, 1) if rgb.size else None,
               "min": round(float(rgb.min()) * 255.0, 1) if rgb.size else None,
               "max": round(float(rgb.max()) * 255.0, 1) if rgb.size else None,
               "luma_p1": pct(1), "luma_p50": pct(50), "luma_p99": pct(99),
               "clipped_share": round(float((rgb.max(axis=1) * 255.0 >= CLIPPED_CODE - 1e-3).mean()), 4)
               if rgb.size else None,
               "crushed_share": round(float((lum <= CRUSHED_LUMA + 1e-3).mean()), 4) if rgb.size else None,
               "coverage": round(float((a[:, 3] >= 0.5).mean()), 4) if a.size else 0.0}
        if gain:
            g = a.copy()
            g[:, :3] = np.clip(g[:, :3] * float(gain), 0.0, 1.0)
            dst = "%s_x%g.png" % (os.path.splitext(src)[0], gain)
            cp = bpy.data.images.new("qa_gain", w, h, alpha=True)
            try:
                cp.pixels.foreach_set(g.ravel())
                cp.filepath_raw = dst
                cp.file_format = "PNG"
                cp.save()
            finally:
                bpy.data.images.remove(cp)
            out["gain_copy"] = dst
        return out
    finally:
        bpy.data.images.remove(im)


def _pbr_module():
    """pbr_check.py from this script's own folder (shipped identically in the pbr-texturing skill), loaded without
    writing a __pycache__ into the skill. Code run through exec has no __file__ of its own: the live route sets
    ns["__file__"] to this script's path first."""
    import importlib.util
    here = globals().get("__file__")
    if not here:
        raise RuntimeError("the PBR check needs this script's path: set ns['__file__'] to qa_measure.py before exec")
    path = os.path.join(os.path.dirname(os.path.abspath(here)), "pbr_check.py")
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("qa_pbr_check", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = keep


def pbr(paths, map_px=None, targets=None, tiling=False):
    """X8: the PBR value checks of texture maps paired by name (T_<FAMILY>_<Name>_BaseColor, _MetallicSmoothness,
    _Normal), one dict per material with its stats, "problems" (blocking) and "notes" (advisory). targets: the spec's
    look.materials, {material: {albedo_srgb, roughness, metal}}. tiling (X4): True judges the maps as tiling (a seam
    along part of an edge, tile-scale variation that draws a grid), "x" as a trim sheet (along U only)."""
    return _pbr_module().check_files(paths, map_px=map_px, targets=targets, tiling=tiling)


def compare_placements(rep, prev):
    """What changed between a previous qa_measure report's placements and this file's. A placement is matched by its
    placement_id first (what placement sync keys on), and by object name only when the previous one had no id. Lists
    moves, rotations, swapped assets, additions and removals, and every id that vanished or changed: an instance that
    was deleted and placed again loses its id even under its old name, so placement sync would see a new placement,
    while a re-pointed one keeps it and shows only as "now places"."""
    old, cur = prev.get("placements", []), rep["placements"]
    by_id = {p["id"]: p for p in cur if p.get("id")}
    used, pairs, out = set(), [], []
    for q in old:
        if q.get("id") in by_id:
            pairs.append((q, by_id[q["id"]]))
            used.add(id(by_id[q["id"]]))
    by_obj = {p["object"]: p for p in cur if id(p) not in used}
    for q in old:
        if q.get("id") in by_id:
            continue
        p = by_obj.get(q["object"])
        p = p if p is not None and id(p) not in used else None
        if p is not None:
            used.add(id(p))
        if q.get("id"):
            if p is None:
                out.append("%s: id %s vanished (%s removed, or deleted and placed again under another name)"
                           % (q["object"], q["id"], q["asset"]))
            else:
                out.append("%s: id %s %s (deleted and placed again, or its id cleared): placement sync would see a "
                           "new placement" % (q["object"], q["id"], ("changed to %s" % p["id"]) if p.get("id")
                                              else "is gone"))
        elif p is None:
            out.append("%s removed (%s)" % (q["object"], q["asset"]))
        else:
            pairs.append((q, p))
    for q, p in pairs:
        if p["asset"] != q["asset"]:
            out.append("%s now places %s (was %s)" % (p["object"], p["asset"], q["asset"]))
        if max(abs(a - b) for a, b in zip(p["pos"], q["pos"])) > 1e-3:
            out.append("%s moved %s -> %s" % (p["object"], q["pos"], p["pos"]))
        if abs((p["rot_z"] - q["rot_z"] + 180.0) % 360.0 - 180.0) > 0.01:
            out.append("%s rotated %s -> %s deg" % (p["object"], q["rot_z"], p["rot_z"]))
    out += ["%s added (%s at %s)" % (p["object"], p["asset"], p["pos"]) for p in cur if id(p) not in used]
    return out


def notes(rep, pieces=None, probe_lit=None):
    """Advisory lines, not failures. pieces and probe_lit as in problems(): pieces outside the task, and pieces or LOD
    objects already marked probe-lit, get none.
    - A lightmap footprint under MIN_FOOTPRINT_PX (with --lightmap-texels), judged on LOD0 only: LOD0 decides for the
      whole piece, and LOD1+ follow it (lightmapped, at 0.5^n under Unity) unless the spec sets lod_lightmap: false.
      Only a Free prop (a Free-sized piece of a PROBE_LIT_FAMILIES family) is told to become probe-lit; every other
      piece, ZONE shells included, stays lightmapped.
    - UV2 charts filling under half their bounding box (uv2_box_fill < 0.5) on a lightmapped mesh whose own footprint
      (with --lightmap-texels) is MIN_FOOTPRINT_PX or more: Unity packs the box and Bakery maps it onto its rect, so
      its empty space costs lightmap texels (U6). Below that the footprint note and the probe-lit advice govern, and
      small LODs would only make noise; a mesh under Bakery's effective-density gate gets a PROBLEM line instead."""
    bakery = rep.get("lightmapper") == "bakery"
    out = ["placement %s (%s) is mirrored (negative scale): Unity keeps it, and a symmetric piece (a door hung the "
           "other way) reads right; text, logos and one-sided wear read backwards, and the spec records turns only, so "
           "record mirror: true on its placement in the spec" % (pl["object"], pl["asset"])
           for pl in rep.get("placements", []) if pl.get("mirrored") and not pl.get("tile_phase")]
    for p in rep.get("pieces", []):
        n = p["piece"]
        if pieces is not None and not any(fnmatch.fnmatchcase(n, g) for g in pieces):
            continue
        if any(fnmatch.fnmatchcase(n, g) for g in probe_lit or []):
            continue
        m = NAME_RE.match(n)
        prop = bool(m) and m.group(2) == "Free" and m.group(1) in PROBE_LIT_FAMILIES
        for on, st in p["objects"].items():
            if any(fnmatch.fnmatchcase(on, g) for g in probe_lit or []):
                continue                                         # one LOD marked probe-lit
            fill, px = st.get("uv2_box_fill"), st.get("lightmap_px")
            if (fill is not None and fill < UV2_BOX_FILL_NOTE and px is not None and px >= MIN_FOOTPRINT_PX
                    and not COL_RE.search(on) and not _density_low(st)):
                out.append("%s/%s: UV2 charts fill %d%% of their bounding box (< %d%%) at its %s px footprint: the "
                           "empty space costs lightmap texels; pack the charts to fill their box (any aspect ratio)"
                           % (n, on, round(100 * fill), round(100 * UV2_BOX_FILL_NOTE), px))
            if not _is_lod0_name(on):
                continue                                         # LOD1+ follow their piece's LOD0
            if px is not None and px < MIN_FOOTPRINT_PX:
                out.append("%s/%s: lightmap footprint %s px < %d: %s" % (n, on, px, MIN_FOOTPRINT_PX, (
                    "a Free prop: make it probe-lit (lightmap: false in the spec), unless its zone has "
                    "lighting_states above 1, where it changes with the switch and stays lightmapped in every "
                    "state copy") if prop else (
                    "not a Free prop (PROP or FOL), so it stays lightmapped; raise its lightmap_scale or the world's "
                    "texels_per_m if it needs more texels%s" % (
                        " (Bakery: Scale In Lightmap acts on the area, so s^2 for a linear factor s)" if bakery
                        else ""))))
    return out


def problems(rep, piece_tris=None, expect_status=None, pieces=None, probe_lit=None, all_lods=UV2_LAYOUT_ALL_LODS):
    """Readable failures. piece_tris: {family or piece name: max LOD0 triangles}; a piece's own entry wins.
    expect_status: the kit_status this stage sets. Local pieces must carry exactly it, linked pieces at least it,
    and the n-gon, empty-slot and UV2 rules apply from it, so a stale status cannot hide a fault. pieces: names or
    globs of the pieces this task touched (a task split by piece); piece checks skip the others. probe_lit: names or
    globs of the pieces the spec marks lightmap: false, or of LOD objects that are probe-lit (<Piece>_LOD[1-9] for a
    piece with lod_lightmap: false); they still need a UV2, but its layout is not checked, and a glob that matches
    nothing is a problem in itself. all_lods: check LOD1+
    layouts too, each at its own footprint (UV2_LAYOUT_ALL_LODS: each LOD has its own atlas space); False checks
    LOD0 only. Measured with lightmapper bakery, a lightmapped mesh at MIN_FOOTPRINT_PX or more whose
    effective_texels_per_m is under its effective_texels_min is a problem too (U4)."""
    out = []
    role = rep.get("role")
    want = STATUS_ORDER.index(expect_status) if expect_status in STATUS_ORDER else None

    def ours(name):
        return pieces is None or any(fnmatch.fnmatchcase(name, g) for g in pieces)

    def lit(*names):                          # a piece, or one LOD object, marked probe-lit is not lightmapped
        return not any(fnmatch.fnmatchcase(x, g) for x in names for g in probe_lit or [])

    for g in pieces or []:
        if not any(fnmatch.fnmatchcase(p["piece"], g) for p in rep["pieces"] + rep.get("linked_pieces", [])):
            out.append("--pieces %s matches no piece in this file" % g)
    for g in probe_lit or []:                 # a typo would leave a probe-lit piece checked as lightmapped
        names = [p["piece"] for p in rep["pieces"] + rep.get("linked_pieces", [])]
        names += [on for p in rep["pieces"] for on in p["objects"]]
        if not any(fnmatch.fnmatchcase(x, g) for x in names):
            out.append("--probe-lit %s matches no piece or LOD object in this file" % g)
    for n in rep.get("unnamed_collections", []):
        out.append("collection %s holds meshes but is named neither <FAMILY>_<Type>_<Size>_<Variant> nor "
                   "ASM_<Name>_<Variant>" % n)
    for n in rep.get("stray_meshes", []):
        out.append("stray mesh %s: outside every piece collection and not in REF" % n)
    for lib in rep.get("libraries", []):
        if not lib["relative"]:
            out.append("library %s is linked by an absolute path (link with relative paths)" % lib["path"])
        if not lib["found"]:
            out.append("library %s not found" % lib["path"])
    single = rep.get("layout") == "single"
    out += rep.get("layout_problems", [])
    if role in ("master", "asm") and not single:
        out += ["%s: local piece collection in a %s file, a copy rather than a link" % (p["piece"], role.upper())
                for p in rep["pieces"]]
    if role == "master" and not single:
        out += ["%s: local assembly in MASTER; link it from its ASM file" % n for n in rep.get("local_assemblies", [])]
    if role == "asm":
        own = os.path.splitext(os.path.basename(rep.get("file", "")))[0]
        if own not in rep.get("local_assemblies", []):
            out.append("ASM file holds no assembly collection named after the file (%s)" % own)
        out += ["%s: an ASM file holds one assembly, named after the file (%s)" % (n, own)
                for n in rep.get("local_assemblies", []) if n != own]
    for n, off in sorted(rep.get("local_assembly_offsets", {}).items()):
        if _nonzero(off):
            out.append("%s: instance_offset %s, must be 0 (every placement of it is drawn that far off)" % (n, off))
    for n, off in sorted(rep.get("linked_assembly_offsets", {}).items()):
        if _nonzero(off):
            out.append("linked assembly %s: instance_offset %s; fix it in its ASM file (every placement of it is "
                       "drawn that far off)" % (n, off))
    for p in rep["pieces"] if role not in ("master", "asm") or single else []:
        n = p["piece"]
        if not ours(n):
            continue
        fam = n.split("_")[0]
        status = p.get("kit_status")
        if want is not None and role != "fbx" and status != expect_status:
            out.append("%s: kit_status %r, expected %r" % (n, status, expect_status))
        stage = want if want is not None else (STATUS_ORDER.index(status) if status in STATUS_ORDER
                                               else len(STATUS_ORDER))
        if _nonzero(p.get("instance_offset", [0, 0, 0])):
            out.append("%s: instance_offset %s, must be 0 (every placement of it is drawn that far off)"
                       % (n, p["instance_offset"]))
        if p["transform_issues"]:
            out.append("%s: non-identity transforms on %s" % (n, ", ".join(p["transform_issues"])))
        if p.get("size_ok") is False:
            out.append("%s: extents %s modules do not match the Size token" % (n, p.get("extent_modules")))
        if p.get("pivot_ok") is False:
            out.append("%s: min corner %s not at the origin" % (n, p.get("bounds_m", [])[:3]))
        limit = (piece_tris or {}).get(n, (piece_tris or {}).get(fam))
        if limit is not None and p["lod0_tris"] > limit:
            out.append("%s: %d LOD0 tris > budget %d" % (n, p["lod0_tris"], limit))
        if p.get("coplanar_overlaps"):
            out.append("%s: %d pairs of overlapping coplanar faces (duplicates, z-fighting or zero-thickness), "
                       "e.g. %s" % (n, p["coplanar_overlaps"], "; ".join(p["coplanar_overlap_examples"][:2])))
        if p.get("bad_materials"):
            out.append("%s: material names not M_<FAMILY>_<Name>: %s" % (n, ", ".join(p["bad_materials"])))
        # Greybox (grey) may still have n-gons; empty material slots are allowed until textured.
        for on, st in p["objects"].items():
            if st["ngons"] and stage >= STATUS_ORDER.index("modelled"):
                out.append("%s/%s: %d n-gons" % (n, on, st["ngons"]))
            if st["edges_over_2_faces"]:
                out.append("%s/%s: %d edges shared by 3+ faces" % (n, on, st["edges_over_2_faces"]))
            if st["loose_verts"]:
                out.append("%s/%s: %d loose vertices" % (n, on, st["loose_verts"]))
            if st.get("loose_edges"):
                out.append("%s/%s: %d wire edges (no face)" % (n, on, st["loose_edges"]))
            if None in st["materials"] and stage >= STATUS_ORDER.index("textured"):
                out.append("%s/%s: empty material slot" % (n, on))
            if COL_RE.search(on) or stage < STATUS_ORDER.index("uv"):
                continue
            # UV2: on every render mesh (LODs and probe-lit pieces too); its layout matters on every lightmapped one,
            # LOD1+ included. Counted on the evaluated mesh, which is what exports: a modifier that rebuilds the
            # geometry drops it.
            uv = list((st.get("uv") or {}).values())
            if len(uv) < 2:
                out.append("%s/%s: no UV2 (second UV layer) on the mesh as it exports%s; every render mesh carries one"
                           % (n, on, " (it has no faces)" if not st["tris"] else ""))
                continue
            if lit(n, on) and (all_lods or _is_lod0_name(on)):
                u0, v0, u1, v1 = uv[1]["bounds"]
                if min(u0, v0) < -EPS or max(u1, v1) > 1.0 + EPS:
                    out.append("%s/%s: UV2 outside 0-1 (bounds %s)" % (n, on, [u0, v0, u1, v1]))
                if st.get("uv2_overlaps"):
                    out.append("%s/%s: %d pairs of UV2 charts overlap" % (n, on, st["uv2_overlaps"]))
                if st.get("uv2_min_gap_texels") is not None and st["uv2_min_gap_texels"] < 2.0:
                    out.append("%s/%s: UV2 charts %s texels apart at its %s px footprint (< 2)"
                               % (n, on, st["uv2_min_gap_texels"], st["lightmap_px"]))
                if st.get("uv2_edge_margin_texels") is not None and st["uv2_edge_margin_texels"] < 1.0:
                    out.append("%s/%s: UV2 %s texels from the tile edge at its %s px footprint (< 1)"
                               % (n, on, st["uv2_edge_margin_texels"], st["lightmap_px"]))
                if _density_low(st):
                    out.append("%s/%s: effective lightmap density %s texels/m at its %s px footprint, under %s (half "
                               "the density planned for it): Bakery sizes a renderer by its area and UV2 bounds, not "
                               "by its charts' area, and these fill %d%% of their box; pack the charts to fill it, or "
                               "raise Scale In Lightmap and pack again for the larger footprint"
                               % (n, on, st["effective_texels_per_m"], st["lightmap_px"], st["effective_texels_min"],
                                  round(100 * (st.get("uv2_box_fill") or 0))))
    for lp in rep.get("linked_pieces", []):
        if not ours(lp["piece"]):
            continue
        s = lp.get("kit_status")
        if want is not None and (s not in STATUS_ORDER or STATUS_ORDER.index(s) < want):
            out.append("linked piece %s: kit_status %r is behind %r" % (lp["piece"], s, expect_status))
        if _nonzero(lp.get("instance_offset", [0, 0, 0])):
            out.append("linked piece %s: instance_offset %s in its KIT file, so every placement of it is drawn that "
                       "far off" % (lp["piece"], lp["instance_offset"]))
    for pl in rep["placements"]:
        sc = [abs(s) for s in pl.get("scale") or [1.0, 1.0, 1.0]]     # a mirror decomposes to negative scales
        if max(sc) > min(sc) * (1.0 + 1e-3):
            out.append("placement %s (%s) scaled unevenly %s: its texture stretches; scale it evenly or remodel it"
                       % (pl["object"], pl["asset"], pl["scale"]))
        if pl.get("kind") in ("free", "asm") and max(sc) <= min(sc) * (1.0 + 1e-3):
            lo, hi = pl.get("scale_band") or FREE_SCALE_BAND
            if not lo - 1e-6 <= sc[0] <= hi + 1e-6:
                out.append("placement %s (%s) scaled %g: its texels per metre are %.2fx the kit's (keep %g-%g, or "
                           "the family's scale_range): model it at that size, or texture it for it"
                           % (pl["object"], pl["asset"], sc[0], 1.0 / sc[0], lo, hi))
        if pl.get("kind") != "grid":
            continue                          # Free props and assemblies: data only, compared with the spec (A3)
        tp = pl.get("tile_phase")
        if tp and tp["horizontal"] and max(tp["u_px"], tp["v_px"]) > TILE_PHASE_TEXELS:
            out.append("placement %s (%s) sits %.1f px along X and %.1f px along Y off its family's %g m tile grid: "
                       "its pattern jumps against its neighbours (a phase variant _P<k>: k = kx + n x ky, n the tile "
                       "in modules)" % (pl["object"], pl["asset"], tp["u_px"], tp["v_px"], tp["tile_m"]))
        if tp and not tp["horizontal"] and tp["u_px"] > TILE_PHASE_TEXELS:
            out.append("placement %s (%s) sits %.1f px along it off its family's %g m tile grid: its pattern jumps "
                       "against its neighbours" % (pl["object"], pl["asset"], tp["u_px"], tp["tile_m"]))
        if tp and not tp["horizontal"] and tp["v_px"] > TILE_PHASE_TEXELS:
            out.append("placement %s (%s) has its courses %.1f px off the walls of its family it meets (%s): its base "
                       "is not a whole number of %g m tiles from theirs" % (
                           pl["object"], pl["asset"], tp["v_px"], ", ".join(tp.get("v_against", [])[:3]),
                           tp["tile_m"]))
        if tp and tp["turn_deg"] > 1e-3:
            out.append("placement %s (%s) turned %g deg: a tiling floor or ceiling turns its pattern with it; place "
                       "it unturned (or give the family turn_symmetry when the texture looks the same turned)"
                       % (pl["object"], pl["asset"], tp["turn_deg"]))
        if pl["on_grid"] is False:
            out.append("placement %s (%s) off grid at %s" % (pl["object"], pl["asset"], pl["pos"][:2]))
        if pl["right_angle"] is False:
            out.append("placement %s (%s) rotated %s deg" % (pl["object"], pl["asset"], pl["rot_z"]))
        if pl.get("mirrored") and tp:
            out.append("placement %s (%s) mirrored (negative scale): its tiling pattern runs backwards against its "
                       "neighbours; place it unmirrored, or model the mirrored piece as its own variant"
                       % (pl["object"], pl["asset"]))
        if not pl["rot_xy_ok"]:
            out.append("placement %s (%s) tilted: rotated about X or Y" % (pl["object"], pl["asset"]))
        if not pl["scale_ok"]:
            out.append("placement %s (%s) scaled: grid pieces are placed at scale 1" % (pl["object"], pl["asset"]))
    out += ["placements %s and %s have %d face pair(s) in one plane facing the same way: they z-fight; set one back "
            "(an engaged capital or base stands proud of the wall face or is let into it) or remove the hidden face"
            % (a, b, k) for a, b, k in rep.get("placement_overlaps", [])]
    out += ["%s is placed from a local copy (appended), not linked" % n for n in rep["appended"]]
    out += ["local collection %s shadows a linked one of the same name" % n for n in rep["shadowing_linked"]]
    if role != "fbx":                        # a Path Mode Strip export carries no textures: data only there
        for im in rep.get("images", []):
            if im.get("missing"):
                out.append("image %s (used by %s) did not load: %s" % (im["image"], ", ".join(im["materials"]),
                                                                        im["filepath"]))
    out += ["placement %s" % c for c in rep.get("placement_changes", [])]
    return out


# ---- renders ------------------------------------------------------------------------------------------------------

# Camera direction (eye towards target) and up, Blender axes. An elevation of a facade facing south is "front",
# north "back", east "right", west "left"; a plan is "top".
VIEWS = {
    "top": ((0, 0, -1), (0, 1, 0)), "front": ((0, 1, 0), (0, 0, 1)), "back": ((0, -1, 0), (0, 0, 1)),
    "right": ((-1, 0, 0), (0, 0, 1)), "left": ((1, 0, 0), (0, 0, 1)),
}
COLORS = {"random": "RANDOM", "texture": "TEXTURE", "material": "MATERIAL"}
LIGHTS = {"studio": "STUDIO", "flat": "FLAT", "lookdev": None}    # lookdev is EEVEE, not a Workbench light
# --light lookdev (house settings): a neutral grey world (linear grey, strength 1), one sun of this strength (W/m2) at
# this elevation and azimuth from behind the camera's left, EEVEE render samples. A mid-grey dielectric facing the
# camera renders about mid-tone at exposure 0 under the Standard view transform.
LOOKDEV = {"world": 0.25, "sun": 2.5, "elevation": 45.0, "azimuth": 45.0, "samples": 16}
CLIPPED_CODE = 250     # image_stats: a pixel with any channel at this code or more is clipped (L7)
CRUSHED_LUMA = 5       # image_stats: a pixel at this luma or less is crushed to black (L7)


def render_hidden(lod=0, show_collision=False, hide_objects=(), isolate=None, hide_collections=()):
    """The objects a review render leaves out: LODs other than `lod` and collision shells (unless show_collision),
    objects whose names match a glob in hide_objects, the objects of hide_collections, and with isolate (a
    collection name) every object outside that collection. Linked objects too: hiding them affects only this run."""
    keep = None
    if isolate:
        coll = bpy.data.collections.get(isolate)
        if coll is None:
            raise ValueError("--isolate: no collection named %s" % isolate)
        keep = set(coll.all_objects)
    gone = set()
    for name in hide_collections:
        coll = bpy.data.collections.get(name)
        if coll is None:
            print("[qa] --hide-collection: no collection %s" % name)
            continue
        gone |= set(coll.all_objects)
    out = []
    for ob in bpy.data.objects:
        if ob.type in ("CAMERA", "LIGHT"):
            continue
        m = LOD_RE.search(ob.name)
        if ((m and int(m.group(1)) != lod) or (not show_collision and COL_RE.search(ob.name))
                or any(fnmatch.fnmatchcase(ob.name, g) for g in hide_objects) or ob in gone
                or (keep is not None and ob not in keep)):
            out.append(ob)
    return out


def render_ortho(path, view, center, extent, px_per_m=20.0, distance=200.0, clip=None, color="random", light="studio",
                 wire=None, cull=None, two_sided=()):
    """Orthographic Workbench render of everything visible. view: top/front/back/right/left ("front" looks along +Y,
    so it shows a facade facing south). extent: (width, height) in metres of the framed area. clip: if given, only
    geometry from `clip` metres in front of the centre plane onward is drawn (an interior wall seen from inside the
    room, without the opposite wall in the way). wire: edge thickness in metres for a wireframe render. cull: back
    faces hidden (default; a section, with clip, shows them: it looks inside the cut). Restores the scene."""
    cull = clip is None if cull is None else cull
    fwd, up = (Vector(v) for v in VIEWS[view])
    c = Vector((list(center) + [0, 0, 0])[:3])
    cam_data = bpy.data.cameras.new("qa_cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = max(extent)
    cam_data.clip_end = distance * 2
    if clip is not None:
        cam_data.clip_start = max(0.001, distance - clip)
    right = fwd.cross(up)
    matrix = Matrix.Translation(c - fwd * distance) @ Matrix((right, up, -fwd)).transposed().to_4x4()
    return _render(path, cam_data, matrix, (max(16, int(round(extent[0] * px_per_m))),
                                            max(16, int(round(extent[1] * px_per_m)))), color, light, wire, cull,
                   two_sided)


def render_view(path, pos, target, lens=24.0, size=(1280, 720), color="random", light="studio", wire=None,
                cull=True, two_sided=()):
    """Perspective Workbench render from a spec view: camera at `pos` looking at `target` (world metres), focal length
    `lens` mm, 36 mm sensor fitted to the width. Use the spec's `views` so the comparison is never framed after seeing
    the result. Restores the scene."""
    cam_data = bpy.data.cameras.new("qa_cam")
    cam_data.lens = lens
    cam_data.clip_start = 0.05
    direction = Vector(target) - Vector(pos)
    rot = direction.to_track_quat("-Z", "Y").to_matrix().to_4x4()
    return _render(path, cam_data, Matrix.Translation(Vector(pos)) @ rot, size, color, light, wire, cull, two_sided)


def _set(obj, attr, value, saved, quiet=False):
    """Set obj.attr, remembering the old value in saved; report instead of failing when this Blender refuses it."""
    try:
        saved.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, value)
        return True
    except (TypeError, AttributeError, ValueError) as exc:
        saved.pop()
        if not quiet:
            print("[qa] %s.%s not set: %s" % (type(obj).__name__, attr, exc))
        return False


def _wire_copies(thickness):
    """Temporary near-black wireframe copies of the visible meshes in the scene (their own modifiers kept). Meshes
    inside collection instances get no wire: review a piece in its KIT file."""
    made = []
    for ob in list(bpy.context.scene.objects):
        if ob.type != "MESH" or ob.hide_render:
            continue
        dup = ob.copy()
        dup.color = (0.02, 0.02, 0.02, 1.0)
        mod = dup.modifiers.new("qa_wire", "WIREFRAME")
        mod.thickness = thickness
        mod.use_even_offset = True
        bpy.context.scene.collection.objects.link(dup)
        made.append(dup)
    return made


def _eevee_id(scene):
    """EEVEE's render engine identifier in this Blender. RenderSettings' enum_items under-reports (Blender 5.2.2 lists
    only BLENDER_EEVEE, measured 2026-10-18), so the full list comes from the TypeError an unknown name raises; the
    failed assignment leaves the engine as it was."""
    ids = [i.identifier for i in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    try:
        scene.render.engine = "QA_NO_SUCH_ENGINE"
    except TypeError as exc:
        ids += re.findall(r"'([A-Za-z0-9_]+)'", str(exc).split("not found in", 1)[-1])
    eevee = next((i for i in ids if "EEVEE" in i.upper()), None)
    if eevee is None:
        raise RuntimeError("--light lookdev needs EEVEE; this Blender offers %s" % ", ".join(dict.fromkeys(ids)))
    return eevee


def _lookdev_rig(scene, matrix, saved):
    """For --light lookdev: EEVEE, a neutral grey world, the scene's own lights hidden from the render (lights inside
    collection instances stay on) and one sun from behind the camera's left (LOOKDEV), so every material reads under
    the same light with its own nodes (roughness, metallic and normal maps included, which Workbench ignores). Changes
    go through _set into saved; returns the sun object, its light data and the world, for removal once saved is
    restored."""
    import warnings
    _set(scene.render, "engine", _eevee_id(scene), saved)
    world = bpy.data.worlds.new("qa_lookdev_world")
    g = LOOKDEV["world"]
    world.color = (g, g, g)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)    # use_nodes is deprecated in Blender 5.x
        try:
            world.use_nodes = True
        except (AttributeError, TypeError):
            pass
    bg = next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None) if world.node_tree else None
    if bg is not None:
        bg.inputs[0].default_value = (g, g, g, 1.0)
        bg.inputs[1].default_value = 1.0
    _set(scene, "world", world, saved)
    for ob in scene.objects:
        if ob.type == "LIGHT" and not ob.hide_render:
            _set(ob, "hide_render", True, saved)
    sun_data = bpy.data.lights.new("qa_lookdev_sun", "SUN")
    sun_data.energy = LOOKDEV["sun"]
    sun = bpy.data.objects.new("qa_lookdev_sun", sun_data)
    scene.collection.objects.link(sun)
    el, az = math.radians(LOOKDEV["elevation"]), math.radians(LOOKDEV["azimuth"])
    # towards the light in camera space (x right, y up, z back towards the viewer), then in world space
    to_light = matrix.to_3x3() @ Vector((-math.cos(el) * math.sin(az), math.sin(el), math.cos(el) * math.cos(az)))
    sun.matrix_world = to_light.normalized().to_track_quat("Z", "Y").to_matrix().to_4x4()   # it shines along -Z
    _set(scene.eevee, "taa_render_samples", LOOKDEV["samples"], saved)
    return sun, sun_data, world


def _render(path, cam_data, matrix, size, color="random", light="studio", wire=None, cull=True, two_sided=()):
    """Workbench render to a PNG. random: each object its own colour with cavity and outlines, so pieces, openings
    and seams read (the default flat grey hides every edge between same-coloured faces). texture: each mesh's image
    textures through the UV layer _set_render_uv makes active (Workbench samples the ACTIVE layer), for judging
    materials; flat light shows albedo as stored, studio a
    neutral light. wire: light surfaces with near-black edges (object colours). light lookdev instead renders through
    EEVEE with each material's own nodes under _lookdev_rig (color and wire do not apply). cull: back faces hidden,
    as the engine's stock shaders hide them, so a single-sided piece wound inside out is missing here as it will be in
    the game (Workbench: the scene setting; lookdev: each editable material's, linked ones are reported). two_sided:
    material name patterns drawn from both sides under lookdev (foliage cards, cloth, glass on a two-sided shader;
    Workbench culls or draws every material alike). Standard view transform, exposure 0, 8-bit PNG. Restores the
    scene."""
    scene = bpy.context.scene
    cam = bpy.data.objects.new("qa_cam", cam_data)
    scene.collection.objects.link(cam)
    cam.matrix_world = matrix
    saved, wires, rig = [], [], None
    shading, img, vs = scene.display.shading, scene.render.image_settings, scene.view_settings
    try:
        if wire:
            wires = _wire_copies(wire)
        _set(scene, "camera", cam, saved)
        if light == "lookdev":
            rig = _lookdev_rig(scene, matrix, saved)
            refused = [m.name for m in bpy.data.materials
                       if cull and not _set(m, "use_backface_culling",
                                            not any(fnmatch.fnmatchcase(m.name, g) for g in two_sided), saved,
                                            quiet=True)]
            if refused:
                print("[qa] back faces still drawn for %d material(s) Blender will not change here (%s)"
                      % (len(refused), ", ".join(refused[:5])))
        else:
            _set(shading, "show_backface_culling", bool(cull), saved)
            _set(scene.render, "engine", "BLENDER_WORKBENCH", saved)
            _set(shading, "color_type", "OBJECT" if wire else COLORS[color], saved)
            _set(shading, "light", LIGHTS[light], saved)
            _set(shading, "show_cavity", color == "random" and not wire, saved)
            _set(shading, "show_object_outline", color == "random" and not wire, saved)
        _set(vs, "view_transform", "Standard", saved)
        if not _set(vs, "look", "NONE", saved, quiet=True):      # "NONE" in Blender 5.x, "None" before
            _set(vs, "look", "None", saved)
        _set(vs, "exposure", 0.0, saved)
        _set(vs, "gamma", 1.0, saved)
        if hasattr(img, "media_type"):
            _set(img, "media_type", "IMAGE", saved)
        _set(img, "file_format", "PNG", saved)
        _set(img, "color_mode", "RGBA", saved)
        _set(img, "color_depth", "8", saved)
        _set(scene.render, "resolution_x", size[0], saved)
        _set(scene.render, "resolution_y", size[1], saved)
        _set(scene.render, "resolution_percentage", 100, saved)
        _set(scene.render, "film_transparent", cam_data.type == "ORTHO", saved)
        _set(scene.render, "use_file_extension", False, saved)
        _set(scene.render, "filepath", path, saved)
        bpy.ops.render.render(write_still=True)
    finally:
        for obj, attr, value in reversed(saved):
            try:
                setattr(obj, attr, value)
            except (TypeError, AttributeError, ValueError):
                pass
        for dup in wires:
            bpy.data.objects.remove(dup)
        if rig is not None:                          # after saved is restored: the scene no longer uses the world
            sun, sun_data, world = rig
            bpy.data.objects.remove(sun)
            bpy.data.lights.remove(sun_data)
            bpy.data.worlds.remove(world)
        bpy.data.objects.remove(cam)
        bpy.data.cameras.remove(cam_data)
    return path


def overlay_svg(render_png, reference, out_svg, opacity=0.5, size=None):
    """An SVG that lays a reference drawing over a render at the same scale, for any browser to open. A reference
    SVG with a data-frame attribute (spec_to_svg output) is cropped to its drawn area; a PNG is stretched to the
    render. The render must cover the same world area: a plan's zone bounds, an elevation's width x height."""
    w, h = size or tuple(bpy.data.images.load(render_png, check_existing=True).size[:])
    def rel(p):
        try:
            return os.path.relpath(os.path.abspath(p), os.path.dirname(os.path.abspath(out_svg))).replace("\\", "/")
        except ValueError:  # Windows: different drives have no relative path
            return "file:///" + os.path.abspath(p).replace("\\", "/").lstrip("/")
    ref = '<image href="%s" width="%d" height="%d" opacity="%g" preserveAspectRatio="none"/>' % (
        rel(reference), w, h, opacity)
    if reference.lower().endswith(".svg"):
        with open(reference, encoding="utf-8") as f:
            head = f.read(4000)
        frame = re.search(r'data-frame="([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+)"', head)
        full = re.search(r'<svg[^>]* width="([\d.]+)" height="([\d.]+)"', head)
        if frame and full:
            fx, fy, fw, fh = frame.groups()
            ref = ('<svg width="%d" height="%d" viewBox="%s %s %s %s" preserveAspectRatio="none" opacity="%g">'
                   '<image href="%s" width="%s" height="%s"/></svg>'
                   % (w, h, fx, fy, fw, fh, opacity, rel(reference), full.group(1), full.group(2)))
    with open(out_svg, "w", encoding="utf-8") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d">'
                '<rect width="100%%" height="100%%" fill="#fff"/><image href="%s" width="%d" height="%d"/>%s</svg>\n'
                % (w, h, rel(render_png), w, h, ref))
    return out_svg


# ---- command line -------------------------------------------------------------------------------------------------

def _set_render_uv(layer=None):
    """Workbench texture renders sample each mesh's ACTIVE UV layer, not its active render layer (measured in Blender
    5.2.2). Point every mesh's active layer at `layer` (a name or index), or by default at its active render layer:
    the one exports and bakes use. Returns [(mesh, old active index)] to restore."""
    saved = []
    for me in bpy.data.meshes:
        uvs = me.uv_layers
        if not len(uvs):
            continue
        if layer is None:
            target = next((i for i, l in enumerate(uvs) if l.active_render), None)
        elif layer.isdigit():
            target = int(layer) if int(layer) < len(uvs) else None
        else:
            target = next((i for i, l in enumerate(uvs) if l.name == layer), None)
        if target is None or target == uvs.active_index:
            continue
        try:
            old = uvs.active_index
            uvs.active_index = target
            saved.append((me, old))
        except (AttributeError, TypeError, RuntimeError) as exc:     # linked mesh data may refuse
            print("[qa] cannot switch the UV layer of %s: %s" % (me.name, exc))
    return saved


def _stats_text(s):
    return ("mean %s, min %s, max %s (0-255), luma p1/p50/p99 %s/%s/%s, clipped %s, crushed %s, coverage %s"
            % (s["mean"], s["min"], s["max"], s["luma_p1"], s["luma_p50"], s["luma_p99"], s["clipped_share"],
               s["crushed_share"], s["coverage"]))


def _expand(ap, flag, args):
    """Expand globs here, so the same command works in PowerShell, cmd and bash."""
    out = []
    for arg in args or []:
        if any(ch in arg for ch in "*?["):
            hits = sorted(glob.glob(arg))
            if not hits:
                ap.error("%s: %s matches no file" % (flag, arg))
            out += hits
        else:
            out.append(arg)
    return out


def _args(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="qa_measure.py")
    ap.add_argument("--module", type=float, help="the spec's grid.module in metres; required on any run that opens a "
                    ".blend or imports FBX (Size and grid checks use it)")
    ap.add_argument("--sub-module", type=float, help="grid.sub_module: the grid step for TRIM-family placements")
    ap.add_argument("--json", help="write the full report here")
    ap.add_argument("--role", choices=ROLES, help="file role; default from the file name (KIT_*, ASM_*, MASTER*)")
    ap.add_argument("--piece-tris", help='JSON {family or piece: max LOD0 tris}, e.g. {"EXT": 800, '
                    '"EXT_Door_2x3_A": 400}; a piece entry wins over its family')
    ap.add_argument("--expect-status", choices=STATUS_ORDER, help="the kit_status this stage sets: local pieces must "
                    "carry it, linked pieces at least it, and the n-gon and empty-slot rules apply from it")
    ap.add_argument("--pieces", help="comma-separated piece names or globs this task touched (a task split by "
                    "piece): piece checks skip the others")
    ap.add_argument("--probe-lit", help="comma-separated piece names or globs the spec marks lightmap: false, and "
                    "LOD objects that are probe-lit (<Piece>_LOD[1-9] for a piece with lod_lightmap: false): they still "
                    "need a UV2, but its overlaps and gaps are not checked; a value that matches nothing is a PROBLEM")
    ap.add_argument("--compare-placements", metavar="JSON", help="a previous qa_measure report of this file: list "
                    "every placement moved, rotated, swapped, added or removed since")
    ap.add_argument("--lightmap-texels", type=float, metavar="TPM", help="report each mesh's lightmap footprint in px: "
                    "TPM x sqrt(area / b) x --lightmap-scale x 0.5^n for a *_LOD<n> mesh, b = its UV2 bounding-box "
                    "share (%g before UV2 exists); with --lightmapper bakery, (TPM x sqrt(2 x area x --lightmap-scale) "
                    "- %d) / the UV2 box's short side, no LOD factor" % (LIGHTMAP_COVERAGE, 2 * BAKERY_INSET_TEXELS))
    ap.add_argument("--lightmap-scale", default="1", help="Scale In Lightmap for --lightmap-texels: one number, or "
                    'JSON {piece: scale} from the spec\'s pieces[].lightmap_scale (others 1), e.g. {"EXT_Trim_2_A": 0.5}')
    ap.add_argument("--lightmapper", default="unity", choices=("unity", "progressive", "bakery"), help="the spec's "
                    "lighting.baker: whose footprint --lightmap-texels uses (progressive is unity); bakery also gates "
                    "each mesh's effective texels per metre (default unity)")
    ap.add_argument("--families", type=json.loads, metavar="JSON", help="the spec's families as JSON: every "
                    "placement of a tiling family's piece is checked against the world tile grid (U7), a floor: true "
                    "family's two-number Sizes read as floors (X by Y, relief free), scale_range bounds Free scales")
    ap.add_argument("--texel-map", type=int, metavar="PX", help="the family's map_px: report each mesh's UV0 texel "
                    "density in px/m")
    ap.add_argument("--import-fbx", nargs="+", metavar="FBX", help="import these FBX files first (E2-E4), each "
                    "into a collection named after it, then measure them as pieces; globs are expanded here")
    shot = ap.add_mutually_exclusive_group()
    shot.add_argument("--render", choices=sorted(VIEWS), help="orthographic render (needs --center, --extent, --png)")
    shot.add_argument("--view", type=float, nargs=7, metavar=("PX", "PY", "PZ", "TX", "TY", "TZ", "LENS"),
                      help="perspective render from a spec view: pos, target and lens (needs --png)")
    ap.add_argument("--center", type=float, nargs="+", help="ortho: centre of the framed area, x y [z]")
    ap.add_argument("--extent", type=float, nargs=2, help="ortho: width and height of the framed area in metres")
    ap.add_argument("--px-per-m", type=float, default=None, help="ortho scale; default the overlay SVG's "
                    "data-px-per-m, else 20")
    ap.add_argument("--clip", type=float, help="ortho only: draw only geometry from this many metres in front of "
                    "the centre plane onward (an interior wall from inside the room)")
    ap.add_argument("--color", choices=sorted(COLORS), default="random", help="random: object colours and outlines "
                    "(layout); texture: image textures (materials, stages 7+)")
    ap.add_argument("--uv-layer", metavar="NAME|INDEX", help="texture renders: the UV layer to draw through (Workbench "
                    "samples each mesh's ACTIVE layer); default each mesh's active render layer, restored afterwards")
    ap.add_argument("--light", choices=sorted(LIGHTS), default="studio", help="flat: albedo as stored; studio: "
                    "neutral light (both Workbench, which draws base colour only); lookdev: EEVEE with each "
                    "material's own nodes (roughness, metallic and normal maps), a grey world and one key light")
    ap.add_argument("--wire", nargs="?", type=float, const=-1.0, metavar="M", help="wireframe render: light surfaces, "
                    "near-black edges M metres thick (default about 1.5 px)")
    ap.add_argument("--no-cull", action="store_true", help="draw back faces too (renders cull them by default, as "
                    "the engine's stock shaders do, so an inside-out single-sided piece shows as missing; a --clip "
                    "section always draws them)")
    ap.add_argument("--two-sided", default="", metavar="GLOBS", help="comma-separated material name patterns drawn "
                    "from both sides under --light lookdev, as their two-sided shader does in the engine (\"M_FOL_*\")")
    ap.add_argument("--lod", type=int, default=0, help="render this LOD; the others are hidden (default 0)")
    ap.add_argument("--show-collision", action="store_true", help="render *_COL shells (hidden by default)")
    ap.add_argument("--hide-object", nargs="+", default=[], metavar="GLOB", help="hide objects whose names match")
    ap.add_argument("--hide-collection", nargs="+", default=[], metavar="NAME",
                    help="hide these collections in renders (e.g. REF for gate and G4 views)")
    ap.add_argument("--isolate", metavar="COLLECTION", help="render only this collection's objects (one KIT piece)")
    ap.add_argument("--png", help="render output (an absolute path is safest)")
    ap.add_argument("--overlay", help="ortho: SVG (spec_to_svg) or PNG to lay over the render")
    ap.add_argument("--overlay-out", help="overlay SVG path; default <png>.overlay.svg")
    ap.add_argument("--tile-seam", nargs="+", metavar="PNG", help="seam metric for tiling textures (X4)")
    ap.add_argument("--image-stats", nargs="+", metavar="PNG", help="pixel mean, min, max, luma percentiles, clipped "
                    "and crushed shares and coverage of images")
    ap.add_argument("--pbr", nargs="+", metavar="PNG", help="PBR value checks of texture maps (X8), paired by name: "
                    "T_<FAMILY>_<Name>_BaseColor, _MetallicSmoothness and _Normal; globs are expanded here")
    ap.add_argument("--map-px", type=int, metavar="PX", help="with --pbr: the family's map_px, the same number as "
                    "--texel-map (a larger map is a PROBLEM)")
    ap.add_argument("--pbr-tiling", action="store_true", help="with --pbr: judge the maps as tiling (X4): a seam "
                    "along part of a wrap edge, tile-scale variation that draws a grid")
    ap.add_argument("--pbr-trim", action="store_true", help="with --pbr: a trim sheet, judged along U only (X4)")
    ap.add_argument("--pbr-targets", metavar="JSON", help="with --pbr: the spec's look.materials as JSON, e.g. "
                    '{"M_EXT_Brick": {"albedo_srgb": [60, 150], "roughness": [0.6, 0.95], "metal": false}}')
    ap.add_argument("--gain", type=float, help="with --image-stats or a render: also save a copy brightened this "
                    "many times as <name>_x<gain>.png")
    a = ap.parse_args(argv)
    if a.module is None and (bpy.data.filepath or a.import_fbx):
        ap.error("--module is required on a .blend or FBX run: pass the spec's grid.module in metres (Size and grid "
                 "checks use it; there is no safe default)")
    if a.module is not None and a.module <= 0:
        ap.error("--module must be a positive number of metres")
    try:
        a.lightmap_scale = float(a.lightmap_scale)
    except ValueError:
        try:
            a.lightmap_scale = {k: float(v) for k, v in json.loads(a.lightmap_scale).items()}
        except (ValueError, AttributeError, TypeError):
            ap.error("--lightmap-scale takes a number or JSON {piece: scale}")
    if a.piece_tris:
        try:
            a.piece_tris = json.loads(a.piece_tris)
            if not isinstance(a.piece_tris, dict) or not all(
                    isinstance(v, (int, float)) and not isinstance(v, bool) for v in a.piece_tris.values()):
                raise ValueError
        except ValueError:
            ap.error('--piece-tris takes JSON {family or piece: max LOD0 tris}, e.g. {"EXT": 800}')
    a.pieces = [p.strip() for p in a.pieces.split(",") if p.strip()] if a.pieces else None
    a.probe_lit = [p.strip() for p in a.probe_lit.split(",") if p.strip()] if a.probe_lit else None
    if a.uv_layer is not None and a.color != "texture":
        ap.error("--uv-layer works with --color texture only")
    if a.light == "lookdev" and a.wire is not None:
        ap.error("--wire works with the Workbench lights only (--light flat or studio)")
    a.import_fbx = _expand(ap, "--import-fbx", a.import_fbx)
    a.tile_seam = _expand(ap, "--tile-seam", a.tile_seam)
    a.image_stats = _expand(ap, "--image-stats", a.image_stats)
    a.pbr = _expand(ap, "--pbr", a.pbr)
    if (a.map_px or a.pbr_targets or a.pbr_tiling or a.pbr_trim) and not a.pbr:
        ap.error("--map-px, --pbr-targets, --pbr-tiling and --pbr-trim work with --pbr only")
    if a.pbr_targets:
        try:
            a.pbr_targets = json.loads(a.pbr_targets)
            if not isinstance(a.pbr_targets, dict) or not all(isinstance(v, dict) for v in a.pbr_targets.values()):
                raise ValueError
        except ValueError:
            ap.error('--pbr-targets takes JSON {material: {"albedo_srgb": [lo, hi], "roughness": [lo, hi], '
                     '"metal": true or false}}')
    if a.render and not (a.png and a.center and a.extent):
        ap.error("--render needs --png, --center and --extent")
    if a.view and not a.png:
        ap.error("--view needs --png")
    if (a.overlay or a.overlay_out) and not a.render:
        ap.error("--overlay works with --render only")
    if a.gain and not (a.image_stats or a.render or a.view):
        ap.error("--gain needs --image-stats, --render or --view")
    if a.compare_placements and not os.path.isfile(a.compare_placements):
        ap.error("--compare-placements: %s not found" % a.compare_placements)
    return a


def _main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        return
    a = _args(argv)
    # Blender resolves a relative output path against something other than the shell's working folder (it wrote
    # to C:/world/... once); make every output path absolute here, where the working folder is still known.
    for k in ("json", "png", "overlay", "overlay_out", "compare_placements"):
        if getattr(a, k):
            setattr(a, k, os.path.abspath(getattr(a, k)))
    if a.px_per_m is None:
        a.px_per_m = 20.0
        if a.overlay and a.overlay.lower().endswith(".svg"):
            with open(a.overlay, encoding="utf-8") as f:
                m = re.search(r'data-px-per-m="([0-9.]+)"', f.read(4000))
            if m:
                a.px_per_m = float(m.group(1))
    folded = []
    if a.import_fbx:
        names, folded = import_fbx(a.import_fbx)
        print("[qa] imported " + ", ".join(names))
        for copy, base in folded:
            print("[qa] folded the importer's copy %s back onto %s" % (copy, base))
    probs = []
    if bpy.data.filepath or a.import_fbx:
        rep = measure(a.module, role=a.role or ("fbx" if a.import_fbx else None), lightmap_texels=a.lightmap_texels,
                      lightmap_scale=a.lightmap_scale, sub_module=a.sub_module, texel_map=a.texel_map,
                      lightmapper=a.lightmapper, families=a.families)
        if folded:
            rep["fbx_folded_materials"] = [{"copy": c, "base": b} for c, b in folded]
        if a.compare_placements:
            with open(a.compare_placements, encoding="utf-8") as f:
                rep["placement_changes"] = compare_placements(rep, json.load(f))
        probs = problems(rep, a.piece_tris, a.expect_status, a.pieces, a.probe_lit)
        for p in rep["pieces"]:
            print("%-32s %6d tris  status=%s" % (p["piece"], p["lod0_tris"], p["kit_status"]))
        for p in rep["linked_pieces"]:
            print("%-32s %6d tris  status=%s  (linked)" % (p["piece"], p["tris"], p["kit_status"]))
        print("[qa] role %s: %d piece(s), %d linked piece(s), %d placement(s), %d librar(ies)"
              % (rep["role"], len(rep["pieces"]), len(rep["linked_pieces"]), len(rep["placements"]),
                 len(rep["libraries"])))
        for im in rep["images"]:
            print("[qa] image %-40s %sx%s ch%d %-10s %s%s%s" % (
                im["image"], im["size"][0], im["size"][1], im["channels"], im["colorspace"],
                "relative" if im["relative"] else "ABSOLUTE", " packed" if im["packed"] else "",
                " MISSING" if im["missing"] else ""))
        for p in probs:
            print("[qa] PROBLEM " + p)
        rep["notes"] = notes(rep, a.pieces, a.probe_lit)
        for n in rep["notes"]:
            print("[qa] NOTE " + n)
    else:
        rep = {"file": "", "role": None}
        print("[qa] no .blend open and no --import-fbx: scene not measured")
    rep["problems"] = probs
    if a.tile_seam:
        rep["tile_seam"] = [tile_seam(p) for p in a.tile_seam]
        for t in rep["tile_seam"]:
            print("[qa] seam %s: x %.2f, y %.2f (edge step / inner step)" % (os.path.basename(t["image"]),
                  t["ratio_x"], t["ratio_y"]))
    if a.image_stats:
        rep["image_stats"] = [image_stats(p, a.gain) for p in a.image_stats]
        for s in rep["image_stats"]:
            print("[qa] pixels %s: %s%s" % (os.path.basename(s["image"]), _stats_text(s),
                                            ("; brightened copy " + s["gain_copy"]) if s.get("gain_copy") else ""))
    if a.pbr:
        rep["pbr"] = pbr(a.pbr, a.map_px, a.pbr_targets, "x" if a.pbr_trim else a.pbr_tiling)
        for r in rep["pbr"]:
            name = r["material"] or r["key"]
            bc, ms, nm = r.get("base_color") or {}, r.get("metallic_smoothness") or {}, r.get("normal") or {}
            parts = ["maps %s" % (", ".join(sorted(r.get("maps") or {})) or "none judged")]
            if bc:
                parts.append("luma p1/p50/p99 %s/%s/%s" % (bc.get("dielectric_luma_p1"), bc.get("dielectric_luma_p50"),
                                                            bc.get("dielectric_luma_p99")))
            if ms:
                parts.append("metal %.0f%%, grey %.1f%%" % (100 * ms["metal_share"], 100 * ms["metallic_mid_share"]))
            if nm:
                parts.append("normal |n| %s, %s" % (nm["length_mean"], nm["convention"]))
            print("[qa] pbr %s: %s" % (name, "; ".join(parts)))
            for msg in r["problems"]:
                rep["problems"].append("pbr %s: %s" % (name, msg))
                print("[qa] PROBLEM pbr %s: %s" % (name, msg))
            for msg in r["notes"]:
                rep.setdefault("notes", []).append("pbr %s: %s" % (name, msg))
                print("[qa] NOTE pbr %s: %s" % (name, msg))
    hidden, uv_saved = [], []
    if (a.view or a.render) and a.color == "texture" and a.light != "lookdev":
        uv_saved = _set_render_uv(a.uv_layer)
    shown = contextlib.ExitStack()
    if (a.view or a.render) and a.isolate and bpy.data.collections.get(a.isolate) is not None:
        shown.enter_context(_evaluated([bpy.data.collections[a.isolate]]))   # a single MASTER excludes KIT
    if a.view or a.render:
        try:
            out = render_hidden(a.lod, a.show_collision, a.hide_object, a.isolate, a.hide_collection)
        except ValueError as exc:
            sys.exit("[qa] %s" % exc)
        for ob in out:
            if not ob.hide_render:
                try:
                    ob.hide_render = True
                    hidden.append(ob)
                except (AttributeError, TypeError, RuntimeError) as exc:
                    print("[qa] cannot hide %s: %s" % (ob.name, exc))
    try:
        wire = None
        two_sided = [g.strip() for g in a.two_sided.split(",") if g.strip()]
        if a.wire is not None:
            wire = a.wire if a.wire > 0 else (1.5 / a.px_per_m if a.render else
                                              0.0025 * (Vector(a.view[3:6]) - Vector(a.view[0:3])).length)
        try:
            if a.view:
                render_view(a.png, a.view[0:3], a.view[3:6], a.view[6], color=a.color, light=a.light, wire=wire,
                            cull=not a.no_cull, two_sided=two_sided)
            elif a.render:
                render_ortho(a.png, a.render, a.center, a.extent, a.px_per_m, clip=a.clip, color=a.color,
                             light=a.light, wire=wire, cull=not a.no_cull and a.clip is None, two_sided=two_sided)
        except RuntimeError as exc:                  # no EEVEE for --light lookdev
            sys.exit("[qa] %s" % exc)
        if a.view or a.render:
            stats = image_stats(a.png, a.gain)
            rep["renders"] = [stats]
            print("[qa] rendered %s: %s" % (a.png, _stats_text(stats)))
        if a.render and a.overlay:
            size = (max(16, int(round(a.extent[0] * a.px_per_m))), max(16, int(round(a.extent[1] * a.px_per_m))))
            print("[qa] overlay " + overlay_svg(a.png, a.overlay, a.overlay_out or a.png + ".overlay.svg",
                                               size=size))
    finally:
        for ob in hidden:
            ob.hide_render = False
        for me, index in uv_saved:
            me.uv_layers.active_index = index
        shown.close()
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)


if __name__ == "__main__":
    _main()
