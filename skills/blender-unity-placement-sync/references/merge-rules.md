# Merge rules, exit codes and file formats

What `scripts/placement_merge.py` decides, so every report line can be traced to a rule. Positions within 1 mm,
rotations within 0.01 deg and scale within 0.01% count as unchanged (`POS_TOL`, `ROT_TOL`, `SCL_TOL` in the script),
so float noise from the round trip never shows up as an edit.

## The three-way table

Each placement id is compared on each side against the snapshot (`<scope>.synced.json`).

| Blender | Unity | Result |
|---|---|---|
| same | same | Nothing to do |
| changed | same | Unity updated |
| same | changed | Blender updated |
| changed | changed, to the same | Nothing to do; the snapshot takes the new state |
| changed | changed, differently | **Conflict**: both left alone, the snapshot entry kept, reported on every merge until decided |
| deleted | same | Deleted in Unity |
| same | deleted | Deleted in Blender |
| deleted | deleted | Dropped from the snapshot |
| deleted | changed (or the reverse) | **Conflict** |
| new | - | Created in Unity, or **BLOCKED** until Unity has a prefab of that name |
| - | new | Created in Blender when Blender has the collection; otherwise kept as **unity-only** in the snapshot, and created in Blender by a later merge once it has the collection |
| new | new, same id | Nothing to do if they match, otherwise a **conflict** |

The table runs for each field on its own: the pose (position, rotation, scale and asset), the name (`label`) and the
folder (`group`). A rename in Unity and a move in Blender both go across with no conflict. The report says which
field clashed (`CONFLICT id: label: blender 'North wall', unity 'Shop wall'`), and `--take-id` picks the winner
for the clashing fields only.

| Field | Blender | Unity | Compared as |
|---|---|---|---|
| `label` | The empty's name | The instance root's name | Without the duplicate suffix (`.001`, ` (1)`), `/` read as `-`, ends trimmed. Apply renames only when that differs, so a ` (1)` the user left stays |
| `group` | The collections from the scope collection down to the empty's (`Street/Shops`; `""` directly in it) | The GameObjects between the scope root and the instance | Each part cleaned like a name. Apply links the empty into that collection and out of the others under the scope (a REF collection outside it keeps it), or reparents the instance, creating missing folders (Unity: identity transform). Neither side deletes an emptied folder |

- A Unity placement parented under another placement is dumped `"nested": true`: its folder is its parent, so its
  `group` is not compared and apply never moves it. Its name still syncs.
- A snapshot from before names synced counts as `label` = the asset name and `group` = `""`, so the first sync
  after the upgrade keeps whichever side renamed or organised; both did, differently, is a conflict.
- A dump without the fields (an older copy of either applier) leaves names and folders alone on that side.
- An asset swap keeps the instance's name and place on both sides.
- A Blender empty in two collections under the scope syncs as being in the first by path; the dump warns.

"Changed" covers position, rotation, scale and the asset (a piece swapped for another). A change pushed to a side that
has no such asset (no prefab of that name in Unity, no collection of that name in Blender, for example a prefab renamed
in Unity) is **BLOCKED** instead: the item keeps its snapshot entry and the next merge tries again. The report line
names the case:

| BLOCKED line says | Cause | Do |
|---|---|---|
| `no Unity prefab called X yet: a new piece, so export and package it` | A piece new to Unity | Export and package it (`blender-to-unity`) |
| `no Unity prefab called ASM_... yet: sync that assembly's own ASM scope first` | An assembly placed in MASTER before its scope synced | Sync the ASM scope, then MASTER |
| `no Unity prefab called X: a placement was swapped from Y to a piece Unity lacks, so export and package X; never rename Y` | Some placements swapped in Blender to a new piece; Blender still has Y | Export and package X. Renaming Y would turn every other Y placement into X |
| `Unity has no prefab called X (it has Y, which Blender no longer has): finish (or undo) the rename on the Unity side` | A piece renamed in Blender only (Y is gone from Blender) | Rename the prefab and its FBX in Unity (or rename the collection back) |
| `no Unity prefab called ASM_X: a placement was swapped from Y to an assembly whose scope has not synced, so sync ASM_X's own scope first; never rename Y` | A placement swapped in Blender to an assembly variant made before its scope synced | Sync the ASM_X scope (its first Apply creates the prefab), then MASTER again |
| `no Blender collection called X: a placement was swapped in Unity from Y to a prefab Blender lacks ...` | Some instances swapped in Unity to a Unity-only prefab; Unity still has Y | Add X as a KIT piece (`blender-kit-library`), or undo the swap in Unity; never rename Y |
| `no Blender collection called ASM_X: a placement was swapped in Unity from Y to an assembly Blender lacks, so build it (under ASM in MASTER, or in blender/asm/ASM_X.blend with split files) and sync its scope, or undo the swap` | An instance swapped in Unity to an assembly prefab Blender has no collection for | Build the assembly (single MASTER: under `ASM`; split: its own ASM file) and sync its scope, or undo the swap in Unity |
| `Blender has no collection called X (it has Y, which Unity no longer has): finish (or undo) the rename on the Blender side` | A prefab renamed in Unity only (Y is gone from Unity) | Rename the collection (single MASTER: in place, its instances follow; split: in its KIT or ASM file, then re-point its instances; `blender-kit-library`), or undo it in Unity |
| `no Blender collection called X: add it as a piece under KIT in MASTER ...` | A piece Blender has never had | Add the collection (single MASTER: under `KIT`; split: to a KIT file, and dump with `--libraries` naming it) |

