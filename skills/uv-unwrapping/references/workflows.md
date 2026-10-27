# UV workflows by asset type

Step lists for the four common cases, as Blender Python an agent can run. Each assumes the object is selected and
active, scale applied, and `import uv_audit as ua` done (SKILL.md, Script). Every `ua` call works on UV0 unless given
`layer=`, except the lightmap calls, which default to the second map. The rules and numbers are in SKILL.md, the
baking rules in `baking-and-normal-maps.md`, the script's functions in `uv-audit.md`.

## Contents

- Hard-surface prop with a baked normal map
- Organic or curved prop
- Modular piece with trims and tiling materials
- Tiling across joints, corners, curves, slopes and terrain
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
   centre if the centre is seen. Cylinder-like parts: one seam down the least-seen side. Rocks, roots and stumps:
   seams on the faces buried in or resting on the ground (delete faces that are always buried), along concave
   cracks and under overhangs, never along a ridge or across a face the player looks at. Shade the low smooth whole
   (an angle split makes every ridge a hard edge, and a hard edge a seam). Many small islands (*practice*: more than
   about 50 on one rock) mean the low is too dense or the seams follow noise: cut along the big forms only.
2. Unwrap `method="MINIMUM_STRETCH", iterations=150, margin=0.001` for even density, or `ANGLE_BASED` when shape
   matters more. Pin border vertices and use Live Unwrap (`SpaceUVEditor.use_live_unwrap`) for hand corrections.
3. Audit; where a band stays stretched, add a seam there. With RizomUV installed, `rizomuv-uv-pipeline`'s `organic`
   preset does this better on revolved bodies. A rock seamed only on its buried and concave sides may stay at
   angular p95 1.16-1.25 at any seam count; when every map it takes is baked from 3D (no painted or tiling texture
   on it), that stretch only lowers its resolution along one direction inside the 0.8-1.25x texel band (a rock at
   1.24 rendered the same as one at 1.04, measured): audit it with `limits={"angular_p95": 1.25}`, which the report
   records, rather than cutting a seam across a face the player sees.
4. Lay out: `ua.layout([ob], map_px, px_per_m, directional=False, rotate_method="ANY")` only when the texture has no
   direction; otherwise keep `directional=True`.
5. Bake on the whole mesh with mirrored copies offset (`bake=True` in step 4).
6. After texturing, measure every seam the player can see with pbr-texturing's seam check: a seam whose colour or
   normal steps more than the texture does inside an island shows, however well it is hidden from one angle.

## Modular piece with trims and tiling materials

1. Model to the grid; `ua.apply_stack(ob)`, then apply scale, as for any piece.
2. One material per kind of surface: tiling (walls, floors) and trim (mouldings, frames, edges, pipes). Every audit
   below takes `material=` so each part is judged by its own rule.
