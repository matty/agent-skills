---
name: blender-mesh-topology
description: Design clean, low-count, flowing topology for generated or hard-surface Blender meshes - hand-designed column/row grids with regular 3-to-1 reductions, thin-plate (fair) surfaces for blends, flat-part fills, driving Quad Remesher's engine from Python with frozen borders, and validation (mesh audit, joint matching, close-up wire and matcap renders). Use when a mesh shades badly, pinches, has messy or fanned topology, needs a lower quad count without losing its look, or when a generator's layout must be repeatable; not for UVs, rigging or sculpting.
---

# Clean topology for generated meshes

Clean topology is designed, not found. A remesher can lay quads over a surface, but it cannot fix a bad shape, and
on engineered surfaces with fixed borders it leaves knots. Decide the shape first, then the layout, then prove both.

## 1. Find the real problem first

- Look at the mesh **the way the user does**: usually a whole-piece view from the normal viewpoint, then a close-up
  wireframe. A fix that changes centimetres is invisible from ten metres; a knot of tiny faces is obvious in wire.
- Separate **shape** problems (a dent, a scoop, a crease that fades wrongly: fix the surface) from **layout**
  problems (fans, poles, slivers, twisted quads: fix the topology) and **normals** problems (fix custom normals or
  sharp edges). Changing normals or easing curves will not fix a shape; remeshing will not fix a shape.
- Any change to a specified shape is the user's decision: show before/after and state how far it moves (cm).

## 2. Shape as a function

Define the surface independently of the mesh, so any layout can sample it:
- Swept pieces: a section profile per station (blended between sections where needed).
- Blends between fixed sections that "don't curve naturally": a **thin-plate (biharmonic) fill** over the plan, with
  the neighbouring sections held two stations deep so slopes carry across (`scripts/grid_topology.py`,
  `thin_plate_heights`). It spreads a drop over all the room it has instead of row-by-row pits.
- Keep features (grooves, seams) as offsets on the base surface so they survive re-sampling.

## 3. Layout — prefer a hand-designed grid

For anything swept, revolved or built from sections (stairs, decks, bands, rings, walls), design the grid:
1. **Columns**: split the piece into zones at every feature boundary (joints, edges, cut-outs, where the section
   changes regime) and space columns evenly inside each zone. Put a column on any mirror line.
2. **Rows**: use the section's own points, so joints with neighbouring pieces match row for row and rows follow the
   shape.
3. **Reductions**: thin out towards short edges with a **regular loop-reduction band**, never with fans: 3 to 1 by
   default, 4 to 2 / 5 to 3 for gentler steps (all quads), 2 to 1 / 4 to 1 only with a hidden triangle. Size the
   ratio from the stations each group of rows needs at its tolerance, and only where many rows run parallel — across
   a single row a band adds faces. See `references/grid-layout.md` (Choosing a loop reduction).
4. **Cut-outs**: bend the columns round them (spread the columns where a curve leaves a straight wall tangentially, or
   the corner quad becomes a dart).
5. **Flat parts**: lay them out too — long quads on the same columns, or a `ladder` straight across between mirrored
   or matching runs (a symmetric deck's two edges, two facing semicircles). Use `flat_fill` (constrained Delaunay, no
   interior points, paired into quads) only for **small** regions; over a large region with few outline points it
   makes a web of long triangles, and a fill with interior points makes fans. Decouple dense features (a semicircle)
   from the grid: give them their chord-rule count and join them to the grid in one small fill, rather than carrying
   their density through the whole piece.
6. **Mismatched edges** (a fixed polyline that another piece owns): a zipper strip, kept to one row; `zipper_by` a
   coordinate gives quads wherever both runs have a station at the same place, so add matching stations.
7. Respect the chord tolerance on every arc (sag = r(1 - cos(step/2))).

Use a **remesher** only for genuinely free-form patches; see `references/quad-remesher.md`. If a remesher is used, freeze
borders, give them even spacing near the target edge length, remesh one half and mirror it, and validate every
result.

## 4. Validate before calling it done

- `scripts/topology_audit.py`: closed islands, no n-gons, no degenerate/short edges, good quads, slivers, open or
  overfull edges, triangle share, poles and fan centres (poles from deliberate templates are fine; scattered ones
  are not), plus `joint_match` for vertices shared with a neighbouring piece.
- `scripts/review_render.py`: off-screen Workbench renders from fixed cameras — **close-up wire**, studio, and a
  reflective matcap (`check_reflection_horizontal.exr`) — before/after in contact sheets. Look at the wire close up.
- Check determinism (build twice, compare a vertex hash) for anything generated.
- Report counts before/after, what was checked, and what was not (for example, a full level build).
- For approval of several pieces at once, build every test hidden in a preview collection, then lay them out in a
  clear area as a labelled grid: one column per item, the current mesh behind and the test in front (new objects
  that link the existing mesh data, so nothing is copied). Swap only what is approved, backing up the old mesh, and
  check first that the generator's defaults rebuild exactly the approved test (compare vertex hashes).

## Scripts

| Script | What it gives |
| --- | --- |
| `scripts/grid_topology.py` | even/zone stations, chord-limited arc counts, `grid_faces`, `step_3to1`, `ladder`, `zipper`, `zipper_by`, `flat_fill`, `PointCache`, `thin_plate_heights` |
| `scripts/quad_remesh.py` | `quad_remesh()` driving the Quad Remesher engine, `weld_layout()` validation/weld, `mirror_half()` |
| `scripts/topology_audit.py` | `audit(obj)`, `joint_match(a, b, select)`, `determinism_hash(obj)` |
| `scripts/review_render.py` | `render(path, eye, target, ...)` off-screen, `contact_sheet(paths, out, cols)` |

Load a script into Blender with `exec(open(path, encoding="utf-8").read(), ns)` and call its functions; none of
them change the scene except where stated (renders add and remove a temporary camera).

## Lessons that cost time

- Quad Remesher's frozen borders plus a coarse target produce knots at corners; "fewest quads" pushed that way looks
  fine in a far render and is messy in wire. The hand-designed grid gave clean topology at about 1.6x the count.
- A crease that fades out needs its sharp flag to end where it is shallow (about 12 deg worked); 3 or 30 deg both
  showed a notch. Snap any remesher edge loop that should sit on the crease back onto it.
- A greedy "best angle at each step" zipper wandered into long fans; arc-length or coordinate matching, or a small
  Delaunay fill, behaved.
- `delaunay_2d_cdt` works in single precision: collinear outline points give triangles of about 1e-8, not 0 — drop
  triangles under about 1e-6 (twice the area) or they turn up as slivers and overfull edges.
- Vertices cached by rounded coordinates still duplicated where two computations landed either side of a rounding
  step (open edges): weld the cached verts by distance (`PointCache.weld`) before adding other islands.
- Worked example (landing + bridge, 29 Sep 2026): 7,242 -> 4,616 triangles, no fans or knots; most of what remains on
  the bridge is its guard-edge sweep, already regular and bound by the chord rule — say so rather than chase it.
- A chord tolerance is a starting point, not the look: on a tight curve, build tests at several tolerances and
  compare them from the player's viewpoint with smooth shading (a gallery rim went 91 -> 38 stations at 8 mm with no
  visible change; 12 mm showed flats on the silhouette). Record the chosen value as the user's decision.
- A flat strip meeting a curve: space its outer points by distance along the curve, not radially, or the lines bunch
  into needles where the curve runs nearly radially.
- Render helpers: call `view_layer.update()` after hiding/showing objects, force `overlay.show_overlays` on for wire,
  and never re-exclude a collection the user excluded — use your own visible collection for previews.
