# Stages in detail

For each stage: what goes in, what comes out, how to split it into tasks, and what QA checks. QA checklist letters
refer to `vrchat-world-qa` (stage 1 = C, 2 = S, 3 = P, 4 = B, 5 = M, 6 = U, 7 = X, 8 = A, 9 = E, 10 = N, 11 = L,
12 = I, 13 = O); every task also gets the general checks G1-G5. Without `vrchat-world-qa` installed, the QA agent uses
the minimum acceptance checks at the end of this file instead.

## Task ids

| Stage | Tasks |
|---|---|
| 1 | `T-MOCK-01` (one per zone, `T-MOCK-<ZONE>`, past three zones) |
| 2 | `T-SPEC-01` |
| 3 | `T-KIT-PLAN` |
| 1-3, `small` scale | `T-PLAN-01` in place of the three above |
| 4 | `T-GREY-<FAMILY>`, `T-GREY-ASM-<NAME>`, `T-GREY-MASTER` |
| 5 | `T-MOD-<FAMILY>`, `T-MOD-MASTER` |
| 6 | `T-UV-<FAMILY>` |
| 7 | `T-TEX-TRIM-LAYOUT` (a trim family only), `T-TEX-<FAMILY>` |
| 8 | `T-ASM-<NAME>`, `T-DRESS-<ZONE>` |
| 9 | `T-EXP-<FAMILY>` |
| 10 | `T-UNITY-IMPORT`, `T-UNITY-SYNC-ASM-<NAME>` per assembly then `T-UNITY-SYNC-MASTER`, `T-UNITY-SETUP`, `T-UNITY-PLATFORM` |
| 11 | `T-LIGHT` |
| 12 | `T-UDON-<ID>`, one per `interactivity` id |
| 13 | `T-OPT`, then `T-BUILD-<PLATFORM>` per platform (`T-BUILD-PC`, `T-BUILD-QUEST`, `T-BUILD-IOS`) |
| Any, after stage 4 | `T-RENAME-<PIECE>`, one per piece renamed after the greybox (`world-spec.md`, "Names"); `<PIECE>` is the old name in upper case with hyphens (`T-RENAME-EXT-DOOR-2X3-A`) |

Ids are upper case with hyphens: `<NAME>` is the assembly name without `ASM_` (`T-GREY-ASM-SHOPFRONT-A`), `<ZONE>` and
`<ID>` the spec id (`T-DRESS-SQUARE`, `T-UDON-SHOP-DOORS`). Add `-2`, `-3` when one family needs several tasks
(`T-UV-PROP-2`), and when a change after stage 4 needs work redone: a finished task is never re-run, so the change
gets a new task with the next number, limited to what changed (`T-UV-EXT-2` for one resized piece, `T-LIGHT-2` for a
re-bake; `world-spec.md`, "Changing the spec"). In `small` scale (one task for every family), kit tasks take
`WORLD` in place of the family: `T-GREY-WORLD`, `T-MOD-WORLD`, `T-UV-WORLD`, `T-TEX-WORLD`, `T-EXP-WORLD`. Only the ids change:
`<FAMILY>` in every path below is still each family's code, so `T-TEX-WORLD` writes `blender/textures/INT/`,
`blender/textures/STR/` and so on. `T-PLAN-01` records `stage: 2`, the stage its gate follows.

## Gate dependencies

Draft every task so that it waits for the gates through its `deps`:

| Task | Lists in `deps` |
|---|---|
| `T-KIT-PLAN` (full scale) | `gate:spec` |
| The first stage-4 tasks: `T-GREY-<FAMILY>` in small scale (full scale: they depend on `T-KIT-PLAN`) | `gate:spec` |
| Every `T-MOD-<FAMILY>` | `gate:greybox` |
| Every `T-TEX-<FAMILY>` but the lead family's (`look.lead_family`; `T-TEX-TRIM-LAYOUT` never waits), and every `T-EXP-<FAMILY>` | `gate:look` (`gates.look.after: [T-TEX-<LEAD FAMILY>]`; small scale: `[T-TEX-WORLD]`) |
| Everything else | Its real predecessors, which lead back to those |

The validator warns when a task of stage 4 or later cannot reach `gate:spec` through its `deps`, a task of stage 5
or later cannot reach `gate:greybox`, or a task of stage 9 or later, or a texture task other than the lead family's
and the trim layout, cannot reach `gate:look`. A plain dependency on `T-PLAN-01` or `T-GREY-MASTER` keeps the order
but lets the task start before the user approves. What happens to tasks under a gate that is not approved:
`ledger.md`, "Task lifecycle".

`T-RENAME-<PIECE>` takes the ledger's current `stage` when it is added (5 or later), and lists in `deps` `gate:spec`
(the rename re-opened it, so it waits for the user) and every task that writes one of its files and has started;
every task that writes one of its files and has not started lists the rename in its own `deps` (for a piece being
modelled: the next kit task, `T-MOD-MASTER`, the assembly task that uses it and that assembly's sync). Run the
validator with `--ledger` after adding it: each one-writer error names a pair still to order.

## Where each stage writes

Put these exact paths in each task's `writes` (relative to `<world>/`, or to the Unity project for `Assets/` and
`ProjectSettings/`). The validator warns on anything outside `world/`, `blender/`, `export/`, `Assets/`,
`ProjectSettings/` and the `@` editors.

