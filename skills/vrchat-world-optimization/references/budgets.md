# VRChat world performance budgets

Practical targets, not SDK-enforced limits, unless marked **hard**.
Re-verify platform limits against https://creators.vrchat.com/platforms/android/quest-content-optimization/ — VRChat tightens these over time.

## Hard limits enforced by VRChat

| Limit | Value |
|---|---|
| Android/Quest world download size | **100 MB after build-time compression** |
| Android/Quest avatar download size | 10 MB after compression |
| Post-processing on Android worlds | disabled |
| Cloth on Android worlds | disabled |

## Geometry

| Metric | PC target | Quest target |
|---|---|---|
| Total world triangles | 500k–1M (scene dependent) | ~250k |
| Triangles visible in one view | < 300k | < 100k |
| Skinned meshes in the world | avoid — animate transforms instead | avoid |
| LOD groups | hero props, foliage, repeated kit pieces | same, more aggressive |

Avatars consume the rest of the frame. A crowded instance can add 20 × 70k triangles plus hundreds of draw calls you do not control. That is why world budgets look small.

## Draw calls

| Metric | PC target | Quest target |
|---|---|---|
| SetPass calls (Stats panel, empty instance) | < 150 | < 50 |
| Batches | < 400 | < 150 |
| Unique materials in scene | < 60 | < 25 |

SetPass calls (shader/material state changes) cost far more than batches. Two batches sharing one material are cheap; two batches with two materials are not.

## Textures and memory

| Metric | PC | Quest |
|---|---|---|
| Max texture dimension | 2048 (4096 for one hero surface) | 1024 |
| Total texture VRAM | < 1.5 GB | < 150 MB |
| Lightmap resolution | 1024–2048, few maps | 512–1024, non-directional |
| Reflection probe resolution | 128 (256 for a hero probe) | 64–128 |

## Lighting

| Metric | PC | Quest |
|---|---|---|
| Realtime per-pixel lights on static geometry | 0–1 | 0 |
| Realtime shadow casters | few, short distance | none |
| Lighting mode | Baked / Mixed Shadowmask | Baked, Subtractive |
| Dynamic-object lighting | VRC Light Volumes preferred over probes | Light Volumes (mobile variant) or probes |

## Audio

- Vorbis compression; `Compressed In Memory` for short clips, `Streaming` for music.
- Force Mono for 3D positional sources — halves size, inaudible difference at distance.
- Sample-rate override 22–44 kHz for ambience and SFX.

## Udon / network

| Metric | Limit |
|---|---|
| Total Udon network throughput | ~11 KB/s |
| Manual sync payload | ~280 bytes per serialization (bigger payloads are rate-limited harder) |
| Continuous sync payload | ~200 bytes per serialization |
| `Update()` behaviours in the scene | as near zero as the design allows |

## What actually fills the download

In order: oversized/uncompressed textures, audio imported as PCM or ADPCM, lightmaps (resolution × map count), meshes with Read/Write enabled or unused rig/blendshape data, and static-batching combined meshes.
