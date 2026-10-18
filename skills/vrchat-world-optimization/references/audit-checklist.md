# Pre-upload audit checklist

Run VRWorld Toolkit's World Debugger first if it is installed (it catches much of this automatically), then walk this
list; without it, walk the list by hand through Unity MCP (`unity-mcp.md`). Mobile means Android (Quest) and iOS.

## Project and scene
- [ ] Unity 2022.3.22f1 exactly.
- [ ] VRChat layers and collision matrix set up (Builder > Setup Layers for VRChat, then Setup Collision Matrix):
      either one missing blocks the build.
- [ ] One scene descriptor; at least one spawn (an empty list blocks the build), each on a floor; respawn height below
      the lowest walkable point.
- [ ] Reference camera assigned with its clip planes set (PC post-processing lives on it).
- [ ] No missing scripts, no magenta (missing shader) materials, editor-only objects under an EditorOnly-tagged
      GameObject (an `IEditorOnly` component still ships in a world).
- [ ] Layers deliberate: nothing on reserved or player layers, pickups on Pickup with VRC Object Sync (without it
      they never respawn in ClientSim), world UI not on layer 5 UI, players collide with the environment, no colliders
      on decorative meshes.
- [ ] Tested on the device for every platform being published (PC, Android / Quest, iOS).

## Rendering
- [ ] Stats panel checked in Play mode; SetPass calls and batches inside budget at the worst view of each zone, not
      the average.
- [ ] Frame Debugger walked once end to end: no surprise passes (duplicate skyboxes, stray cameras, per-light passes).
- [ ] Mirrors off by default, player-toggled, auto-off when nobody is near; Reflect Layers Player and MirrorReflection
      plus only what must show, never PlayerLocal (setup: `vrchat-lighting-and-baking`).
- [ ] No always-on render cameras; any camera writing a RenderTexture is toggled and low resolution.
- [ ] Occlusion culling baked, or the decision not to recorded (a single room with nothing outside it gains nothing);
      settings per `vrchat-lighting-and-baking`.
- [ ] Realtime lights: a world that ships to Quest or iOS has every light Baked (one bake serves every platform);
      otherwise at most 1 realtime per-pixel light at a time (PC-only worlds).
- [ ] Materials used by many objects have Enable GPU Instancing ticked, mobile materials included
      (`VRChat/Mobile/Standard Lite` supports it; only `VRChat/Mobile/Lightmapped` has no instancing variant).

## Lighting
- [ ] Lighting baked, not left on Auto Generate.
- [ ] Lightmap UVs valid on every lightmapped mesh (no overlap, adequate padding).
- [ ] Lightmap count and resolution reviewed in Lighting > Baked Lightmaps.
- [ ] Light probes cover every area a player or pickup can reach (VRC Light Volumes only in addition), otherwise
      avatars render black.
- [ ] Reflection probes baked; box projection where it helps.

## Assets
- [ ] No texture over the platform budget; max-size overrides set on both the Android and the iOS tab.
- [ ] Compression set per texture (BC7/DXT on PC, ASTC on Android and iOS); nothing left as RGBA32.
- [ ] Mipmaps on for all world geometry textures.
- [ ] Mesh import: Read/Write off, Rig None and Blend Shapes off for props, tangents only where needed.
- [ ] Audio compressed, mono where positional, streaming for long clips.
- [ ] Build size checked in the SDK Builder after a build; Android and iOS builds under 100 MB (104,857,600 bytes)
      after compression.

## Udon
- [ ] No `Update()` where an event, trigger or delayed custom event would do.
- [ ] `GetComponent`, `Networking.LocalPlayer` and `transform` cached in `Start()`.
- [ ] Methods called by name (custom, delayed, UI and animation events) are public with a `_` prefix; methods sent
      over the network carry `[NetworkCallable]`; everything else is private.
- [ ] Synced variables minimal and compact; synced arrays initialised; one sync mode per GameObject; no VRC Object
      Sync on a GameObject with a Manual behaviour.
- [ ] Late joiners handled: persistent state in synced variables, applied in `OnDeserialization`.

## Final
- [ ] Tested in a private instance on target hardware with other people and heavy avatars present.
- [ ] SetPass calls, frametime and download size recorded in the project notes for the next pass.
