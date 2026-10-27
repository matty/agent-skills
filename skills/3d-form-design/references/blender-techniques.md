# Profile-first modelling in Blender from Python

Scope: the bpy and bmesh calls behind SKILL.md section 4 (profiles, revolve, sweep, taper, crown, bevel by
weight). API facts from the Blender 5.2 API docs (https://docs.blender.org/api/current/) and release notes, checked
2026-10-19. The snippets have not been run in this repo's tests: run them on a scratch object first and read back the
result (vertex count, bounding box, a render).

## Which technique for which part

| Part | Technique |
| --- | --- |
| Turned or round: legs, lamp bases, bottles, knobs, vases, wheels | Revolve a profile: Screw modifier or `bmesh.ops.spin` |
| Rails, handles, cables, piping, tubes, mouldings along an edge | Sweep: a path curve with a profile (`bevel_object` or `bevel_mode='PROFILE'`), radius and taper along it |
| Boards, panels, tops, slabs | An extruded section at real thickness, its edge profile from bevel tiers |
| Shells, cushions, car panels, moulded plastics | A low cage with Subdivision Surface and edge creases (the `crease_edge` FLOAT EDGE attribute, 4.0+), or cloth for upholstery |
| `cloth` and `sculpt` builds | Headless, with modifiers: Blender's cloth simulation stepped frame by frame and applied (collision distances set to a few millimetres, or the cloth floats), pressure for cushions; a sculpt as a Displace stack on a remeshed base, since brush strokes do not run headless. Recipes, measured: `blender-mesh-topology`'s organic-and-cloth reference |
| Branching tubes, creature or root bases | Skin modifier on an edge skeleton, then Subdivision Surface |
| Whole-part taper, bend, belly or swell | Simple Deform (TAPER, BEND) or a 3x3x3 Lattice; needs enough segments along the axis |
| Cut-outs, recesses, slots | Boolean (`EXACT`, or `MANIFOLD` from 4.5 on manifold operands), bevel by weight after |

## Revolve a profile

```python
import bmesh, bpy, math
# profile in the XZ plane, from the axis outwards: (radius, height) in metres
prof = [(0.0, 0.0), (0.12, 0.0), (0.12, 0.012), (0.03, 0.03), (0.022, 0.25), (0.028, 0.5), (0.0, 0.5)]
bm = bmesh.new()
vs = [bm.verts.new((r, 0.0, z)) for r, z in prof]
edges = [bm.edges.new((vs[i], vs[i + 1])) for i in range(len(vs) - 1)]
bmesh.ops.spin(bm, geom=vs + edges, cent=(0, 0, 0), axis=(0, 0, 1), dvec=(0, 0, 0),
               angle=2 * math.pi, steps=16, use_merge=True, use_duplicate=False)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)   # the axis points
me = bpy.data.meshes.new("LampBase"); bm.to_mesh(me); bm.free()
```

`bmesh.ops.spin(bm, geom, cent, axis, dvec, angle, space, steps, use_merge, use_normal_flip, use_duplicate)`. The
Screw modifier does the same live: `angle`, `axis`, `steps` (default 16), `use_merge_vertices` (only with
`screw_offset` 0), `use_normal_calculate` for meshes (https://docs.blender.org/api/current/bpy.types.ScrewModifier.html).
Check the normals face out afterwards.

## Sweep a section along a path

Curve data (https://docs.blender.org/api/current/bpy.types.Curve.html):
- `bevel_mode`: `ROUND` (with `bevel_depth`, the radius, and `bevel_resolution`), `OBJECT` (`bevel_object` = a curve
  object as the section), `PROFILE` (`bevel_profile`, a CurveProfile).
- `taper_object`: a curve that scales the section along the path; `taper_radius_mode` `OVERRIDE`, `MULTIPLY`, `ADD`.
- Per point: `radius` and `tilt` for local variation. `use_fill_caps` closes the ends; `resolution_u` (default 12)
  sets the samples along the path; `twist_mode` `MINIMUM` keeps sections from flipping.
- Convert to a mesh for export and auditing. Blender 5.0 also has a Curve to Tube geometry-nodes modifier with round
  caps and UVs (https://developer.blender.org/docs/release_notes/5.0/modeling/).

## Subdivision with creases

`SubsurfModifier`: `levels`, `render_levels`, `use_creases` (default on). Since 4.0, creases are float attributes
`crease_edge` and `crease_vert` (`mesh.edge_creases_ensure()`); `MeshEdge.crease` is gone
(https://developer.blender.org/docs/release_notes/4.0/python_api/). In bmesh there is no dedicated accessor: use
`bm.edges.layers.float.get("crease_edge") or bm.edges.layers.float.new("crease_edge")` (inferred from the generic
layer API; check it). Creases between 0.3 and 1.0 give controlled hardness; 1.0 everywhere gives a box with rounded
corners again. Apply and reduce before export: the subdivided cage is rarely the game mesh.

## Deformers

- `SimpleDeformModifier`: `deform_method` `TAPER` (`factor`), `BEND` (`angle`), `TWIST`, `STRETCH`; `deform_axis`,
  `limits`, `origin` (an empty sets the centre)
  (https://docs.blender.org/api/current/bpy.types.SimpleDeformModifier.html).
- Lattice: `points_u/v/w` 1-64, the modifier's `object`, `strength`, `vertex_group`. A 3x3x3 lattice with its middle
  points pushed out 1-2% crowns a whole part (https://docs.blender.org/api/current/bpy.types.Lattice.html).
- Both need segments along the deformed axis, or they bend in facets.

## Bevel by weight, in tiers

Bevel weights are the attributes `bevel_weight_edge` and `bevel_weight_vert` since 4.0 (`MeshEdge.bevel_weight`
removed). One modifier per tier, each with its own attribute:

```python
me = ob.data
attr = me.attributes.get("bevel_tier_primary") or me.attributes.new("bevel_tier_primary", "FLOAT", "EDGE")
for i in primary_edge_indices:            # chosen by rule, never "all edges"
    attr.data[i].value = 1.0
md = ob.modifiers.new("Bevel primary", "BEVEL")
md.limit_method = "WEIGHT"
md.edge_weight = "bevel_tier_primary"     # the attribute this modifier reads
md.offset_type = "WIDTH"
md.width = 0.004
md.segments = 2
```

Pick the edges by rule from the spec's edge list, not by hand or "all": for example convex, not on the floor, not on
a joint face. In bmesh (a float layer becomes an edge attribute of that name when written back; check it in your
build):

```python
import bmesh, math

def tier_edges(ob, attr_name, pick):
    """Weight 1.0 on the edges pick(edge, zmin) accepts, 0.0 elsewhere, in a float edge attribute."""
    bm = bmesh.new(); bm.from_mesh(ob.data)
    lay = bm.edges.layers.float.get(attr_name) or bm.edges.layers.float.new(attr_name)
    zmin = min(v.co.z for v in bm.verts)
    for e in bm.edges:
        e[lay] = 1.0 if pick(e, zmin) else 0.0
    bm.to_mesh(ob.data); bm.free()

def outer_corner(e, zmin, min_deg=30.0):
    if len(e.link_faces) != 2 or not e.is_convex:
        return False                                    # open, overfull or concave: sharp
    if all(abs(v.co.z - zmin) < 1e-4 for v in e.verts):
        return False                                    # on the floor: sharp
    return math.degrees(e.calc_face_angle()) >= min_deg
```

Joint faces need their own test (their position against the neighbour part, or a face map or material set while
building).

`BevelModifier.edge_weight` names the attribute (default `bevel_weight_edge`), per the API page
(https://docs.blender.org/api/current/bpy.types.BevelModifier.html); confirm the property name in your build. The
modifier's enums differ from `bmesh.ops.bevel`'s (`miter_outer` is `MITER_SHARP` there, `SHARP` in the op).

## Version traps for code from older examples

| Old | Now | Source |
| --- | --- | --- |
| `mesh.use_auto_smooth`, `auto_smooth_angle` | Removed in 4.1: `Mesh.set_sharp_from_angle()`, the `sharp_edge` attribute, the Smooth by Angle modifier | https://developer.blender.org/docs/release_notes/4.1/python_api/ |
| `edge.bevel_weight`, `edge.crease` | Attributes `bevel_weight_edge`, `crease_edge` (4.0) | 4.0 Python API notes |
| Boolean `solver='FAST'` | `'FLOAT'` (5.0); `'MANIFOLD'` added in 4.5 | https://developer.blender.org/docs/release_notes/5.0/modeling/ , https://developer.blender.org/docs/release_notes/4.5/modeling/ |

When code fails, read the traceback and fix the call; never "fix" an error by deleting the failing step (an observed
LLM failure, `review-loop.md`).
