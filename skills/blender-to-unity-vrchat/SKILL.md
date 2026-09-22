---
name: blender-to-unity-vrchat
description: Author and export world geometry from Blender to Unity for VRChat - scale and axis conventions, FBX export settings, applied transforms, UV0 vs lightmap UV2, texture atlasing, modular kits, LOD chains, collision meshes, batch export and mesh auditing scripts. Use when assets come into Unity at the wrong size or rotation, when preparing meshes for baking or instancing, when building a modular kit, or when setting up a repeatable Blender to Unity export pipeline.
---

# Blender → Unity (VRChat worlds)

Performance is decided in Blender, before Unity sees anything: how geometry is split, how many materials it uses, whether copies are identical, and whether UV2 exists. Fixing those in Unity is always worse.

## Conventions to get right once

| Thing | Rule |
|---|---|
| Units | Blender scene unit = 1 m = 1 Unity unit. Model at real-world scale; a door is ~2 m |
| Axes | Blender Z-up / -Y forward → Unity Y-up / Z forward. The FBX exporter's defaults (`-Z` forward, `Y` up) handle this |
| Transforms | **Apply rotation and scale** (`Ctrl+A`) before export. Non-applied scale is the root of most weirdness |
| Origins | Put the origin where the object is placed or pivots from — floor centre for props, hinge for doors |
| Naming | Descriptive and stable; Unity prefab references break when you rename meshes |
| Modularity | Model kit pieces on a grid (0.25 m / 0.5 m / 1 m) so copies snap and stay *identical* — identical meshes are what makes GPU instancing possible |

## Mesh hygiene before export

- Merge by distance, recalculate normals outside, delete interior faces nobody sees.
- Triangulate (modifier, or `use_triangles` on export) so Unity's triangulation matches what you previewed.
- Shade Auto Smooth / custom normals where needed, and export with `mesh_smooth_type='FACE'` so smoothing survives.
- No n-gons on anything that deforms or gets lightmapped.
- Remove unused material slots — each slot is a submesh and a draw call in Unity.
- Decimate detail that no player gets close to; a 40k-triangle bolt is a real thing people ship.

## UV channels

| Channel | Blender slot | Purpose |
|---|---|---|
| UV0 | first UV map | Textures. May overlap and tile freely |
| UV2 | second UV map | **Lightmaps.** No overlap, inside 0–1, padded |

Author UV2 for hero geometry rather than letting Unity generate it — `scripts/lightmap_uv2.py` adds and packs a second channel over a selection with consistent margins. Rules and symptoms: `../vrchat-lighting-and-baking/references/lightmap-uvs.md`.

## Materials and atlasing

Material count drives SetPass calls more than triangle count drives anything.

- One material per *visual family*, not per object. A room kit should land on 1–3 materials.
- Atlas per room / per kit, not globally — a global atlas loads every texture to show one prop.
- Channel-pack roughness/metallic/AO into one image (see `vrchat-texture-and-vram`).
- Keep material slot order stable between exports, or Unity re-assigns materials on reimport.

## Splitting geometry: the culling trade-off

One giant mesh = 1 draw call and zero culling. A thousand tiny meshes = perfect culling and a thousand draw calls. Aim between:

- Split by **room / volume / occlusion cell**, so an unseen region can be culled whole.
- Keep repeated props as **separate, identical** objects — they instance; merged copies do not.
- Separate anything that toggles, moves or is interactive.
- Big flat surfaces (floors, walls) benefit from being their own object for lightmap-resolution control.

## LODs

Name children `Thing_LOD0`, `Thing_LOD1`, `Thing_LOD2` under a parent empty and Unity builds the LOD Group automatically on import. Use Decimate (Collapse) at roughly 50% and 20%, then fix the silhouette by hand on LOD1. Worth it for hero props, foliage and anything repeated dozens of times; overkill for a wall.

## Collision

Never let a detailed visual mesh be the collider.

- Prefer Unity primitive colliders (box, capsule) placed by hand — cheapest by far.
- Where a mesh collider is unavoidable, author a separate low-poly shell (`Thing_COL`), export it, and disable its renderer in Unity.
- Player-blocking geometry should be simple, convex-ish and slightly forgiving.

## FBX export settings

Full annotated table in `references/fbx-export.md`. The essentials:

```
Path Mode: Copy (+ embed off)
Include:   Selected Objects; Object Types = Mesh (+ Armature only if rigged)
Transform: Scale 1.0, Apply Scalings = "FBX All", -Z Forward, Y Up,
           Apply Unit = on, Use Space Transform = on, Bake Space Transform = off
Geometry:  Smoothing = Face, Apply Modifiers = on, Tangent Space only if normal-mapped
Animation: off for static world geometry
```

`Apply Scalings: FBX All` is what stops Unity showing a 100× or 0.01 scale on the transform.

## Batch export

`scripts/batch_export_fbx.py` exports each selected object (or each collection) to its own FBX with the settings above, named after the object, into a target folder — run it from Blender's Text Editor, or paste it through the Blender MCP `execute_blender_code`.

`scripts/mesh_audit.py` reports, per object: evaluated triangle count, material slots, UV channels, unapplied scale/rotation, n-gons and duplicate-mesh groups — the last one tells you which objects can share an instanced draw call.

## Working through Blender MCP

When the Blender MCP server is connected:

1. `get_addon_status()` then `get_scene_info()` first — never assume the Blender version or scene contents.
2. Look shader nodes up **by type**, not by name (`n.type == "BSDF_PRINCIPLED"`), because node names are localized.
3. Never hardcode enum identifiers; read them from RNA first.
4. After any change, `get_viewport_screenshot()` and `get_scene_info()` to confirm.
5. Paste the scripts in `scripts/` through `execute_blender_code` rather than re-deriving them.

## Common pitfalls

| Symptom in Unity | Cause |
|---|---|
| Object is 100× or 0.01× size | Scale not applied in Blender, or wrong Apply Scalings |
| Object lies on its side | Rotation not applied; or exported with non-default axis settings |
| Faceted/blocky shading | Smoothing exported as `Off`, or normals not imported |
| Inside-out faces | Negative scale on the object, or flipped normals |
| Lightmap garbage | UV2 missing, overlapping, or authored into UV0 |
| Materials re-shuffle every reimport | Material slot order changed in Blender |
| Extra empties/cameras/lights in the prefab | Object Types not restricted to Mesh on export |
| Identical props won't instance | Copies were joined, or each is a separate mesh datablock — use linked duplicates (`Alt+D`) |
