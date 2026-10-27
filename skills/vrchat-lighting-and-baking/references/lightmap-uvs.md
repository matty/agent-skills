# Lightmap UVs (UV2): rules, generator settings, symptoms

Unity bakes lightmaps into the mesh's second UV channel: the second UV map in Blender's list, `Mesh.uv2` in C#,
`TEXCOORD1` in shaders. How to unwrap it well is the `uv-unwrapping` skill's job (`rizomuv-uv-pipeline` automates it);
how big each mesh's rectangle in the lightmap is, and so how wide its gaps must be, is references/lightmap-budget.md.

## Rules

1. **No overlapping charts.** Two surfaces sharing texels share their light: one wall's shadow lands on another.
   (UV0 may overlap and tile; UV2 may not.)
2. **Everything inside 0-1.**
3. **Gaps of 2 texels or more at the footprint** the mesh gets in the lightmap, and 1 texel or more to the tile
   edge. Pack for the worst case: gap in UV = 2 / (texels/m x sqrt(surface area) x Scale In Lightmap), which holds
   whatever the UV2's bounding box turns out to be (lightmap-budget.md). A margin chosen for a whole 1024 map is a
   fraction of a texel on a small mesh.
4. **Split charts at hard angles.** A chart continued around a 90 deg corner smears the shadow terminator.
5. **Even texel density inside a mesh**; weight whole renderers with Scale In Lightmap instead.

## Runs, joints and overlays

Unity cannot stitch lightmaps across renderers ("Seam stitching only works on single GameObjects"), so the pieces of
one continuous surface (a wall run, a floor, a ceiling, a terrain's chunks) must bake alike on both sides of every
joint. Plan it with the UV2, before the bake:

| Rule | Why |
|---|---|
| Effective density within about 10% across a run (*practice*), read per renderer from the post-bake snippet in lightmap-budget.md | The same light at another texel size blurs and steps differently: a shadow edge or a gradient breaks at the joint |
| Scale In Lightmap set per run, never per piece | One promoted piece is a density step at both of its joints |
| UV2 chart borders on each piece's own edges: a face that runs edge to edge is one chart | The joint is the one seam a run cannot avoid; a chart border inside a face adds another |
| One LOD treatment per run: walls without LODs, or one LOD Group over the whole run so every piece switches together | LOD1 bakes at 0.5x LOD0's texel scale (lightmap-budget.md, LODs) and a probe-lit LOD lights differently: a LOD1 beside a LOD0 neighbour is a lighting step |
| Joints closed: pieces meet exactly on the grid with no gap, and faces hidden in a joint (a wall's bottom against its slab) deleted; where light still leaks, overlap the pieces by at least one texel at the run's density (*practice*; one texel = 1 / texels per metre: 10 cm at 10 texels/m) only where the spec's extents allow it (a kit piece keeps its greybox extents), else Backface Tolerance (below) | Rays escape through a gap or a joint that only touches: light leaks along it, or dark bleeds in |

Leaks or dark lines left at seated joints: **Backface Tolerance**, on a Lightmap Parameters asset (Project window >
Create > Lightmap Parameters; assigned to the scene in the Lighting window's Lightmapping Settings, or per Mesh
Renderer under Lightmapping). A texel whose rays hit too many back faces (one inside a seated wall) is invalid, and
Unity "clones valid values from surrounding texels" into it: 1.0 rejects a texel if any ray hits a back face, 0 only
if every ray does. Unity's scripting page (written for Enlighten's precompute) adds that on closed meshes, where back
faces are rarely visible, "a positive value can reduce light leaking or darkening that intersecting geometry would
otherwise cause"; single-sided geometry (a plane, a decal quad) is the reason to keep it low. Check it in the Scene
view's Texel Validity draw mode. Sources: https://docs.unity3d.com/2022.3/Documentation/Manual/class-LightmapParameters.html,
https://docs.unity3d.com/2022.3/Documentation/ScriptReference/LightmapParameters-backFaceTolerance.html (checked
2026-10-27).

