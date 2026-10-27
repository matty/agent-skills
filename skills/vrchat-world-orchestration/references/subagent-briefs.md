# Subagent briefs

A subagent starts with nothing: no conversation, no ledger, no memory of earlier attempts. The brief is everything
it knows. Write it to `world/briefs/<task>.md` and pass the whole text as the subagent's prompt.

## Template

```markdown
# <task id>: <title>

Do the work yourself: do not spawn subagents.

## Goal
<one or two sentences: what exists when you are done>

## Project
All paths are relative to <world folder, absolute>. The Unity project is <tools.unity_project>.
Scratch folder for your own scripts, renders and notes: <absolute folder outside the project>.

## Load these skills first
- <skill name>: <what for>
(If a skill is not available, say so in your report and follow the fallback below.)

## Inputs (read only)
- world/spec.yaml: sections <...>. Excerpt:
  <paste the relevant YAML: the family, the pieces, budgets, grid>
- <files, diagrams, mockups to work from>

## You may write ONLY
- <exact files or folders: the task's `writes` from the ledger>
- <@unity / @blender-live if this task owns that editor for its duration; otherwise do not touch it>
- your scratch folder
Anything else is out of bounds, including files you think need fixing. Report those instead.

## Steps
1. ...

## Tools and hosts
- Blender CLI: <path>. Run headless: blender -b --factory-startup --python-exit-code 1 <file> --python <script>.py
  (the exit code then shows an uncaught exception), the script in your scratch folder, and set
  bpy.context.preferences.filepaths.save_version = 0 before saving (no .blend1 backup).
- <single layout, a task that writes MASTER: "The user may edit MASTER too. Before changing it, run
  kit_library.py's changes_since on blender/MASTER.snapshot.json and keep everything the user changed; if your task
  must change the same thing, stop and return blocked with the diff lines. Edit live through the Blender MCP when it
  has MASTER open (never headless then), or check the pieces out to blender/work/<task id>/KIT_<FAMILY>.blend, work
  there, and integrate them back (it refuses if they changed meanwhile). End with changes_since once more (report
  anything you did not do), save, then save_snapshot." Paste blender-kit-library's "Editing alongside the user" when
  that skill is not installed.>
- Python and scripts: <world folder>/.venv/Scripts/python (has PyYAML), run from the world folder;
  <this skill, absolute>/scripts/spec_validate.py and spec_to_svg.py; other skills' scripts by their absolute path
  where the task uses them.
- <Blender MCP / Unity MCP / Substance MCP if this task owns them>

## Found on disk from the previous run (only on a re-dispatch after a crash or a partial or blocked return)
- <what exists, what is half done, what to keep and what to redo; the earlier brief and report, if any:
  world/briefs/<task>.attempt<n>-interrupted.md, world/reports/<task>.attempt<n>-interrupted.yaml>

## Acceptance checks (QA will run these; run them yourself first)
- <check id and plain words, with numbers from the spec>
- G1-G5, the general checks, in plain words: every output the brief lists exists where it says; nothing outside
  the files you may write changed; names follow the conventions; the result matches the spec and diagrams; your
  report's claims match what you measured.

## Fallbacks
- <what to do if a skill or tool is missing>

## Report
End your final message with exactly this block, and nothing after it:

    report:
      task: <task id>
      attempt: <n>
      status: complete | partial | blocked
      outputs: [<files written>]
      measurements: {<check id>: "<measured value>"}
      skills_used: [<names>]
      fallbacks_used: [<what and why>]
      issues: [<for QA or the master; if partial or blocked: what is missing, what would unblock it>]
```

On a retry after a QA fail, add a `## Previous attempt` section with the QA verdict's `fixes`, word for word, and say
that this is attempt N of 3. The previous brief and report stay beside it as `<task>.attempt<n>.*` (`ledger.md`). A
re-dispatch after a crash or a `partial` or `blocked` return keeps the attempt number and fills in "Found on disk from
the previous run" instead.

## QA brief

