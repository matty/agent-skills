---
name: rizomuv-uv-pipeline
description: RizomUV from Python - auto seams, unfold and pack, batch-unwrap kit pieces from Blender, UVs stretched, overlapping or badly packed after RizomUV, Pack or texel density doing nothing, UV2 packed for its lightmap footprint, parallel batches. Needs RizomUV 2027.0.417+. Wins for driving RizomUV; seams, padding, density and UV2 rules (uv-unwrapping); lightmap budgets (vrchat-lighting-and-baking).
---

# RizomUV UV pipeline (headless, from Python)

The scripts start a private headless RizomUV, send it the mesh in memory, cut seams, unfold, optimise and
pack, grade the result, and write the UV layers back. A normal job is one call (section 3).

Padding per map size, the distortion gate, texel density classes and the UV2 authoring rules (2-texel gaps) belong
to the `uv-unwrapping` skill; lightmap resolution, the footprint numbers and Scale In Lightmap belong to
`vrchat-lighting-and-baking` (for Unity / VRChat). This skill states the same values and decides only how RizomUV
delivers them.

## 1. Before the first unwrap on a machine

1. Check the install once: `<python> scripts/rizom_link.py` prints the executable, its file version, the temp
   folder and the port, launches RizomUV headless and quits it. It needs **RizomUV 2027.0.417 or later** (headless
   mode; RizomUV 2027 shipped 8 Oct 2026). An older install is refused with a clear message: use `uv-unwrapping`
   instead, or pass `headless=False` to drive RizomUV with its window.
2. `<python>` is a Python 3.6-3.13 (3.9-3.13 on Linux and macOS): RizomUVLink has no 3.14 build. Run inside
   Blender, or use Blender's bundled Python, `<blender>/<version>/python/bin/python.exe`. RizomUV needs a
   logged-in desktop session (not a service, a scheduled task or SSH); each instance takes a floating licence token.

Then go straight to the unwrap: every unwrap is graded as it runs. The other install checks are for a RizomUV
upgrade or a pipeline that misbehaves on every mesh (`references/verifying-an-install.md`).

## 2. When to use RizomUV

| Mesh | Use |
|---|---|
| Curved or organic props, revolved bodies, anything without obvious seams | **RizomUV, `organic`**. Blender's unwrap cannot open a closed body by itself, and Smart UV Project leaves visible stretch on curves (urn angular p95 1.09 against 1.43). Its autoseams ignore where they show: on **upholstery, cushions and smooth furniture tops and fronts, mark the panel seams first** (the welt lines, one cut across the band on its hidden side, arms underneath), or they cut a stepped line across a seat's top that passes the gate (1.08 m on a test seat; section 7 `visible seams`) |
| Hard-surface kit pieces | RizomUV, `hard`, with the structural seams marked. On bevelled or 1-segment chamfered pieces `hard` can join the strips into one sprawling island (coverage 0.10-0.22) or one too long for a texel density to fit: the grade catches both and the organic preset takes over (0.53-0.75; a 2.4 m bevelled strip then fitted 2048 px at 512 px/m) |
| Trim-sheet and tiling surfaces | neither: UVs where the mesh is built, at world scale, and trim matching done by hand per `uv-unwrapping`. This skill does not automate RizomUV's `Hotspot` (interactive in RizomUV; the command is in `references/api-cheatsheet.md`) |
| No RizomUV 2027, or a lightmap UV2 only | `uv-unwrapping` |

## 3. Unwrap

**Inside Blender** (Python console, a script, or any tool that runs Python in a live Blender):

```python
import sys; sys.dont_write_bytecode = True; sys.path.insert(0, r"<skill>/scripts")
import blender_rizom as br
br.unwrap_selected(kind="organic")                                   # the selected meshes
br.unwrap_objects(br.meshes_matching("KIT_*"), kind="hard",          # a batch, with a report and stretch maps
                  lightmap_texels_per_m=20, report_path=r"<dir>/uv_report.json", stretch_dir=r"<dir>/stretch")
```

**A batch with no UI.** `--python-exit-code 1` makes a Python error exit 1; FAIL and REVIEW lines never do, so end
with `br.raise_on_failure(reps)` (`review=True` adds REVIEW). Only `br.save()` saves the .blend (no .blend1):

