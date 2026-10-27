# form_audit: what it measures and where it is wrong

`scripts/form_audit.py` is a first filter, not a judge: it finds the measurable signatures of a blocky or
over-bevelled model so the renders can be spent on the rest. Every threshold is *practice* (this skill's rule, set
from the bevel and form rules in `bevels.md` and `form-principles.md`), tested on built meshes in the repo's tests,
not tuned on a body of real assets.

## Inputs

- Vertices in metres, Z up, faces as vertex index lists. In Blender, `audit_object(obj)` takes the modifier stack's
  result with the object's scale applied, in the object's own axes (rotation left out, so "facing an axis" means the
  piece's axes).
- **Quads**: bevel faces are recognised as quads. Triangulate modifiers are switched off for the reading; an applied
  or exported triangulation hides every bevel. Export OBJs with quads kept.

## Bevels

| Measure | How |
| --- | --- |
| Bevel face | A quad that turns 1-75 deg to the faces across a pair of opposite edges, and is dominated by one of them: the neighbour faces an axis and it does not, or both or neither do and the neighbour is at least twice as wide. Long narrow quads (aspect 2.5+) qualify the same way; an off-axis quad between two axis-facing faces qualifies whatever its aspect (a soap-bar cube's bevels are wider than they are long) |
| Section | Bevel faces chained across their long edges: one section per bevel cross-section, so a 3-segment round counts once. Further segments join within 1.5x of a neighbouring bevel face's width. Chains that close on themselves (a cylinder's facets) or branch are left out |
| width | The section's summed face widths (arc length for a round) |
| flat | How far the flat region beside the bevel reaches from it (coplanar faces within 1 deg joined), the smaller of the two sides |
| ratio | width / flat. A face bevelled on both sides keeps half its original width when ratio is 0.5 |
| kind | `bevel` (judged); `round`: the flanks turn 150 deg or more (an arch, a bullnose, a hinge knuckle: the part's profile); `marked`: a face of it carries the boolean face attribute `form_round` (`rounds=` face indices outside Blender), a round the design calls for, such as a corner bumper; `sliver`: a flank under 0.1 mm wide, a mesh defect with no flat to measure. Only `bevel` sections are judged and tiered |
| contact | A flank faces straight down and lies on the lowest point of the piece |
| tiers | Widths grouped within 1.3x of each tier's smallest |
| hard edges | Unbevelled edges between two flat regions at 45 deg or more |

## Parts and silhouettes

| Measure | How |
| --- | --- |
| parts | Vertex-connected loose parts, each with bounding box, size (largest side), area, `axis_share` (area facing an axis within 2 deg), `fill` (volume / box, closed parts only: 1.0 a box, about 0.785 a cylinder), `cube`, `grounded`, `floating` (off the ground and its box more than 2 mm from every other part's box) |
| size_tiers | Parts sorted by size; a new tier at each 2x step |
| box_share | Area on parts with fill >= 0.9 and axis_share >= 0.85 |
| silhouettes | Front, side, top and three-quarter projections at 96 px: rectangularity (filled / box) and solidity (filled / convex hull) |

## Problems

| Key | Fails when |
| --- | --- |
| `over_bevelled` | Any bevel's ratio over 0.5 (rounds, marked and sliver sections are never judged) |
| `warn_wide_bevels` | Ratio between 0.25 and 0.5 |
| `warn_sliver_flanks` | A section ends on a face under 0.1 mm wide (a Boolean or merge left slivers): fix the mesh with the topology audit, then audit again |
| `contact_bevelled` | A bevel on the bottom contact face |
| `one_bevel_width` | One tier, 8 or more sections, and parts 4x or more apart in size |
| `warn_every_edge_bevelled` | Bevels and no hard edge left |
| `blocky` | box_share 0.6 or more |
| `warn_cube_parts` | Box-filled parts with all sides within 15% |
| `floating_parts` | Any floating part |
| `warn_size_tiers` | 3 or more parts all within 2x of each other in size (furniture members of similar length are normal: only all-one-size is flagged) |
| `warn_box_silhouette` | Front and side silhouettes both 95% or more of their box |

`problems(r, expect_sharp=False)` drops the every-edge warning for a piece that really has no hard edge (a moulded
shell).

## Known blind spots

- Box parts are right for boards, panels and casework carcasses: `blocky` on a bookcase made of boards is expected;
  judge whether the boards have real thickness, overlaps, gaps and edges. Say so in the report.
- A part joined into one mesh with its neighbours is one part to the audit; floating detection only sees loose parts.
- The bounding-box gap is a cheap contact test: two boxes can overlap with the meshes still apart.
- A model rotated off its own axes, or with no axis-facing faces at all, falls back to the width rule for bevels.
- Triangles and n-gons are never bevel faces; corner patches of a bevel are ignored.
- A designed round that turns less than 150 deg (a quarter-round bumper, a moulded lip) reads as a bevel: mark its
  faces `form_round` (marking the whole part covers a Bevel modifier's faces too) and say why in the report, rather
  than shrinking a round the reference has.
- Silhouettes are orthographic and from the object's axes; the perspective renders are still needed.
