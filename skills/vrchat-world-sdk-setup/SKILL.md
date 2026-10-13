---
name: vrchat-world-sdk-setup
description: Set up, test and prepare a VRChat world for publishing with the Worlds SDK - Creator Companion project and the required Unity version, the VRC Scene Descriptor (spawns, respawn height, reference camera), VRChat's reserved and free layers, allowlisted and SDK components (pickups, object sync, stations, mirrors, spatial audio, portals), ClientSim testing in Play mode, Build & Test with several clients, the publish fields (capacity, content warnings, tags, thumbnail), and cross-platform PC / Android (Quest) / iOS builds on one blueprint ID. Use when creating or fixing a world scene's VRChat setup, when players spawn wrong, fall forever or cannot interact, when objects end up on the wrong layer after upload, when testing a world before upload, when preparing PC and Quest versions, or when a build or upload fails SDK validation; for Udon script design see udon-performance, for performance and budgets see vrchat-world-optimization, for lighting see vrchat-lighting-and-baking.
---

# VRChat world SDK setup

Everything that makes a Unity scene a VRChat world, from project to "ready to upload". Uploading itself is the
user's: it publishes under their account, so prepare everything and hand over. Facts here carry a source and a check
date (bottom); VRChat changes the SDK, so re-check anything that disagrees with what the editor shows.

## 1. Project

| Item | Rule |
|---|---|
| Project | Created and updated through the VRChat Creator Companion (VCC) with the Worlds SDK. Add UdonSharp from VCC if scripts are C# |
| Unity version | Exactly the one VRChat uses: **2022.3.22f1** (as of the check date). Never "upgrade" the project past it |
| Platform modules | Android (Quest) and iOS build support installed in the Unity Hub when the world is cross-platform |
| Render pipeline | Built-in. No URP/HDRP |

With Unity MCP, confirm the version from `mcpforunity://instances` before anything else.

## 2. Scene descriptor

Control Panel (`VRChat SDK > Show Control Panel`) > Builder > **Add a VRCSceneDescriptor** creates a `VRCWorld`
object. Exactly one per scene.

