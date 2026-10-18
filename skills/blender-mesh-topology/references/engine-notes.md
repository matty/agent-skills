# Engine notes

What a specific engine does with the topology and normals this skill produces. One section per engine; everything
else in the skill is engine-neutral.

## Unity (2022.3, Built-in Render Pipeline; checked 2026-10-17)

| Topic | Unity behaviour | Source |
| --- | --- | --- |
| Custom normals | Kept when the model's Normals setting is Import (the default); Calculate recomputes normals and discards weighted or hardened ones | https://docs.unity3d.com/2022.3/Documentation/Manual/FBXImporter-Model.html |
| Vertex splits | "a vertex must be split if it has multiple normals, UV coordinates or vertex colors", so Unity's vertex count is usually above Blender's | https://docs.unity3d.com/2022.3/Documentation/Manual/ModelingOptimizedCharacters.html |
| Triangulation | Polygons with more than four vertices always become triangles on import; Keep Quads ("stop Unity from converting polygons that have four vertices to triangles") keeps only quads. Triangulate in Blender to choose the diagonals | https://docs.unity3d.com/2022.3/Documentation/Manual/FBXImporter-Model.html |
| Tangents | The importer can calculate MikkTSpace tangents, the same algorithm Blender bakes with | https://docs.unity3d.com/2022.3/Documentation/Manual/FBXImporter-Model.html |

Export settings, import settings and packaging for Unity: the `blender-to-unity` skill.
