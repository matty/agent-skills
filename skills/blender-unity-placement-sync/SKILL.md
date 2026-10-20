---
name: blender-unity-placement-sync
description: A Blender layout and a Unity scene disagree - pieces moved, added or deleted in Unity that Blender must get (or the reverse), a layout to rebuild in Unity as prefab instances, placements lost after a re-export, CONFLICT, BLOCKED or REFUSED in a sync report. Stable placement ids, JSON dumps, a three-way merge with safety refusals, MASTER and ASM scopes. For .blend structure see blender-kit-library, for FBX export and prefabs blender-to-unity.
---

# Blender <-> Unity placement sync

Sync **placements only** (which piece or assembly goes where) between a Blender file and a Unity scene or prefab, both
ways, through stable ids and a three-way merge against the last synced snapshot. Never move a layout by re-exporting
it as one merged FBX: that throws away whatever was done in Unity. Nothing is overwritten silently: conflicts wait
for a decision, and mass deletions or a dump of the wrong file are refused.

## Requirements

Set up with `blender-kit-library` and `blender-to-unity`; this skill only needs them to hold.

| Side | Requirement |
|---|---|
| Blender | Each piece or assembly is a collection, placed as collection instances (linked or local). The collection name is the asset name. `instance_offset` is (0, 0, 0) on every placed collection, and placements carry no constraints (the dump warns about both). 1 Blender unit = 1 m |
| Blender, assemblies | Each assembly is one collection `ASM_<Name>_<Variant>`: under `ASM` in a single `blender/MASTER.blend` (the default layout), or, with split files, alone in `blender/asm/ASM_<Name>_<Variant>.blend` |
| Unity | Each asset is a prefab with the **same file name** under `Assets/World/Kits/` or `Assets/World/Assemblies/` (other roots: `references/unity-apply.md`), its root at identity rotation and scale. An assembly's prefab is `Assets/World/Assemblies/ASM_<Name>_<Variant>.prefab` |
| Export | FBX exported with -Z Forward, Y Up, Apply Scalings FBX All, Use Space Transform on, Bake Space Transform ("Apply Transform") on, Path Mode Strip for kit pieces, so a piece arrives in Unity at scale 1 and rotation 0. Options of `bpy.ops.export_scene.fbx` (https://docs.blender.org/api/current/bpy.ops.export_scene.html, checked 2026-10-17; Apply Transform is marked experimental there, for armatures and animation, not static pieces) |

## Files

| Script | Host | Does |
|---|---|---|
| `scripts/export_placements.py` | Blender (bpy), headless or live | `dump` placements, `apply` a plan; `--collection` names the collection a scope covers |
| `scripts/placement_merge.py` | Plain Python 3.9+, stdlib | `merge` (a dry run: plans and report), `commit` (verify both sides and write the snapshot) |
| `scripts/unity/PlacementId.cs` | Unity, runtime folder | The id component (`IEditorOnly` in VRChat projects, so SDK validation ignores it: https://creators.vrchat.com/sdk/build-pipeline-callbacks-and-interfaces, checked 2026-10-17) |
| `scripts/unity/Editor/PlacementSync.cs` | Unity editor | `Check`, `Dump`, `Apply`, menu `Tools > Placement Sync` |

## Scopes

A scope is one Blender collection (or split file) paired with one Unity target, synced on its own with its own
snapshot.

| Scope | Blender, single MASTER (default) | Blender, split files | Unity target |
|---|---|---|---|
| `MASTER` | `blender/MASTER.blend`, the `MASTER` collection (world origin = root) | `blender/MASTER.blend`, the whole scene | `scene:MASTER`, a root GameObject called MASTER (`scene:<scene path>#MASTER` when two open scenes have one) |
| `ASM_ShopFront_A` | `blender/MASTER.blend`, the collection `ASM_ShopFront_A` under `ASM` | `blender/asm/ASM_ShopFront_A.blend`, its collection `ASM_ShopFront_A` | `prefab:Assets/World/Assemblies/ASM_ShopFront_A.prefab`, created by the scope's first Apply |

Sync every ASM scope before MASTER, so assembly prefabs exist when MASTER places them. The Blender side of a scope is
the collection named like the scope when the file has one, else (split MASTER only) the whole scene; `--collection
NAME` names another. A single MASTER (`kit_layout = "single"`) refuses a scope it has no collection for, and lists its
own pieces and assemblies as assets, so it needs no `--libraries`.

Everything under a scope root syncs. Unity-only copies that must never reach Blender (the duplicated static geometry of
a switchable-light setup, one copy per lighting state, or any other Unity-only duplicate) live under a separate root
outside the scope root, for example a root GameObject `LIGHT_STATES` beside `MASTER`. Copies left inside the scope get
fresh ids and are created in the .blend; the merge report flags several placements of one asset at one pose.

## Before the first sync

1. Back up the .blend files or keep them under version control: headless applies save them.
2. Install the Unity pair (`references/unity-apply.md`, Install).
3. Create the Unity scope root for MASTER: an empty root GameObject called `MASTER` at identity (position 0,
   rotation 0, scale 1) in the world scene. With no world scene yet, the agent creates one and saves it under
   `Assets/World/Scenes/` (a scene the agent created itself, at a path it chose, is its own to save); in a scene the
   user already works in, add the root and let the user save. Snippet: `references/unity-apply.md`, Scope roots.
   ASM scopes need nothing: their first Apply creates the prefab.
4. Run the round-trip test once per project, and again after changing export settings: `references/round-trip-test.md`.

## The sync loop

Run it in one go, with nobody editing either side: Unity keys in a dump are only valid until the hierarchy changes.
One writer per .blend: the Blender file must not be open in a live Blender session while a headless apply writes it
(a live session's next save would overwrite the sync). If it is open there, run the Blender steps in that session
through Blender MCP instead (`dump` and `apply` from the script's header) and save. The sync itself keeps the user's
moves (they are what it merges), but a MASTER the user also edits gets `blender-kit-library`'s routine around it:
`changes_since` before the dump, and `save_snapshot` after the apply's save.

Placeholders: `<skill>` this skill's folder, `<project>` the project root, `<p>` the absolute placements folder,
`B` = `blender -b --factory-startup --python-exit-code 1`. MASTER shown, for split files; in a single MASTER drop
`--libraries`. An ASM scope differs only in `--scope ASM_ShopFront_A`, its `prefab:` target and, with split files, the
file (`<project>/blender/asm/ASM_ShopFront_A.blend`) and `--libraries "../kits/*.blend"`.

```
1. check   Unity MCP execute_code: return PlacementSync.PlacementSyncTool.Check("scene:MASTER");
           -> must start "[placements] ready"; otherwise tell the user what it says and stop.
2. dump    B <project>/blender/MASTER.blend --python <skill>/scripts/export_placements.py --
               dump --dir <p> --scope MASTER --libraries "kits/*.blend" "asm/*.blend"
           execute_code: return PlacementSync.PlacementSyncTool.Dump("scene:MASTER", "<p>/MASTER.unity.json", "MASTER");
3. merge   python <skill>/scripts/placement_merge.py merge --dir <p> --scope MASTER
           -> read <p>/MASTER.report.txt and act on the exit code (table below). Nothing has changed anywhere yet.
4. apply   Unity first: execute_code: return PlacementSync.PlacementSyncTool.Apply("scene:MASTER", "<p>/MASTER.plan.unity.json");
           -> "[placements] REFUSED" means nothing changed anywhere: fix it with the user, restart at step 1.
5. apply   Blender: B <project>/blender/MASTER.blend --python <skill>/scripts/export_placements.py --
               apply --dir <p> --scope MASTER --libraries "kits/*.blend" "asm/*.blend"
6. dump    both sides again (step 2).
7. commit  python <skill>/scripts/placement_merge.py commit --dir <p> --scope MASTER
           -> refuses, leaving the snapshot alone, unless both sides now match the plan.
```

`--libraries` globs are relative to the .blend file's folder unless absolute; they tell the merge which collections
Blender can take, so pass them on every dump. `apply --no-save` tries a plan without writing the file (a headless run
then discards the result).

## When a step does not end cleanly

| You see | Do |
|---|---|
| Blender dump exits 1, or Unity Dump throws | Stop, and never merge after a failed dump. Both scripts delete their old dump before writing, but a wrong .blend path makes Blender exit before the script runs, leaving the previous file. Fix the cause (the .blend path, `--collection`, Play mode, the scope root) and dump again |
| merge exit 2, `CONFLICT` lines | Show them to the user. Re-run merge with `--take-id ID=blender` or `--take-id ID=unity` per conflict (`--take blender` or `--take unity` for all). The rest of the plan is ready either way |
| merge exit 3, only `BLOCKED` lines | The receiving side has no such asset yet; each line says which case (table in `references/merge-rules.md`). A new piece, or a placement swapped to a piece the other side lacks: export and package it (`blender-to-unity`), or add it as a KIT piece; never rename the old asset, other placements still use it. An assembly: sync its ASM scope first. A rename made on one side only (the old asset is gone from that side): finish (or undo) the rename on the other side (`blender-kit-library` has the rename procedure; an assembly: `references/merge-rules.md`, Renaming an assembly). You may apply and commit now: blocked items stay pending and the next merge retries them |
| merge exit 4, `REFUSED` | Too many deletions, an empty side, or a dump from another file, collection or Unity target than this scope's. Check the dumps (right file and scene, prefab roots). Only if the user confirms the deletions are real: `--allow-deletes`; a scope that really moved: `--accept-source` |
| merge exit 1 | Bad input (a missing or swapped dump, a malformed `--take-id`): fix it and re-run |
| Unity Apply returns `REFUSED` | Nothing changed. Tell the user why (Play mode, an unsaved or never-saved scene, Prefab Mode open, an ambiguous root) and restart at step 1 once they fixed it. Never save the user's scene for them; `save: false` and `force: true` are in `references/unity-apply.md` |
| Unity Apply lists `ERRORS` | `references/unity-apply.md` has each one. A stale key or changed object: restart at step 1. A swap that would discard Unity-side changes: ask the user, then take one of three ways out (otherwise every loop plans the same swap again): **force**, re-run Apply on the same plan with `force: true`, then step 5; **swap by hand** in Unity, keeping the `PlacementId` component on the new instance, then step 5; **keep the old piece**, re-point that Blender instance back to the old collection (`blender-kit-library`), then restart at step 2 |
| Blender apply exits 1 | It printed `ERROR` lines (a missing collection, an object changed since the dump) and still saved what did apply. Fix the cause and restart at step 1 |
| commit exit 2 | The sides do not match the plan: restart at step 2. Never edit the snapshot by hand |

## Merge rules

Full table, id handling, exit codes and file formats: `references/merge-rules.md`. In short:

- One side changed and the other did not: the change goes across. Both changed the same way: nothing to do. Both
  changed differently, or deleted on one side and changed on the other: a conflict, left alone until decided.
- Deleted on one side, unchanged on the other: deleted there too.
- New in Blender: created in Unity, or BLOCKED until its prefab exists. New in Unity: created in Blender when Blender
  has the collection, else kept unity-only until it does.
- "Changed" covers position, rotation, scale and the asset itself (a piece swapped for another). Positions within
  1 mm, rotations within 0.01 deg and scale within 0.01% count as unchanged.
- **Names and folders sync both ways**, each merged on its own, so a rename on one side and a move on the other is
  no conflict. The name is the Blender empty's or Unity instance's name without `.001` or ` (1)`; the folder is the
  collection path under the scope collection, or in Unity the parent GameObjects under the scope root. Apply creates
  missing folders and never deletes one. A Unity piece parented under another piece keeps its parent as its folder.
  `/` in a name becomes `-`.

## What keeps placements stable

- **Ids sit on the object, not in its name**: custom property `placement_id` on the Blender empty, a `PlacementId`
  component on the Unity instance root. Renaming, moving into folders or collections, and parenting a piece under
  another piece never lose a placement. Unity transforms are compared relative to the scope root, not the parent.
  When a sync deletes or moves a placement that others are parented under, both appliers keep those children's world
  pose (a deleted parent's children move to its parent); updates go parents first.
- **Duplicates** copy the id: the merge keeps it on the copy closest to the snapshot and gives the others fresh ids,
  which then sync as new placements. An object that lost its id takes it back when it still matches its placement.
- **Only the kit counts**: collection instances (Blender) and outermost instances of prefabs under the prefab roots
  (Unity) are placements. Lights, Udon objects and folder empties are ignored. Pieces inside an assembly instance
  belong to the assembly's own scope: edit the assembly prefab, not the instance in the MASTER scene.
- **These break identity, so avoid them**: in Blender, a library override of a placed instance (it replaces the
  instance: the dump skips overrides and warns; make a variant piece instead); in Unity, Overrides > Apply All or
  Revert All on a placement, Unpack Prefab, or moving a kit prefab out of the prefab roots
  (`references/unity-apply.md`).
- **Snapshot safety**: merge changes nothing. commit writes `<scope>.synced.json` only after fresh dumps of both
  sides match the plan, keeps the previous one as `<scope>.synced.prev.json`, and writes through a temp file.

## Coordinates

JSON is in Unity space (left-handed, Y up, metres). Blender to Unity is `(-x, z, -y)`, matching the export settings
above: a piece placed in Blender at `(2, 3, 0)`, rotated +90 deg about Z, appears in Unity at `(-2, 0, -3)`, rotated
-90 deg about Y. Scale maps the same way: Blender `(sx, sy, sz)` is Unity `(sx, sz, sy)`. The conversion assumes the
prefab root has identity rotation. If pieces arrive mirrored or turned, check the FBX axis settings before touching
the matrix in `scripts/export_placements.py`.