```
blender -b --factory-startup --python-exit-code 1 scene.blend --python-expr "import sys; sys.dont_write_bytecode = True; sys.path.insert(0, r'<skill>/scripts'); import blender_rizom as br; reps = br.unwrap_objects(br.meshes_matching('KIT_*'), kind='hard'); br.save(); br.raise_on_failure(reps)"
```

**Any other host**: build flat arrays in RizomUV's Data layout (documented at the top of `scripts/rizom_uv.py`):

```python
from rizom_link import rizom_session
import rizom_uv as ru
with rizom_session() as link:                    # one instance for the whole batch, always closed
    res = ru.unwrap_gated(link, mesh, kind="organic",
                          packs={"uv0": ru.pack_spec(1024), "uv2": ru.lightmap_spec(mesh, texels_per_m=20)})
uv0 = res["packs"]["uv0"]           # write back uv0["uvw_ids"], uv0["uvw"] corner by corner; see res["failures"]
```

One call loads the mesh fileless (world-space seeds, your seams cut), adds RizomUV's automatic seams, unfolds, packs
and grades UV0 (retrying, section 6), packs the lightmap UV from the same islands, writes UV0 when it fits (REVIEW
included) and the lightmap UV when it passes (`UVMap` at 0, `UVMap_Lightmap` at 1; nothing when UV0 does not fit),
prints one line per object and closes RizomUV. Launch: about 2 s; then 0.4-1.4 s per small piece (cubes: 0.73 s).

## 4. Options

Arguments of `unwrap_objects` and `unwrap_selected` (passed on to `unwrap_object`):

| Argument | Default | Use |
|---|---|---|
| `kind` | `"hard"` | `"hard"` or `"organic"` (section 6); the object's `rizom_kind` property wins |
| `uv0` | `pack_spec(1024)`: fill 1024 px, 16 px gaps, 8 px to the edge | `pack_spec(map_px, px_per_unit=512)` packs at an exact texel density (section 8). The gap is map_px / 64, the minimum (never less); the edge map_px / 128 |
| `directional` | `False` | `"grain"` (or `True`) lays each island's long side along U (wood, brushed metal); `"upright"` turns world up to +V (text, decals); the `rizom_directional` property wins |
| `uv2` | `"footprint"` | lightmap UV with gaps >= 2 texels for the smallest renderer of the mesh, a `<Piece>_LOD<n>` at 0.5^n of the scale (its own lightmap space); packed for 64 px when too small (section 7); `None` skips it |
| `lightmap_texels_per_m`, `lightmap_scale`, `lightmapper` | 20, 1.0, `"unity"` | the scene's Lightmap Resolution and Scale In Lightmap; the `rizom_lightmap_scale` property wins per object. `lightmapper="bakery"` when the scene bakes with Bakery (the world spec's `lighting.baker`; `"progressive"` is `"unity"`): the UV2 is packed and graded at Bakery's area-based footprint, (texels_per_m x sqrt(2 x area x scale) - 6) / the box's short side with no LOD factor, and the report warns when the charts get under half the planned texels per metre (section 8). One scene, one lightmapper: no per-object property |
| `modifiers` | `"refuse"` | `"apply"` bakes enabled modifiers into a mesh of the object's own, keeping the mesh name (destructive); `"ignore"` only for modifiers that cannot change the faces |
| `report_path`, `stretch_dir` | none | strict JSON report, one entry per object; `<object>_stretch.png` of each written UV0 |
| `gate` | `uv_metrics.GATE` | keys override the defaults and the rest stay (`{"angular_p95": 1.2}`); `float("inf")` switches one off |
| `timeout` | 600 s | per object; past it a separate process kills RizomUV, even mid-command (the call raises about 2 s later), and the batch restarts it and carries on. Kit pieces: 60 s is plenty (a few hundred faces take about 1 s); keep 600 for dense meshes (82k faces: 15-29 s idle, up to 158 s on a busy machine) |
| `priority`, `headless` | normal, `True` | `"below_normal"` or `"idle"` beside interactive work; `headless=False` shows RizomUV's window |

## 5. Prepare the mesh

