# The world spec

`world/spec.yaml` is the contract between the master and every subagent. Start from `../templates/spec.yaml`.
Validate with `scripts/spec_validate.py`, draw with `scripts/spec_to_svg.py`. Coordinates are Blender world metres
(X east, Y north, Z up); rotations are degrees about Z, counter-clockwise seen from above.

## Sections

| Section | Holds | Filled at |
|---|---|---|
| `version` | `1` | 0 |
| `world` | `name`, `platforms` (`pc`, `quest`), `performance_tier`, `allow_generated_assets`, `mockups`, `style` | 0 |
| `tools` | `blender`, `unity_project`, `substance_designer`, `substance_painter`, `rizomuv` | 0 |
| `grid` | `module` (m), `sub_module`, `storey_height` | 2 |
| `families` | Per family code: `file`, `materials` (1-3), `texturing` (`tiling`/`trim`/`atlas`/`unique`), `texel_density` (px/m), `map_px`, `thickness` | 2-3 |
| `budgets` | `world_tris`, `view_tris`, `materials`, `setpass`, `batches`, `texture_vram_mb`, `download_mb` per platform, `piece_tris` per family, `lightmap` (`max_px`, `count`) | 2 |
| `pieces` | `name`, `desc`, `collision` (`box`/`mesh`/`none`), optional `tris`, `lods` | 2-3 |
| `assemblies` | `name`, `file`, `size` [x, y, z] m, `uses` [pieces] | 3 |
| `zones` | `id`, `name`, `kind`, `bounds` [x0, y0, x1, y1], `floor_z`, `placements`, `rooms` | 2 |
| `elevations` | `id`, `zone`, `facing`, `origin`, `courses` | 2 |
| `views` | `id`, `pos`, `target`, `lens`, `matches` (mockup path or null) | 2 |
| `interactivity` | `id`, `desc`, `sync` (`none`/`manual`/`continuous`) | 2 |
| `lighting` | `baker`, `mode`, `light_volumes` | 2 |

### Zones, rooms, openings, placements

```yaml
zones:
  - id: square                     # lowercase, used in file names (plan_square.svg)
    kind: exterior                 # exterior | interior
    bounds: [0, 0, 30, 27]
    placements:                    # coarse layout; the greybox integrator builds MASTER from these
      - {ref: ASM_ShopFront_A, pos: [2, 20, 0], rot: 0}     # pivot position (bottom-left corner)
    rooms:
      - id: bakery
        bounds: [2, 20.3, 8, 26]   # must lie inside the zone
        height: 3                  # >= 2.6
        openings:
          - {type: door, at: [4.5, 20.3], width: 1.2, height: 2.2}   # at = one end, on the room edge
```

### Elevations

An elevation is a facade written as courses of kit pieces: the bottom course first, pieces left to right as seen
from the front. `facing` is the direction the facade faces (`south` means you look at it from the south, looking
north, with +X to your right). `origin` is the facade's bottom-left corner in world space. Elevations take grid
pieces only, and every course should come out the same width. Agents build facades by walking the courses.

### Views

Named cameras that tie the build to the mockups. QA renders from these positions and never from a viewpoint chosen
after seeing the result. Give every mockup a view, and add one view per zone at standing eye height (1.7 m).

## Kit rules

These hold whether or not `blender-to-unity-vrchat` (which covers kit libraries in depth) is installed.

### Files

| Layer | File | Holds |
|---|---|---|
| KIT | `blender/kits/KIT_<FamilyName>.blend`, one per family | One collection per piece, at the origin, with its LODs, collision and the family materials |
| ASM | `blender/asm/ASM_<Name>.blend` | Assemblies built from **linked** kit pieces, plus socket empties |
| MASTER | `blender/MASTER.blend` | Linked KIT and ASM instances placed in the world, zone empties, scale figures. No geometry |

Link (collection instances, relative paths), never append. Library overrides only when unavoidable, recorded under
`flags.overrides` in the ledger.

### Names

```
<FAMILY>_<Type>_<Size>_<Variant>    EXT_Wall_2x3_A   STR_Stair_2x1x2_A   PROP_Crate_Free_A
ASM_<Name>_<Variant>                ASM_ShopFront_A
M_<FAMILY>_<Name>                   M_EXT_Brick
```

- `FAMILY`: 2-5 capitals, declared in `families`. Common: `EXT`, `INT`, `STR` (floors, stairs, roofs), `TRIM`,
  `PROP`, `FOL`, `ZONE` (unique shells, still authored as pieces).
- `Size`: whole modules in X, Y, Z order, skipping any axis thinner than half a module. Walls are `WxH`, floor tiles
  `WxD` (family `STR`), volumes `WxDxH`; `Free` for off-grid pieces.
- `Variant`: `A`, `B`, `A2`.
- Regex: `^[A-Z]{2,5}_[A-Za-z0-9]+_(\d+(x\d+){0,2}|Free)_[A-Z]\d?$` and `^ASM_[A-Za-z0-9]+_[A-Z]\d?$`.

Names are load-bearing: linking, FBX file names, Unity prefab names and placement sync all key on them. Renaming a
piece after stage 4 is a spec change with a task to re-link and re-place everywhere.

### Geometry conventions

| Rule | Value |
|---|---|
| Unit | 1 Blender unit = 1 m |
| Grid pivot | Bottom-left corner: the piece extends into +X, +Y, +Z from its origin |
| Free pivot | Floor centre (props), hinge (doors), trunk base (trees) |
| In the KIT file | Objects at identity transform, `collection.instance_offset` zero |
| Walls | Run along X; thickness in +Y, constant per family (`families.<F>.thickness`) |
| Placement | Grid pieces on whole modules (trim on `sub_module`), rotated in 90-degree steps |
| Status | Collection custom property `kit_status`: `grey`, `modelled`, `uv`, `textured`, `exported` |

## Changing the spec

Edit, run the validator, regenerate the diagrams, then mark every ledger task whose inputs changed as `todo`. A
change to zones, elevations, platforms or budgets after the spec gate re-opens the gate.
