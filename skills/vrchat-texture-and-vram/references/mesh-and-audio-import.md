# Mesh and audio import settings

Textures are usually the biggest item, but meshes and audio fill downloads too. Checked 2026-10-17 against Unity
2022.3.

## Meshes (Model importer)

| Setting | Do this |
|---|---|
| Read/Write Enabled | Off: on keeps a second, CPU-side copy of the mesh |
| Rig > Animation Type | None for static props |
| Blend Shapes | Off unless used |
| Normals | Import, when authored in Blender, so the hard edges survive |
| Tangents | None when the material has no normal map |
| Mesh Compression | **Off for kit pieces and anything with tiling UVs or packed UV2 gaps.** Unity quantises each mesh on its own range ("a range between the maximum and minimum, where a fixed number of bits represents where each value falls", https://docs.unity3d.com/2022.3/Documentation/Manual/mesh-compression.html), so neighbouring pieces round differently. Measured on two kit walls (2 and 3 m) meeting at a joint, Unity 2022.3.22f1, 2026-10-18: Low moved nothing visibly (0.007 mm, 0.01 px); Medium stepped the tiling UV0 by up to 0.61 px at 1024 across the joint and cut 2-texel UV2 gaps to 1.81-1.85 texels; High opened the joint by up to 6.3 mm and cut the gaps to 1.3. The editor holds the quantised mesh, so the lightmap bake sees it too. Low at most, on a unique prop that meets nothing. It saves disk and download only: "Unity decompresses the data" when it loads |
| Optimize Mesh | Everything (the default) |
| Import Cameras, Lights, Visibility | Off: a Blender FBX brings extra objects otherwise |

Static batching's combined mesh ships in the bundle as well: an over-eager Batching Static flag adds download size
(the `unity-batching-and-instancing` skill).

## Audio (AudioClip importer)

| Setting | Do this |
|---|---|
| Compression Format | Vorbis: quality 50-70 for music, 30-50 for effects. PCM and ADPCM clips are what bloat a download |
| Load Type | Streaming for music and long ambience; Compressed In Memory for most clips; Decompress On Load only for short effects played often |
| Force To Mono | On for every positional (3D) source: half the size, no audible difference at a distance |
| Sample Rate Setting | Override to 22-44 kHz for effects and ambience |
