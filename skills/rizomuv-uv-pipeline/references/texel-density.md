# Texel density: choosing it, packing to it, checking it

How many texels per metre a surface should get, and how to make RizomUV deliver exactly that. Worked out for a
PC VRChat dark ride (9 Oct 2026), where every viewing position is known; the method carries to any world.

## Contents

- Principle: match the display
- Classes by viewing distance
- Shared trims and tiling materials
- Unique textures: size and pack
- Lightmaps are a separate density
- Checks

## Principle: match the display

A texture only needs as many texels per metre as the headset shows pixels per metre at the closest distance anyone
sees the surface from. Fewer looks soft; more is memory the GPU never samples (it reads a smaller mip).

A headset shows roughly 20 pixels per degree (Index about 14, Quest 3 about 25, Bigscreen Beyond about 32; take
horizontal pixels per eye divided by the horizontal field of view for any other device, and re-check these as
headsets change). One metre at distance d spans 57.3 / d degrees, so at 20 ppd the screen shows about

    px_per_m = 1150 / d          770 at 1.5 m, 380 at 3 m, 190 at 6 m, 95 at 12 m

## Classes by viewing distance

Quantise to powers of two so textures and trims line up:

| Class | Nearest viewing distance | Target | Typical surfaces |
|---|---|---|---|
| T512 | 0-3 m | 512 px/m | anything within arm's reach of a seat or a walkway, the vehicle itself, door reveals |
| T256 | 3-6 m | 256 px/m | the far side of a room, upper walls, most ceilings |
| T128 | 6-12 m | 128 px/m | back walls of large halls, beds beyond a hedge, a facade seen across a garden |
| T64 | > 12 m | 64 px/m | skyline, treeline cards, the sky dome |

When viewers follow a fixed path (a ride), measure it: sample eye points along the path for every seat, take the
shortest distance from any of them to each placed instance, and assign its class automatically. In a walkable
world, use the nearest point a player can stand, at eye height. A prop used in several places takes the class
of its nearest instance.

## Shared trims and tiling materials

One density everywhere (512 px/m for a T512-led world), authored once: a 2048 trim sheet covers 4 m of strip; a
2048 tile repeats every 4 m. Far surfaces use the **same** material and sample lower mips. Do not make
lower-density copies: they cost a material and a texture, break batching and instancing, and save nothing. Raise
anisotropic filtering (4+) on floors seen at grazing angles. Trim UVs are best generated where the mesh is built
(exact strip coordinates); RizomUV `Hotspot` can match irregular pieces to trim rectangles.

## Unique textures: size and pack

1. Size the map from the class and the surface it must hold, with the packing coverage you expect (about 0.6 from
   RizomUV on props):

       map_px = next_pow2(TD x sqrt(area_m2 / 0.65)), capped (2048 is a sane VRChat cap)

   `rizom_uv.texture_size(TD, area_m2)`.
2. Pack at that density, not "fill the tile":

       ru.pack_spec(map_px, pad_px=8, margin_px=4, px_per_unit=TD)

   This is `Scaling.Mode` 6 (USER_SPECIFIED) with `SpecifiedScale = TD / map_px`, `Optimization "None"` and
   translate-only layout. Mode 7 (TEXEL_DENSITY) would need `TD x 100` for metre input, and the default
   `Optimization "Fill"` would throw the density away (`api-cheatsheet.md`).
3. Check `fits`. If the islands do not fit at that density, RizomUV leaves them where they were and says nothing;
   `blender_rizom` then writes nothing and reports "does not fit". Go up one map size (within the cap); if the cap
   is already reached and the density would fall below 0.8x its class, split the piece into two texture sets or
   remove faces nobody sees. Do not accept it silently. Thin, banded pieces pack loosely: the arch needed more than
   a 2048 map at 512 px/m although `texture_size` assumes 0.65 coverage.
4. Mesh coordinates must be in metres at their placed scale, or the density is off by the object's scale
   (`blender_rizom.mesh_arrays` applies the world matrix, read fresh from the depsgraph).
5. Objects sharing one mesh share its UVs: at different world scales they get different densities.
   `unwrap_objects` unwraps the mesh once and reports every user's density; give differently scaled copies their
   own mesh (or scale-apply them) when their class matters.

Padding: 8 px at 1024 keeps islands one pixel apart down to the 128 px mip; scale it with the map (4 px at 512,
16 px at 2048) if distant mips bleed.

## Lightmaps are a separate density

Lightmaps are measured in texels per metre per scene, much lower than textures (interiors around 20, close-up
surfaces 30, tunnels 12, exteriors 8 and facades 6 in the ride; see `vrchat-lighting-and-baking` for scene
lightmap resolution and Scale In Lightmap). Unity and Bakery give each renderer its own rectangle, so pack each
mesh's UV2 on its own, filling the tile, at the size that rectangle will have:

    footprint_px = next_pow2(sqrt(area_m2) x texels_per_m x scale_in_lightmap), clamped 64-1024

`rizom_uv.lightmap_footprint()`. Then `ru.pack_spec(footprint_px, pad_px=4, margin_px=2)` (fill mode). Padding in
pixels **at the footprint** is what survives the atlas; a padding chosen for 1024 px is a fraction of a texel at
128 px and the bake bleeds. `blender_rizom` packs the lightmap UV at a fixed 128 px unless told otherwise:
`unwrap_object(..., uv2="footprint", lightmap_texels_per_m=20)` computes the footprint from the mesh area, or pass
your own `pack_spec`.

## Checks

- Unique textures within 0.8-1.25x of their class (`uv_metrics.texel_density()["px_per_unit_mean"]`); measured
  packs land exactly on the asked density whenever they fit (48 packs, 0.00% error).
- Shared materials at their fixed density within 10%.
- Density variation inside one piece: CV <= 0.15 (RizomUV's fill and USER_SPECIFIED modes give one ratio for
  every island, so a high CV means distortion inside islands, not packing).
- In the editor, a debug checker coloured by class shows mismatches at a glance before anyone signs off a scene.
