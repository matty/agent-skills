---
name: vrchat-world-optimization
description: Optimise, profile or audit a VRChat world (performance entry point) - low fps, too many draw calls or SetPass calls, VRAM blowout, long downloads, Quest, Android or iOS builds over 100 MB, budgets before building. Ranks the costs and routes to the owning skill (batching, lighting and mirrors, textures, Udon, Blender export, topology, UVs), which wins for its own settings. For whole builds from brief to upload see vrchat-world-orchestration.
---

# VRChat world optimization

VRChat worlds run on Unity 2022.3.22f1's **Built-in Render Pipeline**. Never advise a Unity upgrade: VRChat's Unity 6
build is a client beta, and its servers reject uploads from Unity 6. Two consequences dominate every decision:

- **There is no SRP Batcher.** Generic "SRP Batcher first" advice does not apply. Draw-call reduction here means static
  batching, GPU instancing and fewer materials.
- **You do not own the whole frame.** Avatars, mirrors and other players share it. A world that hits 90 fps empty and
  30 fps with 20 avatars has failed: budget for roughly half the frame. VRChat's own floor is at least 45 fps for one
  VR user at the spawn.

Mobile means Android (Quest) and iOS: VRChat applies its Android/Quest limits and guidelines to iOS too, so every
mobile number here covers both.

## Work in this order

Guessing wastes hours. Measure, fix the top cost, measure again.

### 1. Measure before touching anything

| Tool | What it answers |
|---|---|
| The headset's frame timing: SteamVR's frame timing on PC, Meta's OVR Metrics Tool on Quest | Real frametime, CPU vs GPU bound |
| VRChat's debug views in the client (Right Shift + ~ + number on desktop; Quick Menu > Settings > Toggle Debug UI in VR and on Quest) | Log (3), players and network (4, 6, 8) |
| Unity **Stats** panel (Game view, Play mode) | Batches, SetPass calls, tris, verts |
| Unity **Frame Debugger** | Every draw call, and why each one broke batching |
| Unity **Profiler** | CPU split: scripts, culling, rendering, physics |
| **VRWorld Toolkit > World Debugger** (Creator Companion, curated) | Over 90 checks and tips, plus a build-size report |
| The SDK Builder after a build | Download and uncompressed size, in VRChat's MB (2^20 bytes) |

With the Unity MCP server: `manage_profiler` for captures, `read_console` for warnings, `manage_editor` for Play mode,
`execute_code` to query renderers, materials and import settings in bulk rather than clicking through the Inspector.
Measuring from a script (the ClientSim camera mask, texture memory by storage size, a download estimate when there is
no build): `references/unity-mcp.md`.

**CPU-bound vs GPU-bound decides what to fix.** CPU-bound: draw calls, Udon, physics, animators. GPU-bound: overdraw,
shader cost, fill rate, realtime lights, mirrors, texture bandwidth.

### 2. Rank by cost, not by ease

Typical order of real wins in a VRChat world:

1. **Mirrors, cameras and video players.** A full-scene mirror roughly doubles render cost, so it starts off and is
   toggled by players; toggles, Reflect Layers and mirror occlusion: `vrchat-lighting-and-baking`. Video players stay
   off until used, at most 2 per room: "Bad things happen when you put more than 2 video players in a room."
2. **Realtime lights.** In forward rendering each per-pixel light adds a pass per lit object. Bake:
   `vrchat-lighting-and-baking`.
3. **Texture memory**, the usual cause of "stutters on load" and VRAM blowout: `vrchat-texture-and-vram`.
4. **Draw calls and material count**: `unity-batching-and-instancing`.
5. **Transparency and overdraw.** Stacked alpha-blended layers destroy mobile fill rate. Prefer opaque geometry; on
   Quest and iOS VRChat counts cutout as transparency too: use it only where opaque modelling cannot do the job, and
   never stacked.
6. **Udon**, 200x-1000x slower than compiled C#: `vrchat-udon`.
7. **Triangles**, usually the least important on PC: a 1M-triangle world with 30 draw calls beats a 200k one with
   900. Mobile still has a triangle budget (below).

### 3. Fix, re-measure, record

Change one class of thing at a time and write down before and after SetPass calls, frametime and download size, so a
later regression is obvious.

## Budgets

Full table in `references/budgets.md`. Starting points:

