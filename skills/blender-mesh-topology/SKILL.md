---
name: blender-mesh-topology
description: Retopology and clean low-count topology in Blender - messy, fanned or pinched topology, n-gons, poles, faceted shading, too many triangles, an over-dense low, edge flow; a greybox piece that looks plain, boxy or too clean, what detail to model, at what size. Reduction grids, loop removal, Quad Remesher, hard-surface chamfers, weighted normals, audit, review renders. Blocky props (3d-form-design); textures (pbr-texturing).
---

# Clean topology for generated and hard-surface meshes

Clean topology is designed, not found. Decide the shape first, then the layout, then prove both with numbers and
close-up renders. Finishing a greybox piece, what to model and at what size, is section 5. Engine-neutral; what an
engine does with the result is in `references/engine-notes.md`.

## Pick the path

| The mesh | Path | Read |
|---|---|---|
| Generated, swept, revolved or built from sections (stairs, decks, bands, rings, generated walls) | Design the grid by hand (sections 2-3) | `references/grid-layout.md`, `scripts/grid_topology.py` |
| An existing low that is too dense but already structured (face grids, bands, swept shells, lathe props) | Remove its own edge loops by measured sag, never a remesh (it loses the layout and the UV seams) | `references/loop-reduction.md`, `scripts/loop_decimate.py` |
| A free-form patch with few or free borders | Quad Remesher from Python (section 4) | `references/quad-remesher.md`, `scripts/quad_remesh.py` |
| A prop or piece that looks blocky or over-bevelled, or furniture: its form, proportions and bevel sizes | Load the `3d-form-design` skill, then come back for the stack and validation | - |
| A greybox piece to finish, or one that looks plain, boxy or too clean | Detail at real sizes, geometry or normal map by viewing distance, joints (section 5) | `references/form-and-detail.md`, `references/real-world-sizes.md`, `scripts/detail_scale.py` |
| A hand-modelled static hard-surface piece (kit walls, door surrounds, trims, furniture) | Chamfers, custom normals, flat-face rules (section 6) | `references/hard-surface.md` |
| Any of them, before calling it done | Validate (section 7) | `references/validation.md`, `scripts/topology_audit.py`, `scripts/review_render.py` |

A remesher never fixes a shape, and on engineered surfaces fixed on every side it leaves knots at the borders: when
the piece has sections, design the grid.

## 1. Find the real problem first

- Look at the mesh **the way the user does**: a whole-piece view from the normal viewpoint, then a close-up wireframe.
  A fix that changes centimetres is invisible from ten metres; a knot of tiny faces is obvious in wire.
- Separate **shape** problems (a dent, a scoop, a crease that fades wrongly: fix the surface) from **layout**
  problems (fans, poles, slivers, twisted quads: fix the topology) and **normals** problems (fix custom normals or
  sharp edges). Changing normals or remeshing will not fix a shape.
- Any change to a specified shape is the user's decision: show before/after and state how far it moves (cm).

## 2. Shape as a function (generated pieces)

Define the surface independently of the mesh, so any layout can sample it:
- Swept pieces: a section profile per station, blended between sections where needed.
- Blends between fixed sections that "don't curve naturally": a **thin-plate (biharmonic) fill** over the plan, with
  the neighbouring sections held two stations deep so slopes carry across (`thin_plate_heights`). It spreads a drop
  over all the room it has instead of row-by-row pits.
- Keep features (grooves, seams) as offsets on the base surface so they survive re-sampling.

## 3. Grid layout (generated pieces)

1. **Columns**: split the piece into zones at every feature boundary (joints, edges, cut-outs, where the section
   changes regime) and space columns evenly inside each zone (`zone_stations`). Put a column on any mirror line.
2. **Rows**: the section's own points, so joints with neighbouring pieces match row for row.
3. **Reductions**: thin out towards short edges with a **regular loop-reduction band**, never with fans: 3 to 1 by
   default, 4 to 2 or 5 to 3 for gentler steps (`step_reduce`, all quads). An all-quad band needs the fine and coarse
   counts to differ by an even number; 2 to 1, 3 to 2 and 4 to 1 need a hidden triangle. Size bands from the stations
   each group of rows needs, and only where many rows run parallel: across a single row a band adds faces.
4. **Cut-outs**: bend the columns round them, spreading them where a curve leaves a straight wall tangentially.
5. **Flat parts**: long quads on the same columns, or a `ladder` between mirrored or matching runs; `flat_fill` only
   for small regions.
