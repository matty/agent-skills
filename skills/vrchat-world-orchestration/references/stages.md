# Stages in detail

For each stage: what goes in, what comes out, how to split it into tasks, and what QA checks. QA checklist letters
refer to `vrchat-world-qa` (stage 1 = C, 2 = S, 3 = P, 4 = B, 5 = M, 6 = U, 7 = X, 8 = A, 9 = E, 10 = N, 11 = L,
12 = I, 13 = O); every task also gets the general checks G1-G5.

Task ids: `T-<STAGE TAG>-<FAMILY or AREA>[-n]`, for example `T-MOD-EXT`, `T-UV-PROP-2`, `T-UNITY-MASTER`. In
`small` scale with one `KIT_World.blend`, kit tasks take `WORLD` in place of the family: `T-GREY-WORLD`,
`T-MOD-WORLD`, `T-UV-WORLD`, `T-TEX-WORLD`, `T-EXP-WORLD`.

## Where each stage writes

Put these exact paths in each task's `writes` (relative to `<world>/`, or to the Unity project for `Assets/`).
The validator warns on anything outside `world/`, `blender/`, `export/`, `Assets/`, `ProjectSettings/` and the `@` editors.

| Stage | Writes |
|---|---|
| 1 | `world/mockups/` |
| 2-3 (or `T-PLAN-01`) | `world/spec.yaml`, `world/diagrams/`, `world/briefs/draft-tasks.yaml` |
| 4-6 | `blender/kits/KIT_<FamilyName>.blend` (one task per file); ASM tasks `blender/asm/ASM_<Name>.blend`; MASTER `blender/MASTER.blend` |
| 7 | `blender/textures/<FAMILY>/`, `blender/substance/<FAMILY>/` (also with the Blender fallback, which keeps its node-setup `.blend` there), and the family's KIT file (materials) |
| 8 | `blender/asm/ASM_<Name>.blend`, `blender/MASTER.blend` |
| 9 | `export/fbx/<FAMILY>/`, and the KIT file (`kit_status` only) |
| 10 import, sync | `Assets/World/Kits/<FAMILY>/`, `Assets/World/Assemblies/`, `Assets/World/PlacementSync/` (sync scripts, once), `Assets/World/Scenes/`, `world/placements/`, `@unity`; sync applies also `blender/MASTER.blend` or the ASM file |
| 10 setup, platform | `Assets/World/Scenes/`, `Assets/World/Kits/<FAMILY>/` (static flags, instancing, import overrides), `ProjectSettings/` (layers, quality, build targets), `@unity` |
| 11 | `Assets/World/Scenes/` (lighting objects, lightmaps), `ProjectSettings/` (lighting), `@unity` |
| 12 | `Assets/World/Scripts/`, `Assets/World/Scenes/`, `@unity` |
| 13 | `world/reports/optimisation.md`, `Assets/World/Kits/<FAMILY>/` (import settings), `ProjectSettings/`, `@unity` |

