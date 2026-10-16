---
name: uv-unwrapping
description: How to UV unwrap models properly in Blender for real-time 3D (games, VR, any engine) - choosing tiling, trim-sheet, unique or lightmap UVs, seam placement, hard edges and seams for normal-map baking, distortion, texel density in px/m, straightening and orienting islands, padding in pixels that survives mipmaps, stacking and mirroring, lightmap UV rules, and Blender's UV operators from Python, with an audit script that measures all of it. Use when unwrapping or reviewing UVs, when textures look stretched, blurry, mismatched in density or backwards, when seams or normal-map lines show, when bakes bleed or pick up the wrong parts, when islands waste space, or when choosing seams, padding, map size or texel density; to automate unwrapping with RizomUV see rizomuv-uv-pipeline; engine specifics (Unity) are in this skill's engine notes, and lightmap bake settings belong to the engine's lighting skill (vrchat-lighting-and-baking for Unity / VRChat).
---

# UV unwrapping

Decide what each surface's UVs are for before cutting a single seam: the purpose sets the seams, the density, the
padding and whether islands may overlap. Then unwrap, check with numbers rather than by eye, and pack with padding
given in pixels. `scripts/uv_audit.py` measures every rule below on a real mesh. Everything here is engine-neutral;
what a particular engine does with the UVs (channels, tangents, lightmap generators) is in
[references/engine-notes.md](references/engine-notes.md).

## 1. Pick the UV strategy per surface

| Surface | Strategy | UVs |
|---|---|---|
| Walls, floors, terrain, large plain surfaces | **tiling material** | world scale, may run far outside 0-1; Cube Projection with `cube_size` = metres per tile (section 6) |
| Mouldings, frames, pipes, trims, kit edges | **trim sheet** | straightened strips laid on the trim's rows, U free to run along the strip ([references/workflows.md](references/workflows.md)) |
| Props and hero pieces with their own texture or a bake | **unique unwrap** | the full process in section 2, packed into 0-1 |
| Every mesh that receives baked lightmaps | **lightmap UV**, usually the second UV map | its own rules: no overlap, inside 0-1, 2+ texels between charts (section 9) |

One mesh can mix them (tiling walls with a trim-sheet cornice). Repeated props share one mesh and one set of UVs.

## 2. The order of work for a unique unwrap

