# RizomUVLink API cheatsheet

Measured on RizomUV 2027.0.598 (Windows 11) with RizomUVLink's python313 build, from Blender 5.2's bundled Python,
9 Oct 2026. The full command reference ships with RizomUV: `<install>/doc/index.html`, and every command's
parameters are in the docstrings of `<install>/RizomUVLink/RizomUVLinkBase.py` (grep `PARAMETER       : `).
Examples worth reading: `RizomUVLink/examples/FilelessMeshTransfer.py` and `Headless.py`.

## Contents

- Launching and closing
- Fileless data transfer
- The commands this pipeline uses
- Pack: scaling, layout and the undocumented parts
- Reading state
- Errors
- Running several instances

## Launching and closing

| Call | Notes |
|---|---|
| `sys.path.insert(0, "<install>/RizomUVLink"); from RizomUVLink import CRizomUVLink, CZEx` | The package picks the compiled module for the running Python (3.6-3.13 on Windows; 3.9-3.13 on Linux/macOS). Python 3.14 has no build yet. |
| `link = CRizomUVLink(); port = link.RunRizomUV(exePath=..., headless=True)` | Picks the first port in 49152-65534 with nothing listening, launches `rizomuv.exe -id <port> -hl` and waits until it answers. **Unsafe for parallel work**: the launch is serialised by a per-port lock file in `%TEMP%`, and a second launcher that loses that lock *waits for and connects to the first launcher's instance*. Two clients on one port then swap replies (measured: a cube came back as another job's icosphere, with no error). `rizom_link.RizomSession` avoids it (see "Running several instances"). |
| `subprocess.Popen([exe, "-id", str(port), "-hl"])`, then `link.Connect(port)` | What `rizom_link` does: its own process on a port it has locked, so it can verify, prioritise and kill exactly that instance. About 2 s alone, 5-9 s with three starting together; the first launch after install can take much longer (antivirus), hence the 120 s default timeout. |
| `headless=True` | Needs 2027.0.417+. No window and no dialogs: what a dialog would have said goes to the command log, answered "no". Still needs a logged-in desktop session (Windows) or an X display (Linux); it will not run as a service or in a bare container. |
| `background=True` / `iconized=True` | Window behind the host / minimised. Use when the user may want to look. |
| `link.Quit({})` | Always in a `finally:`. A headless instance has no window to close, so a script that forgets leaves an invisible process (and on a floating licence, a token) behind. `Quit` returns before the process has exited: wait on the process (`RizomSession.close` waits, then kills after 10 s). |
| `link.RizomUVVersion()` | String such as `2027.0.598.g864535413`; log it with every result. |
| `link.Connect(port)` | Attach to an instance started with `rizomuv.exe -id <port>`. The instance also binds `port + 1` (change notifications), so give instances ports two apart. |

Locating the install: Windows registers each version under `HKLM\SOFTWARE\Rizom Lab\RizomUV VS RS <major>.<minor>`
(the default value of the subkey `rizomuv.exe` is the executable path **without** `.exe`, measured on 2027.0: add it). macOS: `/Applications/RizomUV.<ver>.app`,
package at `Contents/Resources/RizomUVLink`. Linux: inside the AppImage at `usr/bin/RizomUVLink`.
`scripts/rizom_link.py` does all of this, with `RIZOMUV_EXE` / `RIZOMUVLINK_DIR` overrides.

## Fileless data transfer

```python
link.Load({"Data.PolySizes": sizes,        # corners per polygon
           "Data.PolyXYZIDs": xyz_ids,     # 3D vertex per corner
           "Data.CoordsXYZ": xyz,          # flat x,y,z
           "Data.PolyUVWIDs": uvw_ids,     # UV vertex per corner: splitting a vertex here IS a seam
           "Data.CoordsUVW": uvw})         # flat u,v,w seed
d = link.Save({"Data": True})["Data"]      # d["PolyUVWIDs"], d["CoordsUVW"] (and d["PolySizes"])
```

- Polygon and corner order are preserved: write `d["PolyUVWIDs"]` back corner by corner. The UV vertex count
  changes (cuts add vertices), the corner count does not.
- **Seed the UVs with the 3D positions**, not zeros: Unfold sizes islands from the seed area.
- **Seams travel in the seed topology.** Give two corners different `uvw_ids` and that edge is cut before RizomUV
  starts; `Select Auto` then adds its own cuts. This is how generator seams and Blender `use_seam` edges get in.
