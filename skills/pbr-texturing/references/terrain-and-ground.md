# Terrain and large ground surfaces

A ground seen across tens of metres fails two ways at once: one tiling map repeats into a visible grid, and one unique
map is too coarse up close (a 2048 map over 150 m is 13.7 px/m, *derived*, against T512 for ground seen at 1.5-3 m).
The route below works with the stock shaders on every platform (Unity's Standard on PC, VRChat's Standard Lite on
Android and iOS), so the mobile build keeps it. UVs for the ground (projection, slopes, chunks) are `uv-unwrapping`'s;
the shader facts are `references/engine-notes.md`'s.

## The layered ground: a macro map with the detail in the detail slot

| Layer | Holds | Where |
|---|---|---|
| Main albedo and normal: a unique **macro map** over the whole ground on UV0 (1024-2048) | Zones (grass, dirt, path, wet patches under trees), slow tonal and hue drift, large-scale forms | The main slots, UV0 with the whole ground in 0-1 |
| **Detail Albedo x2** and **Detail Normal**: a tiling ground texture centred on mid grey | The close-range grain: blades, pebbles, soil | The secondary maps, tiled by the Detail Albedo slot's own tiling on UV0 (`references/engine-notes.md`) |
| **Detail Mask** (alpha, on the main UV) | Where the detail shows: off on paths, paving and water edges, faded where another material takes over | The main albedo's tiling |

1. Choose the detail's density for the nearest distance the player stands from the ground (the texel classes:
   `uv-unwrapping`): T512 for ground seen from standing height. Its tile period is `detail_px / density` (1024 / 512 =
   2 m), and its tiling factor on the macro UVs is `ground size / period` (150 m / 2 m = 75 x 75, *derived*).
2. The detail tile is even at tile scale (`pbr_check.py --tiling`, `scripts/tile_flatten.py` when it fails) and has
   no stand-out feature: over 150 m it repeats 75 times each way, and anything distinctive in it reads as a grid at
   once. Its colour is neutral (mid grey in albedo x2): the macro map gives the colour, so one detail serves every zone.
3. Paint or bake the macro map from the layout: zones from the world's plan, a position mask for slopes and hollows,
   a low-frequency noise at several times the detail's period for drift (`references/wear-and-variation.md`), and the
   transitions (below). Check it at its own scale with the look-dev render, not on the sheet.
4. Keep the detail maps on mobile: they cost a sample, and they are what keeps the ground sharp when the Android and
   iOS overrides halve the macro map.

## Several ground materials

The stock shaders have one detail slot, so one ground mesh has one detail texture. In order of preference:

- **One neutral detail for every zone**, the zones told apart by the macro map's colour and the Detail Mask: the
  cheapest, works everywhere.
- **Separate meshes per material** (a cobbled plaza, a gravel path) with their own materials, the boundary covered by
  geometry: kerb stones, edging boards, a strip of grass fringe cards, a step. Never a bare UV seam between two
  materials on a flat ground: it reads as a cut.
- **A splat or height-blend shader** (two to four layers blended by a mask or vertex colour): a custom shader, allowed
  in VRChat worlds on every platform (`references/engine-notes.md`); each layer is another set of samples per pixel,
  so measure it on the mobile device before relying on it. Not written or tested here.

## Transitions

- Soft (grass into dirt): painted into the macro map's colour and the Detail Mask together, with a ragged edge at
  several scales, never a straight blend.
- Hard (paving against grass, a path's edge): geometry covers it (kerbs, edging, a fringe), and the detail mask is off
  under the paving.
- Rocks, roots and posts meeting the ground: sunk a few centimetres into it, their base darkened by a position mask
  (`references/wear-and-variation.md`), a decal or a card fringe where a hard line would show (*practice*). On sloped
  ground, a fence, a post or a rock is placed where it stands: its height from a ray cast down onto the ground mesh at
  each placement, its base sunk below the lowest point it covers, never one height for a whole run (posts float
  downhill and sink uphill). Grid pieces stay on the flat parts; ground-following pieces are Free pieces.

## Repetition on a large ground

Judge it where the player sees most of it: an eye-height view along the longest open sightline and a view from any
raised point (a hill, a balcony), in the engine, on the mobile build too. What breaks the detail's repeat at a
distance is the macro map (zones and drift every few metres), props and decals at irregular spacing, and the
lightmap. A detail tile that still reads as a grid at a grazing angle is uneven at tile scale (the gate) or too small
for the area: a larger period, or a second detail scale through a custom shader.

## Slopes, cliffs and chunks

- A top-down projection stretches a slope by 1 / cos(slope) (the UV distortion gate fails above 29.6 deg): ground over
  about 25 deg is a separate mesh (a bank, a cliff, rocks) with its own unwrap at the family's density
  (`uv-unwrapping`, slopes and terrain).
- A terrain cut into chunks keeps one projection origin so the macro and detail UVs continue across chunk edges, its
  normals computed before the cut and its chunk borders welded; the lightmap side (one renderer where it fits) is
  `vrchat-lighting-and-baking`'s.
