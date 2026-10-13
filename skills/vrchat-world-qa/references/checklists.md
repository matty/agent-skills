# QA checklists by stage

Stage numbers follow the world-build pipeline (the `vrchat-world-orchestration` skill). Spec fields
(`budgets.piece_tris`, `grid.module`) refer to the project's `world/spec.yaml`; without one, take budgets from the
brief or ask. Checks marked *advisory* can only produce `pass-with-notes`; every other check blocks.

## Tools

QA's own script covers the common measurements, so every checklist runs with only this skill installed. Where a
check needs a specialist's depth, load that skill and use its own audit; if it is not installed, use the fallback
named in the check and say in the evidence that the deeper audit was unavailable.

| Name in the checks | What | Where |
|---|---|---|
| `qa_measure` | Piece names, LOD0 tris, materials, UV layer count, n-gons, bad edges, transforms, extents vs Size, pivots, `kit_status`; placements on grid and at right angles; linked vs appended; ortho renders and overlays | `scripts/qa_measure.py` (this skill) |
| UV audit | Distortion, texel density, padding, overlap, seams vs hard edges | Load `uv-unwrapping` (or `rizomuv-uv-pipeline` for its metrics) |
| Topology audit | Joint matching between pieces, shading review renders | Load `blender-mesh-topology` |
| Export checks | FBX settings and re-import test | Load `blender-to-unity` |
| Spec validator | Schema, names, budgets, ledger graph | The validator that ships with the pipeline skill (`vrchat-world-orchestration`), else check the spec by hand against these lists |
| Placement report | Last merge and commit result per scope | `world/placements/<scope>.report.txt`, written by `blender-unity-placement-sync` |
| Unity MCP | Import settings, hierarchy, console, Stats, screenshots | MCP tools |

## Stage 1 - Mockups

| Id | Check | How |
|---|---|---|
| C1 | One image per view the brief asked for (hero per zone, key interiors, material swatches) | List `world/mockups/` |
| C2 | Each mockup is consistent with the brief's style, era and palette; no two contradict each other on the same element | Look side by side |
| C3 | Prompts recorded next to each image (`<name>.prompt.txt`) so a variant can be regenerated | List files |
| C4 | *advisory* Readable as buildable from a modular kit: repeated bays, clear storey lines | Look |

## Stage 2 - Spec and diagrams

| Id | Check | How |
|---|---|---|
| S1 | Spec validates with no errors | Spec validator |
| S2 | Every zone in the mockups has a zone in the spec, and the reverse | Compare |
| S3 | Every piece used in an elevation or plan is in `pieces`, and every piece is used somewhere | Spec validator reports both |
| S4 | Plans and elevations regenerate from the spec and match the committed SVGs | Regenerate with the pipeline's SVG script, diff |
| S5 | Budgets present and no looser than the platform target (Quest numbers when `quest` is in `platforms`) | Compare with the platform targets at the end of this file |
| S6 | Dimensions are human-scale: doors >= 2.1 m high and >= 1 m wide, ceilings >= 2.6 m, stairs rise <= 0.2 m per step, corridors >= 1.5 m wide (VR players are taller than their avatars suggest and need space to turn) | Read spec, check plans |
| S7 | Task graph (Mermaid) has no cycles and every task has an owner role and a QA step | Spec validator with the ledger |

## Stage 3 - Kit plan

| Id | Check | How |
|---|---|---|
| P1 | Each family has a KIT file path, a material list of 1-3 materials and a texture approach (trim / tiling / atlas / unique) | Spec |
| P2 | Pieces snap: widths and heights are whole modules; corner and end pieces exist for every wall family | Spec, plans |
| P3 | Repeated elements are one piece used many times, not near-duplicates (`_A`/`_B` must differ visibly) | Spec, elevations |
| P4 | Texel density and map size set per family, consistent across families seen side by side | Spec `families.*.texel_density` |

## Stage 4 - Greybox

