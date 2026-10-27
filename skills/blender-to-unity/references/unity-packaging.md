# Packaging kit pieces in Unity

How exported kit pieces land in a Unity 2022.3 project so each one can be found, swapped or deleted on its own while
architecture shares materials (and so draw calls). Pairs with the `blender-kit-library` skill on the Blender side.
`scripts/unity/Editor/KitImport.cs` does the mechanical part; this page says what it does, in what order, and what to
check.

## Folder layout

```
Assets/World/
  Editor/KitImport.cs           this skill's import script (any Editor folder works)
  Kits/<FAMILY>/
    _Shared/                    M_<FAMILY>_*.mat and the family's atlas, trim sheet or tiling textures
    <Piece>/                    one folder per piece
      <Piece>.fbx
      <Piece>.prefab            prefab variant of the FBX: the thing that gets placed
      M_<Piece>.mat, T_<Piece>_*.png    only if the piece has its own material (props)
  Assemblies/ASM_<Name>_<Variant>.prefab    one per ASM file, named after its collection (built by placement sync)
  PlacementSync/                the placement sync scripts (blender-unity-placement-sync)
  Scenes/
```

Deleting a piece is deleting its folder. Replacing one is re-exporting its FBX over the old one (same name, same
material slot order) and nothing else changes. Prefab and placement names must equal the Blender collection names:
placement sync matches them exactly.

## Order of work

1. Once per project: copy `scripts/unity/Editor/KitImport.cs` to `Assets/World/Editor/KitImport.cs`; with Unity MCP,
   `create_script`, `refresh_unity`, then `read_console` for compile errors.
