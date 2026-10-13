// Unity side of blender-unity-placement-sync: dump placements to JSON, apply a merge plan.
// Host: Unity 2022.3+ editor. Copy to Assets/World/PlacementSync/Editor/PlacementSync.cs, next to ../PlacementId.cs.
//
// A placement is an outermost prefab instance under the scope root whose prefab asset lives under one of the prefab
// roots (default Assets/World/Kits and Assets/World/Assemblies); its asset name is the prefab's file name. Anything
// else under the root (lights, Udon objects, empties used as folders) is ignored, so re-organising the hierarchy
// never loses a placement. Transforms are relative to the scope root, in Unity space.
//
// Scope targets:  "scene:<root GameObject name>"  a root object in an open scene (e.g. scene:MASTER)
//                 "prefab:<asset path>"           a prefab asset, edited in place (e.g. an ASM_ assembly)
//
// From Unity MCP execute_code:
//   PlacementSync.PlacementSyncTool.Dump("scene:MASTER", "F:/World/placements/MASTER.unity.json", "MASTER");
//   PlacementSync.PlacementSyncTool.Apply("scene:MASTER", "F:/World/placements/MASTER.plan.unity.json");
// Or menu Tools > Placement Sync > Dump All / Apply All, driven by PlacementSync.json in the project root:
//   {"scopes": [{"name": "MASTER", "target": "scene:MASTER", "dir": "F:/World/placements"}],
//    "prefabRoots": ["Assets/World/Kits", "Assets/World/Assemblies"]}
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace PlacementSync
{
    [Serializable] public class Item { public string id; public string asset; public float[] pos; public float[] rot; public float[] scl; public string key; }
    [Serializable] public class Dump { public string scope; public string side = "unity"; public Item[] items; public string[] assets; }
    [Serializable] public class Assign { public string key; public string id; }
    [Serializable] public class Plan { public string scope; public string side; public Assign[] assign; public string[] delete; public Item[] update; public Item[] create; }
    [Serializable] public class ScopeConfig { public string name; public string target; public string dir; }
    [Serializable] public class Config { public ScopeConfig[] scopes; public string[] prefabRoots; }

    public static class PlacementSyncTool
    {
        const string ConfigFile = "PlacementSync.json";
        static readonly string[] DefaultRoots = { "Assets/World/Kits", "Assets/World/Assemblies" };

        // Set from execute_code to use other prefab roots without a PlacementSync.json (null = config or defaults).
        public static string[] PrefabRootsOverride;

        public static string[] PrefabRoots
        {
            get
            {
                if (PrefabRootsOverride != null && PrefabRootsOverride.Length > 0) return PrefabRootsOverride.Where(AssetDatabase.IsValidFolder).ToArray();
                var cfg = LoadConfig();
                var roots = cfg != null && cfg.prefabRoots != null && cfg.prefabRoots.Length > 0 ? cfg.prefabRoots : DefaultRoots;
                return roots.Where(AssetDatabase.IsValidFolder).ToArray();
            }
        }

        // ---- public API ---------------------------------------------------------------------------------------

        public static string Dump(string target, string outPath, string scopeName = null)
        {
            string summary = null;
            WithRoot(target, false, root =>
            {
                var items = Placements(root).Select(t => ToItem(root, t)).ToArray();
                var dump = new Dump { scope = scopeName ?? target, items = items, assets = AvailableAssets().Keys.OrderBy(k => k).ToArray() };
                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outPath)));
                File.WriteAllText(outPath, JsonUtility.ToJson(dump, true));
                summary = $"[placements] dumped {items.Length} placement(s) to {outPath}";
            });
            Debug.Log(summary);
            return summary;
        }

        public static string Apply(string target, string planPath, bool save = true)
        {
            var plan = JsonUtility.FromJson<Plan>(File.ReadAllText(planPath));
            var errors = new List<string>();
            var counts = new Dictionary<string, int> { { "assign", 0 }, { "delete", 0 }, { "update", 0 }, { "create", 0 } };
            WithRoot(target, true, root =>
            {
                bool inScene = root.gameObject.scene.IsValid() && !EditorSceneManager.IsPreviewScene(root.gameObject.scene);
                var byKey = Placements(root).ToDictionary(t => KeyOf(root, t));
                foreach (var a in plan.assign ?? new Assign[0])
                {
                    if (!byKey.TryGetValue(a.key, out var t)) { errors.Add($"assign: no placement at {a.key}"); continue; }
                    var pid = GetOrAdd(t.gameObject, inScene);
                    if (inScene) Undo.RecordObject(pid, "Placement Sync");
                    pid.id = a.id;
                    counts["assign"]++;
                }

                var byId = new Dictionary<string, Transform>();
                foreach (var t in Placements(root))
                {
                    var pid = t.GetComponent<PlacementId>();
                    if (pid != null && !string.IsNullOrEmpty(pid.id) && !byId.ContainsKey(pid.id)) byId[pid.id] = t;
                }

                foreach (var id in plan.delete ?? new string[0])
                {
                    if (!byId.TryGetValue(id, out var t)) { errors.Add($"delete: no placement with id {id}"); continue; }
                    byId.Remove(id);
                    Destroy(t.gameObject, inScene);
                    counts["delete"]++;
                }

                var assets = AvailableAssets();
                foreach (var (kind, list) in new[] { ("update", plan.update), ("create", plan.create) })
                {
                    foreach (var it in list ?? new Item[0])
                    {
                        byId.TryGetValue(it.id, out var t);
                        if (t == null || AssetName(t) != it.asset)
                        {
                            if (!assets.TryGetValue(it.asset, out var prefab)) { errors.Add($"{kind} {it.id}: no prefab called {it.asset} under {string.Join(", ", PrefabRoots)}"); continue; }
                            if (t == null && kind == "update") errors.Add($"update: no placement with id {it.id} (creating it)");
                            t = Replace(root, t, prefab, it.id, inScene);
                            byId[it.id] = t;
                        }
                        if (inScene) Undo.RecordObject(t, "Placement Sync");
                        SetRelative(root, t, it);
                        counts[kind]++;
                    }
                }
                if (inScene)
                {
                    EditorSceneManager.MarkSceneDirty(root.gameObject.scene);
                    if (save) EditorSceneManager.SaveScene(root.gameObject.scene);
                }
            });
            var summary = $"[placements] applied {plan.scope}: " + string.Join(", ", counts.Select(kv => $"{kv.Value} {kv.Key}"));
            if (errors.Count > 0) summary += "\nERRORS:\n  " + string.Join("\n  ", errors);
            if (errors.Count > 0) Debug.LogError(summary); else Debug.Log(summary);
            return summary;
        }

        [MenuItem("Tools/Placement Sync/Dump All")]
        static void DumpAll()
        {
            foreach (var s in RequireConfig().scopes) Dump(s.target, Path.Combine(s.dir, s.name + ".unity.json"), s.name);
        }

        [MenuItem("Tools/Placement Sync/Apply All")]
        static void ApplyAll()
        {
            foreach (var s in RequireConfig().scopes)
            {
                var plan = Path.Combine(s.dir, s.name + ".plan.unity.json");
                if (File.Exists(plan)) Apply(s.target, plan);
            }
        }

        // ---- internals ----------------------------------------------------------------------------------------

        static Config LoadConfig() => File.Exists(ConfigFile) ? JsonUtility.FromJson<Config>(File.ReadAllText(ConfigFile)) : null;

        static Config RequireConfig() => LoadConfig() ?? throw new FileNotFoundException($"{ConfigFile} not found in the project root");

        static void WithRoot(string target, bool write, Action<Transform> body)
        {
            if (target.StartsWith("prefab:"))
            {
                var path = target.Substring(7);
                var contents = PrefabUtility.LoadPrefabContents(path);
                try
                {
                    body(contents.transform);
                    if (write) PrefabUtility.SaveAsPrefabAsset(contents, path);
                }
                finally { PrefabUtility.UnloadPrefabContents(contents); }
                return;
            }
            var name = target.StartsWith("scene:") ? target.Substring(6) : target;
            for (int i = 0; i < SceneManager.sceneCount; i++)
            {
                var scene = SceneManager.GetSceneAt(i);
                if (!scene.isLoaded) continue;
                var go = scene.GetRootGameObjects().FirstOrDefault(g => g.name == name);
                if (go != null) { body(go.transform); return; }
            }
            throw new ArgumentException($"no root GameObject called {name} in the open scenes");
        }

        // Outermost prefab instances under root whose prefab sits under a prefab root. Does not descend into them.
        public static List<Transform> Placements(Transform root)
        {
            var roots = PrefabRoots;
            var found = new List<Transform>();
            void Walk(Transform t)
            {
                foreach (Transform c in t)
                {
                    if (IsPlacement(c.gameObject, roots)) found.Add(c);
                    else Walk(c);
                }
            }
            Walk(root);
            return found;
        }

        static bool IsPlacement(GameObject go, string[] roots)
        {
            if (!PrefabUtility.IsOutermostPrefabInstanceRoot(go)) return false;
            var path = PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(go);
            return !string.IsNullOrEmpty(path) && roots.Any(r => path.StartsWith(r + "/"));
        }

        static string AssetName(Transform t) => Path.GetFileNameWithoutExtension(PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject));

        static Dictionary<string, GameObject> AvailableAssets()
        {
            var map = new Dictionary<string, GameObject>();
            var roots = PrefabRoots;
            if (roots.Length == 0) return map;
            foreach (var guid in AssetDatabase.FindAssets("t:Prefab", roots))
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                var name = Path.GetFileNameWithoutExtension(path);
                if (!map.ContainsKey(name)) map[name] = AssetDatabase.LoadAssetAtPath<GameObject>(path);
            }
            return map;
        }

        // Sibling-index path from root, e.g. "3/0/2". Valid only until the hierarchy changes: dump, merge and apply
        // in one go.
        static string KeyOf(Transform root, Transform t)
        {
            var parts = new List<string>();
            for (var c = t; c != null && c != root; c = c.parent) parts.Add(c.GetSiblingIndex().ToString());
            parts.Reverse();
            return string.Join("/", parts);
        }

        static Item ToItem(Transform root, Transform t)
        {
            var pos = root.InverseTransformPoint(t.position);
            var rot = Quaternion.Inverse(root.rotation) * t.rotation;
            var rs = root.lossyScale;
            var ls = t.lossyScale;
            var pid = t.GetComponent<PlacementId>();
            return new Item
            {
                id = pid != null ? pid.id ?? "" : "",
                asset = AssetName(t),
                pos = new[] { pos.x * rs.x, pos.y * rs.y, pos.z * rs.z },
                rot = new[] { rot.x, rot.y, rot.z, rot.w },
                scl = new[] { ls.x / rs.x, ls.y / rs.y, ls.z / rs.z },
                key = KeyOf(root, t),
            };
        }

        static void SetRelative(Transform root, Transform t, Item it)
        {
            var rs = root.lossyScale;
            var local = new Vector3(it.pos[0] / rs.x, it.pos[1] / rs.y, it.pos[2] / rs.z);
            t.SetPositionAndRotation(root.TransformPoint(local), root.rotation * new Quaternion(it.rot[0], it.rot[1], it.rot[2], it.rot[3]).normalized);
            var want = new Vector3(it.scl[0] * rs.x, it.scl[1] * rs.y, it.scl[2] * rs.z);
            var ps = t.parent != null ? t.parent.lossyScale : Vector3.one;
            t.localScale = new Vector3(want.x / ps.x, want.y / ps.y, want.z / ps.z);
        }

        // Instantiate `prefab` in place of `old` (same parent and sibling index) or, with no old, under root.
        static Transform Replace(Transform root, Transform old, GameObject prefab, string id, bool inScene)
        {
            var parent = old != null ? old.parent : root;
            var go = (GameObject)PrefabUtility.InstantiatePrefab(prefab, parent);
            if (inScene) Undo.RegisterCreatedObjectUndo(go, "Placement Sync");
            if (old != null)
            {
                go.transform.SetSiblingIndex(old.GetSiblingIndex());
                Destroy(old.gameObject, inScene);
            }
            var pid = GetOrAdd(go, inScene);
            pid.id = id;
            return go.transform;
        }

        // Explicit == null: in the editor a missing component is a "fake null" object that ?? does not catch.
        static PlacementId GetOrAdd(GameObject go, bool inScene)
        {
            var pid = go.GetComponent<PlacementId>();
            if (pid != null) return pid;
            return inScene ? Undo.AddComponent<PlacementId>(go) : go.AddComponent<PlacementId>();
        }

        static void Destroy(GameObject go, bool inScene)
        {
            if (inScene) Undo.DestroyObjectImmediate(go);
            else UnityEngine.Object.DestroyImmediate(go);
        }
    }
}
