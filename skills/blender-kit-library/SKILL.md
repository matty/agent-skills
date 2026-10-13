---
name: blender-kit-library
description: Organise a modular environment kit across several Blender files - KIT files (one per visual family, one collection per piece), ASM files of linked assemblies and a layout-only MASTER file, linking instead of appending, library overrides, relative paths and reloading, piece naming (<FAMILY>_<Type>_<Size>_<Variant>), grid modules and bottom-left pivots, one writer per .blend, plus a script that creates, links, places and audits pieces. Use when building a modular kit or a large scene in Blender, when copies of a piece drift apart or stop being identical, when several agents or people must work on one environment at once, when deciding how kit pieces are named, sized or pivoted, or when a scene's .blend files need structuring; engine-neutral - for getting pieces into Unity see blender-to-unity, for syncing a layout with Unity see blender-unity-placement-sync.
---

# Blender kit library: KIT, ASM and MASTER files

How to lay out a modular environment across several .blend files so pieces are edited in one place, every copy stays
identical (so an engine can instance it), and several agents or people can work at once without overwriting each
other. Engine-neutral: it ends at well-formed piece collections, whatever engine they go to.
Helpers: `scripts/kit_library.py`.

## The three layers

| Layer | File | Holds | Never holds |
|---|---|---|---|
| KIT | `blender/kits/KIT_<FamilyName>.blend` (one per visual family) | One collection per piece, piece at the origin, its LODs and collision, the family's shared materials | Placement of anything in the world |
| ASM | `blender/asm/ASM_<Name>.blend` | Assemblies: a facade, a stall, a furnished room. One collection per assembly made of **linked** KIT instances, plus empties for sockets | Original geometry. If an assembly needs a new shape, it becomes a KIT piece first |
| MASTER | `blender/MASTER.blend` | Layout only: linked KIT and ASM instances placed in the world, zone empties, a scale figure, lighting reference | Geometry, materials, appended copies |

Edits always happen in the lowest layer that owns the thing: geometry in KIT, arrangement in ASM, placement in MASTER.

## Link, never append

- **Link** collections (`File > Link`, or `kit_library.link_piece`) and place them as **collection instances**. Every
  instance points at the one collection in the KIT file, so editing the piece updates every placement and every copy
  stays an identical mesh (which is what GPU instancing in an engine needs).
- **Append** copies the data into the file. The copy drifts from the kit at the first edit and the instancing is gone.
  Do not append kit pieces into ASM or MASTER.
- **Library overrides** only when an instance genuinely needs a local change Blender cannot get otherwise (rare in a
  static world). An override is a fork: record it in the ledger and prefer a new kit variant (`_B`) instead.
- Use **relative paths** (`relative=True` when linking, `File > External Data > Make Paths Relative`) so the project
  survives being moved or cloned.
- After a KIT file changes on disk, reload it in the files that link it: `lib.reload()` for each changed
  `bpy.data.libraries` entry (`kit_library.reload_libraries()` does all of them).

## Families

Split kits by **visual family / material set**, so each family lands on 1-3 materials and one atlas or trim sheet.

| Code | Typical file | Contents |
|---|---|---|
| `EXT` | `KIT_Arch_Exterior.blend` | Facade walls, windows, doors, cornices |
| `INT` | `KIT_Arch_Interior.blend` | Interior walls, skirting, ceilings, interior doors |
| `STR` | `KIT_Structure.blend` | Floors, stairs, roofs, columns, beams |
| `TRIM` | `KIT_Trim.blend` | Strips and edge pieces that read off a trim sheet |
| `PROP` | `KIT_Props_<Theme>.blend` | Furniture and clutter (one file per theme) |
| `FOL` | `KIT_Foliage.blend` | Plants, trees, grass cards |
| `ZONE` | `KIT_Zone_<Zone>.blend` | Unique non-repeating shells for one zone (terrain, a hero building shell) |

