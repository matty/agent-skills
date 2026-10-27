# High and low poly: building a pair that bakes cleanly

Scope: when a piece needs a bake, how to build the high poly, how to build the low poly it bakes onto, how to pair the
parts, and how to prove both before baking. The bake itself (cage, filters, maps) is the `pbr-texturing` skill's; UVs
(seams on hard edges, padding) are `uv-unwrapping`'s; detail sizes are `form-and-detail.md`; organic sculpts and cloth
are `organic-and-cloth.md`.

Everything marked *measured* was run on Blender 5.2.2 headless (`blender -b`) on 2026-10-27, baked through
`pbr-texturing`'s `bake_maps.py` and compared texel by texel; *derived* follows from the headset maths in
`form-and-detail.md`; *practice* is a working rule with no published source, settled by looking from the player's
viewpoint.

## 1. Does the piece need a high poly

| Piece or feature | Route |
| --- | --- |
| Hard-surface kit pieces, furniture, frames | Mid-poly: real chamfers with custom normals (`hard-surface.md`), tiling or trim materials; no bake |
| Ornament, carving, casting, rivets, stitching, worn or damaged detail | A high poly baked onto the low |
| Organic props (rocks, roots, bark, food), cloth | A sculpted or simulated high baked onto a retopologised low (`organic-and-cloth.md`) |
| Any relief deeper than the stereo threshold at the nearest viewing distance (0.014 x d^2 m: 3.5 mm at 0.5 m, 14 mm at 1 m), or on the silhouette | Its main step is geometry in the low; the bake carries what lies inside that step |

**Carving seen up close** is both: model the carving's depth step in the low (the field sunk against its border, a
raised panel, a rim, anything on the silhouette), then bake the carving inside that step from the high. At 0.5 m a
carved panel 6 mm deep has its 6 mm step in the low and its 1-3 mm detail in the normal map; give the step its own
line in the triangle budget. A normal map on its own reads as painted in stereo at that range, and parallax maps are
not available on every target (VRChat's mobile shaders have none).

## 2. Build the high poly

| Form | Route | Blender, headless |
| --- | --- | --- |
| Hard-surface edges (brackets, hinges, machined parts, box edges) | A Bevel modifier (3-5 segments, profile 0.5) on the base mesh, shaded smooth with every fold marked sharp; or Subdivision Surface with edge creases or support loops | Edge creases are the `crease_edge` FLOAT EDGE attribute (4.0+): set to 1 it keeps a level-3 subdivided cube's corners square (half-width 0.500 m against 0.420 without), *measured* |
| Holes, cut panels, vents (booleans) | Boolean, applied, then sharp edges by angle on the result: `me.set_sharp_from_angle(angle=math.radians(30))`, shade smooth | Boolean and Bevel modifiers apply headless |
| Merged or organic forms that booleans would leave as knots | Voxel remesh, then a Smooth modifier, then subdivide to density | `ob.data.remesh_voxel_size = s; bpy.ops.object.voxel_remesh()` or a Remesh modifier in VOXEL mode, *measured* headless |
| Surface detail lying on a part (rivets, bolts, screws, stitching, labels) | Floaters: separate high objects resting on the surface, no boolean | Raytraced bakes take them; Pointiness curvature does not see where they meet the body (`pbr-texturing` baking reference) |
| Sculpted relief (rock, bark, carving) | Modifiers, not brushes: Displace on a Multires or subdivided mesh, largest scale first (`organic-and-cloth.md`) | `bpy.ops.sculpt.brush_stroke` refuses to run headless ("context is incorrect"): brush sculpting needs the user at Blender, *measured* |
| Cloth | A cloth simulation stepped frame by frame and applied (`organic-and-cloth.md`) | Runs headless, *measured* |

### What makes a high poly bake well

Blender bakes the high poly's **shading** normals (smooth-shaded normals interpolated across each face), so its
shading is what lands in the normal map. *Measured* against a reference bake of a 0.1 m cylinder (a 24-sided low,
512 px, about 810 texels per metre):

| The high poly | Texels off the clean bake by more than 1 deg | p90 error |
| --- | --- | --- |
| Smooth-shaded cylinder, 16 to 128 sides, fold edges sharp | none (0.08 deg RMS at every count) | - |
| Flat-shaded, 64 sides / 128 sides | facet stripes: 0.93 / 0.23 deg RMS | - |
| Smooth-shaded everywhere, caps included (smoothing across a fold) | 98% | 41 deg |
| A boolean hole, shaded smooth everywhere | 74% | 1.75 deg |
| The same boolean with sharp edges by angle (30 deg) | 1.7% | 0.15 deg |
| The same, voxel remeshed (1-4 mm) | ripple p50 0.4-1.0 deg, p95 1.1-1.7 deg | - |

So:

1. **Shade smooth, with every fold sharp.** Never smooth across a fold (a cap, a panel edge, a boolean rim): the
   whole face bakes tilted. Never flat-shade a curved part: its facets bake as stripes. For the normal map, density
   beyond what the silhouette needs adds nothing to a cleanly shaded surface (16 and 128 sides baked the same); a
   high that also feeds `pbr-texturing`'s Pointiness curvature bake is cut to a grid of about 2 bake texels before
   its bevels and booleans (sparse, its flat panels read 0.63 instead of 0.5: measured on a crate).
2. **Voxel remesh leaves stair-step ripple** in the bake. A Smooth modifier (factor 0.5, 10 iterations) roughly halved
   it at 4 mm voxels (p50 0.38 to 0.20 deg); Corrective Smooth and Laplacian Smooth at their defaults changed nothing
   measurable. Remesh only what booleans and bevels cannot do, at a voxel size of about a third of the smallest
   rounded edge (*practice*), smooth it, and look at it under a reflective matcap.
3. **Rounded edges at least 3 texels wide** at the bake's density (*practice*, the width under which `pbr-texturing`'s
   baker needs its wider filter): 3 mm at 1024 px/m, 6 mm at 512 px/m. A narrower edge stays sharp in the high (its
   highlight goes in the texture) or becomes a trim-sheet bevel strip. Never under 2 px at the usual viewing distance
   either (`detail_scale.py`).
