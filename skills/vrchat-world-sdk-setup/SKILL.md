---
name: vrchat-world-sdk-setup
description: VRChat world SDK setup and testing - players spawn wrong or fall forever, cannot interact or click UI, wrong layers after upload, SDK validation or build fails, ClientSim and Build & Test on PC, Quest and iOS, pickups, Object Sync, stations, mirrors, scene descriptor, publish fields, one blueprint ID across platforms. Scripts (vrchat-udon); performance (vrchat-world-optimization); mirror lighting (vrchat-lighting-and-baking).
---

# VRChat world SDK setup

Everything that makes a Unity scene a VRChat world, from project to "ready to upload". Uploading is the user's: it
publishes under their account, so prepare everything and hand over. Shelf-life facts carry a source and a check date
(Sources, bottom). What the SDK itself does, read from its code, is in `references/sdk-observed.md` with the SDK
version; doing these steps from a script through Unity MCP is in `references/unity-mcp.md`. VRChat changes the SDK:
re-check anything that disagrees with what the editor shows.

## 1. Project, in this order

1. **Create** the project in the VRChat Creator Companion (VCC) with the Worlds SDK, and update it there. UdonSharp and
   ClientSim ship inside the Worlds SDK (since 3.4.0): never add the standalone UdonSharp or ClientSim packages.
2. **Unity 2022.3.22f1, exactly.** Never upgrade: VRChat's Unity 6 build is a client beta, and its servers reject
   uploads from Unity 6. With Unity MCP, confirm the version from `mcpforunity://instances` before anything else.
3. **Sign in to the SDK** (`VRChat SDK > Show Control Panel` > Authentication). Signed out, the Control Panel shows
   only Settings and Authentication: no Builder tab, so none of its buttons, validation, Build & Test or upload.
   Without the user's sign-in, do the Builder steps from a script (`references/unity-mcp.md`).
4. **Layers and collision matrix, before placing anything.** Builder > **Setup Layers for VRChat**, then **Setup
   Collision Matrix** (each asks to confirm); signed out, `UpdateLayers.SetupEditorLayers()` then
   `UpdateLayers.SetupCollisionLayerMatrix()` do the same. Until both are done the build is blocked, even when every
   other validation passes. A Creator Companion project can show VRChat's layer names and still fail the check, so
   run both rather than judging by eye. The layer setup pushes custom layers down the list, so anything already on
   them needs reassigning.
5. **Build modules**: Android and iOS Build Support in the Unity Hub when the world is cross-platform (section 8).
6. **Render pipeline**: Built-in. No URP or HDRP.

## 2. Scene descriptor

Builder (signed in) > **Add a VRCSceneDescriptor** adds a `VRCWorld` object, a copy of the SDK's
`Packages/com.vrchat.worlds/Samples/UdonExampleScene/Prefabs/VRCWorld.prefab`; signed out, instantiate that prefab
from a script (`references/unity-mcp.md`). It carries the scene descriptor and the **Pipeline Manager**, which holds
the world's blueprint ID (every platform uploads to that one ID). Exactly one per scene.

