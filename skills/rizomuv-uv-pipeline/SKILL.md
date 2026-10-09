---
name: rizomuv-uv-pipeline
description: Drive RizomUV headless from Python through RizomUVLink to auto-seam, unfold, optimise and pack UVs with minimum distortion - fileless transfer from Blender, hard-surface and organic presets, exact texel-density packing, lightmap UV2, a distortion and padding gate with retries, stretch maps, and safe parallel batches. Use when RizomUV is installed and UVs need automating or batch processing, when UVs come out stretched, overlapping or badly packed, when enforcing texel density, or when RizomUV's Pack or texel density seems to do nothing; for a Blender-only lightmap UV2 see blender-to-unity-vrchat.
---

# RizomUV UV pipeline (headless, from Python)

Unwrap with RizomUV through RizomUVLink, passing the mesh in memory: one private headless instance per session,
seams from the mesh generator plus RizomUV's automatic cuts, a measured distortion gate, then a pack that either
fills the tile or hits an exact texel density. **Measure every result**: RizomUV fails silently in several places,
and the numbers below are what caught each one.

## 1. Before starting

- Needs RizomUV **2027.0.417+** (headless mode), a Python **3.6-3.13** and a logged-in desktop session (headless
  draws nothing but will not start as a service). RizomUVLink has no build for 3.14: use Blender's bundled Python,
  `<blender>/<version>/python/bin/python.exe` on Windows, or run inside Blender. Each running instance takes a
  licence token on a floating licence.
- `<python> scripts/rizom_link.py` finds the install, launches headless and quits: if that fails, nothing else
  will work.
- After any RizomUV upgrade, run `<python> scripts/probe_pack_enums.py`. It re-checks the undocumented behaviour
  this skill relies on and exits 1 if anything moved.
- To prove the whole chain in Blender: `blender -b --factory-startup --python scripts/smoke_test_blender.py`
  (about 10 s; builds two test meshes, unwraps, grades, tests texel-density packing and that an overflow writes
  nothing). `<python> scripts/rizom_pool.py --selftest 3` proves parallel workers each get their own instance.

## 2. When RizomUV is worth it

| Mesh | Use | Why (measured, `references/distortion-and-quality.md`) |
|---|---|---|
| Curved or organic props, revolved bodies, anything without obvious seams | **RizomUV, organic preset** | urn angular p95 1.09 against 1.43 for Smart UV Project; Blender's unwrap cannot open a closed body by itself |
| Hard-surface kit pieces with structural seams marked | RizomUV, hard preset | zero distortion and 60% coverage; Blender's Minimum Stretch on the same seams is close (1.07, 56%) |
| Trim-sheet and tiling surfaces | neither: generate UVs where the mesh is built, at world scale | exact strip coordinates; RizomUV `Hotspot` only for irregular pieces |
| A lightmap UV2 in a hurry, no RizomUV | `blender-to-unity-vrchat/scripts/lightmap_uv2.py` | good enough for most bakes |

## 3. The pipeline

1. **Seams in the seed.** Mark the structural seams on the mesh (mitres, springing lines and apexes, the back line
   of revolved parts, material borders). They travel to RizomUV as split UV vertices in the seed topology;
   RizomUV's Auto adds its own on top. Without them an arch's U-shaped bands packed at 14% instead of 62%.
2. **Check the object**: a mesh with faces, no unapplied modifiers (they change what exports), a valid kind.
   Strongly non-planar quads: triangulate first (section 5).
3. **Load fileless**, seed UVs = 3D positions, world transform applied (read fresh, so a transform set earlier in
   the same script counts). Inputs are converted to plain ints and floats; a failed `Load` returns
   `{"Error": ...}` instead of raising, so it is checked.
