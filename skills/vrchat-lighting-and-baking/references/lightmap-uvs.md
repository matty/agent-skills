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
| Seam exactly where two kit pieces meet | Unity: "Seam stitching only works on single GameObjects". Untested route: give neighbours equal texels/m x Scale In Lightmap, put chart borders on each piece's outer edges, or merge a co-planar run into one renderer and tick Stitch Seams |
| Only part of a mesh is lit | UV2 outside 0-1, or the renderer is not Contribute GI |
| Six lightmaps appeared and the bake time exploded | Scene Lightmap Resolution too high, or Scale In Lightmap left high on large meshes |
| Lightmaps enormous in the build | Map count x size, and Directional mode (about twice the memory) |

Seam stitching: https://docs.unity3d.com/2022.3/Documentation/Manual/Lightmapping-SeamStitching.html (checked 2026-10-17).