- `Save({"IndexTable.PolygonIDsToIslandIDs": True})["IndexTable"]["PolygonIDsToIslandIDs"]` gives the island
  of each polygon. Ask for it in its own call: combined with `"Data": True`, only the index table comes back.
- `"Data.UseImportedUVWPolygons": True` on Save keeps the imported UV vertex numbering when RizomUV had to repair
  topology and the host cannot take topology changes.
- Load replaces the current mesh, so one instance can process a whole batch.

## The commands this pipeline uses

```python
# 1. auto seams (on top of the seed seams), cut, clear the selection
link.Select({"PrimType": "Edge", "WorkingSet": "Visible", "Select": True, "ResetBefore": True, "Auto": {...}})
link.Cut({"PrimType": "Edge", "WorkingSet": "Visible"})
link.Select({"PrimType": "Edge", "WorkingSet": "Visible", "DeSelect": True, "All": True})
# 2. flatten
link.Unfold({"PrimType": "Island", "WorkingSet": "Visible", "BorderIntersections": True, "TriangleFlips": True,
             "Iterations": 5})
link.Optimize({"PrimType": "Island", "WorkingSet": "Visible", "BorderIntersections": True, "TriangleFlips": True,
               "Iterations": 25, "Mix": 1, "AngleDistanceMix": 1.0})
# 3. pack (see below), then Save
link.IslandGroups({"Mode": "DistributeInTilesEvenly", "WorkingSet": "Visible"})   # required after a fileless Load
link.Pack({...})
```

