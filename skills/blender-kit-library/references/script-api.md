# kit_library.py calls

Load in Blender: `ns = {}; exec(open(r"<skill>/scripts/kit_library.py", encoding="utf-8").read(), ns)`, then call
`ns["new_piece"](...)` and so on. Paths starting with `//` are relative to the open .blend. The command-line forms
(`--audit`, `--relink`, `--changes`, `--snapshot`, `--checkout`, `--integrate`) are in the script's docstring.

| Call | Run in | Does |
|---|---|---|
| `new_master(filepath)` | Blender run with no file | Empties the scene, `setup_single_master()`, saves at `filepath` |
| `setup_single_master()` | Any file | Makes `KIT` and `ASM` (excluded from the view layer), `PLACEMENTS` and `REF` (not `SHELL` or `CEILINGS`: add them with the first envelope zone), sets `scene["kit_layout"] = "single"`; refuses (RuntimeError) a file with a legacy `MASTER` collection; safe to repeat |
| `audit_shell_zone(coll, materials=None)`, `shell_zones()` | Single MASTER.blend, work file | The shell checks for one `SHELL_<Zone>` or `CEIL_<Zone>` by its `kit_status` (`SKILL.md`, "Checking a kit"); the zone collections in the file. A zone checks out to a work file and integrates back like a piece (a new one lands under `SHELL` or `CEILINGS`) |
| `legacy_collections()` | Any file | Local collections still named `MASTER` or `MASTER_<Zone>`, the placements collection's old name (`SKILL.md`, "Migrating from MASTER") |
| `is_single()` | Any file | True in a single MASTER.blend |
| `new_piece(name, parent=None)` | KIT file, ASM file, single MASTER | Creates (or returns) the piece or assembly collection under `parent` (default: `KIT/KIT_<FAMILY>` or `ASM` in a single MASTER, else the scene collection), rejects names outside the patterns, sets `instance_offset` to zero |
| `place_piece(name, location=(0, 0, 0), rot_z=0, into=None)` | Single MASTER.blend | Places one instance of the local piece or assembly into `into` (default `PLACEMENTS`, refused while a legacy `MASTER` collection is left; pass an assembly's collection to build it) |
| `snapshot(collections=None)`, `diff_snapshots(old, new)`, `describe(diff)` | Any file | Plain-data record of collections, objects (transform, mesh digest, materials, modifiers) and materials (or only the named collections); what changed between two; readable lines |
| `save_snapshot(path)`, `load_snapshot(path)`, `changes_since(path)` | Any file | Writes the snapshot after a save; the changes since it (`None` when there is none yet) |
| `checkout(work, names, blender=None)` | Single MASTER (live or headless) | Writes the named collections to a work .blend, then a short headless Blender (`blender`, default this one) links them into its scene; plus `<work>.checkout.json`. The open file is neither changed nor saved (Blender 5.2.2 crashes writing a scene with `libraries.write`, so the scene is made in the work file itself) |
| `integrate(work, names, materials="master", force=False)` | Single MASTER | Replaces the named collections in place from the work file (instances follow), adds new ones under their family or `ASM`; refuses if they changed since the checkout; `materials="work"` takes the work file's materials. Save afterwards |
| `list_library(path)` | Any file | Piece and assembly collection names in another .blend |
| `link_piece(path, name, location=(0, 0, 0), rot_z=0, into=None, relative=True)` | Split ASM, MASTER.blend | Links the collection (reusing an existing link) and places one instance, turned `rot_z` degrees about Z, into collection `into` |
| `link_collection(path, name, relative=True)`, `place(coll, location, rot_z, name=None, into=None)` | Split ASM, MASTER.blend | The two halves of `link_piece` |
| `reload_libraries(paths=None)` | A live session | Reloads every linked library (or those in `paths`); returns their paths |
| `missing_libraries()`, `missing_ids()`, `relink(search_dirs, relative=True, renamed=None)` | Split ASM, MASTER.blend | Lists libraries whose file is missing and linked data missing from its file; re-points each direct library at the same-named (or `renamed`) .blend under `search_dirs` and reloads it (save afterwards, unless `missing_ids(True)` lists data still missing); indirect links come back as "fix <ASM file> first", several candidates as "ambiguous" |
| `relink_files(blend_files, search_dirs, renamed=None)` | Blender run with no file | Relinks the files in passes until nothing changes, saves each that relinked cleanly, reopens them all; returns `(still, log)`: what each file still misses, and every pass's results |
| `audit_kit(module, materials=None)`, `audit_piece(coll, module)`, `problems(report)` | KIT file, single MASTER.blend, work file | The audit in `SKILL.md` ("Checking a kit") at grid `module` metres (required), reading excluded or disabled pieces as they export (included while it reads them, then restored); every shell zone gets `audit_shell_zone` (`shell`), its meshes are owned (`shell_meshes`), not stray; a legacy `MASTER` collection is a problem; `problems` flattens a report to readable lines |
| `save_file(filepath=None)` | Any headless run | Saves (or saves as, creating the folder) with no `.blend1` backup, restoring `save_version` afterwards |
| `new_file(filepath)` | Blender run with no file | Empties the scene (factory startup emptied, preferences untouched) and saves it at `filepath`, creating folders |

API used, checked against Blender 5.2 on 2026-10-17: `bpy.ops.wm.read_homefile(use_factory_startup=True,
use_empty=True)` (unlike `read_factory_settings`, it leaves the preferences alone),
`bpy.data.libraries.load(path, link=True, relative=True)` and `bpy.data.libraries.write(path, datablocks,
path_remap="RELATIVE_ALL")` (https://docs.blender.org/api/current/bpy.types.BlendDataLibraries.html; `write` and
`ID.user_remap` signatures checked against the 5.2 docs on 2026-10-20), `Library.reload()`
(https://docs.blender.org/api/current/bpy.types.Library.html), `Collection.instance_offset`
(https://docs.blender.org/api/current/bpy.types.Collection.html).