4. **The high covers every face of the low.** A ray that finds no high leaves the map flat there: a missing back or
   underside bakes as a flat patch with a seam round it.
5. **Real sizes.** Bolts, rivets, grooves and beads at their real sizes (`real-world-sizes.md`); a groove narrower
   than 3 texels does not survive the bake, and one with square walls and sharp rims bakes flat whatever its width
   (a 3 mm groove read exactly 0, 0, 1 across: every ray lands on a face parallel to the low). Give grooves and panel
   lines meant for the normal map walls under about 45 deg (a V or a round section) or rims rounded 3 texels wide.

Check it before baking: a close-up of the high alone under a reflective matcap (`review_render.render`, matcap): no
ripples, pinches round poles, streaks along long triangles or facets on curves.

## 3. Build the low poly

1. **Silhouette.** The low's outline is what the player sees round the object, so its curves follow the chord rule
   at the nearest viewing distance (sag at most 2 px: `min_width_m(d)` from `detail_scale.py`, `arc_segments` in
   `grid_topology.py`). `high_low_gap(low, highs)` in `topology_audit.py` measures both ways: `low_outside_max`, the
   low standing outside the high anywhere (a bulge the texture cannot explain), at most `min_width_m(d)`, worst point
   and not a percentile (*measured*: a 4 cm bump on 0.6% of a crate's low read p99 0); `high_outside_p99`, the relief
   the bake must carry, at most `stereo_relief_m(d)` or that relief belongs in the low (section 1). The highs count
   as one surface sampled by area, so a split high or a scatter of rivets does not change the answer.
   *Measured*: a 16-sided low against a 128-sided high of 0.1 m radius gives high_outside 1.92 mm (its sagitta,
   r (1 - cos(pi / 16)), exactly), within 2 px from about 1.1 m (*derived*); a low 2 mm fatter than its high gives
   low_outside 2.0 mm.
2. **Skew.** The cage casts its rays along the low's vertex normals averaged across each face, so on a face whose
   corners lean, projected detail lands shifted by about relief x tan(angle) (15 deg moves 10 mm of relief 2.7 mm).
   `bake_skew(low, highs=highs, faces=seen)` gives the share of the seen faces' area where a ray leans more than 15
   deg from the high's surface where it lands (without `highs`, from the low's own face, which fails a correct
   cylinder: an 8-sided handle read 40% against its faces, 0 against its round high). *Measured* against the low's
   faces: a hard 1 m box 93% (up to 54.7 deg at its corners); the same box with a 5 cm, three-segment bevel 3.7%.
   Where baked detail sits on a leaning face, add the chamfer or support loop to the low; keep the share small where
   it carries detail (*practice*: under 10%). No shells passing into each other inside one low (a hinge leaf through
   its knuckle): their cage rays start inside each other's high.
