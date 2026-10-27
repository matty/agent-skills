---
name: vrchat-udon
description: Udon / UdonSharp scripts for VRChat worlds - scripts costing frametime, Update loops, laggy, desynced or clogged networking, late joiners seeing the wrong state, ownership, manual vs continuous sync, NetworkCallable events, sync budgets, pooling, toggles. SDK components and multi-client tests (vrchat-world-sdk-setup); whole-world frame time (vrchat-world-optimization).
---

# Udon and UdonSharp for VRChat worlds

**Udon takes on the order of 200x-1000x longer than the same C#**, and that is multiplied by every copy of a behaviour
in the scene. Every rule below follows from it. Write scripts in UdonSharp: version 1.x ships inside the Worlds SDK
(3.4.0 and later), so there is nothing extra to install.

Depth: `references/networking-limits.md` (limits, sources), `references/examples.md` (classes),
`references/unity-mcp.md` (scripted setup and tests). SDK components (pickups, VRC Object Sync, stations) and
ClientSim or multi-client testing: `vrchat-world-sdk-setup`. Whole-world frame time: `vrchat-world-optimization`.

## Performance rules, in order of impact

### 1. Delete `Update()`

Every `Update()` is an Udon VM entry per behaviour per frame. Replace it:

| Instead of polling | Use |
|---|---|
| Checking a distance every frame | A trigger collider + `OnPlayerTriggerEnter` / `OnPlayerTriggerExit` |
| Waiting for a timer | A delayed event that re-arms itself (below) |
| Watching a variable another script owns | Have that script call your method directly |
| Polling a synced variable for changes | `OnDeserialization()`, or `[FieldChangeCallback]` on the field |
| Watching for an interaction | `Interact()` / `OnPlayerTriggerEnter` |
| Animating anything | An Animator or Animation, or shader time: never an Udon loop |

If a loop genuinely must run, run it slowly: 5-10 times a second instead of every frame costs a tenth as much. Start it
once from `Start()` and let it re-arm itself (the whole class: `references/examples.md`):

```csharp
public void _Tick()   // public: called by name; "_": cannot be called over the network
{
    // the slow work goes here
    SendCustomEventDelayedSeconds(nameof(_Tick), 0.2f);
}
```

### 2. Cache lookups in `Start()`

```csharp
private Transform _t; private VRCPlayerApi _local; private Renderer[] _renderers;   // using VRC.SDKBase;

void Start()
{
    _t = transform;                   // property lookups are not free in Udon
    _local = Networking.LocalPlayer;
    _renderers = GetComponentsInChildren<Renderer>();
}
```

`GetComponent<T>()` is slow, and slower still for UdonSharpBehaviour types: UdonSharp loops over every UdonBehaviour on
the object to check its type. Call it only in `Start()` or a rare event.

### 3. Private by default; public only what is called by name

| Method | Make it |
|---|---|
| Called only from this script | `private` (fewer public methods is cheaper) |
| Called by name: `SendCustomEvent`, `SendCustomEventDelayedSeconds` / `Frames`, UI events, animation events | `public`, no parameters, name starting with `_` so it cannot be called over the network. A private one is not exported, so the call does nothing |
| Called over the network | `public` with `[NetworkCallable]` (Networking, step 4) |
| Called from another script | `public`; prefer one behaviour that owns a system over several that call each other, since cross-behaviour calls are slower |

### 4. Prefer engine features over Udon

Animator, Animation, particle systems, colliders, VRC Pickup, VRC Object Sync, VRC Station and shader-side animation
all run in native code. Anything you can express as a component instead of a script, express as a component.

### 5. Data structures

- Plain arrays first. UdonSharp has no LINQ and no user-defined generic methods or types, and most generic collections
  are not exposed to Udon.
- When sizes change at runtime, use VRChat's Data Containers (`DataList`, `DataDictionary` in `VRC.SDK3.Data`).
- Avoid string building, string comparison and boxing in hot paths.
- Time-slice long loops (N elements per call) instead of walking a 5000-element array in one event.

**Measure**: Unity Profiler in Play mode with ClientSim, sorted by self time. If total Udon time is under about 1 ms,
stop optimising scripts and look at rendering (`vrchat-world-optimization`).

## Networking: decide in this order

### 1. Sync setup, per GameObject

