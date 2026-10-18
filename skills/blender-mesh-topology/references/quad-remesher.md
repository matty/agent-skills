# Driving Quad Remesher from Python

Measured with Quad Remesher 1.4.1 (Exoside) on Blender 5.2, Windows, 28-29 Sep 2026; interface rechecked
2026-10-17 against the installed Blender bridge (version 1.4.1) and https://exoside.com/quadremesher-troubleshooting.
Exoside released engine 1.4.3 on 15 Oct 2026 (same troubleshooting page): rerun the FreezeBorders check below after
updating. Helpers: `scripts/quad_remesh.py`.

## When to use it, and when not

Keep the remesher for free-form patches with few or free borders. On engineered surfaces bounded on every side by
fixed borders (sweeps, decks, bands) it has to absorb every density mismatch at the borders and leaves knots there:
frozen borders plus a coarse target produced knots at corners that looked fine in a far render and messy in wire. The
hand-designed grid (`grid-layout.md`) was cleaner for the stair landing, at about 1.6x the remesher's fewest-quads
count.

## The engine

- The add-on (`quad_remesher_1_4`) has no Python API: `bpy.ops.qremesher.remesh` is a modal operator on a timer,
  awkward from scripts. Drive the engine directly instead (synchronous, about 0.3 s for a few thousand input
  triangles): `xremesh -s <settings file>`.
- Engine folders (the add-on downloads the engine on its first run; replace 1.4 with the installed version):
  Windows `%ALLUSERSPROFILE%\Exoside\QuadRemesher\Datas_Blender\QuadRemesherEngine_1.4\xremesh.exe`, macOS
  `/Users/Shared/Exoside/QuadRemesher/Datas_Blender/QuadRemesherEngine_1.4/xremesh`, Linux
  `~/.local/share/Exoside/QuadRemesher/Datas_Blender/QuadRemesherEngine_1.4/` (Exoside's troubleshooting page).
  `quad_remesh.find_engine()` picks the newest installed version. The bridge needs Blender's FBX add-on enabled.
- **File names are fixed.** It refuses (`HostApp com failed. (bdfps;bdfpi;bdfpo)` in the progress file) unless the
  settings, input and output are `RetopoSettings.txt`, `inputMesh.fbx`, `retopo.fbx` in the add-on's work folder
  (`%TEMP%/Exoside/QuadRemesher/Blender/` on Windows, `/var/tmp/Exoside/...` on macOS, `/tmp/Exoside/...` on Linux),
  with the progress file `progress.txt` there too.
- Export exactly like the add-on: `export_scene.fbx(use_selection=True, bake_anim=False, global_scale=1,
  apply_unit_scale=False, apply_scale_options='FBX_SCALE_NONE', use_space_transform=False, axis_forward='-X',
  axis_up='Z')`, which writes raw object-space values.
- Import like the add-on: `import_scene.fbx(filepath, global_scale=1, use_manual_orientation=True,
  axis_forward='-X', axis_up='Z')`, then read the imported object's local mesh data. The axis and scale settings
  only change the object's matrix (without `use_manual_orientation` they are ignored and the file's own axes are
  used); the mesh data stays in the exported space unless `bake_space_transform` is on, so never bake on this import.
- Progress file `2` means success; negative values are errors.
- Deterministic: the same input and settings gave the same mesh.

## Settings

Written by the add-on (1.4.1): `TargetQuadCount`, `CurvatureAdaptivness`, `ExactQuadCount` (0 when Adapt Quad Count is
on), `UseVertexColorMap`, `UseMaterialIds`, `UseIndexedNormals`, `AutoDetectHardEdges`, `SymAxis` (+`SymLocal=1`).
`quad_remesh()` writes them too; its defaults differ from the add-on's in `TargetQuadCount` (1000, add-on 5000) and
`AutoDetectHardEdges` (0, add-on 1). Any key can be passed as a keyword.