Codes are 2-5 capitals. A project can add its own; the world spec lists them with their file and material set.
`ZONE` pieces are unique but are still authored as pieces and linked into MASTER like the others, so everything in
the layout is a collection instance and nothing needs a different export or sync path.

## Naming

```
<FAMILY>_<Type>_<Size>_<Variant>        EXT_Wall_2x3_A    STR_Stair_2x1x2_A    PROP_Chair_Free_B
ASM_<Name>_<Variant>                    ASM_ShopFront_A
M_<FAMILY>_<Name>                       M_EXT_Brick       M_TRIM_Sheet01
```

| Token | Rule |
|---|---|
| `Type` | PascalCase noun, letters and digits only |
| `Size` | Extents in whole grid modules, in X, Y, Z order, **skipping any axis thinner than half a module** (wall thickness, a floor slab). A wall is `2x3` (X by Z), a floor tile `2x2` (X by Y), a stair `2x1x2`. `Free` for pieces not on the grid (props, foliage, zone shells) |
| `Variant` | Capital letter, optional digit: `A`, `B`, `A2` |

Regex: `^[A-Z]{2,5}_[A-Za-z0-9]+_(\d+(x\d+){0,2}|Free)_[A-Z]\d?$`, and `^ASM_[A-Za-z0-9]+_[A-Z]\d?$` for assemblies.

The **collection** carries the piece name. Inside it: the render mesh with the same name (or `_LOD0`, `_LOD1`...
siblings), and an optional `<Piece>_COL` collision shell. Names are load-bearing: linking, FBX export (one FBX per
collection), engine prefab or asset names and placement sync all key on them. Renaming a piece is a breaking change. Do it in
the KIT file, then re-link and re-place everywhere, and note it in the ledger.

## Grid, pivots and scale

| Rule | Value |
|---|---|
| Unit | 1 Blender unit = 1 m |
| Grid module | Set once per world in the spec (typically 0.5 m or 1 m; trim and detail may use a 0.25 m sub-grid) |
| Grid piece pivot | **Bottom-left corner** of the footprint: the piece extends into +X, +Y and +Z from its origin |
| Free piece pivot | Floor centre (props), hinge (doors), base of trunk (trees) |
| Piece transform in the KIT file | Origin at world origin, rotation and scale applied, `collection.instance_offset = (0, 0, 0)` |
| Placement rotation | Multiples of 90 deg about Z for grid pieces, so they stay on the grid |
| Dimensions | A `2x3` wall at a 1 m module is exactly 2 m wide (X) and 3 m high (Z). Model walls running along X, so their thickness is in +Y. Thickness is not a grid dimension: keep it constant per family and record it in the spec |

A bottom-left pivot makes a piece snap to grid intersections with vertex snapping off and increment snapping on, and
makes rotations predictable (a 90 deg turn pivots about the corner).

## One writer per file

A .blend file has exactly one writer at a time. Blender saves via a temp file and a rename, so readers that link
from a KIT never see a half-written file, but two writers to the same file silently lose one side's work.

- Kit work runs headless, one process per KIT file:
  `blender -b blender/kits/KIT_Arch_Exterior.blend --python task.py`, ending with
  `bpy.ops.wm.save_mainfile()`.
- MASTER is opened by one owner only (normally through Blender MCP). ASM files likewise get one owner per file.
- Files that link a changed library reload it rather than being reopened.

## Checking a kit

`kit_library.audit_kit()` runs inside the KIT file and reports, per piece collection: name against the regex, origin
and instance offset at zero, unapplied transforms, footprint against the `Size` token at the grid module, materials
outside the family's `M_<FAMILY>_*` set, missing UV2, and stray objects outside any piece collection. It changes
nothing.

## Getting the kit into an engine

Export one file per piece collection (FBX or glTF), named after the collection, at identity transform. For Unity
(export settings, per-piece folders, prefabs, shared family materials): `blender-to-unity`. To keep a MASTER layout
and a Unity scene in step both ways: `blender-unity-placement-sync`.