| Setup | Use for | Notes |
|---|---|---|
| `BehaviourSyncMode.None` | Purely local scripts | No synced variables, and the behaviour cannot receive network events |
| `BehaviourSyncMode.NoVariableSync` | Scripts that sync nothing but receive network events, or share a GameObject with a synced behaviour | UdonSharp sets it to the GameObject's mode |
| `BehaviourSyncMode.Manual` | Discrete state that must arrive exactly: score, game phase, which seat is taken | The owner calls `RequestSerialization()` when the state changes, never per frame |
| `BehaviourSyncMode.Continuous` | Values that change constantly where in-between states do not matter | About 200 bytes per serialization; updates may be dropped; no synced arrays (a compile error) |
| VRC Object Sync component | Moving physics objects and pickups | No script needed; sleeps while the object is still |

- Put the mode on the class: `[UdonBehaviourSyncMode(BehaviourSyncMode.Manual)]`. Without the attribute the mode is
  `Any` and the UdonBehaviour's dropdown decides.
- One sync mode per GameObject: the most restrictive wins, so a Manual and a Continuous behaviour on one object both
  act as Manual.
- VRC Object Sync never shares a GameObject with a Manual behaviour or a VRC Object Pool: the SDK reports an error
  that blocks the build.

### 2. Stay inside the budget

| Limit | Value |
|---|---|
| Outbound Udon data per client | About 11 KB/s |
| Continuous, per serialization | About 200 bytes |
| Manual, per serialization | About 280 KB (280,496 bytes), rate-limited by size: large payloads go out slowly |

A synced bool or byte costs 1 byte, an int or float 4, a Vector3 12, a Quaternion or Color 16, a string 2 per
character (every type: `references/networking-limits.md`).

Over budget the network clogs (`Networking.IsClogged` turns true): Continuous behaviours fail to send and log errors,
Manual ones queue and retry, and local logic keeps running, so it looks like "it works for me but nobody else sees
it".

### 3. Ownership

- Only the owner's values are sent. Before writing a synced variable: if `!Networking.IsOwner(gameObject)`, call
  `Networking.SetOwner(Networking.LocalPlayer, gameObject)`; then change it and call `RequestSerialization()`.
- Or leave ownership where it is and send the change to the owner as a network event (`NetworkEventTarget.Owner`).
- `OnOwnershipRequest` can refuse transfers; never let several scripts request one object's ownership at once.
- Never use collision ownership transfer on UdonBehaviours: it can spam transfers and lag everyone in the instance.

### 4. Network events

```csharp
// using VRC.SDK3.UdonNetworkCalling;  using VRC.Udon.Common.Interfaces;
SendCustomNetworkEvent(NetworkEventTarget.All, nameof(Ring), 0.8f);

[NetworkCallable(maxEventsPerSecond: 2)]
public void Ring(float volume) { bell.volume = volume; bell.Play(); }
```

- A network-callable method is `public`, carries `[NetworkCallable]` (SDK 3.8.1 and later), returns nothing, is not
  static, virtual, override or overloaded, and takes up to 8 parameters of syncable types (16 KB in total). The
  argument types must match the parameters exactly (`0.8f` for a `float`).
- Rate limit: 5 events per second per event by default. Raise it with `maxEventsPerSecond` (1-100), keeping it as low
  as works; extra events queue on the sender, and the whole client is capped near 100 events per second.
- Targets: `All`, `Others`, `Owner`, `Self` (`Self` skips the rate limit). Never send events per frame.
- Legacy: a public method with no parameters and no `_` prefix can still be called without the attribute. Do not rely
  on it; keep everything not meant for the network private or `_`-prefixed.

### 5. Late joiners

Late joiners receive the latest synced values automatically, and `OnDeserialization` runs for them once they have
loaded. Apply state there, and the default state in `Start()`; there is no need to re-send in `OnPlayerJoined`. Events
are not replayed for late joiners, so anything that must persist lives in a synced variable.

### Sync practices

- Sync the cause, not the effect: `bool doorOpen`, not the door's transform every frame.
- Compact types: `Color32` over `Color`, a `byte` or `int` state over a string, an index over a name.
- Initialise synced arrays (an empty array at least): a single uninitialised synced array stops the whole behaviour
  syncing.