6. **Mismatched edges** (a fixed polyline another piece owns): one zipper row (`zipper`, `zipper_by`), with matching
   stations added where you want quads.
7. **Chord rule** on every arc: sag = r(1 - cos(step/2)) within tolerance (`arc_segments`); the tolerance is a starting
   point, settled by comparing tests from the player's viewpoint.

Details, worked examples and the reduction table: `references/grid-layout.md`.

## 4. Remesh (free-form patches)

Freeze the borders and give them even spacing near the target edge length, remesh one half and mirror it
(`mirror_half`), and accept only output whose border is exactly the frozen loop with no edge on three faces:
`patch_input(obj)` turns a patch object into the points, triangles and border loop, and `remesh_patch()` remeshes,
validates and retries other targets. Engine, settings, a worked call and the failure table:
`references/quad-remesher.md`.

## 5. Finish the form (a greybox piece)

- Start from intent: reference images, the brief's description and detail list, the nearest and the usual viewing
  distance, the triangle budget. The greybox's footprint, pivot and openings stay exactly as they are.
- The greybox is the primary form. Add the secondary forms (frames, panels, mouldings, reveals, sills, rails) at real
  sizes (`references/real-world-sizes.md`); tertiary surface detail belongs in textures (`pbr-texturing`).
- Geometry or normal map, per feature, from the distance d: relief deeper than about 0.014 x d^2 m (one pixel of
  stereo disparity at 20 ppd), anything on the silhouette and anything seen at grazing angles is geometry; shallower
  relief seen face-on is a baked normal or a trim bevel. Nothing narrower than 2 px (d / 575 m) at the usual distance:
  it shimmers. `python scripts/detail_scale.py <d>...` prints both with the texel class (`--ppd 25` for Quest 3).
- Chamfer the edges players see up close (section 6), never a face that meets a neighbouring kit piece: two chamfers
  make a groove at every joint. A profile that runs across pieces is identical at both ends.
