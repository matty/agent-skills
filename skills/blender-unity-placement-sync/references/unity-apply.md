# Unity side: Check, Dump, Apply

`scripts/unity/Editor/PlacementSync.cs` and `scripts/unity/PlacementId.cs`, for the Unity 2022.3 editor, driven
through Unity MCP `execute_code`. Measured 2026-10-14 and 2026-10-16 on Unity 2022.3.22f1 (a VRChat world project).

## Install (once per project)

With Unity MCP, `create_script` the two files to `Assets/World/PlacementSync/PlacementId.cs` (a runtime folder: it
is a component) and `Assets/World/PlacementSync/Editor/PlacementSync.cs`, then `refresh_unity` and `read_console`
for compile errors (tool names of the MCP for Unity server, checked 2026-10-17). A file copy into the project works
too.

## Targets

| Target | Scope root |
|---|---|
| `scene:MASTER` | The root GameObject called MASTER in the open scenes |
| `scene:Assets/World/Scenes/Study.unity#MASTER` | The same, in that scene: needed when more than one open scene has such a root (otherwise refused) |
| `prefab:Assets/World/Assemblies/ASM_ShopFront_A.prefab` | That prefab asset, edited in place. The first Apply creates it (one empty root named after the file, identity transform); a Dump before that writes an empty dump |

## Scope roots

A `scene:` target needs its root before the first sync: until it exists, Check says "no root GameObject called
MASTER". Create an empty root GameObject called `MASTER` at identity (position 0, rotation 0, scale 1) in the world
scene. ASM scopes need nothing: their first Apply creates the prefab.

Everything under the scope root syncs, so Unity-only duplicates that must never reach Blender (a switchable light's
per-state copies of the static geometry, for example) go under a separate root outside it, such as `LIGHT_STATES`
beside `MASTER`. Inside the scope they would get fresh ids and be created in the .blend; the merge report flags
several placements of one asset at one pose.

- No world scene yet: the agent creates one under `Assets/World/Scenes/`, adds the root and saves it. A scene the
  agent created itself, at a path it chose, is its own to save. For a VRChat world, start from a copy of the SDK's
  world template scene (`AssetDatabase.CopyAsset` into `Assets/World/Scenes/`, then open it) rather than an empty one.
- A scene the user already works in: add the root and let the user save it; never save their scene for them.

`execute_code` for a new scene the agent owns (it stops if an open scene has unsaved changes, because
`NewSceneMode.Single` closes the open scenes; `SaveScene` needs the folder to exist):

```csharp
const string path = "Assets/World/Scenes/World.unity";
if (AssetDatabase.LoadAssetAtPath<SceneAsset>(path) != null)
    return path + " already exists: open it and add MASTER there (never overwrite a scene)";
for (int i = 0; i < UnityEngine.SceneManagement.SceneManager.sceneCount; i++)
    if (UnityEngine.SceneManagement.SceneManager.GetSceneAt(i).isDirty) return "an open scene has unsaved changes: ask the user";
if (!AssetDatabase.IsValidFolder("Assets/World")) AssetDatabase.CreateFolder("Assets", "World");
if (!AssetDatabase.IsValidFolder("Assets/World/Scenes")) AssetDatabase.CreateFolder("Assets/World", "Scenes");
var scene = UnityEditor.SceneManagement.EditorSceneManager.NewScene(
    UnityEditor.SceneManagement.NewSceneSetup.DefaultGameObjects, UnityEditor.SceneManagement.NewSceneMode.Single);
new GameObject("MASTER");                                    // at the origin, rotation 0, scale 1
UnityEditor.SceneManagement.EditorSceneManager.SaveScene(scene, path);
return PlacementSync.PlacementSyncTool.Check("scene:MASTER");
```

Run through MCP for Unity's `execute_code` wrapper in Unity 2022.3.22f1 batch mode on 2026-10-17: with an unsaved
scene open it changes nothing and says so; otherwise it saves `World.unity` with MASTER at identity and Check reports
ready. The existence guard was added after a re-run overwrote a saved scene.

## Calls

