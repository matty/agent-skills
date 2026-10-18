# Wear, variation and repetition

Clean, uniform, endlessly repeated surfaces are what make a world look generated. This page is where wear goes, how
much, and how to stop a kit's repetition showing. Everything here is *practice*: judge the result at the viewing
distance, not on the texture sheet.

## Decide the story first

Give each material one history, from the art direction (pristine, lived-in, weathered, derelict): what touched it,
what fell on it, how old it is. Wear that has no cause reads as a grunge filter. Keep the wear level the same across
families that sit side by side.

## Where wear goes: masks from the baked maps

| Wear | Mask from | What it changes |
|---|---|---|
| Chipped or rubbed edges | Curvature, convex side (above 0.5 in both bakers measured here), broken up with noise | Lighter or a lower layer showing; paint chipped to bare metal turns metallic to 1 there; edges polish smoother |
| Dirt in crevices and corners | AO and the concave side of curvature | Darker, rougher, less saturated |
| Dust on tops | World-space normal, up-facing (Z up) | Lighter, rougher, desaturated; never on undersides |
| Scuffs and splash near the floor | Position, the lowest 20-30 cm | Darker, rougher; rising damp on masonry |
| Hand contact | Painted or masked by hand: handles, switches, rails, door edges | Smoother and slightly darker (polish and grime) |
| Streaks below sills and ledges | Position plus world normal, running down from top edges | Vertical darker and smoother runs |
| Fading | World normal facing the light, on outdoor materials | Lower saturation, slightly lighter |

Keep metallic binary while doing it: dirt and rust on metal lower metallic towards 0 where they cover it, they do not
darken the metal colour (`references/pbr-values.md`).

## Scale and restraint

- A wear feature smaller than about 2 texels at the surface's texel density turns into noise in the mips: scale chips
  and specks to the density, not to the source resolution.
- Large flat areas stay mostly clean; put the contrast at edges, corners, bases and contact points.
- Vary value and roughness gently: a few percent of value and about 0.05-0.1 of roughness carry most wear; big jumps
  read as stains.
- One generic noise over everything is the grunge-filter look: drive wear from the masks above.

## Breaking up a tiling material

- Macro variation: a low-frequency mask at a period 3-7 times the tile's (or in world space) shifting value by a few
  percent and roughness by 0.05-0.1, so the tile's repeat stops lining up into a grid.
- No strong unique feature inside a tile (one big crack, one dark stone): it repeats on every tile and the eye finds
  the grid at once.
- A detail map at a finer scale gives close-range sharpness without raising the base map (the engine's detail slots:
  `references/engine-notes.md`).
- Trims, decals and props interrupt long runs; place them at irregular intervals.

## Kit variation policy

- Two or three visibly different variants of the most repeated pieces (a crack, a patched panel, a different panel
  arrangement), sharing the family's material: variants cost meshes and memory, not SetPass calls, and each still
  instances or batches with its own copies.
- A variant must differ at the viewing distance; a near-duplicate is a draw call for nothing.
- Vertex colour as a cheap tint varies copies only where every target shader reads it: VRChat's mobile Standard Lite
  multiplies albedo by vertex colour while Unity's Standard ignores it (`references/engine-notes.md`), so a world on
  both looks different on each.

## Judging it

| Look at | For |
|---|---|
| A wide view at eye height (1.6-1.7 m) across the longest run of the material | Repetition, the grid of the tile, variants spread well |
| The 3 x 3 composite from `pbr_check.py --tiling --out` | Seams and a single tile's stand-out features |
| A close-up from the nearest place a player can stand | Wear scale against texel density, sharpness, shimmer |