```markdown
# QA <task id> (attempt <n>)

Do the work yourself: do not spawn subagents. Load `vrchat-world-qa`. You did not build this and must not change it.
Project: <world folder, absolute>; Unity project: <path>. Scratch folder: <absolute folder outside the project>.
Stage: <n>. Checklist: <ids> plus G1-G5.
Builder's brief: world/briefs/<task>.md   Builder's report: world/reports/<task>.yaml
Spec excerpt: <same as the builder's>
Writable files of the builder (for G2): <list>. Dispatched at: <UTC time from the ledger log>
Settings snapshot (projects without git): world/reports/qa/<task>/pre/
Master edits since the builder returned (not the builder's doing): <file and what changed, or none>
Views and diagrams to compare (G4): <view ids, svg paths>
Look to judge against (X5, X8, L7, G4 per piece): <the spec's look, and the pieces' ref and detail, or "none: world.style">
Map size for the PBR check (X8): <the family's map_px>
Live editors you may drive: <@unity / @blender-live, read-only, or none> (the master holds them for you meanwhile)
Python and scripts (S1, S4, S7): <world folder>/.venv/Scripts/python; <this skill, absolute>/scripts/spec_validate.py
and spec_to_svg.py, run from the world folder (S7: spec_validate.py --ledger world/ledger.yaml, plus --draft
world/briefs/draft-tasks.yaml for a planning task)
Accepted deviations (cite as waived_by): <ledger log entries "deviation accepted: ...", or none>
Skills the user declined (`intake.skills_declined`): <list, or none>: checks that need them are not-run, owner user
Skills missing but not declined: <list, or none>: checks that need them are not-run, owner qa (verdict incomplete)
Save evidence under world/reports/qa/<task>/ and end with the verdict block from vrchat-world-qa.
```

**Stage QA brief (`small` scale).** The same, once per stage after the stage's last task returns, with a table in
place of the per-task lines, one row per task: id, checks, brief, report, writable files, dispatched at. Evidence and
one verdict block per task, as a YAML list, go in `world/reports/qa/stage-<n>/verdict.yaml`, `<n>` being the tasks'
`stage` (`T-PLAN-01`: stage 2).

## Filled example: stage 5, one family in the single MASTER

