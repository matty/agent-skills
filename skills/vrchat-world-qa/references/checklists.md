# QA checklists by stage

Every check a QA pass runs, the task each one applies to, and the tools behind them. Stage numbers follow the
world-build pipeline (the `vrchat-world-orchestration` skill). Spec fields (`budgets.piece_tris`, `grid.module`) refer
to the project's `world/spec.yaml`; without one, take budgets from the brief, else from the platform targets at the end
of this file, and say which in `expected`. A budget is one number for every platform or a mapping per platform
(`setpass: {pc: 100, quest: 50}`; `ios` takes the `quest` value when it has none): judge each platform against its own
value. Checks marked *advisory* can only produce `pass-with-notes`; every other check blocks.

## Checks per task

G1-G5 apply to every task. Run the rest for the task you are checking (`<FAMILY>` is `WORLD` when one
`KIT_World.blend` holds every family):

| Stage | Task | Checks |
|---|---|---|
| 1 | `T-MOCK-01`, or `T-MOCK-<ZONE>` per zone | C1-C4 |
| 2 | `T-SPEC-01` | S1-S7 |
| 3 | `T-KIT-PLAN` | P1-P4, S1, S3 |
| 1-3, small scale | `T-PLAN-01` | S1-S7, P1-P4; C1-C4 when there are mockups |
| 4 | `T-GREY-<FAMILY>` (a KIT file) | B1 |
| 4 | `T-GREY-ASM-<name>` (an ASM file) | B2, B3 |
| 4 | `T-GREY-MASTER` | B2-B7 |
| 5 | `T-MOD-<FAMILY>` | M1-M8, M10 |
| 5 | `T-MOD-MASTER` | M9 |
| 6 | `T-UV-<FAMILY>` | U1-U7 |
| 7 | `T-TEX-TRIM-LAYOUT` | X6 |
| 7 | `T-TEX-<FAMILY>` | X1-X5, X7-X10 |
| 8 | `T-ASM-<name>` (its ASM file), `T-DRESS-<zone>` (MASTER) | A1-A5, M9 |
| 9 | `T-EXP-<FAMILY>` | E1-E4 |
| 10 | `T-UNITY-IMPORT` | N1-N3 |
| 10 | `T-UNITY-SYNC-<scope>` | N4, N5 |
| 10 | `T-UNITY-SETUP` | N6, N7 |
| 10 | `T-UNITY-PLATFORM` | N8 |
| 11 | `T-LIGHT` | L1-L7 |
| 12 | `T-UDON-<id>` | I1-I4 |
| 13 | `T-OPT` | O1-O4 |
| 13 | `T-BUILD-<platform>` | O5 |
| Any, after 4 | `T-RENAME-<PIECE>` (a piece renamed after the greybox) | M9 (B2-B3 within it), N4-N5 after stage 10 |

**Single MASTER** (the default layout: `qa_measure` reports `layout: single`; the ledger's `intake.blend_layout`).
The pieces, assemblies and layout are collections in `blender/MASTER.blend`, so read the file-based checks this way:

| Check | In a single MASTER |
|---|---|
| `B1`, `M1`-`M8`, U, X, `E1` (the "KIT file") | The pieces of that family in MASTER (`qa_measure --pieces "<FAMILY>_*"` on MASTER), or on the work file the task left in `blender/work/<task>/` when MASTER is open in the live Blender (then confirm MASTER holds the same: G5) |
| `B2`, `A1` | The `ASM_` collections and the `MASTER` collection hold only collection instances, zone and socket empties; review aids in `REF`; no `layout_problems` (every piece inside `KIT`, every assembly inside `ASM`, both excluded from the view layer) |
| `B3` | Nothing is linked: `libraries` empty; no piece mesh duplicated into the layout or an assembly (no `stray_meshes`) |
| `M9`, `A2` | The kit_status and `instance_offset` of `pieces[]` in MASTER, in place of `linked_pieces[]`; every earlier placement unchanged unless the brief asked |
| `A3` | Compare only placements whose `assembly` is null with `zones[].placements`; the others are inside an assembly, compared with its `uses` |
| `G5` (nothing outside `writes`) | Also: the task kept the user's edits. Its report lists the `changes_since` lines it found before and after; anything the task changed that the user had changed is a fail unless the user agreed (the log says so) |

A builder's brief may list only some of these as its own acceptance checks; QA still runs the whole row. A task of a
kind not listed: run the checks of its stage that touch the files it writes, and say which in `notes`. A task split by
piece (`T-UV-PROP-2`) is checked on its own pieces: `qa_measure --pieces <its pieces>`.

## Tools

With the specialist skill a check names, use that skill's numbers; without it, the check's fallback (a `qa_measure`
field or a look) runs with this skill alone. These parts have no fallback and need their skill:

| Part | Skill |
|---|---|
| U1's distortion gate and UV0 padding; U5; U7 | `uv-unwrapping` |
| M10's gap and skew measures and matcap review | `blender-mesh-topology` |
| S4's regenerated plans and elevations (the pipeline's SVG script) | `vrchat-world-orchestration` |
| I2's payload limits | `vrchat-udon` |
| The stage 13 pre-upload audit (its `not_run` entry goes on O1) | `vrchat-world-optimization` |
| O5's validation while signed out (the SDK reflection checks) | `vrchat-world-sdk-setup` |

Without the skill, the part is `not-run` with `needs: <skill>`, and its owner follows one rule (the QA brief lists the
skills the user declined, from the ledger's `intake.skills_declined`):

> declined: not-run, owner user, passes with notes; missing but not declined: incomplete (owner qa) until the user installs or declines it.

| Name in the checks | What | Where |
|---|---|---|
| `qa_measure` | Blender-side measurements (fields below) and review renders: orthographic plans and elevations with SVG overlays (`--render`, `--overlay`), perspective spec views (`--view`), textured renders (`--color texture --light flat` or `studio`, Workbench: base colour only), look-dev renders through EEVEE with each material's own nodes (`--light lookdev`), wireframes (`--wire`), one piece or LOD at a time (`--isolate`, `--lod`, `--show-collision`, `--hide-object`), pixel statistics and brightened copies (`--image-stats`, `--gain`), FBX re-imports (`--import-fbx`), the tiling-seam metric (`--tile-seam`), the PBR value check of texture maps (`--pbr`, with `--map-px`, `--pbr-targets`, and `--pbr-tiling` or `--pbr-trim` for X4; it runs `scripts/pbr_check.py`, shipped identically in `pbr-texturing`), placement diffs (`--compare-placements`), lightmap footprints (`--lightmap-texels`, Bakery's with `--lightmapper bakery`), UV0 texel density (`--texel-map`) | `scripts/qa_measure.py`; its header lists every command |
| `texture_seams` | The colour or normal step across every UV seam of a textured mesh, and across the joints where placed pieces meet, against the texture's own step (X9) | `scripts/texture_seams.py`, shipped identically in `pbr-texturing`: `blender -b --factory-startup --python-exit-code 1 <file> --python texture_seams.py -- --objects <pattern> --image <map> [--kind normal] [--joints]` |
| `look` | The scene seen from a chosen camera | The Blender MCP `look` when it is connected; headless, `qa_measure --view <px py pz tx ty tz lens>` (any camera) or `--render` (orthographic) |
| UV audit | Distortion, texel density, padding, overlap, seams vs hard edges | Load `uv-unwrapping` (or `rizomuv-uv-pipeline` for its metrics) |
| Topology audit | Closed islands, joint matching between pieces, shading review renders | Load `blender-mesh-topology` |
| Spec validator | Schema, names, budgets, lightmap capacity, ledger graph | The validator that ships with `vrchat-world-orchestration`; without it, check the spec by hand against these lists |
| Placement report | Last merge and commit result per scope | `world/placements/<scope>.report.txt`, written by `blender-unity-placement-sync` |
| Unity MCP | Import settings, hierarchy, console, Stats, renders | MCP tools; `execute_code` for anything they do not expose |

