# Udon behaviours from a script (Unity MCP)

For an agent driving the Unity editor through Unity MCP. `execute_code` wraps the C# in a static method with only
`using System; System.Collections.Generic; System.Linq; System.Reflection; UnityEngine; UnityEditor;` (MCP for Unity,
read 2026-10-17), so write `UnityEngine.Object` rather than a bare `Object` (ambiguous) and give every other type its
full name, as below. The method returns `object`: end every path with `return` (a string to report). Instead of
`Tuple` (Unity's ExCSS.Unity also defines `System.Tuple`: CS0433) use `KeyValuePair`, a value tuple or an anonymous
type; a class cannot be declared inside the body (CS1513). The APIs were checked against the UdonSharp and SDK sources
in Worlds SDK 3.10.5 on 2026-10-17, and the snippets compiled under that exact wrapper in Unity 2022.3.22f1.

## Adding a behaviour

1. Write the `.cs` file, let the editor compile it, and check the console (`read_console`) once
   `EditorApplication.isCompiling` is false.
2. Give it a program asset next to it: only the editor's own "create script" flow makes one, so a script written to
   disk needs `var asset = ScriptableObject.CreateInstance<UdonSharp.UdonSharpProgramAsset>();`,
   `asset.sourceCsScript = AssetDatabase.LoadAssetAtPath<MonoScript>(csPath);`, then
   `AssetDatabase.CreateAsset(asset, <same path with .asset>)`. One script, one program asset.
3. Add it with `UdonSharpEditor.UdonSharpUndo.AddComponent(gameObject, script.GetClass())`, where `script` is the
   script's `MonoScript`; its backing UdonBehaviour is
   `UdonSharpEditor.UdonSharpEditorUtility.GetBackingUdonBehaviour(behaviour)`.
4. Before saving the scene, read the backing behaviour's `SyncMethod` and set it to the class's mode, for example
   `backing.SyncMethod = VRC.SDKBase.Networking.SyncType.Manual;`. Observed 2026-10-16 (SDK 3.10.5): `AddComponent`
   created the UdonBehaviour as Continuous under a `Manual` class. UdonSharp corrects it on the next scene open,
   Play-mode change or script reload, so a save before then stores the wrong mode.
5. Set its public fields on the UdonSharpBehaviour, save the scene, then reopen it and read the fields back to prove
   the wiring was stored.

## Testing in ClientSim

- Enter Play mode with the world scene open; ClientSim spawns the local player.
- Press an interactable: `GetComponent<VRC.Udon.UdonBehaviour>()` on its GameObject, then `.Interact()`.
- ClientSim raises `OnDeserialization` and `OnPostSerialization` only for synced Player Objects, so simulate a received
  update: `udonBehaviour.SetProgramVariable("<syncedField>", value)`, then
  `udonBehaviour.SendCustomEvent("_onDeserialization")`.
- Late-join logic: in a fresh Play session (`Start` has run with the default state), make a remote player the owner
  first. The local player is the master and owns everything, and correct code often skips applying received state on
  the owner (`if (!Networking.IsOwner(gameObject))`, as UdonSharp's own GlobalToggleObject sample does). Then set a
  non-default state and fire the event; the scene must show that state, as a late joiner's would (`LightSwitch` and
  `_isOn` are this example's names):

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

  This checks the logic only: the Builder's Build & Test cannot add a late client, so the real test is a private
  upload with two accounts (`vrchat-world-sdk-setup`).
- ClientSim does not simulate what remote players receive (its remote players are stand-ins): networking needs Build
  & Test with 2+ clients, and late joiners a private upload.
- Exiting Play mode leaves the scene flagged dirty with nothing changed: reopen it from disk with
  `UnityEditor.SceneManagement.EditorSceneManager.OpenScene(path)` instead of saving.

## Reviewing a script

- No `Update`, `LateUpdate` or `FixedUpdate` unless the design needs one per-frame step.
- Every method used with `SendCustomEvent`, a delayed event, a UI event or an animation event is public and starts
  with `_`; every method sent over the network carries `[NetworkCallable]`.
- One sync mode per GameObject, and no VRC Object Sync next to a Manual behaviour (`networking-limits.md`).