```markdown
# T-MOD-EXT: Model the exterior kit

Do the work yourself: do not spawn subagents.

## Goal
Every EXT piece (KIT/KIT_EXT in blender/MASTER.blend) has final geometry in place of its greybox, inside the same
collection, with the same name, pivot and extents. kit_status = modelled on each piece collection. Everything else in
MASTER, including anything the user changed, is as it was.

## Project
All paths are relative to C:/Users/me/Worlds/ExampleMarket. Scratch folder: C:/Users/me/AppData/Local/Temp/T-MOD-EXT/.

## Load these skills first
- blender-mesh-topology: finishing each piece's form (what is geometry, at what size, chamfers and joints) and clean
  low-count topology for the window and door surrounds
- blender-kit-library: kit piece rules
- blender-to-unity: mesh hygiene before export

## Inputs (read only)
- world/spec.yaml excerpt:
    grid: {module: 1.0}
    families: {EXT: {thickness: 0.3, materials: [M_EXT_Brick, M_EXT_Stone]}}
    budgets: {piece_tris: {EXT: 800}}
    pieces:
      - EXT_Wall_2x3_A (box), detail: ["plinth: 0.45 m high, 30 mm proud, chamfered top"]
      - EXT_Window_2x3_A (box), ref: [world/refs/sash_window_01.jpg], detail: ["reveal: 100 mm deep",
        "stone sill: 60 mm projection, 50 mm thick", "sash frame: 50 mm", "glazing bars: 20 mm"]
      - EXT_Door_2x3_A (box), detail: ["door lining: 70 mm architrave", "fanlight: 0.4 m tall", "step: 150 mm"]
    look: {wear: weathered, references: [world/refs/market_dusk_01.jpg, world/refs/shopfront_02.jpg]}
- world/diagrams/elevation_square_north_row.svg (and world/mockups/hero_square.png when there are mockups)
- Nearest walkable viewing distance of the facade: 1.5 m (the square's pavement)

## You may write ONLY
- blender/MASTER.blend, blender/MASTER.snapshot.json, blender/work/T-MOD-EXT/
- @blender-live (the user's Blender has MASTER open; drive it only through the Blender MCP)
- your scratch folder

## Steps
1. Through the MCP, load kit_library.py and run changes_since(r"//MASTER.snapshot.json"). Note what the user
   changed; if they edited an EXT piece, stop and return blocked with the diff lines.
2. checkout(r"//work/T-MOD-EXT/KIT_EXT.blend", [the EXT pieces]). Model on that work file headless: for each piece,
   the final mesh at the collection origin, replacing the greybox mesh data; keep the object name.
2. Keep the footprint exactly 2 x 0.3 x 3 m; window and door openings where the greybox has them.
3. Model every item of each piece's detail list at its size, to its references: relief that shows in stereo at
   1.5 m (blender-mesh-topology's detail_scale.py) is geometry, shallower relief is left to the textures; chamfer
   every edge players see, never a face that meets the next bay. A piece the spec marks bake: true also gets its
   high poly in blender/bake/EXT_high.blend (<Part>_high objects, one vertex group per part on the low), built and
   checked there with its low appended from the work file (high-and-low-poly reference, one scene for the gate and
   the bake); none of these three is marked.
4. Assign M_EXT_Brick and M_EXT_Stone only. Apply transforms. Set coll["kit_status"] = "modelled". Save the work
   file. Render each piece from eye height at 1.5 m and close up, beside its references, for your report.
5. Through the MCP: integrate(r"//work/T-MOD-EXT/KIT_EXT.blend", [the EXT pieces]). If it refuses, the user edited
   a piece meanwhile: return blocked with its message. Then changes_since once more (list anything you did not do in
   your report), bpy.ops.wm.save_mainfile(), save_snapshot(r"//MASTER.snapshot.json").

## Tools and hosts
- Blender CLI: C:/Users/me/.blender/blender-5.2.2/blender.exe, headless on the work file only (never on MASTER,
  which is open in the live Blender): blender -b --factory-startup --python-exit-code 1 <file> --python <script>.py,
  with bpy.context.preferences.filepaths.save_version = 0 set before saving.
- Blender MCP (execute_blender_code) for MASTER: changes_since, checkout, integrate, save, save_snapshot.

## Acceptance checks
- M1 names, identity transforms, pivot at the bottom-left corner, extents match Size
- M2 LOD0 <= 800 tris per piece
- M3 no n-gons, no edges shared by 3+ faces, no loose vertices
- M5 the three pieces share boundary vertices when snapped side by side
- G4 each piece matches its detail list (sizes within 10%) and references, from eye height at 1.5 m and close up
- G1-G5 as in the template

## Fallbacks
- No blender-mesh-topology: plain quads, no n-gons, merge by distance, and keep bevels to the front face only.

## Report
(the block above)
```

## Filled essentials for the other tasks

Expand each into the template: these are the parts that differ per task. Writes are always the task's row in the
`stages.md` write table, copied into the ledger's `writes`.

**Stage 1, T-MOCK-01 (concept artist).** Goal: hero view per zone, key interiors, one swatch sheet per family idea,
a straight-on view of each kit facade. Load: none (paste `mockups.md`). Checks: C1-C4. Fallback: none; the stage is
skipped without an image tool.

**Stage 2, T-SPEC-01 (planner).** Goal: a `spec.yaml` that validates, diagrams generated, stage 3-13 tasks drafted
into `world/briefs/draft-tasks.yaml` (the master merges them into the ledger). Load: none. Paste what drafting needs:
`world-spec.md` (and point to `example-spec.yaml`); from `stages.md` the task-id table, the write table and the gate
dependencies table; from `ledger.md` the `tasks[]` fields. Python and scripts: the venv's python and the absolute
paths of `spec_validate.py` and `spec_to_svg.py`, run from the world folder, with the commands: `spec_validate.py
world/spec.yaml --footprints`, `spec_to_svg.py world/spec.yaml --out world/diagrams`, and `spec_validate.py
world/spec.yaml --ledger world/ledger.yaml --draft world/briefs/draft-tasks.yaml`. When the brief has a light
players switch, also load `vrchat-lighting-and-baking`: it decides the switch method, and lighting states go in the
zone's `lighting_states`. Inputs: brief, intake answers, mockups. Checks: S1-S7.

