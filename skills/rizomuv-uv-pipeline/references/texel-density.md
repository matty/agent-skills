# Texel density: choosing it, packing to it, checking it

How to make RizomUV deliver exactly the texel density, padding and lightmap footprint a surface should get. The
density classes, padding per map size and UV2 authoring rules (2-texel gaps) belong to the `uv-unwrapping` skill;
lightmap resolution, the footprint numbers and Scale In Lightmap to `vrchat-lighting-and-baking` (for Unity /
VRChat). This file states the same values and shows how RizomUV meets them. Worked out for a PC VR dark ride
(9 Oct 2026); the method carries to any world.

## Contents

- Choosing the density
- Unique textures: size and pack
- Padding
- Lightmaps are a separate density
- Checks

## Choosing the density

The density comes from viewing distance: about `1150 / d` px/m at 20 pixels per degree, quantised into classes
T2048 (< 0.75 m, handheld), T1024 (0.75-1.5 m), T512 (1.5-3 m), T256 (3-6 m), T128 (6-12 m) and T64 (> 12 m).
Shared trims and tiling materials keep one density everywhere (512 px/m for a T512-led world, with a detail map for
walls players walk right up to) and far surfaces sample lower mips; never make lower-density copies.
The derivation, class assignment and trim rules are in the `uv-unwrapping` skill (texel density); this file is how
RizomUV delivers a chosen density exactly.

## Unique textures: size and pack

1. Size the map from the class and the surface it must hold, with the packing coverage you expect (about 0.6 from
   RizomUV on props):

       map_px = next_pow2(TD x sqrt(area_m2 / 0.65)), capped (2048 is a sane cap for PC VR; lower on mobile)

   `rizom_uv.texture_size(TD, area_m2)`.
2. Pack at that density, not "fill the tile":

       ru.pack_spec(map_px, px_per_unit=TD)          # padding map_px / 64 (the minimum), margin half of it

   This is `Scaling.Mode` 6 (USER_SPECIFIED) with `SpecifiedScale = TD / map_px`, `Optimization "None"` and
   translate-only layout. Mode 7 (TEXEL_DENSITY) would need `TD x 100` for metre input, and the default
   `Optimization "Fill"` would throw the density away (`api-cheatsheet.md`).
3. Check `fits`. If the islands do not fit at that density, RizomUV leaves them where they were and says nothing.
   A `hard` attempt that does not fit is followed by the organic preset, because the usual cause is a cut, not the
   map: `hard` joins a bevel or chamfer ring into one long island (a 2.4 x 0.04 x 0.3 m strip with a 6 mm bevel
   made a ring about 5.4 m long that fitted neither 1024 nor 2048 px at 512 px/m; the organic preset cut it into 12
   islands that fitted 2048, measured 17 Oct 2026). If that does not fit either, `blender_rizom` writes nothing and
   reports "does not fit". Then, in this order: mark seams along the bevels or chamfers (or pass `kind="organic"`);
   go up one map size (within the cap); only when the cap is reached and the density would fall below 0.8x its
   class, split the piece into two texture sets or remove faces nobody sees. Do not accept it silently. Thin,
   banded pieces pack loosely: the arch needed more than a 2048 map at 512 px/m although `texture_size` assumes
   0.65 coverage.
4. Mesh coordinates must be in metres at their placed scale, or the density is off by the object's scale
   (`blender_rizom.mesh_arrays` applies the world matrix, read fresh from the depsgraph).
5. Objects sharing one mesh share its UVs: at different world scales they get different densities.
   `unwrap_objects` unwraps the mesh once and reports every user's density; give differently scaled copies their
   own mesh (or scale-apply them) when their class matters.

## Padding

The `uv-unwrapping` skill's rule: the gap between islands is map_px / 64 (16 px at 1024, 32 at 2048), and that is
the minimum, not a comfortable default: Polycount's "minimum padding" (8 px at 1024) is the padding around each
shell, and the gutter between two shells is twice it (http://wiki.polycount.com/wiki/Edge_padding, checked
2026-10-17). The gap to the tile edge is half the gap (map_px / 128, 8 px at 1024). `pack_spec(map_px)` uses both;
pass a larger padding if you need one, never a smaller.

Directional textures pack with rotation off after a pre-orientation, never with rotation off alone (that keeps
whatever orientation the unfold gave each island): `directional="grain"` lays every island's long side along U
(wood grain, brushed metal; measured 76 of 76 plank faces), `directional="upright"` turns world up to +V (text,
decals, signage). Per object, the `rizom_directional` property wins.

## Lightmaps are a separate density

Lightmaps are measured in texels per metre per scene, much lower than textures (interiors around 20, close-up
surfaces 30, tunnels 12, exteriors 8 and facades 6 in the ride); `vrchat-lighting-and-baking` owns those numbers,
each renderer's Scale In Lightmap and the footprint rule. Unity scales a renderer's UV2 by

    footprint_px = texels_per_m x sqrt(area_m2 / b) x Scale In Lightmap x 0.5^n

