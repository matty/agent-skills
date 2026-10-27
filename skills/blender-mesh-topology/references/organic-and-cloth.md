# Organic and cloth high polys, and their lows

Scope: rocks, cliffs, roots, stumps, bark and other organic props, and cloth (tablecloths, curtains, cushions), built
by an agent working headless through `bpy` or a Blender MCP. Then the low poly for each. Pairing, the gate and what
makes a high bake well are `high-and-low-poly.md`; the bake is `pbr-texturing`'s; UV seams on organic forms are
`uv-unwrapping`'s (organic section of its workflows).

*Measured* means run on Blender 5.2.2 headless on 2026-10-27; the repo's Blender test
`tools/tests/blender/test_topology_scripts.py` (`test_high_poly_routes_run_headless`) repeats the API facts.

## 1. Sculpting without brushes

`bpy.ops.sculpt.brush_stroke` refuses to run headless (its poll fails: "context is incorrect", *measured*), so an agent
sculpts with modifiers. With the user at Blender, brush sculpting is theirs; give them the detail list and sizes below.

A rock, as a modifier stack on a base mass (*measured*: runs headless, 43,768 faces for a 1.2 x 0.8 x 0.6 m block):

```python
ob.scale = (1.2, 0.8, 0.6); bpy.ops.object.transform_apply(scale=True)     # the primary mass at its real size
bev = ob.modifiers.new("Bevel", "BEVEL"); bev.width, bev.segments = 0.12, 2   # flat fracture planes, soft edges
rem = ob.modifiers.new("Remesh", "REMESH"); rem.mode, rem.voxel_size = "VOXEL", 0.02
sm = ob.modifiers.new("Smooth", "SMOOTH"); sm.factor, sm.iterations = 0.5, 10   # voxel steps out
sub = ob.modifiers.new("Sub", "SUBSURF"); sub.levels = sub.render_levels = 1
seed = bpy.data.objects.new("ROCK_A_seed", None); scene.collection.objects.link(seed)   # moves the noise per variant
for name, kind, scale, strength in (("large", "VORONOI", 0.6, 0.08), ("medium", "CLOUDS", 0.15, 0.02)):
    t = bpy.data.textures.new(name, kind); t.noise_scale = scale
    d = ob.modifiers.new(name, "DISPLACE"); d.texture, d.strength, d.mid_level = t, strength, 0.5
    d.texture_coords, d.texture_coords_object = "OBJECT", seed
```

Rules (*practice* unless marked):

- **Largest scale first.** Primary form (the mass, its big planes and overhangs), then secondary (fractures, strata,
  root flare, bark plates), then tertiary (pits, grain): each Displace at a smaller noise scale and strength than the
  last. One noise of one scale over everything is the "blob" look.
- **Planes before noise.** Rocks break along planes: cut flat facets first (a bevelled block, plane booleans), then
  displace. Keep one strata direction across a cliff, so its layers read as one body of rock.
- **Sizes against the viewing distance** (`detail_scale.py`, *derived*): relief deeper than the stereo threshold at
  the nearest distance (14 mm at 1 m, 55 mm at 2 m, 125 mm at 3 m) shows depth and stays in the low's geometry;
  shallower relief goes in the bake; anything under 2 px wide at the usual distance (1.7 mm at 1 m, 5.2 mm at 3 m)
  goes in the texture.
- **Density for the bake.** The high needs faces small enough to carry its smallest displaced feature (about four
  faces across it), no smaller: a cleanly shaded high bakes the same at any density beyond that
  (`high-and-low-poly.md`). Voxel steps show in the bake: smooth them (Smooth modifier) before the displacement.
- **Variants differ in their primary form**, not in a noise seed: a slab, a tall block, a split pair, a rounded
  boulder. Moving the seed empty changes the noise only (*measured*: 7.8 mm mean height change on the block above,
  invisible at 3 m). Compare variants with `review_render.compare(rock_a, rock_b, views)`: their silhouettes must
  differ from the player's views.