**Stage 3, T-KIT-PLAN (planner).** Goal: complete `pieces`, `families`, `assemblies` (with `uses` counts), with
corners, ends and trims; diagrams regenerated and `draft-tasks.yaml` updated when families or assemblies changed.
The report lists in `issues` every approved piece, zone or elevation renamed or removed (compare with
`world/spec.approved.yaml`): those re-open the spec gate. Checks: P1-P4, S1, S3.

**Stages 1-3 in small mode, T-PLAN-01 (planner, `stage: 2`).** The three briefs above merged: mockups if
`world.mockups` is true, then a validating spec with pieces, families and assemblies complete, diagrams generated,
stage 4-13 tasks drafted. Load: none. Paste the same as for T-SPEC-01 (`world-spec.md`, the three `stages.md` tables,
the `tasks[]` fields, the script paths and commands; `vrchat-lighting-and-baking` for a switchable light), plus
`mockups.md` when there are mockups, which it then writes in `world/mockups/`. Checks: S1-S7,
P1-P4, plus C1-C4 with mockups; QA writes `world/reports/qa/stage-2/`.

**Stage 4, T-GREY-EXT (kit modeller).** Goal: every EXT piece as a collection of box geometry at its exact extents,
pivot bottom-left, openings cut, `kit_status = grey`. Load: `blender-kit-library`. Checks: B1. Fallback: the kit rules
in `world-spec.md` and this skill's `scripts/kit_library.py`.

**Stage 4, T-GREY-ASM-SHOPFRONT-A (integrator).** Goal: the one collection `ASM_ShopFront_A`, built from instances
of the pieces with the spec's `uses` counts, plus socket empties: `single`, under `ASM` in MASTER; `split`, in
`blender/asm/ASM_ShopFront_A.blend` from pieces linked by relative paths. Load: `blender-kit-library`. Checks: B2-B3 on
the assembly.

**Stage 4, T-GREY-MASTER (integrator, live Blender or headless without the Blender MCP).** Goal: the `MASTER`
collection laid out from `zones[].placements` with instances of pieces and assemblies (`split`: linked, relative
paths), scale figures per zone in `REF`. Checks: B2-B7, with overlays against `plan_<zone>.svg` and
`elevation_<id>.svg`.

**Stage 5, T-MOD-MASTER (integrator).** Goal: the greybox views spot-checked with the modelled pieces (`split`: MASTER
reloaded first, every link resolving). Checks: M9.

**Stage 6, T-UV-EXT (UV artist).** Goal: UV0 tiling at 512 px/m; a UV2 on every kit render mesh (LODs and probe-lit
props too, not `_COL`), inside 0-1, no overlaps; on the lightmapped ones, gaps of at least 2 texels packed for the
worst case (UV2 bounding box filling the tile) and at least 1 texel to the tile edge; `kit_status = uv`. Give the
world's `texels_per_m`, its `lighting.baker` and each piece's `lightmap_scale`, and have the builder size each modelled
mesh from its real surface area, not the spec table (which plans the fill only): `--map` =
`uv_audit.lightmap_footprint(ob, texels_per_m, scale, coverage=1, lightmapper=<lighting.baker>)` (a whole number,
rounded down; it applies an LOD mesh's 0.5^n itself, from its `_LOD<n>` name; Bakery's footprint has none), gap =
`2 / --map` in UV units,
Smart UV margin = half the gap, charts packed to fill their bounding box (`stages.md`, stage 6). Tiling UV0 by
`uv_audit.tile_project(pieces, tile_m=1.0, material="M_EXT_*")` (the 512 px tile at 512 px/m: 1 m, phase 0 at each
pivot), never Cube Projection, outside corners left to their trim. Load: `uv-unwrapping`
(+ `rizomuv-uv-pipeline` if RizomUV is installed). Checks: U1-U7, the UV2 audit run per mesh as `uv_audit ... --layer
1 --lightmap --map <--map> --pad 2`. Fallback: Smart UV Project with `margin_method='FRACTION'` and `island_margin` =
half the mesh's gap; UV0 of an atlas or unique map packed with Margin Method Fraction and a margin of 1/128 (islands
`map_px / 64` apart, `map_px / 128` from the edge); texel scaling; all noted in the QA brief.

