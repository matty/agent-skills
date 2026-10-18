# Designing a grid layout

For anything swept, revolved or built from sections. Helpers: `scripts/grid_topology.py`.

Worked examples (Silo v2, 29 Sep 2026): a stair landing band went from 4,404 triangles of fanned, pinched columns to
1,110 quads / 2,418 triangles of regular grid, meeting the neighbouring flights row for row; the landing and bridge
together went from 7,242 to 4,616 triangles with no fans or knots. Most of what remained on the bridge was its
guard-edge sweep, already regular and bound by the chord rule: say so rather than chase it.

## Columns

- List the feature bearings/positions first: joints with other pieces, edges where a neighbour's outline changes,
  where the section changes regime, the ends of cut-outs, and the mirror line.
- Between consecutive features, `zone_stations(breaks, step)` spaces columns evenly (count = round(length/step), at
  least 1). Different zones may have different steps; keep neighbours within about 1.5x of each other.
- A zone can have a floor on its count from shape accuracy, not edge length: for a blended sweep, add columns until
  straight segments stay within tolerance of the blended section (`blend_error` measures it).
- If a reduction band will run across all columns, make the per-side count fit the band (a multiple of 3 for 3 to 1;
  `zone_stations(..., multiple=3)` adjusts the widest zone).

## Chord tolerance

- `arc_segments(radius, span_deg, tol)` keeps the sag r(1 - cos(step/2)) within tol. Starting points: 1.5 mm within
  reach, 4 mm overhead.
- A tolerance is a starting point, not the look: on a tight curve build tests at several tolerances and compare them
  from the player's viewpoint with smooth shading. A gallery rim went from 91 to 38 stations at 8 mm with no visible
  change, and 12 mm showed flats on the silhouette. Record the chosen value as the user's decision.

## Rows

- Use the section's own points. Neighbouring swept pieces then share every row at the joint, and rows follow the
  shape's curvature where it matters.
- Where one column type lacks a row (a cut-out), faces between two columns are made only where both carry both rows
  (`grid_faces`); the gap is closed by the cut-out's own walls.
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

All quads, regular, and the poles are deliberate: valence 3 at p and q, and valence 6 at a coarse vertex shared by
two groups when a row continues below it (4 at the band's ends); f1 and f2 keep valence 4. Place bands just inside a
natural line (a groove, a change of curvature) on a face that is flat across the band, and repeat them for further
reductions. `step_3to1` builds it; `step_reduce(..., n)` builds the whole family; pass a function for the mid points
(`mid_between` for step_3to1, `mid_along` for step_reduce) so they lie on the true surface.

Winding follows the runs, the same way as `grid_faces` when the top (fine) run is the earlier row. When the fine run
is the later row (going coarse to fine, as the second band on a ring does), pass both runs reversed; otherwise that
band faces inwards, which `topology_audit`'s `flipped_edges` reports (measured: 16 of 200 faces on a pipe elbow). A
run that closes on itself (round a pipe) is passed with its first vert repeated at the end, so a ring of g groups
still has (n + 2) * g + 1 top and n * g + 1 bottom entries.

## Choosing a loop reduction (after https://topologyguides.com/loop-reduction)

| Pattern | All quads? | Keeps | Use |
| --- | --- | --- | --- |
| **3 to 1** (`step_reduce` n=1) | yes: loops redirected back towards their origin | 1/3 of the segments | the default |
| **4 to 2, 5 to 3** (n=2, n=3) | yes: the 3 to 1 flow with more loops carried through the middle | 1/2, 3/5 | gentler steps |
| **2 to 1, 3 to 2, 4 to 1** | no: a triangle or an n-gon, or extra loops to the side | 1/2, 2/3, 1/4 | only where nothing else fits; put the triangle on a flat, unseen face |

- **Parity rule:** an all-quad band needs the fine and coarse segment counts to differ by an even number. Every quad
  patch has an even number of border edges (each quad has 4 edges, each interior edge is shared by 2 faces, so the
  border count is 4 x faces - 2 x interior edges). So 3 to 2 always needs a triangle, and a run of 84 fine segments
  cannot become 57 coarse ones in quads (difference 27): aim for 56 or 58.
- A reduction saves faces only across **many parallel rows**. Across one row (a flat deck strip, one quad per station
  to the wall) the band adds faces: on 29 Sep a 3 to 1 band on a bay deck went from 90 to 120 quads per face.
- Size it from the **stations each part actually needs**, not a blanket ratio: Douglas-Peucker the station set per
  group of rows at that group's tolerance (1.5 mm within reach, 4 mm overhead), then cover the fine:coarse ratio with
  the patterns above, mixing reduction groups with unreduced columns (84 to 58 segments is, for example, 13 groups of
  5 to 3 plus 19 segments carried straight through). Keeping every third station of a tight bend blindly broke the
  chord rule by 8-12 mm.
- Each group's end stations are fine stations (the band connects them), and so is the middle one in 4 to 2: choose
  the coarse set first from the fine set. 5 to 3 puts its two inner coarse stations between fine ones.
- Put the band on a face that is flat across the band (a vertical outer face) and away from crisp edges; the valence 3
  and 6 poles are then invisible in shading.

## Zipper strips

When one side's vertices are fixed by another piece (an inset line shared with a bridge edge) and the other side is
your grid, fill one row between them by arc-length fraction (`zipper`) or by a coordinate (`zipper_by`): quads where
both runs have a station at the same place, triangles elsewhere, so add matching stations. Keep it to one narrow row,
ideally on a flat or vertical strip. A greedy "best angle at each step" zipper was tried and wandered into long fans.

## Cut-outs in a flat shelf (the recess example)

- Columns that pass the cut-out bend round it: the cut-out's semicircle gets N segments (even, so a column sits on
  the axis), the rim gets the same N+1 columns between the walls.