- **Ground contact.** Sink rocks and roots into the ground by a few centimetres (*practice*) and let the texture's
  position mask darken the base (`pbr-texturing` wear reference): a rock resting on its lowest point floats.

Bark on a stump: the same stack on the trunk's revolved shape, with the large noise stretched along the trunk (a
Mapping-scaled texture, or `texture_coords_object` scaled along the axis) so plates run with the grain; roots as swept
curves converted to mesh and voxel-merged into the trunk before the displacement.

## 2. The organic low poly

| Route | When | Blender |
| --- | --- | --- |
| QuadriFlow | A closed organic mesh that may deform or will be hand-edited | `bpy.ops.object.quadriflow_remesh(target_faces=n, seed=0)`: on a closed mesh, *measured* 385 quads for a 400 target on an icosphere |
| Decimate (Collapse) | Static props (rocks, stumps): triangles are fine and the silhouette is kept best per triangle | a Decimate modifier, `ratio` to the target count |
| Quad Remesher | Patches with frozen borders (SKILL.md section 4) | `quad_remesh.py`; it refuses a closed mesh with no border |

Then, before UVs:

1. `high_low_gap(low, [high])` at the nearest viewing distance: the low's outline within 2 px of the high's, the
   relief left to the bake within the stereo threshold (`high-and-low-poly.md` section 3).
2. Shade the low smooth whole (no angle split: it makes every ridge a hard edge and a seam).
3. Delete faces that are always buried in the ground; they waste texels and their seams are the easiest to hide.
4. Budgets are the world's; as a starting point (*practice*): a boulder seen from 1-3 m 1-3k triangles, a stump with
   roots 2-5k, LOD1 at about half.
5. UVs: seams on buried and contact faces, concave cracks and undersides (`uv-unwrapping`); bake with a fitted cage
   where creases are deep (`pbr-texturing`).

Several rocks sharing one material: one shared atlas of their baked maps (normal, AO, a macro colour) at one texel
density, with the close-range detail (lichen, grain) in the engine's detail slot on its own tiling, so a 1024 map on
mobile still looks sharp up close (`pbr-texturing`).

## 3. Cloth

A tablecloth, curtain or throw: a subdivided plane at its real size draped by Blender's cloth simulation, stepped
frame by frame and applied. Cushions: a closed, subdivided box inflated by pressure.

```python
plane = ...                                    # real size, about 1-2 cm between vertices; UVs laid out flat first
table.modifiers.new("Collision", "COLLISION"); table.collision.thickness_outer = 0.002
cl = plane.modifiers.new("Cloth", "CLOTH")
cl.collision_settings.distance_min = 0.003
cl.collision_settings.use_self_collision = True        # folds that touch
cl.point_cache.frame_end = 60
for f in range(1, 61):
    scene.frame_set(f)                          # step in order: the cache needs every frame
bpy.ops.object.modifier_apply(modifier="Cloth")         # with the plane active
```

- **Collision distances.** At Blender's defaults (the cloth's `distance_min` 15 mm, the collider's
  `thickness_outer` 20 mm) a draped tablecloth hovered 34 mm above the table; with 3 mm and 2 mm it sat 4.5 mm above
  it (*measured*). Set both to a few millimetres, or the cloth floats visibly.
- **Pressure for cushions**: `cl.settings.use_pressure = True`, `uniform_pressure_force` (a closed box of 0.4 m rose
  from 60 to 110 mm at its top with a force of 5 and no gravity, *measured*); pin a cushion's piping or a curtain's
  top with a vertex group in `cl.settings.vertex_group_mass`.
- **UVs before the simulation**, on the flat sheet, so the weave follows the folds without stretching
  (*practice*); they survive the simulation because the topology does not change.
- **Thickness**: a Solidify (or a hem: the border edge loop extruded down a few millimetres) after the simulation.
  A single-sided sheet disappears from behind in an engine that culls back faces, as Unity's Standard does.
- **The low**: the applied sheet decimated or QuadriFlow-remeshed with its border kept where it meets a rail or a
  table edge, then the simulated folds baked onto it. Upholstery forms (crown, sag, piping sizes) are `3d-form-design`'s.