- Imperfection (sag, chipped corners, uneven boards) goes on the body only, never on joint faces; variants differ in it.
- Mid-poly with custom normals for hard-surface kit pieces; a high-poly bake for ornament and organic or cloth props
  (the bake is `pbr-texturing`'s).
- Review from eye height (1.6-1.7 m) at the nearest walkable and the usual distance, beside the reference, and report
  every detail item with its measured size.

Rules, worked numbers and routes: `references/form-and-detail.md`.

## 6. Hard-surface pieces (hand-modelled)

- Chamfer the edges the player sees up close (one or two segments); only facets of a curved surface are smoothed by
  angle. A fold between two big flat faces is never smoothed, at any angle.
- Keep big faces flat with custom normals, not support loops (they only pay off on meshes that are subdivided). Shade
  the mesh smooth first (`ob.data.shade_smooth()`, not Shade Auto Smooth), after applying scale (Bevel amounts are in
  object space). Mirror and Array go first in the stack, above the Bevel (`modifiers.new` appends at the bottom: move
  them up), never below the Triangulate or the Weighted Normal. Two Blender 5.2 stacks:
  - Route A, the one for pieces with folds: folds and hard edges marked sharp -> Bevel with Harden Normals ->
    Triangulate (Minimum Vertices 4, Keep Normals).
  - Route B: Bevel with Face Strength Affected and its angle limit under the shallowest fold (folds get chamfered:
    marking them sharp does not work on this route) -> Triangulate (Minimum Vertices 4, Keep Normals) directly above
    -> Weighted Normal last, never a Triangulate below it.

  Without the Triangulate, an exporter's own triangulation changes the custom normals (measured: 10 deg).
- A Smooth by Angle goes only first in the stack (below any Mirror or Array), through
  `hard_surface.smooth_by_angle_first()` (the operator acts on the selection), never Shade Auto Smooth on top. Any
  angle (Smooth by Angle or the Bevel limit) must sit above every curved part's facet angle and below the shallowest
  fold; if none does both, use route A with the folds marked.
- UV work applies the stack from the top down to and including the last topology-changing modifier (a Smooth by Angle
  first included), except a Mirror with nothing topology-changing below it, which stays live until just before the
  layout: `hard_surface.apply_for_uv_work()` and `apply_before_layout()`, identical to uv-unwrapping's `apply_stack`.
  It never applies the stack's Triangulate before the layout (it stays, switched off until after it), and never
  shades by angle again afterwards: the normals are mesh data then. With RizomUV, pass `modifiers='ignore'` after it.
- Triangles are fine on flat faces; n-gons are fine while modelling flats; poles go on flats.
- Check with `audit_stack(obj, flat_tol=0.5)` at any stage (Triangulate live, off or applied): big faces flat, Keep
  Normals on, slivers judged before the Triangulate, no Smooth by Angle out of place. Around UV work, take
  `normals_snapshot(obj)` first and pass it as `before=`.

Details, measurements and sources: `references/hard-surface.md`.

## 7. Validate before calling it done

- `topology_audit.audit(obj)` on the modifier stack's result: n-gons, open, overfull or flipped edges, inverted
  islands, short edges, degenerate faces, bad quads, slivers, loose vertices; poles, fan centres and how far big faces
  are off flat reported (faces wider than 2.1 x the largest live Bevel amount, 5 cm without one).
  `problems(r, flat_tol=0.5)` fails the last for flat-faced pieces; smooth curved parts are over it by design, so on
  a piece with them read `r["flat_faces"]` (each face over the tolerance once, as the mesh data's face index and a
  centre) and judge only the flat parts. A hard-surface piece:
  `audit_stack(obj, flat_tol=0.5)` instead. `joint_match` for vertices shared with a neighbouring piece.
- `review_render.render(...)`: close-up wire, studio, and a reflective matcap. Before and after:
  `review_render.compare(dense, low, views, out)` renders each alone from the same eye relative to its own centre,
  into a before | after | silhouette sheet, and returns the silhouette mismatch per view. Never put both in one wide
  frame: perspective shears the offset one, and a correct low looks distorted.
- Generated pieces: build twice and compare `determinism_hash` (vertices and faces).
- Report counts before and after, what was checked and what was not.

Audit keys, render limits and the approval grid for several pieces: `references/validation.md`.

## Scripts

| Script | What it gives |
| --- | --- |
| `scripts/grid_topology.py` | `zone_stations`, `arc_segments`, `blend_error`, `grid_faces`, `step_reduce` / `step_3to1` with `mid_along` / `mid_between`, `ladder`, `zipper`, `zipper_by`, `flat_fill`, `PointCache`, `thin_plate_heights`, `grid_triangles` |
| `scripts/loop_decimate.py` | `loop_decimate(ob, tol, protect_uv="all", max_loops=None)` removes edge loops by least sag while it stays within `tol`, keeping seams, sharp edges, material boundaries and UV maps; `deviation(dense, low, samples="verts")` measures max, p95 and mean |
| `scripts/quad_remesh.py` | `patch_input(obj)` (points, triangles and border loop of a patch), `remesh_patch()` (remesh, validate, retry), `quad_remesh()` one engine run, `weld_layout()`, `mirror_half()`, `find_engine()` |
| `scripts/hard_surface.py` | `smooth_by_angle_first(ob, angle_deg)`, `apply_for_uv_work(ob, add_triangulate=False)`, `apply_before_layout(ob)` |
| `scripts/topology_audit.py` | `audit(obj, evaluated=True)`, `problems(result, allow_open=False, flat_tol=None)`, `audit_stack(obj, flat_tol=0.5, before=None)` for hard-surface pieces, `normals_snapshot(obj)`, `stack_route(obj)`, `flat_floor(obj)`, `audit_many(objects)`, `joint_match(a, b, select, matrix_a=None, matrix_b=None)`, `determinism_hash(obj)` |
| `scripts/review_render.py` | `render(path, eye, target, ...)` live or headless, `isolate(show, hide)`, `contact_sheet(paths, out, cols)`, `compare(before, after, views, out, wire=(True, False), silhouette=True)` |
| `scripts/detail_scale.py` | Plain Python, no Blender: `px_per_m(d)`, `texel_class(d)`, `stereo_relief_m(d)`, `min_width_m(d, px=2)`, each with `ppd=20` (25 for Quest 3); `python detail_scale.py 0.5 1 2 [--ppd 25]` prints the table |

Load a Blender script into Blender with `exec(open(path, encoding="utf-8").read(), ns)` and call its functions
(`detail_scale.py` runs in any Python). None of them change the scene except where stated: the grid helpers build
what you pass them, renders add and remove a temporary camera, `audit_stack` and `normals_snapshot` switch
Triangulate modifiers for a reading and restore them, the `hard_surface` functions change the stack they are given
(and nothing else), `quad_remesh` removes everything it creates, and `loop_decimate` changes only the mesh it is
given.
