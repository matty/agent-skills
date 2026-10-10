---
name: rizomuv-uv-pipeline
description: Drive RizomUV headless from Python through RizomUVLink to auto-seam, unfold, optimise and pack UVs with minimum distortion - fileless transfer from Blender, hard-surface and organic presets, exact texel-density packing, lightmap UV2, a distortion and padding gate with retries, stretch maps, and safe parallel batches. Use when RizomUV is installed and UVs need automating or batch processing, when UVs come out stretched, overlapping or badly packed, when enforcing texel density, or when RizomUV's Pack or texel density seems to do nothing; for UV technique in general (seams, padding, stacking, baking rules) see uv-unwrapping, for a Blender-only lightmap UV2 see blender-to-unity-vrchat.
---

# RizomUV UV pipeline (headless, from Python)

The scripts here start a private headless RizomUV, send it the mesh in memory, cut seams, unfold, optimise and
pack, grade the result, and write the UV layers back. A normal job is one call (section 2).

Go straight to the unwrap. Do not run the test scripts first: every unwrap is graded as it runs, and its report
says which pieces need a look. The install checks are only for a new machine, a RizomUV upgrade or a pipeline that
misbehaves on every mesh (`references/verifying-an-install.md`).

## 1. When to use RizomUV

| Mesh | Use |
|---|---|
| Curved or organic props, revolved bodies, anything without obvious seams | **RizomUV, `organic`**. Blender's unwrap cannot open a closed body by itself, and Smart UV Project leaves visible stretch on curves (urn angular p95 1.09 against 1.43) |
| Hard-surface kit pieces | RizomUV, `hard`, with the structural seams marked. Blender's Minimum Stretch on the same seams comes close; RizomUV packs tighter |
| Trim-sheet and tiling surfaces | neither: generate UVs where the mesh is built, at world scale. RizomUV `Hotspot` only for irregular pieces |
| A lightmap UV2 with no RizomUV | `blender-to-unity-vrchat/scripts/lightmap_uv2.py` |

## 2. Unwrap

Needs RizomUV 2027.0.417+ (headless mode), a Python 3.6-3.13 and a logged-in desktop session (headless draws
nothing but will not start from a service, a scheduled task or SSH). RizomUVLink has no 3.14 build: run inside
Blender, or use Blender's bundled Python, `<blender>/<version>/python/bin/python.exe`. Each running instance takes
a licence token on a floating licence.

**Inside Blender** (Python console, a script, or any tool that runs Python in a live Blender):

```python
import sys; sys.path.insert(0, r"<skill>/scripts")
import blender_rizom as br
br.unwrap_selected(kind="organic")                                   # the selected meshes
br.unwrap_objects(br.meshes_matching("KIT_*"), kind="hard",          # a batch, with a report and stretch maps
                  report_path=r"<dir>/uv_report.json", stretch_dir=r"<dir>/stretch")
```

**A batch with no UI** (the .blend is saved only when you call `br.save()`):

```
blender -b --factory-startup scene.blend --python-expr "import sys; sys.path.insert(0, r'<skill>/scripts'); import blender_rizom as br; br.unwrap_objects(br.meshes_matching('KIT_*'), kind='hard'); br.save()"
```

**Any other host**: build flat arrays in RizomUV's Data layout (documented at the top of `scripts/rizom_uv.py`):

```python
from rizom_link import rizom_session
import rizom_uv as ru
with rizom_session() as link:                    # one instance for the whole batch, always closed
    res = ru.unwrap_gated(link, mesh, kind="organic",
                          packs={"uv0": ru.pack_spec(1024, 8, 4), "uv2": ru.pack_spec(128, 4, 2)})
uv0 = res["packs"]["uv0"]                        # uv0["fits"], uv0["uvw_ids"], uv0["uvw"]: write back corner by corner
```

Pass a whole batch in one call: launching costs about 2-5 s, a few-hundred-face mesh about 0.3 s.

What one call does:

1. Loads the mesh fileless: world-space positions, seed UVs = those positions, your marked seams already cut.
2. Adds RizomUV's automatic seams for the preset, cuts, then Unfold (5 iterations) and Optimize (25).
3. Packs UV0 and grades it; on a failure climbs the retry ladder (section 5).
4. Packs the lightmap UV from exactly the chosen islands.
5. Writes the layers that fit: `UVMap` at index 0 (Unity UV0), `UVMap_Lightmap` at index 1 (Unity UV1), other
   layers kept after them. A UV0 that does not fit writes nothing. Nothing but UV layers changes, unless you pass
   `modifiers="apply"` or call `br.checker_preview`.
