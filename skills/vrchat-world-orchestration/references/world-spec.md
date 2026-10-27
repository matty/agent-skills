# The world spec

`world/spec.yaml` is the contract between the master and every subagent. Stage 0 copies `../templates/spec.yaml`
(version, world, tools and budget ceilings); the planning tasks tighten the budgets and add the rest.
`example-spec.yaml` next to this file is a complete one. Validate with `scripts/spec_validate.py` (a value of the
wrong type is an error, and a key it does not know, such as a misspelt `lighting_state`, a warning), draw with
`scripts/spec_to_svg.py` (commands in `mechanics.md`). Coordinates are Blender world metres (X east, Y north, Z up);
rotations are degrees about Z, counter-clockwise seen from above.

## Sections

| Section | Holds | Filled at |
|---|---|---|
| `version` | `1` | 0 |
| `world` | `name`; `platforms`: `pc`, `quest` (the Android build), `ios` (checked against the Quest limits); `scale` (`full`/`small`); `allow_generated_assets`; `mockups` (true only with a confirmed concept-art tool); `style`; `quality` (`pc_lead`: PC gets its own budgets and source sizes, mobile gets them through import overrides; `parity`: PC ships what mobile ships; "Quality tier" below) | 0 |
| `tools` | `blender` (CLI path), `blender_mcp` (true when the Blender MCP is connected), `unity_project`, `substance_designer`, `substance_painter`, `rizomuv`, `unity_packages` (installed; UdonSharp and ClientSim are inside `com.vrchat.worlds`), `build_modules` (`windows`, `android`, `ios`) | 0 |
| `grid` | `module` (m), `sub_module` (trim placement: it divides `module` into whole steps), `storey_height` | 2 |
| `families` | Per family code: `file` (`blender/MASTER.blend` in the `single` layout, the default; its KIT file when `split`), `materials` (1-3), `texturing` (`tiling`/`trim`/`atlas`/`unique`), `texel_density` (px/m on UV0, from the viewing-distance classes: T2048 under 0.75 m, T1024 0.75-1.5 m, T512 1.5-3 m, T256 3-6 m, T128 6-12 m, T64 beyond; `uv-unwrapping` has the rule), `map_px` (the source size, at most the PC maximum 2048: Android and iOS get 1024 or less from their import overrides at stage 10, QA N8 and X2), `thickness` (m, walls and slabs), optional `detail_map` (true: its materials get a finely tiled detail albedo and normal for the close look, the answer for walls players walk right up to), optional `tile_phase` for a `tiling` family (`grid`, the default: its tile, `map_px / texel_density` m, must divide `grid.module` and `grid.storey_height`, or the pattern jumps at joints between instanced pieces; `variants`: phase variants of each piece (`<Piece>_P<k>`, k the pivot's distance along the piece's own +X, mod the tile, in modules), a tile of whole modules that divides the storey; `world_uv`: a world-space UV shader on every platform; the validator checks every placement of a `grid` or `variants` family against the world tile grid), optional `turn_symmetry` for a tiling family's floors and ceilings (90, 180 or 360, the default: the turns its texture looks the same under; a floor turned otherwise turns its pattern and the validator errors) | 2-3 |
| `budgets` | `world_tris`, `view_tris`, `materials`, `setpass`, `batches`, `texture_vram_mb`: one number for every platform, or a mapping per platform (`setpass: {pc: 100, quest: 50}`); `download_mb` per platform (mobile hard limit 100 MB, where MB = 2^20 bytes). In a mapping, `ios` falls back to the `quest` value, so it is never required; give it only to differ. `piece_tris` per family; `lightmap`: `max_px`, `count`, `texels_per_m` (= Unity's Lightmap Resolution), optional `min_footprint_px` (default 64) | 0 (the template's Quest ceilings), 2 |
| `pieces` | `name`, `desc`, `collision` (`box`/`mesh`/`none`); optional `tris`, `lods` (LODs after LOD0), `lod_lightmap` (default true: each LOD gets its own lightmap space; `false`: LOD1+ probe-lit), `lightmap` (`false` = probe-lit), `lightmap_scale` (Unity's Scale In Lightmap, default 1), `size` [x, y, z] m (required for a one-number Size, whose extents it gives; for Free pieces, without it a lightmapped one is left out of the lightmap check), `ref` (reference images it is modelled to), `detail` (each feature with its size: what stage 5 models and QA's G4 checks), `bake` (true: its detail is baked from a high poly, built at stage 5 and gated by QA's M10) | 2-3 |
| `look` | The art direction: `references`, `wear`, `lighting_mood`, `quality_bar`, `lead_family`, `materials` targets ("Look" below) | 2 |
| `assemblies` | `name`, `file` (`blender/MASTER.blend` in the `single` layout; `split`: `blender/asm/<name>.blend`, one assembly per ASM file), `size` [x, y, z] m, `uses` {piece: count} | 3 |
| `zones` | `id`, `name`, `kind` (`exterior`/`interior`), `bounds` [x0, y0, x1, y1], `floor_z`, `placements`, `rooms`; optional `lighting_states` (default 1: the number of states of a light players switch in the zone, each a baked copy of its static geometry; "Lightmap check"), `switch` (the switch those states follow; default the zone's own id) and `mirrors` (below) | 2 |
| `elevations` | `id`, `zone`, `facing`, `origin`, `courses` | 2 |
| `views` | `id`, `pos`, `target`, `lens` (mm), `matches` (the mockup's path, or `null` without mockups) | 2 |
| `interactivity` | `id` (unique: it names the `T-UDON-<ID>` task), `desc`, `sync` (`none`/`manual`/`continuous`) | 2 |
| `lighting` | `baker` (`progressive`/`bakery`; it also sets whose footprint stage 6 packs the UV2 for, passed as `lightmapper`), `mode` (`baked`: every light Baked, required with `quest` or `ios`: a cross-platform world shares one bake, and Quest/iOS show no realtime shadows (Standard Lite takes the main directional light unshadowed; Lightmapped takes none); `mixed`: PC-only worlds). A light players switch is planned with `vrchat-lighting-and-baking` and recorded as the zone's `lighting_states`, `light_volumes` (true only when the package is installed), optional `notes` | 2 |

The planner writes every section except `version`, `world` and `tools`, which the master owns.

### Zones, rooms, openings, placements

```yaml
zones:
  - id: square                     # lowercase, used in file names (plan_square.svg)
    name: Market Square
    kind: exterior                 # exterior | interior
    bounds: [0, 0, 30, 27]
    floor_z: 0
    placements:                    # coarse layout; the greybox integrator builds MASTER from these
      - {ref: ASM_ShopFront_A, pos: [2, 20, 0], rot: 0}     # pivot position (bottom-left corner)
    rooms:
      - id: bakery
        name: Bakery
        bounds: [2, 20.3, 8, 26]   # must lie inside the zone
        height: 3                  # >= 2.6
        openings:
          - {type: door, at: [4.4, 20.3], width: 1.2, height: 2.2}
          - {type: window, at: [6.4, 20.3], width: 1.2, height: 1.5, sill: 0.9}
```

An opening's `at` is its low end on a room edge (the smaller x on a south or north edge, the smaller y on a west or
east edge), and it runs `width` m along that edge; the validator rejects one that does not lie along an edge.
`sill` is the height of its bottom above the zone's floor (default 0, right for a door); elevations draw the opening
from `sill` to `sill + height`.

### Mirrors

A zone's `mirrors` are the slots `T-UNITY-SETUP` puts a VRC Mirror Reflection in, off by default:
`mirrors: [{id: hall_mirror, pos: [3, 4.8, 1.6], rot: 0, size: [1.2, 2]}]`. `pos` is the mirror's centre, `size` its
width and height in metres, `rot` its facing in degrees about Z (at 0 it looks along -Y, like a Free piece's front).
A toggle for it is an `interactivity` entry. Plans draw each slot. In Unity the slot becomes the SDK's VRCMirror
prefab at position (-x, z, -y) from `pos`, Y rotation 180 - rot and scale (width, height, 1): the prefab is a Unity
Quad whose front faces -Z, so the -rot that placement sync gives kit pieces would leave it facing the wall.

### Elevations

An elevation is a facade written as courses of kit pieces: the bottom course first, pieces left to right as seen
from the front. `facing` is the direction the facade faces (`south` means you look at it from the south, looking
north, with +X to your right). `origin` is the facade's bottom-left corner in world space. Elevations take grid
pieces only, and every course should come out the same width. An elevation documents a facade; what builds it is its
placements (the facade's assembly, or its pieces, in `zones[].placements`), so the validator warns about a piece that
appears only in an elevation: nothing would place it in MASTER, and the lightmap check cannot count it. Agents build
a facade's assembly by walking the courses.

An elevation's `zone` is the zone its facade is placed in, usually the one the viewer stands in (a shop front placed
in the plaza belongs to the plaza), except that a facade a light switch changes is placed in the switched zone
("Lightmap check"). Its drawing shows the openings that run along the facade line, from rooms in any zone, so a front
shared by an exterior and an interior zone keeps its doors and windows; an opening in a side wall, at right angles to
the facade, is left out.

### Views

Named cameras that tie the build to the mockups. QA renders from these positions and never from a viewpoint chosen
after seeing the result. Give every mockup a view, and add one view per zone at standing eye height (1.7 m).

### Look

`world.style` is one line for prompts. `look` is what modelling, texturing, lighting and QA judge the build against,
so a world without mockups still has a target. The planner fills it at stage 2 from the brief and the user's images
(saved under `world/refs/`):

```yaml
look:
  references: [world/refs/market_dusk_01.jpg, world/refs/shopfront_02.jpg]   # the place, its materials and light
  quality_bar: [world/refs/quality_bar_01.jpg]     # optional: finished work at the level aimed for
  wear: weathered                                  # pristine | lived-in | weathered | derelict
  lighting_mood: "dusk: 2700 K gas lamps against a 7500 K sky, deep but readable shadows"
  lead_family: EXT                                 # textured first; the look gate follows it
  materials:                                       # optional targets per material (QA X5 and X8)
    M_EXT_Brick: {ref: world/refs/brick_01.jpg, albedo_srgb: [70, 140], roughness: [0.7, 0.95], metal: false,
                  wear: "soot near the base, cleaner under the cornice"}
```

- `albedo_srgb` is the dielectric base colour's median luma in sRGB (0-255) and `roughness` the median roughness
  (1 - smoothness); QA's `pbr_check` reads both. Keep targets inside 30-240, the range every base colour is held to.
- `lead_family` is the family whose materials set the direction, usually the one with the most visible surface (the
  facades, the main walls). Its `T-TEX-<FAMILY>` runs first and the **look gate** follows it (`stages.md`, stage 7).
- Piece `ref` and `detail` carry the same intent down to one piece: `detail: ["sill: 60 mm projection, 50 mm thick",
  "frame: 70 mm wide, 30 mm reveal"]`. Without a size, stage 5 takes one from `blender-mesh-topology`'s real-world
  sizes and reports it.
- Without `look`, the validator notes it and QA judges against `world.style` and the piece descs alone.

### Quality tier

`world.quality`, asked at intake, decides whether the PC build is held to the mobile platform:

| | `pc_lead` | `parity` |
|---|---|---|
| Budgets | Per platform: `{pc: ..., quest: ...}`, PC up to the PC targets | One number each: the mobile targets bind PC too |
| Source maps (`map_px`) | Sized for PC (up to 2048); Android and iOS get 1024 or less from their import overrides (stage 10) | 1024 or less, the same on every platform |
| PC-only extras | Detail maps, decor and post-processing switched per build target (`vrchat-world-sdk-setup`) | None |
| Lightmaps | One bake for every platform at Max Lightmap Size 1024 (`vrchat-lighting-and-baking`) | The same |

The validator notes a `pc_lead` world whose budgets are all one number (PC held to mobile's), and a cross-platform
world with no `quality` (parity assumed).

### Lightmap check

The validator plans the lightmaps before anything is modelled. Unity gives each lightmapped renderer a texel scale
of `texels_per_m x sqrt(A / b) x Scale In Lightmap` px per UV unit, its footprint: A is the surface area, b the UV2
charts' bounding box (the chart box) as a share of the 0-1 tile (0.79-0.95 on the dry run's five renderers, which the
formula matched within 0.6%; Unity 2022.3.22f1, 2026-10-16). The footprint sets the UV2 gaps and the 64 px rule
below. Before any UV2 exists the validator plans with b = 0.85 (the dry-run wall's value) and the bounding box's
surface as A.

The atlas cost is not the footprint squared: Unity packs each renderer's chart box, not its whole tile, so a renderer
costs `(texels_per_m x Scale In Lightmap)^2 x A` px^2 whatever its UV2 layout (Unity 2022.3.22f1, measured
2026-10-17). Empty space inside the chart box still costs texels, so stage 6 packs the charts to fill it. LOD1+ get
their own atlas space at texel scale 0.5^n (LOD1 0.5, LOD2 0.25), so each costs 0.25^n of its area: the validator adds
them from the piece's `lods` (LOD1 and LOD2 add about 31%), unless `lod_lightmap: false` makes LOD1+ probe-lit
(Receive Global Illumination: Light Probes), which takes them out of the atlas.

With `lighting.baker: bakery` it plans with Bakery's sizing instead, read from Bakery's scripts (`ftBuildGraphics.cs`
as installed in a Unity 2022.3.22f1 project, 2026-10-24; not yet measured in a bake). A renderer's rect has side
`L = texels_per_m x sqrt(2 x A x Scale In Lightmap)`: Scale In Lightmap acts on the area, so a linear factor s needs
s^2. Its footprint is `(L - 6) / sqrt(b)`, because the Default atlas packer insets each rect 3 texels. It costs
`L^2 = 2 x A x Scale In Lightmap x texels_per_m^2` px^2 for square UV2 bounds, twice Unity's at scale 1. Each
lightmapped LOD costs its own area, with no 0.5^n. Oblong UV2 bounds cost `L^2 x` their aspect, which nothing shows
before UV2 exists. The thresholds below were measured with Unity's packer and are assumed for Bakery's.

It sums cost x copies x lighting states, the copies being the placements in zones and inside placed assemblies
(`uses` counts) and the lighting states the zone's `lighting_states`, and compares it with `max_px^2 x count`: a
warning above 0.65 of that area (plan to stay under it), an error above 0.80, where a spill to another map is likely.
At Lightmap Padding 2 (Unity 2022.3.22f1, measured 2026-10-17), kit-like mixed sets spilled at 0.79-0.90 of box fill
(mean 0.85) and equal full-tile squares only at 0.97, so 0.65 plans below every measured spill; a larger padding
lowers every spill. Without `max_px` the capacity check is skipped, with a warning.

Over capacity, the order of remedies depends on the stage. Before stage 6: lower `texels_per_m`, or add a map
(`budgets.lightmap.count`). Once UV2 is packed: add a map, or make small Free props or LOD1+ (`lod_lightmap: false`)
probe-lit; never lower `texels_per_m` then, because the packed UV2 gaps were sized for it.

A light players switch changes the light in its zones only, and only their pieces get state copies, so every piece
the switch changes is placed in one of them. A room it lights inside a bigger zone (a shop in the market square)
becomes its own zone with `lighting_states`, and the facade it shares with the street is placed in the switched zone,
with its elevation. A switched zone follows its `switch` (default: its own id): zones naming one switch change
together and need the same `lighting_states`; different switches are independent. A piece two switches light (a
wall or slab between independently switched rooms) is split, a wall face or a ceiling per room, or planned per
combination of states with `vrchat-lighting-and-baking`. The validator notes a zone on another switch, or none, on
the same storey, that places a wall or facade along a switched zone's edge (not merely touching it) or that the
switched zone's openings face; and a probe-lit piece (`lightmap: false`) in a switched zone, which keeps one state,
since one light probe set serves every state.

Under 64 px (house guidance, no published source), the two kinds of piece differ:

| Piece | Under 64 px |
|---|---|
| Free prop: a Free piece of `PROP` or `FOL` (the validator's `PROBE_LIT_FAMILIES`) | Probe-lit: takes no lightmap space, warned until the spec says `lightmap: false` (in Unity, Receive Global Illumination: Light Probes, still Contribute GI). In a zone with `lighting_states` it changes with the switch, so it stays lightmapped in each copy and counts |
| Every other piece: grid pieces (walls, floors, ceilings), `ZONE` shells and Free pieces of other families | Never made probe-lit by this rule: it stays lightmapped, counts in the fill and gets a NOTE (not a warning) suggesting a higher `lightmap_scale` or `texels_per_m` if it needs more texels. Facades at the lighting skill's 6-10 texels/m sit under 64 px by design; at 15 texels/m a 2 x 3 x 0.2 m wall gets about 61 px |

Any piece can still be made probe-lit on purpose with `lightmap: false`.

UV2 gaps are packed at stage 6, per modelled mesh, for the worst case b = 1 (a fill pack's bounding box approaches the
whole tile): at least 2 texels at `texels_per_m x sqrt(A) x lightmap_scale` px (x 0.5^n for LODn), with A the mesh's
real surface area, so the gap in UV units is `2 / (texels_per_m x sqrt(A) x lightmap_scale x 0.5^n)`, with at least 1
texel to the tile edge. That keeps 2 texels whatever the packer does; checks after packing (QA U4, and L6 after the
bake) use the measured b. Never size the gaps from the bounding box: an opening or an open shell has much less area
than its box (the example door bay: 11.04 m2 against 15.00 m2), and gaps sized from the box came out at 1.73 texels on
the real mesh. Never shrink `lightmap_scale` below what a piece's UV2 gaps were packed for.

`spec_validate.py world/spec.yaml --footprints` prints each piece's planning cost and footprint (the box's surface as
A, b = 0.85), its placements and the fill, for the lighting brief. It plans the lightmap fill only; stage 6 sizes the
gaps (`stages.md`). Pieces in an unplaced assembly or only in an elevation are not counted; the validator warns about
both.

## Kit rules

These hold whether or not `blender-kit-library` (which covers kit libraries in depth) is installed.

### Files

The ledger's `intake.blend_layout` decides: `single` (the default) unless the user explicitly asked for `split`.

| Layer | `single` (default): collections in `blender/MASTER.blend` | `split`: separate files | Holds |
|---|---|---|---|
| KIT | `KIT/KIT_<FAMILY>/<piece>`, `KIT` excluded from the view layer | `blender/kits/KIT_<FamilyName>.blend`, one per family (`small` scale: one `KIT_World.blend` may hold every family) | One collection per piece, at the origin, with its LODs, collision and the family materials |
| ASM | `ASM/ASM_<Name>_<Variant>`, `ASM` excluded from the view layer | `blender/asm/ASM_<Name>_<Variant>.blend`, one assembly per file, named after it | The one collection `ASM_<Name>_<Variant>`, built from instances of kit pieces (`split`: linked), plus socket empties. Its Unity prefab is `Assets/World/Assemblies/ASM_<Name>_<Variant>.prefab` |
| MASTER | The `MASTER` collection (zones may get `MASTER_<Zone>` children); `REF` beside it | `blender/MASTER.blend` | Instances of pieces and assemblies placed in the world, zone empties; scale figures in `REF`. No geometry |

Place collection instances, never copies. `split`: link them by relative paths, never append; library overrides only
when unavoidable, recorded under `flags.overrides` in the ledger. `single`: the scene property `kit_layout =
"single"` marks the file, and every task that writes it keeps the user's edits (`SKILL.md`, rule 5).

### Names

```
<FAMILY>_<Type>_<Size>_<Variant>    EXT_Wall_2x3_A   STR_Stair_2x1x2_A   PROP_Crate_Free_A
ASM_<Name>_<Variant>                ASM_ShopFront_A
M_<FAMILY>_<Name>                   M_EXT_Brick
<Piece>_LOD0, _LOD1, _LOD2          EXT_Wall_2x3_A_LOD1 (siblings inside the piece collection)
<Piece>_COL                         EXT_Wall_2x3_A_COL (collision mesh)
```

- `FAMILY`: 2-5 capitals, declared in `families`. Common: `EXT`, `INT`, `STR` (floors, stairs, roofs), `TRIM`,
  `PROP`, `FOL`, `ZONE` (unique shells, still authored as pieces).
- `Size`: whole modules in X, Y, Z order, skipping any axis under one module (that axis is thickness: a 2 x 0.3 x
  3 m wall is `2x3` at a 1 m module and `4x6` at 0.5 m; a 0.5 x 0.5 x 2.5 m post at 0.5 m is `1x1x5`). Walls are
  `WxH`, floor tiles `WxD` (family `STR`), volumes `WxDxH`; `Free` for off-grid pieces. A family whose `thickness`
  is one module or more has no thin axis, so its pieces need all three numbers (the validator warns). A one-number
  Size (`EXT_Pillar_3_A`) could be a post or a beam, so such a piece must give `size: [x, y, z]`, which sets its
  extents (an error without it).
- `Variant`: `A`, `B`, `A2`.
- Regex: `^[A-Z]{2,5}_[A-Za-z0-9]+_(\d+(x\d+){0,2}|Free)_[A-Z]\d?$` and `^ASM_[A-Za-z0-9]+_[A-Z]\d?$`.

Names are load-bearing: linking, FBX file names, Unity prefab names and placement sync all key on them. Renaming a
piece after stage 4 is a spec change (it re-opens the spec gate) and a task that renames it, its FBX and its Unity
asset: `single`, renaming its collection in MASTER, which every instance follows; `split`, renaming it in the KIT
file, then in each ASM and MASTER file linking the renamed collection and re-pointing the existing instances
(`ob.instance_collection = <renamed collection>`), so their placement ids survive. Never delete and
re-place them: placement sync then sees new pieces and conflicts (the `blender-kit-library` procedure). That task is
`T-RENAME-<PIECE>`, with its own write row in `stages.md`.

### Geometry conventions

| Rule | Value |
|---|---|
| Unit | 1 Blender unit = 1 m |
| Grid pivot | Bottom-left corner: the piece extends into +X, +Y, +Z from its origin |
| Free pivot | Floor centre (props; round pieces such as towers and apses, which never have a whole-module diameter, are Free pieces pivoted here too), hinge (doors), base of trunk (trees), back-face centre (wall-mounted: switches, sconces, frames), top centre (ceiling-mounted: lamps). Front faces -Y at rot 0 |
| In the piece collection | Objects at identity transform, `collection.instance_offset` zero |
| Walls | Run along X; thickness in +Y, constant per family (`families.<F>.thickness`) |
| Placement | Grid pieces on whole modules (`TRIM` pieces on `sub_module`), rotated in 90-degree steps: the validator errors otherwise, as QA blocks on it. Free pieces and assemblies are exempt. Trims sit on wall faces, so a family's `thickness` should be a multiple of `sub_module` (the validator warns) |
| LODs | When `lods` > 0: `<Piece>_LOD0` (the main mesh), `<Piece>_LOD1` (about 50%), `<Piece>_LOD2` (about 20%) as siblings in the piece collection |
| Status | Collection custom property `kit_status`: `grey`, `modelled`, `uv`, `textured`, `exported` |

## Changing the spec

Edit, run the validator and regenerate the diagrams (stale ones are removed). Then, in the ledger:

- Through stage 4: every task whose inputs changed goes back to `todo` (attempts 0, the old count logged). Grey boxes
  are cheap to redo.
- After stage 4: a finished task is never re-run, since a kit task would rebuild every piece of its file over
  finished work. A rename gets `T-RENAME-<PIECE>`. A size change gets one new task, limited to that piece, in the
  piece's latest stage by its `kit_status` (`T-MOD-EXT-2` for a modelled piece, `T-UV-EXT-2` once it has UVs, the
  next free number): its brief resizes the piece and redoes what each stage it has passed made, and QA checks it with
  those stages' ids. A piece still `grey` needs nothing: its `T-MOD` task builds the new size. Anything else gets a
  new task, limited to what changed, of the stage that made it; after the bake, a `T-LIGHT-<n>` follows.
- A grid piece's new size is a new Size token, so a size change is also a rename: `T-RENAME-<PIECE>` first, then the
  resize, or one task that does both. A piece of an `atlas` family that grows needs the whole atlas repacked, since
  keeping its islands drops its texel density below the 0.8-1.25x band, so that task covers the family's atlas UVs
  and texture, not the one piece.
- Tasks that have not started pick the change up when they are dispatched.

Re-open a gate only for these changes after it:

| Gate | Re-opens for |
|---|---|
| spec | A piece, zone or elevation removed or renamed; a platform added or removed; a world budget loosened |
| greybox | The same, plus a placement moved or a piece's size changed |

These do not re-open it:
- Planned completion: `T-KIT-PLAN` completing the pieces, families and assemblies, or tightening budgets.
- A change the user has already approved in their own words, logged with the quote.
- Recording a value already in effect, such as the resolution a bake used.

Re-opening is a ledger step (`ledger.md`): keep the old decision in the gate's `history`, set it `pending`, record
the task that re-opened it in `reopened_by`, and ask with the change (`world/spec.approved.yaml`, kept at each
approval, shows the delta). Every task downstream of the gate that has not started is held until the user approves;
one already running finishes, and one whose session died goes back to `todo` (same attempt).
