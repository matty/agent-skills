# Driving Quad Remesher from Python

Measured with Quad Remesher 1.4 (Exoside) on Blender 5.2, Windows, 28-29 Sep 2026.

## The engine

- The add-on (`quad_remesher_1_4`) has no Python API. `bpy.ops.qremesher.remesh` is modal and asynchronous, awkward
  from scripts. Drive the engine directly instead (synchronous, about 0.3 s for a few thousand input triangles):
  `%ALLUSERSPROFILE%/Exoside/QuadRemesher/Datas_Blender/QuadRemesherEngine_1.4/xremesh.exe -s <settings file>`.
- **File names are fixed.** It refuses (`HostApp com failed. (bdfps;bdfpi;bdfpo)` in the progress file) unless the
  settings, input and output are `RetopoSettings.txt`, `inputMesh.fbx`, `retopo.fbx` in
  `%TEMP%/Exoside/QuadRemesher/Blender/`, with the progress file `progress.txt` there too.
- Export like the add-on: `export_scene.fbx(use_selection=True, global_scale=1, apply_unit_scale=False,
  apply_scale_options='FBX_SCALE_NONE', use_space_transform=False, axis_forward='-X', axis_up='Z')`; import the result
  with the same axes. Progress file `2` means success; negative values are errors.
- Deterministic: the same input and settings give the same mesh.

## Settings

Written by the add-on: `TargetQuadCount`, `CurvatureAdaptivness`, `ExactQuadCount`, `UseVertexColorMap`,
`UseMaterialIds`, `UseIndexedNormals`, `AutoDetectHardEdges`, `SymAxis` (+`SymLocal=1`).

Read by the engine but not exposed (found in `xremeshlib.dll`): **`FreezeBorders`** (tested: keeps every border
vertex, 101/101 against 6/101 without), `FreezeBordersCoef`, `TargetEdgeLength`, `TargetQuadCountAsInputPercentage`,
`VarDensityRatio`, `MaxQuadRatio`, `UseCurves` / `FileCurves` / `GlobalCurvesStrength` / `GlobalCurvesType` (guide
curves), `UseHardEdgeFlags`, `AutoDetectHardEdges_Angle`, `KeepHardEdges`, `UsePolygonGroups`, `UseSmoothingGroups`,
`UseFacesSelections`, `UseEdgesSelections`, `DenoiseStrength`, `FollowBorders`, `SymTopo`, `MaxThreadCount`,
`PreProcess_WeldPoints`, `PostProcess_SplitPointsOnCreasedNormals`. Untested ones: verify before relying on them.

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
than two faces, and retry (target x 0.96/1.04/0.92/..., then a different input fill spacing) before accepting.

## When not to use it

On engineered surfaces bounded on every side by fixed borders (sweeps, decks, bands), the remesher has to absorb
every density mismatch at the borders and leaves knots there. A hand-designed grid (`grid-layout.md`) was cleaner
for the stair landing. Keep the remesher for free-form patches with few or free borders.