| Field | Set it to |
|---|---|
| Spawns | One or more empty transforms on walkable floor, facing into the world. Empty list = the VRCWorld object itself |
| Spawn Radius | About 1-2 m in a busy spawn so players do not stack; 0 for exact placement |
| Spawn Order | First, Sequential, Random, or Demo (spawn is the centre of the player's room-scale space) |
| Spawn Orientation | Default (align player with spawn point) unless room-scale alignment matters |
| Reference Camera | A disabled camera whose clip planes the player camera copies: near 0.01-0.05 m, far just beyond the world's size. PC-only post-processing goes on it |
| Respawn Height -Y | A little below the lowest walkable surface. Too high and players respawn while walking downhill |
| Object Behaviour At Respawn | Respawn (pickups return home) or Destroy |
| Forbid User Portals | On for worlds where dropped portals would break the experience |
| Interact Passthrough | Layers whose colliders let interaction rays through (see layers) |

The **Pipeline Manager** on the same object holds the world's blueprint ID; every platform uploads to the same ID.

## 3. Layers

| Layers | Use |
|---|---|
| 0 Default, 11 Environment, 8 Interactive | Free for world geometry and interactables |
| 22-30 | User layers: free, and VRChat keeps their names and collision settings on upload |
| 13 Pickup, 14 PickupNoEnvironment | Pickups (the second collides only with other pickups) |
| 4 Water | VRChat uses it for portals and mirrors; do not put geometry there |
| 9 Player, 10 PlayerLocal, 18 MirrorReflection | Players and mirror rendering: never put world objects here |
| 3 Item, 6, 7, 21 | Reserved: objects on them are moved to Default on upload |
| 1, 5, 12, 19, 20, 31 | Used by VRChat or Unity internally (UI, menus, hardware, preview): avoid |

VRChat resets its built-in layers' names and collision matrix on upload; only user-layer changes survive. Put
custom collision rules on layers 22-30.

## 4. Components

Only allowlisted components work in an uploaded world; a custom MonoBehaviour that is not Udon does nothing.
Editor-only helpers must implement `VRC.SDKBase.IEditorOnly` (stripped at build) or sit under an `EditorOnly`-tagged
object.

| Need | Component | Notes |
|---|---|---|
| Pick up an object | VRC Pickup + Rigidbody + collider | Put it on the Pickup layer; set Respawn behaviour in the descriptor |
| Sync a moving object | VRC Object Sync | One per synced object; costs network budget (`udon-performance`) |
| Seats, vehicles | VRC Station | Needs an entry and exit point; test sitting and leaving in ClientSim |
| Mirror | VRC Mirror Reflection | Expensive: off by default behind a toggle, layer mask trimmed (`vrchat-lighting-and-baking` for cost) |
| Positional sound | AudioSource + VRC Spatial Audio Source | Audio is restricted on Android: test the Quest build |
| Portal to another world | VRC Portal Marker | |
| Avatar pedestal | VRC Avatar Pedestal | |
| UI that players click | Canvas + VRC Ui Shape | |
| Logic | Udon / UdonSharp behaviours | Design rules: `udon-performance` |

## 5. Colliders and walkability

- Every walkable surface needs a collider; decorative clutter usually needs none.
- Simple colliders (boxes, low-poly shells) for walls and floors; never the render mesh of a detailed piece.
- Block falls off ledges players should not leave with invisible box colliders, and keep stairs as ramps for the
  collider (steps 0.2 m high or less if they must stay stepped).
- Check by walking it: ClientSim in Play mode, every room, every stair, every doorway.

## 6. Testing

| Test | How | Catches |
|---|---|---|
| ClientSim | Press Play in the world scene; Escape opens its menu (respawn, spawn remote players) | Spawns, interacts, pickups, stations, UI, Udon logic, EditorOnly removal |
| Build & Test | Control Panel > Builder > Build & Test Your World; **Clients** = 2 or more for network tests; **Force Non-VR** for desktop | Real client behaviour, networking between clients, late joiners |
| Build & Reload | With Enable World Reload, iterate without restarting clients | |

ClientSim simulates only the local player: networking, remote players and serialization results need Build & Test
with several clients.

## 7. Publish fields (prepare them for the user)

In the Builder's world panel: **Name**, **Description**, **Maximum Capacity**, **Recommended Capacity**, **Content
Warnings**, **Tags**, **World Debugging**, **Thumbnail**. Clear every SDK validation message (apply the offered auto
fixes where they make sense), check the console is free of errors, then hand over: the user presses **Build &
Publish Your World Online** (it needs their account at the "New User" trust rank or higher).

## 8. Cross-platform (PC, Android / Quest, iOS)

Full steps and the mobile rules: `references/cross-platform.md`. In short:

1. Optimise for mobile first (baked lighting, lower geometry, little transparency, textures 1024 or below), with
   per-platform texture overrides (`vrchat-texture-and-vram`).
2. Switch the build target in the Control Panel's platform dropdown (the first switch reimports everything and is
   slow).
3. Upload every platform to the **same blueprint ID**.
4. Android hard limit: **100 MB** after build-time compression. Post-processing and cloth are disabled on Android.

## 9. Before handing over

- [ ] Unity version matches VRChat's; one scene descriptor; spawns on floors, facing in
- [ ] Respawn height below the lowest floor; reference camera clip planes set
- [ ] No objects on reserved or player layers; custom collision only on 22-30
- [ ] Every walkable area tested in ClientSim; interactions and pickups work
- [ ] Network behaviour tested with Build & Test, 2+ clients, including a late joiner
- [ ] Each platform build passes SDK validation with no console errors; Android under 100 MB
- [ ] Publish fields drafted; thumbnail captured

## Sources (checked 2026-10-13)

- Unity version: https://creators.vrchat.com/sdk/upgrade/current-unity-version/
- Scene descriptor: https://creators.vrchat.com/worlds/components/vrc_scenedescriptor/
- Layers: https://creators.vrchat.com/worlds/layers/
- Allowlisted components: https://creators.vrchat.com/worlds/whitelisted-world-components/
- ClientSim: https://creators.vrchat.com/worlds/clientsim/
- First world, build and publish fields: https://creators.vrchat.com/worlds/creating-your-first-world
- Cross-platform: https://creators.vrchat.com/platforms/android/cross-platform-setup/
- Android limits: https://creators.vrchat.com/platforms/android/quest-content-optimization/