6. Prints one line per object (section 6) and closes RizomUV, even on an error.

## 3. Options

Arguments of `unwrap_objects` and `unwrap_selected` (passed on to `unwrap_object`):

| Argument | Default | Use |
|---|---|---|
| `kind` | `"hard"` | `"hard"` or `"organic"` (section 5). An object's custom property `rizom_kind` overrides it |
| `uv0` | `pack_spec(1024, 8, 4)`: fill a 1024 px tile, 8 px padding, 4 px margin | `br.ru.pack_spec(map_px, pad_px, margin_px, px_per_unit=512)` packs at an exact texel density instead (section 7) |
| `uv2` | `pack_spec(128, 4, 2)` | `"footprint"` sizes it from the mesh area at `lightmap_texels_per_m` (default 20); `None` skips the lightmap UV |
| `modifiers` | `"refuse"` | `"apply"` bakes enabled modifiers into the mesh (destructive); `"ignore"` only for modifiers that cannot change the faces |
| `report_path` | none | JSON report, one entry per object |
| `stretch_dir` | none | `<object>_stretch.png` per object: RizomUV's stretch map of the written UV0 |
| `gate` | `uv_metrics.GATE` | a dict with any subset of its keys, to loosen or tighten the gate |
| `timeout` | 600 s | per object; past it RizomUV is restarted and the batch carries on |
| `priority` | `RIZOMUV_PRIORITY`, else normal | `"below_normal"` or `"idle"` for batches that share the machine |

## 4. Prepare the mesh

- **Mark the structural seams** (`use_seam`): mitres and moulding corners, springing lines and apexes of arches,
  the back (least seen) line of revolved and swept parts, material borders. RizomUV's Auto finds sharp edges and
  tubes, not structure: an arch without its seams packed at 14% coverage instead of 62%.
- **Placed scale counts.** Texel density is per metre of the object as placed. Linked duplicates share one set of
  UVs, so copies at different scales get different densities (the report lists each); give them their own mesh
  when that matters.
- **Modifiers**: an object with enabled modifiers is refused, because its base mesh is not what exports (a Mirror
  doubles it). Apply them, or pass `modifiers="apply"`.
- **Strongly non-planar quads**: when the report's `split_sensitive_quads` is not zero, triangulate (Triangulate
  modifier, applied) and unwrap again, so RizomUV, the grade and the engine use the same split.
- **Big meshes**: auto-seam takes about 2.5 minutes and 2.2 GB at 200k faces. Split them, or mark the seams so
  Auto adds little.

## 5. Presets, gate and retries

| | `hard` | `organic` |
|---|---|---|
| For | kit pieces, planar and developable parts, anything with its seams marked | curved bodies, revolved parts, props with no obvious seams |
| `SharpEdges.AngleMin` | 40 | 60 |
| Cutters | `PipesCutter`, `HandleCutter` | `PipesCutter`, `HandleCutter` (no `QuadLoopCutter`: it switches Mosaic off) |
| Mosaic | - | `Developability 0.8, IslandPolyNBMin 1, FitCones, AreaMinRatio 0.01` |
| Stretch limiter | `StretchLimiter {}`, `Quality 0.75`, `FlatteningMode 0` | same |

Gate for a texture channel (`uv_metrics.GATE`): angular p95 <= 1.15, p99 <= 1.5, max <= 2.0 (worst triangle that
is not a sliver), area p95 <= 0.20 (log2, inside islands), global area mean <= 0.05, islands per 100 faces <= 25
(skipped up to 12 islands). Non-finite UVs fail. On a failure the unwrap is retried with `Quality` 0.85, then
Mosaic 0.9; if every attempt fails, the least distorted one is kept and marked for review.

Why these values, and the sweep behind them: `references/distortion-and-quality.md`.

## 6. Read the result

Each object prints one line: state, object, kind, islands, coverage, angular p95, area p95, gate failures (or
`gate ok`), the attempt used and the time.