4. **Auto seams** (`Select` with the preset's `Auto`, `Cut`, deselect), **Unfold** (5 iterations) and
   **Optimize** (25, `Mix 1`, `AngleDistanceMix 1.0`, flips and border intersections on).
5. **Pack the first channel and gate it**; on a failure climb the retry ladder. Still failing means review, not
   acceptance. The chosen layout is reloaded into RizomUV.
6. **Pack the other channels** (the lightmap UV) from exactly the chosen islands. Every pack does
   `IslandGroups DistributeInTilesEvenly` first (after a fileless load nothing is in a tile and `Pack` silently
   does nothing), packs on the CPU, and either fills the tile or packs at a texel density.
7. **Write only what fits**, in a fixed channel order: `UVMap` index 0 (Unity UV0), `UVMap_Lightmap` index 1
   (Unity UV1), other layers kept after them. A UV0 that does not fit writes nothing.
8. **Grade**: overlap, bounds, exact padding and margin, flips, fragmentation, texel density, coverage; keep
   RizomUV's stretch map of the written layout for review.
9. **Close** the instance in a `finally:` (sends `Quit`, waits for the exit, kills after a grace period).

`scripts/blender_rizom.py` does steps 2-9 for Blender objects; `scripts/rizom_uv.py` does them for any host that
can produce flat arrays; `scripts/rizom_pool.py` runs them in several processes at once.

## 4. Traps

| Symptom | Cause | Fix |
|---|---|---|
| Parallel jobs get each other's meshes back, or garbage errors | RizomUVLink's `RunRizomUV`: a launcher that loses the port lock waits for, and connects to, the other launcher's instance | `rizom_link.rizom_session()`: per-session port lock, own `rizomuv.exe`, listener PID checked |
| `Pack` does nothing; UVs come back at 3D scale | after a fileless `Load` the islands are in no tile | `IslandGroups({"Mode": "DistributeInTilesEvenly", "WorkingSet": "Visible"})` before every `Pack` |
| `Scaling.Mode`, `SpecifiedScale` or `TexelDensity` ignored | `Scaling.Optimization` defaults to `"Fill"`, which rescales the layout to the tile | `"Scaling": {..., "Optimization": "None"}` and `LayoutScalingMode` 1 |
| Texel density 100x too small | `TexelDensity` is read per 100 mesh units (centimetres) | `Scaling.Mode` 6 with `SpecifiedScale = px_per_unit / map_px` (`ru.pack_spec(..., px_per_unit=)`) |
| Islands unchanged after a texel-density pack, no error | the density does not fit in the tile | `fits` is False and nothing is written; bigger map, split the piece, or drop unseen faces |
| Texel density off by an object's scale | a transform set in the same script, `matrix_world` not yet updated | read the depsgraph's matrix (`blender_rizom` does) |
| Clean grade, overlaps in the exported mesh | unapplied modifiers (a Mirror doubles the mesh) | refused by default; `modifiers="apply"` bakes them in |
| Lightmap baked from the wrong UVs in Unity | an existing UV layer pushed UV0/UV2 to indices 1/2 | layers rebuilt in order: `UVMap`, `UVMap_Lightmap`, then the others |
| A linked duplicate ends up at the wrong density | two objects share one mesh; the last unwrap wins | one unwrap per mesh; the report lists each user's density |
| One quad grades 13x stretched, a re-ordered copy passes | fan triangulation picks the wrong diagonal of a non-planar quad | `uv_metrics.triangulate` (split the layout fits, reflex corner, ear clipping) |
| Mosaic (`QuasiDevelopable`) has no effect | `IslandPolyNBMin` unset, or `QuadLoopCutter` also on (it wins) | `IslandPolyNBMin: 1`; leave `QuadLoopCutter` out |
| A prop shatters into 40-100 islands | stretch limiter `Quality` 0.9 or above | 0.75; the gate's `islands_per_100_faces` catches it |
| Stretch map is one flat colour | default neutral; RizomUV grades **linear** scale | neutral = the layout's `sqrt(UV area / 3D area)` (`ru.stretch_map`) |
| Stretch map or other file missing, no error | relative path (RizomUV's working directory is its install folder) or missing folder: RizomUV writes nothing | absolute path, folder created, file checked (`ru.stretch_map` does all three) |
| `Pack` competes with a bake or a game for the GPU | `Device` defaults to `"FastestGPU"` (CUDA) | `pack_spec(..., device="CPU")` is the default here |
| Confusing failure several commands after a load | `Load` returned an error dict instead of raising | `ru.load` checks it |
| `Get` on group trees throws (`CSubMeshGroup`) | the tree does not serialise | `Count("Lib.Mesh.Islands")`, `Save({"Data": True})` |
| `Pack` returns empty `Coverages` | fileless mode | measure coverage yourself (`uv_metrics.report`) |
| `The parameter 'Global' is not recognized` | documented but rejected at the top level of `Pack` | put values in `Scaling`/`Rotate` directly, or per island with `IslandProperties` |
| `import RizomUVLink` fails | Python 3.14+, or the folder is not on `sys.path` | Blender's bundled 3.13; `rizom_link.import_link()` explains which |
| Invisible `rizomuv.exe` processes pile up | a script exited without `Quit`, or its host was killed | sessions close in `finally:`; on Windows a Job Object kills the instance with its host |
| Will not start from a scheduled task or SSH | headless still needs a desktop session | run in the logged-in session |

Pack enum integers (not published; measured): `Scaling.Mode` 0 OFF, 1 SET_3D_AREA, 2-5 average-ratio modes,
6 USER_SPECIFIED, 7 TEXEL_DENSITY, 8 PIXEL; `LayoutScalingMode` 0 DISABLED, 1 TRANSLATE_ONLY, 2 BEST_FIT,
3 FORCE_FIT. Details and the rest of the API: `references/api-cheatsheet.md`.

## 5. Presets and the gate

| | Hard surface | Organic |
|---|---|---|
| `SharpEdges.AngleMin` | 40 | 60 |
| Cutters | `PipesCutter`, `HandleCutter` | `PipesCutter`, `HandleCutter` (no `QuadLoopCutter`) |
| Mosaic | - | `Developability 0.8, IslandPolyNBMin 1, FitCones, AreaMinRatio 0.01` |
| Stretch limiter | `StretchLimiter {}`, `Quality 0.75`, `FlatteningMode 0` | same |

Gate for a texture channel (`uv_metrics.GATE`): angular p95 <= 1.15, p99 <= 1.5, max <= 2.0 (worst triangle that
is not a sliver), area p95 <= 0.20 (log2, inside islands), global area mean <= 0.05, islands per 100 faces <= 25
(skipped up to 12 islands). Non-finite UVs fail. Retry ladder: `Quality` 0.85, then Mosaic 0.9. A piece still
failing goes to review with its numbers and stretch map.

Grading triangulates like an exporter, never as fans: concave quads through the reflex corner, convex quads along
the diagonal their UV layout fits, n-gons by ear clipping. A strongly non-planar quad looks different depending on
the split the engine uses, so the report counts `split_sensitive_quads`; when that is not zero, triangulate the
mesh before unwrapping (Blender's Triangulate modifier, applied) so RizomUV, the grade and the engine agree.

Kind per object: the custom property `rizom_kind`, `"hard"` or `"organic"` (any case; `"baseline_organic"` exists
only as a comparison point). Why these values, and the sweep behind them: `references/distortion-and-quality.md`.

## 6. Texel density

Match texels per metre to what the headset shows at the nearest viewing distance (about 1150 / d px/m at 20 px
per degree), quantised into classes (512 / 256 / 128 / 64 px/m). Shared trims and tiling materials keep one
density everywhere; unique textures are sized `next_pow2(TD x sqrt(area / 0.65))` and packed at that density.
The lightmap UV defaults to a fixed 128 px pack; `uv2="footprint"` sizes it from the mesh's area at
`lightmap_texels_per_m` instead, which is what Unity and Bakery will give the renderer. Shared meshes: every
object using a mesh gets the same UVs, so objects at different world scales get different densities (the report
lists them). How to measure, assign and check it: `references/texel-density.md`.

## 7. Batches and parallel work

- One session serves any number of meshes: launching costs about 2-5 s, a few-hundred-face mesh about 0.3 s.
- Parallel work: separate processes, each with its own session (`rizom_pool.unwrap_many`, `run_commands`). They
  can start at the same instant: each session locks its own port and checks that the instance answering is its
  child. Never share a link between threads. Each instance takes a licence token.
- `unwrap_objects(..., timeout=600)`: an object that runs past the timeout, or a RizomUV crash, costs that object;
  the instance is restarted and the batch carries on.
- `priority="below_normal"` (or the `RIZOMUV_PRIORITY` environment variable) for batches that share the machine;
  packing runs on the CPU by default.
- Big meshes are slow in RizomUV's auto-seam (about 2.5 minutes at 200k faces, 2.2 GB): split them, or seam them in
  the generator and let Auto add little.

## Scripts

| Script | Host | What it gives |
|---|---|---|
| `scripts/rizom_link.py` | Python 3.6-3.13 | `find_rizomuv()`, `import_link()`, `RizomSession` (`start`, `close`, `restart`, `alive`, `deadline`), `rizom_session()` (private instance, guaranteed close, `link.port`, `link.session`) |
| `scripts/rizom_uv.py` | any Python | `PRESETS`, `RETRY_LADDER`, `resolve_kind`, `pack_spec`, `normalise`, `load`, `load_layout`, `cut_auto`, `unfold`, `island_count`, `save`, `pack` (returns `fits`), `stretch_map`, `linear_ratio`, `unwrap`, `unwrap_and_pack`, `unwrap_gated`, `texture_size`, `lightmap_footprint` |
| `scripts/uv_metrics.py` | numpy | `triangulate`, `distortion`, `texel_density`, `polygon_areas`, `raster`, `padding_gaps` (exact), `flipped_polygons`, `report`, `check_gate`, `GATE`; grades UVs from any tool |
| `scripts/blender_rizom.py` | Blender 4.2+ | `meshes_matching`, `check_object`, `mesh_arrays` (seams from `use_seam`), `uv_arrays` (grade an existing layer), `order_layers`, `write_uv`, `unwrap_object`, `unwrap_objects`, `unwrap_selected`, `save`, `checker_preview` |
| `scripts/rizom_pool.py` | Python 3.6-3.13 | `unwrap_many` (meshes across N processes), `run_commands` (any command lines, N at a time), `--selftest` |
| `scripts/smoke_test_blender.py` | Blender, background | end-to-end proof with expected numbers; exit 1 on failure |
| `scripts/probe_pack_enums.py` | Python 3.6-3.13 | re-verifies the Pack enums and the undocumented behaviour |

Load in Blender (or any Python): `import sys; sys.path.insert(0, r"<skill>/scripts"); import blender_rizom as br`,
then for example `br.unwrap_selected(kind="organic")`. Objects with modifiers are refused unless you pass
`modifiers="apply"` (destructive) or `modifiers="ignore"`. The scripts only change the UV layers they write (and
the mesh itself with `modifiers="apply"`, and a preview material if you call `checker_preview`).

## Report

`unwrap_objects(..., report_path=...)` writes, per object: RizomUV version, kind, the attempt used and every
attempt tried, islands and faces, gate failures, warnings (does not fit, mixed scales on a shared mesh, modifiers
applied), and per channel: fits and written, texel density, coverage, overlap, flips, exact padding and margin,
fragmentation and the distortion figures, plus the stretch map path. Say which pieces failed the gate or did not
fit, and why, rather than averaging them away.

## Lessons that cost time

- The first run's UVs came back at metre scale: `Pack` had silently done nothing (no tile after a fileless load).
- A checker can look fine in a viewport while p95 angular is 1.44; judge on the percentile and the stretch map.
- The default `Fill` made a texel-density pack look as if it worked: every island had one density, just not the
  one asked for. Compare the achieved density with the target every time.
- Three processes launched together all ended up on one RizomUV instance and swapped meshes without an error:
  RizomUVLink's launch lock makes the loser join the winner. Own the port and the process.
- Fan triangulation graded one folded quad on Suzanne at 13.3 and the same quad with its corners rotated at 1.4.
  A grade must not depend on where a polygon starts.
- RizomUV is not bit-deterministic on every mesh (Suzanne organic: 76-79 islands across calls, smaller meshes
  identical), while the grades held (angular p95 identical to 4 decimals). Regression checks compare metrics
  with tolerances, never hashes of the UVs.

Facts with a shelf life (measured on RizomUV 2027.0.598, 9 Oct 2026): the enum integers, the per-100-units texel
density, the Fill default, the silent overflow, the rejected `Global` and the launch-lock behaviour. Command
reference: `<RizomUV install>/doc/index.html` and the docstrings in `RizomUVLink/RizomUVLinkBase.py`; product site
https://www.rizomuv.com. Re-check with `probe_pack_enums.py` rather than trusting this page.
