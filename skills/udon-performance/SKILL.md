---
name: udon-performance
description: Write and fix UdonSharp scripts for VRChat worlds with performance and networking in mind - avoiding Update, caching lookups, event-driven design, sync variable budgets, manual vs continuous sync, late joiners, ownership, object pooling and toggling expensive objects. Use when Udon scripts cost frametime, when networking is laggy, desynced or "clogged", or when designing interactive world systems.
---

# Udon / UdonSharp performance

**Udon runs 200×–1000× slower than the equivalent compiled C#.** That single fact drives every rule here. Code that would be free in a normal Unity project is a frametime problem in a VRChat world, and it is multiplied by however many copies of the behaviour exist in the scene.

## The rules, in order of impact

### 1. Delete `Update()`

Every `Update()` in the scene is an Udon VM entry per behaviour per frame. Replace it with:

| Instead of polling | Use |
|---|---|
| Checking a distance every frame | A trigger collider + `OnPlayerTriggerEnter/Exit` |
| Waiting for a timer | `SendCustomEventDelayedSeconds("_Tick", 0.5f)` re-armed from itself |
| Watching a variable another script owns | Have that script call your method directly |
| Polling a synced variable for changes | `OnDeserialization()` |
| Watching for an interaction | `Interact()` / `OnPlayerTriggerEnter` |
| Animating anything | A Unity Animator/Animation, or shader time — not an Udon loop |

If a loop genuinely must run, run it **slowly**: a self-rescheduling delayed event at 5–10 Hz instead of 90 Hz costs a tenth as much, and nobody notices.

### 2. Cache everything in `Start()`

```csharp
private Transform _t;
private VRCPlayerApi _local;
private Renderer[] _renderers;

void Start()
{
    _t = transform;                       // property lookups are not free in Udon
    _local = Networking.LocalPlayer;
    _renderers = GetComponentsInChildren<Renderer>();
}
```

`GetComponent<T>()` is slow, and *especially* slow for `UdonSharpBehaviour` types — Udon must loop over every UdonBehaviour on the object to type-check. Never call it outside `Start()` or a rare event.

### 3. Keep methods private, and keep behaviours whole

- `private` methods resolve faster than public ones; the public method table is searched by name.
- Cross-behaviour calls (`SendCustomEvent`) are slower than local calls. Prefer one behaviour that owns a system over five that chat.
- Prefix any local-only method with `_` (`_UpdateVisual`). VRChat blocks network events targeting underscore-prefixed names — it is both a performance and a **security** measure, since any player can otherwise fire your public methods over the network.

### 4. Prefer engine features over Udon

Animator, Animation, particle systems, colliders, `VRC_Pickup`, `VRCObjectSync`, `VRCStation`, and shader-side animation all run in native code. Anything you can express as a component instead of a script, express as a component.

### 5. Data structures

- Udon has poor support for generics and LINQ — use plain arrays.
- Avoid string building, `string` comparison and `object` boxing in hot paths.
- Long loops kill frames: time-slice (process N elements per call) instead of iterating a 5000-element array in one event.

## Networking

Budgets that actually bind (https://creators.vrchat.com/worlds/udon/networking/network-details/):

| Limit | Value |
|---|---|
| Total Udon throughput | **~11 KB/s** |
| Manual sync | ~280 bytes per serialization; larger payloads are rate-limited harder |
| Continuous sync | ~200 bytes per serialization |
| bool / byte | 1 byte |
| float / int | 4 bytes |
| Vector3 | 12 bytes · Quaternion 16 · Color 16 · Color32 4 |
| string | 2 bytes per character |

Exceeding the budget **clogs** the pipe: continuous behaviours silently drop events, manual behaviours queue and retry. Local logic keeps running, so it presents as "it works for me but nobody else sees it".

**Choose the sync mode deliberately:**

- **Continuous** — frequently changing values where intermediate states do not matter (a moving platform's position). VRChat interpolates and compresses.
- **Manual** — discrete state that must arrive exactly (score, game phase, which chair is taken). Call `RequestSerialization()` when the state actually changes, never per frame.
- **None** — the default for anything purely local. Most behaviours should be here.

**Practices:**

- Sync the *cause*, not the *effect*: sync `bool doorOpen`, not the door's transform each frame.
- Sync compact types: `Color32` over `Color`, `byte`/`int` state enums over strings, an index over a name.
- Initialize synced arrays — an uninitialized array fails to sync at all.
- Handle late joiners: apply state in `OnDeserialization()`, and make `Start()`/`OnPlayerJoined` re-apply the current state to the scene.
- Ownership: mutate a synced variable only after `Networking.SetOwner(localPlayer, gameObject)`, or route it through the owner with `SendCustomNetworkEvent(NetworkEventTarget.Owner, ...)`.
- Never fire network events per frame — gate them behind real user actions or a slow timer.

## Patterns worth using

**Toggling expensive things.** Mirrors, cameras, video players and particle systems should be disabled by default and enabled by player action or proximity — checked on a slow delayed event, not `Update()`. This is usually the single largest performance win any Udon script can deliver.

**Object pooling.** Instantiation is restricted and expensive; pre-place a pool of objects, disable them, and hand them out. `VRCObjectPool` exists for the networked case.

**Driving shaders instead of transforms.** `VRCShader.SetGlobalVector("_UdonThing", v)` once per frame is far cheaper than moving hundreds of objects. Global property names must start with `_Udon`, and `VRCShader.PropertyToID` should be resolved once in `Start()`. See the `unity-batching-and-instancing` skill for instanced drawing from Udon.

**Player loops done right.** `VRCPlayerApi.GetPlayers` allocates — call it on join/leave events and cache the array, not every frame.

## Measuring

- Unity Profiler in Play mode with ClientSim: Udon shows as `UdonBehaviour.Update` / event dispatch. Sort by self time.
- In-game debug overlays show Udon time separately from render time.
- If total Udon time is under ~1 ms, stop optimizing scripts and look at rendering (`vrchat-world-optimization`).
