# uv_audit.py: the manual

`scripts/uv_audit.py` measures a UV layout and changes it in the one safe order. Host: Blender 4.1+ with its bundled
numpy (tested on Blender 5.2.2, 2026-10-17), no add-ons. The measuring maths (`measure`, `measure_shared`,
`footprint_px`, `uv_box_share`) also runs in plain Python with numpy, without Blender.

Every function works on UV0 unless given another layer (an index, a name, or `"active"` for whichever map is active);
the lightmap calls (`pack_lightmap`, `lightmap_footprint`, and `audit` for a lightmap) default to the second map,
index 1. Every function leaves the active UV map, the selection and the mode as it found them.

## Contents

- Functions
- Purposes: which checks apply
- Report fields
- Issues: what each means and what to do
- Accuracy and limits
- What it reads and what it changes
- Command line

## Functions

| Call | What it does |
|---|---|
| `apply_stack(ob, keep_mirror=True, add_triangulate=False)` | step 1 of the order of work. Applies the modifier stack from the top, in stack order, down to and including the last modifier that changes topology (`TOPOLOGY_TYPES`: Bevel, Mirror, Array, Subdivision, Solidify, Boolean, Weld and the like, and any Geometry Nodes modifier but Smooth by Angle; a Smooth by Angle above it goes too), never a lower one alone. Stops at the stack's Triangulate: it stays unapplied and off in the viewport until after `layout`. Mirrors at the end of the run (nothing but Mirrors changes topology below them) stay live with `keep_mirror=True`; call again with `keep_mirror=False` just before `layout`. `add_triangulate=True` gives a piece with no Triangulate one (Minimum Vertices 4, Keep Normals) directly above any Weighted Normal. Returns `hard_surface` (checked before applying anything), `shading_designed`, `applied`, `mirrors_live`, `triangulate`. Raises, changing nothing, for a topology change below the Triangulate (move the Mirror or Array above the Triangulate, first in the stack), a modifier off in the viewport, shape keys, or a mesh shared with other objects (apply on a single-user copy, point the others at its mesh, remove their applied modifiers). Run it before applying scale, the same as `blender-mesh-topology`'s hand-off (a repo test runs both on 15 stacks) |
| `hard_surface_stack(ob)` | True for a Weighted Normal, a Bevel with Harden Normals, or custom normals in the mesh: never shade it by angle again |
| `seams_by_angle(objs, angle=30.0)` | a seam on every edge whose faces meet at more than `angle` deg, from the mesh itself: what `mesh.edges_select_sharp` then `mesh.mark_seam` do, without touching the selection or the normals. The seam rule on a hard-surface stack. It places seams; it does not find hard edges |
| `audit(ob, layer=None, map_px=None, pad_px=None, px_per_m=None, purpose="unique", baking=False, directional=False, text=False, material=None, rows=None, texels_per_m=None, lightmap_scale=1.0, lod=None, lightmapper="unity")` | measures one object's UV map on the evaluated mesh in world space; changes nothing. `layer`: 0, or 1 for a lightmap. `map_px`: `1024` (the default for textures), `(2048, 1024)`, `"2048x1024"` or a lightmap footprint (fractions round down). `texels_per_m` or `lightmap=True` makes it a lightmap audit (with another purpose either raises); without `map_px`, a lightmap is audited at the footprint of its measured UV2 box at `texels_per_m` x `lightmap_scale` x 0.5^n, n = `lod` or read from a `<Piece>_LOD<n>` name. `lightmapper="bakery"` (or `"unity"`, `"progressive"`): Bakery's footprint of the measured box instead, `(texels_per_m x sqrt(2 x area x lightmap_scale) - 6) / the box's short side`, no LOD factor, and an issue when the charts get under half the planned density (engine notes). `material`: only the faces whose material name matches (a name or an fnmatch pattern; raises when none does), for a mesh that mixes tiling, trim and unique materials. `text=True` checks the faces marked `uv_text` and raises when none is `tile_m` (tiling only), `steps`, `tile_offset`: also each face against `tile_project`'s scale and phase and the steps as whole numbers of tiles (`tile_phase` in the report) |
| `audit_selected(**kw)`, `audit_objects(objs, report_path=None, **kw)` | the same per selected mesh or per object: one printed line each, the full reports as JSON when `report_path` is given. With `material=`, meshes without that material are skipped; with `text=True`, meshes without `uv_text` faces are audited without the text check (it raises when no mesh has any) |
| `audit_shared(objs, layer=None, map_px=1024, pad_px=None, purpose="unique", material=None)` | objects that share one texture (an atlas): overlaps and gaps between their islands. Tiling and trim layers may overlap: nothing is checked for them |
| `layout(objs, map_px, px_per_m=None, pad_px=None, layer=0, directional=True, rotate_method="CARDINAL", bake=False, together=False, material=None, max_island_m=None, low_factor=None)` | step 8 of the order of work: density (islands marked `uv_low_density` keep their relative size, or with `low_factor` go to that share of `px_per_m`), stacks set apart from everything else, one pack that keeps stacks, sizes and orientation, a fit check, then for a bake the +1 U copies and the flipped halves of merged mirror islands. Returns per object `factor`, `fits` (False when an island leaves the tile or sits closer to its edge than half the gap: `margin_px`, `fit_problem`), `islands`, `stacks`, `copies_moved`, `mirror_halves_moved`, `islands_cut`. `together=True` for an atlas. `material`: every step on that material's faces only (a name or a pattern); the others keep their UVs and objects without it are skipped: one material's bake atlas across several meshes. `max_island_m`: bake atlases only; islands longer than this (metres) are cut into pieces by face centre, moved but never turned or scaled, so one long shell does not cap the atlas's scale (each cut is a seam the bake margin covers; a tiling or painted texture would show it) |
| `pack(objs, map_px=1024, pad_px=None, layer=0, scale=True, rotate=False, rotate_method="CARDINAL", together=False, shape="CONCAVE", keep_stacks=False, material=None)` | one Blender pack with the gap in pixels (default `map_px / 64`); rotation off unless asked. `material`: only those faces are packed (the others are hidden for the pack, then shown again, and keep their UVs) |
| `pack_lightmap(objs, texels_per_m, scale=1.0, layer=1, rotate=True, lod=None, notes=None, lightmapper="unity")` | packs the lightmap UV with a 2 px gap at `texels_per_m x sqrt(area) x scale x 0.5^n` px, the smallest texel scale it can get (b = 1), so 2 texels hold at any real footprint; the charts fill their box. `scale` may be a dict per object name; n is read from each `<Piece>_LOD<n>` name unless `lod` is given. Too small for 2-texel gaps (under `lightmap_capacity_px(charts)`, or under 64 px with a pack that misses them): packed for 64 px instead, never left to spill; the note is printed and stored in `notes` (a dict you pass). `lightmapper="bakery"`: packs at `texels_per_m x sqrt(2 x area x scale) - 6` px (Bakery's rect with the box filling the tile, less its Default packer's inset; xatlas has none, so the gaps hold under both), no LOD factor; the Scale In Lightmap factor in the note is on the area. Returns the size packed for |
| `lightmap_capacity_px(charts)` | the smallest b = 1 footprint that can hold that many charts 2 texels apart and 1 from the edge: 2 x ceil(sqrt(charts)) (6 charts: 6 px), the same bound as `rizomuv-uv-pipeline` |
| `lightmap_footprint(ob, texels_per_m, scale=1.0, coverage=0.85, measured=False, layer=1, lod=None, lightmapper="unity")` | the lightmap texel scale in texels per UV unit, rounded down: b = 0.85 for planning, `measured=True` reads b (the box of all the UV2 charts) from the UV2, `coverage=1.0` gives the packing size; x 0.5^n for LOD n. `lightmapper="bakery"`: Bakery's, the box's short side sqrt(b) when planning or measured from the UV2, no LOD factor |
| `lod_level(name)` | n of a `<Piece>_LOD<n>` name (a `.001` suffix allowed), else 0 |
| `set_texel_density(objs, px_per_m, map_px, layer=0, per_island=True, pack_after=True, pad_px=None, keep_stacks=False, rotate=False, material=None, low_factor=None)` | scales islands to the density, then packs with `scale=False`; `layout` is the safer call. On a non-square trim sheet ("2048x1024"), which `layout` and `pack` refuse, call it with `pack_after=False` and place the strips on their rows. `material=`: only those faces (with `pack_after=False`; the others keep their UVs) |
| `tile_project(objs, tile_m, layer=0, material=None, offset=(0, 0, 0))` | tiling UVs for kit pieces: a box projection from each piece's own axes (scale applied), one tile per `tile_m` metres, phase 0 at the pivot, U to the right seen from the front of each face and V up (Z on walls, +Y on floors and ceilings), so pieces on a grid whose step is a whole number of tiles continue the pattern across joints (walls turned in 90 deg steps too; floors and ceilings only unturned, since their pattern turns with them). Each face's plane from its own positions (Newell), 45 deg ties broken Z, X, Y; a negative scale is refused. Use it instead of Cube Projection, which centres on the selection (5.2.2: a 1 m wall started at U 0.375 and a 2 m wall at 0.25 with `cube_size` 4). `offset`: a phase variant, projected as if the piece stood that far along. Returns faces written per object |
| `tile_uv(p, n, tile_m)`, `tile_phase(d, tile_m, map_px, frame=None, steps=None, offset=(0, 0, 0))`, `tile_steps_issues(tile_m, steps)` | the maths behind it, without bpy: the projection, a layout's distance from it per face (faces marked `uv_strip`, a curve unwrapped as a strip, are left to the seam check: `strip_faces`), placement steps that are not whole numbers of tiles |
| `straighten(objs, layer=0, material=None)` | step 6 for strips: every all-quad island's most rectangular quad squared to its 3D sides at the island's density, turned to the nearest of U or V, then Follow Active Quads (`LENGTH`) from it; islands with a triangle or an n-gon are skipped and counted. Returns per object `straightened`, `skipped` |
| `turn_islands(objs, map_px=1024, layer=0, material=None)` | turns every long island whose long side runs along V by 90 deg about its centre, in square pixels of `map_px` (a non-square sheet stays undistorted): for trim strips no single GEOMETRY axis lays along U. `material=`: only those faces, so a mesh's tiling faces stay as projected. Check a profiled strip's top side afterwards |
| `pair_faces(ob, src_faces, offset, tol=None)` | the faces of a copy in `src_faces`' order: each source face's partner is the face whose centre sits at its centre + `offset` (object space). For Array copies once a Bevel below them is applied: `stack_faces(ob, src, pair_faces(ob, src, (0, 0, step)))`. Raises when a face has no partner |
| `stack_faces(ob, src_faces, dst_faces, layer=0)` | stacks a duplicated part exactly: copies UVs face by face, corner by corner, in order. First fits the copy's corners to the source's by a rotation and a move (no scaling, no mirroring): if any corner is off by more than 1/10000 of the part's size (plus float rounding), or a face pair has different corner counts, it raises naming the pair and the likely causes, and writes nothing. The causes: a mirrored copy (keep the Mirror modifier live instead), a scaled copy (even 1.001x), or faces re-ordered after duplicating (Array copies once a Bevel below them is applied: pair them with `pair_faces`; a Bevel applied after a `bmesh.ops.duplicate` copy, while Shift+D and joined object copies kept their order; a Triangulate: stack before triangulating) |
| `seams_from_hard_edges(objs, clear=False)` | a seam on every hard edge (split corner normals); returns the count per object |
| `measure(d, ...)`, `measure_shared(named, ...)`, `footprint_px(area_m2, texels_per_m, scale, coverage)`, `uv_box_share(uv)`, `corner_misfit(P, Q)` | the maths behind them, without bpy |