| Id | Check | How |
|---|---|---|
| B1 | Every greybox piece has a valid name, identity transforms, a bottom-left pivot and extents matching its Size (UV2 and materials may be missing at greybox) | `qa_measure` on each KIT file |
| B2 | MASTER contains only collection instances, zone empties, a scale figure and lighting reference; no local meshes | `qa_measure` `stray_meshes` (only the scale figure allowed) |
| B3 | Every piece in MASTER is linked, not appended | `qa_measure`: `appended` and `shadowing_linked` empty |
| B4 | Layout matches the plans: overlay a top orthographic render on `world/diagrams/plan_<zone>.svg` | `qa_measure --render top --overlay` |
| B5 | Scale: 1.6 m and 1.9 m figures stand at doors, stairs and ceilings without clipping | `look` angles at each opening |
| B6 | Walkable: no gap wider than 0.3 m in walkable floors, no step higher than 0.4 m without stairs | Look, top view |
| B7 | Elevations match: orthographic render of each facade against `elevation_<id>.svg` | `qa_measure --render front/back/left/right --overlay` |

## Stage 5 - Kit modelling

| Id | Check | How |
|---|---|---|
| M1 | Names, transforms, pivots and extents clean (UV2 comes at stage 6) | `qa_measure` |
| M2 | LOD0 triangles within `budgets.piece_tris.<FAMILY>` (or the piece's own `tris`) | `qa_measure --piece-tris` |
| M3 | Topology: no n-gons on lightmapped faces, no edges shared by 3+ faces, no loose geometry, no interior faces | `qa_measure`; interior faces by looking in X-ray |
| M4 | Shading: no pinching or faceting at the review distance | Topology audit renders, or Blender MCP `look` close-up in solid/matcap |
| M5 | Joints: pieces that meet share boundary vertices (no T-junction cracks when snapped) | Topology audit joint matching; fallback: snap two pieces and `look` at the seam in wireframe |
| M6 | Silhouette and proportions match the greybox piece it replaces (same footprint, same `Size`) | `qa_measure` extents, look |
| M7 | LODs (if the spec asks): named `_LOD1`, `_LOD2`, about 50% and 20% of LOD0, silhouette kept | `qa_measure` per-object tris, look |
| M8 | Collision as the spec says: `_COL` shell present and convex-ish, or none if Unity primitives are planned | Objects in the collection |

## Stage 6 - UVs

| Id | Check | How |
|---|---|---|
| U1 | UV0 distortion: angular p95 <= 1.15, no folded faces | UV audit |
| U2 | UV0 texel density within 10% of the family's `texel_density` (tiling and trim) or packed to it (unique) | UV audit |
| U3 | Trim pieces land on the right strip of the trim sheet | Look with the trim texture applied; UV audit for island positions |
| U4 | UV2 exists, no overlap, inside 0-1, padding >= the pixel padding for the lightmap size | `qa_measure` (UV layer count); UV audit on the second layer for the rest |
| U5 | Hard edges are seams on layers that take a baked normal map | UV audit |
| U6 | *advisory* Coverage of unique UV0 >= 65%, of UV2 >= 60% | UV audit |

## Stage 7 - Texturing

| Id | Check | How |
|---|---|---|
| X1 | Materials per family as planned (1-3), names `M_<FAMILY>_*` match the Unity materials | Blender material list vs spec |
| X2 | Texture sizes no larger than the spec's `map_px` and the platform max (1024 on Quest) | File dimensions |
| X3 | Channel packing as planned (e.g. metallic/AO/roughness in one map), normal maps in the right convention (OpenGL in Blender, Unity accepts it) | Inspect files |
| X4 | Tiling materials tile without visible seams at 3 repeats | Look at a test plane |
| X5 | Colour and value match the mockups under neutral light | `look`, compare with mockup swatches |
| X6 | Source files saved (`.sbs`, `.spp` or `.blend` node setup) next to exports so a change can be remade | List files |

## Stage 8 - Assemblies and master dressing

| Id | Check | How |
|---|---|---|
| A1 | ASM files contain only linked kit instances and socket empties | Like B2 for each ASM |
| A2 | No greybox geometry left: every linked piece collection has `kit_status` of `textured` or later (greybox is the first version of the piece, in the same collection, so nothing is re-linked) | Read the `kit_status` custom property on each linked collection |
| A3 | Snapped: placement positions on the grid (multiples of `grid.module`, or `sub_module` for trim), rotations multiples of 90 deg for grid pieces | `qa_measure` placements (`--module <sub_module>` for trim) |
| A4 | No z-fighting or interpenetration at joints visible from walkable areas | Look along joints |
| A5 | Final views match the mockups from the same camera positions | `references/visual-review.md` |

## Stage 9 - Export

| Id | Check | How |
|---|---|---|
| E1 | One FBX per piece collection, named after it, in `export/fbx/<FAMILY>/` | List files |
| E2 | Re-import one FBX per family into a blank Blender: scale 1, rotation 0, size matches the piece | Export checks; fallback: headless `import_scene.fbx` and read the dimensions |
| E3 | FBX triangle counts equal the audited LOD0 counts | Import, `qa_measure` |
| E4 | Two UV channels in every lightmapped FBX; material slot names unchanged from the previous export | Import, inspect |

## Stage 10 - Unity assembly

| Id | Check | How |
|---|---|---|
| N1 | One folder per piece (`Assets/World/Kits/<FAMILY>/<Piece>/`) with its FBX and a prefab variant; family materials in `<FAMILY>/_Shared/` | Unity MCP `manage_asset` search |
| N2 | No extracted per-FBX materials where `_Shared` ones exist; submesh count equals material slots | Unity MCP |
| N3 | Import settings: Read/Write off, Generate Lightmap UVs off, no cameras or lights, Animation Type None | Unity MCP `execute_code` reading `ModelImporter` |
| N4 | Placement sync committed for every scope; the last merge reports 0 conflicts and 0 blocked | Placement report |
| N5 | Spot check: three placements compared Blender `look` vs Unity screenshot from the same position | `references/visual-review.md` |
| N6 | Static flags as planned; instanced pieces are not Batching Static and their materials have GPU instancing on | Unity MCP |
| N7 | VRChat scene setup: one scene descriptor, spawns on floors, respawn height below the lowest floor, nothing on reserved or player layers; cross-platform worlds have Android texture overrides at 1024 or below and a mobile shader plan | Unity MCP; `vrchat-world-sdk-setup` checklist if installed |

## Stage 11 - Lighting and bake

| Id | Check | How |
|---|---|---|
| L1 | Bake completes with no UV overlap warnings in the console | Unity MCP `read_console` |
| L2 | Lightmap count and size within `budgets.lightmap` | Lightmap settings |
| L3 | No visible seams, splotches or light leaks at kit joints | Look at joints and corners |
| L4 | Avatars lit correctly: probe or Light Volume coverage in every walkable area (test with a capsule) | Look |
| L5 | Realtime lights within the platform limit (Quest: none on static geometry) | Scene query |

## Stage 12 - Interactivity

| Id | Check | How |
|---|---|---|
| I1 | Each system in `interactivity` exists and works in Play mode (ClientSim) | Unity MCP play, console; `vrchat-world-sdk-setup` for ClientSim use |
| I2 | No `Update()` loops where events would do; sync mode and payloads as `vrchat-udon` | Read scripts |
| I3 | Late joiner sees the right state | Build & Test with 2+ clients (ClientSim simulates only the local player), else reasoning from sync code |
| I4 | No console errors or warnings from Udon on start or interaction | `read_console` |

## Stage 13 - Optimisation audit

Load `vrchat-world-optimization` and run its pre-upload audit end to end, then:

| Id | Check | How |
|---|---|---|
| O1 | Every number in `budgets` measured and within it (triangles, SetPass, batches, materials, VRAM, download size per platform) | Stats panel, Profiler, build size report via Unity MCP |
| O2 | Quest build under 100 MB (hard limit) when `quest` is in `platforms` | Build report |
| O3 | Worst view in each zone measured, not the average | Stand at each zone's busiest point |
| O4 | Regressions since the last audit explained | Compare with the previous report in `world/reports/` |
| O5 | Every platform in `world.platforms` builds with no SDK validation errors or console errors, uses one blueprint ID, and passes a ClientSim walk and a 2-client Build & Test; publish fields drafted | Unity MCP, build logs |

## Platform targets

Practical targets, not SDK limits, except the **hard** one. Re-check against
https://creators.vrchat.com/platforms/android/quest-content-optimization/ - VRChat tightens these over time.

| Metric | PC | Quest |
|---|---|---|
| World triangles | 500k-1M | ~250k |
| Triangles in one view | < 300k | < 100k |
| SetPass calls | < 150 | < 50 |
| Batches | < 400 | < 150 |
| Unique materials | < 60 | < 25 |
| Max texture size | 2048 (4096 for one hero surface) | 1024 |
| Texture VRAM | < 1.5 GB | < 150 MB |
| Lightmaps | 1024-2048, few | 512-1024, non-directional |
| Download size | - | **100 MB (hard)** |