A swap is told from a rename by the old asset Y: still on the sending side (other placements, its prefab or its
collection) means a swap; gone means a rename. Only new names the receiving side lacks count: when Y is gone and its
placements went to more than one of those, the line lists each with its placement count and suggests no rename (rename
Y to one of them with the user, and add the others as new pieces). A new placement of a renamed piece gets the same
rename line as the renamed placements, so the one prefab gets one instruction. An assembly is never exported or added
as a KIT piece: it has its own collection (split: its own ASM file) and scope.

## Renaming an assembly

An assembly's name is its collection (split: and its ASM file), its prefab and its sync scope at once.

1. Blender: single MASTER, rename its collection (every instance follows); split, rename the ASM file and its
   collection together, and re-point its instances in every file that places it (`blender-kit-library`, Naming).
2. Unity: rename the prefab in place (`Assets/World/Assemblies/ASM_<New>.prefab`: an assembly prefab has no FBX). Its
   GUID stays, so the scenes that place it follow.
3. In the placements folder, rename the old scope's files (`ASM_<Old>.*`) to the new scope name, then sync the new
   scope once with `--accept-source`: the snapshot recorded the old file, collection and target. Its ids survive.
4. Sync MASTER: its instances of the assembly changed to the new name on both sides, so there is nothing to do.

## Ids

| Situation | What the merge does |
|---|---|
| An id on more than one object (a duplicate) | Keeps it on the copy closest to its snapshot pose; the others get fresh ids (assigned on that side, created on the other) |
| An object without an id that matches a placement missing on its own side (same asset, same pose as that placement's snapshot entry, or as a placement that is new on the other side) | Takes that id back (an assign) instead of becoming a twin. Covers an id lost to Overrides > Revert All, and a loop interrupted between the two applies |
| Objects without ids on both sides that match each other | One new id for both, so a first sync into a hand-built layout doubles nothing |
| Any other object without an id | A fresh id, assigned on its side and created on the other |

Assign entries carry what the merge saw (`was`: the object's id at the dump, `asset`). Both appliers skip an assign
whose object no longer matches and report it, so a stale key never stamps an id on the wrong object.

## Safety refusals (exit 4)

The merge writes empty plans and marks `pending.json` refused (commit then refuses too) when:

| Check | Override, only after the user confirms |
|---|---|
| One side's dump has no placements while the snapshot has some | `--allow-deletes` |
| The plans delete more than max(3, 20% of the snapshot) placements | `--allow-deletes` |
| The Blender file name, the Blender collection or the Unity target differs from the one recorded at the last commit | `--accept-source` |

Usual causes: prefab roots moved, renamed or mistyped (PlacementSync.json, a stale `PrefabRootsOverride`), a prefab
moved out of the roots, deleted or unpacked, or the wrong .blend file or scene dumped.

## Exit codes

| Command | Code | Meaning |
|---|---|---|
| merge | 0 | Plans ready |
| merge | 2 | Unresolved conflicts. Decide with `--take-id ID=blender` or `--take-id ID=unity` (`--take blender` or `--take unity` for all); the rest of the plan is ready either way |
| merge | 3 | Only BLOCKED items left: apply and commit anyway, they stay pending |
| merge | 4 | Refused for safety (above) |
| merge | 1 | Bad input: a missing or swapped dump, a malformed `--take-id` |
| commit | 0 | Snapshot written; the previous one is kept as `<scope>.synced.prev.json` |
| commit | 2 | Refused: the sides do not match the plan, an id sits on two objects, or the merge was refused |

`--take-id` sides are `blender` or `unity` in any case; an id that is not a conflict is reported and ignored.

## Files

All in `--dir`, named after the scope. merge rewrites the plans, `pending.json` and `report.txt` every run, so a
merge run after a commit as a check just writes empty plans.

| File | Written by | Holds |
|---|---|---|
| `<scope>.blender.json` | `export_placements.py dump` | `scope`, `side`, `file`, `collection`, `items`, `assets`, `warnings` |
| `<scope>.unity.json` | `PlacementSyncTool.Dump` | `scope`, `side`, `target`, `prefabRoots`, `note`, `items`, `assets` |
| `<scope>.plan.blender.json`, `<scope>.plan.unity.json` | merge | `assign` [{key, id, was, asset}], `delete` [id], `update` and `create` [items] |
| `<scope>.pending.json` | merge | The state both sides must reach, the skipped ids and their kept snapshot entries (or `refused`) |
| `<scope>.report.txt` | merge | The printed report, then the unresolved conflicts as JSON |
| `<scope>.synced.json` | commit | `items` and `source` (Blender file name and collection, Unity target) |

An item is `{"id", "asset", "pos": [x, y, z], "rot": [x, y, z, w], "scl": [x, y, z], "label", "group", "key"}` in
Unity space (left handed, Y up, metres) relative to the scope root. `label` and `group` are the name and folder
(table above; Unity adds `"nested": true` for a placement under another). `key` is the side's handle (the Blender
object name, the Unity sibling-index path such as `3/0/2`, valid only until the hierarchy changes), never a name;
Unity adds `name`, the hierarchy path, for reports. Report and plan files are the only place these paths appear: the
objects themselves keep plain names, and the id lives in `placement_id` / the `PlacementId` component.
