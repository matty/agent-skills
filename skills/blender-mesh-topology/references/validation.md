# Validating topology

Numbers first, then close-up renders, then (for generated pieces) determinism. Scripts: `scripts/topology_audit.py`,
`scripts/review_render.py`.

## The audit

`audit(obj)` measures the modifier stack's result (`evaluated=False` audits the mesh data alone, which is what a
generator writes). It cannot see an exporter's own triangulation: a hard-surface piece left as quads audits clean but
changes its normals on export. `problems(result)` lists the failing keys (`flat_tol=0.5` adds the big-faces-flat check
for pieces whose big faces must read flat); `audit_many(objects)` prints a table.

A hard-surface piece (`hard-surface.md`: a Weighted Normal, a Bevel with Harden Normals, or custom normals in the mesh
data) needs `audit_stack(obj, flat_tol=0.5)` instead, at any stage of its stack:

- With a live Triangulate it audits twice, with every Triangulate modifier's viewport toggle (`show_viewport`) on and
  off, restores the toggles, and judges slivers, bad quads, poles, fan centres and triangle share on the
  untriangulated pass (triangulated chamfer strips are slivers by design, and every vertex of a triangle mesh counts as
  a pole). With the Triangulate applied it judges them with triangle pairs joined back into quads. Everything else is
  the mesh as it exports.
- `custom_normals_on_quads`: custom normals on faces of 4+ corners as it exports (the Triangulate switched off,
  missing, or set above Minimum Vertices 4): the exporter's triangulation will change them.
- `triangulate_moves_normals`: the corner normals change when the Triangulates below the last enabled Weighted Normal
  (every one on route A) are toggled, so Keep Normals (`keep_custom_normals`) is off; comparing a re-imported FBX with
  Blender does not show it. `triangulate_below_weighted_normal`: route B's Weighted Normal has no Triangulate above it
  but one below (it goes directly above, never after it).
- `smooth_by_angle_late` / `smooth_by_angle_without_bevel`: a Smooth by Angle below the Bevel, Triangulate or Weighted
  Normal (Shade Auto Smooth on top), or above an already applied Bevel. `flat_shaded_faces`: route B on faces not
  shaded smooth. `topology_below_triangulate`: a Mirror, Array or other topology change below the Triangulate or the
  Weighted Normal (Mirror and Array go first, above the Bevel).
- `route` None means no hard-surface stack (modifiers switched off in the viewport do not count): the call is then a
  plain audit plus the Triangulate toggle.
- `normals_snapshot(obj)` before UV work applies the stack, then `audit_stack(obj, before=snapshot)`: fails with
  `normals_changed_since_snapshot` when the normals as exported moved, or `snapshot_geometry_changed` when faces were
  lost, added or resized so they could not be compared (chamfers lost on a mirror plane, scale applied under a live
  Bevel) (`hard-surface.md`, Handing the piece to UV work).
- Slivers the Triangulate itself cuts out of an n-gon are not counted (the untriangulated pass still has the n-gon):
  look for them in the close-up wire.