**Stage 7, T-TEX-TRIM-LAYOUT (texture artist).** Goal: the trim sheet's strip layout (strip heights in pixels, which
strip is which trim) in `blender/substance/<FAMILY>/layout.md`, before the trim family's UVs. Load: none (paste
`texturing.md`). Checks: X6.

**Stage 7, T-TEX-EXT (texture artist).** Goal: `M_EXT_Brick`, `M_EXT_Stone` with base colour, normal and packed
metallic-smoothness maps at the family's `map_px` (channel plan in `texturing.md`), a detail map where the family
has `detail_map: true`, matching the swatch mockups, `look.references` and the `look.materials` targets, worn to
`look.wear`. Every signal of a unique map from 3D space (bakes, Object-coordinate procedurals, Box-projected
images); the tiling maps even at tile scale (`pbr_check.py --tiling`, `tile_flatten.py` when it fails); `bake: true`
pieces baked from their highs with `bake_maps.py` (`--explode` where parts sit close), the report kept beside the
maps. Load: `pbr-texturing` (without it, paste `texturing.md`); the Substance MCP if available. Paste the
spec's `look`. Self-check with `pbr_check.py` and `texture_seams.py` before reporting. When EXT is
`look.lead_family`, its QA's look-dev renders go to the user at the look gate. Checks: X1-X5, X7-X10.

**Stage 8, T-ASM-SHOPFRONT-A (integrator).** Goal: the assembly checked with final pieces, sockets added. Checks:
A1-A5, M9.

**Stage 8, T-DRESS-SQUARE (integrator).** Goal: props and trims placed from the spec, plus dressing within budget,
variants ordered so no two identical ones touch and no sequence repeats, breakers at irregular spacing on long runs.
Checks: A1-A5, M9.

**Stage 9, T-EXP-EXT (exporter).** Goal: one FBX per EXT piece in `export/fbx/EXT/`, `kit_status = exported`
(`single`: exported from a work file checked out just before, the status then set in MASTER). Load:
`blender-to-unity`. Checks: E1-E4. Fallback: the export settings listed in `stages.md`.

**Stage 10, T-UNITY-IMPORT (Unity integrator).** Goal: one folder, FBX and prefab variant per piece, family materials
in `_Shared/`, import settings as `stages.md` lists. Load: `blender-to-unity` (install its `KitImport.cs`, and end with
its `Check()` output in the report). Writes: the stage-table row, which includes `Assets/World/Editor/` for
`KitImport.cs` on the first import. Checks: N1-N3.

**Stage 10, T-UNITY-SYNC-MASTER (Unity integrator).** Goal: Unity's MASTER root matches Blender's MASTER, snapshot
committed (ASM scopes synced first). Load: `blender-unity-placement-sync`. Writes include MASTER.blend only through
the sync's apply step. Checks: N4, N5. Conflicts go to the master, who asks the user.

