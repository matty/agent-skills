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

Two separate jobs, in this order: make the tile itself even at its own scale (the gate), then put variation back at
another period from another layer.

1. **The tile is even at tile scale.** `pbr_check.py --tiling` measures it (`lf`, a PROBLEM over 0.011; calibration:
   `references/pbr-values.md`). Seven of 20 Poly Haven library tiles failed it, six of them with an obvious grid in a
   3 x 3 composite: a library or scanned material is not even by default. Fix a PROBLEM with
   `scripts/tile_flatten.py` on every map of the set together (colour, roughness, height, AO, normal), so no patch
   survives in the maps left alone; it removes the tile's lowest harmonics and keeps the detail
   (weathered_brown_planks 0.0139 to 0.0012, brown_mud_leaves_01 0.0118 to 0.0019, the bands and patches gone).
   In Designer the same job is a highpass or equalise on the inputs before the graph tiles them.
2. **No distinctive feature inside a tile** (one big crack, one pale stone, one dark plank): it repeats on every tile
   and the eye finds the grid at once. Flattening does not remove it (rocks_ground_02's pale rocks still repeat at
   0.0034): retouch it out of the tile, or make it a decal and place it where it belongs.
3. **Variation comes back from another layer, at another period:** never by leaving it in the tile. What can carry it
   depends on the shader and on whether the surface is one mesh or a kit of instanced pieces:

   | Layer | Carries | Where it works |
   |---|---|---|
   | A unique macro map on the main UV with the tiling detail in the detail slot (main albedo low-resolution, unique; Detail Albedo x2 and Detail Normal tiled) | Large-scale colour, wear and zones over a whole surface | One mesh that is not instanced: terrain, a ground plane, a long wall built as one piece. Unity Standard and VRChat's Standard Lite both have the slots (`references/engine-notes.md`); the ground recipe: `references/terrain-and-ground.md` |
   | Piece variants (`_A`, `_B`, `_C`) with different wear, stains or panel layouts | Variation between copies of a kit piece | Every shader; placed by the rule in the kit variation policy below |
   | Decals and props | One-off marks, interrupting long runs | Every shader; at irregular intervals |
   | The baked lightmap and its probes | Light falloff, bounce colour, occlusion | Every lightmapped surface: it already breaks a repeat, so do not flatten the lighting |
   | Vertex colour | A tint per vertex | Only where every target shader reads it (Standard Lite multiplies it in; Unity's Standard ignores it) |
   | A world-space or stochastic tiling shader | Continuous variation at any period, no UV seams | A custom shader: VRChat allows them in worlds on every platform (`vrchat-world-sdk-setup`); measure its cost on the mobile device before relying on it |

   On a kit of instanced pieces, a detail or macro layer whose period is longer than the placement step restarts at
   every joint like the tile does (uv-unwrapping's joint rule): its period divides the step, or the variation comes
   from variants, decals and the lightmap.
4. Shift value by a few percent and roughness by 0.05-0.1 in whatever layer carries it: big jumps read as stains.
- A detail map at a finer scale gives close-range sharpness without raising the base map (the engine's detail slots:
  `references/engine-notes.md`).
- Trims, decals and props interrupt long runs; place them at irregular intervals.

## Kit variation policy

- Two or three visibly different variants of the most repeated pieces (a crack, a patched panel, a different panel
  arrangement), sharing the family's material: variants cost meshes and memory, not SetPass calls, and each still
  instances or batches with its own copies.
- A variant must differ at the viewing distance; a near-duplicate is a draw call for nothing.
- Placement (*practice*): no two identical variants side by side, no sequence that repeats (A B C A B C reads as a
  longer tile), and on a run longer than about four tile periods a breaker (a pilaster, a door, a trim, a prop) at an
  irregular spacing.
- Vertex colour as a cheap tint varies copies only where every target shader reads it: VRChat's mobile Standard Lite
  multiplies albedo by vertex colour while Unity's Standard ignores it (`references/engine-notes.md`), so a world on
  both looks different on each.

## Judging it

| Look at | For |
|---|---|
| A wide view at eye height (1.6-1.7 m) across the longest run of the material | Repetition, the grid of the tile, variants spread well |
| `pbr_check.py --tiling` (`--trim` for a trim sheet) | Tile-scale variation (`lf`) and seams along part of an edge: PROBLEM lines block |
| The 3 x 3 composite from `pbr_check.py --tiling --out` | Seams and a single tile's stand-out features (the check cannot see a repeated distinctive feature) |
| A close-up from the nearest place a player can stand | Wear scale against texel density, sharpness, shimmer |
