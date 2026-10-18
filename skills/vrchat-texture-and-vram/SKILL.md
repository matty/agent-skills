---
name: vrchat-texture-and-vram
description: Cut texture memory and download size in VRChat/Unity worlds - Quest or iOS build over 100 MB, slow loads, stutter, VRAM blowout. Format per map (BC7, DXT1/5, BC5, ASTC block sizes), crunch limits, mip streaming, Android and iOS overrides, metallic-smoothness packing, mesh and audio import settings. Whole-world triage starts at vrchat-world-optimization; lightmap size and count belong to vrchat-lighting-and-baking.
---

# Texture, VRAM and build-size optimisation

Two numbers get confused: the **download** (the compressed bundle: VRChat refuses Android and iOS worlds over 100 MB,
and it sets the loading time) and **memory** (textures in their GPU format: stutter, paging and crashes in full
instances). Find out which one is too big, then follow that procedure. Sizes are VRChat's MB = 2^20 bytes (the
mobile limit is 104,857,600 bytes after build-time compression). For a whole-world performance triage, start with
the `vrchat-world-optimization` skill.

## Measure first

- **Download**: build with the SDK: its Builder checks the bundle's download size (and its uncompressed size)
  against the platform's limit. VRWorld Toolkit's World Debugger, when installed, shows the latest SDK build's stats.
  Without a build (no platform module, no sign-in), estimate from the compressed texture data at each platform's
  format and call it an estimate.
- **Memory**: each texture's storage size, not the Profiler's runtime size (which counts the editor's CPU copy and
  can read up to twice: 1.00-1.01x measured 2026-10-17, 2x in the dry run). The editor encodes for the active build target: measure Quest on the Android target.
- **Every texture the scene ships**: the sweep snippet in references/texture-formats.md walks the open scene's
  dependencies (only what the scene references ships) and lists size, platform overrides, crunch, Mip Streaming and
  filter, largest first.

## Download too big (the 100 MB mobile limit, long loads)

1. Clamp every **Android and iOS** override to 1024 or below (512 for small or distant things), at the ASTC block in
   the format table. Unity keeps separate Android and iOS tabs: set both.
2. Remove duplicates: the same image imported twice and referenced twice ships twice. A texture nothing in the
   scene references does not ship; the sweep lists only what does.
3. Crunch large textures where download size matters: on DXT1/DXT5 (PC) or ETC/ETC2 (Android and iOS) data only, never BC7,
   BC5, BC4 or ASTC. A crunched ETC2 override shrinks a mobile download but takes more VRAM than ASTC 6x6 (ETC2 RGB
   0.5, RGBA 1 byte per pixel, against 0.44).
4. Audio: Vorbis, mono for positional sources, Streaming for music (references/mesh-and-audio-import.md).
5. Lightmaps: Non-Directional, and a lower Lightmap Resolution only before the UV2 is packed (afterwards it pushes
   the UV2 gaps under 2 texels); the `vrchat-lighting-and-baking` skill owns those numbers.
6. Meshes: rig and blend shapes off. Mesh Compression stays Off on kit pieces (Medium already misaligns tiling UVs
   at joints and shrinks UV2 gaps: references/mesh-and-audio-import.md); Low at most on a unique prop.
7. Remove PC-only decor from the mobile builds: EasyQuestSwitch (a Creator Companion package VRChat's cross-platform
   guide recommends) switches objects and components per build target; or keep a separate mobile scene.
8. Re-check static batching: its combined mesh ships in the bundle.

PC has no SDK size limit; VRChat asks public worlds to "Try to keep your worlds under 200MB".

## VRAM too high (stutter, crashes, gigabytes of memory)

Targets for all texture memory together: PC under 1.5 GB, Quest and iOS under 150 MB (the same budgets as the
`vrchat-world-optimization` skill). The sweep prints the total for the active build target.

1. Resolution first: halving a texture's dimensions quarters its memory. PC 2048 at most (4096 only where a player's
   face gets within about 30 cm), Android and iOS 1024.
2. Format: nothing uncompressed (RGBA32 is 4 bytes per pixel against 1 for BC7, 0.5 for DXT1, 0.44 for ASTC 6x6);
   use the format table.
3. Read/Write Enabled off on textures and meshes: on keeps a second, CPU-side copy.
4. Mip Streaming on for world textures, so the client can drop top mips under VRAM pressure.
5. Pack channels (below): one metallic-smoothness map instead of separate grey maps.
6. Reflection probes at 64-128; lightmaps per the `vrchat-lighting-and-baking` skill.

Crunch does nothing for memory: a crunched texture is plain DXT or ETC in VRAM.

## Format per map type

Bytes per pixel in parentheses, top mip; mips add a third. Maths, worked examples and Unity's defaults:
references/texture-formats.md.