3. **Hard edges and seams.** A hard edge only where the low folds (about 90 deg or more on hard surface), every one of
   them a UV seam (`uv-unwrapping`); an organic low is shaded smooth whole.
4. **Triangulated as it exports**: a Triangulate modifier (Minimum Vertices 4, Keep Normals) live during the bake, so
   the baker and the engine split every quad the same way.
5. **Spend triangles** on the silhouette and curves first, then on the folds that skew baked detail, never on flat
   faces seen face-on. The world's budget (`vrchat-world-optimization`, the spec's per-piece budget) decides the
   total; a hero prop seen within 1 m usually lands at a few thousand triangles (*practice*).

## 4. Pair the parts

- One low object per texture set, a vertex group per part (`Body`, `Lid`, `Bracket_L`), and every high object named
  `<Part>_high` (`Lid_high`, `Body_high_rivets`): floaters belong to the part they lie on.
- Parts that sit close together (a lid on its box, a drawer in its carcass, a bracket on a plank) bake **exploded**:
  each part and its highs moved apart for every map, AO included (assembled, its rays land in the neighbour's high
  too). `pbr-texturing`'s `bake_exploded(low, parts_by_name(low, highs))` does this and puts everything back; a high
  may be parented to its own part's high, never another part's. *Measured*: a
  body and a lid 3 mm apart, highs 1 mm proud and a 16.5 mm cage (a bump elsewhere): assembled, 212 of 1,512 cage rays
  started inside the other part's high (normals pointing into the lid); exploded, none.
- Stacked or mirrored parts follow `uv-unwrapping`'s bake layout (one copy in 0-1); copies seen together close up get
  their own UVs so their wear differs.
- **One scene for the gate and the bake.** Where the highs live in their own file (a kit keeps them out of its kit
  and master files), open that file and append the current low into it, removing an older appended copy first so
  the name stays (*measured*, 5.2.2: name, vertex groups, modifiers and UV maps come across):

  ```python
  old = bpy.data.objects.get(low_name)
  if old is not None:
      bpy.data.objects.remove(old, do_unlink=True)
  with bpy.data.libraries.load(kit_path, link=False) as (src, dst):   # append, never link: the bake edits the low
      dst.objects = [low_name]
  bpy.context.scene.collection.objects.link(dst.objects[0])
  ```

  Gate and bake there, save that file, and never carry the highs or the appended low back into the kit file. Append
  again whenever the low changes: the bake must see the mesh that ships.

## 5. Gate before the bake

| Check | Pass |
| --- | --- |
| `topology_audit.audit_stack(low)` (the low keeps its Triangulate live for the bake; plain `audit()` counts the triangulated chamfer strips as slivers) | clean (no n-gons on the low, no open edges where faces are seen) |
| A reflective matcap close-up of the high | no ripples, pinches, streaks or facets |
| `review_render.compare("Body_high", "Chest_low", views, out)` (object names, one high at a time: the part's main high) | silhouettes match from every view the player has (`mismatch` per view) |
| `high_low_gap(low, highs)` at the nearest distance d (raise `samples` until fine panel lines are hit: 60,000 found a 3 mm groove on a 2 m box that 8,000 missed) | `low_outside_max` (bulges of the low) at most `min_width_m(d)`; `high_outside_p99` and `recess_max` (grooves and dents of the high the low spans) at most `stereo_relief_m(d)` |
| `bake_skew(low, highs=highs, faces=seen)` | under 10% of the seen area over 15 deg where detail is baked (*practice*) |
| After the bake | the bake report (`<name>_bake.json`) has `cage_inside` own and neighbour 0 in every pass; `pbr-texturing`'s seam check on the normal map shows no seam |

**Where the normal map does not draw.** VRChat's Standard Lite (Quest, iOS) does not sample the normal map on a
lightmapped surface with Non-Directional lightmaps, glossy reflections off and no realtime light (`pbr-texturing`'s
engine notes): there a baked high reads flat. The lighting skill decides the lightmap mode; where those conditions
hold, the bake's cavity also goes into the base colour (the AO and curvature masks darkening crevices a few percent),
so the form still reads on mobile.
