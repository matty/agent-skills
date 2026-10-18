# UV workflows by asset type

Step lists for the four common cases, as Blender Python an agent can run. Each assumes the object is selected and
active, scale applied, and `import uv_audit as ua` done (SKILL.md, Script). Every `ua` call works on UV0 unless given
`layer=`, except the lightmap calls, which default to the second map. The rules and numbers are in SKILL.md, the
baking rules in `baking-and-normal-maps.md`, the script's functions in `uv-audit.md`.

## Contents

- Hard-surface prop with a baked normal map
- Organic or curved prop
- Modular piece with trims and tiling materials
- Lightmap UV2

## Hard-surface prop with a baked normal map

```python
DIRECTIONAL = True        # this piece's texture has a grain (wood, brushed metal); False for a plain or painted one
BAKE = True               # it takes a baked normal map
st = ua.apply_stack(ob, add_triangulate=BAKE)       # from the top; Triangulate off and trailing Mirrors live for now
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)   # after: a live Bevel is object-space
if st["hard_surface"]:                              # Weighted Normal, Harden Normals or custom normals:
    ua.seams_by_angle([ob])                         # seams by angle, keeping its sharp edges; never shade it again
elif not st["shading_designed"]:                    # a plain piece nobody set sharp edges on: this mesh only
    ob.data.set_sharp_from_angle(angle=math.radians(30))   # hard edges above 30 deg
    ob.data.shade_smooth()
ua.seams_from_hard_edges([ob])                      # every hard edge becomes a seam
# by hand: one seam down the least-seen side of every tube, plus undersides and material borders
ob.data.uv_layers.active_index = 0                  # UV0: the map every UV operator writes to
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.001)   # at margin 0 touching islands fuse across seams
bpy.ops.object.mode_set(mode="OBJECT")
```