2. Make the family materials in `<FAMILY>/_Shared/` (and a prop's own `M_<Piece>.mat` in its folder), named exactly
   like the Blender materials (`M_INT_Wallpaper` in both). Texture maps for Unity's Standard shader: `_MainTex`
   albedo, `_MetallicGlossMap` with metallic in R and smoothness (1 - roughness) in A, occlusion as its own map.
   `T_*_Normal` and detail normal maps import as Texture Type **Normal map** ("formats the texture asset so it's
   suitable for real-time normal mapping",
   https://docs.unity3d.com/2022.3/Documentation/Manual/texture-type-normal-map.html, checked 2026-10-27) and are
   never crunched (*practice*: crunch's block artefacts land on the shading and repeat in every tile); formats and
   sizes are `vrchat-texture-and-vram`'s.
   A material made by script (Unity MCP `execute_code`) also calls `EnableKeyword` for each feature it uses,
   `_NORMALMAP`, `_METALLICGLOSSMAP`, `_DETAIL_MULX2`, `_EMISSION`: only the material inspector sets them, and
   without them the assigned map is ignored ("you must enable that variant by using the EnableKeyword function",
   https://docs.unity3d.com/ru/2020.1/Manual/materials-scripting-standard-shader.html, checked 2026-10-18).
3. Copy each `export/fbx/<FAMILY>/<Piece>.fbx` to `Assets/World/Kits/<FAMILY>/<Piece>/`. On import KitImport.cs sets
   the Model tab as in `fbx-export.md`, remaps every material by name to the project material, turns
   `<Piece>_COL` into a MeshCollider without a renderer, and picks tangents (MikkTSpace only where a remapped
   material has a normal map). FBX files imported before their materials existed: `KitImport.KitImportTool.Reimport()`.
4. `KitImport.KitImportTool.CreateVariants()`: a `<Piece>.prefab` variant beside every FBX that has none, made in a
   preview scene so the open scene stays untouched.
5. Static flags per family: `KitImport.KitImportTool.SetStaticFlags("Assets/World/Kits/<FAMILY>/", flags)` sets them
   on every renderer of every variant, not only the root (a multi-mesh FBX keeps its renderers on children). Which
   flags: Contribute GI and Occluder/Occludee for architecture; Batching Static off for anything that should
   GPU-instance (`unity-batching-and-instancing`); lightmapped or probe-lit is `vrchat-lighting-and-baking`.
6. `KitImport.KitImportTool.Check()` and fix what it lists (next section).

## Materials: shared for architecture, self-contained for props

| Piece kind | Material lives in | Why |
|---|---|---|
| EXT, INT, STR, TRIM, ZONE | `<FAMILY>/_Shared/` | One material per family keeps SetPass calls down (`vrchat-world-optimization` budgets) |
| PROP, FOL with a unique texture | `<Piece>/` | Removing or replacing the prop takes its material and textures with it |
| PROP using a family atlas | `<FAMILY>/_Shared/` | Same reason as architecture |

The remap works only when the Blender material is called exactly what the Unity material is called. A material with
no match stays embedded in the FBX (Check reports it): create the material, then Reimport. Without KitImport.cs, the
same remap from Unity MCP `execute_code`, per FBX:

```csharp
var fbxPath = "Assets/World/Kits/<FAMILY>/<Piece>/<Piece>.fbx";       // the FBX to remap
var imp = AssetImporter.GetAtPath(fbxPath) as ModelImporter;
if (imp == null) return fbxPath + ": not a model";
imp.materialImportMode = ModelImporterMaterialImportMode.ImportViaMaterialDescription;
imp.materialLocation = ModelImporterMaterialLocation.InPrefab;
imp.SearchAndRemapMaterials(ModelImporterMaterialName.BasedOnMaterialName, ModelImporterMaterialSearch.Everywhere);
imp.SaveAndReimport();
return fbxPath + ": materials remapped by name";
```

`execute_code` compiles the body as a method returning `object` (with `using UnityEngine; using UnityEditor;` and a
few System namespaces), so every path returns a value.

## Prefabs

- `<Piece>.prefab` is a **prefab variant of the FBX model**. Reimporting the FBX flows into the variant, and anything
  added in Unity (LOD Group tweaks, static flags, Udon behaviours) lives on the variant and survives re-exports.
  Collision from `<Piece>_COL` is rebuilt on every import, so it follows the Blender shell.
- The prefab root keeps an identity transform: a placement tool positions the root, so an offset baked into the root
  moves every placement.
- Assemblies (`Assemblies/ASM_<Name>_<Variant>.prefab`) are prefabs whose children are kit prefab instances, built
  from the ASM file's placements by `blender-unity-placement-sync`, not by hand.

## Checks after a batch import (what `Check()` reports)

1. Every `<Piece>.fbx` has a `<Piece>.prefab` beside it that is a variant of it, and no prefab is left without its FBX.
2. No material embedded in an FBX where a project material should be, no `Materials/` folder beside an FBX, and one
   submesh per material slot.
3. Import settings as in `fbx-export.md`: Read/Write off, Generate Lightmap UVs off, no cameras or lights, Generate
   Colliders off, Animation Type None, materials not extracted; tangents present wherever a normal map is used.
4. Every model root, its children and every variant root at position 0, rotation 0, scale 1 (X -90 or 270 on the
   root of a single-mesh FBX, or on every child of a multi-mesh one: exported without Bake Space Transform); every
   render mesh has a UV2; every `_COL` has a MeshCollider and no renderer.

By eye: one instance per family at the origin, compared with a 1.6 m reference (Unity's default Capsule is 2 m tall:
scale it to Y 0.8). A grid piece's Blender bottom-left pivot is its +X/+Z corner in Unity, so its mesh runs into -X
and -Z; that is the `(-x, z, -y)` axis mapping, and placements convert the same way.

## Sources (checked 2026-10-17)

- Model importer properties: https://docs.unity3d.com/2022.3/Documentation/ScriptReference/ModelImporter.html
- Material remap: https://docs.unity3d.com/2022.3/Documentation/ScriptReference/ModelImporter.SearchAndRemapMaterials.html
- Variants from an instance: https://docs.unity3d.com/2022.3/Documentation/ScriptReference/PrefabUtility.SaveAsPrefabAsset.html
  ("If the input object is a Prefab instance root the resulting Prefab will be a Prefab Variant")
- Standard shader metallic map (R metallic, A smoothness): https://docs.unity3d.com/2022.3/Documentation/Manual/StandardShaderMaterialParameterMetallic.html
- Import hooks: https://docs.unity3d.com/2022.3/Documentation/ScriptReference/AssetPostprocessor.html
