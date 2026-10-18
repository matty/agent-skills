# What the SDK does, read from its code

Behaviour read from the Worlds SDK's own sources and assemblies (the project's `Packages/com.vrchat.worlds` and
`Packages/com.vrchat.base`), not from VRChat's documentation. Every row names the SDK version and the date it was
read. After an SDK update, re-check the rows the work depends on before trusting them; where VRChat's docs say
otherwise, the newer of the two wins and the row gets fixed.

## Validation and build (Worlds SDK 3.10.5, read 2026-10-17)

| Behaviour | Where | Consequence |
|---|---|---|
| Signed out, the Control Panel allows only the Settings and Authentication tabs: no Builder | `VRCSdkControlPanel.cs` ("When the user isn't logged in - we only allow Settings and Authentication tabs") | Sign in first, or do the Builder steps from a script |
| Opening the Control Panel signs in automatically when credentials are saved: `InitAccount` (from the menu's `Init`, or the account GUI's first draw) runs `ApiCredentials.Load()`, then `APIUser.InitialFetchCurrentUser` | `VRCSdkControlPanelAccount.cs` | "Signed out" holds only on a machine with no saved credentials |
| Showing an editor window makes Unity save its rect to the machine-wide EditorPrefs under the window's type name (`VRCSdkControlPanelx`, `y`, `w`, `h`, plus `z` for maximised); a headless editor saved zeros (seen 2026-10-17) | Unity's `ContainerWindow.SaveGeometry` (Unity 2022.3.22f1) | Scripted checks use a hidden panel (`ScriptableObject.CreateInstance`), never `GetWindow` |
| The panel's constructor sets the static `VRCSdkControlPanel.window`; destroying a panel raises `OnSdkPanelDisable`, on which the world builder cancels any upload in progress, and its `OnDestroy` resets the static `isInitialized` and `signingIn` | `VRCSdkControlPanel.cs`, `VRCSdkControlPanelAccount.cs`, `VRCSdkControlPanelWorldBuilder.HandleSdkPanelDisable` | A script with a hidden panel restores those statics and never runs during an upload |
| The Builder's gate `IsValidBuilder` shows only its message when the scene has several Pipeline Managers ("Multiple Pipeline Managers found in scene. Please remove all but one.") or no descriptor ("A VRCSceneDescriptor or VRCAvatarDescriptor is required to build VRChat SDK Content"). With several descriptors the validation list shows "A Unity scene containing a VRChat Scene Descriptor should only contain one Scene Descriptor." and runs no scene check | `IsValidBuilder`, `CreateValidationsGUI` | These hide every other message: fix them first |
| The validation list adds the builtin-mesh warning ("Udon Objects reference builtin Unity mesh assets, this won't work. ...") and the PostProcessVolume-on-Main-Camera warning, then calls `ResetIssues`, which clears both before the list is shown; only the several-descriptors path, which returns before the reset, shows them | `CreateValidationsGUI` | A script that wants them runs `ShouldShowPrimitivesWarning` and the camera check itself (`unity-mcp.md`) |
| Add a VRCSceneDescriptor runs `GameObject.Instantiate` on `Packages/com.vrchat.worlds/Samples/UdonExampleScene/Prefabs/VRCWorld.prefab` and names the copy `VRCWorld` | `VRCSdkControlPanelWorldBuilder.cs` | A script can add the descriptor the same way |
| Every Build & Test and Test Last Build on PC launches its clients with a new random room (`--url=create?roomId=` plus random digits); the clients of one launch share that room and identical arguments | `VRCWorldAssetExporter.RunWorldTestDesktop` in `VRCSDK3-Editor.dll` | A client started later from the Builder is in a room of its own: no late-joiner test with the Builder's buttons (one started by hand with the same arguments might join; untested) |
| The platform dropdown always lists Windows, Android and iOS, locking an option only when its build module is missing. The account-gated `VRCSdkControlPanelBuilder.GetBuildTargetOptions` has no callers | `PlatformSwitcherPopup` (`VRC_EditorTools.GetBuildTargetOptionsAsEnum`, `IsBuildTargetSupported`) | An iOS entry in the list says nothing about the account |
| With the account's platforms loaded (signed in) and no iOS support, an active iOS target is the error "iOS is not supported as a build target.", with no auto-fix; signed out it cannot fire | `VRCSdkControlPanelBuilder.CheckProjectSetup` (`ApiUserPlatforms.CurrentUserPlatforms`) | iOS needs an account that has it |
| With Android active and Build Settings' texture compression not ASTC, the error "Default texture format on Android should be set to the newer ASTC format ..." blocks the build; its auto-fix sets ASTC. While any other target is active, the SDK sets ASTC itself | `VRCSdkControlPanelBuilder.CheckProjectSetup`, `EnvConfig.SetTextureSettings` | Only a hand-changed setting, or a project already on Android, meets the error |
| The build adds the error "You must address Layers and Collision Matrix issues before you can build." when `UpdateLayers.AreLayersSetup()` or `UpdateLayers.IsCollisionLayerMatrixSetup()` is false, even if every other check passes | `VRCSdkControlPanelWorldBuilder.cs`, build path | Run Setup Layers for VRChat and Setup Collision Matrix first |
| `UpdateLayers` is a class in the global namespace, with no `VRC.Editor.` prefix; the Builder buttons call `SetupEditorLayers()` and `SetupCollisionLayerMatrix()` | `VRCCore-Editor.dll` | Call it as `UpdateLayers.AreLayersSetup()` from a script |
| Setup Layers for VRChat "pushes any custom layers down the layer list. If you have custom layers assigned to gameObjects, you'll need to reassign them." | its confirmation dialog | Set the layers up before placing objects |
| A spawns list with no non-null entry is the error "You must add at least one valid spawn point to the spawns list in your scene descriptor." The build never falls back to the descriptor's own transform (`GetValidatedSpawnList` only drops nulls), and the exporter checks the count again before building. A spawn more than 1000 m from the origin, or below Respawn Height, is a warning | `VerifySpawnPlacement`, `VRC_SceneDescriptor.GetValidatedSpawnList` | At least one spawn transform |
| While the descriptor's Inspector is open, any hierarchy change refills an empty `spawns` array with the descriptor's own transform and logs "Scene Descriptor spawns were empty, adding a default Spawn."; it also adds a missing Pipeline Manager | `VRCSceneDescriptorEditor3.HierarchyChanged` | Assign the new spawns in one step (`descriptor.spawns = new[] { ... }`) |
| World validation leaves components that implement `IEditorOnly` in place (`RemoveIllegalComponents(..., excludeEditorOnly: true)`); only the avatar build strips them (`RemoveAvatarEditorOnly`) | `WorldValidation.cs`, `VRCSDKBase-Editor.dll` | In a world they ship, and the client drops them as not allowlisted; use the EditorOnly tag for editor-only objects |
| "Object Sync cannot share an object with a manually synchronized Udon Behaviour" and "Object Sync cannot share an object with an object pool" are errors | `OnGUISceneCheck` | Keep VRC Object Sync apart from Manual behaviours and pools |
| A 3D AudioSource without a VRC Spatial Audio Source is a "deprecated" warning with a Fix button | `OnGUISceneCheck` | Add VRC Spatial Audio Source to every AudioSource |
| Textures over 8192 px are a warning; 'Box' mip filtering gets a suggestion to switch to 'Kaiser' (or the SDK's DPID setting) | `VerifyMaxTextureSize`, `VerifyTextureMipFiltering` | |
| Android and iOS builds warn "World uses unsupported shader ..." for shaders outside the mobile set | `OnGUISceneCheck` under `UNITY_ANDROID || UNITY_IOS` | A warning only: shaders are not restricted in worlds |
| The Unity-version comparison runs only when the SDK's remote config is loaded (it is fetched after sign-in), and a mismatch is a warning, not an error | `VRCSdkControlPanelBuilder.CheckProjectSetup` | Confirm the editor version yourself when signed out |
| Before building, the world exporter writes the descriptor's gravity, collision matrix and Unity Version from the project, replaces Dynamic Materials with the materials found on the scene's renderers, then saves the scene | `VRCWorldAssetExporter.ExportCurrentSceneResource`, `AssetExporter.FindDynamicContent` (read from the IL; not confirmed in a built bundle) | The template's stale Unity Version and Dynamic Materials entries are cosmetic |
| Exporting a scene for Build & Test or upload starts with a credentials check | `VRC_SdkBuilder.ExportSceneResource` calls `VerifyCredentials` | Building needs a signed-in SDK |

## Size limits (Worlds SDK 3.10.5, `ValidationHelpers` in `VRCSDKBase.dll`, read 2026-10-17)

| Constant | Value | Meaning |
|---|---|---|
| `BYTES_TO_MB` | 1,048,576 | VRChat's MB is 2^20 bytes, including the Builder's "Download Size" and "Uncompressed Size" |
| World, mobile (Android and iOS), compressed | 104,857,600 bytes | The 100 MB limit. Above it the upload stops with "World download size is too large for the target platform" |
| World, mobile, uncompressed | none (-1) | |
| World, PC, compressed and uncompressed | none (-1) | VRChat still asks public worlds to stay under 200 MB |
| Avatars, for comparison | PC 200 / 500 MB, mobile 10 / 40 MB (compressed / uncompressed) | |

## Template scene and the descriptor prefab (Worlds SDK 3.10.5, read 2026-10-17)

- `VRCDefaultWorldScene.unity`: `VRCWorld` with its own transform (at z -2.558) as the only spawn, spawn radius 0.2,
  Respawn Height -100, Unity Version 2019.4.31f1, four template materials in Dynamic Materials; `Floor` (100 x 100 m
  at y 0), `Main Camera` (near 0.3, far 1000), `Directional Light`, `EventSystem`.
- `Samples/UdonExampleScene/Prefabs/VRCWorld.prefab` (what Add a VRCSceneDescriptor copies): its own transform as the
  only spawn, spawn radius 0, Respawn Height -100. VRChat's first-world guide says the same: "By default, players will
  spawn at the location of your VRCWorld prefab."

## Packages, ClientSim and components (Worlds SDK 3.10.5, read 2026-10-17)

- UdonSharp and ClientSim live in `com.vrchat.worlds/Integrations/`; its `package.json` lists `com.vrchat.udonsharp`
  and `com.vrchat.clientsim` as legacy packages, which the Creator Companion removes.
- ClientSim's local player is a CharacterController with step offset 0.5 m and slope limit 50 deg
  (`ClientSimPlayerLocal.prefab`). A ClientSim walk climbs a 0.5 m step, so it cannot show that a step is comfortable.
- ClientSim raises `OnDeserialization` and `OnPostSerialization` only for objects in a synced Player Object
  (https://creators.vrchat.com/worlds/clientsim/), with `success` always true and `byteCount` = 4 x the number of
  serialized properties (`ClientSimUdonEncodeDecode`), not real bytes. Other synced objects need the simulated event
  (`unity-mcp.md`).
- ClientSim's local player is the master, and the master owns every object nobody has claimed
  (`ClientSimPlayerManager.IsOwner`); `ClientSimMain.SpawnRemotePlayer()` adds a remote player at once, and
  `Networking.SetOwner(remote, gameObject)` hands it ownership.
- ClientSim respawns or destroys only position-synced objects that fall below Respawn Height
  (`ClientSimSyncedObjectManager.ProcessPositionSyncedObjects`); VRC Object Sync is the position-synced one
  (`ClientSimObjectSyncHelper`), and a VRC Pickup alone is never respawned (`ClientSimPickupHelper`). The descriptor
  field is `ObjectBehaviourAtRespawnHeight` (`VRC_SceneDescriptor.RespawnHeightBehaviour.Respawn` = 0, the default,
  or `Destroy`), shown as "Object Behaviour At Respawn Height".
- ClientSim adds its own EventSystem and disables the scene's in Play (`ClientSimInputModule.DisableOtherEventSystems`),
  so ClientSim cannot show that a scene lacks one.
- The SDK's GameObject > UI > "TextMeshPro (VRC)" items put the new element in the selected canvas, or else any active
  canvas in the scene, giving it that canvas's layer (`VRCTMP.GetOrCreateCanvasGameObject`, `SetLayerRecursively`).
  Only with no canvas at all do they make one (`VRCTMP.CreateNewUI`): World Space on Default at scale 0.001 with a
  Canvas Scaler, a Graphic Raycaster and a VRC Ui Shape, plus an EventSystem if there is none. Unity's own
  GameObject > UI > Canvas uses layer UI and Screen Space Overlay (`com.unity.ugui` `MenuOptions`).
- UI events may call only listed targets (`VRC.Core.UnityEventFilter`): on an UdonBehaviour `SendCustomEvent`,
  `Interact`, `RunProgram` and `enabled`; also, for example, `GameObject.SetActive` and some AudioSource methods.
- VRC Ui Shape adds and sizes a BoxCollider from the canvas rect when it wakes, if there is none
  (`VRC_UiShape.SetupCollision`).
- `Samples/UdonExampleScene/Prefabs/VRCChair/VRCChair3.prefab`: VRC Station (seated, enter point `Seat`, exit point
  `Exit`), a trigger BoxCollider, and an UdonBehaviour running `StationGraph` (Interact calls `UseAttachedStation`).
  In Play, ClientSim's `VRC.SDK3.ClientSim.ClientSimStationHelper` on the station reports `IsOccupied()` and
  `GetCurrentSittingPlayer()`.
- `VRC_MirrorReflection`'s constructor defaults Disable Pixel Lights and Turn Off Mirror Occlusion to on; the sample
  `VRCMirror` prefab reflects every layer.
- Mobile shaders (`com.vrchat.base/Runtime/VRCSDK/Sample Assets/Shaders/Mobile/`): `VRChat/Mobile/Standard Lite` is a
  surface shader without `noinstancing`, so it has GPU-instancing variants; `VRChat/Mobile/Lightmapped` is an unlit
  vertex/fragment shader with no instancing variant.

## MCP for Unity's `execute_code` (package `com.coplaydev.unity-mcp`, cached version aa5fc638d6, read 2026-10-17)

`ExecuteCode.WrapUserCode` wraps the code in a static method with only `using System; System.Collections.Generic;
System.Linq; System.Reflection; UnityEngine; UnityEditor;`. A bare `Object` is then ambiguous (CS0104) and anything
from another namespace, such as `EditorSceneManager` or `SceneManager`, needs its full name (CS0103 otherwise).

## Observed in use (2026-10-16, Unity 2022.3.22f1, Worlds SDK 3.10.5)

- Exiting Play mode with ClientSim leaves the scene flagged dirty with nothing changed.
- The template's `EventSystem` plus ClientSim's own gives "There can be only one active Event System." in Play.
- Signed out, the Builder's scene checks ran by reflection and reported nothing for a clean scene; no build was
  attempted.
