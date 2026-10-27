---
name: vrchat-lighting-and-baking
description: Bake and debug lighting in VRChat worlds (Unity Built-in RP) - black or flat avatars, seams, splotches, slow bakes, oversized lightmaps, light switches, mirrors, occlusion culling. Lightmap sizing, Progressive and Bakery, light probes, VRC Light Volumes, reflection probes, LTCGI, Quest and iOS. UV2 unwrapping (uv-unwrapping); whole-world triage starts at vrchat-world-optimization.
---

# VRChat world lighting and baking

Bake the environment, light everything that moves with light probes, and keep realtime lights off static geometry:
a fully baked world looks better and runs faster than a realtime one. Settle the decisions below first (each one
changes what gets baked), then work in three passes: plan, bake, verify.

## Decide first

| Decision | Default | Change it only when |
|---|---|---|
| Light Mode of every light | **Baked**: Lighting Mode (Subtractive, Shadowmask) then has no effect | A PC-only world needs realtime sun shadows on avatars: one Mixed directional, Lighting Mode Shadowmask (Distance Shadowmask is opt-in on PC since SDK 3.10.5, set from Udon with `VRCQualitySettings.ShadowmaskMode`). PC worlds allow at most one realtime per-pixel light on at a time: a Mixed sun and a switchable realtime light do not combine |
| PC plus Quest/iOS | One scene and one bake for every platform: every light Baked, Max Lightmap Size 1024 | Never: on Quest a realtime sun lights Standard Lite surfaces without shadows (light through walls), and point and spot lights do not show on lightmapped surfaces (section Quest and iOS) |
| Avatars, pickups, moving props | **Light probes, always** | Add VRC Light Volumes on top when installed, for renderers whose shaders support them |
| A light players switch | Lighting states: a baked copy of the static geometry per state (method under A light players can switch) | Light Volumes installed and the world's shaders read additive volumes (Standard and Standard Lite do not): an Additive volume. PC-only world with no other realtime light on: a shadowless realtime light |
| Lightmapper | Progressive GPU | Bakery is installed (Windows with an NVIDIA GPU) and bakes are slow. Decide before the UV2 is packed: Bakery sizes each renderer differently (plan steps 2, 3 and 5) |
| Directional Mode | Non-Directional (half the memory) | Normal maps that matter: under Non-Directional, Standard shows them only in reflections and Standard Lite skips them; bake Directional or Bakery MonoSH, decided with the texturing plan (references/final-look.md) |

## 1. Plan the lightmap before baking

Unity packs each renderer's UV2 chart box into the lightmap at a texel scale, its **footprint**. The UV2 gaps must
stay at 2 texels or more at that scale, and the boxes must fit the maps. The 2026-10-16 dry run's first bake failed
on both (8 px @ 512 gaps came to 1.76 texels; one 512 map could not give 16 pieces the 128 px their gaps needed).

1. Lightmap Resolution low (*practice*): 2-10 texels/m outdoors (2-5 terrain, 6-10 facades), 10-20 interiors. Raise
   Scale In Lightmap only on surfaces that show detail. Pick it before the UV2 is packed: it sets every gap.
2. Footprint, texels per UV unit: texels/m x sqrt(area in m2 / b) x Scale In Lightmap, b = the UV2 charts' bounding
   box's share of the tile (plan 0.85, check the measured b). **Bakery**: (L - 6) / that box's short side, L =
   texels/m x sqrt(2 x area x Scale In Lightmap): the scale acts on the area (s^2 for a linear s), no LOD 0.5^n. Pack
   the charts to fill the box: effective density = footprint x sqrt(charts' UV area / area).
3. Gaps: pack the UV2 for 2 texels with the box filling the tile, gap in UV = 2 / (texels/m x sqrt(area) x Scale In
   Lightmap) (Bakery: 2 / (L - 6)), and 1 texel to the tile edge: that holds whatever the packer does. Never lower
   Scale In Lightmap below what the gaps were packed for.
4. Under 64 px: a **free prop** (a Free-sized piece of the PROP or FOL family) is probe-lit (Contribute GI on, Receive
   Global Illumination = Light Probes). A **grid piece** (wall, floor, ceiling, facade, any ZONE shell) never is: it
   stays lightmapped and counted, and its size is only a note. A prop that changes with a light switch is lightmapped.
5. Capacity: a renderer's chart box costs (texels/m x Scale In Lightmap)^2 x area px^2, whatever the UV2 layout. Sum
   it x copies x lighting states <= 0.65 x Max Lightmap Size^2 x lightmap count (warn above 0.65, error above 0.80).
   LODs are lightmapped too, LODn at 0.5^n of the texel scale: LOD1 and LOD2 of similar area add about 0.31x LOD0's
   cost, unless their Receive Global Illumination is Light Probes (no atlas space; the lighting changes at the LOD
   switch). Max Lightmap Size is 1024 whenever the world ships to Quest or iOS (one bake serves every platform),
   2048 only in a PC-only world. Bakery: L^2 x the box's aspect, each LOD at its own area (twice Progressive's).
