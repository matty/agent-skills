---
name: unity-batching-and-instancing
description: Reduce draw calls in Unity Built-in Render Pipeline projects, especially VRChat worlds - GPU instancing, static and dynamic batching, MaterialPropertyBlocks, texture atlasing, and Graphics/VRCGraphics.DrawMeshInstanced from Udon. Use when draw calls or SetPass calls are too high, when repeated props should share one draw call, when instancing "is enabled but not working", or when deciding whether to merge meshes, atlas materials or instance.
---

# Batching and GPU instancing (Built-in RP / VRChat)

VRChat worlds are **Built-in Render Pipeline**. There is **no SRP Batcher**, so the tools are: fewer materials, static batching, GPU instancing, and drawing procedurally. Apply them per object class — a scene needs a mix, not one answer.

## Pick the right mechanism

| Situation | Use |
|---|---|
| Level geometry, never moves, unique shapes | **Static batching** + material atlasing, chunked per room |
| Same mesh repeated many times (chairs, bottles, bolts, foliage, kit pieces) | **GPU instancing** |
| Repeated meshes that must also be lightmapped | Instancing works **only if they bake into the same lightmap texture**; otherwise static-batch them |
| Thousands of copies, purely decorative, no per-object components | **`VRCGraphics.DrawMeshInstanced`** from Udon |
| Moving objects sharing a mesh and material | GPU instancing (dynamic batching is obsolete and CPU-expensive) |
| Different meshes, same look | **Atlas the textures**, then one material → static batching becomes possible |

## GPU instancing: the rules that actually bite

Requirements:
1. Same **mesh**, same **material** (same instance of the material asset, not a copy).
2. Material has **Enable GPU Instancing** ticked (`material.enableInstancing = true`).
3. Shader supports it: `#pragma multi_compile_instancing`, `UNITY_VERTEX_INPUT_INSTANCE_ID` in the structs, `UNITY_SETUP_INSTANCE_ID(v)` in the vertex shader. Standard, Standard (Specular) and most hand-written surface shaders do. **Shader Graph shaders do not work in Built-in RP at all.**
4. Mesh Renderers only — **Skinned Mesh Renderers are never instanced**.

What silently disables it:

- **Static batching wins.** If a renderer is marked Batching Static and gets statically batched, Unity disables instancing for it — even with an instancing shader. Instancing and "Batching Static" on the same object is a contradiction; pick one.
- **MaterialPropertyBlock with a non-instanced property.** Setting a property that is not declared inside the instancing constant buffer breaks the batch. Per-instance variation must be declared with `UNITY_INSTANCING_BUFFER_START/END` and `UNITY_DEFINE_INSTANCED_PROP` — see `references/instanced-shader.md`.
- **Different lightmaps.** Lightmapped statics instance only when they bake into the *same* lightmap texture (`unity_LightmapST` is part of the per-instance buffer, so differing UV scale/offset is fine, differing lightmap index is not).
- **Per-pixel realtime lights.** In forward rendering, each additional pixel light adds another pass per object, multiplying whatever you saved. Bake.
- **Material variants.** Two materials identical except for one float are two SetPass calls. Merge them and drive the difference with an instanced property.
- **Batch size.** Instances per batch are capped by the constant buffer (commonly ~500 with default per-instance data); `Graphics.DrawMeshInstanced` is hard-capped at **1023 per call**.

## Verify, never assume

1. Play mode → **Stats** panel: watch *SetPass calls* first, then *Batches*, then *Saved by batching*.
2. **Frame Debugger**: instanced draws appear as `Draw Mesh (instanced)` with an instance count. Select any draw call and read **"Why this draw call can't be batched with the previous one"** — it names the exact reason (different material, different lightmap, MPB, shadow settings, ...).
3. Fix the reason it names, not the reason you assumed.

With Unity MCP: `execute_code` to sweep the scene and report renderers grouped by (mesh, material, lightmapIndex, staticFlags) — that grouping immediately shows which clusters *could* instance and what is blocking them. `manage_profiler` for before/after numbers.

## Static batching, honestly

- It does **not** merge draw calls into one; it merges *state changes* by pre-combining geometry into a combined mesh with submeshes, so consecutive draws avoid mesh binding.
- The combined mesh is **baked into the build**: more download size, more memory. On Quest this can cost more than it saves — check the build report both ways.
- It breaks if the object moves (it cannot move), and it is incompatible with MaterialPropertyBlocks.
- **Chunk it.** Mark static per room or per district, not for the entire world, or you lose frustum and occlusion culling.

## Dynamic batching

Legacy CPU-side vertex merging, limited to small meshes (~300 vertices, fewer with tangents), uniform scale, no lightmap differences. It burns CPU to save draw calls and is usually a net loss on modern hardware. Leave it off unless a profile proves otherwise.

## Atlasing: the highest-leverage move

Most VRChat worlds are material-bound, not triangle-bound. Combining 20 prop textures into one 2048 atlas turns 20 SetPass calls into 1 and makes static batching viable.

- Atlas **by logical group and locality** (one atlas per room / per kit), not by flattening unrelated assets — a global atlas forces every texture into memory for a single visible prop.
- Keep lightmap UVs (UV2) intact when re-laying out UV0.
- Channel-pack metallic/roughness/AO into one texture rather than three.
- Do the atlasing at authoring time in Blender (`blender-to-unity-vrchat`) so the source of truth is the asset, not an editor script.

## Drawing instances from Udon

For large decorative counts where per-object GameObjects are wasteful, VRChat whitelists `VRCGraphics.DrawMeshInstanced`. It must be called **every frame**, is capped at **1023 matrices per call**, and Unity culls the group as a whole — individual instances are not frustum- or occlusion-culled. Full working pattern, including per-instance colors and the `_Udon` global-property rules, in `references/udon-drawmeshinstanced.md`.

## Decision checklist for a new prop set

1. How many copies? `1–3` → don't care. `4–100` → instancing or static batch. `100+` → instancing, or DrawMeshInstanced if purely decorative.
2. Does it move or toggle? Yes → instancing. No → static batching is usually cheaper at runtime, more expensive in build size.
3. Is it lightmapped? Force all copies into one lightmap, or accept static batching.
4. Does each copy need to look different? Instanced properties (color, tint, UV offset), not separate materials.
5. Measure in the Frame Debugger. Record the numbers.
