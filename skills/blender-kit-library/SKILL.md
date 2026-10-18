---
name: blender-kit-library
description: Modular kits in Blender - copies of a piece drifting apart, linked libraries broken after files moved, KIT edits not showing in MASTER, link vs append, library overrides, naming, sizing or pivoting pieces, several agents on one environment. KIT, ASM and MASTER files, one writer per .blend, grid modules, kit_status, a create, link, place and audit script. Engine-neutral; for export see blender-to-unity, for layout sync with Unity blender-unity-placement-sync.
---

# Blender kit library: KIT, ASM and MASTER files

Lay out a modular environment across several .blend files so each piece is edited in one place, every copy stays
identical (so an engine can instance it), and several agents or people can work at once without overwriting each
other. Engine-neutral: it ends at well-formed piece collections, whatever engine they go to. Helpers:
`scripts/kit_library.py` (table below).

## Workflow

1. Fix the grid module (usually 0.5 m or 1 m) and the families with their material sets, and record them where the
   project keeps its decisions (the world spec, when `vrchat-world-orchestration` runs the build).
2. Start each new KIT, ASM or MASTER file from Blender run with no file
   (`blender -b --factory-startup --python-exit-code 1 --python task.py`): the task first calls
   `new_file(r"<project>/blender/kits/KIT_<FamilyName>.blend")`, which empties the scene (no default cube or
   Collection, which the audit would flag) and saves the file at once, so links can be stored relative to it.
   Without the helper: `bpy.ops.wm.read_factory_settings(use_empty=True)`, then `save_file(path)`, before linking.
3. One KIT file per family. For each piece: `new_piece("<FAMILY>_<Type>_<Size>_<Variant>")`, model it at the origin
   with the pivot rules below, and set its `kit_status` (`grey` for a new greybox piece).
4. Audit each KIT file at the project's module (Checking a kit, below) and fix every problem it lists.
5. Build each assembly in its own ASM file, then the MASTER layout, with `link_piece` (relative paths).
6. After a KIT or ASM file changes, `reload_libraries()` in any live session that links it.
7. End every headless run with `save_file()`: it saves without a `.blend1` backup.

## The three layers

| Layer | File | Holds | Never holds |
|---|---|---|---|
| KIT | `blender/kits/KIT_<FamilyName>.blend` (one per visual family) | One collection per piece, piece at the origin, its LODs and collision, the family's shared materials | Placement of anything in the world |
| ASM | `blender/asm/ASM_<Name>_<Variant>.blend`, one assembly per file, named after it | The one collection `ASM_<Name>_<Variant>` (a facade, a stall, a furnished room) made of **linked** KIT instances, plus empties for sockets | Original geometry. If an assembly needs a new shape, it becomes a KIT piece first |
| MASTER | `blender/MASTER.blend` | Layout only: linked KIT and ASM instances placed in the world, zone empties, a scale figure, lighting reference | Geometry, materials, appended copies |

Edit in the lowest layer that owns the thing: geometry in KIT, arrangement in ASM, placement in MASTER. One assembly
per file keeps each assembly's file, collection and engine prefab one-to-one (placement sync pairs them that way).

## Link, never append

- **Link** collections (`File > Link`, or `link_piece`) and place them as **collection instances**. Every instance
  points at the one collection in the KIT file, so editing the piece updates every placement and every copy stays an
  identical mesh (which is what GPU instancing in an engine needs).
- **Append** copies the data into the file. The copy drifts from the kit at the first edit and the instancing is gone.
  Do not append kit pieces into ASM or MASTER.
