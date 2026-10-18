# Doing the SDK setup from a script (Unity MCP)

For an agent driving the Unity editor through Unity MCP. `execute_code` wraps the C# in a static method with only
`using System; System.Collections.Generic; System.Linq; System.Reflection; UnityEngine; UnityEditor;`, so write
`UnityEngine.Object` (a bare `Object` is ambiguous) and give anything from another namespace its full name, as below.
The method returns `object`: end every path with `return` (a string to report). Instead of `Tuple` (Unity's
ExCSS.Unity also defines `System.Tuple`: CS0433) use `KeyValuePair`, a value tuple or an anonymous type; a class
cannot be declared inside the body (CS1513). Every snippet here was compiled under that exact wrapper against Unity
2022.3.22f1 and Worlds SDK 3.10.5 on 2026-10-17; after an SDK update, confirm the calls still exist
(`sdk-observed.md`).

## Layers and collision matrix

- Check: `UpdateLayers.AreLayersSetup()` and `UpdateLayers.IsCollisionLayerMatrixSetup()`, both true. `UpdateLayers`
  sits in the global namespace (no `VRC.Editor.` prefix).
- Fix, signed in or not: `UpdateLayers.SetupEditorLayers();` then `UpdateLayers.SetupCollisionLayerMatrix();`. These
  are what the two Builder buttons call, without the confirmation dialogs. They rewrite
  `ProjectSettings/TagManager.asset` and the physics collision matrix, so list `ProjectSettings/` among the task's
  writes.

## Scene descriptor

- Add one without the Builder (what its Add a VRCSceneDescriptor button does):

  ```csharp
  var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(
      "Packages/com.vrchat.worlds/Samples/UdonExampleScene/Prefabs/VRCWorld.prefab");
  var world = UnityEngine.Object.Instantiate(prefab);
  world.name = "VRCWorld";
  UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(world.scene);
  return world.name + " added to " + world.scene.name;
  ```

- Exactly one: `UnityEngine.Object.FindObjectsOfType<VRC.SDK3.Components.VRCSceneDescriptor>()` has length 1.
- Spawns: its only spawn is its own transform. Assign dedicated spawns in one step, for example
  `descriptor.spawns = new[] { spawnA.transform, spawnB.transform };` (emptying the array first would let the
  descriptor's Inspector refill it with its own transform). Then check `descriptor.GetValidatedSpawnList().Count > 0`
  (an empty list blocks the build) and that a downward raycast from each spawn hits a floor collider within a few
  centimetres.
- Respawn: `descriptor.RespawnHeightY` below the lowest walkable surface, and
  `descriptor.ObjectBehaviourAtRespawnHeight = VRC.SDKBase.VRC_SceneDescriptor.RespawnHeightBehaviour.Respawn` for
  objects that should come back.

## Components

- Pickup: the GameObject has `VRC.SDK3.Components.VRCPickup`, a `Rigidbody`, a `Collider` and
  `VRC.SDK3.Components.VRCObjectSync` (without Object Sync it never respawns in ClientSim, and other players do not
  see it move), and sits on layer 13 Pickup.
- Station: instantiate the SDK's chair, place it (it arrives at the prefab's stored position, (-8.99, 0.75, -3.58)),
  and adapt it rather than building one. It is a prefab instance: a change set directly becomes an override only
  when the scene is saved, and a merge with the prefab before that (as when the prefab asset changes) discards it, so
  record it. Edit through a `SerializedObject` (its `ApplyModifiedProperties` records the override), call
  `PrefabUtility.RecordPrefabInstancePropertyModifications(component)` after a direct change, or unpack the instance.

  ```csharp
  var chairPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(
      "Packages/com.vrchat.worlds/Samples/UdonExampleScene/Prefabs/VRCChair/VRCChair3.prefab");
  var chair = (GameObject)PrefabUtility.InstantiatePrefab(chairPrefab);
  chair.transform.SetPositionAndRotation(new Vector3(1f, 0f, 2f), Quaternion.identity);
  PrefabUtility.RecordPrefabInstancePropertyModifications(chair.transform);
  var station = new SerializedObject(chair.GetComponent<VRC.SDK3.Components.VRCStation>());
  station.FindProperty("canUseStationFromStation").boolValue = false;   // the prefab has true
  station.ApplyModifiedProperties();
  UnityEditor.SceneManagement.EditorSceneManager.SaveScene(chair.scene);
  return chair.name + " at " + chair.transform.position;
  ```

  Then reopen the scene from disk and read both values back (the position, and `canUseStationFromStation` through a
  new `SerializedObject`): a value equal to the prefab's records nothing, so only a real change proves the save.

  In Play, press it and check that the local player sits:

  ```csharp
  var chair = GameObject.Find("VRCChair3");
  chair.GetComponent<VRC.Udon.UdonBehaviour>().Interact();
  var helper = chair.GetComponent<VRC.SDK3.ClientSim.ClientSimStationHelper>();
  if (helper == null) return "no ClientSim station helper: is Play mode running?";
  return helper.IsOccupied()
      ? "seated: " + helper.GetCurrentSittingPlayer().displayName
      : "not seated yet: check again next frame";
  ```

