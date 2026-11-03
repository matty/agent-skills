# Migrating from MASTER to PLACEMENTS

Before 2026-11-03 the placements collection was called `MASTER` (zones `MASTER_<Zone>`), the same name as the file.
It is now `PLACEMENTS`. Nothing falls back to the old name: `setup_single_master()` and `place_piece()` refuse a file
that still has it, and the audit reports "legacy collection MASTER: the placements collection is now PLACEMENTS". The
file keeps its name, `MASTER.blend`. To migrate a world (with the user's go-ahead, editing as in "Editing alongside the
user"):

```python
import bpy
for c in list(bpy.data.collections):
    if c.library is None and (c.name == "MASTER" or c.name.startswith("MASTER_")):
        c.name = "PLACEMENTS" + c.name[len("MASTER"):]
# A room's envelope kept in REF (a stand-in the user builds on) moves to SHELL / SHELL_<Zone> the same way.
```

Then save and `save_snapshot`, and rename the engine side to match: the Unity root GameObject `MASTER` becomes
`PLACEMENTS`, and the sync files follow (`blender-unity-placement-sync`, "Migrating from MASTER").

`legacy_collections()` lists what is left to rename. A split world migrates the same way in its MASTER.blend (its
KIT and ASM files hold no placements collection).
