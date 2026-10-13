# UV workflows by asset type

Step lists for the four common cases, as Blender Python an agent can run. Each assumes the object is selected and
active, scale applied, and `import uv_audit as ua` done (SKILL.md, Script). Sources for the rules are in SKILL.md and
`baking-and-normal-maps.md`.

## Contents

- Hard-surface prop with a baked normal map
- Organic or curved prop
- Modular piece with trims and tiling materials
- Lightmap UV2

## Hard-surface prop with a baked normal map

```python
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
bpy.ops.object.shade_smooth_by_angle(angle=math.radians(30))   # smooth faces, hard edges above 30 deg
ua.seams_from_hard_edges([ob])                                   # every hard edge becomes a seam
# by hand: one seam down the least-seen side of every tube, plus undersides and material borders
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.0)
bpy.ops.object.mode_set(mode="OBJECT")
```

Shade smooth by angle first: on a flat-shaded mesh (Blender's primitives are) every edge is hard, so every face
would become its own island. Use 30 deg (Blender's default) up to 45; check that bevels are caught, since each
bevel segment turns only 90 / segments degrees. Angle-based seams never open a closed tube: tested on a cylinder,
hard-edge seams alone gave angular p95 74, and one extra seam down its back gave 1.00.

1. Check: `ua.audit(ob, map_px=2048, baking=True)`. Fix angular p95 above 1.15 with seams, not relaxing.
2. Straighten strips (Follow Active Quads), orient islands upright, `uv.align_rotation` for directional details.
3. Even the density (`uv.average_islands_scale()`), then scale up the faces seen close and down the hidden ones,
   or `ua.set_texel_density([ob], px_per_m, map_px, pad_px=...)` for an exact value.
4. Stack identical parts; move all but one copy +1 in U.
5. `ua.pack([ob], map_px=2048, pad_px=32)` (`rotate_method` is `CARDINAL` there).
6. Triangulate (modifier, applied) and bake with a cage; keep the triangulation for export.
7. `ua.audit(ob, map_px=2048, pad_px=32, baking=True)`: no issues.

## Organic or curved prop

1. Few seams, all hidden: underside, back, natural folds; the mirror axis for symmetric forms, or offset from the
   centre if the centre is seen. Cylinder-like parts: one seam down the least-seen side.
2. Unwrap `method="MINIMUM_STRETCH", iterations=150` for even density, or `ANGLE_BASED` when shape matters more.
   Pin border vertices and use Live Unwrap (`SpaceUVEditor.use_live_unwrap`) for hand corrections.
3. Audit; where a band stays stretched, add a seam there. With RizomUV installed, `rizomuv-uv-pipeline`'s
   `organic` preset does this better on revolved bodies.
4. Pack with `rotate_method="ANY"` only if the texture has no direction.
5. Bake on the whole mesh with mirrored copies offset.

## Modular piece with trims and tiling materials

1. Model to the grid and apply scale.
2. Split by material: tiling surfaces (walls, floors) and trim surfaces (mouldings, frames, edges).
3. Tiling surfaces: `bpy.ops.uv.cube_project(cube_size=map_px / px_per_m, correct_aspect=False)`; one UV tile is
   `cube_size` metres in object space (2048 / 512 = 4.0). Leave the UVs outside 0-1: they tile.
4. Trim surfaces:
   - seam along the hard edges into rectangular strips and unwrap;
   - straighten each strip (Follow Active Quads) and rotate it to run along U;
   - scale it to the kit's texel density (trims may vary about +/-25% from the scene density to fit a row,
     https://www.beyondextent.com/deep-dives/deepdive-texeldensity);
   - snap its V extent to a trim row; U may run past 0-1 along the strip, V must stay inside its row or it samples
     the next row. Blender 5.0+ can pack into a reserved region (UV > Set User Region, then Pack Islands with Pack
     To: Custom Region).
5. Keep one density across the whole kit so pieces meet without a visible jump.
6. Tools for matching faces to trim rows automatically: RizomUV's Hotspot (`rizomuv-uv-pipeline`), or Blender
   add-ons such as DreamUV HotSpotter and Trimmer; Blender has no built-in hotspotting (5.2).
7. UV0 may overlap freely here; the lightmap UV2 is a separate, unique unwrap.

## Lightmap UV2

```python
me = ob.data
if len(me.uv_layers) < 2:
    me.uv_layers.new(name="UVMap_Lightmap")      # the second map: the lightmap channel in most engines
me.uv_layers.active_index = 1                     # every UV operator below writes to this one
```

1. Start from a copy of a unique UV0 (`me.uv_layers.new(name=..., do_init=True)` copies the active map), or unwrap
   the second map: seam-based `uv.unwrap`, or `uv.smart_project(angle_limit=math.radians(66))` for architecture.
2. Unstack everything: no overlaps and no mirrored copies sharing texels. Re-unwrap Mirror and Array copies after
   applying the modifiers.
3. Few large charts, cut at hard angles; even relative area (`uv.average_islands_scale()`), enlarged only where
   lighting detail matters; straight, axis-aligned chart edges where the lightmapper's seam stitching should hide
   the seam.
4. Pack for the footprint the mesh will actually get: `ua.pack([ob], map_px=footprint_px, pad_px=4, layer=1)` keeps
   charts 4 px apart at that size, 2 px at half of it.
5. `ua.audit(ob, layer=1, map_px=footprint_px, pad_px=4, lightmap=True)`: no issues.
6. In the engine, turn automatic lightmap UV generation off for this mesh, and check its lightmap overlap view
   after baking (Unity: engine notes).

The footprint (texels per metre x mesh size x the renderer's lightmap scale) and the scene settings belong to the
engine's lighting setup (`vrchat-lighting-and-baking` for Unity / VRChat); `rizomuv-uv-pipeline` can size and pack it automatically
(`uv2="footprint"`).