QA writes only `world/reports/qa/<task>/`. Only the master writes `world/ledger.yaml` and the briefs in
`world/briefs/` (the planner's `draft-tasks.yaml` is the one exception).

## 0 - Intake (master)

- In: the user's request.
- Do: the intake questions in `SKILL.md`, then create the layout, copy the templates and fill in `world`, `tools`
  and `intake`.
- Out: `world/spec.yaml` (world and tools sections only), `world/ledger.yaml` with the stage 1-2 tasks.
- No QA. Moving on needs the user's answers.

## 1 - Mockups (concept artist; skipped if `world.mockups` is false)

- In: the brief, the reference images, `world.style`.
- Do: `references/mockups.md`. One hero view per zone, the key interiors, a material swatch sheet per family idea,
  and a street-level view of every facade that will be built from a kit.
- Out: `world/mockups/<view>.png` with `<view>.prompt.txt`.
- Tasks: one, or one per zone if there are more than three zones (each writes only its own files).
- QA: C1-C4. Then show the mockups to the user. This is not a gate, but take their feedback into stage 2.
- Skipped: record `skipped` in the ledger. Stage 2 then works from the reference images and the brief, and the
  views in the spec carry `matches: null`.

## 2 - Spec and diagrams (planner)

- In: brief, mockups, intake answers.
- Do: fill `spec.yaml` (`references/world-spec.md`): grid, families, budgets (with `lightmap.texels_per_m`, and
  `lightmap: false` on props too small to lightmap; the validator then checks the placed pieces fit), pieces as far as known, zones with
  rooms and openings, coarse placements, elevations for every kit-built facade, views matching each mockup. Run
  `spec_validate.py` until clean, then `spec_to_svg.py`. Draft the full task graph for stages 3-13 into the ledger
  and write `tasks.mmd`.
- Out: `world/spec.yaml`, `world/diagrams/*`, ledger tasks.
- QA: S1-S7.
- **Spec gate**: show the user the plans, elevations and mockups side by side, the platform and budgets, the zone
  list, and anything you had to assume. Wait. "Changes requested" means editing the spec, regenerating and asking
  again.

## 3 - Kit plan (planner)

- In: approved spec.
- Do: complete `pieces` (every piece an elevation, room or assembly needs, plus corners, ends and trims), fix
  `families` (KIT file, 1-3 materials, texturing approach, texel density, map size, wall thickness), and
  `assemblies` (each with `uses` and `size`). Mark sockets (doorways, window openings) in piece `desc`.
- Out: `world/spec.yaml`.
- QA: P1-P4, S1, S3.
- Prefer one piece used many times over near-duplicates. Every variant must earn its draw call.

## 1-3 in small mode - one planning task (planner)

- `T-PLAN-01` replaces `T-MOCK-01`, `T-SPEC-01` and `T-KIT-PLAN` when `world.scale` is `small`.
- Do: stage 1 if `world.mockups` is true, then stage 2 and stage 3 as written above, in one pass: the spec comes
  out with its pieces, families and assemblies already complete.
- Out: everything stages 1-3 produce: `world/mockups/` (if any), `world/spec.yaml`, `world/diagrams/`,
  `world/briefs/draft-tasks.yaml`.
- QA: one pass, S1-S7 plus P1-P4, plus C1-C4 when there are mockups.
- Then the **spec gate**, with `gates.spec.after: [T-PLAN-01]`.

## 4 - Greybox (kit modellers in parallel, then the integrator)

- `T-GREY-<FAMILY>`, one per KIT file, in parallel: create each piece as a collection in its KIT file with simple
  box geometry at the exact extents of its Size, pivot at the bottom-left corner, openings cut where the spec says,
  `kit_status = grey`. Headless: `blender -b --factory-startup <KIT> --python <task>.py`, saving at the end with
  `preferences.filepaths.save_version = 0` set, so no `.blend1` backup appears beside the file.
- `T-GREY-ASM-<name>` (after the kits it uses): build each assembly from linked pieces.
- `T-GREY-MASTER` (after all of the above; integrator; live Blender with `@blender-live` in `writes`, or headless
  when the Blender MCP is not connected, see rule 3 in `SKILL.md`): link and place assemblies and pieces from the
  spec's placements. Add a 1.6 m and a 1.9 m scale figure per zone (local empties or simple meshes in a `REF`
  collection).
- QA: B1-B7, for each KIT task and for MASTER.
- **Greybox gate**: walkthrough renders from every view plus top and elevation overlays. Show them to the user.
  This is the last cheap moment to change layout or scale.

Kit rules agents need even without other skills: piece = one collection named `<FAMILY>_<Type>_<Size>_<Variant>`,
mesh objects at identity transform, `instance_offset` zero, walls run along X with thickness in +Y, Size counts
modules in X, Y, Z skipping axes thinner than half a module; link with relative paths; MASTER and ASM never hold
geometry. Full rules: `world-spec.md`. Give kit agents this skill's `scripts/kit_library.py` path in the brief:
`new_piece`, `link_piece`, `reload_libraries`, and `audit_kit` to self-check before reporting.

## 5 - Kit modelling (kit modellers, parallel per KIT file)

- `T-MOD-<FAMILY>`: replace each greybox mesh with final geometry **inside the same collection**, keeping name,
  pivot and extents. LODs if the piece's `lods` > 0 (`_LOD1`, `_LOD2` at about 50% and 20%). Collision per piece
  `collision` (`_COL` shell for `mesh`). `kit_status = modelled`.
- Brief: load `blender-mesh-topology` for topology work.
- Budget: `budgets.piece_tris.<FAMILY>`, or the piece's `tris`.
- QA: M1-M8.
- `T-MOD-MASTER` (integrator, after every `T-MOD-<FAMILY>`, writes `blender/MASTER.blend`): reload libraries in
  MASTER and spot-check the greybox views again.

## 6 - UVs (UV artists, parallel per KIT file)

- `T-UV-<FAMILY>`: UV0 by the family's texturing approach (tiling to `texel_density`, trim onto the trim sheet
  layout, unique packed to `map_px`), UV2 for every lightmapped mesh. `kit_status = uv`.
- UV2 padding comes from each piece's own lightmap footprint, not from the lightmap's size: Unity gives every renderer
  its own square of the map, about `texels_per_m x sqrt(surface area / 0.7)` px (the validator's
  `lightmap_footprints`). Pad for 2 texels at that size (`uv_audit --map <footprint px> --pad 2`, or more), and put
  each piece's footprint in the UV brief. Padding for the whole map size (8 px "at 512") silently assumes every piece
  gets the whole map.
- Brief: load `uv-unwrapping`; also `rizomuv-uv-pipeline` when RizomUV is installed.
- QA: U1-U6.

## 7 - Texturing (texture artist)

- `T-TEX-<FAMILY>`: the family's materials (`M_<FAMILY>_<Name>`), trim sheet or tiling sets or atlas, unique prop
  textures. `kit_status = textured`. Process: `references/texturing.md`.
- Trim sheets come **before** UVs of the families that use them. When a family uses `trim`, schedule a
  `T-TEX-TRIM-LAYOUT` task first that fixes the strip layout, and make that family's UV task depend on it.
