# Distortion, seams and the quality gate

How to get minimum-distortion UVs out of RizomUV automatically, how to measure them, and the evidence behind the
presets in `scripts/rizom_uv.py`. Measured on RizomUV 2027.0.598 and Blender 5.2.2, 9 Oct 2026.

## Contents

- Measures
- RizomUV's own grading (stretch map)
- What each Auto option does to distortion
- The sweep that chose the presets
- RizomUV against Blender's own unwrappers
- Seams: what the generator must mark
- The gate and the retry ladder
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
| Islands per 100 faces | fragmentation; ignored up to 12 islands | a bevelled box cut into one island per face scores 100 |
| Split-sensitive quads | convex quads whose two possible splits differ by more than 10% | non-planar quads whose look depends on the engine's triangulation |

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
length), not area. Its neutral must be the layout's mean linear ratio, `sqrt(UV area / 3D area)` of the current
layout; with the default neutral the whole map is one flat colour and says nothing. Set `Min`/`Max` at
neutral / 1.25 and x 1.25 for a useful contrast. `rizom_uv.stretch_map()` does this on whatever layout RizomUV
holds; `blender_rizom.unwrap_object(stretch_png=...)` reloads exactly the written UV0 layout first. Measured
colours: **red = UV smaller than neutral** (fewer texels per metre), **blue = UV larger** (more texels per metre),
grey = neutral. The path must be absolute and its folder must exist, or RizomUV writes nothing.

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

## The sweep that chose the presets

Urn: a revolved body (24 segments) on a bevelled plinth, 442 faces. Coverage at UV0 (1024 px, padding 8, margin 4).

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
nearly planar quads, and the re-measured presets agree (urn organic p95 1.09-1.10, arch hard 1.000).

Timing: launch about 2 s alone (5-9 s with three starting together); unfold + optimise about 0.1 s and each pack
about 0.1 s per mesh at 200-450 faces; RizomUV's auto-seam takes about 160 s at 200k faces. The arch, the urn and a
torus came back bit-identical across calls and processes; an organic Suzanne did not (76-79 islands), while its
grades held to 4 decimals. Regression checks compare grades with tolerances, not hashes.

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
close on hard surface, and RizomUV still packs tighter.

## Seams: what the generator must mark

RizomUV's Auto finds sharp edges and tubes, not structure. On an arch with no generator seams, the U-shaped
bands came back as single islands that packed at **14%** coverage; seams at both springing lines and the apex
lifted it to 62% (UV0) and 42% (UV2). So a mesh generator should mark the cuts a UV artist would make:

- mitres and corners of mouldings, springing lines and apexes of arches;
- the back (least seen) line of revolved and swept parts;
- material boundaries (a seam there costs nothing, the texture changes anyway).

They reach RizomUV through the seed topology (`blender_rizom.mesh_arrays` splits at `use_seam`).

## The gate and the retry ladder

Default UV0 gate (`uv_metrics.GATE`): angular p95 <= 1.15, p99 <= 1.5, max <= 2.0 (non-sliver triangles), area
local p95 <= 0.20, area global mean <= 0.05, islands per 100 faces <= 25 (skipped up to 12 islands); non-finite UVs
fail. The baseline unwrap of the urn fails it; both chosen presets pass on both test meshes, and on Suzanne,
a torus and the primitives. It sends to review: a bevelled box hard-cut into one island per face (fragmentation),
a low-poly icosphere (p95 1.155) and, depending on the run, a UV sphere (global area 0.05). A lightmap channel can
use the same gate, but there overlap, padding and bounds matter more than shape.

The gate grades the first channel of each attempt; the chosen attempt's layout is then reloaded and the other
channels are packed from exactly its islands, so the lightmap UV and the stretch map show what was graded.

`rizom_uv.unwrap_gated` tries the preset, then `Quality` 0.85, then Mosaic 0.9 with `Quality` 0.85, and returns
the first attempt that passes. If none does, it returns the least distorted one with `gate_failures` filled in:
send that piece to review (or fix its seams), never accept it silently. The ladder steps are heuristics, not
measured optima; record which attempt each piece used.

## Validation checklist

`uv_metrics.report()` gives all of these; `smoke_test_blender.py` shows the expected values.

| Check | Rule |
|---|---|
| Overlap | 0 pixels claimed by two islands at the target resolution (folds inside one island show as flips) |
| Bounds | every UV inside 0-1 for lightmaps and unique-textured pieces; all finite |
| Padding | exact boundary-to-boundary gap (`padding_gaps`) >= padding - 0.5 px: RizomUV's PaddingPerfect pads on a pixel grid and leaves 3.5-3.9 px at padding 4; pass `tol_px=0` for a strict check |
| Margin | every island at least the margin from the tile edge |
| Flips | 0 polygons with negative UV area |
| Distortion | the gate above; `split_sensitive_quads` 0, or the mesh triangulated before export |
| Texel density | within the target band for the piece's class (`texel-density.md`), CV <= 0.15 |
| Coverage | reported; a piece far below its family's usual coverage needs better seams |
| Repeatability | run twice: islands within about 5%, angular p95 within 0.01, coverage within 0.02, density exact |
