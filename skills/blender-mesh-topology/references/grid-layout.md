# Designing a grid layout

Worked example: a stair landing band (Silo v2, 29 Sep 2026). 4,404 triangles of fanned, pinched columns became
1,110 quads / 2,418 triangles of regular grid, meeting the neighbouring flights row for row.

## Columns

- List the feature bearings/positions first: joints with other pieces, edges where a neighbour's outline changes,
  where the section changes regime, the ends of cut-outs, and the mirror line.
- Between consecutive features, `zone_stations(breaks, step)` spaces columns evenly (count = round(length/step), at
  least 1). Different zones may have different steps; keep neighbours within about 1.5x of each other.
- A zone can have a floor on its count from shape accuracy, not edge length: for a blended sweep, add columns until
  straight segments stay within tolerance of the blended section (measure the midpoint error).
- If a 3 to 1 band will run across all columns, make the per-side count a multiple of 3 (adjust the widest zone).
- Chord rule on arcs: `arc_segments(radius, span_deg, tol)`; within reach 1.5 mm, overhead 4 mm are sensible.

## Rows

- Use the section's own points. Neighbouring swept pieces then share every row at the joint, and rows follow the
  shape's curvature where it matters.
- Where one column type lacks a row (a cut-out), faces between two columns are made only where both carry both rows;
  the gap is closed by the cut-out's own walls.
- Thin features (a 10 mm groove) stay as rows of the same columns; do not let a reduction band cross them.

## Reductions: the 3 to 1 band

Top run f0..f(3n) (fine), bottom run c0..cn (coarse), one band of height h. Per group of three fine segments add two
points p, q at mid-band under f1 and f2 (on the surface), and make four quads:

```
 f0 ---- f1 ---- f2 ---- f3
  |       |       |       |
  |       p ----- q       |
  |     /           \     |
 c0 ---------------------- c1
 quads: [f0 f1 p c0] [f1 f2 q p] [f2 f3 c1 q] [p q c1 c0]
```

All quads, regular, and the poles (valence 3 at p, q; 5 at f1, f2) are deliberate and read cleanly. Place bands
just inside a natural line (a groove, a change of curvature) and repeat them for further reductions. `step_3to1`
builds it; pass a function for the mid points so they lie on the true surface.

## Choosing a loop reduction (after topologyguides.com/loop-reduction)

| Pattern | All quads? | Use |
| --- | --- | --- |
| **3 to 1** | yes: loops redirected back towards their origin | the default; near-perfect flow |
| **4 to 2, 5 to 3** | yes: the 3 to 1 flow with more loops carried through the middle | smaller steps (keep 2/3 or 3/5 of the stations) |
| **2 to 1, 4 to 1** | no: a triangle or n-gon, or extra loops to the side | only where nothing else fits; put the triangle on a flat, unseen face |

- A reduction saves faces only across **many parallel rows**. Across one row (a flat deck strip, one quad per station to
  the wall) the band adds faces: 29 Sep, a 3 to 1 band on a bay deck went from 90 to 120 quads per face.
- Size it from the **stations each part actually needs**, not a blanket ratio: Douglas-Peucker the station set per
  group of rows at that group's tolerance (1.5 mm within reach, 4 mm overhead), then pick the pattern whose ratio
  covers fine:coarse (84:57 is about 3:2, so 3 to 2 steps, or 3 to 1 only where the path is straight). Keeping every
  third station of a tight bend blindly broke the chord rule by 8-12 mm.
- The coarse stations must be a subset of the fine ones (the band connects them); choose the coarse set first from the
  fine set.
- Put the band on a face that is flat across the band (a vertical outer face) and away from crisp edges; the poles
  (valence 3 and 5) are then invisible in shading.

## Zipper strips

When one side's vertices are fixed by another piece (an inset line shared with a bridge edge) and the other side is
your grid, fill one row between them by arc-length fraction (`zipper`): quads where the fractions agree, triangles
elsewhere. Keep it to one narrow row, ideally on a flat or vertical strip.

## Cut-outs in a flat shelf (the recess example)

- Columns that pass the cut-out bend round it: the cut-out's semicircle gets N segments (even, so a column sits on
  the axis), the rim gets the same N+1 columns between the walls.
- A semicircle leaves a straight wall tangentially; a column carried straight on along the wall meets it in a 0 deg
  cusp (a dart). Spread the cut-out's columns wider at their inner end (for example +-7 deg instead of +-5.5 deg) so
  every corner there is a proper angle.
- Intermediate rows of the bent columns: the fractions where the wall column crosses the straight columns' rows,
  applied to every bent column, so neighbours join quad for quad.

## Thin-plate fairing of a blend

Where a surface must go from one fixed section to another and the row-by-row blend leaves pits or steps:
- Build a grid over the plan (columns x rows), triangulate, assemble the cotangent Laplacian L and lumped areas M.
- Fix the known heights (both end sections two stations deep, rims, a guide row just outside a rim that follows the
  neighbouring round) and solve (L^T M^-1 L) z = 0 for the rest (`thin_plate_heights`, scipy sparse).
- Keep row positions from the blend; take heights from the field; add feature offsets (grooves) back.
- Measure how far the shape moved; it is a spec change.

## Normals

With a regular grid, default area/angle-weighted smooth normals plus sharp flags on real creases are usually enough.
Mark a fading crease sharp only while its dihedral is over about 12 deg.