### What qa_measure's fields prove

Run it on every .blend the task wrote (headless rule in SKILL.md), with `--module <grid.module>` (required on every
run that opens a .blend or imports FBX: there is no default), `--expect-status <the stage's kit_status>`,
`--sub-module <grid.sub_module>` when the world has trim, and `--json` into the evidence folder. Every PROBLEM line it
prints is a failure of the check listed here; NOTE lines are advisory. `objects` is a dict keyed by object name.

| Field | Means | Checks |
|---|---|---|
| `role` | `kit`, `asm` or `master` (from the file name, or `--role`), `fbx` after `--import-fbx` | B2, B3, A1 |
| `unnamed_collections` | Local collections holding meshes under a name that is neither a piece nor an assembly (`REF` aside) | G3 |
| `stray_meshes`, `ref_meshes` | Local meshes outside every piece collection; review aids in `REF` | B2, A1, G3 |
| `pieces[].kit_status` | The stage the piece reached; a PROBLEM line when it differs from `--expect-status` | G1, M1 |
| `pieces[].instance_offset`, `transform_issues`, `pivot_ok`, `size_ok`, `free_pivot`, `bounds_m`, `extent_modules` | Zero instance offset; identity transforms; grid pivot and Size; the Free pivot the bounds show | B1, M1, M6, E2 |
| `pieces[].lod0_tris`, `objects.<obj>.tris` | Triangles with modifiers applied; `--piece-tris` budgets | M2, M7, E3 |
| `objects.<obj>.ngons`, `edges_over_2_faces`, `loose_verts`, `loose_edges`, `boundary_edges`; `pieces[].coplanar_overlaps` | Topology hygiene | M3 |
| `pieces[].has_collision` | A `<Piece>_COL` shell is present | M8 |
| `objects.<obj>.uv_layers`, `uv` (each layer's `bounds` and `area`), `uv0_px_per_m`, `uv0_px_per_m_range`, `uv0_texel_cv` | UV layer count; UVs inside 0-1; UV0 texel density and its spread between islands with `--texel-map` | U2, U4, U6, E4 |
| `objects.<obj>.area_m2`, `uv2_bbox_share`, `uv2_short_side`, `uv2_box_fill`, `lightmap_px`, `effective_texels_per_m`, `effective_texels_min`, `uv2_charts`, `uv2_overlaps`, `uv2_min_gap_uv`, `uv2_min_gap_texels`, `uv2_edge_margin_uv`, `uv2_edge_margin_texels`; `lightmapper`; `notes` | Surface area; UV2's bounding-box share b, that box's short side and how much of it the charts fill; lightmap footprint with `--lightmap-texels` (Unity's, LODn at 0.5^n; Bakery's with `--lightmapper bakery`), the texels per metre the surface gets at it and, under Bakery, the gate's minimum; the UV2 charts, overlaps, smallest gap and tile-edge margin, in texels at that footprint; NOTE lines for LOD0 footprints under 64 px and for box fill under 0.5 at a footprint of 64 px or more | U4, U6 |
| `objects.<obj>.islands` | Connected parts of the mesh: more than the piece's visible parts means a hidden shell | M3 |
| `objects.<obj>.materials`, `pieces[].bad_materials` | Slot materials; names that are not `M_<FAMILY>_<Name>` | X1, E4, G3 |
| `images[]`: `size`, `missing`, `channels`, `colorspace`, `alpha_mode`, `relative`, `packed` | Every image a material uses (data only for role `fbx`) | X2, X3 |
| `libraries[]`: `relative`, `found` | Linked files resolve, by relative paths | B3, M9 |
| `linked_pieces[]`: `kit_status`, `tris`, `instance_offset` | What MASTER or an ASM file sees of each linked piece | A2, M9 |
| `local_assemblies`, `local_assembly_offsets`, `linked_assembly_offsets`, `appended`, `shadowing_linked` | Local copies of pieces or assemblies; assembly offsets, local and linked | B3, A1, M9 |
| `placements[]`: `kind`, `id`, `pos`, `rot_z`, `on_grid`, `right_angle`, `rot_xy_ok`, `scale_ok`; `placement_changes` | Where every instance sits (grid rules print PROBLEM lines for `kind` grid only; TRIM on `--sub-module`); what changed since a previous report, matched by placement id first (an id that vanished or changed is listed) | B4, A3, M9, N5 |
| `fbx_folded_materials` | Materials the importer copied as `<name>.NNN` because an earlier file brought them, folded back | E4 |
| `tile_seam`, `image_stats`, `renders` | Seam ratios; pixel mean, min and max on the 0-255 scale, and coverage | X4, L3, G4 |
| `luma_p1`, `luma_p50`, `luma_p99`, `clipped_share`, `crushed_share` | In each `image_stats` and `renders` entry: luma percentiles (Rec. 709 weights, 0-255) and the shares of pixels with any channel at 250 or more (clipped) and with luma 5 or less (crushed) | L7, X5, L3 |
| `pbr` | One entry per material from `--pbr`: its maps, the base-colour, metallic-smoothness and normal-map statistics, and its problems and notes; each problem is also in `problems` as `pbr <material>: ...`, each note in `notes` | X8 |

## General checks (every task)

| Id | Check | How |
|---|---|---|
| G1 | Outputs listed in the brief exist and are where it said, including the `kit_status` the stage sets on every piece it touched (`grey` at stage 4, `modelled` 5, `uv` 6, `textured` 7, `exported` 9) | List files; `qa_measure --expect-status <status>` |
| G2 | Nothing outside the brief's writable files changed (edits the QA brief lists as the master's do not count) | Below |
| G3 | Names follow the convention at every stage: pieces `<FAMILY>_<Type>_<Size>_<Variant>`, assemblies `ASM_<Name>_<Variant>` (one per ASM file, named after it), materials `M_<FAMILY>_<Name>` (the name part may hold underscores: `M_EXT_Brick_Dark`; the check catches `Material.001` or `wood`) | Blender files: `qa_measure` `unnamed_collections` empty, no `bad_materials`, and in KIT files no `stray_meshes`; the spec's names: spec validator; Unity: asset names through Unity MCP |
| G4 | Matches the approved mockup, plan, elevation and spec views (planning stages: the diagrams match the spec and the spec matches the brief). A stage's own visual checks (B4, B7, X5, L7) are G4's evidence there; a task that writes only a KIT file is judged piece by piece (`references/visual-review.md`, "One KIT piece") against each piece's `desc` and Size and, where the spec gives them, its `ref` images and `detail` list: every listed feature modelled at its stated size (within 10%, house guidance), seen close up and from the piece's nearest walkable viewing distance at eye height (1.6-1.7 m) | `references/visual-review.md` |
| G5 | The builder's report block is complete and its claims match what you measured | Compare |

### G2: what changed, and what never counts

1. A git project: `git status --porcelain`, plus `git diff --name-only <commit>` when the QA brief gives the commit
   at dispatch (anything committed since).
2. Otherwise: files modified after the dispatch time in the QA brief (UTC: convert local file times first), or,
   failing that, after the builder brief's own modification time.
3. A follow-up the master asked for within the same attempt counts as the builder's work.
4. `ProjectSettings/*.asset` newer than dispatch: compare values with the snapshot the master takes at dispatch
   (`world/reports/qa/<task>/pre/`); a re-save with no value change does not count. Without a snapshot, say in
   `notes` that a value change cannot be ruled out.
5. A file in `Packages/` with a new date: compare it with the package zip the Creator Companion keeps
   (`%LOCALAPPDATA%/VRChatCreatorCompanion/Repos/<package>/<package>-<version>.zip`, observed 2026-10-16); identical
   bytes do not count.