- TextMeshPro Essential Resources: a Creator Companion project lacks them, and the SDK's "TextMeshPro (VRC)" UI items
  and any TextMeshPro label throw until they are imported (TMP opens its importer window instead). Import them once,
  before any UI: Window > TextMeshPro > Import TMP Essential Resources, or from a script (the import finishes on a
  later editor update; then `Assets/TextMesh Pro/Resources/TMP Settings.asset` exists). This route imported them in
  Unity 2022.3.22f1 with TextMeshPro 3.0.6 on 2026-10-17:

  ```csharp
  var tmp = UnityEditor.PackageManager.PackageInfo.FindForAssetPath("Packages/com.unity.textmeshpro/package.json");
  if (tmp == null) return "TextMeshPro package not found";
  AssetDatabase.ImportPackage(
      System.IO.Path.Combine(tmp.resolvedPath, "Package Resources", "TMP Essential Resources.unitypackage"), false);
  return "importing from " + tmp.resolvedPath;
  ```

- Clickable UI: read the canvas against the checklist in `../SKILL.md` (section 4):

  ```csharp
  var canvas = GameObject.Find("Menu").GetComponent<Canvas>();
  bool worldSpace = canvas.renderMode == RenderMode.WorldSpace;
  bool raycaster = canvas.GetComponent<UnityEngine.UI.GraphicRaycaster>() != null;
  bool uiShape = canvas.GetComponent<VRC.SDK3.Components.VRCUiShape>() != null;
  bool eventSystem = UnityEngine.Object.FindObjectsOfType<UnityEngine.EventSystems.EventSystem>(true).Length > 0;
  int layer = canvas.gameObject.layer;
  bool layerOk = layer != LayerMask.NameToLayer("UI") && layer != LayerMask.NameToLayer("UiMenu");
  bool navigationNone = canvas.GetComponentsInChildren<UnityEngine.UI.Selectable>(true)
      .All(s => s.navigation.mode == UnityEngine.UI.Navigation.Mode.None);
  return $"worldSpace {worldSpace}, raycaster {raycaster}, uiShape {uiShape}, eventSystem {eventSystem}, " +
         $"layer {layerOk}, navigation None {navigationNone}";
  ```

  Run it in Edit mode: in Play, ClientSim's own EventSystem is there whatever the scene has.
- Button to Udon: VRChat lets UI events call only listed targets (on an UdonBehaviour: `SendCustomEvent`, `Interact`,
  `RunProgram`, `enabled`). Use `SendCustomEvent`; the method it names must be public, take no parameters and start
  with `_`, so it cannot be called over the network:

  ```csharp
  var button = GameObject.Find("Menu/LightButton").GetComponent<UnityEngine.UI.Button>();
  var target = GameObject.Find("LightSwitch").GetComponent<VRC.Udon.UdonBehaviour>();
  UnityEditor.Events.UnityEventTools.AddStringPersistentListener(button.onClick, target.SendCustomEvent, "_Toggle");
  EditorUtility.SetDirty(button);
  UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(button.gameObject.scene);
  return button.onClick.GetPersistentEventCount() + " listener(s), first " + button.onClick.GetPersistentMethodName(0);
  ```

  Then save, reopen and read `GetPersistentMethodName(0)` back. On a prefab instance, record the change as for the
  station.

## Switching the build target

Done at build time, not during setup. Check the module, switch, and switch back to Windows afterwards; each switch
reimports every texture for the new target and recompiles scripts, which can take minutes. Wait until
`EditorApplication.isCompiling` is false, then read `EditorUserBuildSettings.activeBuildTarget`.

```csharp
if (!BuildPipeline.IsBuildTargetSupported(BuildTargetGroup.Android, BuildTarget.Android))
    return "Android Build Support is not installed";
bool switched = EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.Android, BuildTarget.Android);
return switched + ", active target " + EditorUserBuildSettings.activeBuildTarget;
```