## Purposes: which checks apply

| Check | `unique` (default) | `tiling` | `trim` | `lightmap` |
|---|---|---|---|---|
| Distortion gate, folded faces, zero-area faces | yes | yes | yes | yes |
| Density band against `px_per_m` | 0.8-1.25x on the mean and every island not marked `uv_low_density` | 0.9-1.1x on the mean and every island | 0.9-1.1x on the mean and every island | 0.8-1.25x on the mean |
| `texel_cv` <= 0.15 | yes | yes | yes | yes |
| Bounds | islands stay in the 0-1 tile; whole-tile copies of an island inside it (the +1 U bake copies) are fine | none | none | every UV inside 0-1 |
| Partial overlaps | issue | not checked | not checked | issue |
| Exact stacks | allowed (one island for the gap check); with `baking=True`, an issue inside 0-1 | not checked | not checked | issue |
| Gap between islands when `pad_px` is not given | `map_px / 64` | none | none | 2 texels |
| Gap to the tile edge | half the gap | none | none | half the gap |
| Long islands along V (islands holding `uv_text` faces are left out) | with `directional=True` | with `directional=True` | always | no |
| Text faces (`uv_text`) mirrored, or their up off +V | with `text=True` | with `text=True` | with `text=True` | no |
| Rows (`rows=`) | if given | if given | if given | if given |
| Scale and phase against `tile_project`, steps as whole tiles (`tile_m=`, `steps=`) | no | if given | no | no |
| Charts across a hard edge or a bend over 88 deg | reported only | reported only | reported only | issue |
| Charts filling under half their bounding box (`uv2_box_fill` < 0.5), at footprints of 64 px or more | no | no | no | a note, not an issue |
| `lightmapper="bakery"`: effective density under half the planned `texels_per_m x min(1, sqrt(lightmap_scale))`, at footprints of 64 px or more | no | no | no | an issue (replaces the fill note): pack the charts to fill their box, or raise the scale and pack again |
| Footprint under 64 px | no | no | no | gaps, edge and bounds checked as packed for 64 px, with a note (probe-light a Free prop; a LOD follows its piece; else raise its scale) |
| Hard edges not on seams | with `baking=True` | with `baking=True` | with `baking=True` | with `baking=True` |

