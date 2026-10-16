---
name: vrchat-lighting-and-baking
description: Set up and debug lighting for VRChat worlds in Unity Built-in RP - lightmap baking (Progressive and Bakery), lightmap UVs and texel density, light probes vs VRC Light Volumes, reflection probes, LTCGI area lights, mirrors, and occlusion culling. Use when lighting looks flat, avatars render black or wrongly lit, bakes take forever or produce seams and splotches, lightmaps bloat the build, or realtime lights are killing framerate; this skill owns lightmap resolution, footprint and bake settings, while how to unwrap the lightmap UV2 itself is uv-unwrapping.
---

# VRChat world lighting and baking

Lighting is where VRChat worlds are won: a fully baked world looks better *and* runs faster than a realtime one. The goal is **zero realtime per-pixel lights on static geometry**, good baked lighting on the environment, and a cheap, correct solution for everything dynamic (avatars, pickups, doors).

## The two halves

| What it lights | Solution |
|---|---|
| Static geometry (walls, floors, props marked Contribute GI) | **Lightmaps** — baked texture, free at runtime |
| Dynamic things: avatars, pickups, moving props | **VRC Light Volumes** (preferred) or Unity **Light Probes** |

Getting only one half right is the classic failure: a beautiful baked room where every avatar is pitch black, or perfectly lit avatars in a flat, ambient-only room.

## Baking static lighting

1. **Lighting mode**: Baked Indirect or Mixed → *Shadowmask* on PC; **Subtractive** on Quest (one directional light baking shadows, nothing realtime). The mode only matters for Mixed lights: with every light Baked (an interior with no sun) it has no effect.
2. **Mark geometry**: Contribute GI + Lightmap Static on anything that should receive baked light. Props that move must *not* be static.
3. **Lightmap UVs**: either author UV2 in Blender (better control; how to unwrap it well is the `uv-unwrapping` skill) or tick *Generate Lightmap UVs* on import. Rules and failure modes in `references/lightmap-uvs.md`.
4. **Texel density**: set the scene *Lightmap Resolution* (texels per unit) low — 5–15 for large worlds — and raise *Scale In Lightmap* only on surfaces that show detail (shadow-catching floors, hero walls). Blanket-raising the scene resolution is how bakes end up at 8 × 2048 maps and 200 MB.
5. **Lightmap size**: 1024 on Quest, 1024–2048 on PC. Fewer, well-packed maps beat many sparse ones. Check Lighting → Baked Lightmaps to see what you actually produced.
6. **Directional mode**: Non-Directional halves lightmap memory and is the right default on Quest; Directional only where normal-mapped detail must respond to baked light.
7. **Compress lightmaps** on, ambient occlusion on, and disable *Auto Generate* — always bake explicitly.

**Bakery** (paid, Unity BiRP-native) is the community default for a reason: much faster GPU bakes, better denoising, per-light settings, lightmapped specular, and light-probe modes that suit VRChat. Progressive GPU is fine for smaller worlds. Whichever you use, bake to a scene copy while iterating so you can throw bad bakes away.

## Lighting avatars and dynamic objects

**VRC Light Volumes** (REDSIM, free, VPM) is a voxel-based replacement for light probes — smooth per-pixel lighting for avatars and props, no probe placement tedium, no probe popping, and it works with baked shadows. It is the current best practice for most worlds.

- Create a volume, Edit Bounds to fit a room, tune *Voxels Per Unit* for density.
- **Give every baked volume a unique name** — generated 3D textures inherit the name and collide otherwise.
- Overlap intersecting volumes by ~0.25 m and keep Smooth Blending smaller than the overlap to hide seams.
- Enable Dynamic / Auto Update only if lighting really changes at runtime; cull unused volumes in large scenes.
- With Bakery, enable *Fix Light Probes L1* to correct Bakery's SH exposure behaviour.
- Docs: https://github.com/REDSIM/VRCLightVolumes