| Map | PC (Standalone tab) | Android and iOS tabs |
|---|---|---|
| Albedo, no alpha | DXT1 (0.5); BC7 (1) where banding shows, and on surfaces seen from under 1.5 m when PC leads (`world.quality: pc_lead`) | ASTC 6x6 (0.44); 8x8 (0.25) for background |
| Albedo with alpha | BC7 or DXT5 (1) | ASTC 6x6 (0.44) |
| Normal map | BC5, or Unity's default DXT5 (both 1) | ASTC 4x4 (1); 5x5 (0.64) if size-bound |
| Metallic (R) + smoothness (A) | BC7 or DXT5 (1) | ASTC 6x6 (0.44); 4x4 (1) if its gradients band |
| Single channel (height, mask) | BC4 (0.5) | ASTC 6x6 (0.44) |
| Detail albedo, detail normal | As albedo and normal map: small (256-512) and finely tiled | As albedo and normal map |
| HDR (skybox, cubemap) | BC6H (1) | ASTC HDR (Unity's only compressed HDR format on Android) |
| UI, full-screen | as albedo, mipmaps off | as albedo, mipmaps off |

## Import settings

| Setting | Do this |
|---|---|
| Max Size | Per platform: PC 2048 (4096 only for a hero surface), Android and iOS 1024 or less |
| Format | Per the table; never "None" (uncompressed) |
| Crunch | Default tab: Use Crunch Compression (Format Automatic: DXT1/DXT5 on PC, ETC/ETC2 on Android and iOS). A platform tab: pick RGB Crunched DXT1, RGBA Crunched DXT5, RGB Crunched ETC or RGBA Crunched ETC2 directly. Never with BC7, BC5, BC4 or ASTC; Compressor Quality 50-75 |
| Generate Mip Maps | On for all world geometry; off only for UI and full-screen effects |
| Mip Streaming | On for world textures (VRChat streams world and avatar textures since client 2024.4.2) |
| Mip Map Filtering | Kaiser: the SDK's build panel flags Box filtering as blurry |
| Preserve Coverage, Alpha Cutoff | On for alpha-tested (cutout) textures, with Alpha Cutoff at the material's cutoff: otherwise foliage and fences thin out and vanish with distance as the mips average their alpha (Unity: it keeps "coverage during the alpha test", https://docs.unity3d.com/2022.3/Documentation/Manual/texture-type-default.html, checked 2026-10-18) |
| sRGB (Color Texture) | Off for masks, metallic-smoothness, AO and other data; on for albedo and emission |
| Alpha Source | None when the texture has no alpha (then DXT1 instead of DXT5) |
| Aniso Level | Leave the default: the SDK's quality presets force anisotropic filtering on for all textures (SDK 3.10.5); raise a level only if a floor still blurs at grazing angles in the client |
| Read/Write Enabled | Off |
| Non-Power of 2 | Scale to a power of two: NPOT sizes cost memory and are padded on GPUs without NPOT support (Unity: use them for GUI only) |

## Channel packing (Unity Standard and VRChat Standard Lite)

- One `_MetallicGlossMap`: **R = metallic, A = smoothness** (1 - roughness), G and B unused. Both shaders read it
  that way; Standard Lite also multiplies it by its Metallic and Smoothness sliders, so set both to 1 (a material
  switched from Standard keeps Metallic 0 and renders non-metal; VRChat Worlds SDK 3.10.5 source).
- Occlusion is its own map (Standard reads only its G channel). In a baked world the lightmap carries the occlusion:
  usually leave the slot empty.
- Never a glTF-style ORM map (occlusion R, roughness G, metallic B) on Standard: it reads R as metallic and alpha as
  smoothness.
- A custom shader: pack what it samples, and record the channel layout in the texture name.

## Lightmaps and probes

Lightmaps are textures and follow the same maths (PC 1 byte per pixel, mobile ASTC about 0.45); count, size and
directional mode belong to the `vrchat-lighting-and-baking` skill. On Windows the Low, Normal and High Quality
Lightmap Compression settings all store BC6H at the same size (measured Unity 2022.3.22f1, 2026-10-18), so High
Quality costs no PC memory. Baked reflection probes import compressed: keep them at 64-128.

## Sources (checked 2026-10-17)

| Facts | Source |
|---|---|
| 100 MB mobile limit after build-time compression | https://creators.vrchat.com/platforms/android/quest-content-optimization/ |
| iOS follows the Android rules | https://creators.vrchat.com/platforms/iOS/ |
| EasyQuestSwitch for per-platform objects | https://creators.vrchat.com/platforms/android/cross-platform-setup/ (updated 2026-09-15) |
| PC: "Try to keep your worlds under 200MB" | https://creators.vrchat.com/worlds/submitting-a-world-to-be-made-public |
| Bits per pixel, crunch formats | https://docs.unity3d.com/2022.3/Documentation/Manual/class-TextureImporterOverride.html |
| Default formats, crunch only with Format Automatic | https://docs.unity3d.com/2022.3/Documentation/Manual/class-TextureImporter.html |
| Mip streaming in the client | https://docs.vrchat.com/docs/vrchat-202442-open-beta |
| Standard's metallic and occlusion channels | Unity's built-in shader source (UnityStandardInput.cginc: `MetallicGloss`, `Occlusion`) |
| SDK details (MB size, Kaiser check, quality presets) | VRChat Worlds SDK 3.10.5 source, read 2026-10-17: references/texture-formats.md |