- iOS, with the same guard (without the module the call returns false and logs "Switching to iOS:iOSSupport is
  disabled"):

  ```csharp
  if (!BuildPipeline.IsBuildTargetSupported(BuildTargetGroup.iOS, BuildTarget.iOS))
      return "iOS Build Support is not installed";
  bool switched = EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.iOS, BuildTarget.iOS);
  return switched + ", active target " + EditorUserBuildSettings.activeBuildTarget;
  ```

- Back to Windows: `EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.Standalone,
  BuildTarget.StandaloneWindows64)`.

## Validation while signed out

The Builder tab needs a signed-in SDK. Signed out, the checks behind its validation list can still run by reflection
on a hidden `VRCSdkControlPanel` and a `VRCSdkControlPanelWorldBuilder`. None of these calls needs an open window
(Worlds SDK 3.10.5 source). The snippet below reports, in the SDK's own wording:

- the Unity version against 2022.3.22f1 (the SDK's own comparison needs its remote config, so it is skipped signed
  out), the layer and collision-matrix state, and the build's blocking error when either is not set up;
- the Builder's gate (`IsValidBuilder`: no descriptor, several Pipeline Managers) and its several-descriptors error;
- `CheckProjectSetup`, and `OnGUISceneCheck` on every descriptor, tagged with the descriptor's name when there are
  several;
- the builtin-mesh and PostProcessVolume warnings. SDK 3.10.5 computes them before its `ResetIssues`, so its list
  shows them only next to the several-descriptors error; this reports them always.

It skips what needs a sign-in: blueprint and ownership checks, the account's iOS check, the build-time validators and
the size limit. The Builder stops at its first gate or several-descriptors message; this keeps going, so it can list
more than the Builder shows.

- **Never open the Control Panel for this** (`EditorWindow.GetWindow`). Unity then saves the window's rect to the
  machine-wide EditorPrefs (`VRCSdkControlPanelx`, `y`, `w`, `h`, from `ContainerWindow.SaveGeometry`), and a
  headless editor saved zeros there (2026-10-17).
- **Signed out holds only where no credentials are saved.** In an interactive editor, opening the panel signs in
  automatically with saved credentials (`InitAccount`). The hidden panel never calls it.
- **Not during an upload.** Destroying the hidden panel raises the SDK's `OnSdkPanelDisable`, on which the world
  builder cancels any upload in progress.

```csharp
var flags = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
var panelType = typeof(VRCSdkControlPanel);
var worldType = typeof(VRC.SDK3.Editor.VRCSdkControlPanelWorldBuilder);
bool layers = UpdateLayers.AreLayersSetup(), matrix = UpdateLayers.IsCollisionLayerMatrixSetup();
var report = new List<string>
{
    "Unity " + Application.unityVersion + (Application.unityVersion == "2022.3.22f1" ? "" : " (expected 2022.3.22f1)"),
    "layers set up " + layers + ", collision matrix set up " + matrix
};
if (!layers || !matrix)
    report.Add("GUIErrors: You must address Layers and Collision Matrix issues before you can build.");
// A hidden panel, never shown. Restore the statics its constructor and OnDestroy change.
var previousWindow = VRCSdkControlPanel.window;
var accountFlags = new[] { "isInitialized", "signingIn" }
    .Select(n => panelType.GetField(n, flags)).Where(f => f != null).ToList();
var savedFlags = accountFlags.Select(f => f.GetValue(null)).ToList();
var panel = ScriptableObject.CreateInstance<VRCSdkControlPanel>();
try
{
    var world = new VRC.SDK3.Editor.VRCSdkControlPanelWorldBuilder();
    world.RegisterBuilder(panel);
    panel.ResetIssues();
    string gate;
    if (!world.IsValidBuilder(out gate)) report.Add("GUIErrors: " + gate.Replace("\n", " "));
    worldType.GetMethod("FindScenes", flags).Invoke(world, null);
    var scenes = (VRC.SDKBase.VRC_SceneDescriptor[])worldType.GetField("_scenes", flags).GetValue(world)
        ?? new VRC.SDKBase.VRC_SceneDescriptor[0];
    if (scenes.Length > 1)
        report.Add("GUIErrors: A Unity scene containing a VRChat Scene Descriptor should only contain one"
            + " Scene Descriptor.");
    // Two warnings the Builder computes and then clears with ResetIssues before showing its list.
    var meshCheck = worldType.GetMethod("ShouldShowPrimitivesWarning", flags);
    var meshUsers = ((System.Collections.IList)meshCheck.Invoke(null, null))
        .Cast<Component>().Select(c => c.name).ToList();
    if (meshUsers.Count > 0)
        report.Add("GUIWarnings: Udon Objects reference builtin Unity mesh assets, this won't work. Consider making"
            + " a copy of the mesh to use instead. (" + string.Join(", ", meshUsers) + ")");
    var volumeType = (Type)worldType.GetField("_postProcessVolumeType", flags).GetValue(null);
    if (volumeType != null && Camera.main != null && Camera.main.GetComponentInChildren(volumeType) != null)
        report.Add("GUIWarnings: Scene has a PostProcessVolume on the Reference Camera (Main Camera). This Camera is"
            + " disabled at runtime. Please move the PostProcessVolume to another GameObject.");
    panelType.GetMethod("CheckProjectSetup", flags).Invoke(panel, null);
    foreach (var scene in scenes)
        worldType.GetMethod("OnGUISceneCheck", flags).Invoke(world, new object[] { scene });
    foreach (var field in new[] { "GUIErrors", "GUIWarnings", "GUIInfos" })
    {
        var issues = (System.Collections.IDictionary)panelType.GetField(field, flags).GetValue(panel);
        foreach (System.Collections.DictionaryEntry entry in issues)
        {
            var subject = (UnityEngine.Object)entry.Key;
            string suffix = scenes.Length > 1 && subject != panel ? " (" + subject.name + ")" : "";
            foreach (var issue in (System.Collections.IEnumerable)entry.Value)
                report.Add(field + ": " + issue.GetType().GetField("issueText").GetValue(issue) + suffix);
        }
    }
}
finally
{
    UnityEngine.Object.DestroyImmediate(panel);
    VRCSdkControlPanel.window = previousWindow;
    for (int i = 0; i < accountFlags.Count; i++) accountFlags[i].SetValue(null, savedFlags[i]);
}
return string.Join("\n", report);
```

Do not plan on a local build without signing in: the SDK's export starts with a credentials check. Leave the size to
the user's first Build & Test or upload, and record the size the Builder reports.

## ClientSim from a script

- Enter Play mode with the world scene open; ClientSim spawns the local player.
- Find an UdonBehaviour with `GetComponent<VRC.Udon.UdonBehaviour>()` on its GameObject. Press it with
  `udonBehaviour.Interact()`.
- ClientSim raises `OnDeserialization` only for synced Player Objects, so simulate a received update with
  `udonBehaviour.SetProgramVariable("<syncedField>", value)`, then
  `udonBehaviour.SendCustomEvent("_onDeserialization")`.
- Late-join logic: in a fresh Play session (`Start` has run with the default state), make a remote player the owner
  first, because the local player is the master and owns everything, and correct code often skips applying received
  state on the owner (`if (!Networking.IsOwner(gameObject))`). Then set a non-default state and fire the event; the
  scene must show that state, as a late joiner's would (`LightSwitch` and `_isOn` are this example's names):

  ```csharp
  VRC.SDK3.ClientSim.ClientSimMain.SpawnRemotePlayer("LateJoiner");
  var players = new VRC.SDKBase.VRCPlayerApi[VRC.SDKBase.VRCPlayerApi.GetPlayerCount()];
  VRC.SDKBase.VRCPlayerApi.GetPlayers(players);
  var remote = players.FirstOrDefault(p => p != null && !p.isLocal);
  if (remote == null) return "no remote player: is Play mode running with ClientSim?";
  var target = GameObject.Find("LightSwitch");
  VRC.SDKBase.Networking.SetOwner(remote, target);
  var behaviour = target.GetComponent<VRC.Udon.UdonBehaviour>();
  behaviour.SetProgramVariable("_isOn", true);
  behaviour.SendCustomEvent("_onDeserialization");
  return "owner now " + VRC.SDKBase.Networking.GetOwner(target).displayName;
  ```

  This checks the logic only; the real late-joiner test needs a private upload and two accounts.
- ClientSim does not simulate what remote players receive (its remote players are stand-ins): networking needs Build
  & Test with 2+ clients, and late joiners a private upload.
- Exiting Play mode leaves the scene flagged dirty with nothing changed: reopen it from disk with
  `UnityEditor.SceneManagement.EditorSceneManager.OpenScene(path)` instead of saving.
- If MCP resources are unreadable from a subagent, read editor state through `execute_code`:
  `EditorApplication.isCompiling`, `EditorApplication.isPlaying`, and
  `UnityEngine.SceneManagement.SceneManager.GetActiveScene().isDirty`.