`Auto` keys (the GUI name in brackets): `SharpEdges.AngleMin`, `PipesCutter` (Link holes), `HandleCutter`
(Cut handles), `QuadLoopCutter`, `QuasiDevelopable` (Mosaic: `Developability`, `IslandPolyNBMin`, `AreaMinRatio`,
`FitCones`, `Straighten`, `IslandsNB`), `Skeleton` (Hierarchical: `Open`, `SegLevels`), `Box`, `StretchLimiter`,
`Quality` (the stretch limiter's threshold, 0-1), `FlatteningMode`, `SizeLimiter.LengthRatio`, `ReWeld`
(`Threshold`, `PolyMax`, `LENGTHMax`), `Smooth` (`Iterations`, `Force`), `SkeletonUnoverlap`, `BooleanUnoverlap`.
What each does to distortion: `distortion-and-quality.md`.

Other commands worth knowing: `Weld`, `Hide`, `Tag`, `IslandProperties`, `Hotspot` (trim-sheet matching, with
`Match.Tags`/`Match.Materials`), `RasterExport` (layout and stretch images), `Uvset` (multiple UV sets),
`GenerateCheckerboardTexture`.

## Pack: scaling, layout and the undocumented parts

```python
link.Pack({"RootGroup": "RootGroup", "WorkingSet": "Visible", "ProcessTileSelection": False,
           "RecursionDepth": 1,              # pack the tiles' contents (0 would pack only the tiles: nothing)
           "Translate": True, "UsePixelUnit": True, "PaddingSizePx": 8, "MarginSizePx": 4,
           "MapResolution": 1024, "Strategy": "PaddingPerfect",   # or "Efficient", "PixelAligned"
           "Rotate": {"Step": 90.0},         # 0 disables rotation; smaller steps cost time
           "Device": "CPU",                  # default "FastestGPU" (CUDA, falls back to CPU)
           "Scaling": {"Mode": 2},           # nested dicts and dotted keys ("Scaling.Mode") are equivalent
           "LayoutScalingMode": 2})
```

The enum integers are not published. Measured (re-check with `scripts/probe_pack_enums.py` after an upgrade):

| `Scaling.Mode` | Name | Behaviour seen |
|---|---|---|
| 0 | OFF | islands keep their size |
| 1 | SET_3D_AREA | UV area = 3D area (ratio 1) |
| 2-5 | AVG_RATIO_OF_MOVABLE / GROUP / FIXED / ALL | one shared ratio, the area-weighted average (identical when every island is movable in one group) |
| 6 | AVG_RATIO_USER_SPECIFIED | ratio = `Scaling.SpecifiedScale` exactly |
| 7 | TEXEL_DENSITY | ratio = `Scaling.TexelDensity` / (100 x `MapResolution`): see below |
| 8 | PIXEL | average edge = one pixel |
| 9 | MAP | internal; the command crashes ("bad function call") |

| `LayoutScalingMode` | Name | Use |
|---|---|---|
| 0 | DISABLED | leave everything where packing put it |
| 1 | TRANSLATE_ONLY | texel-density packs (no rescale afterwards) |
| 2 | BEST_FIT | fill the tile uniformly: per-piece maps and lightmaps |
| 3 | FORCE_FIT | non-uniform fill: distorts, avoid |

Behaviour not in the docs:

1. **`Scaling.Optimization` defaults to `"Fill"`**: `Scaling.Mode` sets the islands' relative sizes, then the
   whole layout is scaled to fill the tile. Any absolute request (modes 1, 6, 7) is lost. Pass
   `"Optimization": "None"` inside `Scaling` for them.
2. **`TexelDensity` is per 100 mesh units.** RizomUV treats the coordinates as centimetres, so metre input needs
   `TD x 100`, and no readable unit setting was found (`Vars.Scene...` paths do not exist through `Get`). Use mode 6
   with `SpecifiedScale = px_per_unit / MapResolution` instead: exact, in whatever unit the mesh is in.
3. **A scale that cannot fit leaves the islands untouched**: no error, same return value. Always measure the
   result (`rizom_uv.pack` returns `fits`).
4. **After a fileless Load, `Pack` does nothing** until `IslandGroups({"Mode": "DistributeInTilesEvenly"})` puts
   the islands into the tile. `NormalizeUVW` does not help.
5. **`Coverages` comes back empty** in fileless mode: measure coverage yourself (`uv_metrics.report`).
6. A top-level `"Global"` parameter is rejected (`The parameter 'Global' is not recognized`), although the
   docstring describes one. Per-island or per-group values go through `IslandProperties` / `IslandGroups`.
7. `Device` defaults to `"FastestGPU"` (CUDA) and falls back to CPU. This skill passes `"CPU"`: it leaves the GPU
   to bakes and anything else running. CPU and GPU packs have not been compared; pass `device="FastestGPU"` to
   `pack_spec` for very large batches if the GPU is free.
8. Not every unwrap is repeatable: the same organic mesh came back with 76-79 islands across calls and processes
   (Suzanne), while simpler meshes were bit-identical. Compare grades with tolerances, never hashes.

## Reading state

- `link.Count("Lib.Mesh.Islands")` works.
- `link.Get("Lib.Mesh.RootGroup.Children")` and other group trees fail to serialise (`CSubMeshGroup`): read the
  data with `Save({"Data": True})` instead.
- `link.GetVersion("Lib.Mesh.UVW")` returns a change token without transferring data (for live bridges).

## Errors

- A failed `Load` **returns** `{"Error": {"Msg", "Code"}}` instead of raising. Check it, or the failure surfaces
  several commands later as something unrelated.
- A command that fails inside RizomUV raises `CZEx`. A lost connection (crash) also raises rather than hanging.
- Paths passed to RizomUV (`RasterExport`, file Load/Save) must be absolute with forward slashes, in a folder that
  exists: RizomUV's working directory is its install folder, and with a relative path or a missing folder it writes
  **nothing** and reports no error. Check the file afterwards.

## Running several instances

The link protocol is one client per port, and nothing in RizomUVLink stops two clients sharing one: replies then
cross silently. Rules that held under test (3 processes launched in the same millisecond, 3 threads):

1. **One private instance per session.** Claim the port with an OS file lock held for the whole session (released
   by the OS if the holder dies), check nothing listens on it or on `port + 1`, start `rizomuv.exe -id <port> -hl`
   yourself, wait for the port, then check that the process listening is your child (Windows:
   `GetExtendedTcpTable`). `rizom_link.RizomSession` does this, on ports 61000-64998 (above `RunRizomUV`'s scan).
2. **Separate processes for parallel work** (`rizom_pool.py`). Threads with their own sessions also measured
   clean, but never share one link between threads.
3. **Tie the instance to its host.** On Windows, a Job Object with `KILL_ON_JOB_CLOSE` kills the instance when the
   host dies (measured: gone within 2 s of the host being killed); elsewhere a watchdog process does it.
4. **Restart after a `CZEx` or a timeout** rather than reusing the instance. A killed instance is detected in about
   2 s (`RizomUV is not responding`); a per-job timeout is a timer that kills the process, which makes the blocked
   call raise.

Each instance takes a licence token on a floating licence. A pool of 3-4 is plenty: a 400-face piece takes about
0.3 s to unwrap and pack twice, so launch cost dominates small batches.