- A semicircle leaves a straight wall tangentially; a column carried straight on along the wall meets it in a 0 deg
  cusp (a dart). Spread the cut-out's columns wider at their inner end (for example +-7 deg instead of +-5.5 deg) so
  every corner there is a proper angle.
- Intermediate rows of the bent columns: the fractions where the wall column crosses the straight columns' rows,
  applied to every bent column, so neighbours join quad for quad.
- A flat strip meeting a curve: space its outer points by distance along the curve, not radially, or the lines bunch
  into needles where the curve runs nearly radially.

## Flat parts

- Lay large flat parts out as long quads on the grid's columns, or `ladder` straight across between mirrored or
  matching runs (a symmetric deck's two edges, two facing semicircles).
- `flat_fill` (a constrained Delaunay of the outline, no interior points, paired into quads) only for **small**
  regions: over a large region with few outline points it makes a web of long triangles, and a fill with interior
  points makes fans. It returns the faces it leaves in the mesh.
- `delaunay_2d_cdt` works in single precision: collinear outline points give triangles of about 1e-8, not 0, so
  `flat_fill` drops triangles under 1e-6 (twice the area); without that they turn up as slivers and overfull edges.
- Decouple dense features (a semicircle) from the grid: give them their chord-rule count and join them to the grid in
  one small fill rather than carrying their density through the whole piece.

## Computed coordinates

Vertices cached by rounded coordinates (`PointCache`) still duplicated where two computations landed either side of a
rounding step, leaving open edges: call `PointCache.weld()` on the cached verts before adding other islands (the cache
then points at the surviving verts).

## Thin-plate fairing of a blend

Where a surface must go from one fixed section to another and the row-by-row blend leaves pits or steps:
- Build a grid over the plan (columns x rows, `grid_triangles`), assemble the cotangent Laplacian L and lumped areas M.
- Fix the known heights (both end sections two stations deep, rims, a guide row just outside a rim that follows the
  neighbouring round) and solve (L^T M^-1 L) z = 0 for the rest (`thin_plate_heights`). Held two deep, a plane or a
  quadratic is reproduced exactly; held one deep it is not (tested). It uses scipy's sparse solver when importable and
  a dense numpy solve otherwise (Blender bundles numpy, not scipy).
- Keep row positions from the blend; take heights from the field; add feature offsets (grooves) back.
- Measure how far the shape moved; it is a spec change.

## Normals

With a regular grid, default area/angle-weighted smooth normals plus sharp flags on real creases are usually enough.
A crease that fades out needs its sharp flag to end where it is shallow: mark it sharp only while its dihedral is
over about 12 deg (3 or 30 deg both showed a notch). Snap any remesher edge loop that should sit on the crease back
onto it.