1. **Apply scale** (`Ctrl A` > Scale, or `bpy.ops.object.transform_apply(location=False, rotation=False,
   scale=True)`; the operator's defaults apply location and rotation too): texel density is per metre of the
   placed object, and projections work in object space.
2. **Set hard edges**: `bpy.ops.object.shade_smooth_by_angle(angle=math.radians(30))` smooths the faces and keeps
   edges above the angle hard (Blender 4.1+; a flat-shaded mesh has every edge hard). Mechanical parts usually
   need a hard edge wherever the surface turns more than 30-45 deg; check bevels are caught.
3. **Mark seams** (section 3). For a baked piece start with `ua.seams_from_hard_edges([ob])`, then add the seams
   no angle finds: one down the least-seen side of every tube, undersides, material borders.
4. **Unwrap with an explicit method**: `bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.0)`. An unwrap without
   `method` silently reuses the previous call's method (verified on 5.2.2). `MINIMUM_STRETCH` with
   `iterations=100` or more gives evener density inside islands; `CONFORMAL` spreads density unevenly on curves.
5. **Check distortion** (section 4): `uv_audit` numbers, then the UV editor's Display Stretch and a checker map.
   Add or move seams and unwrap again until it passes.
6. **Straighten and orient** (section 5): rectangular strips straight, islands upright, grain consistent.
7. **Scale** (section 6): even density with Average Islands Scale, then deliberately larger for close-up faces and
   smaller for hidden ones, or an exact density with `uv_audit.set_texel_density`.
8. **Stack** identical parts and mirrored halves where the texture allows it (section 8).
9. **Pack** with padding in pixels (section 7).
10. **Audit**: `ua.audit_selected(map_px=..., pad_px=..., px_per_m=..., baking=True)` must print no issues.
11. **Add the lightmap UV** as the second UV map if the mesh is lightmapped (section 9).

Choosing a tool: Blender's own tools do all of this. If RizomUV is installed, `rizomuv-uv-pipeline` automates the
extra seams, unwrap, distortion check, texel density and packing for whole batches and grades the result. It does
not straighten or stack islands, and it still needs the structural seams of step 3 on generated pieces.

## 3. Seams

| Put seams | Why |
|---|---|
| On every hard edge (split normals) of a piece that takes a baked normal map | otherwise the bake draws a line along the edge; a seam on a hard edge costs no extra vertices (both split there anyway) |
| On hard edges and natural creases of hard-surface parts | the texture changes there anyway, and islands come out flat |
| Where nobody looks: the back line of a cylinder, undersides, the inside of handles, behind other parts | seams show as texture and lighting discontinuities |
| On material boundaries | the mesh is split there already, so the seam is free |
| Around cylinder caps at the rim, and one line down the least-seen side of the tube | cap and tube flatten without stretch; the tube becomes one straight strip |
| Organic and symmetric forms: few, hidden; along the mirror axis to share texture space, or offset from the centre of a face | fewer visible breaks; an offset mirror seam keeps the lighting seam off the centre line |

Seams do not need to form closed loops: a cut only has to relieve the area that would stretch. Too many seams cost
vertices (engines split a vertex wherever UVs or normals differ), visible breaks and wasted gutter space; too few
cost stretch. There is no correct number: stop adding them when distortion passes.

A closed tube never opens by itself: angle-based seams cut its caps off, and the tube unwraps folded onto itself
until one seam runs along it (tested: angular p95 74 without, 1.00 with).

Tools: `bpy.ops.mesh.mark_seam()` on a selection, `ua.seams_from_hard_edges(objs)` for every hard edge, and
`uv.seams_from_islands()` to turn a Smart UV Project result into seams for a cleaner unwrap. Details and every
operator's parameters: [references/blender-uv-tools.md](references/blender-uv-tools.md).

## 4. Distortion

- **Angle distortion** (shape): squares on a checker become rectangles or diamonds. **Area distortion**
  (density): one part of an island gets more texels than another.
- Measure, do not eyeball: `uv_audit` reports angular p95 (1.00 = shapes kept) and area p95 (log2 of the density
  change inside an island). This repo's gate, measured on real props: **angular p95 <= 1.15 and area p95 <= 0.20**
  (measured with the `rizomuv-uv-pipeline` skill's grader). No engine or vendor publishes a number for texture
  UVs; engine lightmap unwrappers use comparable tolerances (engine notes).
- In Blender: UV editor Overlays > Display Stretch (`SpaceUVEditor.show_stretch`, `display_stretch_type`
  `ANGLE` or `AREA`; blue = low, red = high), and a generated `UV_GRID` or `COLOR_GRID` image on the material.
  Area mode also lights up islands you scaled on purpose: read it within an island.
- Fix with seams first. `uv.minimize_stretch` can make angles worse (measured: sphere 1.06 to 1.23); keep its result
  only if the audit improves.

## 5. Straighten and orient

- Straighten every island that is a strip of quads (trims, belts, frames, pipes, stairs): it packs tighter, tiles
  or trims cleanly, and its edges follow the pixel grid instead of stair-stepping. Blender: unwrap or square one
  quad, make it active, `bpy.ops.uv.follow_active_quads(mode="LENGTH_AVERAGE")`. Blender has no one-click
  "rectify island"; add-ons do (TexTools Rectify, UniV, UV Squares).
- Orient islands upright and the same way for directional textures (wood grain, fabric, brushed metal, text, decals):
  `uv.align_rotation(method="GEOMETRY", axis="Z")`, then pack with `rotate_method="CARDINAL"` (90 deg steps only).
  Free rotation (`ANY`) is only for organic, non-directional islands.
- Flipped (mirrored) islands print text and decals backwards: `uv.select_by_winding(winding="NEGATIVE")` finds them
  (5.2), `uv_audit` counts them.

## 6. Texel density

Texel density is texture pixels per metre of surface: `px_per_m = map_px x sqrt(UV area / surface area in m2)`.
Keep it consistent between neighbouring objects, or the odd one out looks blurry or oversharp.

| Target | px/m | Source |
|---|---|---|
| First-person games | 1024 (10.24 px/cm) | industry convention, https://help.maxon.net/c4d/en-us/Content/html/Texel_Density.html |
| Third-person games | 512 (5.12 px/cm) | same |
| VR: what a headset resolves at distance d | about 1150 / d (770 at 1.5 m, 380 at 3 m) | `references/texel-density.md`: classes T512 / T256 / T128 / T64 px/m by nearest viewing distance (0-3 / 3-6 / 6-12 / > 12 m) |

- **Blender has no texel-density tool** (4.2 to 5.2). Average Islands Scale (`uv.average_islands_scale()`) only
  evens islands out relative to each other. Set an absolute density with `uv_audit.set_texel_density(objs,
  px_per_m, map_px)` (scales islands, then packs without rescaling; islands that no longer fit are reported), or an
  add-on such as Texel Density Checker.
- World-scale tiling UVs: Cube Projection maps `cube_size` metres to one UV tile in object space, so
  `cube_size = map_px / px_per_m` gives an exact density (2048 / 512 = 4.0; verified on 5.2.2). Apply scale first:
  an unapplied scale of 2 halves the density.
- Vary it on purpose: hidden faces (undersides, backs against walls) smaller, faces seen up close larger, but keep
  each island internally even.
- Map size for a unique texture: `next_pow2(px_per_m x sqrt(area_m2 / coverage))` with coverage about 0.65, capped
  by the platform (`references/texel-density.md`).

## 7. Packing and padding

Padding is the empty gap between islands. Each mip level halves it, so it has to be big enough at the smallest mip
anyone sees, and on the smallest platform override (a 2048 texture capped at 1024 for a mobile build halves every
gap).

| Map size | Gap between islands (Polycount) | Minimum for pieces only seen close | Gap to the tile edge |
|---|---|---|---|
| 512 | 8 px | 4 px | half the gap |
| 1024 | 16 px | 8 px | half the gap |
| 2048 | 32 px | 16 px | half the gap |
| 4096 | 64 px | 32 px | half the gap |

The Polycount column (https://wiki.polycount.com/wiki/Edge_padding) keeps islands a pixel apart down to the 64 px
mip; the minimum column down to the 128 px mip. Bake dilation (Blender's bake margin, default 16 px) must at least
fill the gap's half on each side.

Blender: `margin_method="FRACTION"` is the only pixel-exact margin. `margin` is the gap to the tile edge and half the
gap between islands (measured on 5.2.2), so **`margin = gap_px / (2 x map_px)`**. `uv_audit.pack(objs, map_px,
pad_px)` does this:

```python
bpy.ops.uv.pack_islands(margin_method="FRACTION", margin=16 / (2 * 1024), rotate=True, rotate_method="CARDINAL",
                        scale=True, shape_method="CONCAVE")
```

- `scale=False` keeps island sizes (after setting a texel density).
- `rotate_method="CARDINAL"` or `"AXIS_ALIGNED"` for straightened and directional islands; `"ANY"` only for organic
  pieces.
- `shape_method="CONCAVE"` nests islands tightest; `"AABB"` is fastest and keeps strips in tidy rows.
- Pack each object on its own unless they share a texture: several objects in Edit Mode pack into one shared tile.
- Coverage: no source sets a target. Low coverage on a unique map usually means unstraightened strips, free-floating
  tiny islands or huge margins.

## 8. Stacking, mirroring and overlap

| Layer | May islands overlap? |
|---|---|
| Tiling and trim UV0 | yes, freely |
| Unique UV0, painted, no bake | stack identical parts and mirrored halves to save space; mirrored islands print text backwards |
| Unique UV0 that takes a baked normal map or AO | stack, but keep **one copy inside 0-1 and move the others exactly +1 in U before baking** (Cycles skipped islands at +1 U and baked the copy inside 0-1, verified on 5.2.2); offsets of whole tiles look the same with the texture on Repeat (the usual engine default). Unstack parts that are occluded differently: stacked AO is one shadow for all copies |
| Lightmap UV | **never**: lightmappers require no overlap, inside 0-1 |

- Mirrored islands shade correctly with a normal map baked in the mirrored layout, in any engine that stores the
  tangent's handedness per vertex and uses MikkTSpace like Blender (engine notes). Do not flip, rotate or move
  islands after the bake.
- The Mirror modifier stacks the mirrored half on the original's UVs by default. Its U Offset (`offset_u = 1.0`)
  moves the copy out of 0-1 for baking; Mirror U (`use_mirror_u`) flips the copy to the other side of the tile
  instead of stacking it. Apply the modifier before making a lightmap UV: every modifier copy reuses its source's
  UVs.
- Baking rules (hard edges, cage, triangulation, tangent space): [references/baking-and-normal-maps.md](references/baking-and-normal-maps.md).

## 9. Lightmap UV

Engines bake lightmaps from a dedicated UV channel; in Blender that is normally the second UV map in the list.
Which channel a given engine reads, and its generator's settings: engine notes.

- Inside 0-1, no overlaps, charts at least **2 texels apart at the final lightmap resolution** (bilinear filtering
  reads neighbouring texels, so closer charts bleed). Size that gap for the smallest footprint the mesh gets in the
  atlas, not for 1024.
- Few, large charts, cut at hard angles (lightmap unwrappers typically cut near 88 deg); even relative area unless a
  part deserves more lightmap detail; straight, axis-aligned chart edges let a lightmapper's seam stitching hide
  the seam.
- Start from a copy of a unique UV0 with every stack and mirror pulled apart, or a seam-based unwrap or Smart UV
  Project on the second map. `uv.lightmap_pack` makes one chart per face: only for very simple meshes.
- An engine's automatic lightmap UV generator overwrites the channel: turn it off for meshes with an authored
  lightmap UV. When you do let it generate, give it margins computed for the real lightmap resolution, not a fixed
  pixel count that assumes a whole map per mesh.

Footprint sizing and bake settings belong to the engine's lighting setup (`vrchat-lighting-and-baking` for Unity /
VRChat). `uv_audit.pack` (with `layer=1`) packs the second UV layer here, for the footprint the mesh will get.

## 10. Symptom, cause, fix

| Symptom | Cause | Fix |
|---|---|---|
| Checker squares stretched into rectangles or diamonds | too few seams, or a projection on a curved form | seams on the curve's back line, `unwrap(method="ANGLE_BASED")`; audit angular p95 |
| Blurry here, crisp there | uneven texel density inside or between objects | Average Islands Scale, `set_texel_density`, same px/m for neighbours |
| A line across a flat surface | seam in view, or seam pixels not padded | move the seam to a hard edge or hidden side; pad the gap (section 7) |
| Normal-map line along a hard edge, light leaking at corners | hard edge without a UV seam, or a bake without a cage | a seam on every hard edge (`audit(baking=True)`), bake with an averaged cage |
| X-shaped shading blotches, seams only in the engine | baker and engine triangulated or computed tangents differently | triangulate before baking and export that mesh; import normals in the engine and use MikkTSpace tangents |
| Coloured fringe at island edges from a distance | gaps too small for the mips or the platform override | Polycount padding column; bake dilation to fill gaps |
| Baked AO or normals garbled where parts overlap | stacked or mirrored copies left inside 0-1 during the bake | move copies +1 U; bake the whole mesh |
| Text or decals read backwards | flipped island | `uv.select_by_winding`, flip it back before texturing |
| Lightmap shadows on the wrong surface, specks at chart edges | lightmap UV overlapping, or charts under 2 texels apart | unstack, more padding at the real footprint, or computed margins in the engine's generator |
| Islands waste half the map | curved strips not straightened, free rotation, tiny islands everywhere | straighten, pack `CARDINAL`, merge tiny islands into neighbours with fewer seams |
| Modifier copies (Mirror, Array) share UVs or overlap in the lightmap UV | modifiers reuse the source UVs | Mirror's UV offsets for UV0; apply and unwrap uniquely for the lightmap UV |
| Re-running a script unwraps differently | `uv.unwrap` without `method` inherits the last one | always pass `method` |

## Script

`scripts/uv_audit.py` (Blender, tested on 5.2.2; no add-ons). `audit` measures the evaluated mesh in world space
and changes nothing; `seams_from_hard_edges`, `set_texel_density` and `pack` change seams or one UV layer:

```python
import sys; sys.path.insert(0, r"<skill>/scripts")
import uv_audit as ua
ua.seams_from_hard_edges(objs)                                         # a seam on every hard edge
ua.audit_selected(map_px=1024, pad_px=16, px_per_m=512, baking=True)   # UV0 of a baked prop
ua.audit_selected(layer=1, map_px=128, pad_px=4, lightmap=True)        # its lightmap UV
ua.set_texel_density(objs, px_per_m=512, map_px=2048, pad_px=32)      # exact density, then pack unscaled
ua.pack(objs, map_px=1024, pad_px=16)                                  # pixel-exact padding
```

One line per object: `OK` or `CHECK`, islands, coverage, angular and area p95, px/m, then each issue: stretch,
uneven density, folded faces (always a fault; whole mirrored islands are reported apart), zero-area UVs, UVs
outside 0-1 (lightmaps), partial overlaps (stacked copies are allowed in UV0, not in a lightmap), gaps and edge
margin below the padding, density off target or uneven between islands, hard edges not on seams (`baking=True`),
more than 8 UV maps (the most an engine like Unity keeps). Command line:
`blender -b --factory-startup scene.blend --python uv_audit.py -- --objects "KIT_*" --map 1024 --pad 16 [--layer 1 --lightmap]`.

Facts with a shelf life (Blender operator names, parameters and defaults; engine lightmap settings; add-on
availability) carry their source and version in the references. Re-check operator parameters in a new Blender with
`bpy.ops.uv.<name>.get_rna_type().properties`.
