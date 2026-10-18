# Repairing broken links

Symptoms: instances draw empty or pink, Blender warns it cannot read a library, the audit lists "linked library
missing" or "linked data missing". Blender keeps placeholders for missing linked data, so re-pointing the library
brings everything back. Checked against Blender 5.2.2 on 2026-10-17.

## Files moved

One headless run repairs every file that links anything. It saves each file that relinked cleanly, reopens them all at
the end and reports what is still missing; it exits 1 if anything is.

```
blender -b --factory-startup --python-exit-code 1 --python <skill>/scripts/kit_library.py --
    --relink <project>/blender/kits <project>/blender/asm
    --files <every ASM .blend> <project>/blender/MASTER.blend
```

- It looks for a .blend of the same file name under the folders after `--relink` and stores the new path relative.
- List every file that links anything. The order does not matter: it repeats passes until nothing changes, because a
  file that places an assembly can only reach the KIT pieces once that ASM file is fixed (until then `relink` reports
  those indirect links as "fix <ASM file> first").
- Point `--relink` at the folders that hold the live files. A file reached through two overlapping folders counts
  once. When several files share a name (an archive copy, a backup), only the one whose parent and grandparent
  folders match the old path's is taken; otherwise that link is left alone and reported as "ambiguous". A file on
  another drive is stored with its absolute path, and the run says so.
- A MASTER (or any file) open in a live Blender session is relinked in that session and saved there: the session's
  next save would overwrite a headless relink.

## A file renamed

- A KIT file whose collections kept their names: add `--renamed KIT_Old.blend=KIT_New.blend` to the same command.
- A renamed assembly (its file and its collection, one per file), or a piece moved to another KIT file, is a rename,
  not a relink: use the rename procedure (SKILL.md, Naming). A relink would find the file but not the collection in
  it; the run says so ("NOT SAVED ... renamed, or moved to another file"), saves nothing and exits 1.

## Files moved and a piece renamed at once

Relink first (the run leaves the renamed piece's files unsaved and says "NOT SAVED"), then follow the rename procedure
(SKILL.md, Naming), then relink again: the second run finds nothing left to repair, or the links the first run could
not save.

## By hand

In the file being fixed: `lib.filepath = "//../kits/KIT_New.blend"`, then `lib.reload()` and `save_file()`. The path is
relative to that file: `//../kits/` from an ASM file in `blender/asm/`, `//kits/` from `blender/MASTER.blend`. In the UI:
Outliner, Blender File view, right-click the library, Relocate
(https://docs.blender.org/manual/en/latest/files/linked_libraries/link_append.html, checked 2026-10-17).

## Python

`missing_libraries()` and `missing_ids()` list what is missing; `relink(search_dirs, renamed=None)` repairs the open
file (save afterwards with `save_file()`, unless `missing_ids(True)` still lists data); `relink_files(files,
search_dirs, renamed=None)` does the whole multi-file run above.