Read by the engine but not exposed (the names appear in `xremeshlib.dll` 1.4.1): **`FreezeBorders`** (tested: keeps
every border vertex, 101/101 against 6/101 without), `FreezeBordersCoef`, `TargetEdgeLength`,
`TargetQuadCountAsInputPercentage`, `VarDensityRatio`, `MaxQuadRatio`, `UseCurves` / `FileCurves` /
`GlobalCurvesStrength` / `GlobalCurvesType` (guide curves), `UseHardEdgeFlags`, `AutoDetectHardEdges_Angle`,
`KeepHardEdges`, `UsePolygonGroups`, `UseSmoothingGroups`, `UseFacesSelections`, `UseEdgesSelections`,
`DenoiseStrength`, `FollowBorders`, `SymTopo`, `MaxThreadCount`, `PreProcess_WeldPoints`,
`PostProcess_SplitPointsOnCreasedNormals`. Unverified, because Exoside does not document them: what each untested
key does, the fixed-file-name rule beyond the error above, and whether 1.4.3 changed any of it. Verify a key on a
small patch before relying on it.

## From a patch object to a remeshed mesh

Split the patch off into its own object first (a disc-like region with one border; for a symmetric patch, one half
cut at its mirror line, so the line is part of the border), apply its modifiers, then:

```python
import bmesh
import bpy

qr, gt = {}, {}
exec(open(r"<skill>/scripts/quad_remesh.py", encoding="utf-8").read(), qr)
exec(open(r"<skill>/scripts/grid_topology.py", encoding="utf-8").read(), gt)
patch_input, remesh_patch, mirror_half = qr["patch_input"], qr["remesh_patch"], qr["mirror_half"]
PointCache = gt["PointCache"]

pts, tris, loop = patch_input(patch)              # object space; loop: the border, in order, frozen
print(len(loop), "border points")                 # even, and spaced near the target edge (table below)
faces, npos, raw = remesh_patch(pts, tris, loop, target=400)

bm = bmesh.new()
cache = PointCache(bm)                            # one vertex per position: the halves share the loop's vertices
loop_verts = [cache.get(p) for p in loop]
for sign in (1, -1):                              # sign 1 only for a patch that is not mirrored
    mirror_half(faces, npos, loop_verts, mirror_vert=lambda lv: cache.get((-lv.co.x, lv.co.y, lv.co.z)),
                new_vert=lambda co: cache.get(co), face=lambda vs: bm.faces.new(vs), sign=sign)
cache.weld()
me = bpy.data.meshes.new("Remeshed")
bm.to_mesh(me)
bm.free()
```

`patch_input` raises when the border is not one simple loop (a hole, or two patches in one object). Resample a border
with uneven or odd spacing in the source mesh before calling it. Then audit the result (`validation.md`) with
`problems(r, allow_open=True)` if the patch stays open.

## What goes wrong, and the handling

| Symptom | Cause | Handling |
| --- | --- | --- |
| Pinches, knots of tiny faces at corners | frozen border spacing uneven or far from the target edge | resample borders evenly near the target edge; keep patches away from sharp border corners; or design the grid by hand |
| Border edge split, open edges | a frozen edge over about 3x the target | add stations so no border edge is much longer than the target |
| Zero-area slivers at the border | odd number of border edges; repeated border vertices in the output | make each loop's edge count even; weld output by position and drop collapsed and hairpin faces (`weld_layout`) |
| Extra vertex on the mirror line, seam unwelded | `SymAxis` | remesh one half with the mirror line as a frozen border and mirror it yourself (`mirror_half`) |
| Material-border edge loop 1-3 cm off the intended line | the loop is approximate | snap its vertices back onto the line; merge any vertex left within a third of an edge length |
| A face folded over another (edge with 3-4 faces) | narrow strip with a right-angled corner | avoid narrow strip patches; retry at other target counts, then another input fill spacing |
| Curvature adaptivity | no measurable effect on a smooth, even surface | leave at default |

Always run the output through a validation that checks the border is exactly the frozen loop and no edge has more
than two faces, and retry (target x 0.96/1.04/0.92/..., then a different input fill spacing) before accepting:
`remesh_patch()` does the first two.