- An `atlas` family runs the other way round: its UV task packs every piece into the shared atlas, then
  `T-TEX-<FAMILY>` paints it, so the texture task depends on the UV task. Only an atlas laid out from existing
  textures (UVs placed onto a finished sheet) needs a layout task first, like a trim sheet.
- QA: X1-X6.

## 8 - Assemblies and dressing (integrator)

- `T-ASM-<name>`: finish each assembly with final pieces (usually nothing to do but check, since pieces improved in
  place), add sockets.
- `T-DRESS-<zone>`: props and trims placed in MASTER from the spec's placements plus dressing for life (clutter,
  foliage), within budget.
- QA: A1-A5.

## 9 - Export (exporter)

- `T-EXP-<FAMILY>`: one FBX per piece collection into `export/fbx/<FAMILY>/<Piece>.fbx`. `kit_status = exported`.
- Brief: load `blender-to-unity`. Without it, use these settings: Limit to Selected, Object Types Mesh, Scale
  1.0, Apply Scalings FBX All, -Z Forward, Y Up, Apply Unit on, Use Space Transform on, Bake Space Transform on,
  Smoothing Face, Apply Modifiers on, Triangulate on, Tangent Space only with normal maps, no animation, Path Mode
  Strip (kit pieces use the family's shared Unity material), embed off. Apply rotation and scale first.
- QA: E1-E4.

## 10 - Unity assembly (Unity integrator, Unity MCP)

- `T-UNITY-IMPORT`: copy FBX files into `Assets/World/Kits/<FAMILY>/<Piece>/`, set import settings (Read/Write off,
  Generate Lightmap UVs off, no cameras or lights, Animation Type None), make family materials in
  `<FAMILY>/_Shared/` and remap by name, make a prefab variant per FBX.
- `T-UNITY-SYNC-<scope>`: placement sync for each ASM scope, then MASTER. Brief: load
  `blender-unity-placement-sync`; first time, install its Unity scripts.
- `T-UNITY-SETUP`: VRChat scene setup (scene descriptor, spawns, respawn height, reference camera, layers,
  colliders for walkable areas), static flags, GPU instancing on the materials of repeated pieces. Brief: load
  `vrchat-world-sdk-setup`, `unity-batching-and-instancing`.
- `T-UNITY-PLATFORM` (cross-platform worlds): per-platform texture import overrides (1024 or below on Android),
  mobile shader choice per material, per-platform objects, Android and iOS modules present. Brief: load
  `vrchat-texture-and-vram` and `vrchat-world-sdk-setup` (cross-platform). Done here, not at the end, so every later
  stage is measured on the platform that is hardest to fit.
- Every Unity task lists `@unity` in `writes`: one Unity editor, one writer at a time.
- Subagents may not be able to read MCP resources (`mcpforunity://editor/state`). Brief them to read editor state
  through `execute_code` instead: `EditorApplication.isCompiling`, `isPlaying`, and the active scene's `isDirty`.
- QA: N1-N7.
- From here on, layout edits happen on either side and go through placement sync, never by re-exporting MASTER.

## 11 - Lighting and bake (lighting artist)

- `T-LIGHT`: lighting per `lighting` in the spec, probes or VRC Light Volumes, reflection probes, bake, with Lightmap
  Resolution = `budgets.lightmap.texels_per_m`. Brief: load `vrchat-lighting-and-baking`.
- QA: L1-L6.

## 12 - Interactivity (Udon developer)

- `T-UDON-<id>`, one per entry in `interactivity`: UdonSharp, event-driven, sync as specified. Brief: load
  `vrchat-udon`.
- QA: I1-I4.

## 13 - Optimisation audit (optimiser)

- `T-OPT`: measure everything in `budgets` on every platform build; fix in rank order of cost; re-measure. Brief:
  load `vrchat-world-optimization`. Fixes that change geometry or UVs go back to the owning KIT task as new tasks,
  never patched in Unity.
- `T-BUILD-<platform>` (after `T-OPT`), one per platform in `world.platforms`, run one at a time (`@unity`): switch
  the build target, clear SDK validation and console errors, Play-mode test with ClientSim, Build & Test with two
  clients, and set the Pipeline Manager to the same blueprint ID as the PC build. Brief: load
  `vrchat-world-sdk-setup`. Draft the publish fields (name, description, capacities, content warnings, tags,
  thumbnail) for the user.
- QA: O1-O5. Then tell the user the world is ready to upload on each platform, with the measured numbers and the
  drafted publish fields. Uploading is the user's: it publishes under their account.

## Parallelism at a glance

| Can run together | Must wait |
|---|---|
| Greybox/modelling/UV tasks for different KIT files | ASM tasks wait for the kits they use; MASTER waits for ASMs |
| Texturing a family while another family is modelled | UVs of a trim family wait for its trim layout |
| QA of one task while other tasks build | Anything that writes MASTER, or drives the live Blender (`@blender-live`): one at a time |
| Udon scripts written outside Unity, in parallel with other work | Anything that drives the Unity editor (`@unity`): one at a time; lighting bake waits for final geometry and placements |
