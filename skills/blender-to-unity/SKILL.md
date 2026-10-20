---
name: blender-to-unity
description: Blender to Unity FBX export and import - models arriving 100x too big or rotated X -90/270, faceted shading after import, missing LOD or collision meshes, stray .fbm or Materials folders, unshared materials, kit pieces to package as prefabs. Export settings, headless batch export, a Unity import postprocessor, prefab variants, LODs, colliders, mesh audit, VRChat notes. For kit .blend structure see blender-kit-library, layout sync blender-unity-placement-sync, UVs uv-unwrapping.
---

# Blender to Unity

Performance is decided in Blender, before Unity sees anything: how geometry is split, how many materials it uses,
whether copies are identical, and whether UV2 exists. Fixing those in Unity is always worse. Every exporter and
importer setting, with sources, is in `references/fbx-export.md`; folders, prefabs and materials in Unity are in
`references/unity-packaging.md`. This page is the order of work and the rules.

## Do this, in order

1. **Structure.** One collection per kit piece (`blender-kit-library`): the render mesh named after the piece, or
   `<Piece>_LOD0`, `<Piece>_LOD1`, `<Piece>_LOD2` as siblings, plus an optional `<Piece>_COL` collision shell.
2. **Hygiene.** Apply transforms (kit pieces: every object at identity, origin at the piece pivot), work through
   "Mesh hygiene" below, then run `scripts/mesh_audit.py`.
3. **UVs.** UV0 for textures; an authored UV2 on every kit render mesh, LODs included (probe-lit props too: cheap,
   and it keeps Scale In Lightmap open). `uv-unwrapping` owns how.
4. **Materials.** One per visual family, named `M_<FAMILY>_<Name>` exactly as the Unity material will be named.
5. **Export.** `scripts/batch_export_fbx.py -- --kit` (Scripts below); the settings are its own, documented row by
   row in `references/fbx-export.md`.
6. **Check in Blender.** Re-import into an empty scene with `bake_space_transform=True`: every mesh present, rotation
   0, scale 1, sizes equal to the piece (`references/fbx-export.md`, "Sanity tests").
7. **Package in Unity.** Install `scripts/unity/Editor/KitImport.cs` once, copy each FBX to
   `Assets/World/Kits/<FAMILY>/<Piece>/`, create the prefab variants and static flags
   (`references/unity-packaging.md`, "Order of work").
8. **Check in Unity.** `KitImport.KitImportTool.Check()`: settings, materials, collision, roots at identity, one
   variant per FBX.

## Kit piece or one-off asset

