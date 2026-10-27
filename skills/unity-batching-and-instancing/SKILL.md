---
name: unity-batching-and-instancing
description: Cut draw calls and SetPass calls in Unity Built-in RP and VRChat worlds - GPU instancing that will not batch, static vs dynamic batching, MaterialPropertyBlocks, atlasing, instancing shaders, DrawMeshInstanced and VRCGraphics.DrawMeshInstanced from Udon, Quest instancing. VRChat triage starts at vrchat-world-optimization; atlas UVs (uv-unwrapping); shared materials (blender-to-unity).
---

# Batching and GPU instancing (Unity Built-in RP)

The Built-in Render Pipeline has **no SRP Batcher**, so the tools are fewer materials, static batching, GPU
instancing and procedural drawing. Pick per class of object: a scene needs a mix, not one answer. VRChat worlds are
Built-in RP; what differs there is in references/vrchat-notes.md. For a whole VRChat world's performance triage,
start with the `vrchat-world-optimization` skill.

## Pick the mechanism

| Situation | Use |
|---|---|
| Level geometry that never moves, unique shapes | **Static batching** plus material atlasing |
| Static low-poly repeats (kit walls, floor tiles, trims under about 256 vertices) | **Static batching**: Unity advises against instancing meshes under 256 vertices. On Quest/iOS weigh the combined mesh's download size, and measure both |
| The same mesh many times at about 256 vertices or more (chairs, bottles, foliage clumps), or anything that moves or toggles | **GPU instancing** |
| Many static repeats that are lit by the bake (lamp posts, pillars) | **GPU instancing** when they reach about 256 vertices: lightmapped copies batch per lightmap texture (one lightmap, one batch), and probe-lit copies batch anywhere (small props usually are: vrchat-lighting-and-baking's 64 px rule). Static batching only for repeats under about 256 vertices, and on Quest/iOS it adds every copy's mesh to the download |
| Thousands of purely decorative copies, no per-copy components | **`Graphics.DrawMeshInstanced`** every frame (VRChat: `VRCGraphics.DrawMeshInstanced` from Udon) |
| Moving objects sharing a mesh and material | GPU instancing (dynamic batching is legacy and costs CPU) |
| Different meshes, same look | **Atlas the textures** into one material; then static batching works |

## GPU instancing: the rules that bite

Requirements:

1. Same **mesh** and same **material** (the same material asset, not a copy).
2. **Enable GPU Instancing** ticked on the material (`material.enableInstancing = true`).
3. A shader with an instancing variant: Standard, Standard (Specular) and every surface shader have one; a
   vertex/fragment shader needs `#pragma multi_compile_instancing` and the instance-ID macros
   (references/instanced-shader.md). Shader Graph has a Built-In target in Unity 2022.3: check that its output
   instances. Standard, Standard (Specular) and VRChat's Standard Lite instance only the transform (Unity: "no
   per-instance properties other than the transform"), so a per-copy `_Color` in a MaterialPropertyBlock breaks
   instancing on them. For per-copy colour use an instancing shader (`scripts/InstancedUnlit.shader`, the surface
   shader in references/instanced-shader.md), or one material per variant (each still instances).
4. Mesh Renderers only: Skinned Mesh Renderers are never instanced.

What silently disables it:

- **Static batching wins.** A renderer that is Batching Static and gets statically batched is never instanced, even
  with an instancing shader. Pick one per object.
- **A MaterialPropertyBlock with a non-instanced property.** Unity: "Don't put non-instanced properties in the
  MaterialPropertyBlock, because this disables instancing." Per-instance values go inside
  `UNITY_INSTANCING_BUFFER_START/END` with `UNITY_DEFINE_INSTANCED_PROP`.
- **Different lightmaps.** Lightmapped renderers instance only when they bake into the same lightmap texture (each
  one's lightmap scale and offset is per-instance data; the lightmap texture is not). Unity: each instance takes its
  GI from "Any number of Light Probes", "One lightmap" or one Light Probe Proxy Volume.
- **Realtime pixel lights.** Each extra per-pixel light adds a forward-add pass per object, and Standard's forward-add
  pass has no instancing variant: every lit object draws on its own (measured 2026-10-16: one point light took a view
  from 9 to 18 SetPass calls). Bake.
- **Material variants.** Two materials that differ in one float are two SetPass calls: merge them and drive the
  difference with an instanced property, on a shader that declares it per instance. On Standard, Standard
  (Specular) or Standard Lite keep the variants: each material still instances.
- **Batch size.** Instances per batch are capped by the constant buffer (500 by default); `Graphics.DrawMeshInstanced`
  draws at most **1023 per call**.

## Verify, never assume

1. Play mode -> Stats panel: SetPass calls first, then Batches, then Saved by batching.
2. Frame Debugger: instanced draws read `Draw Mesh (instanced)` with an instance count. Select any draw and read "Why
   this draw call can't be batched with the previous one": it names the reason (different material, different
   lightmap, MaterialPropertyBlock, shadow settings, ...).
3. Fix the reason it names, not the one you assumed.

With Unity MCP: `execute_code` to group renderers by (mesh, material, lightmapIndex, static flags); the groups show
which clusters could instance and what blocks them. `manage_profiler` for before and after numbers.

## Static batching

- Unity combines the static meshes into shared vertex and index buffers at build time, then draws the visible objects
  with almost no state changes between them. **Per-object frustum and occlusion culling still work**: merging meshes
  by hand is what loses them.
- The cost is memory and download: every GameObject gets its own copy of a shared mesh in the combined buffer (a dense
  forest of one tree mesh multiplies it), and the combined mesh ships in the build. On Quest/iOS that can outweigh the
  draw calls saved: check the build size both ways, and instance the dense repeats instead.
- Up to 64000 vertices per batch; statically batched objects cannot move.
- LTCGI turns static batching off on its receivers on purpose ("By default, LTCGI disables static batching on
  LTCGI-enabled receivers during the bake", https://ltcgi.dev/Advanced/Shadowmaps): count those receivers' draw
  calls, and see the `vrchat-lighting-and-baking` skill before re-enabling it.

## Dynamic batching

Legacy CPU-side vertex merging: meshes up to 300 vertices and 900 vertex attributes (180 vertices with UV1 and
tangents), lightmapped objects only when they point to the same lightmap location, and only the first pass of a
multi-pass shader. On modern hardware its CPU work often costs more than the draw calls it saves: leave it off unless
a profile proves otherwise.

## Atlasing: the highest-leverage move

Most prop-built scenes are material-bound, not triangle-bound. Twenty prop textures in one 2048 atlas turn 20 SetPass
calls into 1 and make static batching possible.

- Atlas by group and locality (one atlas per room or kit), not everything into one: a global atlas loads every
  texture for one visible prop.
- Keep the lightmap UV2 intact when re-laying out UV0.
- Pack metallic (R) and smoothness (A) into the one Standard metallic map instead of separate grey maps.
- Atlas at authoring time in Blender, so the asset stays the source of truth: packing several pieces' UVs into one
  texture is the `uv-unwrapping` skill (its shared-atlas layout); the shared materials and the export are
  `blender-to-unity`.

## Drawing instances procedurally

`Graphics.DrawMeshInstanced` draws up to **1023 matrices per call** and must be called every frame. Its copies are
culled as one group, never one by one, so a thousand of them behind a wall still cost their vertex work. Unity 2022.3's
documentation recommends `Graphics.RenderMeshInstanced` in its place; Udon has only `VRCGraphics.DrawMeshInstanced`:
references/udon-drawmeshinstanced.md, with a working UdonSharp script in `scripts/InstancedField.cs` and a matching
shader in `scripts/InstancedUnlit.shader`. They scatter on a flat plane, vary only yaw and tint, and draw unlit and
opaque: grass on a terrain needs heights sampled at edit time, scale jitter and a lit cutout instancing shader (same
reference, What the example does not do).

## Decision checklist for a new prop set

1. How many copies? 1-3: do not bother. Thousands, purely decorative: DrawMeshInstanced.
2. Does it move or toggle, or reach about 256 vertices? Instancing. Static and under about 256 vertices: static
   batching, which is cheaper at runtime but dearer in memory and download (check the Quest/iOS build size).
3. Lit by the bake? Probe-lit copies instance anywhere; lightmapped copies instance per lightmap texture, so fewer,
   fuller lightmaps mean fewer batches.
4. Should each copy look different? On a shader that declares them per instance (InstancedUnlit, the surface
   shader in references/instanced-shader.md): instanced properties (colour, tint, UV offset). On Standard, Standard
   (Specular) or Standard Lite: one material per variant, since an MPB `_Color` there breaks instancing.
5. Measure in the Frame Debugger and record the numbers.

## Sources (checked 2026-10-17)

| Facts | Source |
|---|---|
| Instancing requirements, lightmaps, the 256-vertex advice | https://docs.unity3d.com/2022.3/Documentation/Manual/GPUInstancing.html |
| Shader macros, surface shaders, the MaterialPropertyBlock rule, 500 per batch | https://docs.unity3d.com/2022.3/Documentation/Manual/gpu-instancing-shader.html |
| Static batching wins over instancing | https://docs.unity3d.com/2022.3/Documentation/Manual/optimizing-draw-calls.html |
| Static batching memory, 64000 vertices | https://docs.unity3d.com/2022.3/Documentation/Manual/static-batching.html |
| Static batching draws only the visible objects | https://docs.unity3d.com/2019.4/Documentation/Manual/DrawCallBatching.html |
| Dynamic batching limits | https://docs.unity3d.com/2022.3/Documentation/Manual/dynamic-batching.html |
| DrawMeshInstanced: 1023 per call, group culling, RenderMeshInstanced | https://docs.unity3d.com/2022.3/Documentation/ScriptReference/Graphics.DrawMeshInstanced.html |
| Standard's forward-add pass has no instancing pragma | Unity's built-in shader source, Standard.shader (FORWARD_DELTA pass) |
