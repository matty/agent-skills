// Unity side of blender-unity-placement-sync: check the editor is ready, dump placements to JSON, apply a merge plan.
// Host: Unity 2022.3+ editor. Copy to Assets/World/PlacementSync/Editor/PlacementSync.cs, next to ../PlacementId.cs.
//
// A placement is an outermost prefab instance under the scope root, at any depth (a piece parented under another
// piece counts), whose prefab asset lives under one of the prefab roots (default Assets/World/Kits and
// Assets/World/Assemblies); its asset name is the prefab's file name. Pieces that are part of an assembly instance
// belong to the assembly's own scope. Anything else under the root (lights, Udon objects, folder empties) is ignored.
// Transforms are relative to the scope root, in Unity space.
//
// Names and folders sync too: "label" is the instance's name without Unity's " (1)" suffix, "group" the path of the
// non-placement GameObjects between the scope root and the instance ("Street/Shops"; "" directly under the root).
// A placement parented under another placement is "nested": its folder is its parent's, so its group is not synced.
// Apply renames an instance whose label changed and moves it under its group's folder, creating missing folder
// GameObjects (identity transform) under the root; it never deletes a folder. "/" in a name reads as "-".
//
// Scope targets:  "scene:<root name>"                a root GameObject in an open scene (e.g. scene:MASTER)
//                 "scene:<scene path>#<root name>"   the same, when more than one open scene has such a root
//                 "prefab:<asset path>"              a prefab asset edited in place (an ASM_ assembly); the first
//                                                    Apply creates it (one empty root) when it does not exist yet
//
// From Unity MCP execute_code:
//   return PlacementSync.PlacementSyncTool.Check("scene:MASTER");      // "[placements] ready ..." or why not
//   return PlacementSync.PlacementSyncTool.Dump("scene:MASTER", "F:/World/placements/MASTER.unity.json", "MASTER");
//   return PlacementSync.PlacementSyncTool.Apply("scene:MASTER", "F:/World/placements/MASTER.plan.unity.json");
// Dump throws when the editor is not ready (Play mode, no prefab root, no or several matching roots) and deletes the
// old dump first, so a merge never reads a stale one. Apply returns "[placements] REFUSED ..." and changes nothing in
// Play mode, when the target scene was never saved or already has unsaved changes, or when the target prefab is open
// in Prefab Mode. save: false applies and leaves the scene unsaved for review (scenes only); force: true saves over
// pending changes the user confirmed are safe, and lets an asset swap discard Unity-side changes on that instance.
// Or menu Tools > Placement Sync > Dump All / Apply All, driven by PlacementSync.json in the project root:
//   {"scopes": [{"name": "MASTER", "target": "scene:MASTER", "dir": "F:/World/placements"}],
//    "prefabRoots": ["Assets/World/Kits", "Assets/World/Assemblies"]}
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace PlacementSync
{
    [Serializable] public class Item { public string id; public string asset; public float[] pos; public float[] rot; public float[] scl; public string key; public string name; public string label; public string group; public bool nested; }
    [Serializable] public class Dump { public string scope; public string side = "unity"; public string target; public string[] prefabRoots; public string note; public Item[] items; public string[] assets; }
    [Serializable] public class Assign { public string key; public string id; public string was; public string asset; }
    [Serializable] public class Plan { public string scope; public string side; public Assign[] assign; public string[] delete; public Item[] update; public Item[] create; }
    [Serializable] public class ScopeConfig { public string name; public string target; public string dir; }
    [Serializable] public class Config { public ScopeConfig[] scopes; public string[] prefabRoots; }

    public static class PlacementSyncTool
    {
        const string ConfigFile = "PlacementSync.json";
        static readonly string[] DefaultRoots = { "Assets/World/Kits", "Assets/World/Assemblies" };

        // Set from execute_code to use other prefab roots without a PlacementSync.json (null = config or defaults).
        // A static: it stays set until the next domain reload, so set it back to null when done.
        public static string[] PrefabRootsOverride;

        static string[] ConfiguredRoots()
        {
            if (PrefabRootsOverride != null && PrefabRootsOverride.Length > 0) return PrefabRootsOverride;
            var cfg = LoadConfig();
            return cfg != null && cfg.prefabRoots != null && cfg.prefabRoots.Length > 0 ? cfg.prefabRoots : DefaultRoots;
        }

        public static string[] PrefabRoots => ConfiguredRoots().Where(AssetDatabase.IsValidFolder).ToArray();

        // ---- public API ---------------------------------------------------------------------------------------

        // Whether Apply would run now, and what the scope holds. Changes nothing.
        public static string Check(string target)
        {
            var why = NotReady(target, true, true, false);
            if (why != null) return $"[placements] not ready: {why}";
            string what;
            if (IsMissingPrefab(target)) what = $"{target.Substring(7)} does not exist yet (the first Apply creates it)";
            else
            {
                int n = 0;
                WithRoot(target, false, root => n = Placements(root).Count);
                what = $"{n} placement(s)";
            }
            var missing = MissingRootsNote();
            return $"[placements] ready: {target}, {what}, prefab roots {string.Join(", ", PrefabRoots)}"
                   + (missing != null ? $" ({missing})" : "");
        }

        public static string Dump(string target, string outPath, string scopeName = null)
        {
            if (File.Exists(outPath)) File.Delete(outPath);
            var why = NotReady(target, false, false, false);
            if (why != null) throw new InvalidOperationException($"[placements] dump of {target} refused: {why}");
            var dump = new Dump
            {
                scope = scopeName ?? target, target = target, prefabRoots = PrefabRoots, note = MissingRootsNote(),
                assets = AvailableAssets().Keys.OrderBy(k => k).ToArray(), items = new Item[0],
            };
            if (IsMissingPrefab(target))
                dump.note = $"{target.Substring(7)} does not exist yet: the first Apply creates it. " + dump.note;
            else
                WithRoot(target, false, root => dump.items = Placements(root).Select(t => ToItem(root, t)).ToArray());
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outPath)));
            File.WriteAllText(outPath, JsonUtility.ToJson(dump, true));
            var summary = $"[placements] dumped {dump.items.Length} placement(s) from {target} to {outPath}";
            Debug.Log(summary);
            return summary;
        }

        public static string Apply(string target, string planPath, bool save = true, bool force = false)
        {
            var plan = JsonUtility.FromJson<Plan>(File.ReadAllText(planPath));
            var why = NotReady(target, true, save, force);
            if (why == null && !string.IsNullOrEmpty(plan.side) && plan.side != "unity")
                why = $"{planPath} is the {plan.side} plan, not the unity one";
            if (why != null)
            {
                var refused = $"[placements] REFUSED {plan.scope}: {why}. Nothing was changed.";
                Debug.LogError(refused);
                return refused;
            }
            if (target.StartsWith("prefab:")) EnsurePrefab(target.Substring(7));
            var errors = new List<string>();
            var counts = new Dictionary<string, int> { { "assign", 0 }, { "delete", 0 }, { "update", 0 }, { "create", 0 } };
            WithRoot(target, true, root =>
            {
                bool inScene = root.gameObject.scene.IsValid() && !EditorSceneManager.IsPreviewScene(root.gameObject.scene);
                int undoGroup = -1;
                if (inScene)
                {
                    Undo.IncrementCurrentGroup();
                    Undo.SetCurrentGroupName("Placement Sync");
                    undoGroup = Undo.GetCurrentGroup();
                }
                var touched = new List<UnityEngine.Object>();
                var byKey = Placements(root).ToDictionary(t => KeyOf(root, t));
                var haveIds = new HashSet<string>();
                foreach (var t in byKey.Values)
                {
                    var p0 = t.GetComponent<PlacementId>();
                    if (p0 != null && !string.IsNullOrEmpty(p0.id)) haveIds.Add(p0.id);
                }
                foreach (var a in plan.assign ?? new Assign[0])
                {
                    if (haveIds.Contains(a.id)) continue;   // done by an earlier run of this plan (a re-run with force: true)
                    if (!byKey.TryGetValue(a.key, out var t)) { errors.Add($"assign {a.id}: no placement at {a.key} (the hierarchy changed since the dump: run the loop again)"); continue; }
                    var cur = t.GetComponent<PlacementId>();
                    var curId = cur != null ? cur.id ?? "" : "";
                    if (a.was != null && curId != a.was) { errors.Add($"assign {a.id}: {NameOf(root, t)} has id '{curId}', the merge saw '{a.was}' (changed since the dump: run the loop again)"); continue; }
                    if (!string.IsNullOrEmpty(a.asset) && AssetName(t) != a.asset) { errors.Add($"assign {a.id}: {NameOf(root, t)} is {AssetName(t)}, the merge saw {a.asset} (changed since the dump: run the loop again)"); continue; }
                    var pid = GetOrAdd(t.gameObject, inScene);
                    if (inScene) Undo.RecordObject(pid, "Placement Sync");
                    pid.id = a.id;
                    touched.Add(pid);
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
                    if (!byId.TryGetValue(id, out var t)) continue;   // already gone (an earlier run of this plan)
                    byId.Remove(id);
                    KeepNestedPlacements(t, inScene);
                    Destroy(t.gameObject, inScene);
                    counts["delete"]++;
                }

                // Every placement's pose (relative to root) before anything moves. Updates and the restoring of every
                // other placement then run in one pass, parents first: an update sets its planned pose, and a
                // placement the plan does not move, or whose update is skipped, gets its old pose back when a parent's
                // move dragged it (the update-path twin of KeepNestedPlacements).
                var before = new Dictionary<Transform, Item>();
                foreach (var p in Placements(root)) before[p] = ToItem(root, p);
                var planned = new Dictionary<string, Item>();
                foreach (var it in plan.update ?? new Item[0])
                    if (!string.IsNullOrEmpty(it.id)) planned[it.id] = it;
                var assets = AvailableAssets();

                bool ApplyItem(string kind, Item it)
                {
                    byId.TryGetValue(it.id, out var t);
                    if (t == null || AssetName(t) != it.asset)
                    {
                        if (!assets.TryGetValue(it.asset, out var prefab)) { errors.Add($"{kind} {it.id}: no prefab called {it.asset} under {string.Join(", ", PrefabRoots)}"); return false; }
                        if (t != null)
                        {
                            var work = LocalChanges(t);
                            if (work != null && !force) { errors.Add($"{kind} {it.id}: swapping {AssetName(t)} for {it.asset} would discard Unity-side changes on {NameOf(root, t)} ({work}); swap it by hand, or re-run with force: true"); return false; }
                            KeepNestedPlacements(t, inScene);
                        }
                        if (t == null && kind == "update") errors.Add($"update: no placement with id {it.id} (creating it)");
                        t = Replace(root, t, prefab, it.id, inScene);
                        byId[it.id] = t;
                    }
                    if (it.group != null && !Nested(root, t) && GroupOf(root, t) != CleanGroup(it.group))
                    {
                        var folder = EnsureGroup(root, it.group, inScene);
                        if (inScene) Undo.SetTransformParent(t, folder, "Placement Sync");
                        else t.SetParent(folder, true);
                    }
                    if (!string.IsNullOrEmpty(it.label) && Clean(t.name) != Clean(it.label))
                    {
                        if (inScene) Undo.RecordObject(t.gameObject, "Placement Sync");
                        t.gameObject.name = Clean(it.label);
                        touched.Add(t.gameObject);
                    }
                    if (inScene) Undo.RecordObject(t, "Placement Sync");
                    SetRelative(root, t, it);
                    touched.Add(t);
                    var tid = t.GetComponent<PlacementId>();
                    if (tid != null) touched.Add(tid);
                    counts[kind]++;
                    return true;
                }

                void Restore(Transform t)
                {
                    if (t == null || !before.TryGetValue(t, out var pose) || SamePose(ToItem(root, t), pose)) return;
                    if (inScene) Undo.RecordObject(t, "Placement Sync");
                    SetRelative(root, t, pose);
                    touched.Add(t);
                }

                var steps = new List<(int depth, Transform t, Item it)>();
                foreach (var it in planned.Values)
                    steps.Add((DepthOf(root, byId, it.id), byId.TryGetValue(it.id, out var ut) ? ut : null, it));
                foreach (var p in before.Keys)
                {
                    var pid = p.GetComponent<PlacementId>();
                    if (pid == null || string.IsNullOrEmpty(pid.id) || !planned.ContainsKey(pid.id))
                        steps.Add((Depth(root, p), p, null));
                }
                foreach (var step in steps.OrderBy(s => s.depth))
                    if (step.it == null || !ApplyItem("update", step.it)) Restore(step.t);
                foreach (var it in plan.create ?? new Item[0])
                    ApplyItem("create", it);
                if (inScene)
                {
                    // Edits to prefab instances become overrides only when recorded; left to the end of the frame they
                    // land after the save and the scene shows unsaved changes again. Record and flush them first.
                    foreach (var o in touched)
                        if (o != null && PrefabUtility.IsPartOfPrefabInstance(o))
                            PrefabUtility.RecordPrefabInstancePropertyModifications(o);
                    Undo.FlushUndoRecordObjects();
                    Undo.CollapseUndoOperations(undoGroup);
                    var scene = root.gameObject.scene;
                    EditorSceneManager.MarkSceneDirty(scene);
                    if (save)
                    {
                        if (!EditorSceneManager.SaveScene(scene))
                            errors.Add($"could not save {scene.path}: save it yourself");
                        else if (scene.isDirty)
                            errors.Add($"saved {scene.path}, but Unity still reports unsaved changes in it: check and save it");
                    }
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

        // Why `target` cannot be dumped (forApply false) or applied now, or null. Checked before anything is touched.
        // force skips only the checks about the user's pending work (a dirty scene, the prefab open in Prefab Mode).
        static string NotReady(string target, bool forApply, bool save, bool force)
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
                return "the editor is in Play mode, whose changes are discarded when it stops: stop Play mode first";
            if (PrefabRoots.Length == 0)
                return $"none of the prefab roots exists ({string.Join(", ", ConfiguredRoots())}): fix PlacementSync.json or PrefabRootsOverride";
            if (target.StartsWith("prefab:"))
            {
                var path = target.Substring(7);
                if (!path.StartsWith("Assets/") || !path.EndsWith(".prefab")) return $"{path} is not an Assets/....prefab path";
                var stage = PrefabStageUtility.GetCurrentPrefabStage();
                if (forApply && !force && stage != null && stage.assetPath == path)
                    return $"{path} is open in Prefab Mode: close it first (its open copy could later be saved over the sync's changes)";
                return null;
            }
            if (FindSceneRoot(target, out var scene, out var why) == null) return why;
            if (forApply && save && string.IsNullOrEmpty(scene.path))
                return $"scene {scene.name} has never been saved: save it once first (saving it would open a dialog)";
            if (forApply && save && !force && scene.isDirty)
                return $"scene {scene.name} already has unsaved changes: the user saves or discards them first";
            return null;
        }

        static string MissingRootsNote()
        {
            var missing = ConfiguredRoots().Where(r => !AssetDatabase.IsValidFolder(r)).ToArray();
            return missing.Length == 0 ? null : $"prefab root(s) not found: {string.Join(", ", missing)}";
        }

        static bool IsMissingPrefab(string target) =>
            target.StartsWith("prefab:") && AssetDatabase.LoadAssetAtPath<GameObject>(target.Substring(7)) == null;

        // The first Apply of an ASM scope creates its prefab: one empty root named after the file, identity transform.
        static void EnsurePrefab(string path)
        {
            if (AssetDatabase.LoadAssetAtPath<GameObject>(path) != null) return;
            EnsureFolder(Path.GetDirectoryName(path).Replace('\\', '/'));
            var go = new GameObject(Path.GetFileNameWithoutExtension(path));
            try
            {
                PrefabUtility.SaveAsPrefabAsset(go, path, out bool ok);
                if (!ok) throw new InvalidOperationException($"[placements] could not create {path}");
            }
            finally { UnityEngine.Object.DestroyImmediate(go); }
        }

        static void EnsureFolder(string folder)
        {
            if (AssetDatabase.IsValidFolder(folder)) return;
            var parent = Path.GetDirectoryName(folder).Replace('\\', '/');
            EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, Path.GetFileName(folder));
        }

        static Config LoadConfig() => File.Exists(ConfigFile) ? JsonUtility.FromJson<Config>(File.ReadAllText(ConfigFile)) : null;

        static Config RequireConfig() => LoadConfig() ?? throw new FileNotFoundException($"{ConfigFile} not found in the project root");

        // The one root GameObject a "scene:" target names in the loaded scenes, or null with the reason.
        static Transform FindSceneRoot(string target, out Scene scene, out string why)
        {
            scene = default;
            why = null;
            var spec = target.StartsWith("scene:") ? target.Substring(6) : target;
            string scenePath = null, name = spec;
            var hash = spec.LastIndexOf('#');
            if (hash >= 0) { scenePath = spec.Substring(0, hash); name = spec.Substring(hash + 1); }
            var found = new List<GameObject>();
            for (int i = 0; i < SceneManager.sceneCount; i++)
            {
                var s = SceneManager.GetSceneAt(i);
                if (!s.isLoaded || (scenePath != null && s.path != scenePath)) continue;
                found.AddRange(s.GetRootGameObjects().Where(g => g.name == name));
            }
            if (found.Count == 1)
            {
                scene = found[0].scene;
                return found[0].transform;
            }
            why = found.Count == 0
                ? $"no root GameObject called {name} in the open scenes" + (scenePath != null ? $" ({scenePath} must be open)" : "")
                : $"{found.Count} root GameObjects called {name} ({string.Join(", ", found.Select(g => g.scene.path))}): target one as scene:<scene path>#{name}";
            return null;
        }

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
            var root = FindSceneRoot(target, out _, out var why);
            if (root == null) throw new ArgumentException($"[placements] {why}");
            body(root);
        }

        // Outermost prefab instances under root whose prefab sits under a prefab root, at any depth. A piece parented
        // under another piece is an added GameObject on that instance and still outermost; pieces that are part of an
        // assembly instance are not outermost, so they stay with the assembly's own scope.
        public static List<Transform> Placements(Transform root)
        {
            var roots = PrefabRoots;
            var found = new List<Transform>();
            void Walk(Transform t)
            {
                foreach (Transform c in t)
                {
                    if (IsPlacement(c.gameObject, roots)) found.Add(c);
                    Walk(c);
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

        // Readable hierarchy path for reports only; never used to find an object (names need not be unique).
        static string NameOf(Transform root, Transform t)
        {
            var parts = new List<string>();
            for (var c = t; c != null && c != root; c = c.parent) parts.Add(c.name);
            parts.Reverse();
            return string.Join("/", parts);
        }

        // A name as every side compares it: Unity's duplicate suffix " (1)" dropped, "/" (Find's path separator) read
        // as "-", ends trimmed.
        static string Clean(string name) => Regex.Replace(name ?? "", @" \(\d+\)$", "").Replace("/", "-").Trim();

        static string CleanGroup(string group) =>
            string.Join("/", (group ?? "").Split('/').Select(Clean).Where(p => p.Length > 0));

        // Whether a placement sits under another placement below root (its folder is then its parent's).
        static bool Nested(Transform root, Transform t)
        {
            var roots = PrefabRoots;
            for (var c = t.parent; c != null && c != root; c = c.parent)
                if (IsPlacement(c.gameObject, roots)) return true;
            return false;
        }

        // The folder path between root and t: the names of its ancestors below root.
        static string GroupOf(Transform root, Transform t)
        {
            var parts = new List<string>();
            for (var c = t.parent; c != null && c != root; c = c.parent) parts.Add(Clean(c.name));
            parts.Reverse();
            return string.Join("/", parts.Where(p => p.Length > 0));
        }

        // The folder for `group` under root, creating the missing GameObjects (identity transform). Placements are
        // never used as folders.
        static Transform EnsureGroup(Transform root, string group, bool inScene)
        {
            var roots = PrefabRoots;
            var cur = root;
            foreach (var part in CleanGroup(group).Split('/').Where(p => p.Length > 0))
            {
                Transform next = null;
                foreach (Transform c in cur)
                    if (Clean(c.name) == part && !IsPlacement(c.gameObject, roots)) { next = c; break; }
                if (next == null)
                {
                    var go = new GameObject(part);
                    go.transform.SetParent(cur, false);
                    if (inScene) Undo.RegisterCreatedObjectUndo(go, "Placement Sync");
                    next = go.transform;
                }
                cur = next;
            }
            return cur;
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
                name = NameOf(root, t),
                label = Clean(t.name).Length > 0 ? Clean(t.name) : AssetName(t),
                nested = Nested(root, t),
                group = Nested(root, t) ? "" : GroupOf(root, t),
            };
        }

        // How many levels below root the placement with this id sits (0 when it is not there yet: a create).
        static int DepthOf(Transform root, Dictionary<string, Transform> byId, string id)
        {
            if (id == null || !byId.TryGetValue(id, out var t) || t == null) return 0;
            return Depth(root, t);
        }

        static int Depth(Transform root, Transform t)
        {
            int d = 0;
            for (var c = t; c != null && c != root; c = c.parent) d++;
            return d;
        }

        static bool SamePose(Item a, Item b)
        {
            for (int i = 0; i < 3; i++)
                if (Mathf.Abs(a.pos[i] - b.pos[i]) > 1e-5f || Mathf.Abs(a.scl[i] - b.scl[i]) > 1e-5f) return false;
            float dot = a.rot[0] * b.rot[0] + a.rot[1] * b.rot[1] + a.rot[2] * b.rot[2] + a.rot[3] * b.rot[3];
            return Mathf.Abs(dot) > 1f - 1e-7f;
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

        // What an asset swap would throw away on this instance: components, children and overrides added in Unity
        // (placements parented under it are moved out first, so they do not count). Null when there is nothing.
        static string LocalChanges(Transform t)
        {
            var go = t.gameObject;
            var roots = PrefabRoots;
            var parts = new List<string>();
            foreach (var c in PrefabUtility.GetAddedComponents(go))
                if (!(c.instanceComponent is PlacementId)) parts.Add("added " + c.instanceComponent.GetType().Name);
            foreach (var g in PrefabUtility.GetAddedGameObjects(go))
                if (!IsPlacement(g.instanceGameObject, roots)) parts.Add("added child " + g.instanceGameObject.name);
            foreach (var r in PrefabUtility.GetRemovedComponents(go))
                parts.Add("removed " + (r.assetComponent != null ? r.assetComponent.GetType().Name : "a component"));
            foreach (var o in PrefabUtility.GetObjectOverrides(go, false))
                if (o.instanceObject != null && o.instanceObject != t && o.instanceObject != go)
                    parts.Add("changed " + o.instanceObject.name);
            return parts.Count == 0 ? null : string.Join(", ", parts.Distinct());
        }

        // Placements parented under `t` are placements in their own right: before `t` is destroyed or swapped, move the
        // ones directly under it (no other placement in between) to t's parent, keeping their world pose.
        static void KeepNestedPlacements(Transform t, bool inScene)
        {
            var roots = PrefabRoots;
            var move = new List<Transform>();
            foreach (var c in t.GetComponentsInChildren<Transform>(true))
            {
                if (c == t || !IsPlacement(c.gameObject, roots)) continue;
                var p = c.parent;
                while (p != t && !IsPlacement(p.gameObject, roots)) p = p.parent;
                if (p == t) move.Add(c);
            }
            foreach (var c in move)
            {
                if (inScene) Undo.SetTransformParent(c, t.parent, "Placement Sync");
                else c.SetParent(t.parent, true);
            }
        }

        // Instantiate `prefab` in place of `old` (same parent, sibling index and name) or, with no old, under root.
        static Transform Replace(Transform root, Transform old, GameObject prefab, string id, bool inScene)
        {
            var parent = old != null ? old.parent : root;
            var go = (GameObject)PrefabUtility.InstantiatePrefab(prefab, parent);
            if (inScene) Undo.RegisterCreatedObjectUndo(go, "Placement Sync");
            if (old != null)
            {
                go.name = old.name;                     // a swap keeps the user's name (and its " (1)")
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