- **Mark the structural seams** (`use_seam`): mitres and moulding corners, springing lines and apexes of arches,
  the back (least seen) line of revolved and swept parts, material borders, upholstery panels (section 2). RizomUV's
  Auto finds sharp edges and tubes, not structure: an arch without its seams packed at 14% coverage instead of 62%.
- **Unwrap in the KIT file.** Linked objects and meshes and library-override meshes are refused: UVs are lost on save.
- **Placed scale counts.** Texel density and the lightmap footprint are per metre of the object as placed. Linked
  duplicates share one set of UVs: the report lists each copy's density and footprint, and the lightmap UV is
  packed for the smallest; give a copy its own mesh (Make Single User) when its texture density matters.
- **Modifiers**: modifiers on in the viewport are refused (a Mirror doubles what exports). A Triangulate, Weighted
  Normal or Normal Edit never counts, is never applied or removed, and one off in the viewport is inactive. **After
  uv-unwrapping's `apply_stack`, use `modifiers="ignore"`; never `"apply"` on a hard-surface piece** (it used to bake
  the viewport mesh and drop its Triangulate and Weighted Normal: normals 12.59 deg off after export).
- **Strongly non-planar quads** (`split_sensitive_quads` not zero): apply a Triangulate, then unwrap again.
- **A seam only cuts where its ends reach a border or another seam**; one whose ends stay joined is dropped. Four
  seams across a table top's rim did nothing until its two edge loops were seams too (coverage 0.16 to 0.53).
- **Big meshes**: 82k faces auto-seam in 15-29 s idle (158 s busy), 200k in 2.5 min and 2.2 GB: split, or seam.

## 6. Presets, gate and retries

`hard` is for kit pieces, planar and developable parts and anything with its seams marked; `organic` for curved
bodies, revolved parts and props with no obvious seams (Auto settings, sweep: `references/distortion-and-quality.md`).

Every attempt is graded by `uv_metrics.grade()`: the distortion gate (angular p95 <= 1.15, p99 <= 1.5, max <= 2.0
over non-sliver triangles, area p95 <= 0.20, plus this grader's global area mean <= 0.05 and islands beyond a shell's
planar regions <= 25 per 100 faces, on shells cut into more than 12 islands), the layout (inside 0-1, no overlap,
padding and margin as asked, no flipped polygons) and, for a filled UV0 of up to 100 islands, coverage >= 0.35,
lowered for long thin pieces to 0.8 x what their shape allows (3D area / the largest connected shell's bounding-box
diagonal squared; a 3 m beam 0.16). On a failure the unwrap is retried with `Quality` 0.85, then Mosaic 0.9; a `hard`
pack that covers too little or does not fit goes straight to the organic preset. If every attempt fails, the least
failing one is kept and marked for review.

## 7. Read the result

Each object prints one line: state, object, kind, islands, coverage, angular p95, area p95, failures (or `gate ok`)
and notes, the attempt used and the time.