3. Tiling surfaces: `ua.tile_project([ob], tile_m=map_px / px_per_m, material="M_Wall*")` (512 / 512 = 1 m; the
   tile must divide the grid module and the storey height: next section). Never scale them into 0-1: they tile. Move
   them home by whole tiles, `ua.home_tiling([ob], material="M_Wall*")` (`period=` 1 / the material's tiling when it
   is not 1); that never changes the phase.
   Not `bpy.ops.uv.cube_project`: it centres the projection on the selection's bounds, so each piece starts at a
   different phase (5.2.2, measured: a 1 m wall's left edge at U 0.375, a 2 m wall's at 0.25, with cube_size 4).
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
   map_px=512, px_per_m=512, tile_m=1.0, steps=[1.0, 3.0])` (CLI `--material`, `--tile-m`, `--steps`): distortion,
   density within 10% on every island, every tiling face at tile_project's scale and phase, strips along U,
   every strip inside one row; overlaps and the tile bounds do not apply. Audited whole, the trim rules flag the
   tiling faces and the other way round. `island_boxes_px` in the JSON gives each island's pixel box.
6. Keep one density across the whole kit so pieces meet without a visible jump.
7. UV0 may overlap freely here; the lightmap UV2 is a separate, unique unwrap.

## Tiling across joints, corners, curves, slopes and terrain

A tiling material on a kit is laid by every instance of every piece at once, so a joint shows wherever the UVs of two
neighbours disagree mod one tile. Nothing per piece catches that: plan it.

**The tile divides the placement step.** Instanced pieces share one mesh, so each copy's pattern restarts at its
pivot; it continues across a joint only when every period in the material (the tile `map_px / px_per_m`, and a detail
or macro layer's period) divides the step the pieces are placed on: the grid module along walls and floors, the
storey height (or the vertical module) up the walls.

| Grid | 512 px/m | 1024 px/m |
|---|---|---|
| 1 m module, 3 m storeys | 512 px map (1 m tile), or 256 (0.5 m) | 1024 px map (1 m tile) |
| 2 m module, 4 m storeys | 1024 px (2 m), 512 (1 m) | 2048 px (2 m) |
| 1 m module, 4 m tile wanted | jumps at three joints in four: one of the three options below | |

A small tile repeats more often, so it must pass pbr-texturing's tile-scale check (an even tile), with variation from
variants, decals and the lightmap. A photographed or library material keeps its real scale: its period is the size
its source covers (`size_m` in `pbr-texture-sources`' source.json, `tile_m` in `image-to-pbr`'s record), or a whole
number of its own repeats cropped to fit; scaled the
same on U and V, never squeezed (a 1.4 m brick tile forced into 1 m makes every brick 29% too small, and different
factors on U and V stretch it). Where the art needs a period longer than the step:

1. Place that family only on multiples of the tile (the world spec's placements, checked by the validator), or
2. phase variants: one mesh per offset (`_P0`, `_P1`, ...: `tile_project(..., offset=(k * module, 0, 0))`, projected
   as if the piece stood k modules along), each placed where k = (s mod tile) / module, s the pivot's distance along
   the piece's own +X: s = x at rot 0, -x at 180, y at 90, -y at 270 (`x mod tile` alone is right only for walls
   facing -Y: measured, it put a +Y-facing run half a tile off at every joint). They share the material and batch
   (audit each with `tile_offset=`, CLI `--tile-offset`, and `--steps <tile>,<storey>`: a variant family's pieces
   repeat at the tile, not at the module); QA checks every placement's phase against the world grid, or
3. a world-space UV shader (UVs from the world position in the vertex shader): a custom shader, allowed in VRChat
   worlds on every platform; measure it on the mobile device. Untested here.

`audit(purpose="tiling", tile_m=..., steps=[module, storey])` flags a step that is not a whole number of tiles and any
face off tile_project's scale and phase by more than half a texel (`tile_phase`, uv-audit.md).

**Pivots and turns.** `tile_project` reads each face's position in the piece's own axes, so a piece must have its
pivot on the grid (the kit's bottom-left corner) and its scale applied (it refuses a negative scale). Walls may turn
in 90 deg steps about Z: U runs along each wall face whichever way the piece faces, so a turned wall matches an
unturned one facing the same way, and an applied Mirror gets the right U again when re-projected. **Floors and
ceilings may not turn**: their faces take U and V from the piece's own X and Y, so a floor tile turned 90 deg turns
its pattern too and jumps against its neighbours (measured, 5.2.2). Place tiling floor and ceiling pieces unturned,
or turned only by the texture's own symmetry (a pattern that looks the same turned 180 deg), and give QA the rule.

**Corners.** V is world Z on every wall face, so courses line up round any corner. U cannot continue round an outside
corner and keep both walls' own phase (the wall thickness is not a whole number of tiles): cover the corner with a
trim (quoins on masonry, a corner bead or pilaster on plaster; a quoin stands proud, so it is a TRIM piece of its own, never part of the wall piece, whose footprint must stay whole modules), or make the corner a piece of its own whose bricks
turn the corner in its own unique or trim UVs. Inside corners show less (shadowed); the same fixes apply.

**Trims across joints.** A strip's V span equals its row's span to half a pixel (an underfilled row cuts the baked
bevel off), both sides of a mitre map the same rows, and the strip carries nothing along U that would show a jump:
no patches, wear or features along it, or its U is projected from the piece's axes like tiling (`tile_project` on
those faces, then their V moved onto the row). A row with joints along U (voussoirs, blocks) follows the trim-on-an-
arc rule below.

**Curved walls, towers, columns, arches, spiral stairs.** A box projection stretches a face turned theta off its
axis by 1 / cos theta (1.15 at 30 deg, the angular p95 gate; 1.41 at 45 deg) and seams where the axis switches.
Unwrap them as strips, and mark the strip faces with the boolean face attribute `uv_strip`: the tiling audit then
judges them by stretch, density and their seams' continuity instead of against tile_project's phase.

1. Seams at the piece's ends; a closed ring (a tower, a column, a newel) gets one, in an opening or where something
   stands in front of it. An arch's jambs and intrados are one strip from foot to foot (tile_project runs the two
   jambs' U opposite ways, so a seam at a springing line opens by 205 px whatever you do); mark the jambs `uv_strip`
   with it. Planar faces off the piece's axes (a bay window's 45 deg sides, a splayed reveal, spiral risers) go the
   same way: one strip across their folds, marked `uv_strip`, never a box projection (1.41 at 45 deg).
2. Unwrap, then Follow Active Quads with `mode="LENGTH"` from a square quad, so U runs along the curve and V up the
   wall (on an intrados or a stair soffit, V along the arc and U across). Never `LENGTH_AVERAGE` on a strip cut from
   a larger mesh: it averages each edge loop with the faces the loop runs on into (spandrels, reveals, a plinth) and
   stretched an arch soffit 0.87-1.31x and tore a tower ring 23 mm (measured, 5.2.2); `LENGTH` was exact. It
   straightens only the active quad's island: each island needs its own active quad.
3. Scale each island to the family's density: `ua.set_texel_density(..., per_island=True)` (`per_island=False`
   averages over every island of the material, so use it only when the strip is that material's only island: a
   newel sharing its material with projected treads came out 1.35% off). Then move V so V = z / tile on a wall (the
   courses meet the straight pieces), and U so the end that meets a neighbour sits on a whole tile.
4. A closed ring closes on whole tiles. The strip lies at the facets' chord length, so N facets at radius r hold
   2 N r sin(pi / N) / tile tiles, not 2 pi r / tile (*derived*: at r = 16 / 2 pi a 64-gon holds 15.994, 6.4 mm short,
   a 16-gon 103 mm short). Plan the radius for the most seen ring, r = n x tile / (2 N sin(pi / N)) (16 tiles on 64
   facets: 2.5475 m); scale U on every other ring of the piece (the inside face, a plinth, a cornice) to its nearest
   whole count, which moves its density a percent or two (keep it in the band). An open arc cannot put both ends on
   whole tiles: the end that meets a continuation goes on one, the other under a trim or into an opening.
5. Trim on an arc (voussoirs, an archivolt, a cornice ring): the trim row bent along the arc. Joints along U are
   allowed when their period divides the strip's arc length at its mid radius (17 voussoirs of 0.25 m on a 4.31 m
   arc: U x 0.986, an odd count with the keystone on the crown). A strip of depth w on a ring of mid radius r stretches
   by (r + w / 2) / r at its outer edge and squeezes as much at the inner, so keep w / r under about 0.19 (the 1.15
   gate; 0.2 m at 1.37 m read p95 1.114) or split it into two rows. A closed trim ring holds whole sheet widths.
6. Spiral stairs: tread tops and undersides by `tile_project` (they are flat), risers planar, tread rims at arc
   length, the newel as a ring (step 4), the handrail as one helix strip with the grain along it.
7. Audit `purpose="tiling"` with `tile_m=`: strip faces are judged for stretch and density, and every UV seam inside
   the surface must open by whole tiles (`seam_phase_px_max`, half a texel: a ring that does not close fails). Seams
   between two strip faces count up to a 60 deg fold, so an octagon's or a hexagon's ring is judged; a tread's 79 deg
   corner is not.
8. What the gate cannot pass, choose before modelling: a column of r 0.18-0.28 m at a 1 m tile cannot close on whole
   tiles inside the stretch gate (a smaller tile, a plain or trim material, or a radius that closes); a dome's rings
   cannot tile (a unique bake, or radial trim); a hip or ridge between two tiling planes shows unless a cap piece
   covers it (texture_seams X9 sees the uncovered join).

**Slopes and terrain.** A top-down projection (U = x, V = y, what tile_project gives faces that face up) stretches a
slope by 1 / cos(slope) along the fall line: the angular p95 gate (1.15) fails above 29.6 deg, the tiling density
band (the audit's sqrt(UV area / surface area), sqrt(cos(slope)) here, under 0.9) above 35.9 deg (*derived*). Project
the ground from a shared origin (chunks with pivots on the tile grid, so they continue) and only where it is under
about 25 deg, a margin under the gate; steeper ground is a separate mesh (a bank, a cliff, rocks) with a seam-based unwrap
at the family's density and its seams in cracks and at its foot, or a world-space triplanar shader (a custom shader;
measure it on mobile). Its seams cannot open by whole tiles: judge them with `texture_seams` on the real texture (busy
ground hid every one, a rock texture showed 3.7 m), then audit it as tiling with `limits={"seam_continues_deg": 0}`,
which the report records. Compute terrain normals before cutting it into chunks and weld chunk borders, or every chunk
edge shows as a lighting line. Never `uv.randomize_uv_transform` on a surface that continues across a joint or a
seam: each island jumps against its neighbour. Ground materials (a macro map with the tiling detail in the detail
slot): pbr-texturing.

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
   A scene that bakes with Unity's Bakery: `pack_lightmap(..., lightmapper="bakery")` packs for Bakery's
   area-based footprint instead (engine notes), and the audit in step 5 takes the same `lightmapper`.
   A footprint too small for 2-texel gaps (fewer texels than `lightmap_capacity_px(charts)`, or under 64 px with a
   pack that misses them) is packed for 64 px instead, never left to spill, with a note: a Free prop (a Free-sized
   PROP or FOL piece) is probe-lit, a LOD follows its piece, any other piece needs its Scale In Lightmap raised.
   Pass `notes={}` to collect the notes.
5. `ua.audit(ob, texels_per_m=..., lightmap_scale=...)`: no issues. `texels_per_m` makes it a lightmap audit of the
   second map; it measures b, the box of all the UV2 charts as a share of the tile, and checks gaps, edge margin,
   chart bends and bounds at that footprint (x the LOD scale); under 64 px, as packed for 64 px, with the note. At 64
   px or more, a note when the charts fill under half their box (with `lightmapper="bakery"`, an issue when they
   get under half the planned texels per metre).
6. `me.uv_layers.active_index = 0`, so later UV work and texture painting target UV0 again.
7. In the engine, turn automatic lightmap UV generation off for this mesh and check its lightmap overlap view after
   baking (Unity: engine notes). Free props (Free-sized PROP or FOL pieces) under a 64 px footprint are probe-lit
   instead, judged on LOD0; the lighting setup decides (`vrchat-lighting-and-baking` for Unity / VRChat).

With RizomUV installed, `rizomuv-uv-pipeline` packs the lightmap UV from the same islands as UV0.
