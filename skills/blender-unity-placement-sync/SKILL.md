---
name: blender-unity-placement-sync
description: Keep a modular layout in step between Blender and Unity - every placed kit piece or assembly gets a stable id, both sides dump their placements to JSON, and a three-way merge against the last synced snapshot pushes Blender moves to Unity and Unity moves back to the MASTER or ASM .blend without losing either, with conflicts, duplicates, deletions and Unity-only additions reported instead of overwritten. Use when a Blender layout must be rebuilt in Unity as prefab instances, when someone moved, rotated, added, deleted or re-organised pieces in Unity and Blender must catch up (or the reverse), when placements were lost or reset after a re-export, or when setting up a repeatable layout round trip; for kit file structure see blender-kit-library, for Unity packaging see blender-to-unity.
---

# Blender <-> Unity placement sync

The layout (which piece goes where) lives on both sides: Blender's MASTER and ASM files place linked collection
instances, Unity places prefab instances. Exporting geometry does not move placements, and re-exporting a layout as a
merged FBX throws away whatever was done in Unity. This skill syncs **placements only**, both ways, and never
silently overwrites a change.

What it relies on (`blender-kit-library` and `blender-to-unity` cover how to set these up; this skill only needs
them to hold):

| Side | Requirement |
|---|---|
| Blender | Each piece or assembly is a collection, placed as collection instances (linked or local). The collection name is the asset name |
| Unity | Each asset is a prefab with the **same file name** under `Assets/World/Kits/` or `Assets/World/Assemblies/` (other roots via config), its root at identity rotation and scale |
| Export | FBX exported with -Z forward, Y up, Apply Scalings FBX All, Use Space Transform on, Bake Space Transform ("Apply Transform") on, so a piece arrives in Unity at scale 1 and rotation 0 |

## Files

| Script | Host | Does |
|---|---|---|
| `scripts/export_placements.py` | Blender (bpy), headless or live | `dump` placements, `apply` a plan |
| `scripts/placement_merge.py` | Plain Python, stdlib | `merge` (dry run: plans and report), `commit` (verify and write the snapshot) |
| `scripts/unity/PlacementId.cs` | Unity, runtime folder | The id component (`IEditorOnly` in VRChat projects, stripped from builds) |
| `scripts/unity/Editor/PlacementSync.cs` | Unity editor | `Dump`, `Apply`, menu `Tools > Placement Sync` |

Install the Unity pair once with Unity MCP: `create_script` both files to `Assets/World/PlacementSync/PlacementId.cs`
and `Assets/World/PlacementSync/Editor/PlacementSync.cs`, then `refresh_unity` and `read_console` for compile errors.

## Scopes

A **scope** is one Blender file paired with one Unity target, synced independently with its own snapshot:

| Scope | Blender | Unity target |
|---|---|---|
| `MASTER` | `blender/MASTER.blend` (world origin = root) | `scene:MASTER`: a root GameObject called MASTER in the world scene |
| `ASM_ShopFront_A` | `blender/asm/ASM_ShopFront_A.blend` | `prefab:Assets/World/Assemblies/ASM_ShopFront_A.prefab` |

Sync ASM scopes before MASTER, so assembly prefabs exist when MASTER places them.

## The sync loop

Run all of it in one go: Unity keys in a dump are only valid until the hierarchy changes.

```
1. dump    blender -b MASTER.blend --python export_placements.py -- dump --dir placements --scope MASTER
                    --libraries "kits/*.blend" "asm/*.blend"
           Unity MCP execute_code:
           return PlacementSync.PlacementSyncTool.Dump("scene:MASTER", "<abs>/placements/MASTER.unity.json", "MASTER");
2. merge   python placement_merge.py merge --dir placements --scope MASTER
           -> read the report. Exit 2 = conflicts or blocked items: show them to the user, decide, re-run with
              --take-id ID=blender|unity (or --take for all). Nothing has changed anywhere yet.
3. apply   blender -b MASTER.blend --python export_placements.py -- apply --dir placements --scope MASTER --libraries ...
           execute_code: return PlacementSync.PlacementSyncTool.Apply("scene:MASTER", "<abs>/placements/MASTER.plan.unity.json");
4. dump    both sides again (step 1)
5. commit  python placement_merge.py commit --dir placements --scope MASTER
           -> refuses, and leaves the snapshot alone, unless both sides now match the plan.
```

