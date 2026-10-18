# Hand-modelled hard-surface pieces

Scope: static pieces for a real-time engine that are modelled by hand and never deform or get subdivided after export
(kit walls, door and window surrounds, trims, furniture). Swept or generated pieces: `grid-layout.md`. Free-form
patches: `quad-remesher.md`.

Sources, checked 2026-10-17: the Blender 5.2 manual (Bevel, Weighted Normal, Smooth by Angle and Triangulate
modifiers, URLs below) and Blender 2.80's release notes for Harden Normals
(https://developer.blender.org/docs/release_notes/2.80/modeling/). Numbers marked *measured* come from Blender 5.2.2
(2026-10-17) on these test pieces: a 1 x 0.08 x 2 m panel with a 10 mm, 2-segment bevel; a 1 x 0.1 x 2 m panel with a
13 deg ridge; a 1 x 0.06 x 2 m raised-and-fielded panel (13 deg folds at the field, 18 deg at the mitres); a 16-segment
column (radius 0.15 m); a door trim with a 20 deg fold and a quarter round of 15 deg facets; and a 70 x 20 mm
architrave whose faces are 5-30 mm wide, with folds of 10 and 12 deg. What a particular
engine does with the result is in `engine-notes.md`. Rows marked *practice* are this skill's working rules, not
sourced numbers: treat them as starting points and check the result (Check, below).

## Pick a route

- **Route A, Harden Normals** (Bevel with Harden Normals, then Triangulate with Keep Normals). The simpler route, and
  the one for pieces with folds between big flat faces: folds are simply marked sharp.
- **Route B, Weighted Normal** (Bevel with Face Strength Affected, then Triangulate with Keep Normals directly above
  the Weighted Normal, which comes last). Folds must be chamfered, or caught by a Smooth by Angle first in the stack:
  marking them sharp is not enough.
- A piece with folds and smooth curved parts (a quarter round, a column): route A with the folds marked by hand,
  unless one angle sits both above every curved part's facet angle and below the shallowest fold (next table).

## Decide per edge

| Edge | Do | Why |
| --- | --- | --- |
| Silhouette edges and edges the player sees up close (door and window surrounds, table tops, trims) | One chamfer: a bevel of 1-2 segments, 5-20 mm wide (*practice*) | A real edge catches a highlight; one segment adds a thin strip per edge, far fewer faces than support loops |
| A fold between two big flat faces (a raised panel, a sloped frame), at any angle | Route A: mark it sharp. Route B: chamfer it (the Bevel's angle limit under the shallowest fold). Either route: a Smooth by Angle first in the stack, its Angle under the shallowest fold. The angle must also sit above every curved part's facet angle; if no angle does both, use route A with the folds marked by hand | Smoothing bends both faces' normals: a 13 deg fold left smooth reads 6.50 deg off flat on route A, 8.67 on route B. On route B a marked fold that ends on chamfered edges has a single sharp edge at each end vertex, so the normal fan does not split: 8.67 deg off flat on the ridge, 14.56 on the fielded panel. Route A marked, route B chamfered, or Smooth by Angle at 10 deg first: 0.00. An angle under a curved part's facets reaches the curve too: on the trim's quarter round (15 deg facets), Smooth by Angle at 10 deg marked 5 of its 7 edges sharp, and a Bevel limit of 10 deg chamfered it into short edges and degenerate faces (*measured*) |
| Facets of a curved surface (a column, a rounded trim) meeting at under about 30 deg (*practice*) | Smooth | The 30 deg rule is for facets that approximate a curve, not for folds between flat faces |
| Hard 90 deg edges on big panels that stay unchamfered | Sharp | Keeps the panels flat; each sharp edge splits its vertices in the engine |
| Curved surfaces in general | Enough segments for the chord rule (`grid-layout.md`), shaded smooth | Facets show on the silhouette first |

## The stack, in order (Blender 5.2)

Helpers: `scripts/hard_surface.py` (`smooth_by_angle_first`, `apply_for_uv_work`, `apply_before_layout`).

0. **Before any modifier.** Apply scale (`bpy.ops.object.transform_apply(location=False, rotation=False,
   scale=True)`, or Ctrl+A > Scale): Bevel amounts are in object space, so a chamfer on an object at scale 2 comes out
   twice as wide as set. Then **Shade Smooth**, not Shade Auto Smooth: `ob.data.shade_smooth()` (the Object > Shade
   Smooth operator acts on every selected object; this keeps sharp edges). Blender's primitives come flat-shaded, and
   on flat-shaded faces route B's chamfers stay flat: their corner normals sat 0.0 deg off their own faces, against
   22.5-34.1 deg shaded smooth (*measured*; route A was unaffected).
1. **Mirror and Array first**, above the Bevel; never below the Triangulate or the Weighted Normal. `modifiers.new`
   appends at the bottom, so move each one up:

   ```python
   m = ob.modifiers.new("Mirror", "MIRROR")
   with bpy.context.temp_override(object=ob, active_object=ob):
       bpy.ops.object.modifier_move_to_index(modifier=m.name, index=0)
   ```

   Appended under a finished route B stack, a Mirror left the big faces 22.28 deg off flat, and the UV hand-off
   refuses such a stack (`audit_stack` names it `topology_below_triangulate`) (*measured*).
2. **Sharp edges.** Route A: mark folds and unchamfered hard edges sharp by hand (Edge > Mark Sharp). Route B: mark
   unchamfered hard edges, and leave folds to the Bevel (step 3). Or, on either route, a Smooth by Angle modifier with
   its Angle under the shallowest fold and above every curved part's facet angle, first in the stack after any
   Mirror or Array. Smooth by Angle "sets the sharpness of mesh edges based on the angle between the neighboring
   faces" (https://docs.blender.org/manual/en/latest/modeling/modifiers/normals/smooth_by_angle.html). Shade Auto
   Smooth adds it pinned last, after the Bevel and the Weighted Normal, where it re-sharpens the chamfers (split
   corners 56 -> 96; on a finished stack the normals moved 30.10-41.84 deg), and at its 30 deg default it misses every
   fold under 30 deg (fielded panel: route A 9.45, route B 15.13 deg off flat; at 10 deg, 0.00). Above a Mirror it
   misses a fold on the mirror plane (a half ridge: 6.50 deg off flat; below the Mirror, 0.00) (*measured*). The
   operator also acts on the selection: use `hard_surface.smooth_by_angle_first(ob, angle_deg)`, which touches only
   `ob`, puts the modifier below any leading Mirror or Array, gives the same stack when run again, and refuses outside
   Object Mode.
3. **Bevel** modifier: Limit Method Angle (on route B, with its Angle under the shallowest fold, so the folds are
   chamfered too, and above every curved part's facet angle), 1-2 segments, 5-20 mm (*practice*), then the route's
   normals setting:
   - A, **Harden Normals** on: "the per-vertex face normals of the bevel faces are adjusted to match the surrounding
     faces", keeping "the surrounding faces flat (if they were before), with the bevel faces shading smoothly into
     them" (2.80 release notes). It creates the custom normals attribute it needs
     (https://docs.blender.org/manual/en/latest/modeling/modifiers/generate/bevel.html).
   - B, **Face Strength** set to Affected, for the Weighted Normal below. Its default, None, gives Face Influence
     nothing to work with: the big faces end 4.51 deg off flat with the stack below, against 0.00 deg with Affected
     (*measured*).
4. **Triangulate** modifier, Minimum Vertices 4, so quads and n-gons arrive as triangles
   (https://docs.blender.org/manual/en/latest/modeling/modifiers/generate/triangulate.html), with Keep Normals on
   (`keep_custom_normals`) on both routes. The API reference
   (https://docs.blender.org/api/current/bpy.types.TriangulateModifier.html, checked 2026-10-17) describes it as "Try
   to preserve custom normals. Warning: Depending on chosen triangulation method, shading may not be fully preserved,
   'Fixed' method usually gives the best result here"; with the default Quad Method, Shortest Diagonal, the stacks
   below kept their normals exactly (0.00 deg). Route A needs it: without it the Triangulate itself moves the hardened
   chamfer normals, by up to 12.6 deg; on route B it changes nothing (0.00 deg) (*measured*). On route B it sits
   directly above the Weighted Normal, never below it: below, the Weighted Normal weights the untriangulated faces,
   and the normals differed from this stack by 7.86-11.69 deg with Keep Normals on and 12.55-19.35 with it off
   (*measured*, panel and ridge).
5. Route B only: **Weighted Normal** modifier, last: Weighting Mode Face Area, Keep Sharp on, Face Influence on
   (https://docs.blender.org/manual/en/latest/modeling/modifiers/normals/weighted_normal.html).

Why the Triangulate is in the stack: an exporter that triangulates (Blender's FBX exporter with Triangulate Faces, for
one) splits every face of 4+ corners its own way, and custom normals are stored relative to the faces around each
corner, so the new diagonals change them. *Measured*: route B without the Triangulate went from 0.00 to 10.42 deg off
flat through the FBX export, and route A's chamfer normals moved by up to 12.6 deg; both stacks as above exported
unchanged (0.00 deg). Triangulating only n-gons did not help (10.42 deg), and a Triangulate after the Weighted Normal
with Keep Normals off breaks the normals in Blender already (10.43 deg). An exporter can also pick the other diagonal
of a non-planar quad: triangulate those in the stack too.

Triangulated chamfer strips are slivers by the audit's 2 deg rule (a 10 mm x 1 m strip split into triangles has
corners well under 2 deg; 36 on the test panel). They are expected there, and `audit_stack` (Check) judges slivers on
the untriangulated mesh instead.

## Handing the piece to UV work

UV seams and layout need the chamfers as real faces, so UV work applies the stack: `uv-unwrapping`'s `apply_stack`,
or this skill's `hard_surface.apply_for_uv_work(ob)` before seams and `hard_surface.apply_before_layout(ob)` just
before the layout. The two behave identically (a repo test runs both on the same stacks). Rules for a piece with a
hard-surface stack (a Weighted Normal, a Bevel with Harden Normals, or custom normals already in the mesh data):

- Before seams, apply from the top down to and including the last topology-changing modifier above the Triangulate
  (a Smooth by Angle first in the stack, Mirror, Array, Bevel, Subdivision, Decimate, Weld, Solidify, Boolean and
  the like, and any Geometry Nodes modifier but Smooth by Angle), in stack order; never a lower one alone. Applying
  the Bevel alone left the Smooth by Angle above it to re-sharpen the chamfers: the normals moved 39.14 deg on route
  A and 34.33 on route B; applied from the top, 0.00 (*measured*).
- A Mirror with nothing topology-changing below it stays live through seams and unwrap, so its halves share UVs, and
  is applied just before the layout, when it is first in the stack. A Mirror with a topology-changing modifier below
  it (Mirror -> Bevel, as step 1 builds it) is applied in the top-down run, and its halves get unique UVs: applying
  the Bevel alone under it loses the chamfer faces on the mirror plane (a half ridge with its fold there: 148 -> 132
  faces, and the fold no longer chamfered, *measured*).
- The stack's own Triangulate (Keep Normals on) is never applied before the layout: it stays a modifier, switched off
  in the viewport until after the layout, then on again. A piece that needs one and has none gets one, Minimum
  Vertices 4 and Keep Normals on, directly above any Weighted Normal, never below it (step 4); `apply_for_uv_work(ob,
  add_triangulate=True)` does that. The Weighted Normal may stay live.
- Refused, with nothing applied (a ValueError naming the modifier): a topology change below the Triangulate (move it
  up, step 1), a modifier to apply that is switched off in the viewport (Blender 5.2.2's `modifier_apply` applies it
  anyway: a disabled Mirror doubled a half panel, *measured*), shape keys, and a mesh shared with other objects.
- Scale: applied before the stack was built (step 0). A piece that already has a live Bevel and a scale other than 1
  runs the hand-off first, then applies scale; applying scale first resizes the chamfers (`snapshot_geometry_changed`).
- RizomUV (`rizomuv-uv-pipeline`) after the hand-off: pass `modifiers='ignore'`, so it neither counts the switched-off
  Triangulate nor bakes the live Weighted Normal onto quads (that moved route B's normals 7.86 deg, *measured*).
- From then on the normals are mesh data (custom normals): never run Shade Auto Smooth, Smooth by Angle or
  `shade_smooth_by_angle` on the piece again (route A: the normals moved 30.06-33.84 deg, *measured*). Seams go by
  angle (`mesh.edges_select_sharp` at 30 deg, then Mark Seam), keeping the sharp edges the stack set.

Check it: `snap = topology_audit.normals_snapshot(ob)` while the stack is live, and after the layout (Triangulate on
again) `topology_audit.audit_stack(ob, flat_tol=0.5, before=snap)`: `normals_changed_since_snapshot` means the normals
moved; `snapshot_geometry_changed` that faces were lost, added or resized (the chamfers on a mirror plane, scale
applied under a live Bevel); `smooth_by_angle_without_bevel` that a Smooth by Angle was left above an applied Bevel.

## Custom normals, not support loops

- A chamfered low-poly mesh shaded smooth without custom normals bends its big flat faces towards the chamfer, and
  gradients run across the panels: that is what the stack above prevents.
- Support loops (tight extra loops beside an edge) exist to sharpen a subdivision surface. On a mesh that is not
  subdivided they only add thin faces (*practice*): use them only when you subdivide before export, then apply it.
- Custom normals only help if the engine imports them instead of recalculating normals (`engine-notes.md`).
- Hard edges cost vertices: the GPU needs one vertex per distinct normal, so every sharp edge splits the vertices along
  it. Smooth shading with weighted normals keeps one normal per vertex away from sharp edges. An engine vertex count
  well above Blender's means many hard edges or UV seams.
- Normal-map baking needs UV seams on hard edges; that rule, and the bake setup, are `uv-unwrapping`'s.
- LODs: each LOD gets its own Triangulate and Weighted Normal (or Harden Normals), since decimating breaks the normals
  of the mesh it was made from.

## Where triangles and n-gons are fine

- **Triangles on a flat face: fine.** A planar face with one normal shades the same however it is split, and the engine
  draws triangles anyway (`engine-notes.md`). Keep triangles out of curved, smooth-shaded areas, where the diagonal
  changes the interpolation, and avoid long thin slivers outside chamfer strips: they bake and lightmap badly.
- **N-gons: fine while modelling flat faces** (a wall face around a door cut). The Triangulate in the stack (Beauty
  method for n-gons) or a triangulation by hand chooses the diagonals before UV2 and export; non-planar or concave
  n-gons triangulate unpredictably otherwise. A finished lightmapped piece carries no n-gons (the audit and QA count
  them).
- **Poles:** invisible on flat faces, a pinch on curved smooth-shaded ones. Keep them on flats, like reduction bands.
- **T-junctions** (a vertex lying on another face's edge) crack in the engine: split the long edge so both faces share
  the vertex.

## Check

- `topology_audit.audit_stack(obj, flat_tol=0.5)` on every hard-surface piece, at any stage. `route` is "A", "B", or
  None when the piece has no hard-surface stack (no enabled Weighted Normal, no enabled Bevel with Harden Normals, no
  custom normals in the mesh data: the call is then a plain audit). A modifier switched off in the viewport does not
  count, since the export leaves it out too. `triangulate` says how slivers, bad quads, poles and fan centres were
  judged (with a Triangulate on, every chamfer strip is a sliver and every vertex a pole):
  - `live`: on a second pass with every Triangulate's viewport toggle (`show_viewport`) off, restored afterwards;
  - `applied` (no Triangulate modifier, only triangles): with triangle pairs joined back into quads (within 10 deg of
    one plane: on 1-3 segment bevels this gave the untriangulated counts exactly, *measured*);
  - `disabled` or `none`: as they are, and the piece then fails `custom_normals_on_quads` if it has custom normals.
  Everything else (n-gons, flipped, open and overfull edges, flatness) is the mesh as it exports.
- `flat_faces_off_deg` is the worst angle between a corner normal and its own face, over faces wider than 2.1 x the
  largest amount of the live Bevel modifiers (at least 5 mm; 5 cm when no Bevel is live, so after the hand-off pass
  `min_flat_width` yourself; `flat_min_width` reports the one used). A one-segment chamfer is at most 2 x its amount
  wide (1.41 x on a 90 deg edge) and its corners carry the neighbouring faces' normals, 45 deg off its own, so it is
  left out, while the narrow faces of a trim are judged: a 70 mm architrave with route B folds marked sharp reads
  7.80 deg (a fixed 5 cm floor saw none of its faces) (*measured*). Above 0.5 deg the big faces do not read flat (a
  route B fold marked sharp, Face Strength left at None). Smooth curved parts are over it by design: a 16-segment
  column reads 11.25 deg on route A and 15.04 on route B (*measured*). On a piece with curved parts read `flat_faces`
  (each face over the tolerance once, as the mesh data's face index and the centre of its worst evaluated face: the
  triangles of a quad and the halves of a Mirror fold into one entry) and judge only the flat parts.
- Its other problems: `custom_normals_on_quads` (the Triangulate is off, missing or above Minimum Vertices 4: the
  exporter's triangulation will change the normals); `triangulate_moves_normals` (Keep Normals is off on a
  Triangulate below the last enabled Weighted Normal, or on route A on any; a re-imported FBX does not show it: such
  pieces still matched after export within 0.09-0.49 deg while the Triangulate had moved their chamfer normals
  0.74-12.59 deg, *measured*); `triangulate_below_weighted_normal` (route B's Weighted Normal has no Triangulate above
  it but one below); `smooth_by_angle_late` (a Smooth by Angle below the Bevel, Triangulate or Weighted
  Normal: Shade Auto Smooth on top); `smooth_by_angle_without_bevel` (one left above an applied Bevel);
  `flat_shaded_faces` (route B without step 0); `topology_below_triangulate` (a Mirror, Array or other topology
  change below the Triangulate or Weighted Normal: step 1); `normals_changed_since_snapshot` and
  `snapshot_geometry_changed` (UV work, above).
- `scripts/review_render.py` close-up in a reflective matcap: big faces read flat, chamfers catch a smooth highlight,
  no gradients across panels.
- After export: no re-triangulation warning from the exporter (`blender-to-unity`'s batch export prints one for custom
  normals on faces of 4+ corners).