| | Kit piece (`<FAMILY>_<Type>_<Size>_<Variant>`) | One-off asset (a hero prop, a kitbash import) |
|---|---|---|
| Export | `batch_export_fbx.py --kit`: one FBX per piece collection, hidden members included | the script's `object` or `collection` mode on the selection |
| Path Mode | Strip: the FBX carries no textures | Copy with Embed Textures off: it brings its own textures |
| Material | the family's shared `M_<FAMILY>_*` in `<FAMILY>/_Shared/`, remapped by name | its own, in its own folder |
| UV2 | authored in Blender on every render mesh (LOD1+ too: the Progressive Lightmapper gives each LOD its own lightmap space at half the texel scale per level, so pack a LOD's UV2 gaps for that smaller footprint; measured 2026-10-17 in Unity 2022.3.22f1); Generate Lightmap UVs off | authored, or Unity's Generate Lightmap UVs with Margin Method Calculate |
| Unity folder | `Assets/World/Kits/<FAMILY>/<Piece>/` (KitImport.cs applies the settings) | outside `Kits/`: set the import settings by hand |
| Prefab | a variant of the FBX, root at identity | the same |

## Conventions

| Thing | Rule |
|---|---|
| Units | 1 Blender unit = 1 m = 1 Unity unit, scene Unit Scale 1.0. Model at real-world scale: a door is about 2 m |
| Axes | Blender Z up, -Y forward -> Unity Y up, +Z forward. Export -Z Forward and Y Up (the defaults) plus Bake Space Transform on (not the default): Unity = (-x, z, -y) and every root arrives at rotation 0 |
| Transforms | Apply rotation and scale (`Ctrl+A`) before export: unapplied scale is the root of most size and lighting surprises. Kit pieces apply location too: every object at identity with its origin at the piece pivot (the batch export warns, and `KitImport` `Check()` flags an offset child) |
| Origins | Grid pieces: the bottom-left corner of the footprint. Free pieces: floor centre for props, hinge for doors (the full list is in `blender-kit-library`) |
| Naming | Stable names: prefab references, material remaps and placement sync all key on them |
| Modularity | Pieces on a grid (0.25, 0.5 or 1 m) so copies snap and stay identical: identical meshes are what Unity can instance |

## Mesh hygiene

- Merge by distance, recalculate normals outside, delete interior faces nobody sees.
- The export triangulates (`use_triangles`), splitting each face of 4+ corners its own way. That changes custom
  normals (measured on Blender 5.2.2: a weighted-normal panel 10.4 deg off flat after export) and can pick the other
  diagonal of a non-planar quad. So a piece with custom normals (Weighted Normal, Harden Normals) or non-planar faces
  arrives already triangulated in its modifier stack (`blender-mesh-topology` gives the stack). `batch_export_fbx.py`
  warns about custom normals on quads; `mesh_audit.py` also counts non-planar faces.
- Shade smooth where a surface should read smooth: plain Shade Smooth on a piece without a hard-surface stack (Shade
  Auto Smooth adds a Smooth by Angle modifier, pinned last). A piece with the stack (a Weighted Normal, a Bevel with
  Harden Normals, or custom normals) follows `blender-mesh-topology`: Shade Smooth, a Smooth by Angle only first in
  the stack, never Shade Auto Smooth on top (it moved such normals 30-42 deg, measured on Blender 5.2.2). Faceting in
  Unity comes from flat-shaded faces, not from the FBX smoothing option.
- No n-gons on lightmapped faces, no loose vertices or edges.
- Remove unused material slots: every used slot is a submesh and a draw call in Unity.
- Decimate detail no player gets close to; a 40k-triangle bolt is a real thing people ship.
- Layout problems (fans, poles, pinching, a lower count without losing the look): `blender-mesh-topology`.

## UV channels

| Channel | Blender | Purpose |
|---|---|---|
| UV0 | first UV map | Textures; may overlap and tile |
| UV2 | second UV map | Lightmaps: inside 0-1, no overlap, gaps of at least 2 texels between charts and 1 texel to the tile edge at the piece's own lightmap footprint. Pack gap g = 2 / (texels_per_m x sqrt(A) x Scale In Lightmap x 0.5^n), A the mesh's area in m2, n its LOD level. `vrchat-lighting-and-baking` sets texels_per_m, `uv-unwrapping` packs it |

How to unwrap and pack either channel, padding and texel density: `uv-unwrapping` (or `rizomuv-uv-pipeline` when
RizomUV is installed). Lightmap resolution and bake settings: `vrchat-lighting-and-baking`.

## Materials and atlasing

Material count drives SetPass calls more than triangle count drives anything.

- One material per visual family, not per object: a room kit lands on 1-3 materials.
- Atlas per room or per kit, never globally: a global atlas loads every texture to show one prop. Packing several
  pieces into one atlas is `uv-unwrapping`; texture formats and sizes, `vrchat-texture-and-vram`.
- Unity's Standard shader (VRChat PC): one `_MetallicGlossMap` with metallic in R and smoothness (1 - roughness) in
  A; occlusion is its own map. Never a glTF-style ORM map for Standard.
- Keep material slot order stable between exports: submesh indices, and anything set per submesh in Unity, follow it.

## Splitting geometry: the culling trade-off

One giant mesh is one draw call and no culling; a thousand tiny meshes cull perfectly and cost a thousand draw calls.
Aim between:

- Split by **room, volume or occlusion cell**, so an unseen region can be culled whole.
- Keep repeated props as **separate, identical** pieces: they instance; merged copies do not. Unity's static batching
  keeps per-object culling (its cost is memory and download); hand-merging meshes loses it.
- Separate anything that toggles, moves or is interactive.
- Big flat surfaces (floors, walls) as their own objects, for lightmap-resolution control.

## LODs and collision

- LODs: `<Piece>_LOD0`, `<Piece>_LOD1`, `<Piece>_LOD2` as siblings in the piece collection; Unity builds the LOD Group
  from the `_LODn` suffixes on import ("Importing LOD Meshes", Unity 2022.3:
  https://docs.unity.cn/Manual/importing-lod-meshes.html, checked 2026-10-17). Decimate (Collapse) to about 50% and
  20% of LOD0, then fix LOD1's silhouette by hand. Worth it for hero props, foliage and pieces repeated dozens of
  times; overkill for a wall.
- Collision: prefer Unity primitive colliders (box, capsule), cheapest by far. Where a mesh collider is needed, model
  a low-poly shell `<Piece>_COL` in the piece collection: it exports with the piece and KitImport.cs turns it into a
  MeshCollider without a renderer. Never let the detailed render mesh be the collider.

## Scripts

| Script | Host | Use |
|---|---|---|
| `scripts/batch_export_fbx.py -- --kit --dir <dir> [--set-status]` | Blender 4.2+, headless: `blender -b --factory-startup KIT_<Name>.blend --python-exit-code 1 --python batch_export_fbx.py -- ...` (without `--python-exit-code 1` a failed export still exits 0) | One FBX per piece collection into `<dir>/<FAMILY>/<Piece>.fbx`, every member mesh (hidden ones too) with modifiers applied, Path Mode Strip; prints each file's objects, and warns about custom normals on quads, which the exporter would re-triangulate. `<dir>`: absolute, `//`-relative to the .blend (`//../../export/fbx` from `blender/kits/`), or relative to the current directory. `--set-status` writes `kit_status = "exported"` and saves the KIT file without a .blend1. A single MASTER (`blender-kit-library`'s default layout) holds every family, so export a family from a work file checked out of it (`checkout`) and set the status in MASTER through the MCP (never `--set-status` on a MASTER someone has open) |
| `scripts/batch_export_fbx.py` (`MODE`) | Blender Text Editor or Blender MCP | The selection: `object`, `collection` or `single`; set `EXPORT_DIR`, `MODE` and `PATH_MODE` at the top |
| `scripts/mesh_audit.py` | Blender, headless: `blender -b --factory-startup file.blend --python-exit-code 1 --python mesh_audit.py` | Per mesh, evaluated as the kit export evaluates it (excluded and outside-scene collections included, and in a MASTER or ASM the meshes inside instanced collections, flagged `instanced`): triangles, slots, UV maps (UV2 on everything but `_COL`), n-gons, loose geometry, custom normals on quads, unapplied rotation or scale; render triangles including collection instances, and the instancers Blender does not show (hidden, or in hidden or excluded collections), left out of the total; hidden or excluded objects never count as shown. The total is what Blender shows: Unity gets every instancer, since placement sync ships hidden and excluded ones too |
| `scripts/unity/Editor/KitImport.cs` | Unity 2022.3 editor | Import settings, material remap and `_COL` colliders for `Assets/World/Kits/`; `CreateVariants()`, `SetStaticFlags()`, `Check()` |

Through Blender MCP: `get_addon_status` and `get_scene_info` first; run a script with `execute_blender_code` (put
`BATCH_EXPORT_NO_MAIN = True` in the namespace to load `export_kit()` without exporting the selection); look at the
result with `look`.

## VRChat notes

VRChat worlds are Unity 2022.3.22f1 with the Built-in Render Pipeline
(https://creators.vrchat.com/sdk/upgrade/current-unity-version/), and VRChat's servers reject uploads from Unity 6
(https://ask.vrchat.com/t/developer-update-25-june-2026/48618); both checked 2026-10-17. Never advise an upgrade. Every
rule here applies. What differs: mobile builds (Android and iOS) have tighter texture, triangle and download budgets
(`vrchat-world-optimization`, `vrchat-texture-and-vram`), and scene setup, layers and upload are
`vrchat-world-sdk-setup`.

## Common pitfalls

| Symptom in Unity | Cause | Fix |
|---|---|---|
| 100x or 0.01x size, or scale 100 on the root | Scale not applied, or Apply Scalings left at All Local with Bake Space Transform off | Apply scale; export with FBX All |
| Root (single mesh) or every child (several meshes) reads rotation X -90 or 270, mesh looks right | Exported with Bake Space Transform off | Re-export with it on; Unity's Bake Axis Conversion does not fix it |
| Lies on its side or faces the wrong way | Rotation not applied, or non-default axis settings | Apply rotation; -Z Forward, Y Up |
| Faceted or blocky shading | Faces flat-shaded in Blender, or Unity Normals set to Calculate with a low Smoothing Angle | Shade Smooth in Blender (a piece with a hard-surface stack: `blender-mesh-topology`); Normals: Import |
| Gradients across flat panels, or chamfers shading differently than in Blender | Custom normals on quads, re-triangulated by the exporter | Triangulate in the stack before the Weighted Normal (or after Harden Normals, Keep Normals on): `blender-mesh-topology` |
| Inside-out faces | Negative scale, or flipped normals | Apply scale, recalculate outside |
| Lightmap garbage | UV2 missing, overlapping or unpadded | Author UV2 (`uv-unwrapping`) |
| A LOD or collision mesh missing from the FBX | Exported as a selection: Blender cannot select hidden objects | `batch_export_fbx.py --kit` exports the whole piece collection |
| `.fbm` folders or `Materials/` beside the FBX files | Path Mode Copy, or materials extracted | Strip for kit pieces; KitImport.cs keeps materials embedded and remapped |
| Materials re-shuffle on reimport | Material slot order changed in Blender | Keep slot order stable |
| Extra empties, cameras or lights in the prefab | Object Types not limited to Mesh | Mesh only |
| Identical pieces do not instance | Different prefabs or materials, Batching Static on, or GPU instancing off | One prefab per piece, shared material with instancing on: `unity-batching-and-instancing` |
