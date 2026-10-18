# Udon networking limits

Every number here was checked on 2026-10-17 against the page cited above its table. VRChat says its specs "are
subject to change": re-check a page before relying on a value close to its limit.

## Bandwidth and serialization

Source: https://creators.vrchat.com/worlds/udon/networking/network-details/ (page updated 2025-08-08)

| Limit | Value |
|---|---|
| Outbound Udon data | "Udon scripts can send out about 11 kilobytes per second" |
| Manual sync | "roughly 280,496 bytes per serialization"; each manually synced object is rate-limited as a factor of its data size, so calling `RequestSerialization()` more often does not send faster |
| Continuous sync | "roughly 200 bytes per serialization" |
| Over the limit | Networking clogs (`Networking.IsClogged`): Continuous behaviours fail to send and write errors to the log; Manual behaviours cache the change and retry; nothing is sent or received meanwhile, and local logic keeps running |
| Several UdonBehaviours on one GameObject | The most restrictive mode applies: "a Manual UdonBehaviour and a Continuous one on the same object will both act as manual" |
| Synced arrays | Initialise them: "If any of the synced arrays are left uninitialized - the behaviour will not sync!" |

Approximate size of a synced value (serialisation can add more):

| Type | Bytes |
|---|---|
| bool (sent as at least 1 byte), byte, sbyte | 1 |
| short, ushort, char | 2 |
| int, uint, float, Color32 | 4 |
| long, ulong, double, Vector2 | 8 |
| Vector3 | 12 |
| Vector4, Quaternion, Color | 16 |
| string, VRCUrl | 2 per character |

## Network events

Source: https://creators.vrchat.com/worlds/udon/networking/events (page updated 2026-06-17). Parameters and
`[NetworkCallable]` arrived in SDK 3.8.1, 2025-05-22 (https://creators.vrchat.com/releases/release-3-8-1).

| Rule | Value |
|---|---|
| Callable method (UdonSharp) | `public`, `[NetworkCallable]` (`using VRC.SDK3.UdonNetworkCalling;`), no return value, not static, virtual, override or overloaded |
| Parameters | Up to 8, of types Udon can sync, no `params` or default values; 16 KB in total per event; parameters over 1024 bytes are split into several internal events that count against the rate limit |
| Argument types | Must match the declared parameter types, or the send fails |
| Rate limit per event | 5 per second by default; `[NetworkCallable(maxEventsPerSecond: n)]` with n from 1 to 100; excess events queue on the sender |
| Global limit | About 100 outgoing events per second per client |
| Targets | `All`, `Others`, `Owner`, `Self` (`Self` bypasses the rate limit) |
| Legacy | Any public method with no parameters whose name does not start with `_` can still be called; "not recommended" |
| Security | A `_` prefix keeps a method from ever being called over the network, unless it carries `[NetworkCallable]` |

## Late joiners

Source: https://creators.vrchat.com/worlds/udon/networking/late-joiners (page updated 2025-04-28)

- A late joiner receives the latest synced variable values, and `OnDeserialization` triggers "once they've loaded in".
- "Events are not replayed": state that must persist lives in synced variables.

## Object pools

Source: https://creators.vrchat.com/worlds/udon/networking/network-components (page updated 2024-11-19), and the
`VRCObjectPool` IL in Worlds SDK 3.10.5 (read 2026-10-17).

- "the Owner of the pool triggers the TryToSpawn node"; it returns an object, "or a null object if none are
  available". "Objects may be returned to the pool by the pool's owner".
- A non-owner's `TryToSpawn` or `Return` logs "Non-owner attempted to spawn object from ..." or "Non-owner attempted
  to return ..." and does nothing. ClientSim's local player owns everything, so a ClientSim test cannot show it.
- "Late joiners will have the objects automatically made active or inactive where appropriate."

## UdonSharp sync modes

Source: https://udonsharp.docs.vrchat.com/udonsharp, and the attribute's own comments and compiler checks in the
UdonSharp bundled with Worlds SDK 3.10.5 (read 2026-10-17).

| `BehaviourSyncMode` | Meaning |
|---|---|
| `Any` | Nothing enforced; the default without the attribute |
| `None` | No synced variables, the sync dropdown is hidden, "SendCustomNetworkEvent will not work on the behaviour" |
| `NoVariableSync` | No synced variables, but "SendCustomNetworkEvent() will still work"; UdonSharp sets its UdonBehaviour to Manual when the GameObject has a Manual behaviour, otherwise Continuous |
| `Continuous` | Updates often, not always reliably. Synced arrays are a compile error |
| `Manual` | Updates when requested, reliably. `UdonSyncMode.Linear` or `UdonSyncMode.Smooth` interpolation on a synced field is a compile error |

## SDK errors and warnings (Worlds SDK 3.10.5, read 2026-10-17)

- The Builder raises the errors "Object Sync cannot share an object with a manually synchronized Udon Behaviour" and
  "Object Sync cannot share an object with an object pool" (`VRCSdkControlPanelWorldBuilder.cs`); errors block the
  build.
- UdonSharp warns when the behaviours on one GameObject have conflicting sync methods, or use Manual next to VRC Object
  Sync (`UdonSharpEditorManager.cs`).

## Debug views in the client

Source: https://creators.vrchat.com/worlds/udon/world-debug-views (page updated 2026-01-29). On desktop, Right Shift +
~ + number (on layouts without ~ left of 1, the key that is); in VR and on Quest, the Toggle Debug UI button near the
bottom of the Quick Menu's Settings page.

| View | Shows |
|---|---|
| 3 Log Viewer | The output log, including Udon behaviour crashes and `Debug.Log` |
| 4 Players | Per player send interval and delay, and "Suffering" when Udon is sending too much data |
| 6 Net Objects | Per networked object: owner, sleeping (VRC Object Sync only), size in bytes per serialization, bytes per second, time since last send, syncs per second |
| 8 Network Object Info Overlay | A panel on each synced object: ping, data quality, owner, status |

By default only the world's creator can open view 6 and the world overlays; enable World Debugging in the world's
settings on the website (players rejoin) to share them.

## Testing networked behaviour

- ClientSim (https://creators.vrchat.com/worlds/clientsim/): does not simulate what remote players receive (its
  remote players are stand-ins). It raises `OnDeserialization` and `OnPostSerialization` only for objects in a synced
  Player Object; there `success` is always true, `byteCount` is 4 x the number of serialized properties rather than
  real bytes (Worlds SDK 3.10.5, `ClientSimUdonEncodeDecode`; VRChat's page calls it the property count), and
  `sendTime` / `receiveTime` are always 0.
- Local Build & Test (https://creators.vrchat.com/worlds/udon/using-build-test, page updated 2024-08-28): the clients
  of one launch share a room, and every launch opens a new room (Worlds SDK 3.10.5 builds a random room id each time),
  so a client started later is alone. Late joiners are tested on a private upload with a second account.

## Players and triggers

Remote players' physics collider is currently a sphere around their feet, so they trigger `OnPlayerTriggerEnter`
there; VRChat plans to replace it with a capsule matching the local player, and says "This change has a chance of
affecting existing worlds" (https://ask.vrchat.com/t/developer-update-8-october-2026/49095, 2026-10-08).
