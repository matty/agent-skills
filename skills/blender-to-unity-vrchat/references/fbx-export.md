# FBX export settings for Unity / VRChat, annotated

Blender's FBX exporter, static world geometry. Defaults are fine for most fields; these are the ones that matter.

## Include

| Field | Value | Why |
|---|---|---|
| Limit to Selected Objects | on | Export deliberately, not whatever is in the file |
| Object Types | **Mesh** (+ Armature/Empty only if actually needed) | Otherwise cameras, lights and empties become GameObjects in the prefab |
| Custom Properties | off | Noise |

## Transform

| Field | Value | Why |
|---|---|---|
| Scale | 1.0 | Do the conversion via Apply Scalings, not this |
| Apply Scalings | **FBX All** | Bakes unit conversion into the FBX so Unity's transform reads scale 1. `FBX Units Scale` (default) usually also works with Unity's Convert Units, but FBX All is the predictable one |
| Forward | **-Z Forward** (default) | Matches Unity's +Z forward after conversion |
| Up | **Y Up** (default) | Unity is Y-up |
| Apply Unit | on | Metre-consistent |
| Use Space Transform | on | Applies the axis conversion to the data |
| Bake Space Transform | **off** | Known to break normals/animation in several Unity versions; leave it off unless you have a specific reason |

Always **apply rotation and scale in Blender** (`Ctrl+A → Rotation & Scale`) regardless of these settings. Exporter tricks cannot fully compensate for a dirty transform.

## Geometry

| Field | Value | Why |
|---|---|---|
| Smoothing | **Face** | `Normals Only` and `Off` lose smoothing groups; Unity then guesses |
| Export Subdivision Surface | off | Bake it down yourself and control the count |
| Apply Modifiers | on | What you see is what ships |
| Loose Edges | off | Not renderable |
| Triangulate Faces | on (or use a Triangulate modifier) | Guarantees Unity's triangulation matches Blender's preview |
| Tangent Space | on **only** if the mesh uses normal maps | Otherwise wasted vertex data — and requires UVs and triangles |
| Vertex Colors | off unless the shader reads them (then match the colour space; Blender 4.x exports linear `sRGB`/`Linear` per the `colors_type` setting) | |

## Animation

Off entirely for static geometry. For animated world props, export with Baked Animation on and NLA strips off unless you are using them intentionally.

## Unity import settings to match

| Field | Value |
|---|---|
| Scale Factor | 1 (Convert Units on) |
| Mesh Compression | Off while iterating; Low/Medium at ship time |
| Read/Write Enabled | **off** |
| Optimize Mesh | on |
| Generate Colliders | off (author collision explicitly) |
| Normals | Import (Calculate only if Blender normals are wrong) |
| Tangents | Calculate Mikktspace, or **None** if no normal map |
| Generate Lightmap UVs | off if you authored UV2, on for kitbash props |
| Rig → Animation Type | **None** for static props |
| Import Cameras / Lights / Visibility | off |
| Blend Shapes | off unless used |

## Sanity test after the first export of a new asset

1. Drop the FBX into the scene. Transform should read position 0, rotation 0, **scale 1,1,1**.
2. A 2 m door should be 2 m against a 1.6 m capsule.
3. Face the object: no inside-out faces, smoothing intact.
4. Mesh inspector: expected triangle count, expected UV channel count (2 if you authored lightmap UVs), expected submesh count.
