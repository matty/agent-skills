---
name: vrchat-world-optimization
description: Triage and fix performance problems in VRChat worlds built in Unity - framerate drops, high draw calls, VRAM blowout, long downloads, Quest/Android builds failing the 100 MB limit. Use when asked to optimize, profile or audit a world, when planning a performance budget before building, or when choosing between batching, atlasing, LODs, occlusion culling and baked lighting. Routes to the deeper skills for instancing, lighting, textures, Blender export and Udon.
---

# VRChat world optimization

VRChat worlds run on Unity's **Built-in Render Pipeline** (last verified editor: **2022.3.22f1**; a Unity 6 BiRP build has been in open beta — confirm against https://creators.vrchat.com/sdk/upgrade/current-unity-version/ before advising an upgrade). Two consequences dominate every decision:

- **There is no SRP Batcher.** Generic Unity optimization advice that starts with "SRP Batcher first" does not apply. Draw-call reduction here means static batching, GPU instancing, and fewer materials.
- **You do not own the whole frame.** Avatars, mirrors and other players share it. A world that hits 90 fps empty and 30 fps with 20 avatars is a failed world. Budget for roughly half the frame.

## Work in this order

Guessing wastes hours. Measure, fix the top cost, measure again.

### 1. Measure before touching anything

| Tool | What it answers |
|---|---|
| In-game debug overlays / `Meters` | Real in-headset frametime, CPU vs GPU bound |
| Unity **Stats** panel (Game view, Play mode) | Batches, SetPass calls, tris, verts |
| Unity **Frame Debugger** | Every draw call, and *why* each one broke batching |
| Unity **Profiler** | CPU split: scripts, culling, rendering, physics |
| **VRWorld Toolkit → World Debugger** | ~90 static checks plus a build-size report |
| SDK build report / editor log "statistics" | Real download size and per-asset contribution |

With the Unity MCP server connected: `manage_profiler` for captures, `read_console` for warnings, `manage_editor` for play mode, `unity_reflect` / `execute_code` to query renderers, materials and import settings in bulk rather than clicking through the Inspector.

**CPU-bound vs GPU-bound decides what to fix.** CPU-bound → draw calls, Udon, physics, animators. GPU-bound → overdraw, shader cost, fill rate, realtime lights, mirrors, texture bandwidth.

### 2. Rank by cost, not by ease

Typical order of real wins in a VRChat world:

1. **Mirrors and cameras** — a full-scene mirror roughly *doubles* render cost, and occlusion culling does not apply inside reflections. Off by default, player-toggled, auto-off on leaving the area, culling mask trimmed hard.
2. **Realtime lights** — in forward rendering each per-pixel light adds an extra pass per affected object. Bake instead → `vrchat-lighting-and-baking`.
3. **Texture memory** — the usual cause of "stutters on load / eats all my VRAM" → `vrchat-texture-and-vram`.
4. **Draw calls and material count** → `unity-batching-and-instancing`.
5. **Transparency / overdraw** — stacked alpha-blended layers destroy Quest fill rate; prefer opaque or cutout.
6. **Udon** — runs 200×–1000× slower than compiled C# → `udon-performance`.
7. **Triangles** — usually the *least* important item here. A 1M-tri world with 30 draw calls beats a 200k-tri world with 900.

### 3. Fix, re-measure, record

Change one class of thing at a time and write down before/after SetPass calls, frametime and download size, so a later regression is obvious.

## Budgets

Full table in `references/budgets.md`. Starting points:

| | PC | Quest / Android |
|---|---|---|
| World triangles | ~500k–1M workable | **~250k total** |
| SetPass calls | < 150 | < 50 |
| Max texture size | 2048 (4096 only for a hero surface) | **1024** |
| Download size | keep modest (~200 MB guidance) | **100 MB hard limit after compression** |
| Realtime lights on static geometry | 0–1 | 0 |
| Post-processing | budget carefully | **disabled by VRChat** |

## Routing

| Symptom / task | Skill |
|---|---|
| Too many draw calls, repeated props, GPU instancing, atlasing, `DrawMeshInstanced` | `unity-batching-and-instancing` |
| Lighting flat or slow, lightmap bake setup, light probes, VRC Light Volumes, LTCGI, reflection probes, occlusion culling | `vrchat-lighting-and-baking` |
| VRAM, download size, compression formats, mipmaps, the 100 MB Quest limit | `vrchat-texture-and-vram` |
| Geometry coming out of Blender: scale, UV2, LODs, colliders, modular kits, batch export | `blender-to-unity-vrchat` |
| Scripts, sync, networking, pickups, per-frame Udon cost | `udon-performance` |

## Rules of thumb that survive contact with reality

- **Never merge the whole world into one mesh.** It destroys frustum and occlusion culling — you trade 200 draw calls for drawing everything, every frame. Merge *per room / per locality*.
- **Static batching is not free.** It bakes a combined mesh into the build: more download size and more memory. On Quest that often costs more than the draw calls it saves.
- **Occlusion culling needs real occluders.** Mark walls and floors Occluder Static, props Occludee Static, and set a smallest-occluder size that matches the architecture. It does nothing inside mirrors.
- **LODs are for dense detail, not for everything.** Per-object LOD group overhead is real; use LODs on hero props and foliage, and per-layer cull distances for small clutter.
- **Test on device early.** Quest behaviour is not predictable from the editor. Build to hardware while the world is still cheap to change.
- **Run `references/audit-checklist.md` before every publish.**