| Field | Set it to |
|---|---|
| Spawns | One or more dedicated empty transforms on walkable floor, facing into the world. The SDK's `VRCWorld` lists its own transform as the only spawn, so players spawn wherever `VRCWorld` stands: replace it, assigning the new list in one step (while the descriptor's Inspector is open, an emptied list is refilled with `VRCWorld`'s transform). An empty list is a build-blocking SDK error |
| Spawn Radius | About 1-2 m in a busy spawn so players do not stack; 0 for exact placement |
| Spawn Order | First, Sequential, Random, or Demo (the spawn is the centre of the player's room-scale space) |
| Spawn Orientation | Default (aligns the player with the spawn point) unless room-scale alignment matters |
| Reference Camera | A disabled camera whose settings the player camera copies: clip planes (house guidance: near 0.01-0.05 m, far just beyond the world's size) and, on PC, the post-processing layer |
| Respawn Height -Y | A little below the lowest walkable surface. Too high and players respawn while walking downhill; the SDK warns when a spawn is below it |
| Object Behaviour At Respawn Height | Respawn (the default: objects return to where they started) or Destroy, for pickups that fall below Respawn Height (field `ObjectBehaviourAtRespawnHeight`, `VRC_SceneDescriptor.RespawnHeightBehaviour.Respawn`). VRChat's page says pickups respawn or are destroyed without mentioning Object Sync; ClientSim does it only for objects with VRC Object Sync |
| Forbid User Portals | On for worlds where dropped portals would break the experience |
| Interact Passthrough | User layers (22-31) that interaction rays pass through; interaction through user layers is blocked otherwise |
| Dynamic Prefabs, Dynamic Materials | Ignore: deprecated and unused in SDK3, never a user action |
| Unity Version | Leave it: a stale value from the template is cosmetic |

### Starting from the SDK template scene

The Creator Companion's Worlds template opens `VRCDefaultWorldScene`:

| Template object | Do |
|---|---|
| `VRCWorld` | Keep, and set the fields above: its Respawn Height is -100 m and its only spawn is its own transform |
| `Floor`, a 100 x 100 m plane at y 0 | Remove it if the world has its own floor: it z-fights a floor at the same height |
| `Main Camera` (near 0.3, far 1000) | Reuse it as the Reference Camera: disable the Camera component, remove its AudioListener, clear the MainCamera tag, set the clip planes |
| `Directional Light` | Decide in the lighting step (`vrchat-lighting-and-baking`) |
| `EventSystem` | Keep it if the world has UI: VRChat needs one in the scene, and ClientSim brings its own, so a ClientSim test cannot show it is missing. Remove it only when the world has no UI (with ClientSim's it gives a harmless "only one active Event System" warning in Play) |

## 3. Layers

| Layers | Use |
|---|---|
| 0 Default, 11 Environment | World geometry (stickers allowed) |
| 8 Interactive | Geometry and interactables where stickers should be blocked |
| 17 Walkthrough | Colliders players pass through: trigger volumes, non-blocking props |
| 13 Pickup, 14 PickupNoEnvironment | Pickups. Pickup does not collide with players; PickupNoEnvironment collides only with Pickup |
| 22-30 | User layers: free, and VRChat keeps their names and collision settings on upload. Interaction through them is blocked unless they are in Interact Passthrough |
| 15 StereoLeft, 16 StereoRight | Unused by Unity and VRChat: free |
| 2 IgnoreRaycast | Unity raycasts without a layer mask skip it; VRChat's raycasts do not |
| 4 Water | Portals, mirrors and often post-processing volumes. Water never renders in mirrors, so put no geometry here |
| 5 UI, 12 UiMenu | VRChat's pointer ignores them unless the menu is open: world UI goes on Default or another interactable layer |
| 9 Player, 10 PlayerLocal, 18 MirrorReflection | Other players, the local player, and the local player's mirror copy: never put world objects here |
| 3 Item, 6, 7, 21 | Reserved: objects on them are moved to Default on upload |
| 1 TransparentFX, 19 InternalUI, 20 HardwareObjects, 31 | Used by Unity or VRChat (flares and debug visuals, menus, controllers, editor preview): avoid |

VRChat resets its built-in layers' names and collision matrix on upload; only user-layer changes survive. Put custom
collision rules on layers 22-30.

## 4. Components

Only allowlisted components work in an uploaded world; a custom MonoBehaviour that is not Udon does nothing.
Editor-only helpers go under an `EditorOnly`-tagged GameObject, which Unity leaves out of the build. A component that
implements `VRC.SDKBase.IEditorOnly` only passes world validation: it still ships, and the client removes it as a
component that is not allowlisted.

| Need | Component | Notes |
|---|---|---|
| Pick up an object | VRC Pickup + Rigidbody + collider + VRC Object Sync | Pickup layer (13). Object Sync shows its movement to other players and makes it respawn below Respawn Height (Object Behaviour At Respawn Height = Respawn); without it other players never see it move, and ClientSim never respawns it |
| Sync a moving object | VRC Object Sync | One per synced object. Never on a GameObject with a Manual-sync UdonBehaviour or a VRC Object Pool: the SDK reports an error that blocks the build. Network budget: `vrchat-udon` |
| Seats, vehicles | VRC Station | A collider (usually a trigger), an UdonBehaviour whose Interact calls `Networking.LocalPlayer.UseAttachedStation()`, and enter and exit points (Station Enter / Exit Player Location). The SDK's `Packages/com.vrchat.worlds/Samples/UdonExampleScene/Prefabs/VRCChair/VRCChair3.prefab` has all of it: start from it, record your changes on the instance and read them back (`references/unity-mcp.md`). Test sitting and leaving in ClientSim |
| Mirror | VRC Mirror Reflection | Reflect Layers: Player (9) and MirrorReflection (18, the local player); never PlayerLocal (10, the headless first-person copy); Water never renders. Off by default behind a toggle; cost, resolution and mirror occlusion: `vrchat-lighting-and-baking` |
| Positional sound | AudioSource + VRC Spatial Audio Source | The SDK flags 3D sources without one. On mobile VRChat disables audio sources on avatars; for worlds it says only "restricted", without detail. They cost CPU: keep them few and test on the device |
| Portal to another world | VRC Portal Marker | |
| Avatar pedestal | VRC Avatar Pedestal | |
| UI that players click | Canvas + VRC Ui Shape | First import TextMeshPro's essentials once (Window > TextMeshPro > Import TMP Essential Resources): without them TMP items and labels fail. Easiest: GameObject > UI > any "TextMeshPro (VRC)" item with no canvas selected or in the scene: it makes a World Space canvas on Default with a Graphic Raycaster, a VRC Ui Shape and an EventSystem. With a canvas present it nests the item there, on that canvas's layer. Unity's own GameObject > UI > Canvas lands on 5 UI in Screen Space: fix both. Checklist below |
| Logic | UdonSharp behaviours | Design rules: `vrchat-udon` |

**UI not clickable?** Check every line; ClientSim passing proves nothing about the EventSystem, since it brings its own.

- [ ] Canvas Render Mode World Space, scaled down (about 0.001-0.01), its Z axis facing away from the viewer
- [ ] Canvas on Default or another interactable layer, never 5 UI
- [ ] VRC Ui Shape on the Canvas (it adds and sizes its own box collider on load), and no other collider in front
- [ ] Graphic Raycaster on the Canvas
- [ ] An EventSystem in the scene (keep the template's)
- [ ] Navigation None on buttons, toggles and sliders
- [ ] The element being clicked has an Image with Raycast Target on
- [ ] In the client, debug view 0 (the VRC_UiShape overlay) shows what the pointer hits

## 5. Colliders and walkability

- Every walkable surface needs a collider; decorative clutter usually needs none.
- Simple colliders (boxes, low-poly shells) for walls and floors; never the render mesh of a detailed piece.
- Block falls off ledges players should not leave with invisible box colliders.
- Stairs: a ramp collider under the visible steps. If they must stay stepped, keep each step 0.2 m high or less
  (house guidance: VRChat publishes no step height, and ClientSim's player climbs 0.5 m, so a ClientSim walk does not
  prove a step is comfortable).
- Colliders players should pass through go on Walkthrough (17).
- Check by walking it: ClientSim in Play mode, every room, every stair, every doorway.

## 6. Testing

| Test | How | Catches |
|---|---|---|
| ClientSim | Press Play in the world scene; Escape opens its menu (respawn, spawn remote players) | Spawns, interacts, pickups, stations, UI, local Udon logic, EditorOnly removal |
| Build & Test, PC | Builder > Build & Test Your World, after setting the **VRChat Client** path (bottom of the Settings tab; without it worlds may not launch). **Clients** 2 or more for network tests; **Force Non-VR** for desktop | Real client behaviour, networking between the clients started together |
| Build & Reload | With Enable World Reload on, rebuild without restarting the clients | Fast iteration |
| Late joiner | Not possible with the Builder's buttons: every Build & Test (and Test Last Build) opens a new room, so a client started later is alone and shows the default state (a client started by hand with the same launch arguments might join; untested). Check the late-join logic with a simulated `OnDeserialization` (`references/unity-mcp.md`). The real test is the user's: a private upload where one account changes the state and a second account joins afterwards | Late joiners getting the current state |
| Build & Test, Android / Quest | Builder platform Android; ADB copies the build to a device on USB (steps: `references/cross-platform.md`) | Mobile shaders, performance and memory on hardware |
| Build & Test, iOS | Builder platform iOS (always listed, greyed out without iOS Build Support; the account must support iOS, section 8); VTP over the local network, SDK 3.8.1 and later (steps: `references/cross-platform.md`) | The same on iOS |

ClientSim does not simulate what remote players receive (its remote players are stand-ins): networking needs Build &
Test with several clients.
Every Build & Test needs a signed-in SDK. Driving ClientSim from a script: `references/unity-mcp.md`.

## 7. Publish fields (prepare them for the user)

In the Builder's world panel: **Name**, **Description**, **Maximum Capacity**, **Recommended Capacity**, **Content
Warnings**, **Tags**, **World Debugging**, **Thumbnail**. Clear every SDK validation message (apply the offered auto
fixes where they make sense), check the console is free of errors, then hand over: the user presses **Build &
Publish Your World Online** (it needs their account at the "New User" trust rank or higher). Without a signed-in SDK
only part of the validation can run: `references/unity-mcp.md`.

## 8. Cross-platform (PC, Android / Quest, iOS)

Mobile means Android and iOS: VRChat applies its Android/Quest guidelines and limits to iOS too. VRChat's order is
modules, switch, validate, optimise, upload; a world that is cross-platform from the start splits it in two, so later
work is planned for the platform hardest to fit (steps, errors, shaders: `references/cross-platform.md`):

1. **Early, right after the scene setup, with no switch:** Android and iOS Build Support; texture overrides on both the
   Android and the iOS tab (`vrchat-texture-and-vram`); mobile materials; objects that exist on one platform only.
   iOS also needs the user's account to support it: ask before planning an iOS build.
2. **Later:** one bake for every platform (the lighting step). Before the optimisation audit, switch to each mobile
   target (a full reimport), clear its errors (Android: texture compression ASTC) and run ClientSim on it (in a
   `vrchat-world-orchestration` build, T-BUILD does this after T-OPT's estimates, and switches back to Windows at the
   end). Then the
   mobile budgets (`vrchat-world-optimization`) and the hard limit of **100 MB** after build-time compression
   (VRChat's MB is 2^20 bytes: 104,857,600 bytes) on Android and iOS alike; Build & Test on each device (section 6);
   every platform uploaded to the **same blueprint ID** (one project keeps it on the Pipeline Manager); then switch
   back to Windows. Post-processing and cloth are disabled on mobile.

## 9. Before handing over

- [ ] Unity 2022.3.22f1; Setup Layers for VRChat and Setup Collision Matrix done (either missing blocks the build)
- [ ] One scene descriptor; at least one spawn, on a floor and facing in; respawn height below the lowest floor
- [ ] Reference camera assigned and its clip planes set
- [ ] No objects on reserved or player layers; custom collision only on 22-30; world UI not on layer 5
- [ ] Every walkable area tested in ClientSim; interactions work; pickups carry VRC Object Sync and respawn when
      dropped below Respawn Height; world UI passes the "UI not clickable" checklist
- [ ] Network behaviour tested with Build & Test, 2+ clients; late-join logic checked with a simulated
      `OnDeserialization`, and the user told the real late-joiner test needs a private upload
- [ ] Each platform being published passes SDK validation with no console errors; texture overrides set for each
      mobile platform in it (iOS only when the user wants it and their account supports it); mobile builds under
      100 MB; each platform tested on its device
- [ ] Publish fields drafted; thumbnail captured

## Sources (checked 2026-10-17)

- Unity version: https://creators.vrchat.com/sdk/upgrade/current-unity-version/ ; uploads from Unity 6 rejected:
  https://ask.vrchat.com/t/developer-update-25-june-2026/48618
- UdonSharp and ClientSim inside the Worlds SDK: https://creators.vrchat.com/releases/release-3-4-0
- Scene descriptor (Dynamic Prefabs and Materials deprecated): https://creators.vrchat.com/worlds/components/vrc_scenedescriptor/
- Layers (updated 2026-08-17): https://creators.vrchat.com/worlds/layers/
- Allowlisted components: https://creators.vrchat.com/worlds/whitelisted-world-components/
- Mirror component: https://creators.vrchat.com/worlds/components/vrc_mirrorreflection/
- TextMeshPro and its Essential Resources import (2024-05-21): https://creators.vrchat.com/worlds/components/textmeshpro/
- Pickup (2026-06-23), Station (2024-12-10) and UI Shape (2025-05-06):
  https://creators.vrchat.com/worlds/components/vrc_pickup/ ,
  https://creators.vrchat.com/worlds/components/vrc_station/ , https://creators.vrchat.com/worlds/components/vrc_uishape/
- ClientSim respawns only position-synced objects:
  https://creators.vrchat.com/worlds/clientsim/systems/runtime/synced-object-manager
- ClientSim: https://creators.vrchat.com/worlds/clientsim/
- First world, Build & Test and the publish fields: https://creators.vrchat.com/worlds/creating-your-first-world
- Build & Test clients, rooms and the VRChat Client path: https://creators.vrchat.com/worlds/udon/using-build-test
- Cross-platform order, mobile limits, audio, iOS and device testing: the sources in `references/cross-platform.md`
- SDK behaviour read from its code (empty spawns, Object Sync errors, size constants, template contents, ClientSim's
  step height): `references/sdk-observed.md`
