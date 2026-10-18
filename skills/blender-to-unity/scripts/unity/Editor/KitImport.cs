// Unity side of blender-to-unity: import settings, material remap, collision shells, prefab variants and a check for
// kit pieces exported by batch_export_fbx.py --kit.
// Host: Unity 2022.3 editor (Built-in Render Pipeline projects, VRChat worlds included). Copy to any Editor folder,
// for example Assets/World/Editor/KitImport.cs, then let it compile (Unity MCP: create_script, refresh_unity,
// read_console). It acts only on .fbx files under KitImportTool.KitsRoot (Assets/World/Kits/); edit that constant to
// move the kit.
//
// On every import of a kit FBX (KitModelPostprocessor):
//   - Model settings: Scale Factor 1 with Convert Units, no Bake Axis Conversion (the FBX already has the axis change
//     in its vertices), Read/Write off, Generate Lightmap UVs off (UV2 is authored in Blender), no cameras, lights,
//     visibility, blend shapes, generated colliders or animation, Normals Import.
//   - Materials: imported via MaterialDescription, kept embedded, and remapped by name to an existing material
//     anywhere in the project (M_<FAMILY>_* in <FAMILY>/_Shared/, or a prop's own M_<Piece>). A material with no
//     match stays embedded until it exists: create the shared materials, then Reimport.
//   - Tangents: MikkTSpace when a remapped material has a normal map (or nothing is remapped yet), otherwise None.
//   - <Piece>_COL meshes become a MeshCollider with that mesh, and lose their MeshRenderer.
// Tools (menu Tools > Kit Import, or Unity MCP execute_code):
//   return KitImport.KitImportTool.Reimport();                 // reimport every kit FBX (after adding materials)
//   return KitImport.KitImportTool.CreateVariants();           // <Piece>.prefab variant beside each FBX lacking one
//   return KitImport.KitImportTool.SetStaticFlags("Assets/World/Kits/INT/",
//       UnityEditor.StaticEditorFlags.ContributeGI | UnityEditor.StaticEditorFlags.OccluderStatic |
//       UnityEditor.StaticEditorFlags.OccludeeStatic);        // every renderer of every variant under the folder
//   return KitImport.KitImportTool.Check();                    // "[kit] ok ..." or one line per problem
// Variants are made in a preview scene, so the open scenes stay clean. Nothing here saves a scene.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using Object = UnityEngine.Object;

namespace KitImport
{
    public static class KitImportTool
    {
        public const string KitsRoot = "Assets/World/Kits/";
        public const string CollisionSuffix = "_COL";

        public static bool IsKitModel(string assetPath)
        {
            return assetPath.StartsWith(KitsRoot, StringComparison.Ordinal)
                && assetPath.EndsWith(".fbx", StringComparison.OrdinalIgnoreCase);
        }

        public static string VariantPath(string fbxPath)
        {
            return Path.ChangeExtension(fbxPath, ".prefab").Replace('\\', '/');
        }

        static string Folder(string folder)
        {
            folder = string.IsNullOrEmpty(folder) ? KitsRoot : folder;
            return folder.TrimEnd('/');
        }

        public static List<string> KitModels(string folder = null)
        {
            var root = Folder(folder);
            var paths = new List<string>();
            if (!AssetDatabase.IsValidFolder(root)) return paths;
            foreach (var guid in AssetDatabase.FindAssets("t:Model", new[] { root }))
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                if (IsKitModel(path)) paths.Add(path);
            }
            paths.Sort(StringComparer.Ordinal);
            return paths;
        }

        static bool HasTexture(Material mat, string property)
        {
            return mat != null && mat.HasProperty(property) && mat.GetTexture(property) != null;
        }

        // True when a remapped material samples a normal map, or when nothing is remapped yet (keep tangents until the
        // shared materials exist; Reimport afterwards drops them where no normal map is used).
        public static bool NeedsTangents(ModelImporter importer)
        {
            var materials = importer.GetExternalObjectMap()
                .Where(kv => kv.Key.type == typeof(Material))
                .Select(kv => kv.Value as Material)
                .Where(m => m != null)
                .ToList();
            if (materials.Count == 0) return true;
            return materials.Any(m => HasTexture(m, "_BumpMap") || HasTexture(m, "_DetailNormalMap"));
        }

        [MenuItem("Tools/Kit Import/Reimport Kit Models")]
        static void ReimportMenu() { Debug.Log(Reimport()); }