**Stage 10, T-UNITY-SETUP (Unity integrator).** Goal: VRChat layers and collision matrix set up first (self-check:
`UpdateLayers.AreLayersSetup()` and `UpdateLayers.IsCollisionLayerMatrixSetup()` both true), then scene descriptor,
spawns, respawn height, reference camera, colliders, static flags and instancing as planned in the brief, and a
VRC Mirror Reflection at each `zones[].mirrors` slot (paste them: centre, facing, size), off by default, with Reflect
Layers Player and MirrorReflection, never PlayerLocal. The SDK's VRCMirror prefab is a Unity Quad facing -Z: place it
at position (-x, z, -y) from the slot's centre, Y rotation 180 - rot, scale (width, height, 1). Load:
`vrchat-world-sdk-setup`, `unity-batching-and-instancing`. Checks: N6, N7 (N7 covers the mirror's layers).

**Stage 10, T-UNITY-PLATFORM (Unity integrator).** Goal: Android and iOS texture overrides (1024 or below), a mobile
shader per material, per-platform objects; a missing build module reported as a user action. Load:
`vrchat-texture-and-vram`, `vrchat-world-sdk-setup`. Checks: N8.

**Stage 11, T-LIGHT (lighting artist).** Goal: baked lighting within `budgets.lightmap`, avatars lit everywhere, every
lightmapped renderer keeping its UV2 gaps at 2 texels (paste the `--footprints` table); occlusion culling baked,
and Turn Off Mirror Occlusion unticked on each mirror unless objects flicker. A zone with `lighting_states`: one
render-only copy of its static geometry per state, built in Unity under a `LIGHT_STATES` root outside MASTER's scope
root so placement sync never sees them, by `vrchat-lighting-and-baking`'s method; the originals under MASTER keep
their place, colliders and placement-sync role with their Mesh Renderers off, and are never moved, deleted or
deactivated. A piece with `lod_lightmap: false`: Receive Global Illumination = Light Probes on its LOD1+ renderers.
A `T-LIGHT-<n>` after stage 12 keeps the state parents the `T-UDON` scripts reference and adds I1 to its checks.
Report, for the user: layout edits in a switched zone go to the originals under MASTER (selected in the Hierarchy)
or to Blender, never to the copies. Lights, colours and contrast follow `look.lighting_mood` (paste it); bake with the
lighting skill's final-quality settings. Writes: the stage-table row. Load: `vrchat-lighting-and-baking`. Checks:
L1-L7.

**Stage 12, T-UDON-SHOP-DOORS (Udon developer).** Goal: the interaction as described in the spec, synced as
specified, no `Update()`. Load: `vrchat-udon`; for a light switch also `vrchat-lighting-and-baking` (every state
copy enabled at load, all but the starting one disabled in `OnEnable`). Checks: I1-I4.

**Stage 13, T-OPT (optimiser).** Goal: every budget measured on PC and estimated for the mobile platforms from the
import overrides (the real mobile builds are T-BUILD's), and met; a report of the numbers.
Load: `vrchat-world-optimization`. Geometry or UV problems are reported back as new tasks, not fixed here. Checks:
O1-O4.

**Stage 13, T-BUILD-QUEST (optimiser).** Goal: the build target switched, the Quest budgets and the 100 MB limit
measured on the real build, SDK validation and console clean, ClientSim
walk passed, `world/reports/build-quest.md` written; uploads and on-device tests listed for the user. The Pipeline
Manager keeps the world's blueprint ID across target switches in this one project: nothing to attach. The last
build task ends by switching the build target back to Windows. Load: `vrchat-world-sdk-setup`. Checks: O5.

**Any stage after 4, T-RENAME-EXT-DOOR-2X3-A (integrator).** Goal: the piece renamed, and its FBX and Unity asset
once they exist: `single`, its collection renamed in MASTER (every instance follows); `split`, renamed in its KIT
file, the renamed collection linked in each ASM and MASTER file and the existing instances re-pointed
(`ob.instance_collection = <renamed collection>`). Never deleted and re-placed, so placement ids survive; after stage 10, a placement merge that carries the rename into Unity. Ordering: `stages.md`, "Gate
dependencies"; its `stage` is the ledger's stage when it is added. Load: `blender-kit-library`,
`blender-unity-placement-sync`. Writes: the stage-table row, with `world/placements/`. Checks: B2-B3, M9 (every
earlier placement keeps its id, position and rotation), and N4-N5 after stage 10.