| Key | Fails when | Notes |
| --- | --- | --- |
| `ngons` | any | Fine while modelling flat faces; triangulate them on purpose before UVs (`hard-surface.md`) |
| `open_edges` | any, unless `problems(r, allow_open=True)` | Pieces meant to be open (a single wall face) pass with allow_open |
| `overfull_edges` | any | An edge with 3+ faces: a fold, or two layers fused |
| `flipped_edges` | any | An edge whose two faces both run along it the same way: a face wound against its neighbours (a reduction band built with its runs the wrong way round, `grid-layout.md`). Engines cull back faces, so it shows as a hole |
| `inverted_islands` | any | A closed island whose faces all point inwards |
| `short_edges`, `degenerate_faces` | any | Edges under 1 mm, faces under 1e-8 m2 |
| `bad_quads` | any | A corner under 3 deg, a quad folded over 25 deg (edges of 2 cm or more), or a bow-tie |
| `slivers` | any | A face with a corner under 2 deg, flat-shaded or not; on a stack-triangulated piece, judged by `audit_stack` on the untriangulated mesh |
| `loose_verts` | any | |
| `flat_faces_off_deg` | above `flat_tol`, when given | The worst angle between a corner normal and its own face, over faces wider than `flat_floor(obj)`: 2.1 x the largest live Bevel amount (at least 5 mm), or 5 cm without a live Bevel (`min_flat_width` overrides it; `flat_min_width` reports the one used). A one-segment chamfer is at most 2 x its amount wide and its corners are 45 deg off its own face by design, so it is left out, while a trim's narrow faces are judged (a 70 mm architrave with route B folds marked sharp: 7.80 deg, measured). About 0 on hard-surface pieces whose big faces read flat. Smooth curved parts are over it by design (a 16-segment column: 11.25 deg on route A, 15.04 on route B, measured), so on a piece with curved parts read `flat_faces`: each face over the tolerance once, as `{face, deg, centre}`, `face` being the index of the nearest face of the mesh data (the triangles of a quad and the halves of a Mirror fold into one entry) and `centre` the centre of its worst evaluated face in object space; judge only the faces on flat parts. `flat_worst_face` is the worst one's mesh-data index |
| `poles`, `fan_centres`, `tri_faces_pct`, `islands` | never (reported) | Poles are interior vertices with valence other than 4, triangles included; fan centres have 8+ edges or 2+ triangles meeting at them. A clean reduction band can have more poles than the fans it replaces (its poles are deliberate: two valence-3 and one valence-6 per 3 to 1 group), so judge a rebuild by fan centres and triangle share as well: a zipper-fanned pipe elbow read 6 poles, 14 fan centres and 8.3% triangles, its 3 to 1 rebuild 22 poles, 0 fan centres, 0% (measured). Look where poles are, and compare counts between layouts of the same surface, never with a mesh triangulated in its stack |

`joint_match(a, b, select, matrix_a=None, matrix_b=None)` compares the vertices two pieces have on a joint, in one
frame: kit pieces pivot at the origin, so pass `matrix_b=Matrix.Translation((2, 0, 0))` to set a 2 m wall's
neighbour beside it. Anything only on one side is a T-junction crack waiting to happen.

## Close-up renders

- `render(path, eye, target, ..., light, matcap, wire)` from fixed cameras: a **close-up wire**, a studio view, and a
  reflective matcap (`check_reflection_horizontal.exr`), before and after, tiled with `contact_sheet`. Look at the wire
  close up: a knot of tiny faces is obvious in wire and invisible from ten metres.
- Live, it draws the current 3D viewport off-screen, switched to Solid shading for the render, and restores the
  viewport's settings; headless (`blender -b`) it falls back to a Workbench scene render with wire drawn by temporary
  Wireframe-modifier copies.
- A matcap shows smoothly curved bands across flat faces in a perspective view: that is the matcap, not smooth
  shading. Bands that bend or break at a fold, or near a chamfer, are the shading: check `flat_faces_off_deg` there.
- Wire limits: objects inside collection instances get no wire in a headless render, so review a piece in its own
  file; the headless wire leaves subdivision out (it shows the cage).
- Helpers learned the hard way: call `view_layer.update()` after hiding or showing objects, force
  `overlay.show_overlays` on for wire, and never re-exclude a collection the user excluded: put previews in a visible
  collection of your own (`isolate()` restores hide flags it changed).

## Determinism (generated pieces)

Build twice and compare `determinism_hash(obj)`: it hashes the vertex positions and every face as its corner positions
in winding order, so a different diagonal, a flipped face or another reduction over the same stations changes it,
while vertex and face order do not.

## Approving several pieces at once

Build every test hidden in a preview collection, then lay them out in a clear area as a labelled grid: one column per
item, the current mesh behind and the test in front (new objects that link the existing mesh data, so nothing is
copied). Swap in only what is approved, backing up the old mesh, and check first that the generator's defaults
rebuild exactly the approved test (`determinism_hash`).

## Report

Counts before and after, what was checked, and what was not (for example, a full level build).