**Light probes** remain the fallback (and what non-supporting shaders use). If you use them: dense where lighting changes, sparse in uniform areas, always covering every walkable/reachable volume including the ceiling height an avatar's head reaches. A missing probe volume = black avatars.

## A light players can switch

A baked light cannot be turned off at runtime, and the Quest shaders ignore extra realtime lights. Pick the method
before the bake, since it changes what gets baked:

| Method | PC | Quest | Cost |
|---|---|---|---|
| Lighting states: bake each state into its own copy of the affected static meshes, and toggle the copies with Udon (or an animator bool) | Yes | Yes | One extra lightmap set and mesh copy per state; keep every copy enabled at load so Unity can batch them, then switch |
| Realtime point or spot light toggled by Udon, no shadows | Yes (Standard renders it in a forward-add pass); without shadows it lights through geometry (under desks, through thin walls) | No: `VRChat/Mobile/Standard Lite` does not support realtime lighting, so surfaces on it stay unlit | One extra draw pass per lit object on PC |
| Emissive swap only (the fixture glows, the room does not change) | Yes | Yes | None; reads as a lamp, not as room light |

For a world that must work on Quest, use lighting states. A realtime light on top of a baked bake is a PC-only
nicety, so say so in the world's notes. Sources: VRChat wiki, swapping baked lightmaps
(https://wiki.vrchat.com/wiki/How_to_swap_out_Baked_Lightmaps); VRChat Creators, Quest content limitations, Standard
Lite and realtime lighting (https://creators.vrchat.com/platforms/android/quest-content-limitations/), both checked
2026-10-16.

## Reflection probes

Baked, box projection for interiors, resolution 64–128 (256 only for a hero probe). Box-project the room probe so reflections track walls, with the box matching the room's interior faces (a larger box shifts every reflection; renderers just outside a smaller box fall back to the skybox, so size it to the interior and check the walls' renderers sit inside). Blend probes sparingly — overlapping probes cost per-pixel work on every reflective surface.

## LTCGI

Realtime area lights (screens, neon strips, windows) via linearly transformed cosines — plug-and-play, free with attribution, and pairs with baked shadows from Unity or Bakery. Cheap relative to realtime lights, **not** cheap in absolute terms: it scales with vertex/pixel count of receivers. Optimize the world first, add LTCGI last, and test on device before committing. https://ltcgi.dev/

## Mirrors

A mirror re-renders the world from a second viewpoint: roughly **double** the frame cost, and **occlusion culling does not apply inside reflections** — a mirror facing a wall still renders what's behind it.

- Off by default, enabled by a player-facing toggle.
- Auto-disable when nobody is near (distance check on a slow interval, not per frame).
- Trim the **culling mask** to the minimum: usually Player, PlayerLocal, Default, and whatever décor must appear. Drop MirrorReflection, UiMenu, Water, and every layer of environment that is not visible in it.
- One high-quality mirror beats several scattered ones.

## Occlusion culling

- Mark large solid geometry **Occluder Static**, props **Occludee Static**.
- Bake with a *Smallest Occluder* value near your thinnest real wall (often 2–5 m for buildings, less for interiors). Too small explodes bake time and data size.
- It buys the most in cellular layouts (rooms, corridors), almost nothing in an open field — use LODs and cull distances there instead.
- Verify in the Occlusion Culling window's visualization mode, walking the camera through the world.
- Remember it does nothing for mirrors and nothing for `DrawMeshInstanced` groups.

## Debug order when lighting looks wrong

1. Is the lighting actually baked, or is the scene showing a stale/auto bake? Check Lighting → Baked Lightmaps.
2. Black avatars → missing probes / Light Volumes coverage.
3. Splotches, bleeding, seams → lightmap UV problems (`references/lightmap-uvs.md`), too-low texel density, or missing padding.
4. Blown-out or washed-out → intensity in linear space, an extra ambient source, or a skybox contributing more than intended.
5. Shadows missing on Quest → Subtractive mode requires exactly one realtime-mixed directional light and Contribute GI on receivers.
6. Huge build → lightmap count × resolution, and Directional mode doubling the data.