**Overlays** (a decal, a sign, a plaque, a painted line) on a lightmapped surface are lightmapped whatever their size,
at the surface's Scale In Lightmap with Cast Shadows Off (so the quad casts no shadow on the surface under it in the
bake), and counted as the budget script's KIND `lightmap`; or they are modelled into the piece mesh and share its
UV2. Probe-lit (the 64 px rule for a Free prop), an overlay gets one ambient value across its surface and reads as a
lighter or darker patch on the lightmapped wall.

## Authoring UV2 in Blender without the uv-unwrapping skill

The minimum that bakes cleanly:

1. Add a **second** UV map (order matters, not the name). Make it active before unwrapping so UV0 is untouched.
2. Unwrap into few, large charts cut at hard angles: Smart UV Project at about 66 deg suits architecture. Lightmap
   Pack makes one chart per face and suits only very simple meshes.
3. Average Islands Scale, then Pack Islands with Margin Method **Fraction** and Margin = half the gap from rule 3
   (2 texels at b = 1). Fraction leaves the margin at the tile edge and twice it between islands. The default,
   Scaled, ignores the number: packed with the full gap on a 2 x 3 x 0.2 m wall at 15 texels/m it left 0.71 texels
   between islands, while Fraction at half the gap left 2.09 between and 1.04 to the edge (Blender 5.2.2, measured
   2026-10-17).
4. Export both UV layers; in Unity leave *Generate Lightmap UVs* **off** for these meshes.

## Letting Unity generate them

For one-off props only (a mesh change regenerates the layout and invalidates the bake). Model importer > Generate
Lightmap UVs, then:

| Setting (Unity 2022.3) | Use |
|---|---|
| Margin Method | **Calculate**, never Manual: the Manual Pack Margin (default 4 px) assumes the mesh fills a whole 1024 map |
| Min Lightmap Resolution | the scene's Lightmap Resolution x the smallest Scale In Lightmap this mesh gets |
| Min Object Scale | the smallest scale the mesh is placed at |
| Hard Angle (default 88 deg) | lower for more splits and fewer smeared corners |
| Angle Error (8%), Area Error (15%) | lower for less distortion, at the cost of more charts |

Source: https://docs.unity3d.com/2022.3/Documentation/Manual/LightingGiUvs-GeneratingLightmappingUVs.html (checked
2026-10-17).

## Symptom -> cause

| Symptom | Cause |
|---|---|
| A shadow on an unrelated surface | Overlapping UV2 charts |
| "objects in the Scene with overlapping UV's" in Editor.log | Charts closer than about 2 texels at the footprint, or real overlap |
| Dark or bright fringes along chart borders | Gaps too small for the footprint |
| Blocky, pixelated shadows | Texel density too low: raise Scale In Lightmap for that renderer, not the whole scene |
| Visible seam across a flat wall | Charts split where they should be continuous. Stitch Seams (Mesh Renderer > Lightmapping, Progressive only, off by default) hides seams between straight, axis-aligned chart edges inside one renderer |
| Seam or step exactly where two kit pieces meet | Unity: "Seam stitching only works on single GameObjects": the run's rules above (density, Scale In Lightmap, chart borders, LODs). Still showing: merge a co-planar run into one renderer and tick Stitch Seams (untested) |
| Light along the foot of a wall or under a ceiling | Pieces that only touch at the joint: seat and overlap them, then Backface Tolerance (above) |
| A lighter or darker patch under a decal or sign | The overlay is probe-lit: lightmap it or model it into the piece (Overlays, above) |
| Only part of a mesh is lit | UV2 outside 0-1, or the renderer is not Contribute GI |
| Six lightmaps appeared and the bake time exploded | Scene Lightmap Resolution too high, or Scale In Lightmap left high on large meshes |
| Lightmaps enormous in the build | Map count x size, and Directional mode (about twice the memory) |

Seam stitching: https://docs.unity3d.com/2022.3/Documentation/Manual/Lightmapping-SeamStitching.html (checked 2026-10-17).
