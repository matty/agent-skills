---
name: blender-kit-library
description: Modular kits in Blender - copies of a piece drifting apart, KIT edits not showing in MASTER, editing a MASTER the user also edits, linked libraries broken after files moved, naming, sizing or pivoting pieces. One MASTER .blend with KIT, ASM and layout collections by default (split files on request), syncing with the user's changes, grid modules, kit_status, a create, place, snapshot and audit script. Engine-neutral; export blender-to-unity, Unity layout sync blender-unity-placement-sync.
---

# Blender kit library: KIT, ASM and MASTER

Lay out a modular environment so each piece is edited in one place, every copy stays identical (so an engine can
instance it), and the user and agents can edit it without overwriting each other. Engine-neutral: it ends at
well-formed piece collections, whatever engine they go to. Helpers: `scripts/kit_library.py` (table below).

## Choose the file layout first

| Layout | When | Files |
|---|---|---|
| `single` (**default**) | Always, unless the user explicitly asks for separate files | One `blender/MASTER.blend` holding the KIT pieces, the assemblies and the layout as collections |
| `split` | Only when the user asks for it (typically a large world with several people or agents modelling families at the same time) | `blender/kits/KIT_<FamilyName>.blend` per family, `blender/asm/ASM_<Name>_<Variant>.blend` per assembly, `blender/MASTER.blend` linking them |

Never pick `split` on your own: one file is far easier to keep in step on a small project. Record the decision with
the user's words where the project keeps its decisions (`vrchat-world-orchestration`: the ledger's
`intake.blend_layout`); the file records it too, as the scene custom property `kit_layout` (`"single"`), which
`setup_single_master()` sets and the audit, QA and placement-sync scripts read. No property means a split file.
Everything below applies to both layouts unless it says otherwise.

## Workflow

1. Fix the grid module (usually 0.5 m or 1 m) and the families with their material sets, and record them where the
   project keeps its decisions (the world spec, when `vrchat-world-orchestration` runs the build).
2. Start the file from Blender run with no file (`blender -b --factory-startup --python-exit-code 1 --python
   task.py`), whose task first calls `new_master(r"<project>/blender/MASTER.blend")`: an empty scene (no default
   cube), the organising collections, saved at once. Split: `new_file(<path>)` per KIT, ASM or MASTER file.
3. For each piece: `new_piece("<FAMILY>_<Type>_<Size>_<Variant>")` (single: it lands in `KIT/KIT_<FAMILY>`), model it
   at the origin with the pivot rules below, and set its `kit_status` (`grey` for a new greybox piece).
4. Audit at the project's module (Checking a kit, below) and fix every problem it lists.
5. Build each assembly, then the layout. Single: `new_piece("ASM_<Name>_<Variant>")` and
   `place_piece(piece, ..., into=<that assembly>)`, then `place_piece(...)` into MASTER. Split: each assembly in its
   own ASM file, then MASTER, with `link_piece` (relative paths).
6. Whenever the file may also be edited by the user, follow "Editing alongside the user" below on every change.
7. End every headless run with `save_file()`: it saves without a `.blend1` backup. Split: after a KIT or ASM file
   changes, `reload_libraries()` in any live session that links it.

## The three layers

| Layer | Single MASTER (default) | Split files | Holds | Never holds |
|---|---|---|---|---|
| KIT | Collection `KIT`, one child `KIT_<FAMILY>` per family (`KIT_EXT`), one collection per piece inside it; **excluded from the view layer** | `blender/kits/KIT_<FamilyName>.blend` per visual family | One collection per piece, piece at the origin, its LODs and collision, the family's shared materials | Placement of anything in the world |
| ASM | Collection `ASM`, one child `ASM_<Name>_<Variant>` per assembly; **excluded from the view layer** | `blender/asm/ASM_<Name>_<Variant>.blend`, one assembly per file, named after it | The assembly (a facade, a stall, a furnished room) made of instances of KIT pieces, plus empties for sockets | Original geometry. If an assembly needs a new shape, it becomes a KIT piece first |
| MASTER | Collection `MASTER` (optionally `MASTER_<Zone>` children) | `blender/MASTER.blend` | Layout only: instances of KIT pieces and assemblies placed in the world, zone empties | Geometry, materials, copies of pieces |

Scale figures and other review aids go in `REF` (or `REF_<Name>`) in either layout; nothing in it is exported. In a
single MASTER the pieces all sit at the origin, which is why `KIT` and `ASM` are excluded: their instances still draw
in the layout. To look at or edit a piece by hand, tick `KIT` (or just its family) back on, use local view, and
exclude it again afterwards; scripts in other skills that need the pieces in the view layer (UV, RizomUV, renders)
run on a work file instead (Work files, below).

Edit in the lowest layer that owns the thing: geometry in KIT, arrangement in ASM, placement in MASTER. One assembly
per collection (and, split, per file) keeps each assembly's collection and engine prefab one-to-one (placement sync
pairs them that way).

## Editing alongside the user

The user may change MASTER (or any .blend) between your edits, and their work must survive yours. On every change to
a file the user can also edit (calls and edge cases: `references/master-sync.md`):

1. **Find where it is open.** The Blender MCP has it open: edit **live through the MCP**, never headless. Open in a
   Blender without the MCP (`Get-Process blender | Select-Object MainWindowTitle`): ask the user to connect the MCP or
   close it. Open nowhere: headless is fine.
2. **Read their changes first:** `changes_since(r"//MASTER.snapshot.json")` (or headless `--changes`) lists what
   changed since your last save. No snapshot yet: save one as the baseline first. Unsaved live work is theirs too.
