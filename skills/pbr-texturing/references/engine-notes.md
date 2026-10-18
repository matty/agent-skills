# Engine notes

What an engine reads from the maps this skill makes. One section per engine; sources inline.

## Unity, Built-in Render Pipeline (VRChat worlds)

VRChat worlds run on Unity 2022.3.22f1 with the Built-in pipeline: Unity's Standard shader on PC and VRChat's mobile
shaders on Android (Quest) and iOS. Formats, sizes, crunch and per-platform overrides are `vrchat-texture-and-vram`'s;
lightmap modes are `vrchat-lighting-and-baking`'s. Shader facts below are read from the shader sources: Unity's
CGIncludes in the 2022.3.22f1 editor install (`Editor/Data/CGIncludes`) and the VRChat Worlds SDK 3.10.5 package
(`Packages/com.vrchat.base/Runtime/VRCSDK/Sample Assets/Shaders/Mobile/` in a VRChat project), read 2026-10-18.

### Standard (PC)

| Slot | Map | Notes |
|---|---|---|
| Albedo (`_MainTex`) | `T_*_BaseColor`, sRGB on | A cutout or fade material reads opacity from its alpha |
| Metallic (`_MetallicGlossMap`) | `T_*_MetallicSmoothness`: R metallic, A smoothness | With the map assigned, `_Metallic` is ignored and smoothness = A x `_GlossMapScale` (`UnityStandardInput.cginc` lines 151-170); never a glTF-style ORM map, which this reads as metal in R |
| Normal Map (`_BumpMap`) | `T_*_Normal`, imported as texture type Normal map | "Unity uses Y+ normal maps", "sometimes known as OpenGL format" (https://docs.unity3d.com/2022.3/Documentation/Manual/StandardShaderMaterialParameterNormalMap.html, checked 2026-10-18) |
| Occlusion (`_OcclusionMap`) | Its own map; Standard reads only G (`UnityStandardInput.cginc` lines 117-125) | In a baked world the lightmap carries large-scale occlusion: use it only for small crevices |
| Emission (`_EmissionMap` x `_EmissionColor`) | sRGB on | Set the material's Global Illumination to Baked so it lights the bake: BakedEmissive "emits lighting into baked lightmaps and baked lightprobes" (https://docs.unity3d.com/2022.3/Documentation/ScriptReference/MaterialGlobalIlluminationFlags.BakedEmissive.html, checked 2026-10-18) |
| Secondary maps: Detail Mask, Detail Albedo x2, Detail Normal Map | A finer tiling layer for close-range sharpness on tiling surfaces | Detail albedo multiplies by `unity_ColorSpaceDouble` (`UnityStandardInput.cginc` line 96), 4.59 in a linear project (`UnityCG.cginc` line 33): mid-grey (sRGB 128) is neutral. The detail tiling is the Detail Albedo slot's own; UV0 or UV1 per material. The mask's alpha limits it ("mask off certain areas", https://docs.unity3d.com/2022.3/Documentation/Manual/StandardShaderMaterialParameterDetail.html, checked 2026-10-18) |

**Keywords come from the inspector.** Standard compiles each feature only with its keyword: `_NORMALMAP`,
`_METALLICGLOSSMAP`, `_DETAIL_MULX2`, `_EMISSION` (`UnityStandardInput.cginc` lines 11, 15, 95, 155, 193, 200). The
material inspector sets them when a texture is assigned by hand; a script that assigns textures (an import script,
Unity MCP) must call `material.EnableKeyword(...)` for each, or the map is ignored until someone opens the material.

**Kit meshes and tiling textures.** Keep Mesh Compression Off on kit pieces: it quantises each mesh within its own
range, so neighbours round differently (measured 2026-10-18 on Unity 2022.3.22f1: Medium shifted tiling UVs 0.6 px at
a joint between two pieces and cut 2-texel UV2 gaps to 1.8). The mesh import settings are `vrchat-texture-and-vram`'s.

### VRChat/Mobile/Standard Lite (Android, iOS)

Lit world materials on mobile; GPU instancing on (tick it on the material).

| Behaviour | Source (`VRChat-Mobile-StandardLite.shader` unless named) | Consequence |
|---|---|---|
| Metallic = map R x `_Metallic`, smoothness = map A x `_Glossiness`, both sliders always applied (defaults 1.0) | lines 8-10, 153-155; the inspector draws both beside the map (`GUI/StandardLiteShaderGUI.cs` lines 310-317) | **Set `_Metallic` and `_Glossiness` to 1 when the map carries the values.** A Standard material switched to Standard Lite keeps Standard's `_Metallic` (unused by Standard once a map is set, default 0): it renders as non-metal, and at Standard's default `_Glossiness` 0.5 at half the smoothness |
| Occlusion from G | line 158 | As Standard; the inspector suggests packing it into the metallic map's G |
| Detail maps: mask (A), albedo x2 (`unity_ColorSpaceDouble`), detail normal with a scale, UV0 or UV1 (`_UVSec`), the albedo slot's tiling | lines 21-26, 60, 117-124, 138-139, 180-200; keyword `_DETAIL`, set by the inspector (`StandardLiteShaderGUI.cs` line 334) | The same close-range layer works on mobile, at extra samples per pixel |
| Geometric specular anti-aliasing (keyword `_ENABLE_GEOMETRIC_SPECULAR_AA`; property default on, variance 0.1, threshold 0.2) | lines 31-33, 66, 174-178; `VRChat.cginc` lines 494-498; the keyword is set only by the inspector (`StandardLiteShaderGUI.cs` line 351) | Reduces the shimmer of glossy, finely detailed surfaces in VR, but a material made or edited by script has it off until the keyword is enabled. Unity's Standard has none |
| Opaque only, no parallax | `RenderType` Opaque and no alpha in the surface pragma (lines 44, 83); no height property | Cutout or transparent surfaces need another shader on mobile, and cost there (Alpha, below) |
| Lightmap type Default, MonoSH or MonoSH without highlights (Bakery MonoSH) | lines 35, 63, 72-79; `VRChat.cginc` lines 273-293; directional lightmaps `VRChat.cginc` line 346 | Normal maps respond to baked light only with directional or MonoSH lightmaps |
| On a lightmapped surface with Non-Directional lightmaps, glossy reflections off and no realtime light, the normal map is not even sampled | lines 163-172 | A normal map there shows nothing: put the form in geometry and base colour, or bake directional or MonoSH |
| Vertex colour multiplies albedo unless the material sets `DISABLE_VERTEX_COLORING` | lines 67-68, 147-149 | Unity's Standard ignores vertex colour: a mesh exported with a colour attribute tints on mobile only |
| Emission (keyword `_EMISSION`) and the surface shader's generated Meta pass (no `nometa`) | lines 67, 83, 202-204 | Emissive materials can light the bake, as on PC |
| "Enable Bicubic Sampling" toggle | line 39; its variant is commented out (line 70) | Does nothing in SDK builds |
| `noforwardadd noshadow nodynlightmap nolppv noshadowmask` | line 83 | One realtime directional light, unshadowed; the lighting rules are `vrchat-lighting-and-baking`'s |

Every Standard Lite feature keyword is set only by its inspector (`StandardLiteShaderGUI.cs` lines 328-351): `_DETAIL`,
`_EMISSION`, `_MONOSH_SPECULAR` or `_MONOSH_NOSPECULAR`, `_ENABLE_GEOMETRIC_SPECULAR_AA`. A script that creates or
converts mobile materials sets the properties and enables the matching keywords itself, as for Standard.

### VRChat/Mobile/Lightmapped

Albedo (`_MainTex`, with its tiling) times the lightmap, nothing else: no normal, metallic, smoothness, detail,
emission or light probes (`VRChat-Mobile-Lightmapped.shader` lines 12, 78-79, 103-107). The cheapest baked surfaces;
everything else in the material is wasted texture memory.

### Alpha

- VRChat counts cutout as transparency on mobile: "As an aside, yes, 'alpha cutout' counts as transparency"
  (https://creators.vrchat.com/platforms/android/cross-platform-setup/, updated 2026-09-15, checked 2026-10-18).
- A cutout texture keeps its coverage in the distance with the importer's Mip Maps Preserve Coverage
  (`TextureImporter.mipMapsPreserveCoverage`: "rescale the alpha values of computed mipmaps so coverage is preserved")
  at the material's cutoff, `TextureImporter.alphaTestReferenceValue` ("the reference value (also known as the alpha
  cutoff)") (https://docs.unity3d.com/2022.3/Documentation/ScriptReference/TextureImporter-mipMapsPreserveCoverage.html
  and .../TextureImporter-alphaTestReferenceValue.html, checked 2026-10-18).
- Alpha-to-coverage needs MSAA and a shader that turns it on (`AlphaToMask On` in ShaderLab); Standard's Cutout mode
  does not.
