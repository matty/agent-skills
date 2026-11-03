// Unity side of blender-to-unity for the world shell: import settings, material remap, colliders and static flags for
// the shell zone FBX files exported by batch_export_fbx.py --shell (one FBX per SHELL_<Zone> or CEIL_<Zone>).
// Host: Unity 2022.3 editor (Built-in Render Pipeline projects, VRChat worlds included). Copy to any Editor folder,
// for example Assets/World/Editor/ShellImport.cs, beside KitImport.cs, then let it compile (Unity MCP: create_script,
// refresh_unity, read_console). It acts only on .fbx files under ShellImportTool.ShellRoot (Assets/World/Shell/);
// edit that constant to move the shell.
//
// The shell is each room's envelope, greybox or finished (walls, floors, tiers, stairs, openings, ceilings): Blender's
// top-level SHELL collection, one SHELL_<Zone> child per zone (ceilings may sit in CEILINGS/CEIL_<Zone>), objects
// named SHL_<id>, materials a shared M_<FAMILY>_* (finished) or M_SHL_* (greybox). In the scene, a root GameObject
// SHELL holds one instance of each zone FBX (ceiling zones under a CEILINGS root), outside the placement-sync root
// (PLACEMENTS). A shell object evolves in place in Blender; re-export its zone and copy the FBX over the old file.
// Never change the instance in Unity (an object disabled, a material swapped): those overrides orphan on re-export.
//
// On every import of a shell FBX (ShellModelPostprocessor):
//   - Model settings as KitImport.cs: Scale Factor 1 with Convert Units, no Bake Axis Conversion (the FBX already has
//     the axis change in its vertices), Read/Write off, Generate Lightmap UVs off, no cameras, lights, visibility,
//     blend shapes, generated colliders or animation, Normals Import, MikkTSpace tangents, Mesh Compression Off.
//   - Materials: imported via MaterialDescription, kept embedded, and remapped by name to an existing material
//     anywhere in the project (a shared M_<FAMILY>_*, or M_SHL_* in Assets/World/Shell/Materials/).
//   - Every mesh gets a static, non-convex MeshCollider with its own mesh, unless its Blender object has the custom
//     property unity_collider = 0 (a floor runner, a decal plane). The export writes custom properties for this.
//   - Every GameObject is marked fully static.
// Tools (menu Tools > Shell Import > Reimport Shell, or Unity MCP execute_code):
//   return ShellImport.ShellImportTool.Reimport();    // reimport every shell FBX (after adding materials)
// Nothing here saves a scene. Bump GetVersion() when these rules change: Unity then reimports the shell.
using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEditor;
using UnityEngine;

namespace ShellImport
{
    public static class ShellImportTool
    {
        public const string ShellRoot = "Assets/World/Shell/";
        public const string NoColliderProperty = "unity_collider";

        public static bool IsShellModel(string assetPath)
        {
            return assetPath.StartsWith(ShellRoot, StringComparison.Ordinal)
                && assetPath.EndsWith(".fbx", StringComparison.OrdinalIgnoreCase);
        }

        [MenuItem("Tools/Shell Import/Reimport Shell")]
        public static void ReimportMenu() { Debug.Log(Reimport()); }

        // Reimport every shell FBX (after adding or renaming materials, or changing these rules).
        public static string Reimport()
        {
            int n = 0;
            foreach (var guid in AssetDatabase.FindAssets("t:Model", new[] { ShellRoot.TrimEnd('/') }))
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                if (!IsShellModel(path)) continue;
                AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceUpdate);
                n++;
            }
            return "[shell] reimported " + n + " FBX";
        }
    }

    public class ShellModelPostprocessor : AssetPostprocessor
    {
        // Bump when the rules below change: Unity then reimports the shell models.
        public override uint GetVersion() { return 1; }

        readonly HashSet<string> _noCollider = new HashSet<string>();

        void OnPreprocessModel()
        {
            if (!ShellImportTool.IsShellModel(assetPath)) return;
            var importer = assetImporter as ModelImporter;
            if (importer == null) return;
            importer.globalScale = 1f;
            importer.useFileUnits = true;
            importer.bakeAxisConversion = false;
            importer.isReadable = false;
            importer.generateSecondaryUV = false;
            importer.importCameras = false;
            importer.importLights = false;
            importer.importVisibility = false;
            importer.importBlendShapes = false;
            importer.addCollider = false;
            importer.importNormals = ModelImporterNormals.Import;
            importer.importTangents = ModelImporterTangents.CalculateMikk;
            importer.meshCompression = ModelImporterMeshCompression.Off;
            importer.animationType = ModelImporterAnimationType.None;
            importer.importAnimation = false;
            importer.materialImportMode = ModelImporterMaterialImportMode.ImportViaMaterialDescription;
            importer.materialLocation = ModelImporterMaterialLocation.InPrefab;
            importer.SearchAndRemapMaterials(ModelImporterMaterialName.BasedOnMaterialName, ModelImporterMaterialSearch.Everywhere);
        }

        // FBX user properties arrive here (exported with Custom Properties on), before OnPostprocessModel.
        void OnPostprocessGameObjectWithUserProperties(GameObject go, string[] names, object[] values)
        {
            if (!ShellImportTool.IsShellModel(assetPath)) return;
            for (int i = 0; i < names.Length; i++)
            {
                if (names[i] != ShellImportTool.NoColliderProperty) continue;
                var v = Convert.ToString(values[i], CultureInfo.InvariantCulture);
                if (v == "0" || v.Equals("false", StringComparison.OrdinalIgnoreCase)) _noCollider.Add(go.name);
            }
        }

        void OnPostprocessModel(GameObject root)
        {
            if (!ShellImportTool.IsShellModel(assetPath)) return;
            foreach (var t in root.GetComponentsInChildren<Transform>(true))
                GameObjectUtility.SetStaticEditorFlags(t.gameObject, (StaticEditorFlags)~0);
            foreach (var mf in root.GetComponentsInChildren<MeshFilter>(true))
            {
                if (_noCollider.Contains(mf.name)) continue;
                var collider = mf.GetComponent<MeshCollider>();
                if (collider == null) collider = mf.gameObject.AddComponent<MeshCollider>();
                collider.sharedMesh = mf.sharedMesh;
                collider.convex = false;
            }
        }
    }
}