**MASTER** in the table stands for `blender/MASTER.blend`, `blender/MASTER.snapshot.json` and
`blender/work/<task id>/` (the task's work files), plus `@blender-live` when `tools.blender_mcp` is true. Every task
that writes MASTER takes its turn, so the planner chains them through `deps` (families in the order the spec lists
them, then the assemblies, then the MASTER task of the stage); the validator rejects two that could run at once. A
task that runs long or headless tools (modelling, UVs, texturing, export) checks its family's pieces out to
`blender/work/<task id>/KIT_<FAMILY>.blend`, works there, and integrates them back (`blender-kit-library`, "Work
files"). Nothing writes `blender/kits/` or `blender/asm/`: the pipeline has no separate KIT or ASM files, and the
validator rejects a task that writes there.

| Stage | Writes |
|---|---|
| 1 | `world/mockups/` |
| 2-3 (or `T-PLAN-01`) | `world/spec.yaml` (every section but `version`, `world` and `tools`), `world/diagrams/`, `world/briefs/draft-tasks.yaml`; `world/mockups/` too for `T-PLAN-01` when `world.mockups` is true |
| 4-6, 8 | MASTER |
| 7 | `blender/textures/<FAMILY>/`, `blender/substance/<FAMILY>/` (also with the Blender fallback, which keeps its node-setup `.blend` there), and MASTER (the family's materials); `T-TEX-TRIM-LAYOUT` only `blender/substance/<FAMILY>/layout.md` |
| 9 | `export/fbx/<FAMILY>/`, and MASTER (`kit_status` only, with the export run on a checked-out work file) |
| 10 import | `Assets/World/Kits/<FAMILY>/`, `Assets/World/Editor/` (`blender-to-unity`'s `KitImport.cs`, first import only), `@unity` |
| 10 sync | `Assets/World/PlacementSync/` (the sync scripts, first sync only), `Assets/World/Assemblies/` (`ASM_<Name>_<Variant>.prefab`), `Assets/World/Scenes/`, `world/placements/`, `@unity`; its apply step also writes MASTER (placement sync runs its Blender steps through the MCP when the live Blender has MASTER open) |
| 10 setup | `Assets/World/Scenes/`, `Assets/World/Kits/<FAMILY>/` (static flags, instancing), `ProjectSettings/` (layers, collision matrix), `@unity` |
| 10 platform | `Assets/World/Kits/<FAMILY>/` (Android and iOS import overrides, mobile materials), `Assets/World/Scenes/` (per-platform objects), `ProjectSettings/`, `@unity` |
| 11 | `Assets/World/Scenes/` (lighting objects, lighting settings asset, lightmaps, occlusion data; with lighting states the baked copies under a `LIGHT_STATES` root outside MASTER's scope root, and the Mesh Renderers of the switched originals under MASTER turned off, the originals never moved, deleted or deactivated), `ProjectSettings/`, `@unity` |
| `T-RENAME-<PIECE>` | MASTER, the piece's `export/fbx/<FAMILY>/` file and `Assets/World/Kits/<FAMILY>/<Piece>/` folder (once they exist), `world/placements/` (after stage 10: the merge that carries the rename), `@unity` |
| 12 | `Assets/World/Scripts/`, `Assets/World/Scenes/`, `@unity` |
| 13 `T-OPT` | `world/reports/optimisation.md`, `Assets/World/Kits/<FAMILY>/` (import settings), `Assets/World/Scenes/`, `Assets/World/Editor/` (build-time scripts), `ProjectSettings/`, `@unity` |
| 13 `T-BUILD-<PLATFORM>` | `world/reports/build-<platform>.md`, `world/reports/publish-fields.md` (the first build task only), `Assets/World/Scenes/` (Pipeline Manager), `@unity` |

QA writes only `world/reports/qa/<task>/` (`small` scale: `world/reports/qa/stage-<n>/`). Only the master writes
`world/ledger.yaml` and the briefs in `world/briefs/` (the planner's `draft-tasks.yaml` is the one exception). Every
agent keeps its own scripts and scratch renders in the scratch folder its brief names, outside the project.

## 0 - Intake (master)

- In: the user's request.
- Do: detect what is installed (below), ask the intake questions in `SKILL.md`, then create the layout
  (`mechanics.md`), copy both templates, fill the spec's `world` and `tools` and the ledger's `intake`, and add the
  first tasks: `T-SPEC-01` (plus `T-MOCK-01` when `world.mockups` is true), or `T-PLAN-01` in `small` scale with
  `gates.spec.after: [T-PLAN-01]`.

| Detect | How |
|---|---|
| Blender CLI path (`tools.blender`) | `bpy.app.binary_path` through the Blender MCP; else `blender` on PATH, `Program Files\Blender Foundation\*`, portable unzips such as `~/.blender/blender-*`, Steam's `common\Blender`; else ask |
| Blender MCP (`tools.blender_mcp`) | A call to it answers. Its `search_assets` lists the asset libraries it reaches, for the generated-assets question |
| Unity project (`tools.unity_project`) | Unity MCP: `mcpforunity://instances` lists the open projects as `Name@hash`; the path is probably in `mcpforunity://project/info` (unverified: read both, and confirm the path with the user) |
| Packages and build modules (`tools.unity_packages`, `tools.build_modules`) | `Packages/vpm-manifest.json` and `Packages/manifest.json`; `BuildPipeline.IsBuildTargetSupported` through Unity MCP. UdonSharp and ClientSim ship inside the Worlds SDK since 3.4.0 (https://creators.vrchat.com/releases/release-3-4-0, checked 2026-10-17): never detect or add them as packages |
| Substance Designer and Painter | Substance MCP `sd_ping`, install folders. Painter is user-assisted unless a Painter bridge (an MCP or plugin) answers |
| Pipeline scale | The size of the brief, to propose `full` or `small` |
- Out: `world/spec.yaml` (version, world, tools and the template's budget ceilings), `world/ledger.yaml` with the
  first tasks.
- No QA. Moving on needs the user's answers.

## 1 - Mockups (concept artist; skipped if `world.mockups` is false)

- In: the brief, the reference images, `world.style`.
- Do: `mockups.md`. One hero view per zone, the key interiors, a material swatch sheet per family idea, and a
  street-level view of every facade that will be built from a kit.
- Out: `world/mockups/<view>.png` with `<view>.prompt.txt`.
- Tasks: one, or one per zone if there are more than three zones (each writes only its own files).
- QA: C1-C4. Then show the mockups to the user. This is not a gate, but take their feedback into stage 2.
- Skipped: record `skipped` in the ledger. Stage 2 then works from the reference images and the brief, and the
  views in the spec carry `matches: null`.

## 2 - Spec and diagrams (planner)

- In: brief, mockups, intake answers.
- Do: fill `spec.yaml` (`world-spec.md`; `example-spec.yaml` is a complete one): grid, families, budgets (with
  `lightmap.texels_per_m`, and `lightmap: false` on props too small to lightmap; per platform, `{pc: ..., quest:
  ...}`, when `world.quality` is `pc_lead`), pieces as far as known (`size` on lightmapped Free pieces; `ref` and a
  `detail` list of features with sizes for every piece players see up close), zones with rooms and openings, coarse
  placements, elevations for every kit-built facade, views matching each mockup, interactivity (with a local
  post-processing toggle, `sync: none`, when a PC world uses post-processing), lighting, and `look` (references,
  wear, lighting mood, the lead family, material targets: `world-spec.md`, "Look"). Run
  `spec_validate.py --footprints` until clean (it reports the lightmap fill), then `spec_to_svg.py` (it removes
  drawings of zones and elevations no longer in the spec).
- A light players switch: load `vrchat-lighting-and-baking`; the switch method comes from it. In a world with
  `quest` or `ios` that is lighting states, a baked copy of the zone's static geometry per state: set the zone's
  `lighting_states`, which the fill check multiplies in. A switch changes the light in one zone, so every piece it
  changes is placed in that zone: a room it lights inside a bigger zone becomes its own zone, and a facade shared
  with the street is placed in the switched zone (`world-spec.md`, "Lightmap check"). Never fall back to a realtime
  point light: it does not show on lightmapped Quest surfaces.
- Draft the stage 3-13 tasks into `world/briefs/draft-tasks.yaml`: a `tasks:` list in the ledger's task format
  (`status: todo`, `attempts: 0`, ids and `writes` from the tables above), checked with `spec_validate.py --ledger
  world/ledger.yaml --draft world/briefs/draft-tasks.yaml`.
- Out: `world/spec.yaml`, `world/diagrams/*`, `world/briefs/draft-tasks.yaml`.
- QA: S1-S7.
- Master, then: merge the draft into the ledger, set `gates.look.after` to the lead family's `T-TEX-<FAMILY>`
  (`look.lead_family`; `small` scale: `T-TEX-WORLD`), run the validator with `--ledger` and `--mermaid`.
- **Spec gate**: show the user the plans, elevations and mockups side by side, the platforms and budgets, the zone
  list, `tasks.mmd`, and anything you had to assume. Wait. "Changes requested" means editing the spec, regenerating
  and asking again.

## 3 - Kit plan (planner)

- In: approved spec.
- Do: complete `pieces` (every piece an elevation, room or assembly needs, plus corners, ends and trims), fix
  `families` (1-3 materials, texturing approach, texel density, map size, wall thickness), and
  `assemblies` (each with `uses` counts and `size`). Mark sockets (doorways, window openings) in piece `desc`.
  Validate, regenerate the diagrams, and when families or assemblies changed, update `draft-tasks.yaml` (one task per
  family and per assembly); the master checks it with `--draft` (a re-drafted task replaces its ledger copy) and
  swaps the changed tasks into the ledger. This planned completion, adding pieces or tightening budgets, does not
  re-open the spec gate; removing or renaming an approved piece, zone or elevation does (`world-spec.md`), so the
  report lists every rename and removal in `issues`, checked against `world/spec.approved.yaml`.
- Out: `world/spec.yaml`, `world/diagrams/`, `world/briefs/draft-tasks.yaml`.
- QA: P1-P4, S1, S3.
- Prefer one piece used many times over near-duplicates, and give the most repeated pieces 2-3 visibly different
  variants (different wear, a missing brick, another panel layout) so long runs do not read as copies. A variant that
  shares the family material costs a mesh, not a SetPass call; P3 checks that variants differ visibly.
- Texel density per family from the viewing-distance classes (`world-spec.md`, families); `detail_map: true` for
  tiling families players walk right up to, rather than a higher class across the whole world. Props players pick up
  or lean over (pickups, desk and counter items) get a family of their own at T1024 or T2048 (an atlas), not the
  room props' density.

## 1-3 in small mode - one planning task (planner)

- `T-PLAN-01` replaces `T-MOCK-01`, `T-SPEC-01` and `T-KIT-PLAN` when `world.scale` is `small`.
- Do: stage 1 if `world.mockups` is true, then stage 2 and stage 3 as written above, in one pass: the spec comes
  out with its pieces, families and assemblies already complete.
- Out: everything stages 1-3 produce: `world/mockups/` (if any), `world/spec.yaml`, `world/diagrams/`,
  `world/briefs/draft-tasks.yaml`.
- QA: one pass, S1-S7 plus P1-P4, plus C1-C4 when there are mockups, writing `world/reports/qa/stage-2/` (the task's
  `stage` is 2).
- Then the master merges the draft and asks at the **spec gate** (`gates.spec.after: [T-PLAN-01]`).

## 4 - Greybox (kit modellers, then the integrator)

- The first stage-4 task makes `blender/MASTER.blend` with `kit_library.py`'s `new_master()` (organising
  collections, `kit_layout = "single"`) and writes the first snapshot.
- `T-GREY-<FAMILY>`, one per family, one after another, each in `KIT/KIT_<FAMILY>` in MASTER: create each piece as a
  collection with simple box geometry at the exact extents of its Size, pivot at the bottom-left corner, openings cut
  where the spec says, `kit_status = grey`. Live through the MCP or headless (`mechanics.md`): `blender -b
  --factory-startup --python-exit-code 1 <file> --python <task>.py`, saving at the end with
  `preferences.filepaths.save_version = 0` set, so no `.blend1` backup appears beside the file.
- `T-GREY-ASM-<NAME>` (after the kits it uses): build the assembly as the one collection `ASM_<Name>_<Variant>` under
  `ASM` in MASTER, from instances of the pieces, with its `uses` counts.
- `T-GREY-MASTER` (after all of the above; integrator): place assemblies and pieces from the spec's placements in the
  `MASTER` collection. Add a 1.6 m and a 1.9 m scale figure per zone (local empties or simple meshes in a `REF`
  collection).
- QA: B1 for each KIT task (on MASTER's pieces of that family); B2-B3 for each `T-GREY-ASM` (on its assembly) and
  for `T-GREY-MASTER`; B4-B7 for MASTER.
- **Greybox gate**: walkthrough renders from every view plus top and elevation overlays. Show them to the user.
  This is the last cheap moment to change layout or scale.

Kit rules agents need even without other skills: piece = one collection named `<FAMILY>_<Type>_<Size>_<Variant>`,
mesh objects at identity transform, `instance_offset` zero, walls run along X with thickness in +Y, Size counts
modules in X, Y, Z skipping any axis under one module (thickness); MASTER and ASM never hold geometry. Full rules:
`world-spec.md`. Give kit agents this skill's `scripts/kit_library.py` path in the brief: `new_piece`, `place_piece`,
`changes_since`, `checkout`, `integrate`, `save_snapshot`, `save_file` (a headless save without a `.blend1`), and
`audit_kit` (`--audit --module <grid.module>` from the command line) to self-check before reporting.

## 5 - Kit modelling (kit modellers)

- `T-MOD-<FAMILY>` (checked out to a work file, modelled there, integrated back): replace each greybox
  mesh with final geometry **inside the same collection**, keeping name,
  pivot and extents. Model every feature in the piece's `detail` list at its size, to its `ref` images: relief deep
  enough to show in stereo at the nearest viewing distance is geometry, shallower relief goes to the normal map or
  the trim bevel, chamfers on every edge players see but never on faces that meet a neighbouring piece. When the
  piece's `lods` > 0: the main mesh becomes `<Piece>_LOD0`, with `<Piece>_LOD1` (about 50%) and `<Piece>_LOD2`
  (about 20%) as siblings in the collection. Collision per piece `collision`: a `<Piece>_COL` shell for `mesh`.
  `kit_status = modelled`.
- Brief: load `blender-mesh-topology` (finishing the form: what is geometry and at what size, real-world sizes for
  anything the detail list leaves open; then topology). Paste each piece's `detail` and `ref` into the brief.
- A piece with `bake: true` (ornament, carving, rivets, sculpted or cloth forms) also gets its high poly here, in
  `blender/bake/<FAMILY>_high.blend` (`<Part>_high` objects, one vertex group per part on the low), never in MASTER or
  a KIT file: built and gated by `blender-mesh-topology`'s high-and-low-poly reference (shading that bakes clean, the
  low's outline within 2 px, carving seen close keeping its depth step in the low). Gate and bake in that file with
  the piece's current low appended into it from the work file (never linked; an older copy removed first), and
  append again after any change to the low.
- Budget: `budgets.piece_tris.<FAMILY>`, or the piece's `tris`.
- QA: M1-M8, M10 (M10 only for `bake: true` pieces).
- `T-MOD-MASTER` (integrator, after every `T-MOD-<FAMILY>`, writes `blender/MASTER.blend`): spot-check the greybox
  views again with the modelled pieces. QA: M9.

## 6 - UVs (UV artists)

- `T-UV-<FAMILY>`: UV0 by the family's texturing approach (tiling to `texel_density`, trim onto the trim sheet
  layout, atlas or unique packed to `map_px`); a UV2 on every kit render mesh (LODs and probe-lit props too, not
  `_COL`), whose gaps matter on the lightmapped ones. `kit_status = uv`.
- Tiling UV0 with `uv-unwrapping`'s `tile_project` (U from each piece's own axes, phase 0 at its pivot), never Cube
  Projection, which centres on each piece so pieces of different sizes start out of phase; the family's tile divides
  `grid.module` and `grid.storey_height` (the validator holds the spec to it) or its `tile_phase` says how the pattern
  continues; outside corners covered by a trim or a corner piece.
- UV2 gaps come from each mesh's own lightmap square, not from the lightmap's size: padding for the whole map (8 px
  "at 512") silently assumes every piece gets the whole map. Pack them for the worst case, UV2 charts whose bounding
  box fills the tile: at least 2 texels at `texels_per_m x sqrt(A) x Scale In Lightmap` px, and at least 1 texel to
  the tile edge (`world-spec.md`, "Lightmap check"). A `<Piece>_LOD<n>` mesh gets its own atlas space at 0.5^n of
  that texel scale, so its gaps are sized at `texels_per_m x sqrt(A) x Scale In Lightmap x 0.5^n` px.
- Pack the UV2 charts to fill their bounding box, in any aspect ratio: Unity packs the box, so empty space inside it
  costs lightmap texels and lowers the texel density on the mesh (`uv-unwrapping` notes a box fill under 0.5).
- A is the modelled mesh's real surface area, measured per mesh at this stage, never the spec's bounding box: an
  opening or an open shell makes it much smaller (the example door bay: 11.04 m2 against 15.00 m2 for its box, so
  gaps sized from the box came out at 1.73 texels), and QA's U4 measures the real mesh. The spec's `--footprints`
  table plans the lightmap fill only. Per mesh:
  - `--map` = that square rounded down: with `uv-unwrapping`, `uv_audit.lightmap_footprint(ob, texels_per_m,
    scale, coverage=1, lightmapper=<lighting.baker>)`, which applies an LOD mesh's 0.5^n itself (from its `_LOD<n>`
    name); otherwise the formula `texels_per_m x sqrt(A) x scale x 0.5^n` with `qa_measure --lightmap-texels
    <texels_per_m>`'s `area_m2` as A, or without either skill the evaluated mesh's summed polygon areas
    (`sum(p.area for p in ob.evaluated_get(depsgraph).to_mesh().polygons)`);
  - `lighting.baker: bakery` changes that square: Bakery sizes a renderer by `texels_per_m x sqrt(2 x A x scale)`,
    the scale on the area, minus 6 texels and with no LOD factor (`vrchat-lighting-and-baking`, Bakery). Pass the
    spec's `lighting.baker` as `lightmapper=` to `pack_lightmap`, `lightmap_footprint` and `rizomuv-uv-pipeline`'s
    `unwrap_objects`, and as `--lightmapper` to the UV2 audit;
  - the gap = `2 / --map` in UV units, the Smart UV margin half of it;
  - put those numbers in the UV brief, and audit with `uv_audit ... --layer 1 --lightmap --map <--map> --pad 2`.
- Without `uv-unwrapping`: Smart UV Project with `margin_method='FRACTION'` and `island_margin` = half the mesh's
  gap. FRACTION leaves exactly twice the margin between islands and the margin itself at the tile edge (measured in
  Blender 5.2.2, 2026-10-17); the default `SCALED` left between 0.34 and 1.33 times it, depending on the mesh. UV0 of
  an atlas or unique map gets the same treatment: islands `map_px / 64` apart (16 px at 1024) and `map_px / 128` from
  the tile edge, which is Pack Islands (or Smart UV Project) with Margin Method Fraction and a margin of 1/128.
- Under 64 px a Free prop (a Free `PROP` or `FOL` piece) is probe-lit (`lightmap: false`; its UV2 needs no gaps),
  unless its zone has lighting states; every other piece, `ZONE` shells included, stays lightmapped whatever its size
  (the validator only notes it).
- Brief: load `uv-unwrapping`; also `rizomuv-uv-pipeline` when RizomUV is installed.
- QA: U1-U7 (U4 checks the gaps at the UV2's measured bounding-box share, with `lighting.baker` passed to
  `qa_measure` as `--lightmapper`; under Bakery it also gates each mesh's effective lightmap density; U7 the tiling
  phase).

## 7 - Texturing (texture artist)

- `T-TEX-<FAMILY>`: the family's materials (`M_<FAMILY>_<Name>`), trim sheet or tiling sets or atlas, unique prop
  textures, a detail map where the family has `detail_map: true`. `kit_status = textured`. Integrated with
  `materials="work"`, so the new materials replace MASTER's of the same name. Brief: load
  `pbr-texturing` (without it, `texturing.md`), with the spec's `look` and the family's `look.materials` targets.
- **Lead family first.** `look.lead_family`'s `T-TEX-<FAMILY>` runs alone; when its QA passes, the master stops at
  the **look gate** with QA's X5 look-dev renders and X8 numbers beside the mockups or `look.references`. Every other
  `T-TEX-<FAMILY>` and every `T-EXP-<FAMILY>` waits for `gate:look` (in `small` scale the one `T-TEX-WORLD` is the
  lead task, and its export waits). "Changes requested" re-opens the lead task with the user's words; the other
  families then start from the approved direction.
- Trim sheets come **before** UVs of the families that use them. When a family uses `trim`, schedule
  `T-TEX-TRIM-LAYOUT` first, which fixes the strip layout in `blender/substance/<FAMILY>/layout.md`, and make that
  family's UV task depend on it.
- An `atlas` family runs the other way round: its UV task packs every piece into the shared atlas, then
  `T-TEX-<FAMILY>` paints it, so the texture task depends on the UV task. Only an atlas laid out from existing
  textures (UVs placed onto a finished sheet) needs a layout task first, like a trim sheet.
- Seams and repetition: every signal of a unique map comes from 3D space (bakes, Object-coordinate procedurals,
  Box-projected images, tri-planar fills), so no UV seam shows; tiling maps are even at tile scale (`pbr_check.py
  --tiling`; `tile_flatten.py` when they fail) and carry no stand-out feature; `bake: true` pieces are baked from their
  highs in `blender/bake/<FAMILY>_high.blend` with the low as modelled appended into it, exploded where parts sit
  close, with the bake report kept beside the maps (`pbr-texturing`).
- QA: `T-TEX-TRIM-LAYOUT` X6; `T-TEX-<FAMILY>` X1-X5 and X7-X10.

## 8 - Assemblies and dressing (integrator)

- `T-ASM-<NAME>`: finish each assembly with final pieces (usually nothing to do but check, since pieces improved in
  place), add sockets. QA: A1-A5, M9.
- `T-DRESS-<ZONE>`: props and trims placed in MASTER from the spec's placements plus dressing for life (clutter,
  foliage), within budget. Variants ordered so no two identical ones touch and no sequence repeats; breakers
  (pilasters, doors, downpipes, props, decals) at irregular spacing along any run long enough to show the repeat
  (*practice*: one every 4-8 m along a facade, never at a fixed interval). QA: A1-A5, M9.

## 9 - Export (exporter)

- `T-EXP-<FAMILY>`: one FBX per piece collection into `export/fbx/<FAMILY>/<Piece>.fbx`. `kit_status = exported`.
  Export from a work file checked out just before, then set `kit_status` on the pieces in MASTER (live, or
  headless when MASTER is open nowhere); never integrate a work file only to carry the status.
- Brief: load `blender-to-unity` (its batch export exports each piece collection whole). Without it, use these
  settings: Limit to Selected, with every LOD and `_COL` object of the piece unhidden and selected (the exporter skips
  hidden objects without a word), Object Types Mesh, Scale 1.0, Apply Scalings FBX All, -Z Forward, Y Up, Apply Unit
  on, Use Space Transform on, Bake Space Transform (Apply Transform in the UI) on, Smoothing Face, Apply Modifiers on,
  Triangulate on, Tangent Space off (Unity calculates MikkTSpace tangents on import), Vertex Colors None, no
  animation, Path Mode Strip (kit pieces use the family's shared Unity material), embed off. Apply rotation and scale
  first. These are the FBX add-on's options, documented as "FBX (Legacy)" in the Blender 5.2 manual:
  https://docs.blender.org/manual/en/latest/files/import_export/fbx_legacy.html (checked 2026-10-17).
- QA: E1-E4.

## 10 - Unity assembly (Unity integrator, Unity MCP)

- `T-UNITY-IMPORT`: copy FBX files into `Assets/World/Kits/<FAMILY>/<Piece>/`, set import settings (Read/Write off,
  Generate Lightmap UVs off, no cameras or lights, Animation Type None, Tangents Calculate Mikktspace on
  normal-mapped materials and None otherwise, Mesh Compression Off: on kit pieces Medium already shifted tiling UVs
  up to 0.6 px at a joint and shrank 2-texel UV2 gaps to 1.8, measured in Unity 2022.3.22f1 on 2026-10-18), make
  family materials in `<FAMILY>/_Shared/` and remap by name (with the family's detail map where `detail_map` is set,
  on UV0, and emissive practicals' Global Illumination set to Baked; a Standard material made by script also enables
  the keyword of each map it uses, `_NORMALMAP`, `_METALLICGLOSSMAP`, `_DETAIL_MULX2`, `_EMISSION`, which only the
  inspector sets), turn `_COL` into a MeshCollider, make a prefab
  variant per FBX. `blender-to-unity` ships this as `KitImport.cs` (an import postprocessor plus prefab variants);
  its `Check()` output is N1-N3 evidence. QA: N1-N3.
- `T-UNITY-SYNC-ASM-<NAME>` for each assembly (it makes `Assets/World/Assemblies/ASM_<Name>_<Variant>.prefab`), then
  `T-UNITY-SYNC-MASTER`. Brief: load `blender-unity-placement-sync`; the first sync installs its Unity scripts.
  QA: N4-N5.
- `T-UNITY-SETUP`: VRChat project and scene setup (first: the SDK's Setup Layers for VRChat and Setup Collision
  Matrix, which a build otherwise fails on; then scene descriptor, spawns, respawn height, reference camera, layers,
  colliders for walkable areas), static flags, GPU instancing on the materials of repeated pieces, and a VRC Mirror
  Reflection at each of the spec's `zones[].mirrors` slots, off by default, with Reflect Layers per
  `vrchat-world-sdk-setup` (Player and MirrorReflection, never PlayerLocal), placed by the slot conversion in
  `world-spec.md`, "Mirrors" (not the -rot placement sync gives kit pieces). Brief: load `vrchat-world-sdk-setup`,
  `unity-batching-and-instancing`. QA: N6-N7 (N7 covers the mirror's Reflect Layers).
- `T-UNITY-PLATFORM` (cross-platform worlds): texture import overrides on both the Android and the iOS tab (1024 or
  below), mobile shader choice per material, per-platform objects (in a `pc_lead` world the PC-only extras too), the
  Android and iOS build modules present (a missing module is a user install: `flags.user_actions`). A
  `VRChat/Mobile/Standard Lite` material made by script gets its keywords set by the script too (its detail maps,
  emission, Bakery MonoSH and geometric specular anti-aliasing are shader features only its inspector switches on),
  and Metallic and Smoothness at 1 under a metallic-smoothness map, which it multiplies by them: a material switched
  from Standard keeps Metallic 0 and renders non-metal (`vrchat-world-sdk-setup`). Brief: load `vrchat-texture-and-vram` and `vrchat-world-sdk-setup` (cross-platform).
  Done here, not at the end, so every later stage is measured on the platform that is hardest to fit. QA: N8.
- Every Unity task lists `@unity` in `writes`: one Unity editor, one writer at a time.
- From here on, layout edits happen on either side and go through placement sync, never by re-exporting MASTER.
  After stage 11, in a zone with lighting states, edit the originals under MASTER (select them in the Hierarchy:
  their renderers are off, so a click in the Scene view picks a `LIGHT_STATES` copy, which sync never sees) or edit
  in Blender; a `T-LIGHT-<n>` then rebuilds the copies from the originals and re-bakes.

## 11 - Lighting and bake (lighting artist)

- `T-LIGHT`: lighting per `lighting` in the spec, light probes (plus VRC Light Volumes when installed), reflection
  probes, bake, with Lightmap Resolution = `budgets.lightmap.texels_per_m`. With `quest` or `ios` in the platforms,
  every light is Baked: a cross-platform world shares one bake, and Quest/iOS show no realtime shadows (Standard
  Lite takes the main directional light unshadowed; Lightmapped takes none). Then occlusion culling: bake it, and on
  each mirror untick Turn Off Mirror Occlusion unless objects flicker in the reflection. A piece with
  `lod_lightmap: false` gets Receive Global Illumination = Light Probes on its LOD1+ renderers. The lights follow
  `look.lighting_mood`; the final bake uses the lighting skill's final-quality settings, and its Directional Mode
  decision decides whether the normal maps show under baked light at all. On PC, when the Post Processing package is
  installed, the grading and bloom go on here too (the lighting skill's final look), kept out of the mobile builds.
  Brief: load `vrchat-lighting-and-baking`, and give it the `--footprints` table and the spec's `look`.
- A zone with `lighting_states` (the method is `vrchat-lighting-and-baking`'s):
  - The state copies, one set of the zone's static geometry per state, are made here in Unity under a `LIGHT_STATES`
    root outside MASTER's scope root, render-only (no colliders), so placement sync never sees them.
  - The placed originals under MASTER keep their place, their colliders and their placement-sync role, with their
    Mesh Renderers off. Never move, delete or deactivate them: moved or deleted, the next merge loses them;
    deactivated, their colliders go too.
  - During the bake, the copy whose state avatars should match sits at the origin inside the light probe group
    (baked probes stay where they were baked); the others sit far away, and every copy moves back afterwards.
  - A later placement sync that changes a switched piece needs a new `T-LIGHT-<n>`: rebuild the copies from the
    originals and re-bake. After stage 12 it keeps the state parents, which the `T-UDON` scripts reference, and
    rebuilds only their contents; its QA runs I1 as well as L1-L6.
  - Hand-off: tell the user that a layout edit in a switched zone goes to the originals under MASTER (selected in
    the Hierarchy) or to Blender, never to a copy, which the next `T-LIGHT-<n>` would overwrite.
- QA: L1-L7 (L6 checks the UV2 gaps at the square Unity actually gave each renderer, its `lightmapScaleOffset`; L7
  the final lit spec views in Unity against the mockups or `look`).

## 12 - Interactivity (Udon developer)

- `T-UDON-<ID>`, one per entry in `interactivity`: UdonSharp (it ships inside the Worlds SDK), event-driven, sync as
  specified. Brief: load `vrchat-udon`; for a light switch also `vrchat-lighting-and-baking`: every state copy stays
  enabled at load, and the script disables all but the starting one in `OnEnable`.
- QA: I1-I4.

## 13 - Optimisation audit and platform builds (optimiser)

- `T-OPT`: measure everything in `budgets` on the PC build, and estimate the mobile platforms from the Android and
  iOS import overrides (`vrchat-world-optimization`'s method; nothing switches the build target yet); fix in rank
  order of cost; re-measure. The real mobile builds are measured by `T-BUILD-<PLATFORM>`. Brief: load
  `vrchat-world-optimization`. Fixes that change geometry or UVs go back to the owning KIT task as new tasks,
  never patched in Unity, and Mesh Compression stays off on kit pieces (stage 10). QA: O1-O4.
- `T-BUILD-<PLATFORM>` (after `T-OPT`), one per platform in `world.platforms`, one at a time (`@unity`): switch the
  build target, clear SDK validation and console errors, measure that platform's budgets on the real build (on
  mobile, the 100 MB download limit too), Play-mode test with ClientSim, and on PC a Build & Test with two clients
  when the SDK is signed in. Blueprint ID: one project serves every platform, and its Pipeline Manager
  keeps the ID across build-target switches, so there is nothing to attach. A new world has no ID until the user's
  first upload creates it; every later platform upload from this project then uses it (`vrchat-world-sdk-setup`,
  cross-platform; only a separate copy of the project needs Detach and the ID pasted). Draft
  the publish fields (name, description, capacities, content warnings, tags, thumbnail) into
  `world/reports/publish-fields.md` and write `world/reports/build-<platform>.md`. The last build task switches the
  build target back to Windows (`vrchat-world-sdk-setup`, cross-platform). Brief: load `vrchat-world-sdk-setup`.
  QA: O5.
- The user's part, recorded in `flags.user_actions`: uploads, on-device Build & Test (Android over ADB, iOS over VTP),
  any multi-client test that needs their sign-in. Then tell the user the world is ready to upload on each platform,
  with the measured numbers, the drafted publish fields and that list.

## Minimum acceptance checks (when vrchat-world-qa is not installed)

The QA ids above are the route whenever `vrchat-world-qa` is installed: it has the measurements, scripts and verdict
format. Without it, a QA agent checks at least this, records what it measured, and says in its verdict that the
deeper checklist was unavailable.

| Stage | Minimum checks |
|---|---|
| Every task | Every output the brief lists exists; nothing outside its `writes` changed (file times against the dispatch time); names follow `world-spec.md`; the result matches the spec and its diagrams; the report's claims match what was measured |
| 1 | One image per requested view (a hero per zone, key interiors, swatches), each with its prompt file, consistent in style |
| 2-3 | `spec_validate.py` reports no errors, with `--draft` on the drafted tasks; the diagrams regenerate identically; budgets no looser than the platform targets; doors at least 1 x 2.1 m, ceilings at least 2.6 m; every family has 1-3 materials and a texturing approach; pieces are whole modules, with corners and ends or a reason |
| 4 | `kit_library.py --audit` reports no problems on MASTER, layout checks included; assemblies and the layout hold only instances (and `REF` aids); a top render of MASTER matches each plan, and each facade its elevation, within half a module; the 1.6 m and 1.9 m figures fit the doors and ceilings |
| 5 | The same audit with `kit_status` `modelled`; LOD0 triangles within budget; no n-gons, no edges shared by three faces, no loose geometry; pieces that meet share boundary vertices; LODs and collision as the spec says; every feature in each piece's `detail` list there at its size, judged against its `ref` images from eye height at the nearest walkable distance; nothing in MASTER is linked from another file |
| 6 | UV0 texel density within 10% of the family's (tiling and trim); no folded or badly stretched faces; a UV2 on every kit render mesh (not `_COL`), inside 0-1, no overlaps; on lightmapped ones, gaps of at least 2 texels at the mesh's real lightmap square (stage 6 above) and 1 texel to the tile edge |
| 7 | 1-3 materials per family, named `M_<FAMILY>_<Name>`; maps no larger than `map_px`; metallic in R and smoothness in A, normal maps OpenGL; dielectric base colours within 30-240 sRGB luma, raw metal 160 or more, metallic 0 or 1 except blends; colour, value and roughness against the mockups or `look` in a render that shows roughness (EEVEE or Cycles, not Workbench); tiling maps seamless in a 3 x 3 repeat; source files kept |
| 8 | No greybox left (every placed piece `textured` or later); grid pieces on the grid in 90-degree turns; no z-fighting at joints seen from walkable areas |
| 9 | One FBX per piece in `export/fbx/<FAMILY>/`; a re-import has scale 1, rotation 0 and the piece's size; triangle counts equal the audit's; two UV channels on every render mesh |
| 10 | One folder, FBX and prefab variant per piece; shared family materials, no extracted copies; Read/Write and Generate Lightmap UVs off, model roots at rotation 0; placement sync committed with no conflicts; VRChat layers and collision matrix set up, one scene descriptor, spawns on floors; Android and iOS overrides at 1024 or below |
| 11 | The bake reports no UV overlaps; lightmap count and size within budget; no seams or light leaks at joints; avatars lit everywhere (probes); every lightmapped renderer keeps at least 2 texels of UV2 gap at the square Unity gave it; each spec view, rendered in Unity, reads like the mockups or `look.references` and `look.lighting_mood` |
| 12 | Each interaction works in ClientSim; events rather than `Update()` loops; a late joiner sees the right state; no Udon console errors |
| 13 | Every budget measured per platform and within it; mobile builds under 100 MB; the worst view per zone measured; every platform builds with no SDK validation or console errors |

## Parallelism at a glance

| Can run together | Must wait |
|---|---|
| Mockup tasks for different zones; `T-TEX-TRIM-LAYOUT` beside any task (it writes only its `layout.md`) | Every task that writes MASTER (stages 4-9: kit, assembly, texturing, export and layout tasks), or drives the live Blender (`@blender-live`): one at a time |
| QA of one task while other tasks build, unless the QA drives a live editor: then it holds `@unity` or `@blender-live` like a task until it returns | ASM tasks wait for the kits they use; MASTER waits for ASMs; UVs of a trim family wait for its trim layout |
| Planning an Udon system (behaviour, sync, events) for its brief while other tasks build | Anything that drives the Unity editor (`@unity`) or writes into the open project's `Assets/` (a script dropped there recompiles the editor under another task): one at a time; lighting bake waits for final geometry and placements |
