---
name: vrchat-texture-and-vram
description: Cut texture memory, VRAM use and download size in Unity/VRChat projects - compression formats (BC7, DXT, BC5, ASTC), crunch, mipmaps, per-platform max size overrides, channel packing, mesh and audio import settings. Use when a world is too big to upload, exceeds the Quest 100 MB limit, stutters on load, eats gigabytes of VRAM, or when choosing import settings for textures, meshes and audio.
---

# Texture, VRAM and build-size optimization

Two different numbers get confused constantly:

- **Download size** — the compressed asset bundle. Governs the Quest **100 MB hard limit** and how long players wait at the loading screen.
- **Memory (VRAM) size** — textures decompressed to their GPU format, always larger. Governs stutter, paging and crashes in full instances.

**Crunch compression only shrinks download size.** In memory a crunched texture is still plain DXT/ETC. Fixing "my world is 400 MB" and fixing "my world eats 3 GB of VRAM" are different jobs.

## Measure first

- SDK **build report**, or search the editor log for `statistics` after a build — per-asset sizes, largest offenders first.
- **VRWorld Toolkit → Build Report** tab: sorted asset sizes plus batch texture-compression helpers.
- Unity **Memory Profiler** package for the in-memory picture.
- Quick sweep with Unity MCP `execute_code`: iterate `AssetDatabase.FindAssets("t:Texture2D")`, report width × height × format and flag anything over budget — far faster than clicking through the Project window.

## Texture memory maths

Bytes per pixel by format, plus **+33%** if mipmaps are on (they should be):

| Format | Bytes/px | Use for |
|---|---|---|
| RGBA32 / ARGB32 | 4.0 | never ship this |
| RGB24 | 3.0 (stored as 4) | never ship this |
| BC7 | 1.0 | PC albedo with alpha, high-quality colour |
| DXT5 / BC3 | 1.0 | PC albedo with alpha, cheaper/faster import |
| DXT1 / BC1 | 0.5 | PC albedo, **no alpha** — the workhorse |
| BC5 | 1.0 | normal maps (2-channel, best quality) |
| BC4 | 0.5 | single-channel masks (roughness, AO, height) |
| BC6H | 1.0 | HDR (skyboxes, reflection probes) |
| ASTC 4×4 | 1.0 | Quest, highest quality |
| ASTC 6×6 | ~0.36 | **Quest default for albedo** |
| ASTC 8×8 | 0.25 | Quest, background/low-detail |

Worked examples (with mips):

| Texture | Size |
|---|---|
| 4096² RGBA32 | **~89 MB** |
| 4096² BC7 | ~22 MB |
| 2048² BC7 | ~5.6 MB |
| 2048² DXT1 | ~2.8 MB |
| 1024² BC7 | ~1.4 MB |
| 1024² ASTC 6×6 | ~0.5 MB |

One uncompressed 4K texture can outweigh an entire well-built Quest world. Halving a texture's dimensions quarters its memory — resolution is a bigger lever than format.

## Import settings that matter

| Setting | Do this |
|---|---|
| **Max Size** | Per-platform override. PC 2048 (4096 only where a player's face is 30 cm from it), **Android 1024 or less** |
| **Compression** | Never "None". PC: BC7 for quality, DXT1/DXT5 for bulk. Android: ASTC 6×6 |
| **Crunch** | On for large textures where download size matters; it is lossy and slow to import, so quality slider 50–75. Zero VRAM benefit |
| **Generate Mip Maps** | **On** for all world geometry. Off only for UI and full-screen effects. Missing mips cause shimmer *and* thrash memory bandwidth |
| **Mipmap Filtering** | Use **Kaiser** when generating mipmaps (user preference). Set the Unity Texture Importer mipmap filter explicitly; this is separate from runtime Point/Bilinear/Trilinear filtering and anisotropy. |
| **sRGB (Color Texture)** | **Off** for masks, roughness, metallic, AO, data textures. On for albedo/emission |
| **Alpha Source** | None if the texture has no alpha — lets you use DXT1 at half the size |
| **Aniso Level** | 1–2 for most, 4+ only for floors seen at grazing angles |
| **Read/Write Enabled** | **Off** — it keeps a second CPU-side copy |
| **Non-power-of-two** | Scale to power of two, or block compression is unavailable |

## Channel packing

Three grayscale maps as three DXT1 textures = 1.5 bytes/px. The same three packed into RGB of one DXT5/BC7 = 1 byte/px, and one sampler instead of three. Pack roughness/metallic/AO (or whatever your shader wants) at authoring time in Blender or an image tool, and document the channel layout in the material name.

## Meshes

| Setting | Do this |
|---|---|
| Read/Write Enabled | **Off** (doubles mesh memory when on) |
| Rig → Animation Type | **None** for static props |
| Blend Shapes | Off unless used |
| Normals / Tangents | Tangents `None` if the shader has no normal map; Normals `Import` if authored in Blender |
| Mesh Compression | Low/Medium shrinks the bundle; check for visible artifacts on large flat surfaces |
| Optimize Mesh | On |
| Import Cameras / Lights / Visibility | Off — Blender FBX ships junk otherwise |

## Audio

Audio routinely accounts for half a world's download when imported raw.

- **Compression**: Vorbis, quality 50–70 for music, 30–50 for SFX.
- **Load Type**: `Streaming` for music and long ambience, `Compressed In Memory` for short clips, `Decompress On Load` only for very short, frequently-triggered SFX.
- **Force To Mono** for any 3D positional source.
- **Sample Rate Setting**: Override to 22–44 kHz for non-music.

## Lightmaps and probes

Lightmaps are textures and follow the same maths — see `vrchat-lighting-and-baking`. Non-Directional mode halves them; resolution × map count is the real driver. Reflection probes at 256 with HDR are quietly expensive; 64–128 is usually indistinguishable.

## Getting under the Quest 100 MB limit

Work top-down from the build report:

1. Clamp every Android texture to 1024 (many can go 512), ASTC 6×6.
2. Delete unused variants and duplicate textures — the same albedo imported twice ships twice.
3. Compress audio; stream music.
4. Drop lightmap resolution and switch to Non-Directional.
5. Strip mesh rig/blendshape data and enable mesh compression.
6. Remove the PC-only décor the Quest build does not need (a build-target-conditional object hierarchy, or a separate Quest scene).
7. Re-check: static batching's combined mesh is part of the bundle, so an over-eager static flag can silently add megabytes.
