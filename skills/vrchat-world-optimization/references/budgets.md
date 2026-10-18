# VRChat world performance budgets

Practical targets, not SDK-enforced limits, unless marked **hard**. Mobile means Android (Quest) and iOS: VRChat applies
its Android/Quest guidelines to iOS (https://creators.vrchat.com/platforms/iOS/). Re-verify platform limits against
https://creators.vrchat.com/platforms/android/quest-content-optimization/ (checked 2026-10-17): VRChat tightens these
over time. VRChat's MB is 2^20 bytes (Worlds SDK 3.10.5 `ValidationHelpers.BYTES_TO_MB = 1048576`).

## Hard limits enforced by VRChat

| Limit | Value |
|---|---|
| iOS and Android/Quest world download size | **100 MB after build-time compression** (104,857,600 bytes); the SDK refuses the upload above it |
| Post-processing on mobile worlds | disabled |
| Cloth on mobile worlds | disabled |
| PC world download size | no SDK limit; VRChat asks public worlds to stay under 200 MB (https://creators.vrchat.com/worlds/submitting-a-world-to-be-made-public) |

## Geometry

| Metric | PC target | Mobile target |
|---|---|---|
| Total world triangles | 500k-1M (scene dependent) | ~250k |
| Triangles visible in one view | < 300k | < 100k |
| Skinned meshes in the world | avoid; animate transforms instead | avoid |
| LOD groups | hero props, foliage, dense repeated pieces seen from far away | same, more aggressive |

Avatars consume the rest of the frame. A crowded instance can add 20 x 70k triangles plus hundreds of draw calls you
do not control. That is why world budgets look small.

## Draw calls

| Metric | PC target | Mobile target |
|---|---|---|
| SetPass calls (Stats panel, empty instance) | < 150 | < 50 |
| Batches | < 400 | < 150 |
| Unique materials in scene | < 60 | < 25 |

SetPass calls (shader and material state changes) cost far more than batches. Two batches sharing one material are
cheap; two batches with two materials are not.

## Textures and memory

| Metric | PC | Mobile |
|---|---|---|
| Max texture dimension | 2048 (4096 for one hero surface) | 1024, on both the Android and the iOS override |
| Total texture VRAM | < 1.5 GB | < 150 MB |
| Lightmap size, max (px per map; not Unity's Lightmap Resolution, which is texels per metre) | 2048, only in a PC-only world; few maps | 1024, non-directional. One bake serves every platform, so a world that ships to Quest or iOS uses this size on PC too |
| Reflection probe resolution | 128 (256 for a hero probe) | 64-128 |

## Lighting

| Metric | PC | Mobile |
|---|---|---|
| Light mode | Baked; Mixed + Shadowmask only in a PC-only world that needs realtime sun shadows | Baked: a cross-platform world shares one bake |
| Realtime per-pixel lights on static geometry | at most 1 realtime per-pixel light at a time (PC-only worlds) | 0: bake every light. VRChat documents Standard Lite and Lightmapped as not supporting realtime lighting; Standard Lite's source still draws the main directional light, unshadowed |
| Realtime shadow casters | few, short distance, only in a PC-only world | none |
| Dynamic objects and avatars | light probes always; VRC Light Volumes in addition, for shaders that read them | light probes (the VRChat mobile shaders and Quest avatars read only probes) |

## Audio

- Vorbis compression; Compressed In Memory for short clips, Streaming for music.
- Force Mono for 3D positional sources: half the size, no audible difference at distance.
- Sample-rate override 22-44 kHz for ambience and SFX.

## Udon and network

Source: https://creators.vrchat.com/worlds/udon/networking/network-details/ (checked 2026-10-17).

| Metric | Limit |
|---|---|
| Total Udon network throughput | about 11 KB/s outbound per client |
| Manual sync payload | about 280 KB (280,496 bytes) per serialization, rate-limited by size: large payloads go out slowly |
| Continuous sync payload | about 200 bytes per serialization |
| `Update()` behaviours in the scene | as near zero as the design allows |

## What actually fills the download

In order: oversized or uncompressed textures, audio imported as PCM or ADPCM, lightmaps (resolution x map count),
meshes without mesh compression or with unused rig and blend-shape data, and static batching's combined meshes.
Read/Write on meshes and textures costs memory, not download.
