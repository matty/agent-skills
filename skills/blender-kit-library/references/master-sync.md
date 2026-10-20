# Editing a MASTER the user also edits

The procedure in `SKILL.md` ("Editing alongside the user"), with the calls. It applies to a single MASTER and equally
to any split KIT, ASM or MASTER file the user may open. The snapshot is the agent's record of the file as it last
saved it; the user never needs to make one.

## 1. Where is the file open?

Through the Blender MCP (`execute_blender_code`):

```python
import bpy
print(bpy.data.filepath, bpy.data.is_dirty, bpy.context.scene.get("kit_layout"))
```

| Result | Route |
|---|---|
| The MCP answers with the file's path | Live: every read and edit goes through the MCP; never run a headless Blender that saves this file |
| The MCP answers with another file, or is not connected | Look for a Blender window holding it: `Get-Process blender \| Select-Object MainWindowTitle` (the title names the open file). Found: ask the user to connect the MCP to that Blender, or to save and close the file. None: headless |
| `is_dirty` is true | The user has unsaved work in that session. It is theirs: never discard or revert it, and ask before your save writes it to disk |

Never open the file in a second Blender to edit it while another has it open: whichever saves last wins, silently.

## 2. What changed since your last write

Load the helpers once per live session, then compare:

```python
ns = {}; exec(open(r"<skill>/scripts/kit_library.py", encoding="utf-8").read(), ns)
diff = ns["changes_since"](r"//MASTER.snapshot.json")
print("no snapshot yet" if diff is None else "\n".join(ns["describe"](diff)) or "no changes")
```

Headless: `blender -b --factory-startup --python-exit-code 1 <project>/blender/MASTER.blend --python
<skill>/scripts/kit_library.py -- --changes <project>/blender/MASTER.snapshot.json` (exit 1 when something changed).

Reading the lines:

| Line | Means |
|---|---|
| `object X changed: matrix` | Moved, turned or scaled (placements are instance empties named after their piece) |
| `object X changed: mesh` | The mesh was edited (`co` shape, `topology`, `uv` layers, `attributes` or `materials` differ inside) |
| `object X changed: instance` | A placement was swapped to another piece |
| `object X added` / `removed` | Placed, modelled or deleted; a renamed object shows as one of each |
| `collection C changed: children` / `objects` / `parents` | Pieces added to or moved between collections |
| `collection C changed: props` | `kit_status` or another custom property |
| `material M changed: nodes` / `settings` | A material was edited |

No snapshot (`None`): the file has never been written by an agent, or the snapshot was lost. Save one now as the
baseline (`ns["save_snapshot"](r"//MASTER.snapshot.json")`) before any edit, and treat everything already in the file
as the user's.

Snapshots compare to 0.1 mm and 0.0001 of a UV unit, and leave out UI state (node positions, selection, edit-mode
selection layers, which collections are ticked in the view layer), so opening, looking and saving changes nothing in
them. A placement moved by script shows at once (snapshots read each object's own transform, not the evaluated one).

## 3. Plan around the user's changes

- Keep every change the user made. If the task is "place the shop fronts" and the user moved one, the new ones go
  where the spec says and theirs stays where they put it; mention it.
- When your task has to change something they changed (the same piece, placement or material), stop and ask: show the
  diff lines and what you were going to do. In `vrchat-world-orchestration`, that is a `flags.user_actions` entry.
- A change the user made that breaks a rule (a mesh left in `MASTER`, a piece moved out of `KIT`) is reported, not
  fixed silently.

## 4. Make the change

**Live, directly.** Small steps through `execute_blender_code`, each printing what it changed, and a `look` or
`get_scene_info` when placement matters. Use the helpers (`new_piece`, `place_piece`) so new data lands in the right
collection. Do not leave `KIT` or `ASM` included in the view layer when you finish unless the user had them on.

**Through a work file.** For long or tool-heavy work, or work another agent does headless:

```python
ns["checkout"](r"//work/KIT_EXT.blend", ["EXT_Wall_2x3_A", "EXT_Door_2x3_A"])   # live, through the MCP
```

Then, headless and in parallel with other work files if needed, run any skill's scripts on
`blender/work/KIT_EXT.blend` (modelling, `uv-unwrapping`, `rizomuv-uv-pipeline`, `pbr-texturing`, review renders,
`blender-to-unity` export), ending with `save_file()`. Then integrate:

```python
rep = ns["integrate"](r"//work/KIT_EXT.blend", ["EXT_Wall_2x3_A", "EXT_Door_2x3_A"])   # materials="work" after texturing
print(rep)
```

- `integrate` refuses with the lines that changed when someone edited those collections in MASTER after the
  checkout. Do not pass `force=True` to get past it: check out again and redo the work on the new version, or ask the
  user which version to keep.
- A new piece made in the work file is integrated by naming it; it lands in its family collection.
- An assembly checked out carries copies of the pieces it uses; on integrate those map back to MASTER's own pieces,
  so only the assembly's arrangement comes back. To change a piece, check the piece out.
- Export straight from a work file is fine (`blender-to-unity` exports each piece collection), as long as the work
  file was checked out after the last change to those pieces. Set `kit_status = "exported"` in MASTER afterwards
  (live), not by integrating a work file just for that.
- Delete the work file and its `.checkout.json` once integrated, so nobody integrates a stale copy later.

Headless, when MASTER is open nowhere: `-- --checkout <work> --names ...`, then later `-- --integrate <work> --names
... [--materials work]` (it saves MASTER and writes the snapshot; run `--changes` first, as always).

## 5. Save and snapshot

```python
diff = ns["changes_since"](r"//MASTER.snapshot.json")   # yours, plus anything the user did meanwhile
print("\n".join(ns["describe"](diff)))
bpy.ops.wm.save_mainfile()                               # live: the user's own save settings
ns["save_snapshot"](r"//MASTER.snapshot.json")
```

Anything in that last diff that you did not do is the user working while you did: tell them it is included in the
save. Headless: `save_file()`, then `save_snapshot`. A save without a snapshot after it makes your own edits look like
the user's next time; a snapshot without a save makes their unsaved work look like yours.

In `vrchat-world-orchestration`, `blender/MASTER.snapshot.json` and `blender/work/` belong in the `writes` of every
task that writes MASTER.

## Changing layout

Split to single, after the user asked (record it):

1. Make sure no session has any of the files open, and copy the `blender/` folder somewhere as a backup.
2. Open `MASTER.blend`, `setup_single_master()`, and move every existing placement into the `MASTER` collection.
3. For each KIT file: append (not link) its piece collections and parent them under `KIT/KIT_<FAMILY>`. For each ASM
   file: append its assembly collection under `ASM`, then re-point the instances inside it at the local pieces.
4. Re-point every placement in `MASTER` from the linked collection to the local one of the same name
   (`ob.instance_collection = <local collection>`), so placement ids survive; never delete and re-place.
5. Check that `missing_ids()` and the libraries list are empty once saved (unused libraries drop on save), audit, save,
   snapshot. Keep the old KIT and ASM files until the user has checked the result.

Single to split: `checkout()` each family's pieces to `blender/kits/KIT_<FamilyName>.blend` and each assembly to
`blender/asm/ASM_<Name>_<Variant>.blend` (rebuild its instances there as links to the KIT files), then in MASTER link
them and re-point the placements, and delete the local `KIT` and `ASM` collections. Unset `kit_layout` (or set it to
`"split"`).