- **Library overrides** only when an instance needs a local change Blender cannot get otherwise (rare in a static
  world). An override is a fork: prefer a new kit variant (`_B`), and record any override with the project's
  decisions. Making a library override of a placed instance removes its instancing empty and instances the
  overridden collection instead
  (https://docs.blender.org/manual/en/latest/files/linked_libraries/library_overrides.html, checked 2026-10-17), so
  the placement and any placement id on it are gone: `blender-unity-placement-sync` reads that as a deletion.
- Use **relative paths** (`relative=True` when linking, `File > External Data > Make Paths Relative`) so the project
  survives being moved or cloned.
- After a KIT file changes on disk, reload it in the files that link it: `Library.reload()` on each changed
  `bpy.data.libraries` entry (`reload_libraries()` does all of them).
- **Links broken after files moved or renamed** (empty or pink instances, "cannot read library" warnings; the audit
  lists "linked library missing"): one headless run repairs every file that links anything, in any order, and
  reports what is still missing:
  `blender -b --factory-startup --python-exit-code 1 --python <skill>/scripts/kit_library.py -- --relink <project>/blender/kits <project>/blender/asm --files <every ASM .blend> <project>/blender/MASTER.blend`.
  A renamed KIT file adds `--renamed KIT_Old.blend=KIT_New.blend`; a renamed assembly, or a piece moved to another
  KIT file, takes the rename procedure (Naming). Details, ambiguous copies, live sessions, moved and renamed at once,
  and the manual route: `references/repair-links.md`.

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

Codes are 2-5 capitals. A project can add its own, recorded with their file and material set. `ZONE` pieces are
unique but are still authored as pieces and linked into MASTER like the others, so everything in the layout is a
collection instance and nothing needs a different export or sync path.

## Naming

```
<FAMILY>_<Type>_<Size>_<Variant>        EXT_Wall_2x3_A    STR_Stair_2x1x2_A    PROP_Chair_Free_B
ASM_<Name>_<Variant>                    ASM_ShopFront_A
M_<FAMILY>_<Name>                       M_EXT_Brick       M_TRIM_Sheet01
```

| Token | Rule |
|---|---|
| `Type` | PascalCase noun, letters and digits only |
| `Size` | Extents in whole grid modules, in X, Y, Z order, naming grid axes only: **any axis under one module is thickness and is skipped** (a wall's thickness, a floor slab). A wall is `2x3` (X by Z), a floor tile `2x2` (X by Y), a stair `2x1x2`; at a 0.5 m module a 2.0 x 0.3 x 3.0 m wall is `4x6` and a 0.5 x 0.5 x 2.5 m post `1x1x5`. `Free` for pieces not on the grid (props, foliage, zone shells) |
| `Variant` | Capital letter, optional digit: `A`, `B`, `A2` |

Regex: `^[A-Z]{2,5}_[A-Za-z0-9]+_(\d+(x\d+){0,2}|Free)_[A-Z]\d?$`, and `^ASM_[A-Za-z0-9]+_[A-Z]\d?$` for assemblies.

The **collection** carries the piece name. Inside it: the render mesh named like the piece, or LODs `<Piece>_LOD0`,
`<Piece>_LOD1`, `<Piece>_LOD2` as siblings, and an optional `<Piece>_COL` collision shell. Names are load-bearing:
linking, FBX export (one FBX per collection), engine prefab or asset names and placement sync all key on them.
Renaming a piece or an assembly is a breaking change. Rename the collection in its file (for an assembly, the ASM
file too, keeping one assembly per file named after it), and rename its exported file and engine asset to match.
Then in every file that places it (ASM files, then MASTER) link the renamed collection and re-point the existing
instances (`ob.instance_collection = <renamed collection>`) instead of deleting and re-placing them, so placement ids
survive; the old link is dropped when the file is saved. Moving a piece to another KIT file is the same procedure:
append the piece's collection into the new KIT file, delete it from the old one, then in every file that places it
link it from the new file and re-point the instances.

## Grid, pivots and scale

| Rule | Value |
|---|---|
| Unit | 1 Blender unit = 1 m |
| Grid module | Set once per world (typically 0.5 m or 1 m; trim and detail may use a 0.25 m sub-grid, audited at that module) |
| Grid piece pivot | **Bottom-left corner** of the footprint: the piece extends into +X, +Y and +Z from its origin |
| Free piece pivot | Floor centre (props), hinge (doors), base of trunk (trees), back-face centre (wall-mounted: switches, sconces, frames), top centre (ceiling-mounted: lamps). Front faces -Y at rot 0 |
| Piece transform in the KIT file | Origin at world origin, rotation and scale applied, `collection.instance_offset = (0, 0, 0)` |
| Placement rotation | Multiples of 90 deg about Z for grid pieces, so they stay on the grid |
| Dimensions | A `2x3` wall at a 1 m module is exactly 2 m wide (X) and 3 m high (Z). Model walls running along X, so their thickness is in +Y. Thickness is not a grid dimension: keep it under one module and constant per family, and record it |

With a bottom-left pivot, placing by hand lands on grid intersections when snapping is set to Snap To **Grid** (or
Increment with Absolute Increment Snap) and the viewport grid scale equals the module. Plain Increment snapping only
moves in grid steps from where the piece started, so an off-grid piece stays off-grid
(https://docs.blender.org/manual/en/latest/editors/3dview/controls/snapping.html, checked 2026-10-17). Rotations are
predictable too: a 90 deg turn pivots about the corner.

## One writer per file

A .blend file has exactly one writer at a time. Blender writes `<file>.blend@` and then renames it over the file
(https://projects.blender.org/blender/blender/src/branch/main/source/blender/blenloader/intern/writefile.cc, checked
2026-10-17), so readers that link from a KIT never see a half-written file, but two writers to the same file silently
lose one side's work.

- Kit work runs headless, one process per KIT file:
  `blender -b --factory-startup --python-exit-code 1 blender/kits/KIT_Arch_Exterior.blend --python task.py`,
  ending with `save_file()`. With factory settings `save_version` is 1, so a plain `bpy.ops.wm.save_mainfile()`
  also writes a `.blend1` backup beside the file, which the task was not briefed to write; `save_file()` sets
  `save_version = 0` for the save (https://docs.blender.org/api/current/bpy.types.PreferencesFilePaths.html, checked
  2026-10-17).
- MASTER is opened by one owner only (normally through Blender MCP). ASM files likewise get one owner per file.
- Files that link a changed library reload it rather than being reopened. A headless run (`blender -b`) opens the
  file fresh and already loads every library from disk, so there a reload changes nothing: check the result against
  the previous placement snapshot or render, not against the same session before the reload.

## The script

Load in Blender: `ns = {}; exec(open(r"<skill>/scripts/kit_library.py", encoding="utf-8").read(), ns)`, then call
`ns["new_piece"](...)` and so on. Paths starting with `//` are relative to the open .blend.

| Call | Run in | Does |
|---|---|---|
| `new_piece(name, parent=None)` | KIT or ASM file | Creates (or returns) the piece or assembly collection under `parent` (default the scene collection), rejects names outside the patterns, sets `instance_offset` to zero |
| `list_library(path)` | Any file | Piece and assembly collection names in another .blend |
| `link_piece(path, name, location=(0, 0, 0), rot_z=0, into=None, relative=True)` | ASM, MASTER | Links the collection (reusing an existing link) and places one instance, turned `rot_z` degrees about Z, into collection `into` |
| `link_collection(path, name, relative=True)`, `place(coll, location, rot_z, name=None, into=None)` | ASM, MASTER | The two halves of `link_piece` |
| `reload_libraries(paths=None)` | A live session | Reloads every linked library (or those in `paths`); returns their paths |
| `missing_libraries()`, `missing_ids()`, `relink(search_dirs, relative=True, renamed=None)` | ASM, MASTER | Lists libraries whose file is missing and linked data missing from its file; re-points each direct library at the same-named (or `renamed`) .blend under `search_dirs` and reloads it (save afterwards, unless `missing_ids(True)` lists data still missing); indirect links come back as "fix <ASM file> first", several candidates as "ambiguous" |
| `relink_files(blend_files, search_dirs, renamed=None)` | Blender run with no file | Relinks the files in passes until nothing changes, saves each that relinked cleanly, reopens them all; returns `(still, log)`: what each file still misses, and every pass's results |
| `audit_kit(module, materials=None)`, `audit_piece(coll, module)`, `problems(report)` | KIT file | The audit below at grid `module` metres (required); `problems` flattens a report to readable lines |
| `save_file(filepath=None)` | Any headless run | Saves (or saves as, creating the folder) with no `.blend1` backup, restoring `save_version` afterwards |
| `new_file(filepath)` | Blender run with no file | Empties the scene (factory startup emptied, preferences untouched) and saves it at `filepath`, creating folders |

API used, checked against Blender 5.2 on 2026-10-17: `bpy.ops.wm.read_homefile(use_factory_startup=True,
use_empty=True)` (unlike `read_factory_settings`, it leaves the preferences alone),
`bpy.data.libraries.load(path, link=True, relative=True)`
(https://docs.blender.org/api/current/bpy.types.BlendDataLibraries.html), `Library.reload()`
(https://docs.blender.org/api/current/bpy.types.Library.html), `Collection.instance_offset`
(https://docs.blender.org/api/current/bpy.types.Collection.html).

## Checking a kit

Run the audit in each KIT file at the world's grid module. It changes nothing.

```
blender -b --factory-startup --python-exit-code 1 <project>/blender/kits/KIT_Arch_Exterior.blend
        --python <skill>/scripts/kit_library.py -- --audit --module 0.5 [--json report.json]
```

It prints one line per piece and exits 1 on any problem (2 without `--module`). Always pass the real module: audited
at the wrong one, correct pieces fail and pieces built at the wrong size pass.

| Check | Rule |
|---|---|
| Name | Piece collections match the pattern; collections that hold objects but have no kit name are listed |
| Transforms | Every object in a piece at identity (origin at the pivot, rotation and scale applied); `instance_offset` zero |
| Footprint | Grid pieces: minimum corner at the origin, extents in whole modules matching the `Size` token (axes under one module skipped) |
| Materials | Named `M_<FAMILY>_<Name>`, matching `^M_[A-Z]{2,5}_[A-Za-z0-9][A-Za-z0-9_]*$` (a `.001` duplicate fails), and only the piece's family or `M_TRIM_*` (another set: `audit_kit(module, materials=("M_EXT_", ...))`) |
| Stray meshes | Mesh objects outside any piece collection |
| Libraries | Linked libraries whose file is missing, and linked data missing from a file that exists (renamed in it) |
| `kit_status` | A collection custom property: `grey`, `modelled`, `uv`, `textured`, `exported`. UV2 is required from `uv` on, filled material slots from `textured` on; a piece without `kit_status` gets every check |

## Getting the kit into an engine

Export one file per piece collection (FBX or glTF), named after the collection, at identity transform. For Unity
(export settings, per-piece folders, prefabs, shared family materials): `blender-to-unity`. To keep a MASTER layout
and a Unity scene in step both ways: `blender-unity-placement-sync`.