3. **Plan around them.** Never revert, rename, move or delete what the user changed; if your task must change the same
   thing, stop and ask.
4. **Change it** directly through the MCP for short edits (placing, renaming, `kit_status`, a material value), or
   through a work file for long or tool-heavy work (modelling, UVs, texturing, renders, export): below.
5. **Save, then snapshot.** `changes_since` once more first: anything you did not do is the user working meanwhile;
   report it, and ask before saving unsaved user work. Save (live `bpy.ops.wm.save_mainfile()`, headless
   `save_file()`), then at once `save_snapshot(r"//MASTER.snapshot.json")`.

## Work files (single MASTER)

`checkout(r"//work/KIT_<label>.blend", [names])` copies piece or assembly collections out to a work file where they
sit in its scene and view layer, so it reads like a KIT file and every skill's scripts work on it unchanged.
Work on it headless (several work files at once if needed), then in MASTER `integrate(work, [names])`
replaces each collection in place, so every instance shows the new version (`materials="work"` after texturing;
by default MASTER's materials win). Command line, assemblies, export and clean-up: `references/master-sync.md`.

Changing an existing project's layout (split to single, or back) is the user's decision: ask, record it, and follow
`references/master-sync.md`, "Changing layout".

## Instance, never copy

Place pieces and assemblies as **collection instances** (`place_piece`; split files: linked, `link_piece`), never as
copies: a duplicated mesh (Shift+D, Make Instances Real, an appended piece) drifts from the kit at the first edit and
the engine can no longer instance it. Split files also need relative links, reloads and relinking:
`references/split-files.md`.

## Families

Split kits by **visual family / material set**, so each family lands on 1-3 materials and one atlas or trim sheet.

| Code | Single MASTER collection | Typical split file | Contents |
|---|---|---|---|
| `EXT` | `KIT/KIT_EXT` | `KIT_Arch_Exterior.blend` | Facade walls, windows, doors, cornices |
| `INT` | `KIT/KIT_INT` | `KIT_Arch_Interior.blend` | Interior walls, skirting, ceilings, interior doors |
| `STR` | `KIT/KIT_STR` | `KIT_Structure.blend` | Floors, stairs, roofs, columns, beams |
| `TRIM` | `KIT/KIT_TRIM` | `KIT_Trim.blend` | Strips and edge pieces that read off a trim sheet |
| `PROP` | `KIT/KIT_PROP` | `KIT_Props_<Theme>.blend` | Furniture and clutter (split: one file per theme) |
| `FOL` | `KIT/KIT_FOL` | `KIT_Foliage.blend` | Plants, trees, grass cards |
| `ZONE` | `KIT/KIT_ZONE` | `KIT_Zone_<Zone>.blend` | Unique non-repeating shells for one zone (terrain, a hero building shell) |

Codes are 2-5 capitals. A project can add its own, recorded with their collection (or file) and material set.
`ZONE` pieces are unique but are still authored as pieces and placed in MASTER like the others, so everything in the
layout is a collection instance and nothing needs a different export or sync path.

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
Renaming a piece or an assembly is a breaking change. Single MASTER: rename the collection in place (every
instance follows it, so placement ids survive), then rename its exported file and engine asset to match; moving a
piece to another family is moving its collection to that family's `KIT_<FAMILY>` (and renaming it, since the family is
in the name). Split files: `references/split-files.md`, "Renaming".

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

A .blend has one writer at a time: two writers to the same file silently lose one side's work. A single MASTER holds
everything, so every task that changes the kit, an assembly or the layout writes MASTER and they take turns; work
that should run in parallel goes to work files (one writer each), integrated one at a time. MASTER's owner is normally
the user's live Blender, which agents drive through the MCP.

Headless work runs one process per file (`blender -b --factory-startup --python-exit-code 1
blender/work/KIT_EXT.blend --python task.py`) and ends with `save_file()`: with factory settings `save_version` is 1,
so a plain `bpy.ops.wm.save_mainfile()` also writes a `.blend1` backup the task was not briefed to write
(https://docs.blender.org/api/current/bpy.types.PreferencesFilePaths.html, checked 2026-10-17).

## The script

Load in Blender: `ns = {}; exec(open(r"<skill>/scripts/kit_library.py", encoding="utf-8").read(), ns)`, then call
`ns["new_piece"](...)` and so on. Paths starting with `//` are relative to the open .blend. Main calls: `new_master`,
`new_piece`, `place_piece`, `changes_since`, `save_snapshot`, `checkout`, `integrate`, `audit_kit` and `problems`,
`save_file`; every call, where it runs and what it does, and the API sources: `references/script-api.md`.

## Checking a kit

Run the audit in each KIT file (single: in MASTER, or in a work file) at the world's grid module. It changes
nothing.

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
| Stray meshes | Mesh objects outside any piece collection (`REF` aside) |
| Layout | Single MASTER: every piece inside `KIT`, every assembly inside `ASM`, both excluded from the view layer, a `MASTER` collection |
| Libraries | Linked libraries whose file is missing, and linked data missing from a file that exists (renamed in it) |
| `kit_status` | A collection custom property: `grey`, `modelled`, `uv`, `textured`, `exported`. UV2 is required from `uv` on, filled material slots from `textured` on; a piece without `kit_status` gets every check |

## Getting the kit into an engine

Export one file per piece collection (FBX or glTF), named after the collection, at identity transform. For Unity
(export settings, per-piece folders, prefabs, shared family materials): `blender-to-unity`. To keep a MASTER layout
and a Unity scene in step both ways: `blender-unity-placement-sync`.