| Call | Does |
|---|---|
| `PlacementSync.PlacementSyncTool.Check(target)` | Returns `[placements] ready: ...` (placement count, prefab roots) or `[placements] not ready: <why>`. Changes nothing |
| `PlacementSync.PlacementSyncTool.Dump(target, outPath, scopeName)` | Writes the dump. When not ready it deletes any old dump at `outPath` and throws, so a merge can never read a stale one |
| `PlacementSync.PlacementSyncTool.Apply(target, planPath, save: true, force: false)` | Applies the plan and saves; returns `[placements] REFUSED ...` (nothing changed) or a summary, with an `ERRORS:` list when something was skipped |
| Menu `Tools > Placement Sync > Dump All` / `Apply All` | Every scope in `PlacementSync.json` in the project root: `{"scopes": [{"name", "target", "dir"}], "prefabRoots": [...]}` |

## When Apply refuses (nothing was changed)

| Condition | `force: true` skips it | Do |
|---|---|---|
| The editor is in Play mode | No | Stop Play mode: Play-mode changes are discarded when it stops |
| None of the prefab roots exists | No | Fix `PlacementSync.json` or `PrefabRootsOverride` |
| No root, or several roots, with the target's name | No | Open the scene, or target `scene:<scene path>#<root>` |
| The target scene was never saved (with `save: true`) | No | The user saves it once (saving it would open a dialog) |
| The target scene has unsaved changes (with `save: true`) | Yes | The user saves or discards them; never save the user's scene for them. `save: false` applies and leaves the scene unsaved for them to review |
| The target prefab is open in Prefab Mode | Yes | The user closes Prefab Mode (its open copy could later be saved over the sync's changes) |
| The plan is the Blender one | No | Pass `<scope>.plan.unity.json` |

Editor extensions such as Bakery can mark a scene dirty without changing it; that still refuses, by design.

## Errors inside an Apply (the rest was applied)

| Error | Do |
|---|---|
| `assign ...: no placement at <key>`, `has id ...`, `is <asset>` | The hierarchy changed since the dump: run the loop again from the dumps |
| `swapping A for B would discard Unity-side changes on ...` | The instance has added components, children or overrides an asset swap would destroy. Tell the user, then take one way out, or every loop plans the same swap again: (a) re-run Apply on the same plan with `force: true`, then the Blender apply (step 5); (b) swap it by hand in Unity, keeping the `PlacementId` component on the new instance, then step 5; (c) keep the old piece: re-point that Blender instance back to the old collection, then restart at step 2 |
| `no prefab called X under ...` | Package the piece, or check the prefab roots |
| `saved ..., but Unity still reports unsaved changes` / `could not save` | Check the scene and save it |

## What Apply does

- Scene edits go through Undo as one group named Placement Sync, so one Ctrl+Z reverses the whole apply (the scene is
  then unsaved again). Prefab-instance edits are recorded as overrides and flushed before the save, so the scene saves
  clean (verified 2026-10-16).
- Order: assign, delete, update, create. Updates run in one pass, parents first, together with every placement the
  plan does not move: a placement dragged by a parent's move gets its old pose back, and so does an update that was
  skipped (a refused swap, a missing prefab). A placement parented under a deleted or swapped placement is moved out
  first, keeping its world pose.
- A second run of the same plan (way out (a) above, with `force: true`) skips the assigns and deletes the first run
  already did, without errors.
- An asset swap (same id, another piece) instantiates the new prefab in the old one's place (same parent, sibling
  index and name) and copies the id.
- Names and folders: an update or create renames the instance when its name without ` (1)` differs from the plan's
  `label`, and reparents it under the plan's `group` path (keeping its world pose), creating missing folder
  GameObjects under the scope root at identity transform. Folders are never deleted, and a placement parented under
  another placement is never moved to a folder. A plan item without `group` is not moved. A folder is a plain
  GameObject (only a Transform) or one that holds placements, preferred in that order; a light called `Lobby` is
  never used as the `Lobby` folder. The plan's `folders` entries run after the assigns: each renames or reparents
  one folder with everything in it, or, when it is missing or the target exists, moves the placements under it. The
  renames, reparents and new folders are in the same Undo group (verified 2026-10-20, Unity 2022.3.22f1 batch: 41 of
  41 checks).