6. Runs and overlays (references/lightmap-uvs.md): the pieces of one continuous surface (a wall run, a floor) keep
   effective density within about 10% of each other (*practice*): Scale In Lightmap per run, never per piece, one LOD
   treatment per run, UV2 chart borders on each piece's own edges, joints closed with their hidden faces deleted
   (leaks: the reference). A decal or sign on a lightmapped surface is lightmapped at any size (Cast Shadows Off) or joins its mesh.

`scripts/lightmap_budget.py` runs steps 2-5 for pieces (KIND prop, grid, lightmap or probe; LODs) and prints the
texels/m windows that fit them all; `--lightmapper bakery` for Bakery. Maths and sources: references/lightmap-budget.md.
UV2: author it in Blender (`uv-unwrapping`), or Generate Lightmap UVs, Margin Method Calculate, for one-off props.

## 2. Bake

- Static flags: **Contribute GI** on all static geometry (it was Lightmap Static before Unity 2019.2); Receive Global
  Illumination per plan step 4. Anything that moves stays non-static.
- Lighting window (Unity 2022.3 names): Lightmapper Progressive GPU; Lightmap Resolution and Max Lightmap Size from
  the plan; Lightmap Padding 2 (the minimum); Lightmap Compression High Quality (the same BC6H size as Normal on
  Windows); Ambient Occlusion on; Directional Mode per the decision table; Auto Generate **off**: bake explicitly. The
  final bake's samples, bounces and denoiser, lighting design and PC post-processing: references/final-look.md.
