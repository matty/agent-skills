---
name: uv-unwrapping
description: UV unwrapping in Blender for real-time 3D - stretched, blurry, backwards or overlapping UVs, visible seams or normal-map lines, bleeding bakes, wasted island space; seams, texel density (px/m), mip-safe padding, stacking, trim, tiling, unique and lightmap UV2 rules, with an audit and layout script. For automating with RizomUV, rizomuv-uv-pipeline wins; for lightmap resolution, footprint budgets and bakes, vrchat-lighting-and-baking wins.
---

# UV unwrapping

Decide what each surface's UVs are for before cutting a seam: the purpose sets the seams, the density, the padding and
whether islands may overlap. `scripts/uv_audit.py` measures every number below and runs the stack, density and pack
steps in their only safe order ([manual](references/uv-audit.md); engines: [notes](references/engine-notes.md)).

**First:** with RizomUV installed and a batch of pieces, load `rizomuv-uv-pipeline` for seams, unwrap, grading and
packing; it does not straighten or stack islands and still needs the structural seams of section 3. After
`apply_stack`, a hard-surface piece goes to it with `modifiers='ignore'`, never `'apply'` (that bakes the viewport
mesh and drops the Triangulate and Weighted Normal: 12.59 deg off after export).

## 1. Pick the UV strategy per surface

| Surface | `purpose` | UVs |
|---|---|---|
| Walls, floors, terrain, large plain surfaces | `tiling` | world scale, may run far outside 0-1 (Cube Projection, section 6) |
| Mouldings, frames, pipes, trims, kit edges | `trim` | straightened strips on the trim sheet's rows, U free along the strip |
| Props and hero pieces with their own texture or a bake; objects sharing an atlas | `unique` | the order of work below, inside 0-1 |
| Every render mesh of a kit (LODs and probe-lit props too, not `_COL`) | `lightmap` | the second UV map; its gaps and bends matter where it is lightmapped (section 9) |

One mesh can mix them (audit each part with `material=`); repeated props share one mesh and one set of UVs. Recipes
per asset type as runnable Python: [references/workflows.md](references/workflows.md).

## 2. Order of work for a unique unwrap

1. `st = ua.apply_stack(ob)`, then apply scale (a live Bevel's width is in object space). It applies the stack (built
   Mirror / Array, Smooth by Angle, Bevel, Triangulate, Weighted Normal) from the top down to and including the last
   topology change, never a lower one alone. The Triangulate stays unapplied and off in the viewport until after
   `layout`; a Weighted Normal and trailing Mirrors stay live (section 8). A baked piece with none gets one:
   `add_triangulate=True` (Minimum Vertices 4, Keep Normals, directly above any Weighted Normal).
2. Hard edges. A hard-surface stack (`st["hard_surface"]`: a Weighted Normal, a Bevel with Harden Normals, or custom
   normals) is never shaded by angle again: seam it by angle, `ua.seams_by_angle(objs)` (`edges_select_sharp` at 30
   deg, then Mark Seam), keeping its sharp edges. A plain piece whose sharp edges nobody set (`not
   st["shading_designed"]`): `ob.data.set_sharp_from_angle(angle=math.radians(30))`, `ob.data.shade_smooth()` (this
   mesh only: `bpy.ops.object.shade_smooth_by_angle` re-shades every selected object).
3. Seams (section 3); a baked piece starts with `ua.seams_from_hard_edges(objs)`.
4. Unwrap UV0: `ob.data.uv_layers.active_index = 0`, then `bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.001)`.
   Without `method` it reuses the last one; at margin 0, islands that land touching along a seam fuse into one.
5. Distortion (section 4): audit (`pad_px=0` until the layout), add or move seams, unwrap again until the gate passes.
6. Straighten strips and orient islands, one face group at a time (section 5).
7. Stack identical parts and mirrored halves exactly on one copy, before triangulating (section 8); shrink islands
   nobody sees and mark them `uv_low_density` (section 6).
8. `ua.apply_stack(ob, keep_mirror=False)` (a Mirror kept live), then lay out in one call, `ua.layout(objs, map_px,
   px_per_m=..., directional=..., bake=...)`: density, one pack keeping stacks, sizes and orientation, `fits`, and +1 U
   copies for a bake. Never pack again: a plain pack undoes it. Then turn the Triangulate back on.
9. Audit: `ua.audit_selected(purpose="unique", map_px=..., px_per_m=..., baking=..., directional=...)` prints no
   issues (`text=True`: section 5); then look at a checker or the texture: grain along U, text readable.
