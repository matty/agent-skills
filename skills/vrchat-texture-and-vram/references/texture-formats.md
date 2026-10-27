# Texture formats, memory maths and measuring

Sizes are VRChat's MB: 2^20 = 1,048,576 bytes, as the SDK counts them (`ValidationHelpers.BYTES_TO_MB`, SDK 3.10.5).
Facts checked 2026-10-17 against https://docs.unity3d.com/2022.3/Documentation/Manual/class-TextureImporterOverride.html
(bits per pixel, crunch formats) and https://docs.unity3d.com/2022.3/Documentation/Manual/class-TextureImporter.html
(default formats, crunch rules).

## Bytes per pixel (top mip; a full mip chain adds a third)

| Format | Bytes/px | Platforms | Notes |
|---|---|---|---|
| RGBA32 | 4 | all | uncompressed: never ship it |
| RGB24 | 3 on disk, 4 on the GPU | all | uncompressed |
| BC7 | 1 | PC | RGB(A), best quality; Unity's High Quality choice on PC |
| DXT5 (BC3) | 1 | PC | RGBA, faster to compress; the Normal Quality choice for RGBA |
| DXT1 (BC1) | 0.5 | PC | RGB, no alpha; the Normal Quality choice for RGB |
| BC5 | 1 | PC | two channels: normal maps |
| BC4 | 0.5 | PC | one channel |
| BC6H | 1 | PC | HDR: skyboxes, cubemaps, HDR lightmaps |
| ASTC 4x4 | 1 | Android, iOS | High Quality choice |
| ASTC 5x5 | 0.64 | Android, iOS | |
| ASTC 6x6 | 0.44 | Android, iOS | Normal Quality choice |
| ASTC 8x8 | 0.25 | Android, iOS | Low Quality choice; background albedo only: surfaces a player never gets nearer than about 6 m (*practice*), never the ground or anything walked on |
| ETC2 RGB / RGBA | 0.5 / 1 | Android, iOS (A7 and later) | fallback for GPUs without ASTC; with ETC, the only mobile formats crunch can use |

ASTC stores 16 bytes per block at every block size, so bytes per pixel = 16 / (block width x block height), and a
texture rounds up to whole blocks.

## Worked examples (full mip chain)

| Texture | Size |
|---|---|
| 4096^2 RGBA32 | 85.3 MB |
| 4096^2 BC7 | 21.3 MB |
| 2048^2 BC7 | 5.33 MB |
| 2048^2 DXT1 | 2.67 MB |
| 2048^2 ASTC 6x6 | 2.38 MB |
| 1024^2 BC7, DXT5, BC5 or ASTC 4x4 | 1.33 MB |
| 1024^2 DXT1 | 0.67 MB |
| 1024^2 ASTC 6x6 | 0.60 MB (626,288 bytes: measured 2026-10-16 in Unity 2022.3.22f1) |
| 1024^2 ASTC 8x8 | 0.33 MB |

One uncompressed 4K texture outweighs a whole well-built Quest world, and halving a texture's dimensions quarters its
memory: resolution is a bigger lever than format.

## Unity's choices with Format: Automatic

| Platform | Low Quality | Normal Quality | High Quality |
|---|---|---|---|
| Windows, RGB / RGBA | DXT1 / DXT5 | DXT1 / DXT5 | BC7 |
| Windows, HDR | BC6H | BC6H | BC6H |
| Android and iOS | ASTC 8x8 | ASTC 6x6 | ASTC 4x4 |

On Android, HDR textures compress only to ASTC HDR. A per-platform override with an explicit format replaces these.

## Crunch

- Only DXT1/DXT5 (PC) and ETC/ETC2 (Android, and iOS from the A7 chip) data can be crunched: never BC7, BC5, BC4 or ASTC. Two ways in: the
  Default tab's Use Crunch Compression checkbox, which needs Format Automatic; or a platform tab's format list, which
  offers RGB Crunched DXT1, RGBA Crunched DXT5, RGB Crunched ETC and RGBA Crunched ETC2 directly. An Android or iOS
  override set to ASTC is not crunched at all.
- A crunched ETC2 override shrinks a mobile download, but in VRAM it is ETC2 (RGB 0.5, RGBA 1 byte per pixel), more
  than ASTC 6x6 (0.44).