- Local events run on every client: `OnTriggerEnter`, `OnCollisionEnter` and the like fire wherever the contact is
  seen (for a ball with VRC Object Sync, on every client), and `OnPlayerTriggerEnter` fires everywhere for every
  player. Let one client act, the moving object's owner (`if (!Networking.IsOwner(other.gameObject)) return;`) or the
  player themselves (`player.isLocal`), and send the change to the state's owner with `NetworkEventTarget.Owner`.
  Worked classes (a manual-sync toggle, a network event, a basket counted once): `references/examples.md`.

## Debugging sync ("it works for me but nobody else sees it")

1. Reproduce with two clients started together: Build & Test, 2+ clients (`vrchat-world-sdk-setup`); ClientSim does
   not simulate what remote players receive. The Builder's buttons cannot add a late joiner (a new room per launch).
2. VRChat's debug views (Right Shift + ~ + number on desktop; Quick Menu > Settings > Toggle Debug UI in VR and on
   Quest): 6 Net Objects (owner, bytes per serialization and per second, sync interval), 4 Players ("Suffering": Udon
   sends too much), 8 the network overlay, 3 the log with Udon crashes. Others see 6 and 8 only with World Debugging.
3. Ownership: log `Networking.GetOwner(gameObject).displayName`; check `Networking.IsOwner(gameObject)` before every
   write.
4. Sends, in a real client: override `OnPostSerialization(SerializationResult result)` (`using VRC.Udon.Common;`) and
   read `result.success` and `result.byteCount` (ClientSim raises it only for synced Player Objects, with fake values).
5. `Networking.IsClogged` true: cut payload size or send frequency (step 2).
6. A late joiner sees the wrong state: it was sent as an event (not replayed) or applied outside `OnDeserialization`.
   Check the logic with a simulated `OnDeserialization` (`references/unity-mcp.md`); the real test is a private upload
   where one account changes the state and a second joins afterwards (`vrchat-world-sdk-setup`, Late joiner).
7. The UdonBehaviour's sync method matches the class's mode, and the GameObject has one mode (step 1).

## Patterns worth using

- **Toggle expensive things.** Mirrors, cameras, video players and particle systems off by default, on by player
  action or proximity: usually the largest win a script can deliver. Remote players trigger `OnPlayerTriggerEnter`
  with a small sphere at their feet (a capsule is planned): make proximity triggers reach the floor.
- **Pool, do not instantiate.** Pre-place objects, disable them and hand them out; `VRCObjectPool` for the networked
  case. Only the pool's owner can `TryToSpawn` (null when the pool is empty) or `Return`; a non-owner's call logs an
  error and does nothing, which ClientSim hides because its local player owns everything. Send requests to the owner
  (`NetworkEventTarget.Owner`, from a behaviour on the pool's GameObject) or take ownership first. Late joiners get
  the pool's active states automatically.
- **Drive shaders instead of transforms.** One global value per frame beats moving hundreds of objects:
  `VRCShader.SetGlobalVector(id, value)` with the int ID from `VRCShader.PropertyToID("_UdonThing")` (names start with
  `_Udon`; example in `references/examples.md`). Instanced drawing from Udon: `unity-batching-and-instancing`.
- **Player lists.** `VRCPlayerApi.GetPlayers(array)` fills an array you size with `VRCPlayerApi.GetPlayerCount()`:
  refresh it in `OnPlayerJoined` / `OnPlayerLeft` and cache it, never every frame.

## Sources (checked 2026-10-17)

- Udon's cost, GetComponent, public methods for SendCustomEvent, the `_` rule, collision ownership transfer:
  https://udonsharp.docs.vrchat.com/random-tips-&-performance-pointers
- Sync modes and attributes: https://udonsharp.docs.vrchat.com/udonsharp
- UdonSharp inside the Worlds SDK: https://creators.vrchat.com/releases/release-3-4-0
- Networking limits, events, late joiners, object pools, debug views, SDK errors: `references/networking-limits.md`
- `VRCShader` and `_Udon` names: https://creators.vrchat.com/worlds/udon/vrc-graphics/
- Data Containers: https://creators.vrchat.com/worlds/udon/data-containers/
- APIs in the code samples checked against the UdonSharp and SDK sources in Worlds SDK 3.10.5 (2026-10-17)