10. Add the lightmap UV as the second UV map of every render mesh in a kit (section 9).

## 3. Seams

| Put seams | Why |
|---|---|
| On every hard edge (split normals) of a piece that takes a baked normal map | otherwise the bake draws a line along the edge; a seam on a hard edge costs no extra vertices |
| On hard edges, natural creases and material boundaries of hard-surface parts | the texture changes (or the mesh splits) there anyway, and islands come out flat |
| Where nobody looks: the back of a cylinder, undersides, inside handles, behind other parts | seams show as texture and lighting breaks |
| Around cylinder caps, and one line down the least-seen side of every tube | a closed tube never opens by itself: it unwraps folded until one seam runs along it |
| Organic and symmetric forms: few and hidden; on the mirror axis to share texture, or offset from a face's centre | fewer visible breaks; an offset seam keeps the lighting seam off the centre line |

Seams need not form closed loops. Too many cost vertices and gutter space, too few cost stretch: stop when the
distortion gate passes. Operators and their traps: [references/blender-uv-tools.md](references/blender-uv-tools.md).

## 4. Distortion

Measure, do not eyeball. The gate (this skill owns the numbers; `rizomuv-uv-pipeline` and `vrchat-world-qa` use them):

| Measure | Gate | Reads as |
|---|---|---|
| Angular p95 (singular-value ratio of the 3D-to-UV map, area-weighted) | <= 1.15 | 1.00 = shape kept; 1.15 = a square drawn 15% longer one way |
| Angular p99 | <= 1.5 | the tail p95 hides: a folded or collapsed band |
| Angular max, over triangles that are not 3D slivers | <= 2.0 | one squashed face fails it |
| Area p95 (log2 of the density change inside an island) | <= 0.20 | 0 = even density inside each island |

Fix with seams first; keep a `uv.minimize_stretch` result only if the audit improves (sphere p95 1.06 to 1.23, 5.2.2).

## 5. Straighten and orient

- Straighten every strip of quads (trims, belts, frames, pipes, stairs): it packs tighter and its edges follow the
  pixel grid. Square one quad, make it active, `bpy.ops.uv.follow_active_quads(mode="LENGTH_AVERAGE")`.
- Directional textures (wood grain, fabric, brushed metal): grain along U on every island.
  `uv.align_rotation(method="GEOMETRY", axis=A)` turns each selected island so 3D axis A points along +V (an island
  whose normal is A stays put; Blender 5.2.2). Pass the axis ACROSS the grain, one face group at a time: Z for the
  vertical faces of horizontal boards, Y for the horizontal faces of boards along X, X for boards along Y, X or Y for
  vertical posts. Select each group in Edit Mode, face select mode, after deselecting all: with UV Sync Selection on
  (the 5.x default) `uv.select_all` selects the whole mesh. `audit(directional=True)` reports long islands along V.
- Text and decals: mark their faces with the boolean face attribute `uv_text`: never mirrored (`uv.select_by_winding`
  finds flipped islands, 5.2), the letters' up on +V (world +Z: `align_rotation` GEOMETRY Z; or the face vector
  `uv_text_up` for text up a pillar, round a pipe or flat). `audit(text=True)` checks those faces; they skip the grain.
- Keep packing rotation off (`layout` and `pack` default): Blender 5.2.2 turned 6 of 10 boards with `CARDINAL` and with
  `AXIS_ALIGNED`. `CARDINAL` only for non-directional strips and lightmaps, `ANY` only for organic non-directional
  islands. A mixed atlas is laid out with `directional=True`; audit directional and other props in separate runs.

## 6. Texel density

Texels per metre of surface: `px_per_m = map_px x sqrt(UV area / surface area in m2)`. Keep it the same on neighbouring
objects, or the odd one out looks blurry or oversharp.