- It shrinks the download only. Unity decompresses a crunched texture to DXT or ETC on the CPU at load, so VRAM is
  unchanged. VRChat: "Crunch compression only helps with download size", and it "may break your avatars later on if a
  new Unity version employs an incompatible version of Crunch"
  (https://creators.vrchat.com/platforms/android/quest-content-optimization/).
- Compressor Quality 50-75; it is lossy and slow to import.
- Never on a normal map or a detail normal map (*practice*, no published source): crunch's block artefacts land on
  the shading, and on a tiling or detail map they repeat in every tile. A Normal map texture left at Unity's PC
  default is DXT5 (the SKILL's format table), which crunch accepts: leave Use Crunch Compression off on it.

## Detail maps on mobile

When an Android or iOS override halves a surface's maps, its detail maps (Detail Albedo x2, Detail Normal) keep the
close-range sharpness for far less memory: a 512 pair (albedo ASTC 6x6, normal ASTC 4x4) is about 0.48 MB with
mips, while keeping an albedo and normal pair at 2048 instead of 1024 costs about 5.8 MB more (*derived* from the
worked examples above). Keep them on the mobile materials. In VRChat's `Standard Lite` (Worlds SDK 3.10.5,
`VRChat-Mobile-StandardLite.shader`): the detail maps use the Detail Albedo slot's own tiling and offset on UV0 or
UV1 (line 139), the Detail Mask's alpha is sampled on the main texture's UV (line 181), and the detail normal, like
the main normal map, is skipped on a surface with Non-Directional lightmaps, Glossy Reflections off and no realtime
light (lines 190-198): there only the detail albedo shows. The keyword `_DETAIL` is set only by the material
inspector: a script that builds the material enables it.

## Mipmaps and streaming

- Mipmaps on for everything in the world (UI and full-screen effects excepted): missing mips shimmer and waste
  bandwidth.
- Mip Map Filtering **Kaiser**: the SDK's world build panel flags Box-filtered textures ("This scene uses textures
  with 'Box' mipmap filtering, which blurs distant textures. Switch to 'Kaiser' for improved sharpness", SDK 3.10.5),
  and its opt-in DPID setting replaces the mips of Kaiser-filtered textures
  (https://creators.vrchat.com/releases/release-3-7-1/).
- Mip Streaming: the client has streamed textures under VRAM pressure "for Avatars and Worlds" since VRChat 2024.4.2,
  leaving world texture priority alone (https://docs.vrchat.com/docs/vrchat-202442-open-beta). Unity "always loads
  textures that don't use Mipmap Streaming at full resolution" (https://docs.unity3d.com/2022.3/Documentation/Manual/TextureStreaming.html),
  so tick Mip Streaming on world textures. VRChat does not document how its client treats the flag on world
  textures; the SDK's own quality presets switch streaming off in the editor, so editor numbers show full size.

## Anisotropic filtering

The SDK resets the project's quality levels to VRChat's presets, and every level sets Anisotropic Textures to Forced
On (`anisotropicTextures` 2 in the SDK's `EnvConfig.cs`, SDK 3.10.5): Unity then filters "all textures"
anisotropically (https://docs.unity3d.com/2022.3/Documentation/ScriptReference/AnisotropicFiltering.ForceEnable.html).
A per-texture Aniso Level only matters above the forced minimum. The client's own graphics settings are not
documented, so judge floors in the client.

## Measuring memory in the editor

- Read the storage size: `UnityEditor.TextureUtil.GetStorageMemorySizeLong(Texture)` (TextureUtil is internal: call
  it by reflection), or the size the texture inspector shows.
- The Profiler's runtime size also counts any CPU copy the editor keeps, so it can read up to twice the GPU size
  (28.7 MB runtime against 14.2 MB storage for one scene on 2026-10-16; 1.00-1.01x for nine textures on 2026-10-17).
- The editor encodes for the active build target: switch to Android (or encode with the Android override) to measure
  Quest sizes.

## Sweep the textures a scene ships (Unity Editor C#)

A method body that ends in a `return`: Unity MCP's `execute_code` wraps it in `public static object Execute()`; in an
Editor script, put it inside a static method that returns `object`. Save the scene first. It walks the open scene's
dependencies (`AssetDatabase.GetDependencies`, recursive): only what the scene references ships, lightmaps and baked
reflection probes included. It lists each texture, largest first, with its storage size for the active build target,
its PC, Android and iOS overrides (the iOS tab is "iPhone" in scripts), crunch, Mip Streaming, mipmap filter and
Read/Write, then the total. Editor-only textures (anything under an `Editor` folder, such as script icons) are
dependencies too but never ship, so the sweep skips them. RenderTextures (mirrors, cameras) and textures made at
runtime are not assets and are not counted: add them by hand (width x height x 4 bytes for a default colour target,
plus its depth buffer, times the MSAA sample count).

```csharp
string scene = UnityEngine.SceneManagement.SceneManager.GetActiveScene().path;
var getSize = typeof(UnityEditor.Editor).Assembly.GetType("UnityEditor.TextureUtil").GetMethod(
    "GetStorageMemorySizeLong", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.Public);
var rows = new System.Collections.Generic.List<System.Collections.Generic.KeyValuePair<long, string>>();
long total = 0;
foreach (string path in UnityEditor.AssetDatabase.GetDependencies(scene, true))
{
    if (path.Contains("/Editor/")) continue;                           // editor-only: never ships
    var imp = UnityEditor.AssetImporter.GetAtPath(path) as UnityEditor.TextureImporter;
    if (imp == null) continue;                                         // not a texture
    var tex = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Texture>(path);
    if (tex == null) continue;
    long size = (long)getSize.Invoke(null, new object[] { tex });
    total += size;
    string overrides = "";
    foreach (var platform in new[] { "Standalone", "Android", "iPhone" })
    {
        var s = imp.GetPlatformTextureSettings(platform);
        overrides += s.overridden ? $"{platform} {s.maxTextureSize} {s.format}; " : $"{platform} -; ";
    }
    rows.Add(new System.Collections.Generic.KeyValuePair<long, string>(size, $"{size / 1048576f:F2} MB {tex.width}x{tex.height} | {overrides}crunch {imp.crunchedCompression}, " +
        $"mip streaming {imp.streamingMipmaps}, filter {imp.mipmapFilter}, read/write {imp.isReadable} | {path}"));
}
rows.Sort((a, b) => b.Key.CompareTo(a.Key));
var report = new System.Text.StringBuilder();
foreach (var r in rows) report.AppendLine(r.Value);
report.AppendLine($"total {total / 1048576f:F1} MB in {rows.Count} textures for the active build target " +
                  "(targets: PC under 1500 MB, Quest and iOS under 150 MB)");
return report.ToString();
```
