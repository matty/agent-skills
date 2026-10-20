# Round-trip test

Run once per project before relying on the sync, and again after changing the FBX export settings. It proves the
axis conversion, the merge and both appliers on the real project, so every step compares the two sides.

## Steps

1. Two KIT pieces, one asymmetric (an L-shaped wall), exported and packaged as prefabs.
2. In MASTER, place three instances, one turned 90 deg, and sync. Unity must show them where Blender does: compare a
   Blender render with a Unity screenshot from the same viewpoint, and the numbers after `(-x, z, -y)`.
3. Move one in Unity and a different one in Blender, sync: both sides end up with both moves.
4. Move the same one differently on both sides: merge exits 2 with one conflict; resolve it with `--take-id`.
5. Duplicate one in Unity and move the copy: the copy becomes a new placement in Blender; the original keeps its id.
6. In Unity, parent one piece under another: nothing changes in Blender.
7. Delete one in Blender: it disappears in Unity.
8. For a project with assemblies, the same steps for one ASM scope first, then place that assembly in MASTER and
   sync MASTER. The first Apply of the ASM scope must create its prefab.

Commit after each step must succeed, and a merge right after a commit must report everything unchanged.

## Log

| Date | Blender / Unity | Passed |
|---|---|---|
| 2026-10-14 | 5.2.2 / 2022.3.22f1, VRChat world project | Steps 1-5 and 7, a re-parent into a folder in Unity (not an edit), a duplicate made with Ctrl+D after a script reload |
| 2026-10-16 | 5.2.2 / 2022.3.22f1 | A first sync of 18 placements into a new scene; a create-then-update confirming Apply leaves the scene saved and clean |
| 2026-10-17 | 5.2.2 headless | The agent-skills repo tests: dump and apply in Unity space, the merge loop, an ASM collection scope, the offset and override warnings, a deleted parent's children kept in place, no stale dump after a failed one |
| 2026-10-17 16:50 | Unity 2022.3.22f1, scripted batch in a test project | 44 of 44 checks: Check and Apply refusals; nested placements dumped relative to MASTER and kept when their parent is deleted; swap refusals; ASM prefab creation with no dirty scene; a Dump, merge, Apply, commit round trip; the Tools menu |
| 2026-10-17 19:53 | Unity 2022.3.22f1, same batch | 57 of 57: the above, plus a moved parent leaving the placement under it in place (two levels, with and without a plain empty between, each undone with one Ctrl+Z), and the swap and rename BLOCKED lines on both sides |
| 2026-10-17 20:36 | Unity 2022.3.22f1, same batch | 68 of 68: the above, plus the one-pass update (three levels: a building and a crate moved, the table between them kept; a refused swap under a moved table keeping its pose, then way out (c)), a forced re-run of a plan with assigns and deletes reporting no errors, and an empty plan leaving the scene bit-identical. Step 8 end to end (a real ASM file nested in MASTER) is still to run |
| 2026-10-20 | Blender 5.2.2 headless, Unity 2022.3.22f1 batch in a test project | Names and folders: labels without `.001` / ` (1)`, `/` read as `-`, collection and GameObject folders created on apply and never deleted, a nested placement kept under its parent, a swap keeping the name, a plan item without `group` left in place, one Undo for renames and moves, an ASM prefab target. Blender 13 of 13 cases, Unity 31 of 31 checks, merge 62 tests |
| 2026-10-20 (later) | Blender 5.2.2 headless, Unity 2022.3.22f1 batch | Folder renamed whole (a light inside going along, one Ctrl+Z restoring it), a light sharing a folder name never used as one, the fallback when the target exists, folder lists in both dumps, names cut to 255 bytes, the rename budget. Blender 14 of 14, Unity 41 of 41, merge 70 tests |
