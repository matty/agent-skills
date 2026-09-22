# Pre-upload audit checklist

Run VRWorld Toolkit's World Debugger first — it catches most of this automatically — then walk this list.

## Scene / SDK
- [ ] One scene descriptor, spawn points above the floor, respawn height below the lowest walkable point.
- [ ] Reference camera assigned if using post-processing (PC only).
- [ ] No missing scripts, no magenta (missing shader) materials, no editor-only objects left in the build.
- [ ] Layers and the collision matrix are deliberate: players collide with environment, pickups on correct layers, no colliders on decorative meshes.
- [ ] Tested on **both** PC and Android if publishing cross-platform.

## Rendering
- [ ] Stats panel checked in Play mode; SetPass calls and batches inside budget.
- [ ] Frame Debugger walked once end to end — no surprise passes (duplicate skyboxes, stray cameras, per-light passes).
- [ ] Mirrors off by default, culling mask trimmed to the minimum layers, auto-disabled when players leave.
- [ ] No always-on render cameras; any camera writing a RenderTexture is toggled and low resolution.
- [ ] Occlusion culling baked, Occluder/Occludee Static flags set deliberately.
- [ ] Realtime light count is 0 or 1; everything else baked.
- [ ] Materials used by many objects have **Enable GPU Instancing** ticked.

## Lighting
- [ ] Lighting baked, not left on Auto Generate.
- [ ] Lightmap UVs valid on every lightmapped mesh (no overlap, adequate padding).
- [ ] Lightmap count and resolution reviewed in Lighting → Baked Lightmaps.
- [ ] Probes or VRC Light Volumes cover every area a player or pickup can reach, otherwise avatars render black.
- [ ] Reflection probes baked; box projection where it helps.

## Assets
- [ ] No texture over the platform budget; per-platform max-size override set for Android.
- [ ] Compression set per texture (BC7/DXT on PC, ASTC on Android); nothing left as RGBA32.
- [ ] Mipmaps on for all world geometry textures.
- [ ] Mesh import: Read/Write **off**, Rig `None` and Blend Shapes off for props, tangents only where needed.
- [ ] Audio compressed, mono where positional, streaming for long clips.
- [ ] Build size checked in the SDK build report; Android build under 100 MB after compression.

## Udon
- [ ] No `Update()` where an event, trigger or delayed custom event would do.
- [ ] `GetComponent`, `Networking.LocalPlayer` and `transform` cached in `Start()`.
- [ ] Local-only methods prefixed with `_` so they cannot be invoked as network events.
- [ ] Synced variables minimal and correctly typed; synced arrays initialized (uninitialized arrays fail to sync).
- [ ] Late joiners handled (`OnDeserialization`, `OnPlayerJoined`).

## Final
- [ ] Tested in a private instance on target hardware with other people and heavy avatars present.
- [ ] SetPass calls / frametime / download size recorded in project notes for the next pass.
