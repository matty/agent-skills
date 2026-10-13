# Engine notes

The rest of this skill is engine-neutral. This file holds what a specific engine does with the UVs, with sources.
Add a section when another engine is used, with its own sources, rather than writing its specifics into the body.

## Unity (2022.3, Built-in Render Pipeline; the version VRChat uses)

| Topic | Unity behaviour | Source |
|---|---|---|
| UV channels | A mesh carries UV0-UV7 (8 maps). Blender's first UV map is UV0 (textures), the second is UV1, which Unity calls `uv2` / "UV1" and bakes lightmaps from | https://docs.unity3d.com/2022.3/Documentation/Manual/LightingGiUvs.html |
| Vertex splits | "A vertex must be split if it has multiple normals, UV coordinates or vertex colors" | https://docs.unity3d.com/2022.3/Documentation/Manual/ModelingOptimizedCharacters.html |
| Tangents | The model importer calculates MikkTSpace tangents ("Calculate Tangent Space") by default, matching Blender's bakes | https://docs.unity3d.com/2022.3/Documentation/Manual/FBXImporter-Model.html |
| Normal map convention | Y+ (OpenGL-style), which is what Blender bakes | same |
| Normals | Import normals from the FBX (Normals: Import) so the hard edges you baked with survive | same |
| Mirrored islands | The bitangent sign is stored per vertex in `tangent.w`, so a normal map baked with the mirror in place shades correctly | https://docs.unity3d.com/2022.3/Documentation/ScriptReference/Mesh-tangents.html |
| Texture wrap | Wrap Mode Repeat is the default, so islands offset by whole tiles sample the same texels | https://docs.unity3d.com/2022.3/Documentation/Manual/texture-type-default.html |
| Lightmap UV rules | Inside 0-1 and no chart sharing texels with another. Keeping charts at least 2 texels apart at the final resolution is a practical rule, not a stated Unity number: bilinear filtering reads neighbouring texels, so closer charts bleed | https://docs.unity3d.com/2022.3/Documentation/Manual/LightingGiUvs.html |
| Generate Lightmap UVs | The importer's generator overwrites `uv2`: leave it off for meshes with an authored lightmap UV. When generating: Hard Angle 88 deg, Angle Error 8%, Area Error 15%, Pack Margin 4 px by default; use Margin Method **Calculate** with honest Min Lightmap Resolution and Min Object Scale, since the manual 4 px Pack Margin assumes the mesh fills a whole 1024 lightmap | https://docs.unity3d.com/2022.3/Documentation/Manual/LightingGiUvs-GeneratingLightmappingUVs.html |
| Seam stitching | Stitch Seams (Progressive lightmapper) hides seams between straight, axis-aligned chart edges | https://docs.unity3d.com/2022.3/Documentation/Manual/Lightmapping-SeamStitching.html |
| Checking a bake | Scene view draw mode UV Overlap shows overlapping lightmap texels | https://docs.unity3d.com/2022.3/Documentation/Manual/GIVis.html |
| Bakery | The Bakery lightmapper has the same no-overlap, inside 0-1 rule and packs each renderer into its own rectangle | Bakery documentation (https://geom.io/bakery/wiki/) |

Lightmap resolution, footprint sizing and bake settings for Unity / VRChat worlds: the `vrchat-lighting-and-baking`
skill.
