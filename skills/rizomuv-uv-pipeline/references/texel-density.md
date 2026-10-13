# Texel density: choosing it, packing to it, checking it

How to make RizomUV deliver exactly the texel density a surface should get. Worked out for a
PC VR dark ride (9 Oct 2026), where every viewing position is known; the method carries to any world.

## Contents

- Choosing the density
- Unique textures: size and pack
- Lightmaps are a separate density
- Checks

## Choosing the density

The density comes from viewing distance: about `1150 / d` px/m at 20 pixels per degree, quantised into classes
T512 (0-3 m), T256 (3-6 m), T128 (6-12 m) and T64 (> 12 m). Shared trims and tiling materials keep one density
everywhere (512 px/m for a T512-led world) and far surfaces sample lower mips; never make lower-density copies.
The derivation, class assignment and trim rules are in the `uv-unwrapping` skill (texel density); this file is how
RizomUV delivers a chosen density exactly.

## Unique textures: size and pack

1. Size the map from the class and the surface it must hold, with the packing coverage you expect (about 0.6 from
   RizomUV on props):

       map_px = next_pow2(TD x sqrt(area_m2 / 0.65)), capped (2048 is a sane cap for PC VR; lower on mobile)

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
surfaces 30, tunnels 12, exteriors 8 and facades 6 in the ride; the engine's lighting setup owns scene
lightmap resolution and per-renderer scale; `vrchat-lighting-and-baking` for Unity / VRChat). Lightmappers (Unity's, Bakery) give each renderer its own rectangle, so pack each
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