Blender must not have MASTER open and unsaved in a live session while the headless apply writes it (one writer per
file). If MASTER is open in the live Blender, run `dump`/`apply` there through Blender MCP instead and save.

## Merge rules

Against the snapshot (`<scope>.synced.json`); positions within 1 mm, rotations within 0.01 deg and scale within 0.01%
count as unchanged, so float noise from the round trip never shows up as an edit.

| Blender | Unity | Result |
|---|---|---|
| changed | same | Unity updated |
| same | changed | Blender updated |
| changed | changed (to the same) | nothing to do |
| changed | changed (differently) | **conflict**, both left alone |
| deleted | same | deleted in Unity |
| same | deleted | deleted in Blender |
| deleted | changed (or the reverse) | **conflict** |
| new | - | created in Unity (or **blocked** until its prefab exists) |
| - | new prefab instance | created in Blender, if Blender has that collection; otherwise kept as **unity-only** and left to Unity |

"Changed" covers position, rotation, scale and the asset itself (a prefab or collection swapped for another piece).
An unresolved conflict keeps its previous snapshot entry, so it is reported again on the next merge until decided.

## Why it is stable

- **Ids sit on the object, not in its name**: custom property `placement_id` on the Blender empty, a `PlacementId`
  component on the Unity prefab instance root. Renaming, re-parenting, moving into folders or collections, and
  re-organising the hierarchy never lose a placement. Unity transforms are compared relative to the scope root, not
  the parent, so grouping pieces under new empties is not an edit.
- **Duplicates**: duplicating an object copies its id. The merge keeps the id on the copy closest to the snapshot
  (the original) and issues a fresh id for the rest, which then sync as new placements.
- **Nothing outside the kit counts**: only collection instances (Blender) and outermost instances of prefabs under
  `Assets/World/Kits` and `Assets/World/Assemblies` (Unity) are placements. Lights, Udon objects and folder empties
  under the root are ignored.
- **Snapshot safety**: `merge` changes nothing. `commit` writes `<scope>.synced.json` only after fresh dumps of both
  sides match the plan, keeps the previous one as `<scope>.synced.prev.json`, and writes through a temp file.
- **Undo**: Unity edits in a scene go through `Undo`, so `Ctrl+Z` reverses an apply. Blender headless applies save
  the file. Keep MASTER under version control or back it up before the first sync.

## Coordinates

JSON is in Unity space (left-handed, Y up, metres). Blender to Unity is `(-x, z, -y)`, matching the export
settings above: a piece placed in Blender at
`(2, 3, 0)`, rotated +90 deg about Z, appears in Unity at `(-2, 0, -3)`, rotated -90 deg about Y. The conversion
assumes the prefab root has identity rotation. If pieces arrive mirrored or turned, check the FBX axis settings
before touching the matrix in `export_placements.py`.

## Round-trip test (run once per project, and after changing export settings)

1. Two KIT pieces, one asymmetric (an L-shaped wall), exported and packaged as prefabs.
2. In MASTER: place three instances, one rotated 90 deg, sync: Unity must show them where Blender does (compare a
   `look` render with a Unity screenshot from the same viewpoint).
3. Move one in Unity, a different one in Blender, sync: both sides end up with both moves.
4. Move the same one differently on both sides: merge exits 2 with one conflict; resolve it with `--take-id`.
5. Duplicate one in Unity and move the copy: the copy becomes a new placement in Blender; the original keeps its id.
6. Delete one in Blender: it disappears in Unity. Commit after each step must succeed.

Last full pass: 2026-10-14, Blender 5.2.2 and Unity 2022.3.22f1 (a VRChat world project), including a re-parent
into a folder in Unity (not an edit) and a duplicate made with Ctrl+D after a script reload.
