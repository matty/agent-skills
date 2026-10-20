# Split files: linking, reloading, relinking and renaming

Only for a project the user asked to split into KIT, ASM and MASTER files (`SKILL.md`, "Choose the file layout
first"). A single MASTER links nothing, so none of this applies to it.

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
  `bpy.data.libraries` entry (`reload_libraries()` does all of them). Files that link a changed library reload it
  rather than being reopened. A headless run (`blender -b`) opens the file fresh and already loads every library from
  disk, so there a reload changes nothing: check the result against the previous placement snapshot or render, not
  against the same session before the reload.
- **Links broken after files moved or renamed** (empty or pink instances, "cannot read library" warnings; the audit
  lists "linked library missing"): one headless run repairs every file that links anything, in any order, and
  reports what is still missing:
  `blender -b --factory-startup --python-exit-code 1 --python <skill>/scripts/kit_library.py -- --relink <project>/blender/kits <project>/blender/asm --files <every ASM .blend> <project>/blender/MASTER.blend`.
  A renamed KIT file adds `--renamed KIT_Old.blend=KIT_New.blend`; a renamed assembly, or a piece moved to another
  KIT file, takes the rename procedure (Renaming, below). Details, ambiguous copies, live sessions, moved and renamed
  at once, and the manual route: `repair-links.md`.

## Renaming

Rename the collection in its file (for an assembly, the ASM file too, keeping one assembly per file named after it),
and rename its exported file and engine asset to match. Then in every file that places it (ASM files, then MASTER) link the renamed collection and re-point the existing
instances (`ob.instance_collection = <renamed collection>`) instead of deleting and re-placing them, so placement ids
survive; the old link is dropped when the file is saved. Moving a piece to another KIT file is the same procedure:
append the piece's collection into the new KIT file, delete it from the old one, then in every file that places it
link it from the new file and re-point the instances.

## Script calls

The linking, reloading and relinking calls are in `script-api.md`.