| State | Meaning | Do |
|---|---|---|
| `OK` | every written layer passed the grade and fitted | nothing |
| `OK` with `thin piece` or `many islands` | a square tile cannot hold a long thin piece better (a 3 m beam covers 0.16), or hundreds of islands: the map/64 gaps take the tile (a 5120-face rock: 0.21) | thin: a texel-density pack (`pack_spec(map_px, px_per_unit=TD)`) or a trim; many islands: accept it, or reduce surface detail first |
| `OK` with `visible seams N m` (advisory) | seams you did not mark run N m through smooth faces that face up or to the front (-Y): the grade measures distortion, not where the cuts are, and a tiling texture jumps there | look: `br.checker_preview(ob, cell_m=0.25)`; the report's `seams.visible_seam_bounds` says where. Upholstery, flat tops, fronts: mark the structural seams (section 5) and unwrap again. A body seen from every side (an urn 1.17 m, a rock 5.9 m): expected; move the long runs to the back with marked seams, or accept it on a unique (baked) texture |
| `REVIEW` with distortion failures | the best attempt still distorts | open its stretch map; add seams where it is strongly red or blue, or try the other `kind`; report it rather than accepting it |
| `REVIEW` with `coverage < X` | one sprawling island: a chamfer or bevel ring, a band (a table top's rim, a washer, a hoop) or an L or T plate | seams: along the chamfers; across the band together with its edge loops; at the L's corner. Rerun; report it if it stays |
| `REVIEW` with `islands_per_100_faces` | a shell cut into more islands than its planar regions (faces joined under the preset's SharpEdges angle, between seams): confetti | mark the structural seams or try the other `kind`; if those islands are the parts you want, pass `gate={"islands_per_100_faces": float("inf")}` |
| `REVIEW` with `padding` on over ~1000 islands | RizomUV's gap tops out near map_px / (2 x sqrt(islands)) at any map size, so map/64 is out of reach (1500 islands: 13 px of 16) | fewer islands (fewer cuts, merge small parts) or split the texture set; a bigger map does not help |
| `REVIEW` with overlap, flips, margin, or padding on a few islands | RizomUV's pack broke a rule | report it with the numbers; rerun once; the install checks if it repeats |
| `REVIEW` with `UVMap_Lightmap: 2-texel gaps fit only at N px` | a lightmapped piece (64 px or more) whose charts need a larger footprint: its UV2 is packed for N px | raise Scale In Lightmap by the factor given, or probe-light it if it is a Free prop; fewer islands also help. With nothing up to 8x passing, no UV2 is written and an older one is removed |
| `REVIEW` with `does not fit` | the texel density does not fit the map (a `hard` piece has already tried the organic preset) | first seams along the bevels or chamfers, or `kind="organic"`; then the next map size up (within the cap); only then split the piece or delete faces nobody sees |
| `FAIL` | an error or a timeout | read the message (often a refused modifier, a linked or override mesh, a .blend another job holds, or a broken mesh); `layers written:` says what changed |
| `SHARED` | a linked duplicate of an earlier object | uses that object's UVs; its report lists every copy's density and footprint |

- A note `lightmap N px under 64` (LOD0 only; LOD1+ follow their piece): probe-light a Free prop (a Free-sized PROP
  or FOL piece outside lighting-state zones), else raise Scale In Lightmap or the texels per metre. `UV2 packed for
  N px: too small`: packed for 64 px (then 2x, 4x, 8x), its footprint too small for 2-texel gaps: probe-lit only, or
  raise Scale In Lightmap by the report's factor. `UV2 box N% full` (advisory, 64 px and up): the box costs texels.
- Stretch map colours: **red = UV smaller than neutral** (fewer texels per metre), **blue = larger**, grey =
  neutral: judge distortion on them and angular p95; seams on `br.checker_preview(ob, cell_m=0.25)`, 25 cm world
  squares (no `cell_m`: a grid over the tile). Neither touches materials; `br.checker_clear(ob)` removes it.
- The report's fields, and grading UVs made any other way: `references/distortion-and-quality.md`. Say which
  pieces failed or did not fit, and why, rather than averaging them away.

## 8. Texel density and lightmaps

Choose the density with `uv-unwrapping` (about 1150 / d px/m at d metres; classes 2048 / 1024 / 512 / 256 / 128 / 64
px/m), size the map with `ru.texture_size(TD, area_m2)` and pack it exactly with `pack_spec(map_px, px_per_unit=TD)`.
A renderer's lightmap footprint is texels_per_m x sqrt(area / b) x Scale In Lightmap, b = the UV2 bounding-box share
(0.85 only to plan): gaps are packed for b = 1, so they hold at >= 2 texels, and checked at the measured b. How
RizomUV delivers both, and Bakery's sizing: `references/texel-density.md`.

## 9. Batches and parallel work

- One session serves any number of meshes: one `unwrap_objects` call or one `rizom_session` per batch. Never share
  a link between threads.
- **One Blender job per .blend.** Two jobs that save one file keep only the last save, and the others' UVs are lost.
  `unwrap_objects` and `br.save()` hold a lock file next to the .blend and refuse a second job, or a file another
  process saved since this one loaded it, a check that starts at the first `import blender_rizom` (if another
  process may have saved a file you opened before that, revert or reopen it). Other Blenders are not stopped.
- Parallel work: separate processes, 3-4 at most (a licence token each). `rizom_pool.run_commands(...,
  check=True)` runs `blender -b --python-exit-code 1` jobs, one .blend each; `rizom_pool.unwrap_many` takes plain
  meshes (`kind`, `packs` may be functions `(name, mesh)`), no Blender objects: properties, refusals, report lines
  and writing back are `blender_rizom`'s. Workers die with their host; a crash or a timeout costs one mesh.

## 10. Traps

| Symptom | Cause | Fix |
|---|---|---|
| `import RizomUVLink` fails | Python 3.14+, or the folder is not on `sys.path` | Blender's bundled Python; `rizom_link.import_link()` says which |
| "cannot run headless" | RizomUV older than 2027.0.417 | upgrade, `headless=False`, or `uv-unwrapping` |
| Will not start from a scheduled task or SSH | headless still needs a desktop session | run in the logged-in session |
| RizomUV or the host aborts at start (`Socket operation on non-socket`, `Bad file descriptor`) | a temp folder over about 90 characters breaks libzmq | the session gives RizomUV and its link a short one; set TMP and TEMP shorter if it still happens |
| Lightmap baked from the wrong UVs in the engine | an older layer at index 1 | the scripts order `UVMap`, `UVMap_Lightmap`, the rest, and remove a stale `UVMap_Lightmap` |
| Parallel jobs get each other's meshes back | `CRizomUVLink.RunRizomUV` used for parallel work | `rizom_link.rizom_session()` (own port, own process) |
| A parallel batch printed OK, then most UVs were missing | several Blender jobs saved one .blend | one .blend per job (the lock refuses the second) |

Own RizomUVLink calls (Pack doing nothing, density 100x off, flat stretch maps): read `references/api-cheatsheet.md`.

## Scripts

| Script | Host | What it gives |
|---|---|---|
| `scripts/blender_rizom.py` | Blender 4.2+ | `unwrap_selected`, `unwrap_objects`, `unwrap_object`, `raise_on_failure`, `meshes_matching`, `check_object`, `guard_blend`, `mesh_arrays`, `uv_arrays` (grade an existing layer), `world_area`, `renderers`, `order_layers`, `write_uv`, `save`, `checker_preview`, `checker_clear` |
| `scripts/rizom_uv.py` | any Python | `unwrap_gated`, `unwrap_and_pack`, `pack_spec`, `directional`, `lightmap_spec`, `lightmap_footprint`, `lightmapper_name`, `lightmap_capacity_px`, `lightmap_too_small`, `layer_report`, `layer_failures`, `pack` (returns `fits`), `PRESETS`, `RETRY_LADDER`, `load`, `load_layout`, `unfold`, `save`, `stretch_map`, `texture_size`, `mesh_area` |
| `scripts/rizom_link.py` | Python 3.6-3.13 | `rizom_session()` (private instance, guaranteed close), `RizomSession` (with `deadline()`), `FileLock`, `find_rizomuv()`, `exe_version()`, `import_link()`, `zmq_safe_temp()` |
| `scripts/uv_metrics.py` | numpy | `report`, `grade`, `check_gate`, `merge_gate`, `GATE`, `coverage_floor`, `shape_coverage_limit`, `distortion`, `texel_density`, `padding_gaps`, `bbox_share`, `flipped_polygons`, `visible_seams`, `visible_seam_warning`, `triangulate`, `json_safe`; grades UVs from any tool |
| `scripts/rizom_pool.py` | Python 3.6-3.13 | `unwrap_many` (meshes across N supervised processes), `run_commands` (any command lines, N at a time) |
| `scripts/probe_pack_enums.py`, `scripts/smoke_test_blender.py`, `rizom_pool.py --selftest` | install checks | only when `references/verifying-an-install.md` says so |

## Facts with a shelf life

Measured on RizomUV 2027.0.598, 9 and 17 Oct 2026: the Pack enums, per-100-units density, Fill default, silent
overflow, rejected `Global`, linear stretch grading, `Rotate.Initial` (re-checked by `probe_pack_enums.py`), a call
holding the GIL, the many-island gap cap. Read, not re-checked: the launch lock that makes `RunRizomUV` unsafe in
parallel. Sources: https://github.com/RemiArq/RizomUVLink (README, `RizomUVLink.py`, `RizomUVLinkBase.py`, examples;
checked 2026-10-17), `<install>/doc/index.html`, https://www.rizomuv.com/feature/rizomuv-2027-release-features/.