        public static string Reimport(string folder = null)
        {
            var models = KitModels(folder);
            foreach (var path in models) AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceUpdate);
            return "[kit] reimported " + models.Count + " model(s) under " + Folder(folder);
        }

        [MenuItem("Tools/Kit Import/Create Prefab Variants")]
        static void CreateVariantsMenu() { Debug.Log(CreateVariants()); }

        public static string CreateVariants(string folder = null)
        {
            var made = new List<string>();
            var failed = new List<string>();
            var scene = EditorSceneManager.NewPreviewScene();
            try
            {
                foreach (var fbx in KitModels(folder))
                {
                    var prefabPath = VariantPath(fbx);
                    if (AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath) != null) continue;
                    var model = AssetDatabase.LoadAssetAtPath<GameObject>(fbx);
                    if (model == null) { failed.Add(fbx + " (no model)"); continue; }
                    var instance = PrefabUtility.InstantiatePrefab(model, scene) as GameObject;
                    if (instance == null) { failed.Add(fbx + " (could not instantiate)"); continue; }
                    PrefabUtility.SaveAsPrefabAsset(instance, prefabPath, out bool ok);
                    Object.DestroyImmediate(instance);
                    if (ok) made.Add(prefabPath); else failed.Add(prefabPath);
                }
            }
            finally
            {
                EditorSceneManager.ClosePreviewScene(scene);
            }
            var sb = new StringBuilder("[kit] created " + made.Count + " prefab variant(s)");
            foreach (var p in made) sb.Append("\n  ").Append(p);
            foreach (var p in failed) sb.Append("\n  FAILED ").Append(p);
            return sb.ToString();
        }

        // Static flags go on every GameObject with a Renderer in each variant (a multi-mesh FBX keeps its renderers on
        // children) and on the variant root. Which flags: vrchat-lighting-and-baking and unity-batching-and-instancing
        // (leave BatchingStatic off for anything that should GPU-instance).
        public static string SetStaticFlags(string folder, StaticEditorFlags flags)
        {
            var done = new List<string>();
            foreach (var fbx in KitModels(folder))
            {
                var prefabPath = VariantPath(fbx);
                if (AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath) == null) continue;
                var root = PrefabUtility.LoadPrefabContents(prefabPath);
                try
                {
                    GameObjectUtility.SetStaticEditorFlags(root, flags);
                    foreach (var r in root.GetComponentsInChildren<Renderer>(true))
                        GameObjectUtility.SetStaticEditorFlags(r.gameObject, flags);
                    PrefabUtility.SaveAsPrefabAsset(root, prefabPath);
                    done.Add(prefabPath);
                }
                finally
                {
                    PrefabUtility.UnloadPrefabContents(root);
                }
            }
            return "[kit] static flags " + flags + " on " + done.Count + " variant(s) under " + Folder(folder);
        }

        [MenuItem("Tools/Kit Import/Check")]
        static void CheckMenu() { Debug.Log(Check()); }

        static bool IsIdentity(Transform t)
        {
            return t.localPosition.sqrMagnitude < 1e-10f
                && Quaternion.Angle(t.localRotation, Quaternion.identity) < 0.01f
                && (t.localScale - Vector3.one).sqrMagnitude < 1e-8f;
        }

        // N1-N3 of the QA checklist, read-only: settings, materials, collision, roots, variants, orphan prefabs.
        public static string Check(string folder = null)
        {
            var lines = new List<string>();
            var models = KitModels(folder);
            foreach (var fbx in models)
            {
                var issues = new List<string>();
                var importer = AssetImporter.GetAtPath(fbx) as ModelImporter;
                var model = AssetDatabase.LoadAssetAtPath<GameObject>(fbx);
                if (importer == null || model == null) { lines.Add(fbx + ": not imported as a model"); continue; }
                if (importer.isReadable) issues.Add("Read/Write on");
                if (importer.generateSecondaryUV) issues.Add("Generate Lightmap UVs on");
                if (importer.importCameras || importer.importLights) issues.Add("imports cameras or lights");
                if (importer.addCollider) issues.Add("Generate Colliders on");
                if (importer.animationType != ModelImporterAnimationType.None) issues.Add("Animation Type " + importer.animationType);
                if (importer.materialLocation != ModelImporterMaterialLocation.InPrefab) issues.Add("materials extracted");
                if (!IsIdentity(model.transform)) issues.Add("model root not at identity (rotation " + model.transform.localEulerAngles + "): export with Bake Space Transform on");
                // A multi-mesh FBX exported with Bake Space Transform off keeps the root at identity and puts X 270 on
                // every child (measured 2026-10-17, Unity 2022.3.22f1); kit objects have identity transforms anyway.
                foreach (Transform child in model.transform)
                {
                    if (IsIdentity(child)) continue;
                    var e = child.localEulerAngles;
                    bool axisFlip = Mathf.Abs(Mathf.DeltaAngle(e.x, 270f)) < 1f && Mathf.Abs(Mathf.DeltaAngle(e.y, 0f)) < 1f
                        && Mathf.Abs(Mathf.DeltaAngle(e.z, 0f)) < 1f;
                    issues.Add("child " + child.name + " not at identity (position " + child.localPosition + ", rotation " + e
                        + ", scale " + child.localScale + "): " + (axisFlip
                            ? "X 270 on every child means Bake Space Transform was off at export"
                            : "every object in a kit piece keeps identity transforms: origin at the piece pivot, location, rotation and scale applied in Blender"));
                }
                var dir = Path.GetDirectoryName(fbx).Replace('\\', '/');
                if (AssetDatabase.IsValidFolder(dir + "/Materials")) issues.Add("Materials/ folder beside the FBX");
                bool normalMapped = false;
                foreach (var mf in model.GetComponentsInChildren<MeshFilter>(true))
                {
                    var mesh = mf.sharedMesh;
                    if (mesh == null) continue;
                    if (mf.name.EndsWith(CollisionSuffix, StringComparison.Ordinal))
                    {
                        var mc = mf.GetComponent<MeshCollider>();
                        if (mc == null || mc.sharedMesh != mesh) issues.Add(mf.name + " has no MeshCollider");
                        if (mf.GetComponent<MeshRenderer>() != null) issues.Add(mf.name + " still renders");
                        continue;
                    }
                    var mr = mf.GetComponent<MeshRenderer>();
                    if (mr == null) continue;
                    var mats = mr.sharedMaterials;
                    if (mesh.subMeshCount != mats.Length) issues.Add(mf.name + ": " + mesh.subMeshCount + " submeshes, " + mats.Length + " materials");
                    foreach (var mat in mats)
                    {
                        if (mat != null && AssetDatabase.GetAssetPath(mat) == fbx) issues.Add(mf.name + ": material " + mat.name + " is embedded (no project material of that name)");
                        if (HasTexture(mat, "_BumpMap") || HasTexture(mat, "_DetailNormalMap")) normalMapped = true;
                    }
                    if (!mesh.HasVertexAttribute(VertexAttribute.TexCoord1)) issues.Add(mf.name + " has no UV2");
                }
                if (normalMapped && importer.importTangents == ModelImporterTangents.None) issues.Add("normal-mapped material but Tangents None: Reimport");
                var variant = AssetDatabase.LoadAssetAtPath<GameObject>(VariantPath(fbx));
                if (variant == null) issues.Add("no prefab variant " + VariantPath(fbx));
                else if (PrefabUtility.GetPrefabAssetType(variant) != PrefabAssetType.Variant
                         || PrefabUtility.GetCorrespondingObjectFromSource(variant) != model)
                    issues.Add(VariantPath(fbx) + " is not a variant of the FBX");
                else if (!IsIdentity(variant.transform)) issues.Add("variant root not at identity");
                if (issues.Count > 0) lines.Add(fbx + ": " + string.Join("; ", issues));
            }
            var root = Folder(folder);
            if (AssetDatabase.IsValidFolder(root))
            {
                foreach (var guid in AssetDatabase.FindAssets("t:Prefab", new[] { root }))
                {
                    var prefab = AssetDatabase.GUIDToAssetPath(guid);
                    if (AssetImporter.GetAtPath(Path.ChangeExtension(prefab, ".fbx").Replace('\\', '/')) == null)
                        lines.Add(prefab + ": prefab without its FBX");
                }
            }
            if (lines.Count == 0) return "[kit] ok: " + models.Count + " model(s) under " + root;
            return "[kit] " + lines.Count + " problem(s) in " + models.Count + " model(s) under " + root + "\n  " + string.Join("\n  ", lines);
        }
    }

    public class KitModelPostprocessor : AssetPostprocessor
    {
        // Bump when the rules below change: Unity then reimports the kit models.
        public override uint GetVersion() { return 1; }

        void OnPreprocessModel()
        {
            if (!KitImportTool.IsKitModel(assetPath)) return;
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
            importer.animationType = ModelImporterAnimationType.None;
            importer.importAnimation = false;
            importer.materialImportMode = ModelImporterMaterialImportMode.ImportViaMaterialDescription;
            importer.materialLocation = ModelImporterMaterialLocation.InPrefab;
            importer.SearchAndRemapMaterials(ModelImporterMaterialName.BasedOnMaterialName, ModelImporterMaterialSearch.Everywhere);
            importer.importTangents = KitImportTool.NeedsTangents(importer) ? ModelImporterTangents.CalculateMikk : ModelImporterTangents.None;
        }

        void OnPostprocessModel(GameObject root)
        {
            if (!KitImportTool.IsKitModel(assetPath)) return;
            foreach (var mf in root.GetComponentsInChildren<MeshFilter>(true))
            {
                if (!mf.name.EndsWith(KitImportTool.CollisionSuffix, StringComparison.Ordinal)) continue;
                var go = mf.gameObject;
                var collider = go.GetComponent<MeshCollider>();
                if (collider == null) collider = go.AddComponent<MeshCollider>();
                collider.sharedMesh = mf.sharedMesh;
                var renderer = go.GetComponent<MeshRenderer>();
                if (renderer != null) Object.DestroyImmediate(renderer);
            }
        }
    }
}