`lightmap=True` (CLI `--lightmap`) and `texels_per_m` (`--lightmap-texels`) each make it a lightmap audit, which
reads the second UV map unless `layer` says otherwise and needs `map_px` or `texels_per_m`. Either one with another
purpose raises (exit 2 on the command line) rather than one of them being ignored.

`directional` applies to every object in a call: audit directional and non-directional props in separate runs (a
round bollard in a directional run reports its long islands), or one material at a time with `material=`.

Text and decals are checked on the faces marked with the boolean face attribute `uv_text` (`uv_text_<UV map name>`
for one map), never on the whole object, so a mirrored strip or a grain-oriented post next to a sign is not judged
as text. On those faces: no island mirrored, and the letters' up within 45 deg of +V. Up is world +Z unless the face
vector attribute `uv_text_up` (object space, one per face) says otherwise: set it for letters turned up a pillar
(the pillar's horizontal reading direction turned 90 deg, i.e. the direction the letters' tops point), a label
wrapped round a pipe, or text on a horizontal face (a floor marking, a desk plaque), where +Z has no direction in the
face and the island is reported as flat until given one. Text islands skip the grain check: a portrait poster may
run along V.

## Report fields

| Field | Meaning |
|---|---|
| `object`, `layer`, `layers`, `purpose`, `map_px`, `pad_px` | what was measured and with which settings (after defaults) |
| `footprint_px`, `uv2_box_share`, `graded_at_px` | lightmap audits without `map_px`: the texel scale (px per UV unit, LOD factor included), its measured b (the bounding box of all the UV2 charts together as a share of the tile), and the size the layout was checked at (64 when the footprint is smaller) |
| `lod`, `uv2_box_fill`, `effective_texels_per_m`, `lightmapper` | lightmap audits: the LOD level used; the charts' area over their box's area; `texels_per_m` x scale x 0.5^n x sqrt(fill), the density the charts really get (Bakery: the footprint x sqrt(charts' UV area / surface area)); whose footprint it used |
| `notes` | worth a look but not a failure: a lightmap footprint under 64 px (checked as packed for 64 px: probe-light a Free prop, a Free-sized PROP or FOL piece; a LOD follows its piece; else raise its Scale In Lightmap), or at 64 px or more, charts filling under half their box (the empty space costs atlas texels: pack them to fill it, at any aspect ratio) |
| `faces`, `islands` | counts; an island is faces joined across edges whose UVs match |
| `angular_p95`, `angular_p99`, `angular_max`, `area_p95` | the distortion gate (SKILL.md section 4) |
| `islands_distorted`, `worst_islands` | islands holding at least 0.5% of the area (`ISLAND_MIN_SHARE`) whose own angular p95 or area p95 is over the limit, worst first (`island`, `area_share`, `angular_p95`, `area_p95`): a small label stretched 1.45x passes the object's numbers |
| `text_angular_p95` | angular p95 over the faces marked `uv_text` together (None without them): over 1.15 the letters read squashed, whatever `text=` says |
| `area_max` | log2 of the worst non-sliver face's density against its island's (`uv_low_density` faces left out): over 2.0 a patch reads blurred or oversharp (a label shrunk to 1/8 inside its panel measured 6.0 while slivers round it took the stretch) |
| `seam_phase_px_max`, `seams_off_phase` | tiling only: over the UV seams inside a continuing surface (faces within 30 deg, `SEAM_CONTINUES_DEG`, or two `uv_strip` faces within 60 deg, `STRIP_FOLD_DEG`), how far each opens from a whole number of tiles, in texels, and how many open by more than half a texel: a ring that does not close or a strip off its neighbour's phase (a 0.1-tile closure is 102 px at 1024) |
| `limits_overridden` | the overrides an audit ran with (`limits=`, CLI `--limits`): `gate(limits)` merges a dict of any of `angular_p95`, `angular_p99`, `angular_max`, `area_p95`, `area_max`, `texel_cv`, `island_min_share`, `tile_phase_px`, `seam_continues_deg` over the defaults; `float("inf")` switches one off; a misspelt key raises. For a piece whose look needs it (a stylised prop drawn stretched, a density graded on purpose); the report carries the overrides so a reviewer sees them |
| `tile_phase` | with `tile_m`: `tile_m`, `faces`, `phase_px_max` (the worst face's distance from tile_project's UVs after whole tiles, in texels, counting a corner whose offset differs from the face's first corner), `off_faces`, `mirrored_faces` |
| `folded_faces` | faces flipped inside an otherwise unflipped island: always a fault |
| `mirrored_islands` | whole islands flipped: mirrored geometry, fine for painting; text on them reads backwards |
| `mirror_stacks` | islands whose two mirrored halves lie on each other (a Mirror modifier, or one applied with Merge on) |
| `zero_area_uv_faces` | faces collapsed to a line or a point in UV |
| `outside_0_1` | share of UV coordinates outside 0-1 |
| `islands_off_tile` | islands outside the tile that are not whole-tile copies of an island inside it: they did not fit |
| `texel_px_per_m`, `texel_cv`, `texel_island_range` | mean density, spread between islands, lowest and highest island; faces marked `uv_low_density` left out |
| `islands_off_density` | unique, tiling and trim with `px_per_m`: islands outside the band (marked islands left out) |
| `text_faces` | faces marked `uv_text` |
| `text_islands_mirrored`, `text_islands_not_upright`, `text_islands_flat` | with `text=True`, islands holding `uv_text` faces: mostly mirrored; whose letters' up (`uv_text_up`, default +Z) is not within 45 deg of +V; whose text faces all lie across their up direction (no up to check) |
| `material` | the `material=` filter, when given |
| `island_boxes_px`, `island_px_per_m` | per island: its pixel box `[x0, y0, x1, y1]` (whole-tile offsets kept) and its px/m (None when all its faces are marked) |
| `elongated_islands`, `elongated_along_v` | islands at least 1.5x longer than wide, and those whose long side runs along V |
| `islands_across_rows` | islands whose V range leaves every row of `rows` |
| `chart_bends` | edges inside a chart (continuous UVs) that are hard (corner normals over 0.5 deg apart) or bend more than 88 deg; a bend between faces under 1/100 of a texel each (a triangulated bevel-corner quad at a lightmap's scale) is not counted |
| `low_density_faces`, `low_density_px_per_m` | faces marked `uv_low_density` and their density |
| `hard_edges_not_seams` | hard edges (split normals) whose UVs are continuous |
| `margin_px` | distance to the tile edge, measured on the islands inside the tile |
| `coverage`, `overlap_px`, `raster_scale` | share of the tile covered, pixels claimed by two islands, raster pixels per texture pixel (unique and lightmap only) |
| `stacked_island_pairs`, `overlapping_island_pairs` | exact stacks (mirror-stack halves included), partial overlaps |
| `padding_ok`, `min_gap_px` | the gap check: `min_gap_px` is set when a gap is below `pad_px` |
| `issues` | what needs a look; empty means OK |

## Issues: what each means and what to do

| Issue | Meaning | Do |
|---|---|---|
| `angular stretch p95 x` or `p99 x` | shapes distorted over 5% or 1% of the area | seams on the stretched band, unwrap again |
| `a face stretched x` | a folded, collapsed or squashed face somewhere | find it with Display Stretch (Angle); unwrap that area again |
| `uneven density inside islands` | area p95 over 0.20 | more seams, or `MINIMUM_STRETCH` with 100 or more iterations |
| `N folded faces` | part of an island flipped over the rest | unwrap again; look for a twisted seam or a pinned vertex dragged across |
| `N faces with zero UV area` | faces collapsed in UV, under 1/100 of their island's UV area per 3D area (Project from View with faces edge-on does it) | unwrap them again |
| `UVs outside 0-1` (lightmap) | a chart leaves the tile | pack again |
| `N islands leave the 0-1 tile` | a unique layout that did not fit | a larger map, a lower density, split the piece, or delete faces nobody sees |
| `N island pairs partly overlap` | two islands share texels | pack again; for a tiling or trim layer audit with that purpose |
| `N stacked island pairs in a lightmap` | stacked copies would share lightmap texels | apply Mirror and Array, unwrap the second map uniquely |
| `N stacked island pairs inside 0-1 at bake time` | `baking=True`: copies (or a mirrored half) left in the tile would bake into each other | `layout(..., bake=True)` |
| `islands x px apart (< g)` | a gap below the padding | lay out or pack with the right `pad_px`; for a lightmap, `pack_lightmap` |
| `x px from the tile edge (< g)` | the edge margin is below half the gap (for a lightmap, 1 texel) | pack again |
| `N edges inside lightmap charts are hard or bend more than 88 deg` | a chart wraps a corner or a hard edge: its texels smear across it | unwrap the second map seam-based: `seams_from_hard_edges`, then `uv.unwrap(margin=0.001)`; Smart UV Project joined charts at corners at every `island_margin` tried (0.001-0.02) |
| `N long islands run along V: grain or a trim strip should run along U` | a directional texture (or a trim strip) runs across these islands | orient per face group with the axis across the grain (SKILL.md section 5); trim strips no axis fixes (tubes): `turn_islands` |
| `N text islands are mirrored` | `text=True`: the `uv_text` faces of an island are flipped | unwrap those faces again from the front, or flip the island in U before any bake |
| `N text islands do not have the letters' up ... on +V` | `text=True`: the text is turned | `uv.align_rotation(method="GEOMETRY", axis="Z")` on those faces (or turn the island to its `uv_text_up`), then lay out again |
| `N text islands lie across their up direction` | `text=True`: text on faces +Z cannot orient (lying flat) | give those faces a `uv_text_up` vector: the direction the letters' tops point |
| `N islands cross a trim row edge` | a strip's V range leaves its row and samples the next one | scale or move it into its row |
| `texel density varies between islands` | `texel_cv` over 0.15 | `layout(px_per_m=...)`; mark deliberate drops `uv_low_density` |
| `N faces marked low-density are not lowered` | a mark on faces at full density | shrink those islands or remove the mark |
| `texel density x px/m, target y` | the mean is outside the purpose's band | `layout(px_per_m=...)`; for tiling, `tile_project(objs, tile_m=map_px / px_per_m)` |
| `placement step x m is not a whole number of y m tiles` | a tiling family's tile does not divide the grid module or storey height | a tile that divides the step, or the family placed only on multiples of the tile, or phase variants (workflows) |
| `n of m tiling faces off tile_project's scale and phase` | Cube Projection, a rescaled or moved projection, or a pivot off the grid: the pattern jumps where these faces meet a neighbour (the check allows half a texel) | `tile_project`; the pivot on the grid, scale applied |
| `n tiling faces mirrored against tile_project` | U runs backwards on those faces (another tool's convention, or a mirror applied after projecting) | `tile_project` again |
| `N islands outside 0.80-1.25x of y px/m` (0.90-1.10x for tiling and trim) | islands off the band, although the mean may pass | rescale those islands (`layout(px_per_m=...)`), or mark a deliberate drop `uv_low_density` |
| `N hard edges not on a UV seam` | a normal-map bake would draw lines there; seamed edges reported here were fused by an unwrap at margin 0 | first `apply_stack(ob)`: the stack from the top down to the last topology change, never a Bevel alone (with one live, seams are read off the unbevelled mesh); the Triangulate stays off until after `layout`, a Weighted Normal live. Then, on a hard-surface stack, `seams_by_angle` (never shade it by angle again); then `seams_from_hard_edges`, and unwrap again with `margin=0.001` |
| `N UV maps` | more than 8: engines drop the rest | delete unused UV maps |

## Accuracy and limits

- Gaps, overlaps and coverage are rasterised at `raster_scale` raster pixels per texture pixel: 8 at a 128 px
  footprint, 2 at 512, 1 at 1024 and 2048, 0.5 at 4096. A border pixel's centre sits up to a raster pixel inside its
  island, so a reported gap is real and a pass can be up to 2 / `raster_scale` px short (0.25 px at 128, 2 px at
  1024). The margin to the tile edge is exact: a lightmap chart 0.99 texels from the edge is reported (1/1000 px
  is the only tolerance, for float error). A fractional footprint is rounded down before measuring (76.8 px is
  measured as 76), so gaps and edges read short by under one part in the footprint (a 2-texel gap reads 1.98 at
  76.8 px): on the safe side.
- The text check reads, per island and over its `uv_text` faces only, where the letters' up (`uv_text_up`, default
  world +Z) goes in UV: +V within 45 deg passes. Faces whose normal lies within about 26 deg of that up carry no up
  (default +Z on a floor marking): an island with only such faces is reported as flat.
- Triangles are Blender's loop triangles (a convex quad splits along its first diagonal). The RizomUV pipeline's
  grader picks the diagonal that fits the UVs best, so a strongly non-planar quad can grade differently there. The
  final audit, after `layout` with the Triangulate back on, reads the triangles that are baked and exported.
- Angular max skips 3D slivers (quality 4 x sqrt(3) x area / sum of squared edges below 0.02); p95 and p99 include them.
- Collapse is judged against density, not pixels: a triangle with under 1/100 of its island's UV area per 3D area
  (or in an island with under 1/100 of the layout's) is a zero-area face, reported on its own and left out of the
  distortion and density figures. Small faces at a lightmap's few texels per metre are not collapsed: a 5 mm
  chamfer's triangles at 10 texels/m cover under 1/1000 px^2 each and are mapped at the layout's density.
- An edge is hard when its two faces' corner normals are more than 0.5 deg apart (`HARD_EDGE_DEG`): a Triangulate
  with Keep Normals re-encodes custom normals and leaves 0.006-0.035 deg splits (route A with a Boolean or Array),
  which are not hard edges and need no seams.
- An island whose two winding halves lie exactly on each other is split into its halves and counted in
  `mirror_stacks`. Any other flipped part of an island is a fold.
- Orientation is read from the shape: an island's long side (principal axis of its UV corners, 1.5x or more) should
  run along U. End faces of boards and squares carry no direction; a panel whose grain runs across its short side
  reads as wrong: look before rotating it.
- A non-square map (`map_px` "2048x1024") is measured in square pixels: U and V are scaled to pixels first.
- Density is in Blender units read as metres: keep the scene's unit scale at 1.
- Stacks for `layout` are islands with the same bounding box (whole-tile offsets ignored) and area, per object;
  `layout(together=True)` does not stack islands of different objects.
- `pack` and `layout` take square maps only (Blender packs into a square tile); the audit, `set_texel_density(...,
  pack_after=False)` and `turn_islands` take non-square maps.
- `material=` keeps the faces whose material matches and cuts the edges to the rest: a hard edge or a chart bend on a
  material border is not counted.

## What it reads and what it changes

- The audit reads the evaluated mesh (modifiers applied, as it exports) in world space: an unapplied scale changes
  px/m, Mirror and Array copies count, and `uv_low_density` marks follow the modifiers. It changes nothing.
- `apply_stack` changes the modifier stack and the mesh: it applies modifiers (from the top only), may add a
  Triangulate, and switches the Triangulate off in the viewport; turn it back on after `layout`. It never shades.
- `seams_from_hard_edges` reads the evaluated mesh when its topology matches the mesh's own, so a Smooth by Angle
  modifier (what Shade Auto Smooth adds) or a live Weighted Normal counts; with a modifier that changes the topology
  it reads the mesh itself. `seams_by_angle` reads the mesh's face normals. Both change only edge seams.
- `layout`, `pack`, `pack_lightmap`, `set_texel_density`, `tile_project`, `turn_islands` and `stack_faces` change only the UV map they
  work on, and restore the active UV map, the selection and the mode. Those that write UVs directly leave Edit Mode
  while they write (edit-mode data would overwrite the new UVs on exit) and return to it.
- `set_texel_density` and `layout(px_per_m=...)` refuse a mesh whose modifiers change its corner count: run
  `apply_stack` (and `apply_stack(ob, keep_mirror=False)` for a Mirror kept live) and keep the Triangulate off in the
  viewport until after `layout`.
- `stack_faces` checks every copy against its source before writing and raises, writing nothing, on a mismatch.
- Blender's `merge_overlap` (`keep_stacks=True`) merges every overlapping island, which is why `layout` moves each
  stack and each single island to its own place before its one pack.

## Command line

In a single MASTER (`blender-kit-library`'s default layout) the pieces sit in an excluded `KIT` collection, which
selection and edit-mode tools cannot reach: unwrap and audit a work file checked out of it (`checkout`, then
`integrate`).

```
blender -b --factory-startup --python-exit-code 1 scene.blend --python uv_audit.py -- --objects "KIT_*" --map 1024 --td 512
blender -b --factory-startup --python-exit-code 1 scene.blend --python uv_audit.py -- --objects "KIT_*" --lightmap-texels 20
blender -b --factory-startup --python-exit-code 1 scene.blend --python uv_audit.py -- --objects "KIT_*" --purpose trim --material "M_Trim*" --map 2048x1024 --td 512
blender -b --factory-startup --python-exit-code 1 scene.blend --python uv_audit.py -- --objects "KIT_*" --purpose tiling --material "M_EXT_*" --map 512 --td 512 --tile-m 1 --steps 1,3
```

| Flag | Meaning |
|---|---|
| `--objects` | object name pattern, case-sensitive (`fnmatchcase`); default every mesh |
| `--material` | only the faces whose material name matches (a name or a pattern); meshes without that material are skipped |
| `--tile-m`, `--steps`, `--tile-offset` | tiling: the tile's size in metres; every face against tile_project's scale and phase, and the placement steps (grid module, storey height, comma-separated) as whole numbers of tiles; a phase variant's offset `x,y,z` (its steps are the tile and the storey) |
| `--layer` | UV map index or name, or `active`; default 0 (UV0), or 1 for a lightmap |
| `--purpose` | `unique` (default), `tiling`, `trim` or `lightmap`; `--lightmap` is the same as `--purpose lightmap` and goes with no other purpose |
| `--map` | texture size in pixels, `1024` (default) or `2048x1024`; for a lightmap, the footprint (fractions such as `165.2` round down) |
| `--lightmap-texels`, `--lightmap-scale` | lightmap texels per metre and the renderer's scale. `--lightmap-texels` makes it a lightmap audit of the second map; without `--map`, at the footprint of the measured UV2 box |
| `--lod` | the LOD level of a lightmap audit (texel scale x 0.5^n); by default read from each object's `<Piece>_LOD<n>` name |
| `--lightmapper` | `unity` (default; `progressive` is the same) or `bakery`: whose footprint a lightmap audit uses |
| `--pad` | gap between islands in pixels (default by purpose, see above) |
| `--td` | target texel density in px/m |
| `--baking` | the layer takes a baked normal map or AO |
| `--directional` | the texture has a direction: long islands must run along U |
| `--text` | check the faces marked `uv_text`: not mirrored, the letters' up (`uv_text_up`, default +Z) on +V |
| `--rows` | trim rows in pixels counted from the bottom of the map (V = 0), such as `0-128,128-192`: every island must stay inside one |
| `--shared` | the matched objects share one texture: also check overlaps and gaps between them |
| `--json` | write the full reports to this file |

Exit code 0 when nothing needs a look; 1 when any object (or the shared layout) has an issue; 2 for a request it
cannot audit: no mesh matched `--objects` (or none has the `--material`), a lightmap without `--map` or
`--lightmap-texels`, `--lightmap` or `--lightmap-texels` with another purpose, `--text` with no face marked
`uv_text`, a bad `--map`. Notes (`NOTE:` on the line) never change the exit code. Without `--python-exit-code 1`,
a script error would exit 0.
