# Distortion, seams and the quality gate

How to get minimum-distortion UVs out of RizomUV automatically, how to measure them, how to read a report, and the
evidence behind the presets in `scripts/rizom_uv.py`. Measured on RizomUV 2027.0.598 and Blender 5.2.2, 9 Oct 2026;
the smoke-test meshes and the stretch-map grading again on 17 Oct 2026. The gate values are the `uv-unwrapping`
skill's (it owns them); this file states the same numbers.

## Contents

- Measures
- RizomUV's own grading (stretch map)
- What each Auto option does to distortion
- The sweep that chose the presets
- RizomUV against Blender's own unwrappers
- Seams: what the generator must mark
- Visible seams: where the cuts run
- The grade and the retry ladder
- Reading a report
- Validation checklist

## Measures

All are area-weighted over triangles. `scripts/uv_metrics.py` computes them from the same flat arrays RizomUV
uses, so they grade UVs from any tool.

| Measure | Definition | Reads as |
|---|---|---|
| Angular | sigma1 / sigma2 of the 3D-to-UV Jacobian | 1.00 = shape kept. 1.15 = a square drawn 15% longer one way. Shows as a checker turning into rectangles or diamonds |
| Angular p99, max | the tail; max over triangles that are not slivers in 3D (quality >= 0.02) | folds and collapsed UVs that p95 hides |
| Area, local | abs(log2(sigma1 x sigma2 / island mean)) | 0 = even texel density inside each island. 0.2 = two spots 1.15x apart in density |
| Area, global | abs(log2(sigma1 x sigma2 / mesh mean)) | the same across islands: did packing keep one density for the whole piece? |
| Texel CV | coefficient of variation of per-polygon texels/unit (exact polygon areas) | the same idea as global area, in the units a texture budget uses |
| Islands per 100 faces | fragmentation, per connected shell, against its planar regions (`uv_metrics.planar_regions`: faces joined across non-seam edges at under the preset's SharpEdges.AngleMin): a shell cut into more than 12 islands and more islands than regions scores its islands beyond its regions per 100 faces | a flat shell cut into one island per face scores 97; a mitred frame (16 regions), a stair (14) and a crate of separate planks score 0 (`islands_per_100_faces_all` keeps the whole-mesh figure) |
| Split-sensitive quads | convex quads whose two possible splits differ by more than 10% | non-planar quads whose look depends on the engine's triangulation |
| Visible seams | metres of UV seam through smooth surface (dihedral < 15 deg) whose faces face up or to the front (-Y), not marked by you (`uv_metrics.visible_seams`; next to the grade, never in it) | 0 = no cut crosses a visible smooth face. A seat cushion's autoseams: 1.08 m across its top. Shows as a checker that steps or jumps, or a tiling texture's patch |

Use the 95th percentile, not the mean: one badly stretched band on a curved body hides behind a good average
(baseline urn: mean 1.14 looked fine, p95 1.44 and max 3.5 did not).

**Triangulation decides the grade of non-planar polygons.** A fan from corner 0 graded one folded quad on
Suzanne at 13.3 and the same quad with its corners rotated at 1.4, and it fills the wrong area for concave
n-gons (a perfect star layout showed 16,975 px of false overlap). `uv_metrics.triangulate` never fans: concave
quads split through the reflex corner, convex quads along the diagonal their UV layout fits best (the split
RizomUV flattened), n-gons by ear clipping. Texel density and the linear ratio use exact polygon areas (Newell,
shoelace). Suzanne's organic unwrap then grades p95 1.106, p99 1.17, max 1.39, with 59 split-sensitive quads
(8.7% of its area): triangulate such meshes before unwrapping so the engine uses the split that was graded.

## RizomUV's own grading (stretch map)

`RasterExport` with `PolygonColorMode "Stretches"` colours each polygon by **linear** scale (UV length / 3D
length), not area, although its docstring says "triangle area ratio": measured 17 Oct 2026, the urn's layout came
out grey with Neutral = sqrt(UV area / 3D area) and saturated blue with the area ratio. Its neutral must be the
layout's mean linear ratio; with the default neutral the whole map is one flat colour and says nothing. Set
`Min`/`Max` at neutral / 1.25 and x 1.25 for a useful contrast. `rizom_uv.stretch_map()` does this on whatever
layout RizomUV holds; `blender_rizom.unwrap_object(stretch_png=...)` reloads exactly the written UV0 layout first.
Measured colours: **red = UV smaller than neutral** (fewer texels per metre), **blue = UV larger** (more texels per
metre), grey = neutral. The path must be absolute and its folder must exist, or RizomUV writes nothing; a map that
fails after the UVs were written is a warning, not a failure.

## What each Auto option does to distortion

| Option | Effect | Gotcha |
|---|---|---|
| `SharpEdges.AngleMin` | cuts at hard edges | 40 deg for hard surface, 60 deg for organic (fewer cuts across soft bevels) |
| `PipesCutter` | opens tubes and cylinders (the thing Blender's unwrap cannot do on its own) | keep on |
| `HandleCutter` | cuts handles (genus) | keep on |
| `QuadLoopCutter` | follows quad loops on grid meshes | **overrides Mosaic**: with both on, Mosaic does nothing |
| `QuasiDevelopable` (Mosaic) | splits islands into nearly developable patches: the main distortion reducer on curved bodies | **never splits an island with fewer polygons than `IslandPolyNBMin`** (default undocumented): left unset, Mosaic did nothing on the 442-face urn. Set it to 1 |
| `StretchLimiter` + `Quality` | adds cuts only where flattening still distorts | `Quality` 0.75 is a safety net; 0.9 shattered the urn into 39 islands, 0.99 into 103 |
| `Skeleton` | hierarchical cuts for limbs | no effect on props |
| `ReWeld` | merges islands back | recovers few islands but costs coverage (62% to 44% on the urn) |
| `Optimize.AngleDistanceMix` | 1 = keep angles, 0 = keep lengths | 1.0 and 0.5 measured the same within noise; 1.0 kept |

The presets in `rizom_uv.PRESETS`:

| | `hard` | `organic` |
|---|---|---|
| For | kit pieces, planar and developable parts, anything with its seams marked | curved bodies, revolved parts, props with no obvious seams |
| `SharpEdges.AngleMin` | 40 | 60 |
| Cutters | `PipesCutter`, `HandleCutter` | `PipesCutter`, `HandleCutter` (no `QuadLoopCutter`: it switches Mosaic off) |
| Mosaic | - | `Developability 0.8, IslandPolyNBMin 1, FitCones, AreaMinRatio 0.01` |
| Stretch limiter | `StretchLimiter {}`, `Quality 0.75`, `FlatteningMode 0` | same |

## The sweep that chose the presets

Urn: a revolved body (24 segments) on a bevelled plinth, 442 faces. Coverage at UV0 (1024 px, padding 8, margin 4,
the padding used on 9 Oct 2026).

| Candidate | Islands | Coverage | Angular mean / p95 / max | Area p95 | Global |
|---|---|---|---|---|---|
| Baseline: QuadLoopCutter + sharp 60 | 6 | 59% | 1.137 / 1.44 / 3.52 | 0.50 (1.41x) | 0.125 |
| Mosaic 0.8 + sharp 60 + cutters | 14 | 65% | 1.030 / 1.11 / 1.67 | 0.11 | 0.030 |
| Mosaic 0.95 + sharp | 14 | 62% | 1.040 / 1.22 / 1.62 | 0.19 | 0.036 |
| Mosaic 0.8, AngleDistanceMix 0.5 | 14 | 65% | 1.028 / 1.10 / 1.54 | 0.13 | 0.033 |
| **Mosaic 0.8 + sharp + stretch limiter 0.75 (chosen "organic")** | **17-18** | **61-62%** | **1.020 / 1.09 / 1.33** | **0.098 (1.07x)** | **0.019** |
| Chosen + ReWeld | 5 | 44% | 1.024 / 1.11 / 1.33 | 0.105 | 0.021 |

The arch (pointed-arch portal surround, 202 faces, generator seams at the springing lines and apex) scored angular
1.000 and area 0 under the hard preset (the organic preset's softer cuts give p95 1.06): planar and developable
parts are carried entirely by good seams.

The sweep and the Blender comparison below were measured with the earlier fan triangulation; both meshes are
nearly planar quads, and the re-measured presets agree (urn organic p95 1.09-1.10, arch hard 1.000). With the
16 px default padding (17 Oct 2026) the same unwraps cover 0.55 (urn) and 0.59 (arch) of the tile.

To rerun the sweep after an upgrade: build the arch and the urn with `smoke_test_blender.build_arch()` /
`build_urn()` in Blender, take `blender_rizom.mesh_arrays(ob)`, and for each candidate `auto` dict call
`rizom_uv.unwrap_and_pack(link, mesh, auto=candidate, packs={"uv0": spec})` with `spec = rizom_uv.pack_spec(1024)`,
then grade the pack with `rizom_uv.layer_report(mesh, ids, uvw, spec)`. Change `PRESETS` only for a candidate
that beats the current one on angular p95 and area p95 on both meshes.

**1-segment chamfered boxes, the common kit shape** (measured 17 Oct 2026, UV0 1024 px, 16 px gaps): under `hard`
the chamfer strips stay joined through the corner triangles (35 deg from each strip, under `SharpEdges.AngleMin`
40) into one sprawling island. Coverage per attempt:

| Mesh | `hard` | + `Quality` 0.85 | + Mosaic 0.9 | `organic` |
|---|---|---|---|---|
| Pillar 0.4 x 0.4 x 3 m | 0.10 | 0.10 | 0.15 | 0.53 |
| Cube 1 m | 0.22 | 0.22 | 0.35 | 0.61 |
| Slab 2 x 0.2 x 3 m | 0.17 | 0.17 | 0.20 | 0.75 |
| Pillar, 2-segment chamfer | 0.57 | 0.57 | 0.57 | 0.57 |
| Cube, 3-segment chamfer | 0.33 | 0.33 | 0.40 | 0.65 |

The ladder's steps keep the sprawl, so a `hard` pack under 0.35 coverage goes straight to the organic preset; the
distortion stays at angular p95 about 1.00 either way. A texel-density pack shows the same sprawl as "does not fit":
a 2.4 x 0.04 x 0.3 m strip with a 6 mm bevel made one ring about 5.4 m long under `hard` and fitted neither 1024
nor 2048 px at 512 px/m (only 4096); the organic preset cut 12 islands that fitted 2048 (17 Oct 2026). So a `hard`
attempt that does not fit also goes to the organic preset before the ladder stops.

**Long thin pieces are not sprawl.** A plain 3 x 0.12 x 0.12 m beam covered 0.158 on every attempt and a 1.2 x
0.15 x 0.03 m plank 0.297: a square tile cannot hold a 25:1 island better, whatever the seams. The floor therefore
drops to 0.8 x the shape's limit, 3D area / (bounding-box diagonal of the largest connected shell)^2
(`uv_metrics.shape_coverage_limit`: beam 0.163, plank 0.301, 1 m cube 1, three 1 m cubes 5 m apart in one object 1),
and the line notes `thin piece`: give such pieces a texel-density pack or put them on a trim. Compact pieces keep
0.35, so the chamfered boxes above still fail it (three of them spread out in one object used to read 0.14 over the
whole object and pass at 0.33 under `hard`; the organic preset gives 0.57).

**Bands and L plates stay REVIEW until seams cut them**, because an unrolled band is pi x its diameter, longer than
the piece. Measured 17 Oct 2026, every preset gave the same: a round 1.2 m table top 0.16, a washer 0.07, a barrel
hoop 0.06, a flat 1 m L bracket 0.10. Seams fix them, but only seams that reach a cut: four seams across the table
top's rim did nothing (one seed island) until its two edge loops were seams too (0.53, OK); a seam ring at the L's
corner gave 0.41, OK. A marked seam whose ends stay joined to the rest is dropped.

Timing: launch about 2 s alone (5-9 s with three starting together); unfold + optimise about 0.1 s and each pack about
0.1 s per mesh at 200-450 faces. An 82k-face auto-seam and unfold took 15-16 s (organic) and 26-29 s (hard) on an idle
machine (17-18 Oct 2026) and up to 158 s with other jobs running; 200k faces about 160 s. The arch, the urn and a
torus came back bit-identical across calls and processes; an organic Suzanne did not (76-79 islands), while its grades
held to 4 decimals. Regression checks compare grades with tolerances, not hashes.

## RizomUV against Blender's own unwrappers

Same meshes, same metrics, Blender 5.2 operators with default-ish settings and an 8 px margin:

| Mesh | Method | Islands | Coverage | Angular p95 | Area p95 | Global |
|---|---|---|---|---|---|---|
| Urn | Blender Smart UV Project (66 deg) | 34 | 57% | 1.43 | 0.34 | 0.16 |
| Urn | Blender seams from sharp 60 deg + Minimum Stretch | 82 | 64% | 6.77 | 1.41 | 0.39 |
| Urn | **RizomUV organic** | 18 | 61% | **1.10** | **0.10** | **0.02** |
| Arch | Blender Smart UV Project | 20 | 56% | 1.41 | 0.35 | 0.10 |
| Arch | Blender seams (generator + sharp 60) + Minimum Stretch | 86 | 56% | 1.07 | 0.08 | 0.02 |
| Arch | **RizomUV hard** | 22 | **63%** | **1.00** | **0** | **0** |

Blender's unwrap cannot open a closed body by itself (the urn's body had no seam, hence 6.77); Smart UV Project
cuts by angle only and leaves visible stretch on curves. With good seams already marked, Blender's Minimum Stretch is
close on hard surface, and RizomUV packed the arch tighter; on 1-segment chamfered boxes the `hard` preset alone
packs worse than either (above), which the coverage floor catches.

## Seams: what the generator must mark

RizomUV's Auto finds sharp edges and tubes, not structure. On an arch with no generator seams, the U-shaped
bands came back as single islands that packed at **14%** coverage; seams at both springing lines and the apex
lifted it to 62% (UV0) and 42% (UV2). So a mesh generator should mark the cuts a UV artist would make:

- mitres and corners of mouldings, springing lines and apexes of arches;
- the back (least seen) line of revolved and swept parts;
- material boundaries (a seam there costs nothing, the texture changes anyway).

They reach RizomUV through the seed topology (`blender_rizom.mesh_arrays` splits at `use_seam`).

## Visible seams: where the cuts run

The grade measures distortion and layout, not where the seams are, and RizomUV's Auto cuts to lower distortion
without knowing which side is seen. On a quad-remeshed seat cushion with nothing marked, `organic` put a stepped cut
across the top that passed the gate (angular p95 1.04, area p95 0.04); a tiling fabric at 1 UV/m shows a patch with
stepped edges there. `uv_metrics.visible_seams` measures it; `report()` carries it as `seams`:

| Field | Definition |
|---|---|
| `seam_m` | every UV seam: an interior edge (exactly two faces) whose UVs differ across it at either end by more than 1e-5 (`SEAM_UV_TOL`; unwelded corners with equal UVs and open borders are not seams) |
| `smooth_seam_m` | the seams whose two faces meet at a dihedral under 15 deg (`SMOOTH_SEAM_DEG`): through a surface, not along an edge |
| `visible_seam_m` | the smooth seams whose faces' mean normal has a component of at least 0.5 (`VIEW_FACING`) up (+Z) or to the front (-Y) (`VIEW_DIRS`) |
| `visible_seam_unmarked_m` | of those, the ones not split in the seed `mesh["uvw_ids"]` (`mesh_arrays` splits it at `use_seam`): the cuts the unwrapper chose. The note uses this one |
| `visible_seam_bounds` | the box `[min xyz, max xyz]` round the unmarked visible seams, in the mesh's (world) metres: where to look |
| `size_m` | the bounding-box diagonal: the note's scale |

Why these values:

- **15 deg.** A hard-surface seam sits on an edge of 30 deg or more (a 3-segment chamfer's steps, a 1-segment
  chamfer's 45, a box's 90), so it never counts; a subdivided or remeshed round (a cushion's welt, about 11 deg per
  step) is smooth. A 24-segment revolve is 15 deg round its body, on the boundary: the urn's tapered rows count.
- **0.5, up and the front.** cos 60 deg: a face turned further from the viewer shows under half its area. Tops,
  fronts and the rounds between them count; the back (+Y), the underside and the sides (+-X) do not. The directions
  are world space as placed: unwrap a piece at rot 0, its front at -Y, as the kit holds it. For a piece seen from
  every side pass `view_dirs=None` (every smooth seam counts).
- **Closed shells are turned outward** by the sign of their volume before the facing test: bmesh's
  `recalc_face_normals` turned a thin bevelled cushion inward (24 Oct 2026), which read its top as its bottom.
- **Marked seams are not noted.** A seam you marked on a welt or a back line is a decision; the defect is a cut
  nobody chose.

The note, `visible seams N m` on the object's line (`uv_metrics.visible_seam_warning`, in UV0's report `warnings`),
starts at 0.25 m unmarked (one 25 cm checker square at 1 UV/m; shorter runs rarely read as a line), or a quarter of
`size_m` on a smaller piece. It is advisory, never a gate failure: a closed smooth body (an urn, a rock) needs its
seams somewhere, the facing directions are a guess for a piece seen from every side, and the retry ladder only adds
cuts (`Quality`, Mosaic), so a failure would spend the attempts and end in REVIEW with the same seams. Moving a seam
takes a marked one.

Measured 24 Oct 2026 on RizomUV 2027.0.598 and Blender 5.2.2 (UV0 1024 px, filled). Rounded-box cushions: a box cut
7 times each way, its edges bevelled in 4 segments, one subdivision level, then QuadriFlow to 2,100-2,350 quads (a
quad remesh): a seat 0.6 x 0.6 x 0.15 m, a back cushion 0.6 x 0.15 x 0.55 m tilted back 12 deg, a bench pad 1.4 x
0.45 x 0.06 m. Panels: welts on the 45 deg line of the rounds, one band cut on the hidden side (the seat's back, the
back cushion's bottom, both short ends of the pad). Every unwrap below passed the gate:

| Piece | `organic`, nothing marked | Panels, `organic` | Panels, `hard` |
|---|---|---|---|
| Seat cushion | 1.08 m (8 islands) | 0 (4) | 0 (4) |
| Back cushion | 0.34 m (3) | 0 (4) | 0.50 m (10) |
| Bench pad | 2.04 m (12) | 0 (4) | 1.96 m (34) |

With nothing new marked: the urn (`organic`) 1.17 m, Suzanne (`organic`) 0.88 m, the 5120-face rock (`organic`)
5.91 m, a 1 m cube with 8-segment rounded bevels (`hard`) 5.88 m; the arch (`hard`, generator seams marked) 0 of
1.57 m visible, a 1-segment chamfered cube 0. The same seat without the remesh (bevel and subdivision, 3,456 faces):
1.25 m, and 0 with panels, but its one band cut left a 2.4 m band and coverage 0.19 (REVIEW); cuts on both sides as
well gave 0.50 and OK, still 0.

To see it: `br.checker_preview(ob, cell_m=0.25)` puts 25 cm squares in world space on `UVMap` (a procedural checker,
scaled per object by its `rizom_checker_scale` property, 1 / (UV units per metre x 0.25)), so it shows what a tiling
material at 1 UV/m shows whatever the pack's density. On the seat above the top showed squares offset along a
staircase line; with the panels marked it was one unbroken checker.

## The grade and the retry ladder

`uv_metrics.grade(report)` is the one verdict, for every attempt and every written layer:

- **Distortion gate** (`uv_metrics.GATE`, the `uv-unwrapping` skill's values): angular p95 <= 1.15, p99 <= 1.5,
  max <= 2.0 (non-sliver triangles), area local p95 <= 0.20; this grader also keeps area global mean <= 0.05 and
  islands per 100 faces <= 25 for its retries; non-finite UVs fail. Fragmentation counts per connected shell
  against its planar regions: only a shell cut into more than 12 islands and into more islands than it has regions
  counts. A crate of 19 planks (6 islands per box), a mitred window frame (16 islands, 16 regions) and a 5-step stair
  (14 and 14) pass; they used to score 100 and 28 against faces. One flat or smooth shell in confetti does not.
  A partial gate merges over these defaults (`{"angular_p95": 1.2}` loosens one
  key and keeps the rest; `float("inf")` turns one off); an unknown key or a non-dict is an error at once.
- **Layout**: every UV inside 0-1, no overlap between islands, padding and margin at least what the pack asked
  (UV0: in map pixels, 0.5 px tolerance for PaddingPerfect's pixel grid; lightmap: in texels at each renderer's
  footprint, strict), no flipped polygons. The lightmap layer is graded on its layout only.
- **Coverage** of a filled UV0 pack of up to 100 islands >= 0.35 (`uv_metrics.MIN_FILL_COVERAGE`): below it the
  pack is one sprawling island (the chamfered boxes above). Long thin pieces get 0.8 x their shape's limit instead
  (`coverage_floor`). With hundreds of islands the map/64 gaps take the tile, so there is no floor and the line
  notes `many islands`: a craggy 5120-face rock gave 520-550 islands at 0.20-0.21 under every preset and step
  (18 Oct 2026); accept it, or reduce surface detail first. A texel-density pack is exempt: its density decides its
  coverage. Failures print coverage to 3 decimals (`0.347 < 0.350`).

The baseline unwrap of the urn fails the gate; both chosen presets pass on both test meshes, and on Suzanne, a torus
and the primitives. Measured 17 Oct 2026, the organic preset's first attempt fails a low-poly icosphere (angular p95
1.40 at 1 subdivision, 1.30 at 2) and a 16 x 8 UV sphere (1.18), and the `Quality` 0.85 retry passes all three:
none of them goes to review.

`rizom_uv.unwrap_gated` tries the preset, then `Quality` 0.85, then Mosaic 0.9 with `Quality` 0.85, and returns
the first attempt that passes; a `hard` attempt that fails on coverage or does not fit is followed at once by the
organic preset. If none passes, it returns the least failing one (fitting first, then fewest failures, then lowest
angular p95) with `gate_failures` filled in: send that piece to review (or fix its seams), never accept it silently.
Any other attempt that does not fit stops the ladder (its steps do not shorten an island), and with a `time_budget`
no attempt starts that would overrun it (`blender_rizom` uses 80% of the per-object timeout). The ladder steps are
heuristics; record which attempt each piece used.

The gate grades the first channel of each attempt; the chosen attempt's layout is then reloaded, the other channels
are packed from exactly its islands and graded on their layout (`failures` per channel), so the lightmap UV and the
stretch map show what was graded. A lightmap channel whose smallest footprint cannot hold the islands with 2-texel
gaps is not packed (`skipped`), and one that fails its layout is not written.

**Many islands on one map.** RizomUV's gap tops out near map_px / (2 x sqrt(islands)), whatever the map size, the
asked padding, a texel-density pack or Pack's `Resolution` (measured 17 Oct 2026, 16 px asked at 1024: 16.0 px with
1000 islands, 15.1 with 1200, 13.0 with 1500, 10.9 with 2000, 8.9 with 3000; 1500 islands gave 27.0 of 32 at 2048
and 54.1 of 64 at 4096; the margin held). The map/64 gap needs sqrt(islands) <= 32, so above about 1000 islands it
cannot be met at any map size: use fewer islands (fewer cuts, small parts merged) or split the texture set.

## Reading a report

`unwrap_objects(..., report_path=...)` writes one strict-JSON entry per object (no NaN or Infinity: unknown values
are `null`):

| Field | Meaning |
|---|---|
| `object`, `mesh`, `kind`, `directional`, `rizomuv` | what was unwrapped, with which preset, orientation and RizomUV build |
| `attempt`, `attempts` | the attempt used; every attempt tried, with its failures, angular p95, coverage and `fits` (or why it was skipped) |
| `islands`, `faces` | of the chosen attempt |
| `failures` | every failure that made the line REVIEW: UV0's grade, then `UVMap_Lightmap: ...` layout failures |
| `gate_failures` | UV0's grade alone |
| `warnings` | modifiers applied (and a mesh name that could not be kept), a layer renamed or left at index 1, a renderer's lightmap footprint under 64 px, a lightmap UV not written (too small, or failed its layout), a thin piece, visible seams (UV0), a stretch map not written, shared meshes at different scales |
| `written` | the layers written (also on a `FAIL` entry, with `error`) |
| `layers.<name>` | per layer: `fits`, `written`, `skipped` (the note when it was not packed), `px_per_unit` (texels per metre; at the footprint for the lightmap), `pack` (map, padding and margin in pixels), `coverage`, `shape_coverage_limit`, `bbox_share`, `shells`, `overlap_px`, `flipped_polygons`, `in_unit_tile`, `padding_min_px` and `padding_pairs_below_min`, `margin_px_min` and `margin_ok`, `texel` (mean and CV), `distortion`, `seams` (where the seams run: Visible seams above), `failures` |
| `layers.UVMap_Lightmap` also | `footprint_px` (this object's footprint at the measured `bbox_share`), `footprints_px` (every renderer of the mesh, with its LOD scale) and `graded_at_px` (the smallest: padding and margin are in texels there), `box_fill` (charts' area / their box), `fallback` and `packed_for_px` when it was packed for 64 px |
| `removed` | an older `UVMap_Lightmap` removed because the new one failed |
| `shared_by`, `px_per_unit_per_user` | linked duplicates and the texture density each ends up with |
| `stretch_png`, `stretch_neutral` | the stretch map and the linear ratio it is centred on |

`padding_min_px` is exact when it is below about twice the asked padding, and `null` when every pair of islands is
farther apart than that (or there is one island); `padding_pairs_below_min` is always exact.

To grade UVs made any other way (Blender's unwrap, a hand layout): `mesh, ids, uv = br.uv_arrays(ob, "UVMap")`,
then `spec = br.ru.pack_spec(1024)`, `rep = br.ru.layer_report(mesh, ids, uv, spec)` and
`br.ru.layer_failures(rep, spec, first=True)`: the same verdict as the pipeline's, coverage floor included (a
cube-projected plank: `coverage 0.15 < 0.24`). For a lightmap layer, pass `br.ru.lightmap_spec(mesh, texels_per_m)`
as the spec and grade with `br.ru.layer_failures(rep, spec)`. The texture report's `seams` and `warnings` carry
the visible seams of that layout too, measured against the seams marked on the object (`uv_arrays` seeds with
them); `br.um.visible_seams(mesh, ids, uv, view_dirs=None)` counts every side.

## Validation checklist

`uv_metrics.grade()` checks the first seven rows; `smoke_test_blender.py` shows the expected values.

| Check | Rule |
|---|---|
| Overlap | 0 pixels claimed by two islands at the target resolution (folds inside one island show as flips) |
| Bounds | every UV inside 0-1 for lightmaps and unique-textured pieces; all finite |
| Padding | UV0: exact boundary-to-boundary gap >= the asked padding - 0.5 px (default map_px / 64, 16 px at 1024; RizomUV's PaddingPerfect pads on a pixel grid and has left 3.5-3.9 px at padding 4). Lightmap: >= 2 texels at each renderer's footprint texels_per_m x sqrt(A / b) x scale, b measured from the layout, strict |
| Margin | UV0: every island at least the margin (half the padding) from the tile edge; lightmap: at least 1 texel |
| Flips | 0 polygons with negative UV area |
| Distortion | the gate above; `split_sensitive_quads` 0, or the mesh triangulated before export |
| Coverage | a filled UV0 pack at least 0.35 (0.8 x the shape's limit for long thin pieces, per connected shell); below it, one sprawling island, band or L plate |
| Texel density | within 0.8-1.25x of the class for unique textures, within 10% for shared trims and tiling materials (`texel-density.md`); CV <= 0.15 inside a piece |
| Direction | for `directional` packs, the grain or world up along U or +V on every island (the smoke test checks it) |
| Repeatability | run twice: islands within about 5%, angular p95 within 0.01, coverage within 0.02, density exact |
| Seam placement | a piece that takes a tiling material, or is seen from above or the front: no `visible seams` note, or the seams it names looked at with `checker_preview(ob, cell_m=0.25)` and accepted (advisory, not graded) |
