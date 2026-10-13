# Packaging kit pieces in Unity

How exported kit pieces land in a Unity project so each one can be found, swapped or deleted on its own, while
architecture still shares materials (and so draw calls). Pairs with `kit-library.md` on the Blender side.

## Folder layout

```
Assets/World/
  Kits/<FAMILY>/
    _Shared/                    M_<FAMILY>_*.mat and the family's atlas / trim sheet textures
    <Piece>/                    one folder per piece
      <Piece>.fbx
      <Piece>.prefab            prefab variant of the FBX: the thing that gets placed
      M_<Piece>.mat, T_<Piece>_*.png    only if the piece has its own material (props)
  Assemblies/ASM_<Name>.prefab  nested prefabs of kit prefabs
  PlacementSync/                PlacementId.cs and Editor/PlacementSync.cs (see blender-unity-placement-sync)
  Scenes/
```

Deleting a piece is deleting its folder. Replacing one is re-exporting its FBX over the old one (same name, same
material slot order) and nothing else changes.

## Materials: shared for architecture, self-contained for props

| Piece kind | Material lives in | Why |
|---|---|---|
| EXT, INT, STR, TRIM, ZONE | `<FAMILY>/_Shared/` | One material per family keeps SetPass calls down (see `vrchat-world-optimization` budgets) |
| PROP, FOL with a unique texture | `<Piece>/` | Removing or replacing the prop takes its material and textures with it |
| PROP using a family atlas | `<FAMILY>/_Shared/` | Same reason as architecture |

Bind FBX materials to the shared ones by name rather than letting each FBX extract its own copies. With Unity MCP
(`execute_code`), per FBX:

```csharp
var imp = (ModelImporter)AssetImporter.GetAtPath(fbxPath);
imp.materialImportMode = ModelImporterMaterialImportMode.ImportViaMaterialDescription;
imp.SearchAndRemapMaterials(ModelImporterMaterialName.BasedOnMaterialName, ModelImporterMaterialSearch.Everywhere);
imp.SaveAndReimport();
```

This only works if the Blender material is called exactly what the Unity material is called (`M_EXT_Brick` in both).
Check the API with `unity_reflect` before relying on it in an unfamiliar Unity version.

## Import settings

Apply the table in `fbx-export.md` ("Unity import settings to match") to every kit FBX, through an `AssetPostprocessor`
keyed on `Assets/World/Kits/` or through Unity MCP after each import. The ones that bite: Read/Write off, Generate
Lightmap UVs off (UV2 is authored), Import Cameras/Lights off, Animation Type None.

## Prefabs

- Make `<Piece>.prefab` a **prefab variant of the FBX model**. Reimporting the FBX flows into the variant, and anything
  added in Unity (colliders, LOD Group tweaks, static flags, Udon behaviours) lives on the variant and survives
  re-exports.
- Static flags on the variant: Contribute GI and Occluder/Occludee for architecture. Leave **Batching Static off** for
  anything you want GPU-instanced (`unity-batching-and-instancing`).
- Assemblies are prefabs whose children are kit prefab instances, built from the ASM file's placements by
  `blender-unity-placement-sync`, not by hand.
- The prefab root must keep an identity transform. A placement tool positions the root, so an offset baked into the
  root moves every placement.

## Checks after a batch import

1. Every `<Piece>.fbx` has a `<Piece>.prefab` beside it, and no prefab is left without its FBX.
2. No `Materials/` folders extracted next to FBX files that should use `_Shared` materials.
3. One placed instance per family at the origin: position 0, rotation 0, scale 1, correct size against a 1.6 m capsule.
4. Submesh count per mesh equals the number of material slots you expected.