Why this order (Blender 5.2.2, measured 2026-10-17 on `blender-mesh-topology`'s route A and B stacks):

- The stack is built Mirror / Array first, then Smooth by Angle (if used), Bevel, Triangulate (Keep Normals),
  Weighted Normal (`blender-mesh-topology`): a Smooth by Angle above a leading Mirror misses a fold on the mirror
  plane (6.50 deg off flat). `apply_stack` refuses a Mirror or Array below the Triangulate: move it above the
  Triangulate, first in the stack. Run `apply_stack` before applying scale: a live Bevel's width is in object space.
- `apply_stack` applies from the top, in stack order, down to and including the last topology-changing modifier,
  never a lower one alone. Applying only the Bevel under a Smooth by Angle let the Smooth by Angle re-sharpen the
  chamfers: the normals moved 39.14 deg (route A) and 34.33 deg (route B); from the top, 0.00. Applying the Bevel
  alone under a Mirror lost all 8 chamfer faces on the ridge that lies on the mirror plane (10 mm off); from the top,
  the mesh matched the live stack exactly. With the Bevel live instead, the hard edges sit on its rails while the
  seams stay on the base edges (144 hard edges off their seams, chamfer angular p95 1.31).
- A hard-surface stack is never shaded by angle again: `shade_smooth_by_angle` on an applied route-A piece moved the
  normals 30.06-33.84 deg and added 48-67 sharp edges. `seams_by_angle` (what `edges_select_sharp` at 30 deg and Mark
  Seam do) places seams without touching the normals. A plain mesh is shaded by angle first: flat-shaded (Blender's
  primitives are), every edge is hard and every face would become its own island. 30 deg (Blender's default) up to 45.
  Shade through the mesh (`ob.data.set_sharp_from_angle`, `ob.data.shade_smooth`): the operator
  `bpy.ops.object.shade_smooth_by_angle` re-shades every selected object, and moved an applied route-A piece that was
  also selected 33.84 deg.
- The stack's Triangulate (Keep Normals) stays a modifier, off in the viewport until after `layout`, which refuses
  it. One added after the Weighted Normal moved the normals 7.86 deg (12.55 with Keep Normals off); one above it with
  Keep Normals off, 0.74-12.59 deg; so `add_triangulate=True` adds it with Keep Normals and Minimum Vertices 4
  directly above the Weighted Normal.
- RizomUV after `apply_stack` (`rizomuv-uv-pipeline`): pass `modifiers='ignore'`, never `'apply'`, which bakes the
  viewport mesh and drops the Triangulate and Weighted Normal (12.59 deg off after export).
- A Mirror with nothing topology-changing below it stays live through seams and unwrap (its halves share UVs) and is
  applied in step 4. A Mirror above a Bevel is applied with the stack and its halves get unique UVs: once applied,
  nothing stacks mirrored halves (`stack_faces` refuses them; `uv.copy` / `uv.paste` folded them, angular max 175).
- Angle-based seams never open a closed tube: on a cylinder, hard-edge seams alone gave angular p95 74, one extra
  seam down its back 1.00.

1. Check: `ua.audit(ob, map_px=2048, pad_px=0, baking=True)` (`pad_px=0`: the gaps come with the layout). Fix the
   distortion gate with seams, not relaxing.
2. Straighten strips (Follow Active Quads). For a directional texture, orient per face group with the axis across
   the grain (SKILL.md section 5), selecting each group in Edit Mode, face select mode, after `mesh.select_all(action=
   "DESELECT")`, never `uv.select_all`.
3. Stack identical parts exactly, before triangulating: `ua.stack_faces(ob, part_a_faces, part_b_faces)` for
   duplicated parts (it raises, writing nothing, when the copy's corners do not match: a mirrored or scaled copy, or
   faces re-ordered; Shift+D and joined object copies kept their order through an applied Bevel, `bmesh.ops.duplicate`
   copies did not), or `uv.copy` / `uv.paste` one island at a time. Array copies are not one contiguous face range
   once a Bevel below the Array is applied: pair them by position, `ua.stack_faces(ob, src, ua.pair_faces(ob, src,
   offset))` with `offset` the Array step in object space (all 4 copies of a slat stacked so). Shrink islands nobody
   sees and mark their faces: `me.attributes.new("uv_low_density", "BOOLEAN", "FACE")`, True on those faces.
4. Apply a Mirror kept live, then lay out in one call: `ua.apply_stack(ob, keep_mirror=False)`, then
   `res = ua.layout([ob], map_px=2048, px_per_m=512, directional=DIRECTIONAL, bake=BAKE)`. If `res[ob.name]["fits"]`
   is False: a larger map, a lower density, split the piece or delete faces nobody sees. Do not pack again after it.
   `bake=True` also moves the mirrored halves' flipped half +1 U.
5. Turn the Triangulate back on (`if st["triangulate"]: ob.modifiers[st["triangulate"]].show_viewport = True`; the
   bake and the exporter read it live) and bake with a cage into a plain, non-UDIM image.
6. `ua.audit(ob, purpose="unique", map_px=2048, px_per_m=512, baking=BAKE, directional=DIRECTIONAL)`: no issues
   (with `text=True` too where faces are marked `uv_text`: SKILL.md section 5). Look at a checker: grain along U on
   every board. Audit directional and non-directional pieces in separate calls (the flag applies to every object),
   or one material at a time with `material=`.

## Organic or curved prop

1. Few seams, all hidden: underside, back, natural folds; the mirror axis for symmetric forms, or offset from the
   centre if the centre is seen. Cylinder-like parts: one seam down the least-seen side.
2. Unwrap `method="MINIMUM_STRETCH", iterations=150, margin=0.001` for even density, or `ANGLE_BASED` when shape
   matters more. Pin border vertices and use Live Unwrap (`SpaceUVEditor.use_live_unwrap`) for hand corrections.
3. Audit; where a band stays stretched, add a seam there. With RizomUV installed, `rizomuv-uv-pipeline`'s `organic`
   preset does this better on revolved bodies.
4. Lay out: `ua.layout([ob], map_px, px_per_m, directional=False, rotate_method="ANY")` only when the texture has no
   direction; otherwise keep `directional=True`.
5. Bake on the whole mesh with mirrored copies offset (`bake=True` in step 4).

## Modular piece with trims and tiling materials

1. Model to the grid; `ua.apply_stack(ob)`, then apply scale, as for any piece.
2. One material per kind of surface: tiling (walls, floors) and trim (mouldings, frames, edges, pipes). Every audit
   below takes `material=` so each part is judged by its own rule.
3. Tiling surfaces: `bpy.ops.uv.cube_project(cube_size=map_px / px_per_m, correct_aspect=False)`; one UV tile is
   `cube_size` metres in object space (2048 / 512 = 4.0). Leave the UVs outside 0-1: they tile.
4. Trim surfaces, on a sheet of w x h px (2048x1024 below). Neither this skill nor `rizomuv-uv-pipeline` automates
   trim matching; do it by hand:
   - Give the trim material the sheet before unwrapping: an Image Texture node holding an image of the sheet's size,
     made the material's active node (`mat.node_tree.nodes.active = node`). `uv.unwrap` (`correct_aspect=True`, its
     default) reads the aspect from it. Without it, every island on a 2048x1024 sheet came out 2.00x stretched;
     with it, 1.000 (5.2.2). No image at hand: unwrap, then scale those islands' U by h / w (0.5 here).
   - Seam along the hard edges into rectangular strips, one seam down every tube; unwrap (`margin=0.001`);
     straighten each strip (Follow Active Quads).
   - Orient: GEOMETRY with the axis across the strip, per face group. Strips still along V (tube strips have no single
     axis): `ua.turn_islands([ob], map_px="2048x1024", material="M_Trim*")` turns them 90 deg in square pixels; check
     a profiled strip's top side.
   - Density: `ua.set_texel_density([ob], 512, "2048x1024", pack_after=False, material="M_Trim*")` (`layout` and
     `pack` take square maps only), within 10% of the kit's density (the trim tolerance); a strip that needs more to
     fit its row belongs on another row. Both calls take `material=` so the tiling faces of the same mesh keep their
     cube projection: on the whole object they turned and rescaled the wall (tiling audit: angular p95 4.00).
   - Move each strip's V extent onto its row from the trim layout (rows in pixels); U may run past 0-1 along the
     strip, V must stay inside its row or it samples the next one. Blender 5.0+ can pack into a reserved region:
     `bpy.ops.uv.custom_region_set`, then Pack Islands with `udim_source="CUSTOM_REGION"`.
   - Caps, end discs and flange rings are not strips: give them a row or region of their own on the sheet (a plain
     or radial band, the last 128 px say) and list it in `rows=`, or put them on the tiling material.
   RizomUV's Hotspot can match pieces to trim rectangles interactively, in RizomUV itself.
5. Audit each material with its purpose: `ua.audit(ob, purpose="trim", material="M_Trim*", map_px="2048x1024",
   px_per_m=512, rows="0-128,128-192,192-224,896-1024")` and `ua.audit(ob, purpose="tiling", material="M_Wall*",
   map_px=2048, px_per_m=512)` (CLI `--material`): distortion, density within 10% on every island, strips along U,
   every strip inside one row; overlaps and the tile bounds do not apply. Audited whole, the trim rules flag the
   tiling faces and the other way round. `island_boxes_px` in the JSON gives each island's pixel box.
6. Keep one density across the whole kit so pieces meet without a visible jump.
7. UV0 may overlap freely here; the lightmap UV2 is a separate, unique unwrap.

## Lightmap UV2

```python
me = ob.data
if len(me.uv_layers) < 2:
    me.uv_layers.new(name="UVMap_Lightmap")      # the second map: the lightmap channel in most engines
me.uv_layers.active_index = 1                     # every UV operator below writes to this one
```

1. Unwrap the second map seam-based, the default: `ua.seams_from_hard_edges([ob])` (hard edges as in the hard-surface
   list, plus a seam down every closed tube), then `bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.001)` with all
   faces selected in Edit Mode. On a 2 x 3 m wall with a door this gave 10 charts and no bends. A copy of a unique UV0
   (`me.uv_layers.new(name=..., do_init=True)` copies the active map) with stacks and mirrors pulled apart also works.
   `uv.smart_project(angle_limit=math.radians(66), island_margin=0.001)` only with the audit of step 5 straight after
   it: on that wall it joined faces across four 90 deg corners at every `island_margin` from 0.001 to 0.02.
2. Unstack everything: no overlaps and no mirrored copies sharing texels. Re-unwrap Mirror and Array copies after
   applying the modifiers.
3. Few large charts, cut at hard edges and bends over 88 deg; even relative area (`uv.average_islands_scale()`),
   enlarged only where lighting detail matters; straight, axis-aligned chart edges where the lightmapper's seam
   stitching should hide the seam.
4. Pack: `ua.pack_lightmap([ob], texels_per_m, scale)` with the scene's lightmap texels per metre and the renderer's
   lightmap scale (both from the lighting setup). It packs a 2 px gap at `texels_per_m x sqrt(area) x scale` px, the
   smallest texel scale the renderer can get (b = 1), so the gaps stay 2 texels or more at the real one, and the
   charts fill their bounding box (the box of all the charts together). Fill the box at any aspect ratio: empty space
   inside it costs texels. What a lightmapper packs (Unity: that box, so the cost does not depend on the layout) and
   each LOD's texel scale (Unity: 0.5^n for `<Piece>_LOD<n>`, each LOD in its own space) are the engine's: engine
   notes. Each LOD's UV2 is packed for its own footprint, which `pack_lightmap` reads from the name (or `lod=`).
   A footprint too small for 2-texel gaps (fewer texels than `lightmap_capacity_px(charts)`, or under 64 px with a
   pack that misses them) is packed for 64 px instead, never left to spill, with a note: a Free prop (a Free-sized
   PROP or FOL piece) is probe-lit, a LOD follows its piece, any other piece needs its Scale In Lightmap raised.
   Pass `notes={}` to collect the notes.
5. `ua.audit(ob, texels_per_m=..., lightmap_scale=...)`: no issues. `texels_per_m` makes it a lightmap audit of the
   second map; it measures b, the box of all the UV2 charts as a share of the tile, and checks gaps, edge margin,
   chart bends and bounds at that footprint (x the LOD scale); under 64 px, as packed for 64 px, with the note. At 64
   px or more, a note when the charts fill under half their box.
6. `me.uv_layers.active_index = 0`, so later UV work and texture painting target UV0 again.
7. In the engine, turn automatic lightmap UV generation off for this mesh and check its lightmap overlap view after
   baking (Unity: engine notes). Free props (Free-sized PROP or FOL pieces) under a 64 px footprint are probe-lit
   instead, judged on LOD0; the lighting setup decides (`vrchat-lighting-and-baking` for Unity / VRChat).

With RizomUV installed, `rizomuv-uv-pipeline` packs the lightmap UV from the same islands as UV0.