- A prefab target is loaded with `LoadPrefabContents` and written with `SaveAsPrefabAsset`: no Undo.

## Prefab roots

Default `Assets/World/Kits` and `Assets/World/Assemblies`. Others: `prefabRoots` in `PlacementSync.json`, or
`PlacementSync.PlacementSyncTool.PrefabRootsOverride = new[] { "Assets/MyKits" };` from `execute_code`. That is a
static field: it stays set until the next domain reload, so set it back to `null` when done. Configured roots that do
not exist are listed by Check and in the dump's `note`.

## What breaks a placement's identity in Unity

| Action | Effect | Instead |
|---|---|---|
| Overrides > Apply All on a placement | Pushes its PlacementId into the kit prefab: every instance shares one id and the merge re-issues ids | Apply overrides selectively, never the PlacementId component |
| Overrides > Revert All on a placement | Removes its PlacementId; the merge gives the id back if the instance did not move, otherwise it reads as deleted plus new | Revert selectively |
| Unpack Prefab, deleting or moving the prefab out of the roots | The instance stops being a placement and reads as deleted (refused above the deletion budget) | Keep kit prefabs under the roots |
| Editing pieces inside an assembly instance in the MASTER scene | Overrides on the assembly instance that no scope syncs | Edit the assembly prefab and sync its ASM scope |

## APIs relied on (Unity 2022.3 script reference, checked 2026-10-17)

Base URL `https://docs.unity3d.com/2022.3/Documentation/ScriptReference/`, then the page:

| API | Page |
|---|---|
| `PrefabUtility.LoadPrefabContents`, `SaveAsPrefabAsset` (with `out bool`), `UnloadPrefabContents` | `PrefabUtility.LoadPrefabContents.html`, `PrefabUtility.SaveAsPrefabAsset.html`, `PrefabUtility.UnloadPrefabContents.html` |
| `PrefabUtility.IsOutermostPrefabInstanceRoot` (true for an instance added under another instance) | `PrefabUtility.IsOutermostPrefabInstanceRoot.html` |
| `PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot`, `InstantiatePrefab(Object, Transform)`, `IsPartOfPrefabInstance`, `RecordPrefabInstancePropertyModifications` | `PrefabUtility.<name>.html` |
| `PrefabUtility.GetAddedComponents`, `GetAddedGameObjects`, `GetRemovedComponents`, `GetObjectOverrides(GameObject, bool)` with `AddedComponent.instanceComponent`, `AddedGameObject.instanceGameObject`, `RemovedComponent.assetComponent`, `ObjectOverride.instanceObject` | `PrefabUtility.<name>.html`, `SceneManagement.<type>.html` |
| `PrefabStageUtility.GetCurrentPrefabStage`, `PrefabStage.assetPath` | `SceneManagement.PrefabStageUtility.GetCurrentPrefabStage.html`, `SceneManagement.PrefabStage-assetPath.html` |
| `EditorSceneManager.IsPreviewScene`, `MarkSceneDirty`, `SaveScene` (returns false on failure; shows a dialog for a never-saved scene) | `SceneManagement.EditorSceneManager.<name>.html` |
| `EditorApplication.isPlayingOrWillChangePlaymode` | `EditorApplication-isPlayingOrWillChangePlaymode.html` |
| `Undo.RecordObject`, `AddComponent`, `RegisterCreatedObjectUndo`, `DestroyObjectImmediate`, `SetTransformParent` (keeps the world pose, like `Transform.parent`), `FlushUndoRecordObjects`, `IncrementCurrentGroup`, `SetCurrentGroupName`, `GetCurrentGroup`, `CollapseUndoOperations` | `Undo.<name>.html` |
| `AssetDatabase.IsValidFolder`, `CreateFolder`, `FindAssets`, `GUIDToAssetPath`, `LoadAssetAtPath` | `AssetDatabase.<name>.html` |
| `SceneManager.sceneCount`, `GetSceneAt`; `Scene.GetRootGameObjects`, `isLoaded`, `isDirty`, `path` | `SceneManagement.SceneManager.<name>.html`, `SceneManagement.Scene.<name>.html` |
| `JsonUtility.ToJson`, `FromJson` (fields missing from the JSON stay null) | `JsonUtility.<name>.html` |