| | PC | Mobile: Quest / Android, iOS |
|---|---|---|
| World triangles | ~500k-1M workable | **~250k total** |
| SetPass calls | < 150 | < 50 |
| Max texture size | 2048 (4096 only for a hero surface) | **1024** (set on both the Android and the iOS override) |
| Download size | no SDK limit; VRChat asks public worlds to stay under 200 MB | **100 MB hard limit** (104,857,600 bytes) after compression |
| Realtime lights on static geometry | at most 1 realtime per-pixel light at a time (PC-only worlds) | 0: a cross-platform world bakes every light |
| Post-processing | budget carefully | **disabled by VRChat** |

VRChat's MB is 2^20 bytes: the SDK checks the mobile limit against 104,857,600 bytes and shows sizes in that unit.

## Routing

| Symptom / task | Skill |
|---|---|
| Too many draw calls, repeated props, GPU instancing, atlasing, `DrawMeshInstanced` | `unity-batching-and-instancing` |
| Lighting flat or slow, bake setup and lightmap resolution, light probes, VRC Light Volumes, LTCGI, reflection probes, occlusion culling, mirrors | `vrchat-lighting-and-baking` |
| VRAM, download size, compression formats, mipmaps, the 100 MB mobile limit | `vrchat-texture-and-vram` |
| Geometry coming out of Blender: scale, LODs, colliders, batch export | `blender-to-unity` |
| Structuring a modular kit across .blend files | `blender-kit-library` |
| Too many triangles in a mesh, bad shading, messy topology | `blender-mesh-topology` |
| UV layout, texel density, padding, lightmap UV2 authoring | `uv-unwrapping` (`rizomuv-uv-pipeline` to automate it with RizomUV) |
| Scripts, sync, networking, per-frame Udon cost | `vrchat-udon` |
| Scene descriptor, spawns, layers, pickups and other SDK components, testing, Android / iOS builds and upload prep | `vrchat-world-sdk-setup` |
| Layout moved in Unity and Blender out of step | `blender-unity-placement-sync` |
| A sign-off with a pass/fail verdict on a fix or a stage, with evidence (an audit without sign-off stays here) | `vrchat-world-qa` |
| Building or rebuilding a whole world end to end | `vrchat-world-orchestration` (it calls this skill for its final audit) |

## Rules of thumb that survive contact with reality

- **Never hand-merge the whole world into one mesh.** A merged mesh is culled as one object, so you trade 200 draw
  calls for drawing everything, every frame. Merge per room or locality.
- **Static batching is not free.** It keeps per-object culling, but its combined mesh ships in the build: more
  download and more memory. On mobile that can cost more than the draw calls it saves.
- **Occlusion culling pays in cellular layouts** (rooms, corridors), not in an open field or a single sealed room;
  occluder flags and bake settings: `vrchat-lighting-and-baking`.
- **LODs are for dense detail, not for everything.** Use them on hero props, foliage and dense repeated pieces seen
  from far away; give small clutter a LOD Group whose last level culls it.
- **Test on device as soon as a mobile build exists.** Quest and iOS behaviour is not predictable from the editor:
  Build & Test on the device (`vrchat-world-sdk-setup`) while the world is still cheap to change.
- **Run `references/audit-checklist.md` before every publish.**

## Sources (checked 2026-10-17)

- Unity version: https://creators.vrchat.com/sdk/upgrade/current-unity-version/ ; uploads from Unity 6 rejected:
  https://ask.vrchat.com/t/developer-update-25-june-2026/48618
- 45 fps at the spawn, under 200 MB, one mirror and at most 2 video players per room (page updated 2024-02-13):
  https://creators.vrchat.com/worlds/submitting-a-world-to-be-made-public
- Cutout counts as transparency ("As an aside, yes, 'alpha cutout' counts as transparency", updated 2026-09-15):
  https://creators.vrchat.com/platforms/android/cross-platform-setup/
- Mobile limits and budgets: https://creators.vrchat.com/platforms/android/quest-content-optimization/ ; iOS follows
  them: https://creators.vrchat.com/platforms/iOS/
- VRChat's MB and the 104,857,600-byte check: Worlds SDK 3.10.5, `ValidationHelpers` (read 2026-10-17)
- Debug views: https://creators.vrchat.com/worlds/udon/world-debug-views
- OVR Metrics Tool: https://developer.oculus.com/documentation/unity/ts-ovrmetricstool (redirects to Meta's current
  page)
- VRWorld Toolkit: https://github.com/oneVR/VRWorldToolkit
- Udon's cost: https://udonsharp.docs.vrchat.com/random-tips-&-performance-pointers
