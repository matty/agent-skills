# Finishing a piece from its greybox

Scope: turning a greybox piece (exact extents, pivot and openings, no detail) into a finished piece that reads right
from where players stand, before UVs and texturing. Topology, chamfer stacks and validation stay in the other
references of this skill; texturing, trim sheets and bakes are the `pbr-texturing` skill's.

Numbers marked *derived* follow from the headset maths below (`scripts/detail_scale.py` computes them); *practice*
marks working rules with no published source: starting points, settled by looking from the player's viewpoint.
Sources, checked 2026-10-18: headset pixels per degree (Quest 2 and 3S 20, Quest 3 25) from
https://roadtovr.com/quest-3s-quest-3-quest-2-specs-compared/ (2024-09-25); adult interpupillary distance about 63 mm
(Dodgson 2004, "Variation and extrema of human interpupillary distance", https://doi.org/10.1117/12.529999, as cited
by later surveys; the paper itself was not read).

## 1. Start from intent

Collect these before adding a single loop, and put any that are missing in your report:

| Input | Gives |
| --- | --- |
| Reference images for the piece (the brief's, the mockups, photos the user gave) | Proportions, profiles, what a real one has |
| The piece's description and detail list from the brief | The features to model, each with its size (`references/real-world-sizes.md` when the brief gives none) |
| Nearest and usual viewing distance (where players stand closest, where they mostly see it from) | Texel class, stereo relief and narrowest feature: `python scripts/detail_scale.py <d>...` |
| Triangle budget for the piece | How much secondary form fits; spend it on silhouette and close-up edges first |
| The greybox | Footprint, pivot and openings: fixed. Detail goes inside the extents, never past them |

A piece with no reference and no detail list gets a short one written into the report from its description (feature,
size, geometry or texture) before modelling, so the review has something to check against.

## 2. Detail hierarchy

| Level | What | Goes into | Judged from |
| --- | --- | --- | --- |
| Primary | Massing, silhouette, openings, big steps in depth | Geometry, set by the greybox | The far viewpoint: it must read with every texture off |
| Secondary | Frames, panels, mouldings, reveals, sills, rails, chamfers, bolts and hinges that stand proud | Geometry or a baked normal / trim bevel, by the rules in section 3 | The usual viewing distance |
| Tertiary | Grain, mortar texture, scratches, small dents, stitching | Textures (normal, roughness, colour): `pbr-texturing` | Close up |

Work in that order: block the secondary forms at their real sizes, then add chamfers, then review (section 7). A piece
that only has primary forms looks like a greybox with a material on it.

## 3. Geometry, baked normal or texture: decide per feature

Three rules, all from the headset's pixels per degree (ppd, 20 for Quest 2 and 3S) and the distance d in metres:

- **Stereo relief** (*derived*): two points dz apart in depth differ in binocular disparity by about IPD x dz / d^2
  radians. One pixel is theta = (pi / 180) / ppd radians (8.7e-4 at 20 ppd), so the smallest depth step that moves a
  whole pixel between the eyes is dz = d^2 x theta / IPD, about **0.014 x d^2 m** at 20 ppd and IPD 63 mm. Relief
  shallower than that at the nearest viewing distance looks the same as a normal map; deeper relief shows as depth.
  Sub-pixel disparity is still seen a little, so treat it as a guide, not a cliff.
- **Narrowest feature** (*derived*): one pixel spans d / 1150 m at 20 ppd. A chamfer, rail, cable or frame narrower
  than about 2 px at the distance players usually see it from shimmers as the head moves (*practice*: 2 px).
- **Texel class**: 1150 / d px/m is what the headset resolves (texture density itself is the `uv-unwrapping` skill's).

`detail_scale.py` at 20 ppd (`--ppd 25` for Quest 3, which needs 1.25 x the density and 0.8 x the relief):

| d (m) | Headset px/m | Texel class | Relief that shows in stereo | 2 px wide |
| --- | --- | --- | --- | --- |
| 0.5 | 2300 | T2048 | 3.5 mm | 0.9 mm |
| 1 | 1150 | T1024 | 13.9 mm | 1.7 mm |
| 2 | 575 | T512 | 55 mm | 3.5 mm |
| 3 | 383 | T256 | 125 mm | 5.2 mm |
| 6 | 192 | T128 | 499 mm | 10.4 mm |

Classes: T2048 under 0.75 m (handheld, face-close), T1024 0.75-1.5 m (desks, counters, switches, door handles), T512
1.5-3 m, T256 3-6 m, T128 6-12 m, T64 over 12 m; each gives at least two thirds of the headset's density at the near
edge of its band.

| Feature | Make it | Why |
| --- | --- | --- |
| On the silhouette (a cornice, a sill or a handle seen in profile) | Geometry | A normal map never changes the outline |
| Relief deeper than the stereo threshold at the nearest viewing distance | Geometry | It shows depth between the eyes |
| Relief shallower than that, seen roughly face-on | Baked normal map, or the trim sheet's bevel strip | Looks the same in stereo and costs no triangles |
| Seen at grazing angles (a wall along a corridor, a step edge, a floor) with relief over a few mm | Geometry, or flatten it | Normal maps do not move with the head (no motion parallax): at grazing angles they read as painted |
| Under 2 px wide at the usual distance | Widen it, move it into the texture or the trim bevel, or drop it | It shimmers |
| Surface texture: grain, mortar, scratches | Texture only | Below every threshold |

Worked examples at 20 ppd: a window reveal 60 mm deep, nearest view 2 m (threshold 55 mm): geometry. A panel
moulding 8 mm proud, nearest view 1.5 m (threshold 31 mm), seen face-on: normal map or trim bevel. A handrail 40 mm
across, usually seen from 3 m (2 px is 5.2 mm): geometry, fine. A 5 mm chamfer on a facade usually seen from 5 m
(2 px is 8.7 mm): widen it to about 10 mm or leave it to the texture.

## 4. Chamfers and joints

- Chamfer every edge players see up close: one or two segments, 5-20 mm (*practice*), never narrower than 2 px at the
  usual distance. The modifier stack and normals are `hard-surface.md`; check flatness with `audit_stack`.
- **Never chamfer an edge or face that meets a neighbouring kit piece.** Two chamfers meeting at a joint make a
  V-groove at every joint: a dark line in the lightmap and a highlight break in reflections. Joint faces stay flat
  and square; round the outer corners of a run with its corner and end pieces instead.
- Shared profiles: a moulding, skirting or cornice that runs across pieces has the identical section at both ends of
  every piece, on the same vertex rows (`grid-layout.md`, rows), so it continues without a step. Check the joint with
  `joint_match` (`validation.md`).
- A curved piece meeting a straight one (a curved wall, an apse, a round corner): its smooth end vertices lean half a
  facet angle off the straight neighbour (measured, Blender 5.2.2: 2.81 deg for 16 segments per quarter turn), a
  crease in the shading at every such joint. Set the joint vertices' custom normals to the shared surface normal
  (`me.normals_split_custom_set_from_vertices(normals)`: measured 0 deg after) and check `joint_normals` (under about
  0.5 deg, *practice*).
- A piece let into another at an angle (an arcade's spandrel or an engaged column against a round tower, a buttress
  against a wall) is a masonry abutment, not an edge-to-edge joint: it may run a few centimetres into its neighbour,
  every face it buries hidden, but no face of it may lie in the neighbour's face plane. An engaged column's capital
  and base stand proud of the wall face or are let into it, never flush (a capital flush with the wall z-fought
  through the brick, measured in a dry run); QA reports such faces between placements.
- Openings keep their greybox size; frames and reveals go inside them, the lining flush with the wall face (*practice*).

## 5. Imperfection without breaking the kit

- Only on the body of the piece, never on joint faces or the footprint: a slight sag along a long beam or shelf (a few
  millimetres per metre, *practice*), chipped or softened corners where hands and feet hit, boards of uneven width, a
  brick course a little off on one variant.
- Size it for the viewing distance: imperfection under 2 px at the usual distance shimmers or vanishes. Leave the
  small scale to textures and decals (`pbr-texturing`).
- Repeated pieces: give variants (`_A`, `_B`) different imperfections, sharing one material, rather than copies that
  differ by nothing.

## 6. Mid-poly or a high-poly bake

| Piece | Route |
| --- | --- |
| Hard-surface kit pieces, furniture, frames | Mid-poly: real chamfers with custom normals (`hard-surface.md`); texture from tiling or trim materials, no bake needed |
| Ornament, carving, cast or worn detail | A high-poly baked onto the low-poly; the low-poly keeps the silhouette and any relief past the stereo threshold (section 3: carving seen close keeps its depth step in the low). Building the pair: `high-and-low-poly.md`; the bake is the `pbr-texturing` skill's |
| Organic props (rocks, roots, food) | A modifier-stack sculpt (brush strokes do not run headless), a QuadriFlow or decimated low, UVs, the sculpt baked onto it: `organic-and-cloth.md` |
| Cloth props (curtains, tablecloths, cushions) | Blender's cloth simulation stepped and applied (or Marvelous Designer through its MCP when connected), a low with its border kept where it meets a rail or edge, UVs, the simulated folds baked onto it: `organic-and-cloth.md` |
| Foliage cards | The `pbr-texturing` skill |

## 7. Review

- Renders with `scripts/review_render.py` (studio and reflective matcap, wire for topology): one from eye height
  (1.6-1.7 m) at the nearest walkable distance, one at the usual distance, and a close-up of each detail item. Put the
  reference images beside them in a contact sheet.
- Check, and report each with its measured value:
  - every item in the detail list is there at its size (measure the feature's vertices or bounds in Blender, in
    millimetres);
  - silhouette and proportions match the reference from the far viewpoint;
  - no chamfer or thin part under 2 px at the usual distance (`detail_scale.py`);
  - joint faces unchamfered, profiles continuous (`joint_match`);
  - triangles within the budget, and the audit clean (`validation.md`).
- What a particular engine does with chamfers and custom normals: `engine-notes.md`.