| State | Meaning | Do |
|---|---|---|
| `OK` | passed the gate, every layer fitted and was written | nothing |
| `REVIEW` with gate failures | the best attempt still distorts | open its stretch map; add seams where it is strongly red or blue, or try the other `kind`; report the piece rather than accepting it |
| `REVIEW` with `does not fit` | the asked texel density does not fit the map | next map size up (within the cap), split the piece, or delete faces nobody sees |
| `FAIL` | an error or a timeout; RizomUV was restarted | read the message: often a refused modifier or a broken mesh |
| `SHARED` | a linked duplicate of an earlier object | uses that object's UVs; its report lists both densities |

- Stretch map colours: **red = UV smaller than neutral** (fewer texels per metre), **blue = larger**, grey =
  neutral. Judge on angular p95 and the stretch map, not on a viewport checker. `br.checker_preview(ob)` adds a
  colour-grid material for a quick look.
- The report (`report_path`) holds per object: RizomUV version, kind, the attempt used and every attempt tried,
  islands and faces, gate failures, warnings, and per channel: fits and written, texel density, coverage,
  overlap, flips, exact padding and margin, fragmentation, distortion and the stretch map path. Say which pieces
  failed or did not fit, and why, rather than averaging them away.
- To grade UVs made any other way (Blender's unwrap, a hand layout):
  `mesh, ids, uv = br.uv_arrays(ob, "UVMap")`, then `br.um.report(mesh, ids, uv, 1024, pad_px=8, margin_px=4)`
  and `br.um.check_gate(<report>["distortion"])`.

## 7. Texel density

Match texels per metre to what the headset shows at the nearest viewing distance (about 1150 / d px/m at 20 px
per degree), quantised into classes (512 / 256 / 128 / 64 px/m). Shared trims and tiling materials keep one
density everywhere; unique textures are sized `ru.texture_size(TD, area_m2)` (`next_pow2(TD x sqrt(area / 0.65))`)
and packed at that density with `pack_spec(..., px_per_unit=TD)`. The lightmap UV defaults to a fixed 128 px pack;
`uv2="footprint"` sizes it from the mesh's area at `lightmap_texels_per_m`, which is what Unity and Bakery will
give the renderer. How to measure, assign and check it: `references/texel-density.md`.

## 8. Batches and parallel work

- One session serves any number of meshes: use one `unwrap_objects` call or one `rizom_session` for a batch.
- Parallel work: separate processes, each with its own session (`rizom_pool.unwrap_many` for meshes,
  `rizom_pool.run_commands` for any command lines, such as several `blender -b` jobs). They can start at the same
  instant. Never share a link between threads. Each instance takes a licence token; 3-4 workers is plenty.
- An object that runs past `timeout`, or a RizomUV crash, costs that object; the instance restarts and the batch
  carries on.

## 9. Traps

Using the scripts:

| Symptom | Cause | Fix |
|---|---|---|
| `import RizomUVLink` fails | Python 3.14+, or the folder is not on `sys.path` | Blender's bundled Python; `rizom_link.import_link()` says which |
| Will not start from a scheduled task or SSH | headless still needs a desktop session | run in the logged-in session |
| Object refused | enabled modifiers | apply them, or `modifiers="apply"` |
| Clean grade, overlaps in the exported mesh | modifiers ignored with `modifiers="ignore"` that do change the faces | `modifiers="apply"` |
| A prop shatters into 40-100 islands | a custom `Auto` with stretch limiter `Quality` 0.9 or above | 0.75; the gate's `islands_per_100_faces` catches it |
| Mosaic (`QuasiDevelopable`) has no effect in a custom `Auto` | `IslandPolyNBMin` unset, or `QuadLoopCutter` also on (it wins) | `IslandPolyNBMin: 1`; leave `QuadLoopCutter` out |
| Lightmap baked from the wrong UVs in Unity | an older layer sat at index 0 or 1 | the scripts rebuild the order (`UVMap`, `UVMap_Lightmap`, then the rest); re-export |
| A linked duplicate ends up at the wrong density | two objects share one mesh at different scales | give it its own mesh (Make Single User) and unwrap it |
| Parallel jobs get each other's meshes back | `CRizomUVLink.RunRizomUV` used for parallel work | `rizom_link.rizom_session()` (own port, own process) |

Writing your own RizomUVLink calls (the scripts already handle all of these):

| Symptom | Cause | Fix |
|---|---|---|
| `Pack` does nothing; UVs come back at 3D scale | after a fileless `Load` the islands are in no tile | `IslandGroups({"Mode": "DistributeInTilesEvenly", "WorkingSet": "Visible"})` before every `Pack` |
| `Scaling.Mode`, `SpecifiedScale` or `TexelDensity` ignored | `Scaling.Optimization` defaults to `"Fill"` | `"Scaling": {..., "Optimization": "None"}` and `LayoutScalingMode` 1 |
| Texel density 100x too small | `TexelDensity` is read per 100 mesh units | `Scaling.Mode` 6 with `SpecifiedScale = px_per_unit / map_px` |
| Islands unchanged after a texel-density pack, no error | the density does not fit in the tile | measure the result; `ru.pack` returns `fits` |
| Stretch map is one flat colour | default neutral; RizomUV grades **linear** scale | neutral = `sqrt(UV area / 3D area)` of the layout (`ru.stretch_map`) |
| A file RizomUV should write is missing, no error | relative path (its working directory is its install folder) or missing folder | absolute path, folder created, file checked afterwards |
| Confusing failure several commands after a load | `Load` returned `{"Error": ...}` instead of raising | check it (`ru.load` does) |
| `The parameter 'Global' is not recognized` | documented but rejected at the top level of `Pack` | put values in `Scaling`/`Rotate`, or per island with `IslandProperties` |
| `Get` on group trees throws (`CSubMeshGroup`) | the tree does not serialise | `Count("Lib.Mesh.Islands")`, `Save({"Data": True})` |
| `Pack` returns empty `Coverages` | fileless mode | measure coverage yourself (`uv_metrics.report`) |
| `Pack` competes with a bake or a game for the GPU | `Device` defaults to `"FastestGPU"` | `"Device": "CPU"` (the `pack_spec` default) |
| Invisible `rizomuv.exe` processes pile up | a script exited without `Quit`, or its host was killed | `rizom_session()`: closes in `finally:`, and a Job Object (Windows) or a watchdog kills the instance with its host |

Pack enum integers (not published; measured): `Scaling.Mode` 0 OFF, 1 SET_3D_AREA, 2-5 average-ratio modes,
6 USER_SPECIFIED, 7 TEXEL_DENSITY, 8 PIXEL; `LayoutScalingMode` 0 DISABLED, 1 TRANSLATE_ONLY, 2 BEST_FIT,
3 FORCE_FIT. Every command and the rest of the undocumented behaviour: `references/api-cheatsheet.md`.

## Scripts

| Script | Host | What it gives |
|---|---|---|
| `scripts/blender_rizom.py` | Blender 4.2+ | `unwrap_selected`, `unwrap_objects`, `unwrap_object`, `meshes_matching`, `check_object`, `mesh_arrays` (seams from `use_seam`), `uv_arrays` (grade an existing layer), `order_layers`, `write_uv`, `save`, `checker_preview` |
| `scripts/rizom_uv.py` | any Python | `unwrap_gated`, `unwrap_and_pack`, `unwrap`, `pack_spec`, `pack` (returns `fits`), `PRESETS`, `RETRY_LADDER`, `load`, `load_layout`, `cut_auto`, `unfold`, `save`, `stretch_map`, `texture_size`, `lightmap_footprint` |
| `scripts/rizom_link.py` | Python 3.6-3.13 | `rizom_session()` (private instance, guaranteed close), `RizomSession`, `find_rizomuv()`, `import_link()` |
| `scripts/uv_metrics.py` | numpy | `report`, `check_gate`, `GATE`, `distortion`, `texel_density`, `padding_gaps`, `flipped_polygons`, `triangulate`; grades UVs from any tool |
| `scripts/rizom_pool.py` | Python 3.6-3.13 | `unwrap_many` (meshes across N processes), `run_commands` (any command lines, N at a time) |
| `scripts/probe_pack_enums.py`, `scripts/smoke_test_blender.py`, `rizom_pool.py --selftest` | install checks | only when `references/verifying-an-install.md` says so |

Facts with a shelf life (measured on RizomUV 2027.0.598, 9 Oct 2026): the enum integers, the per-100-units texel
density, the Fill default, the silent overflow, the rejected `Global` and the launch-lock behaviour. After a
RizomUV upgrade, re-check them with `probe_pack_enums.py` (`references/verifying-an-install.md`). Command
reference: `<RizomUV install>/doc/index.html` and the docstrings in `RizomUVLink/RizomUVLinkBase.py`; product site
https://www.rizomuv.com.