texels per UV unit, area = the mesh's surface area as placed, b = the UV2 charts' bounding-box area as a share of
the tile, n = the LOD level of a `<Piece>_LOD<n>` renderer (each LOD gets its own lightmap space; LOD0 1, LOD1 0.5,
LOD2 0.25). Measured in Unity 2022.3.22f1: within 0.6% for b from 0.79 to 0.95 on five renderers (2026-10-16; a
2 x 3 x 0.2 m wall at 60 texels/m with b 0.850 got 242.8 px), exact for b 0.125-1 and LOD scales 0.995 / 0.492 /
0.250 (2026-10-17). Use b = 0.85 only to plan before a UV2 exists. Unity packs the charts' bounding box, not the
whole tile, so the box's aspect does not matter, but empty space inside it does: the charts get texels_per_m x
sqrt(charts' area / box area); the report gives `box_fill` and notes one under half full at 64 px or more. The UV2
rules (the `uv-unwrapping` skill's): inside 0-1, no overlap, gaps of at least 2 texels between charts and at least 1
texel to the tile edge. A padding chosen for a whole 1024 map is a fraction of a texel on a small piece and the bake
bleeds.

How the scripts meet it:

1. **Pack for b = 1, the worst case**: gap in UV = 2 / (texels_per_m x sqrt(area) x scale), so the gaps hold at 2
   texels whatever bounding box the packer makes. `rizom_uv.lightmap_spec(mesh, texels_per_m, scale)` packs at
   `map_px = max(128, next_pow2(that footprint))` with `pad_px = ceil(2 x map_px / footprint + 0.5)` and
   `margin_px = ceil(map_px / footprint + 0.5)` (the 0.5 px is what PaddingPerfect's pixel grid can lose).
2. **Pack a shared mesh for its smallest renderer**: every object using the mesh counts, at its own placed size and
   its own Scale In Lightmap (`rizom_lightmap_scale`, else `lightmap_scale`) times 0.5^n for a `<Piece>_LOD<n>`
   object or mesh; `users=` (or `lod=n`) in `lightmap_spec`, `blender_rizom.renderers(ob)` in Blender. A LOD1 is
   packed for half the footprint, so its gaps are twice as wide in UV.
3. **Check at the measured b**: `rizom_uv.layer_report` measures `bbox_share`, works out every renderer's footprint
   and grades the gaps and edge strictly in texels at the smallest (`footprints_px`, `graded_at_px`).

`blender_rizom` does all three by default (`uv2="footprint"`, `lightmap_texels_per_m` = the scene's Lightmap
Resolution). Measured 17 Oct 2026: a mesh shared by a 1 m box and a half-size copy, 20 texels/m: footprints 67.5
and 33.7 px, closest gap 2.9 texels at 33.7 px.

Under 64 px (house guidance, no published source): a Free prop (a Free-sized PROP or FOL piece; props in a zone
with lighting states stay lightmapped) is probe-lit (Receive Global Illumination: Light Probes, still Contribute
GI); every other piece, grid pieces (walls, floors, ceilings) included, is never made probe-lit by this rule: raise
its Scale In Lightmap or the scene's texels per metre. The line notes `lightmap N px under 64`, judged on LOD0 only
(a LOD1+ follows its piece, as vrchat-world-qa does), and the lightmap UV is still written, padded for that
footprint. Never lower Scale In Lightmap below what the UV2 gaps were packed for.

When the smallest renderer's b = 1 footprint F cannot hold the charts with 2-texel gaps, the lightmap UV is packed
for a larger footprint instead (`rizom_uv.pack_lightmap`): 64 px when F is under 64, else 2F, then 2x, 4x and 8x
that until one passes. Every render mesh so keeps a valid UV2 (the repo's QA wants one on probe-lit props too), and
the line notes `UV2 packed for N px: too small`, with the note "too small for 2-texel gaps: probe-light it (a Free
prop, or a LOD via lod_lightmap: false), or raise its Scale In Lightmap" and the factor ("probe-lit only" past
64 px). "Too small" is either below `rizom_uv.lightmap_capacity_px(charts)` (2 x ceil(sqrt(charts)) texels, 6 px for
6 charts; measured 17 Oct 2026 on a plank's and a cube's 6 charts: 3 and 5 px overlapped, 7 px and up packed
clean) or a pack that failed its gaps. Measured 18 Oct 2026: a craggy 5120-face rock (522 charts, 45 px) failed at
64 and 128 px and passed at 256, with the note "probe-lit only, or raise its Scale In Lightmap 5.6x"; a plank with a
half-size copy at Scale In Lightmap 0.5 (3.3 px) passed at 64. At F of 64 px or more the piece is meant to be
lightmapped: its UV2 is written for the larger footprint, and the line says REVIEW. Only when no step passes is
no UV2 written, an older `UVMap_Lightmap` removed rather than left at index 1, and the under-64 note still printed.

## Checks

- Unique textures within 0.8-1.25x of their class (`uv_metrics.texel_density()["px_per_unit_mean"]`); measured
  packs land exactly on the asked density whenever they fit (48 packs, 0.00% error; 300 px/m asked, 300.0 got on
  17 Oct 2026).
- Shared trims and tiling materials within 10% (0.9-1.1x) of their fixed density.
- Density variation inside one piece: CV <= 0.15 (RizomUV's fill and USER_SPECIFIED modes give one ratio for
  every island, so a high CV means distortion inside islands, not packing).
- Lightmap UV: the report's `UVMap_Lightmap` layer has `padding_pairs_below_min` 0 and `margin_ok` at its
  `graded_at_px` (the larger footprint when `fallback` holds the too-small note). `box_fill` is advisory: under
  0.5 it is noted at footprints of 64 px or more only, as vrchat-world-qa does.
- In the editor, a debug checker coloured by class shows mismatches at a glance before anyone signs off a scene.