- Light probes and reflection probes placed first (sections below), so one bake covers all three.
- Iterate on a scene copy, so a bad bake can be thrown away; scripted bakes (Unity MCP): references/lightmap-budget.md.
- Bakery (paid; Windows with an NVIDIA GPU, Kepler or newer: https://geom.io/bakery/wiki/index.php?title=Manual):
  faster GPU bakes, better denoising, per-light settings, lightmapped specular and the probe modes VRChat creators
  use. Progressive GPU suits small worlds and AMD machines.

## 3. Verify after every bake

- [ ] Lighting > Baked Lightmaps: count and size match the plan; nothing left over from an Auto Generate bake.
- [ ] No overlapping UVs: none of "objects in the Scene with overlapping UV's" in Editor.log (the console loses it
      once cleared), and Unity's overlap flag false per renderer.
- [ ] Real footprints: `lightmapScaleOffset.x` x the lightmap's width per renderer; padding = UV2 gap x footprint
      >= 2 texels; effective density >= 0.5 x texels/m at 64 px or more (else raise Scale In Lightmap and repack,
      Bakery's recipe in the reference). The snippet in references/lightmap-budget.md prints all three and overlaps.
- [ ] A grey Standard capsule moved through every reachable area renders lit, never black (probe coverage).
- [ ] Joints and corners: no seams, steps, splotches or light leaks; each run's effective density within about 10%.

## Avatars and other dynamic objects

- **Light probes are required, not a fallback.** Standard, the VRChat mobile shaders and every Quest/iOS avatar read
  only probes. Dense where lighting changes, sparse in uniform areas, covering every reachable volume up to head
  height. A missing probe area = black avatars.
- **VRC Light Volumes** (REDSIM, free, MIT; 3.x checked 2026-10-17) add smooth per-pixel lighting to renderers whose
  shaders support them (Poiyomi, lilToon and others; not Standard, not VRChat's mobile avatar shaders). Naming,
  overlap, limits and the runtime API: references/light-volumes-and-ltcgi.md.

## A light players can switch

A baked light cannot be turned off at runtime. Pick the method before the bake:

| Method | PC | Quest/iOS | Cost and catch |
|---|---|---|---|
| Lighting states: each state baked into its own copy of the static geometry (method below); Udon toggles the copies | Yes | Yes | A lightmap set and mesh copy per state. One light probe set serves every state, so avatars and probe-lit props do not change |
| VRC Light Volumes (if installed): bake the switchable lamps alone in a scene copy into an Additive volume ("Remove any unwanted environment lighting from this bake as well"), bring the volume back ("Enable Additive and disable Bake on this volume": left on, the main bake overwrites it), and bake the main scene with those lamps' bake lights disabled. Udon sets the volume's intensity to 1 (the baked brightness) or 0, starting from its Inspector Intensity: 1 for a lamp that starts on, 0 for off | Yes | With world shaders that support Light Volumes | Surfaces change only where their shader reads additive volumes; the change is local, so sync the state |
| Realtime point or spot light, no shadows, toggled by Udon | Yes, as the only realtime per-pixel light on at the time: Standard draws a forward-add pass per lit object; without shadows it lights through geometry | No: point and spot lights do not show on lightmapped Quest surfaces | About doubles SetPass calls while on (9 -> 18 measured, 2026-10-16) |
| Emissive swap only | Yes | Yes | None; the fixture glows, the room does not change |

Baking lighting states (Udon cannot swap lightmaps: "VRChat does not allow you access to change Lightmaps directly",
and a second bake replaces the first). Sources and detail: references/lighting-states.md.

1. The placed originals stay under MASTER with their colliders and their place in placement sync, Mesh Renderers
   off. The render-only copies live under a root of their own (for example `LIGHT_STATES`), outside MASTER, with
   renderers on and colliders removed (copies duplicated from the originals arrive the other way round).
2. Build the first state's two parents there (static geometry; that state's lights and reflection probes), then
   duplicate them once per further state. A piece that must change with the switch is lightmapped in every copy,
   even a small prop (the budget script's KIND `lightmap`).
3. Baked light probes stay where they were baked ("You can't move Light Probes by updating the Transform component
   of the Light Probe Group object", Unity), so the copy whose state avatars should match sits at the origin,
   inside the probe group. The others go far away: a sunlit copy far above a shadows-only plane, a sunless copy far
   below it (the plane: Contribute GI on, Cast Shadows Shadows Only, Scale In Lightmap 0).
4. Leave the Lighting window's skybox empty, cover the whole world with reflection probes (the fallback reflection
   is that empty sky), bake once, then move every copy back to the origin.
5. Keep every copy enabled at load (so Unity batches them). In Udon's `OnEnable`, disable all but the starting
   state and set its sky with `RenderSettings.skybox`; to switch, enable one copy, disable the others and set the
   sky (and `RenderSettings.customReflectionTexture`, if used).
6. Plan step 5 counts every switched piece once per state. After a placement sync changes a switched piece,
   rebuild and re-bake the copies.

## Quest and iOS (cross-platform worlds)

VRChat applies its Android rules to iOS. One scene and one bake serve every platform, so the mobile shaders set the
rules:

| World shader | Lightmaps | Light probes | Realtime lights | GPU instancing |
|---|---|---|---|---|
| `VRChat/Mobile/Standard Lite` | Yes (Bakery MonoSH too) | Yes | The main directional light only, unshadowed; point and spot lights not on lightmapped surfaces | Yes: tick Enable GPU Instancing |
| `VRChat/Mobile/Lightmapped` | Yes | No (dynamic objects on it are unlit) | No | No |

- VRChat documents both as not supporting real-time lighting (quest-content-limitations, updated 2025-10-08), but
  Standard Lite's shader source still adds the main directional light in its base pass, without shadows, so a
  realtime sun leaks light through walls on Quest. Either way, bake every light in a cross-platform world.
- The SDK's Mobile quality preset turns realtime shadows and realtime reflection probes off (Udon can turn realtime
  reflection probes back on with `VRCQualitySettings.RealtimeReflectionProbes`, SDK 3.10.5): bake reflection probes.
- Quest/iOS avatars are lit by probes only. Light Volumes and LTCGI both need world shaders that support them and
  build for Android: on Standard Lite or Lightmapped they light nothing (LTCGI also runs one screen on mobile).
- Evidence (shader pragmas, the SDK's quality presets, sources): references/quest-and-cross-platform.md.

## Reflection probes

- Baked, box projection for interiors, resolution 64-128 (256 only for one hero probe on PC).
- Size the box to the room's interior faces: a larger box shifts every reflection; a renderer whose bounds miss every
  box uses the default (skybox) reflection.
- Blend probes sparingly: overlapping probes cost per-pixel work on every reflective surface.

## LTCGI

Realtime area lights from screens and strips, free with attribution. It is realtime lighting, not a cheap substitute:
cost scales with screens per receiving object and doubles on transparent receivers, and every receiver needs an
LTCGI-compatible shader (Standard is not one). On Quest/iOS it lights only receivers whose mobile material uses an
LTCGI shader that builds for Android, with one screen; on Standard Lite or Lightmapped it lights nothing. Its
shadowmaps are a second lightmap set (memory and download), and its bake turns static batching off on its receivers
on purpose ("LTCGI disables static batching on LTCGI-enabled receivers during the bake"): leave it off and count
their draw calls. Re-tick it only to try LTCGI 1.7.0+'s Allow Static Batching, then check in a build that the LTCGI
light is not offset. Add it last, after the world meets its budgets, and measure on device
(references/light-volumes-and-ltcgi.md).

## Mirrors

A mirror renders the scene again, per eye in VR (Auto resolution goes up to 2048 x 2048 per eye); VRChat warns it
"can drastically reduce the framerate".

- Off by default; a player toggle, or a proximity check on a slow interval (never per frame).
- Reflect Layers (default: everything): **Player and MirrorReflection** for a players-only mirror (MirrorReflection is
  how the local player appears in mirrors); add Default or Environment only where the room must show. Never
  PlayerLocal (the headless first-person copy). Water never renders in mirrors.
- **Turn Off Mirror Occlusion** is ticked by default (and in the SDK sample prefab): untick it unless objects flicker
  in the reflection, so the mirror uses the baked occlusion culling.
- Keep Disable Pixel Lights ticked (the default); lower Mirror Resolution before adding a second mirror. One good
  mirror beats several.

## Occlusion culling

- Mark large solid geometry Occluder Static and props Occludee Static, then bake it in the Occlusion Culling window.
- Smallest Occluder = the smallest wall panel or block that should hide things, in metres (often 2-5 m for buildings,
  less for interiors): its extent, not its thickness. Smallest Hole below the narrowest gap a camera sees through.
  Larger values bake faster and smaller.
- It pays in cellular layouts (rooms, corridors), little in an open field (use LODs and cull distances), and nothing in
  one sealed room: record that decision instead.
- Check it in the window's visualisation, walking the camera through the world.
- It culls statically batched objects one by one; it never culls single `DrawMeshInstanced` copies; it works inside a
  mirror only once Turn Off Mirror Occlusion is unticked (it is ticked by default).

## Debug order when lighting looks wrong

1. Is it baked, or showing a stale or auto bake? Lighting > Baked Lightmaps.
2. Black or flat avatars -> probe coverage (and Light Volume coverage, where used).
3. Splotches, bleeding, seams -> UV2 overlap, gaps under 2 texels (references/lightmap-uvs.md); joints, decals: step 6.
4. Blown out or washed out -> light intensities, an extra ambient source, or the skybox contributing more than meant.
5. Shadows missing on Quest -> Quest shows baked shadows only: the light must be Baked, the casters Contribute GI,
   and the Quest material must read the lightmap (Standard Lite and Lightmapped do).
6. Huge build -> lightmap count x size, and Directional mode (about twice the memory).

## Sources (checked 2026-10-17)

| Facts | Source |
|---|---|
| Lighting settings, compression, directional cost, lighting modes | https://docs.unity3d.com/2022.3/Documentation/Manual/class-LightingSettings.html, https://docs.unity3d.com/2022.3/Documentation/Manual/lighting-mode.html |
| Contribute GI, Receive Global Illumination | https://docs.unity3d.com/2022.3/Documentation/Manual/StaticObjects.html |
| Occlusion culling settings | https://docs.unity3d.com/2022.3/Documentation/Manual/occlusion-culling-window.html |
| Mirror layers and properties | https://creators.vrchat.com/worlds/layers/, https://creators.vrchat.com/worlds/components/vrc_mirrorreflection/; defaults (Turn Off Mirror Occlusion and Disable Pixel Lights on, every layer reflected) from the SDK 3.10.5 `VRC_MirrorReflection` constructor |
| Mobile shaders; iOS follows Android | https://creators.vrchat.com/platforms/android/quest-content-limitations/, https://creators.vrchat.com/platforms/iOS/ |