- Targets: about 1024 px/m for first-person games, 512 for third-person (Maxon, checked 2026-10-17,
  https://help.maxon.net/c4d/en-us/Content/html/Texel_Density.html). In VR a headset resolves about 1150 / d px/m at
  nearest viewing distance d: T2048 (< 0.75 m, handheld), T1024 (0.75-1.5 m), T512 (1.5-3 m), T256 (3-6 m),
  T128 (6-12 m), T64 (> 12 m); walls players walk up to get a detail map instead (`texel-density.md`).
- Tolerance: tiling, trim and shared materials within 10% (0.9-1.1x) of the target; unique and atlas textures within
  0.8-1.25x of their class; inside a piece `texel_cv` <= 0.15. The audit checks the mean and every unmarked island.
- Blender has no texel-density tool (5.2; Average Islands Scale only evens islands): `ua.layout(..., px_per_m=...)`,
  or on a non-square trim sheet, which `layout` refuses, `ua.set_texel_density(..., pack_after=False)` (workflows).
- Tiling: Cube Projection maps `cube_size` metres to one UV tile in object space, so `cube_size = map_px / px_per_m`
  (2048 / 512 = 4.0, verified on 5.2.2). An unapplied scale of 2 halves the density.
- Lower it on purpose only where nobody looks (undersides, backs against walls), each island internally even, and
  mark those faces with the boolean face attribute `uv_low_density` (`uv_low_density_<UV map name>` for one map): the
  audit leaves them out of the mean and spread, `layout` keeps their relative size. Map size: `texel-density.md`.

## 7. Packing and padding

| Map size | Gap between islands (`map_px / 64`) | Gap to the tile edge (`map_px / 128`, half the gap) |
|---|---|---|
| 512 | 8 px | 4 px |
| 1024 | 16 px | 8 px |
| 2048 | 32 px | 16 px |

Mips and a platform override that caps the map shrink the gap in pixels. Polycount gives 4, 8 and 16 px of padding
round each shell at 512, 1024 and 2048 and twice that between shells (http://wiki.polycount.com/wiki/Edge_padding):
`map_px / 64` is the minimum gap, the `layout` and `pack` default, pixel-exact. Bake dilation fills half the gap
(Blender's 16 px: maps up to 2048). A shared texture: `ua.layout(objs, ..., together=True)`, then `--shared`.
A bake atlas for one material of meshes that carry others (fabric baked, wood not): add `material="M_Fabric"`,
so the other faces keep their UVs and take no atlas space, and `max_island_m=0.8` when a long shell (a sofa's
back) caps the scale; then `--shared --material M_Fabric`.

## 8. Stacking, mirroring and overlap

| Layer | May islands overlap? |
|---|---|
| Tiling and trim UV0 | yes, freely |
| Unique UV0, painted, no bake | stack identical parts and mirrored halves exactly; mirrored islands print text backwards |
| Unique UV0 that takes a baked normal map or AO | stack, but at bake time one copy inside 0-1 and the others exactly +1 in U (`layout(bake=True)`); unstack parts that are occluded differently |
| Lightmap UV | never |

- Stack by face correspondence, before triangulating: `ua.stack_faces(ob, src_faces, copy_faces)` copies UVs corner by
  corner onto a duplicated part and refuses a mismatch; or `uv.copy` / `uv.paste` one island at a time.
- Mirrored islands shade correctly with a normal map baked in the mirrored layout in engines that store the tangent
  sign per vertex and use MikkTSpace (engine notes). Never flip, rotate or move islands after the bake.
- A Mirror with nothing topology-changing below it stays live through seams and unwrap, so its halves share UVs
  (Merge on: one island folded on the axis); `apply_stack(ob, keep_mirror=False)` applies it before `layout`, whose
  `bake=True` moves the flipped half +1 U. First in the stack (above the Bevel) it is applied in step 1: unique
  halves. Apply Mirror and Array before a lightmap UV. Baking: [references](references/baking-and-normal-maps.md).

## 9. Lightmap UV

Engines bake lightmaps from a dedicated UV map, normally the second (channel and generator: engine notes). Lightmap
resolution and bake settings belong to the engine's lighting setup (`vrchat-lighting-and-baking` for Unity / VRChat).

- Inside 0-1, no overlaps, charts cut at hard edges and bends over 88 deg, at least 2 texels between charts and 1
  texel to the tile edge: bilinear filtering reads neighbouring texels, so closer charts bleed.
- Texel scale: `footprint_px = texels_per_m x sqrt(surface area m2 / b) x lightmap scale x LOD scale` px per UV unit;
  b = the bounding box of all the UV2 charts together as a share of the tile. The engine decides what it packs and
  each LOD's scale (Unity: that box, its cost blind to the layout, 0.5^n per `_LOD<n>`; Bakery: by area, engine
  notes). `ua.lightmap_footprint(ob, ...)` plans with b = 0.85; `lightmapper="bakery"` (also `pack_lightmap`, audit).
- Pack the charts to fill their box, at any aspect ratio: empty space inside it costs texels, effective density
  `texels_per_m x sqrt(charts' area / box area)`; the audit notes a fill under 0.5 at footprints of 64 px or more.
- `ua.pack_lightmap(objs, texels_per_m, scale)` packs 2 px gaps for b = 1, the smallest texel scale (each LOD for its
  own). A UV2 too small for 2-texel gaps is packed and checked for 64 px, with a note: a Free prop (a Free-sized PROP
  or FOL piece) is probe-lit, LODs follow their piece, other pieces need a higher lightmap scale (the lighting skill
  decides). Audit with `ua.audit(ob, texels_per_m=..., lightmap_scale=...)`: gaps, bends, bounds, fill, density.
- Unwrap it seam-based (`ua.seams_from_hard_edges(objs)`, then `uv.unwrap(method="ANGLE_BASED", margin=0.001)` on
  the second map) or copy a unique UV0 with its stacks and mirrors pulled apart: few, large, straight charts. Smart UV
  Project only with an audit after it (at `island_margin=0.001` it joined a door wall across four 90 deg corners).
  Turn the engine's automatic lightmap UV generator off for these meshes.

## 10. Symptom, cause, fix

| Symptom | Cause | Fix |
|---|---|---|
| Checker squares stretched into rectangles or diamonds | too few seams, or a projection on a curved form | seams on the curve's back line, `unwrap(method="ANGLE_BASED")`, audit |
| Blurry here, crisp there | uneven texel density inside or between objects | `layout(px_per_m=...)`, the same px/m for neighbours |
| A line across a flat surface | seam in view, or seam pixels not padded | move the seam to a hard edge or hidden side; pad the gap (section 7) |
| Normal-map line along a hard edge, light leaking at corners | hard edge without a UV seam, or a bake without a cage | a seam on every hard edge (`baking=True` audit), bake with an averaged cage |
| X-shaped shading blotches, seams only in the engine | baker and engine triangulated or computed tangents differently | triangulate before baking and export that mesh; MikkTSpace tangents in the engine |
| Coloured fringe at island edges from a distance | gaps under `map_px / 64`, or a platform override that caps the map | `map_px / 64` gaps at the shipped size; bake dilation that fills them |
| Baked AO or normals garbled where parts overlap | stacked or mirrored copies left inside 0-1 during the bake | `layout(bake=True)`; bake the whole mesh |
| Grain along V on posts, lids or board edges; grain turned, stacks apart or density changed after a pack | one align axis for every face; a plain pack with rotation on, or after stacking or setting density | per face group, the axis across the grain (section 5); one `layout` call |
| Islands waste the map: audit `coverage` under about 0.5 | gaps above the `map_px / 64` rule, unstraightened strips, scattered tiny islands, rotation off on a non-directional texture | default gap, straighten, merge tiny islands, `rotate_method="CARDINAL"` when nothing has a direction; packed at `map_px / 64`, pieces measured 0.52-0.60 |
| Lightmap shadows on the wrong surface, specks or smears at chart edges | overlapping UV2, gaps under 2 texels, or a chart round a corner | unstack; `pack_lightmap`; a seam-based UV2 unwrap (section 9) |

## Script

`scripts/uv_audit.py` (Blender 4.1+, tested on 5.2.2; no add-ons); purposes, report fields, every issue, accuracy and
side effects: [references/uv-audit.md](references/uv-audit.md).

```python
import sys; sys.path.insert(0, r"<skill>/scripts")
import uv_audit as ua
st = ua.apply_stack(ob)                                            # from the top; Triangulate off until after layout
if st["hard_surface"]: ua.seams_by_angle([ob])                     # route A / B: seams by angle, never re-shaded
ua.seams_from_hard_edges(objs)                                     # a seam on every hard edge
ua.apply_stack(ob, keep_mirror=False)                              # a Mirror kept live, just before the layout
ua.layout(objs, map_px=2048, px_per_m=512, bake=True)              # UV0: density, one pack, fits, +1 U copies
ua.audit_selected(purpose="unique", map_px=2048, px_per_m=512, baking=True, directional=True)
ua.pack_lightmap(objs, texels_per_m=20)                            # UV2: 2 texels at any scale; LODs at 0.5^n
ua.audit_selected(texels_per_m=20)                                 # UV2 at its measured footprint
```

Command line (exit 1 when anything needs a look, 2 for a request it cannot audit; every flag in the manual):
`blender -b --factory-startup --python-exit-code 1 scene.blend --python uv_audit.py -- --objects "KIT_*" --map 1024 --td 512`