6. Anything else outside the writable files fails G2. One exception: a stray `.blend1` backup next to a writable
   `.blend` leaves G2 `pass`, with the file listed in `notes` for deletion and a reminder to the builder that headless
   saves set `save_version = 0` first.

| Never counts against the builder | Paths |
|---|---|
| Pipeline paperwork | `world/ledger.yaml`; `world/spec.approved.yaml` (the master's copy of the spec at each gate approval); `world/briefs/` (briefs for later tasks are written while a task runs); `world/reports/<task>.yaml`; `world/reports/qa/`; `world/diagrams/` regenerated by the master (`tasks.mmd` at every dispatch) |
| Edits the master logged in the ledger or listed in the QA brief | Spec edits, skill fixes during a dry run, any other file the ledger log records as the master's |
| Files the Unity editor rewrites on its own (scene open, script compile, Play) | `*.csproj`, `*.sln`, `Library/`, `Temp/`, `Logs/`, `UserSettings/`; `Assets/SerializedUdonPrograms/`; UdonSharp program assets (`Assets/UdonSharp/UtilityScripts/`, the `.asset` beside each UdonSharp script); `Packages/**/WorldQualitySettings.asset`; `ClientSimStorage/`; `ProjectSettings/*.asset` re-saved with no value change |

## Stage 1 - Mockups

| Id | Check | How |
|---|---|---|
| C1 | One image per view the brief asked for: a hero per zone, key interiors, material swatches, a straight-on view of each kit-built facade | List `world/mockups/` |
| C2 | Each mockup is consistent with the brief's style, era and palette; no two contradict each other on the same element | Look side by side |
| C3 | Prompts recorded next to each image (`<name>.prompt.txt`) so a variant can be regenerated | List files |
| C4 | *advisory* Readable as buildable from a modular kit: repeated bays, clear storey lines | Look |

## Stage 2 - Spec and diagrams

| Id | Check | How |
|---|---|---|
| S1 | Spec validates with no errors, grid-placement errors included (grid pieces on `grid.module` and in 90 deg steps; the TRIM family on `grid.sub_module`): QA's B4 and A3 apply the same rule, so a spec that breaks it cannot be built to pass | Spec validator |
| S2 | Every zone in the mockups has a zone in the spec, and the reverse | Compare |
| S3 | Every piece used in an elevation or plan is in `pieces`, and every piece is used somewhere | Spec validator reports both |
| S4 | Plans and elevations regenerate from the spec and match the committed SVGs | Regenerate with the pipeline's SVG script into `world/reports/qa/<task>/regen/` (never over `world/diagrams/`), diff |
| S5 | Budgets present and, for every platform in `world.platforms`, no looser than its targets (the Android and iOS column for `quest` and `ios`; a per-platform mapping is read per platform) | Compare with the platform targets at the end of this file |
| S6 | Dimensions are human-scale: doors >= 2.1 m high and >= 1 m wide, ceilings >= 2.6 m, stairs rise <= 0.2 m per step, corridors >= 1.5 m wide (house guidance: VR players are taller than their avatars suggest and need room to turn) | Read the spec, check the plans; the validator checks doors and ceilings |
| S7 | Task graph has no cycles, every task has an owner role, and every `writes` path is the project-layout path for its stage (QA is implicit for every build task) | Spec validator with the ledger, or with a copy of the ledger with the drafted tasks merged in; it warns on paths outside the layout. Compare paths with the pipeline's stage write table |

## Stage 3 - Kit plan

| Id | Check | How |
|---|---|---|
| P1 | Each family has a file path (`blender/MASTER.blend` in the single layout, its KIT file when split), a material list of 1-3 materials and a texture approach (trim / tiling / atlas / unique) | Spec |
| P2 | Pieces snap: widths and heights are whole modules; corner and end pieces exist for every wall family, or the piece `desc` says why none is needed and the plan bears it out (for example walls that overlap in the corners and never end in open space) | Spec, plans |
| P3 | Repeated elements are one piece used many times, not near-duplicates (`_A`/`_B` must differ visibly) | Spec, elevations |
| P4 | Texel density and map size set per family, consistent across families seen side by side | Spec `families.*.texel_density`, `map_px` |

## Stage 4 - Greybox

| Id | Check | How |
|---|---|---|
| B1 | Every piece in the KIT file has identity object transforms and a zero `instance_offset` (a non-zero one draws every placement of the piece that far off); grid pieces a bottom-left pivot and extents matching their Size, whole modules on every axis of one module or more (an axis under one module is thickness and not in the token: a 2.0 x 0.3 x 3.0 m wall at a 0.5 m module is `4x6`); Free pieces the pivot their kind takes (floor centre for props, hinge for doors, back-face centre for wall-mounted, top centre for ceiling-mounted, or what the piece `desc` says) with the front facing -Y. UV2 and materials may be missing at greybox | `qa_measure` on the KIT file: `instance_offset` zero, `transform_issues` empty; grid pieces `pivot_ok` and `size_ok`; Free pieces `free_pivot` against the desc (`null` means a pivot it cannot name, such as a hinge: read `bounds_m`); the facing from a "One KIT piece" render |
| B2 | ASM files and MASTER hold only collection instances, zone and socket empties, and review aids in a `REF` collection (scale figures, a lighting reference): no local meshes and no local piece collections; an ASM file holds one assembly collection, named after the file, with a zero `instance_offset` | `qa_measure` (role `asm` or `master`): no PROBLEM lines about local pieces, assemblies, offsets or stray meshes; `pieces` and `stray_meshes` empty, review aids in `ref_meshes` |
| B3 | Every piece and assembly is linked, not appended, by a relative path | `qa_measure`: `appended` and `shadowing_linked` empty, no `local_assemblies` in MASTER, every `libraries` entry `relative` and `found` |
| B4 | Layout matches the plans: a top orthographic render overlaid on `world/diagrams/plan_<zone>.svg`, nothing more than half a module off; grid pieces on the grid: the TRIM family on `grid.sub_module`, every other grid piece on `grid.module` (the spec validator's rule) | `qa_measure --sub-module <sub_module> --render top ... --overlay` (`references/visual-review.md`) |
| B5 | Scale: the 1.6 m and 1.9 m figures stand at doors, stairs and under ceilings without clipping | `look` from each opening, `REF` shown |
| B6 | Walkable: no gap wider than 0.3 m in walkable floors; no step up higher than 0.2 m except on stairs or ramps (house guidance, the same 0.2 m as S6's stair rise and `vrchat-world-sdk-setup`) | Top render; floor heights from the placements and `bounds_m` |
| B7 | Elevations match: an orthographic render of each facade overlaid on `elevation_<id>.svg` | `qa_measure --render front/back/left/right ... --overlay` |

## Stage 5 - Kit modelling

| Id | Check | How |
|---|---|---|
| M1 | As B1, and `kit_status` = `modelled` on every piece | `qa_measure --expect-status modelled` |
| M2 | LOD0 triangles within `budgets.piece_tris.<FAMILY>`, or the piece's own `tris` where the spec sets one | `qa_measure --piece-tris '{"<FAMILY>": n, "<Piece>": n}'` (a piece entry wins over its family) |
| M3 | Topology: no n-gons (Unity triangulates them its own way), no edges shared by 3+ faces, no loose vertices or wire edges, no overlapping coplanar faces (duplicates, z-fighting, zero-thickness doubles), no faces hidden inside a closed part | `qa_measure --expect-status modelled` (`ngons`, `edges_over_2_faces`, `loose_verts`, `loose_edges`, `coplanar_overlaps`; `boundary_edges` 0 on parts meant to be closed); hidden faces: the topology audit (each part one closed island) proves it numerically; without it, `islands` against the piece's visible parts, and orthographic section renders at a few depths (`--isolate <Piece> --render front --center <x> <depth> <z> --clip 0.05 --wire`, depths across the piece): a plain wireframe cannot show a face sealed inside |
| M4 | Shading: no pinching or faceting at the review distance | Topology audit renders; without it, a "One KIT piece" render close up, studio light |
| M5 | Joints: pieces that meet share boundary vertices (no T-junction cracks when snapped) | Topology audit joint matching; without it, place two pieces side by side in an unsaved session and render the seam with `--wire` |
| M6 | Silhouette and proportions match the greybox piece it replaces: same footprint, same `Size` | `qa_measure` `bounds_m` and `extent_modules` against the stage 4 report; a "One KIT piece" render |
| M7 | LODs (where the spec's `lods` asks): `<Piece>_LOD0`, `_LOD1`, `_LOD2` as siblings in the piece collection, about 50% and 20% of LOD0, silhouette kept | `qa_measure` `objects.<obj>.tris`; one render per LOD (`--lod n`) |
| M8 | Collision as the spec's `collision` says: `mesh` has a convex-ish `<Piece>_COL` shell; `box` and `none` have none (Unity primitives, or nothing) | `qa_measure` `has_collision`; a render with `--show-collision` |
| M9 | MASTER and ASM files after kit work: every library found by a relative path; every linked piece at the stage's `kit_status` or later, and every linked piece and assembly with a zero `instance_offset` (a non-zero one is fixed in its KIT or ASM file); every earlier placement where the previous stage left it (ids, positions, rotations), and no new placement except those the brief asked for (dressing); in a `T-RENAME-<PIECE>`, every instance of the renamed piece re-pointed to the new name with its placement id kept, never deleted and placed again; B2 and B3 still hold | `qa_measure --expect-status <the stage's kit_status: modelled at stage 5, textured from stage 8> --sub-module <sub_module> --compare-placements <the last QA report of this file>`. Placements match by placement id first, so an id that vanished or changed prints a PROBLEM line. No PROBLEM lines other than the `added` placements the brief asked for and, in a `T-RENAME-<PIECE>`, the renamed piece's `now places <new name> (was <old name>)` lines; plan and elevation overlays as B4 and B7 |
| M10 | High and low poly, for every piece the spec marks `bake: true` (ornament, carving, rivets, sculpted or cloth forms): its highs in `blender/bake/<FAMILY>_high.blend` as `<Part>_high` objects, one part per vertex group on the low (never in MASTER or a KIT file, where B3 counts them as stray and an export would ship them); each high shaded smooth with every fold sharp, with no ripples, pinches, streaks or facets under a reflective matcap; the low's outline within 2 px of the high's at the nearest viewing distance d and the relief left to the bake within the stereo threshold; where detail is baked, under 10% of the low's area where the bake's rays lean more than 15 deg (*practice*); carving seen within about 1 m keeps its depth step in the low | Topology audit in one scene holding the low and its highs: `high_low_gap(low, highs)` (`low_outside_p99` at most `min_width_m(d)`, `high_outside_p99` at most `stereo_relief_m(d)`, both from `detail_scale.py`), `bake_skew(low)` (`over_share`), `review_render.compare(high, low, views)` and a matcap close-up of the high; without it, `not-run` (needs: blender-mesh-topology) |

## Stage 6 - UVs

Without `uv-unwrapping`, every check below has a `qa_measure` route except U1's distortion gate, U1's UV0 padding, U5
and U7: those parts are `not-run` with `needs: uv-unwrapping`, their owner by the rule in Tools, above.

| Id | Check | How |
|---|---|---|
| U1 | UV0 layout: distortion within the gate (angular p95 <= 1.15, p99 <= 1.5, max <= 2.0 over non-sliver triangles; area p95 <= 0.20) and no folded faces; on a unique or atlas map, islands at least `map_px / 64` px apart (16 px at 1024) and at least `map_px / 128` px from the tile edge; directional islands (wood grain, text, decals) upright and packed without rotation (90 deg steps only for non-directional straightened strips, free rotation only for organic, non-directional islands) | UV audit; without it, a checker render ("A UV layer with a checker" in `references/visual-review.md`: squares square, none mirrored, grain and text upright) for shape and orientation, and the gate numbers and padding `not-run` (owner as the stage intro says) |
| U2 | UV0 texel density against the family's `texel_density`: tiling, trim and shared materials 0.9-1.1x; unique and atlas 0.8-1.25x; even inside a piece, `texel_cv` <= 0.15; faces marked `uv_low_density` (hidden, lowered on purpose) excepted | UV audit (`--td <texel_density>`), computed from its `texel_px_per_m` rather than its OK line; without it, `qa_measure --texel-map <map_px>`: `uv0_px_per_m` for the band, `uv0_texel_cv` <= 0.15 for evenness (the audit's own definition: the spread of island densities, weighted by area) |
| U3 | Trim pieces land on the right strip of the trim sheet (the X6 layout) | `look` with the trim texture applied; UV audit island positions, or `qa_measure` `uv` bounds per piece, against the layout's strip rows |
| U4 | A UV2 (the second UV layer) on every kit render mesh, LODs and probe-lit props too, not `_COL`. On every lightmapped render mesh, LODs included (the Progressive Lightmapper gives each LOD its own atlas space): LOD1+ follow their piece (lightmapped at 0.5^n), unless the spec sets `lod_lightmap: false`; a piece with `lightmap: false`, or a LOD the scene sets to Receive Global Illumination = Light Probes, is probe-lit and skipped. Inside 0-1, no overlapping or stacked charts, gaps of at least 2 texels and at least 1 texel to the tile edge at the mesh's own lightmap footprint: `footprint_px ~= texels_per_m x sqrt(A / b) x Scale In Lightmap x 0.5^n` for LODn (LOD0 1, LOD1 0.5, LOD2 0.25), with A the mesh's surface area in m2, b its UV2 charts' bounding-box share of the 0-1 tile (0.85 is only the planning estimate before UV2 exists), `texels_per_m` from the spec's `budgets.lightmap` and Scale In Lightmap the piece's `lightmap_scale` (default 1); never at the whole map's size. Under 64 px at LOD0 (house guidance; LOD0's footprint decides for the whole piece, and LOD1+ follow it): a Free prop (a Free-sized PROP or FOL piece) should be probe-lit (`lightmap: false` in the spec), unless its zone has `lighting_states` above 1, where it changes with the switch and stays lightmapped, and counted, in every state copy; every other piece (grid pieces, ZONE shells, other families) stays lightmapped and still counts in capacity, so note it to raise its `lightmap_scale` or the world's `texels_per_m`. Under Bakery (`lighting.baker: bakery`) the footprint is Bakery's, `footprint_px ~= (texels_per_m x sqrt(2 x A x Scale In Lightmap) - 6) / w` with w the UV2 bounding box's short side in UV units and no LOD factor (each LOD is sized by its own area), and each lightmapped mesh of 64 px or more also gets at least `0.5 x texels_per_m x min(1, sqrt(Scale In Lightmap))` effective texels per metre (`footprint_px x sqrt(a / A)`, a = its UV2 charts' own area in UV units): Bakery sizes a renderer by its area and UV2 bounds, not by its charts, so many small charts bake at almost no density | `qa_measure --expect-status uv --lightmap-texels <texels_per_m> --lightmap-scale '{"<Piece>": <lightmap_scale>}' --probe-lit <the pieces with lightmap: false, plus "<Piece>_LOD[1-9]" for each piece with lod_lightmap: false>` (a `--probe-lit` value that matches nothing prints a PROBLEM line): a missing UV2, UV2 outside 0-1, overlapping charts, gaps under 2 texels and edge margins under 1 texel at each mesh's measured-b footprint (with its LOD's 0.5^n) all print PROBLEM lines (exact edge-to-edge distances between chart outlines: `uv2_min_gap_texels`, `uv2_edge_margin_texels`); NOTE lines for LOD0 footprints under 64 px. Under Bakery add `--lightmapper bakery`: `lightmap_px` is then Bakery's footprint, and an `effective_texels_per_m` under `effective_texels_min` at 64 px or more prints a PROBLEM line. uv-unwrapping's `uv_audit.py -- --objects "<mesh>" --layer 1 --lightmap --map <lightmap_px rounded down> --pad 2` cross-checks the gaps and also holds UV2 to the distortion gate (a stretched chart bakes stretched shadows); with `uv-unwrapping` installed run it on every lightmapped mesh. L6 confirms the footprints the lightmapper gave |
| U5 | Hard edges are seams on layers that take a baked normal map | UV audit (`--baking`); without it, `not-run` (owner as the stage intro says) |
| U6 | *advisory* Wasted space, a note to look for oversized gaps or islands: coverage of unique and atlas UV0 below 50% (this pipeline's own threshold; no published source sets one; with map_px/64 padding, automated unwraps of organic props measured 55-59%, rizomuv-uv-pipeline 2026-10-17); UV2 charts filling less than half their bounding box (box fill, the charts' area over the box's, under 0.5: Unity packs each renderer's chart box, so its empty space still costs lightmap texels, measured Unity 2022.3.22f1, 2026-10-17), on a UV2 whose footprint is 64 px or more; below that the 64 px fallback and the probe-lit advice govern instead. Under Bakery the box is mapped onto a rect sized by the surface area, so the same holds, and a mesh that also fails U4's effective-density gate is U4's failure, not this note. A long strip that fills its box is fine whatever its tile coverage | UV audit (`coverage`; `uv2_box_fill` in a lightmap audit); without it, `qa_measure`'s `uv` area of UV0 (its share of the 0-1 tile when nothing overlaps or stacks) and, with `--lightmap-texels`, `uv2_box_fill` (a NOTE line under 0.5 at a footprint of 64 px or more, LODs at 0.5^n under Unity) |
| U7 | Tiling continues across joints: every tiling face at `tile_project`'s scale and phase (U from each piece's own axes, phase 0 at its pivot, U to the right seen from the front), never Cube Projection (it centres on each piece, so pieces of different sizes start out of phase); the family's tile (`map_px / texel_density` m) divides `grid.module` and `grid.storey_height`, or its `tile_phase` (variants, world_uv) says how it continues; outside corners covered by a trim or a corner piece | UV audit per tiling material: `uv_audit.py -- --objects "<FAMILY>_*" --purpose tiling --material "<M>" --map <map_px> --td <texel_density> --tile-m <map_px / texel_density> --steps <module>,<storey>` (every face within half a texel; a phase variant audited with its `tile_offset`); without it, `not-run` (owner as the stage intro says) |

## Stage 7 - Texturing

| Id | Check | How |
|---|---|---|
| X1 | Materials per family as planned (1-3), named `M_<FAMILY>_<Name>` (underscores allowed in the name part), plus the shared trim sheet's `M_TRIM_*` materials on a piece of any family, every slot filled, `kit_status` = `textured` | `qa_measure --expect-status textured` (`objects.<obj>.materials`, `bad_materials`, empty-slot PROBLEM lines) against the spec's `families.<FAMILY>.materials` |
| X2 | Every image a material uses loads, at no more than the family's `map_px` (and the PC maximum: 2048, or 4096 for one hero surface); the 1024 cap for Android and iOS is N8's import override, not a source size | `qa_measure` `images[]` (`size`, `missing`) |
| X3 | Channel packing for Unity's Standard shader: `_MetallicGlossMap` R = metallic, A = smoothness (1 - roughness), G and B unused; occlusion, if any, its own map (Standard reads its G); never a glTF-style ORM map. Base colour sRGB; metallic-smoothness, occlusion and normal maps linear (Non-Color in Blender); normal maps OpenGL (Y+), as Blender bakes them | `qa_measure` `images[]` (`channels`, `colorspace`, `alpha_mode`); the channel values with Blender's image API (`pixels.foreach_get`) |
| X4 | Tiling materials repeat without a seam and without a grid: no seam along any part of a wrap edge (the worst of 16 windows of each edge under 1.5 x the texture's own p99.9 step), no tile-scale variation that draws a grid once the map repeats (base colour `lf` under 0.011: calibrated on 20 library tiles, the six with an obvious grid measured 0.0118-0.0205), no distinctive feature inside the tile (one pale stone, one crack) in its 3 x 3 composite; trim sheets the same along U | `qa_measure --pbr "<the family's tiling maps>" --pbr-tiling` (`--pbr-trim` for a trim sheet): each `[qa] PROBLEM pbr ...` seam or tile-scale line fails X4 (`pbr-texturing`'s `tile_flatten.py` is the fix for the variation); the 3 x 3 composite from `pbr_check.py --tiling --out <scratch>` for the features; `--tile-seam <png>` gives the older whole-edge ratio for any PNG |
| X5 | Materials read as intended, against the mockups, the spec's `look.references` and `look.materials.<M>.ref` (without any of them, `world.style` and the piece `desc`s): colour and value under flat and studio light (albedo as stored); roughness, metal and relief under look-dev light (a glossy surface shows a tight highlight and a rough one a broad, soft one; metal reflects its surroundings, tinted by its base colour, with no diffuse shading; relief lit from above reads raised, not dented); wear at the level `look.wear` names | `qa_measure --view <spec view> --color texture --light flat` and `--light studio` (Workbench: base colour only, it ignores roughness, metallic and normal maps), plus `--light lookdev` from the same views and one close-up per material (`--isolate <Piece> --view ...`): EEVEE with each material's own nodes under a fixed neutral light; `references/visual-review.md`. These renders are what the pipeline's look gate shows the user |
| X6 | Trim layout (`T-TEX-TRIM-LAYOUT`, before the trim family's UVs): `blender/substance/<FAMILY>/layout.md` (the trim family's code) names every strip with its pixel rows and the trim pieces that use it; the strips fit the family's `map_px` without overlapping; each strip's height is its trim's real height at the family's `texel_density`, within 10%; the trim family's UV brief cites the file | Read the layout; sum the rows against `map_px`; heights against the spec's trim pieces |
| X7 | Source files saved (`.sbs`, `.spp` or the node-setup `.blend`) next to the exports, so a map can be remade | List files |
| X8 | PBR values: every map of the family passes the PBR check. Base colour: dielectric luma within 30-240 sRGB at its 1st and 99th percentiles (under 50 is a note), raw metal at least 160 at its 5th (under the guide's 180 is a note: measured titanium is 171); metallic binary (more than 10% of the map between 0.1 and 0.9 fails, over 2% is a note); smoothness in the metallic-smoothness map's A channel; normal maps unit-length, not pointing into the surface and OpenGL (Y+, from the correlation of their mixed derivatives); every map a power of two and no larger than `map_px`; inside the spec's `look.materials` targets (`albedo_srgb`, `roughness`, `metal`) where it gives them. NOTE lines are advisory | `qa_measure --pbr "blender/textures/<FAMILY>/*.png" --map-px <map_px> --pbr-targets '<look.materials as JSON>'` (the trim family's maps too): each `[qa] PROBLEM pbr ...` line fails X8, each `[qa] NOTE pbr ...` line goes in `notes`; the `pbr` field is the evidence. A map whose name does not end in `_BaseColor`, `_MetallicSmoothness` or `_Normal` is not judged: say so in `notes` |
| X9 | No visible texture seams: on every unique or atlas textured mesh, no UV seam whose colour or normal step is over 3 times the texture's own (`visible_m` 0), and every seam in the 2-3 band looked at in a close render; across the placed kit, no joint between pieces of a tiling family where the pattern jumps. Every texture signal on a unique layout comes from 3D space (bakes, Object-coordinate procedurals, Box-projected images, tri-planar fills), so a failure names its cause | `texture_seams.py -- --objects "<FAMILY>_*" --image <its BaseColor>` and again with `--kind normal --image <its Normal>` on the pieces (a work file with them in the view layer), and `--joints` on MASTER's layout empties for each tiling material: exit 1 fails X9; `look_m` goes in `notes` |
| X10 | Bakes: every `bake: true` piece's maps baked from its highs (M10) through a cage that encloses them: the bake report's `cage_inside` own and neighbour both 0 (parts that sit close together baked exploded), the normal map OpenGL (X8) and seam-free (X9) | The `bake_maps.py` report saved beside the maps (`report.cage_inside`, `report.passes.exploded` for an exploded bake); without the report, `not-run` with the bake to be repeated |

## Stage 8 - Assemblies and master dressing

G4 covers the final views against the mockups.

| Id | Check | How |
|---|---|---|
| A1 | ASM files and MASTER hold only linked instances, zone and socket empties, and `REF` aids: the B2 and B3 rules | `qa_measure` on each file the task wrote, read as B2 and B3 |
| A2 | No greybox left: every linked piece at `kit_status` `textured` or later | `qa_measure --expect-status textured` (`linked_pieces[].kit_status`; one behind is a PROBLEM line) |
| A3 | Placed as the spec says: every placement, pieces and assemblies alike, at its `zones[].placements` position and rotation (`pos`, `rot` about Z); grid pieces also on the grid (multiples of `grid.module`; TRIM pieces on `grid.sub_module`), in 90 deg steps about Z, not tilted, at scale 1. A placement the spec does not list is only dressing the brief asked for; inside an ASM file, the count of each piece equals the assembly's `uses`. Free props: note any tilt or scale | `qa_measure --sub-module <sub_module>` `placements` (`pos`, `rot_z`) against the spec's placements; grid pieces' `on_grid`, `right_angle`, `rot_xy_ok`, `scale_ok` print PROBLEM lines (for assemblies these values are data only) |
| A4 | No z-fighting or interpenetration at joints visible from walkable areas | `look` along the joints |
| A5 | Repetition never obvious: along the longest run of each tiling material and in every spec view, no grid of the tile, no stain or panel recurring at one period, no two identical variants side by side or in a repeating sequence, and a breaker (pilaster, door, trim, prop, decal) at irregular spacing on runs over about four tile periods (*practice*) | Eye-height renders along each long run and from every spec view (`qa_measure --view ... --light lookdev`), judged as `references/visual-review.md` says; `placements` for the variant order |

## Stage 9 - Export

| Id | Check | How |
|---|---|---|
| E1 | One FBX per piece collection, named after it, in `export/fbx/<FAMILY>/`; the KIT's pieces at `kit_status` `exported` | List files; `qa_measure --expect-status exported` on the KIT file |
| E2 | Every FBX re-imports into a blank Blender at scale 1 and rotation 0, at its piece's size and pivot | `qa_measure --module <grid.module> --import-fbx "export/fbx/<FAMILY>/*.fbx"` in a factory-startup session (imports with `bake_space_transform=True`, one collection per file): `transform_issues` empty, `size_ok` and `pivot_ok` or `free_pivot`; a file named other than its piece shows in `unnamed_collections`. Images come back unloaded under Path Mode Strip (the FBX names the texture but carries none): for role `fbx` they are data, never a PROBLEM line, and renders of a re-import use `--color random` or `material` (a texture render has nothing to sample). A plain import without `bake_space_transform` shows X 90 deg with Y and Z swapped even for a correct file; Unity's own check is N3 |
| E3 | FBX triangle counts equal the KIT's LOD0 counts | The same run: `lod0_tris` per file against E1's `qa_measure` run on the KIT in this pass (so a re-export after a geometry fix still compares like with like) |
| E4 | Two UV channels on every render mesh in every FBX, LODs too, not `_COL`; material slot names unchanged from the previous export (on a first export: equal to the KIT's) | The same run: `objects.<obj>.uv_layers`, `objects.<obj>.materials`. A family material shared by several files comes back from the importer as `<name>.001` after the first: `qa_measure` folds those copies back onto `<name>` and lists them in `fbx_folded_materials`, so compare names after the fold |

## Stage 10 - Unity assembly

| Id | Check | How |
|---|---|---|
| N1 | One folder per piece (`Assets/World/Kits/<FAMILY>/<Piece>/`) with its FBX and a prefab variant; family materials in `<FAMILY>/_Shared/`; each assembly as `Assets/World/Assemblies/ASM_<Name>_<Variant>.prefab` | Unity MCP `manage_asset` search |
| N2 | No extracted per-FBX materials where `_Shared` ones exist; submesh count equals material slots | Unity MCP |
| N3 | Import settings: Read/Write off, Generate Lightmap UVs off, no cameras or lights, Animation Type None; each model root at rotation 0,0,0 and scale 1 (X -90 or 270 means the FBX was exported with Bake Space Transform off, which a Blender re-import in E2 does not show) | Unity MCP `execute_code` reading `ModelImporter` |
| N4 | Placement sync committed for every scope; the last merge reports 0 conflicts and 0 blocked | Placement report |
| N5 | Spot check: three placements compared Blender vs Unity, numerically (ids; positions after `(-x, z, -y)`; a Blender rotation about Z is the negative Unity rotation about Y) and visually from the same camera | `qa_measure` on MASTER (`placements`; `--view` without the Blender MCP); `references/visual-review.md` |
| N6 | Static flags as planned (the plan is in the T-UNITY-SETUP brief and report); instanced pieces are not Batching Static, and their materials have Enable GPU Instancing on, Standard (PC) and `VRChat/Mobile/Standard Lite` alike; only `VRChat/Mobile/Lightmapped`, which has no instancing variant, is exempt | Unity MCP |
| N7 | VRChat scene setup: the project's layers and collision matrix set up for VRChat (`UpdateLayers.AreLayersSetup()` and `UpdateLayers.IsCollisionLayerMatrixSetup()` both true, a class in the global namespace: either false blocks the build, and the signed-out reflection validation does not run them); one scene descriptor; at least one spawn (an empty list blocks the build), each on a walkable floor facing in; respawn height below the lowest floor; reference camera clip planes set; nothing on reserved or player layers; every VRC Mirror Reflection's Reflect Layers include Player (9) and MirrorReflection (18) and never PlayerLocal (10); every mirror at its slot in the spec's `zones[].mirrors`, off by default: the SDK's VRCMirror prefab at position (-x, z, -y) from `pos`, Y rotation 180 - rot and scale (width, height, 1) from `size` (the prefab is a Unity Quad whose front faces -Z, so the -rot kit pieces get would face it into the wall) | Unity MCP `execute_code` (each mirror's transform against its slot); the `vrchat-world-sdk-setup` checklist if installed |
| N8 | Mobile overrides, for worlds with `quest` or `ios` in `world.platforms`: Android and iOS texture overrides (both tabs) at 1024 or below on every texture, ASTC: albedo 6x6 (8x8 for background surfaces), normal maps 4x4 (5x5 if size-bound), packed masks 6x6 unless their gradients band (then 4x4); a mobile shader for every material, or a per-platform material swap planned; the Android and iOS build modules installed, or the missing one recorded as a user action | Unity MCP: `TextureImporter.GetPlatformTextureSettings("Android")` and `("iPhone")`, each material's shader, `BuildPipeline.IsBuildTargetSupported`; `vrchat-texture-and-vram` for the formats |

## Stage 11 - Lighting and bake

A zone with `lighting_states` above 1 has a render-only copy of its static geometry per state under a `LIGHT_STATES`
root outside MASTER, and MASTER's originals of those pieces stay active and unmoved, keeping their colliders and their
place in placement sync, with their Mesh Renderers off (`vrchat-lighting-and-baking`'s method). Where a check looks at
renderers, the lightmapped ones are the state copies, every state's, never the originals: L1 and L6 check each copy
(each has its own `lightmapScaleOffset`), and L2 counts every copy's lightmaps. L3 checks the layout (each copy at its
original's pose; every original active, at its placement, with its colliders and its Mesh Renderer off: one still on
draws over its copy) and looks at each state in turn without editing the real objects: switch states in Play mode
with the world's own switch, or use hidden temporary objects in the editor (`references/visual-review.md`), never by
toggling or moving the real copies; reopen the scene from disk afterwards. L4's probes serve every state, so avatars
and probe-lit props do not change with the switch. L7 renders every state from every spec view, switching states the
same way.

| Id | Check | How |
|---|---|---|
| L1 | Bake completes with no UV overlap warnings | Unity MCP `execute_code`: `Lightmapping.HasUVOverlaps` is internal in Unity 2022.3, so call it by reflection, `typeof(UnityEditor.Lightmapping).GetMethod("HasUVOverlaps", System.Reflection.BindingFlags.Static \| System.Reflection.BindingFlags.NonPublic).Invoke(null, new object[] { renderer })`, for each lightmapped renderer; and the Editor log (`%LOCALAPPDATA%/Unity/Editor/Editor.log`: "objects in the Scene with overlapping UV's"). `read_console` misses them once the console is cleared |
| L2 | Lightmap count and size within `budgets.lightmap` | Lighting settings, `LightmapSettings.lightmaps` through Unity MCP |
| L3 | No visible seams, splotches or light leaks at kit joints, in every lighting state; with lighting states, each state copy at its original's pose, and every original active, at its placement, with its colliders and its Mesh Renderer off (stage intro) | `look` at joints and corners, per state; dark renders judged by number and on a brightened copy (`qa_measure --image-stats <png> --gain 4`); Unity MCP `execute_code` for the copies' and originals' world poses, `activeInHierarchy`, colliders and `MeshRenderer.enabled` |
| L4 | Avatars lit correctly: light probes cover every walkable area at standing and head height. Probes are always required; VRC Light Volumes add to them for shaders that read Light Volumes, while Standard, the VRChat mobile shaders and every mobile (Android and iOS) avatar read only probes | Read-only: temporary capsules with `HideFlags.HideAndDontSave`, rendered and destroyed (the scene stays clean), plus `LightProbes.GetInterpolatedProbe` at test points for numbers |
| L5 | Realtime lights: a world with `quest` or `ios` keeps every light Baked, in one bake shared by every platform (VRChat documents its mobile shaders, Standard Lite and Lightmapped, as not supporting real-time lighting); a PC-only world has at most one realtime per-pixel light on static geometry at a time (a switchable light passes while only one is on at once) | Scene query through Unity MCP |
| L6 | Every lightmapped renderer, LOD1+ included (each LOD has its own atlas space, at 0.5^n of LOD0's scale), keeps its UV2 gaps at 2 texels or more at the footprint Unity gave it: gap texels = authored gap in UV units x footprint px (footprint = `lightmapScaleOffset.x` x lightmap width). Under 64 px at LOD0 (house guidance; LOD0's footprint decides for the whole piece): a Free prop (a Free-sized PROP or FOL piece) is probe-lit instead (Contribute GI on, Receive Global Illumination = Light Probes), except in a zone with `lighting_states` above 1, where it changes with the switch and stays lightmapped in every state copy; every other piece stays lightmapped, noted to raise its Scale In Lightmap or `texels_per_m`. LOD1+ follow their piece (lightmapped at 0.5^n), unless the spec sets `lod_lightmap: false` (then their Receive Global Illumination is Light Probes). Scale In Lightmap never below what U4 packed the gaps for. Under Bakery: the footprint Bakery gave it (Bakery writes `lightmapScaleOffset` too), each LOD at its own area with no 0.5^n, and each lightmapped renderer of 64 px or more keeps U4's effective density, at least `0.5 x texels_per_m x min(1, sqrt(Scale In Lightmap))` texels per metre | Unity MCP: each lightmapped renderer's `lightmapScaleOffset` (with lighting states, every state copy's, as the stage intro says) against its UV2 gap (U4's evidence); under Bakery also its effective density, footprint px x sqrt(a / A) with a the summed UV2 triangle areas of its mesh and A its triangles' world-space area (`localToWorldMatrix`), read in Edit mode, where mesh data is readable whatever Read/Write is |
| L7 | Final look: every spec view, in every lighting state, rendered in Unity matches the mockups, the spec's `look.references` and `look.lighting_mood` (palette, light colour, contrast and mood; without them, `world.style`), judged like G4 and blocking like it. Record each render's luma p1, p50 and p99 and its clipped and crushed shares: more than 1% clipped or 5% crushed is a note to look at where (house guidance: a lamp or a window may clip on purpose, a corner may be meant dark) | Unity MCP `execute_code`: a temporary camera at each view's transform (Blender `(x, y, z)` is Unity `(-x, z, -y)`; vertical FOV `2 * atan(18 / lens * h / w)` degrees) rendered to a RenderTexture, read back, saved outside the project and destroyed afterwards (`references/visual-review.md`, "Blender vs Unity"); in a PC world whose reference camera carries post-processing, the temporary camera gets a copy of its post-processing layer so the render shows the graded look (say in `notes` when it cannot); each lighting state switched in Play mode with the world's own switch, the scene reopened from disk afterwards; then `qa_measure --image-stats <png>...` for the numbers |

## Stage 12 - Interactivity

| Id | Check | How |
|---|---|---|
| I1 | Each system in `interactivity` exists and works in Play mode (ClientSim) | Unity MCP: enter Play, press it with `UdonBehaviour.Interact()` through `execute_code`, read the console; afterwards reopen the scene from disk (never save). If Play mode cannot be driven, I1 is `not-run` (`owner: qa`), not a pass. `vrchat-world-sdk-setup` for ClientSim |
| I2 | No `Update()` loops where events would do; sync mode as the spec's `interactivity[].sync`, payloads within `vrchat-udon`'s limits | Read the scripts |
| I3 | A late joiner sees the right state | The simulated late-join check from `vrchat-world-sdk-setup`, in a fresh Play session through Unity MCP: give a simulated remote player ownership first, set the synced fields to a non-default state, fire `_onDeserialization`, and the scene must show that state. Local Build & Test cannot add a late joiner (each launch opens a new room), so the real test, a private upload joined by two accounts, goes in `not_run` with `owner: user` |
| I4 | No console errors or warnings from Udon on start or interaction | `read_console` |

## Stage 13 - Optimisation audit

Load `vrchat-world-optimization` and run its pre-upload audit end to end, then:

| Id | Check | How |
|---|---|---|
| O1 | Every number in `budgets` measured on every platform in `world.platforms` and within that platform's value (one number for all, or `{pc, quest, ios}` with `ios` falling back to `quest`): triangles, SetPass, batches, materials, VRAM, download size, in every state players can reach (a light switched on, a mirror on) | Stats panel, Profiler, build size report via Unity MCP, on the active build target. The other platform's numbers without a switch: texture VRAM computed from each texture's `TextureImporter.GetPlatformTextureSettings` for that platform; draw calls and triangles unchanged unless the scene swaps objects or materials per platform. When it does, or a number cannot be computed, switch to that platform, measure, and switch back to the target you found (the stage 13 exception in SKILL.md). An estimate in place of a measurement goes in `not_run` |
| O2 | Every Android and iOS build under 100 MB (the hard limit: 104,857,600 bytes after build-time compression; VRChat's MB is 2^20 bytes) | Build report; without a build, an estimate from the compressed data at the mobile formats, in `not_run` with `owner: user`. An estimate over the limit fails O2: it is never `not-run` |
| O3 | Worst view in each zone measured, not the average | Stand at each zone's busiest point |
| O4 | Regressions since the last audit explained | Compare with the previous report in `world/reports/` |
| O5 | The task's own platform (`T-BUILD-<platform>`) builds with no SDK validation errors or console errors, uses one blueprint ID (once the first upload has assigned one), and passes a ClientSim walk and a 2-client Build & Test; publish fields drafted | With the task's platform as the active build target: the SDK compiles its mobile scene checks (the unsupported-shader check) only for an Android or iOS target, so switch to it if needed and back to the target you found afterwards (the stage 13 exception in SKILL.md). Signed in: the Builder's validation list. Signed out: the reflection checks (`vrchat-world-sdk-setup`) plus `UpdateLayers.AreLayersSetup()` and `UpdateLayers.IsCollisionLayerMatrixSetup()`, which the reflection checks do not include: either false fails O5. Build logs and console through Unity MCP. A part the user excluded, or one blocked by a missing build module or sign-in, goes in `not_run` with `owner: user`, and the user is told what is left before upload |

## Platform targets

Practical targets, not SDK limits, except the **hard** one. Mobile means Android (Quest) and iOS: VRChat's Android
guidance applies to iOS too. Sizes in VRChat's MB, 2^20 bytes. Re-check against the sources below: VRChat tightens
these over time.

| Metric | PC | Android and iOS |
|---|---|---|
| World triangles | 500k-1M | ~250k |
| Triangles in one view | < 300k | < 100k |
| SetPass calls | < 150 | < 50 |
| Batches | < 400 | < 150 |
| Unique materials | < 60 | < 25 |
| Max texture size | 2048 (4096 for one hero surface) | 1024 |
| Texture VRAM | < 1.5 GB | < 150 MB |
| Lightmaps | 2048 in a PC-only world (1024 when it also ships to Android or iOS), few | 512-1024, non-directional |
| Realtime lights on static geometry | PC-only worlds: at most 1 per-pixel light at a time | 0: every light Baked when the world ships to Android or iOS |
| Download size | under 200 MB for a public world (VRChat's request) | **100 MB (hard)** (104,857,600 bytes, after compression) |

## Sources and versions

- Mobile limits and guidance: https://creators.vrchat.com/platforms/android/quest-content-optimization/ and
  https://creators.vrchat.com/platforms/iOS/ ("Guidelines that refer to 'Android' or 'Quest' apply to iOS, too"),
  checked 2026-10-17.
- Mobile shaders and real-time lighting (Standard Lite and Lightmapped do not support it):
  https://creators.vrchat.com/platforms/android/quest-content-limitations/ (updated 2025-10-08), checked 2026-10-17.
- PC public-world size: https://creators.vrchat.com/worlds/submitting-a-world-to-be-made-public ("Try to keep your
  worlds under 200MB"), checked 2026-10-17.
- VRChat's MB = 2^20 bytes (`ValidationHelpers.BYTES_TO_MB = 1048576`), the layer and collision-matrix calls
  (`UpdateLayers`, global namespace, VRCCore-Editor.dll) outside the signed-out reflection validation, the build
  error for an empty spawn list, and the mobile scene checks compiled only for an Android or iOS target
  (`#if UNITY_ANDROID || UNITY_IOS` in `VRCSdkControlPanelWorldBuilder.cs`): Worlds SDK 3.10.5, read 2026-10-17. Layers: https://creators.vrchat.com/worlds/layers/
  (updated 2026-08-17).
- GPU instancing: `VRChat/Mobile/Standard Lite` has an instancing variant, `VRChat/Mobile/Lightmapped` none (Worlds SDK
  3.10.5 shader source, read 2026-10-17).
- Light probes and Light Volumes: which shaders read Light Volumes, https://github.com/REDSIM/VRCLightVolumes, as of
  2026-10-17.
- Standard shader channels: https://docs.unity3d.com/2022.3/Documentation/Manual/StandardShaderMaterialParameterMetallic.html,
  checked 2026-10-17.
- Lightmap footprint `texels_per_m x sqrt(A / b) x Scale In Lightmap`: fitted to five dry-run renderers within 0.6%,
  Unity 2022.3.22f1, 2026-10-16 (b measured; 0.85 is the planning estimate). LOD1+ get their own atlas space at
  0.5^n of LOD0's texel scale (Unity's `GetLightmapLODLevelScale`; measured 0.995, 0.492 and 0.250 for LOD0-2,
  whatever the transition heights; a LOD set to Receive Global Illumination = Light Probes leaves the atlas):
  Progressive GPU bakes, Unity 2022.3.22f1, 2026-10-17. `Lightmapping.HasUVOverlaps` internal,
  called by reflection, and the Editor.log overlap message: Unity 2022.3.22f1, 2026-10-16.
- Bakery's footprint `(texels_per_m x sqrt(2 x A x Scale In Lightmap) - 6) / w`: read from Bakery's scripts as
  installed in a Unity 2022.3.22f1 project, 2026-10-24 (`Assets/Editor/x64/Bakery/scripts/ftBuildGraphics.cs`: the
  area loop sums |cross| over the triangles, 2 x A, Scale In Lightmap multiplies that area, the rect's side goes to
  the UV2 bounds' short side, and the Default atlas packer insets each rect by `texelPaddingForDefaultAtlasPacker`, 3
  texels; xatlas does not inset, so the footprint is a floor under both). With Alternative Scale In Lightmap off, its
  default. Not yet measured in a bake (GitHub issue #10). The effective-density gate (half the planned texels per
  metre at 64 px or more) is house guidance; on the repo owner's Bakery world a 588-chart wall panel baked at 0.43
  texels/m (GitHub issue #8). Mesh data readable in Edit mode whatever Read/Write is:
  https://docs.unity3d.com/2022.3/Documentation/ScriptReference/Mesh-isReadable.html, checked 2026-10-24.
- `qa_measure` behaviour (FBX re-import axes and material copies, Workbench renders, hiding linked objects, image
  statistics; Workbench texture renders sample the mesh's active UV layer, not its active render layer): Blender
  5.2.2, measured 2026-10-17.
- Base-colour ranges (dielectrics 30 sRGB tolerant, 50 strict, 240 at most; raw metals 180-255) and the binary
  metallic map, X8: Adobe, "The PBR Guide, Part 2", https://www.adobe.com/learn/substance-3d-designer/web/the-pbr-guide-part-2,
  checked 2026-10-18. The percentiles, the grey-metal shares and the normal-map rules are house rules.
- `--light lookdev`, Blender 5.2.2, measured 2026-10-18: EEVEE renders headless (`-b`); a 1280 x 720 look-dev view at
  16 samples took about 1.3 s a run, start-up included. Workbench ignores the material's node roughness: two grey
  spheres with node roughness 0.1 and 0.9 peaked at luma 187.6 and 191.6 under `--light studio`, 255 and 193 under
  `--light lookdev`. RenderSettings' engine list (`bl_rna` enum items) names only `BLENDER_EEVEE`, while the error an
  unknown engine raises names `BLENDER_EEVEE`, `BLENDER_WORKBENCH` and `CYCLES`, so the look-dev rig reads EEVEE's id
  from that error. Its UV2 footprints on the dry run's KIT (wall 243.5, door 237.3, floor 200.5, desk
  144.2 px at 60 texels/m) match the footprints Unity gave (242.8, 236.7, 200.3, 143.4 px).
