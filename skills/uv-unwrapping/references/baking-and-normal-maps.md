# UVs for baked normal maps and AO

What the UV layout must do so a bake from a high-poly (or a Cycles bake of any map) comes out clean in the engine.
What a specific engine does (tangents, normal map convention, wrap mode) is in `engine-notes.md`.
Sources are inline; "verified" means tested in Blender 5.2.2 on 10 Oct 2026. Polycount's wiki answers on http only
(its https host refused connections, checked 2026-10-17).

## Contents

- Hard edges and seams
- Tangent space and triangulation
- Cage and bake settings
- Padding and dilation
- Stacked and mirrored parts
- After the bake

## Hard edges and seams

| Rule | Source |
|---|---|
| **Every hard edge (split normals) must be a UV seam.** If it is not, both faces bake onto the same texels along the edge and a line appears | Polycount, http://wiki.polycount.com/wiki/Normal_map ; Marmoset, https://marmoset.co/posts/toolbag-baking-tutorial/ |
| The reverse is not required: a UV seam may be smooth | Joe Wilson (EarthQuake), "Making sense of hard edges, UVs, normal maps and vertex counts", Polycount, Oct 2012 (read through web.archive.org) |
| Hardening UV-border edges that turn about 90 deg or more is still worth it on hard surface: weaker gradients in the normal map, better BC compression, fewer smoothing errors at small mips and on LODs | same thread; Marmoset tutorial |
| A hard edge on a UV seam costs no extra vertices: the vertex is split once for both | same thread; engines split vertices wherever normals, UVs or colours differ (Unity's wording: `engine-notes.md`) |

In Blender 4.1+ sharpness is per edge (the `sharp_edge` attribute:
https://developer.blender.org/docs/release_notes/4.1/python_api/), set with `bpy.ops.object.shade_smooth_by_angle`,
`bpy.ops.mesh.set_sharpness_by_angle` or the Smooth by Angle modifier
(https://developer.blender.org/docs/release_notes/4.1/modeling/). In order:

1. Apply the modifier stack from the top down to and including the last topology-changing modifier, never a lower
   one alone: `uv_audit.apply_stack(ob)` (SKILL.md section 2). With a Bevel live, the hard edges sit on its rails
   while the seams stay on the base edges; applied alone under a Smooth by Angle, its chamfers are re-sharpened.
2. A plain mesh: shade smooth by angle (flat-shaded faces make every edge hard), unless its sharp edges were set on
   purpose; through the mesh, `ob.data.set_sharp_from_angle(angle=math.radians(30))` then `ob.data.shade_smooth()`,
   since the operator re-shades every selected object. A hard-surface stack (a Weighted Normal, a Bevel with Harden
   Normals, or custom normals in the mesh):
   never shade it by angle again (it moved the normals 30-34 deg on an applied Harden Normals piece); place its seams
   by angle, `uv_audit.seams_by_angle(objs)`, which does what `mesh.edges_select_sharp(sharpness=math.radians(30))`
   then `mesh.mark_seam()` do, and keeps the stack's own sharp edges.
3. Every hard edge a seam: `uv_audit.seams_from_hard_edges(objs)`. It reads the split normals of the evaluated mesh
   when its topology matches the mesh's own, so a Smooth by Angle modifier or a live Weighted Normal counts; an edge
   is hard when its corner normals are more than 0.5 deg apart (smaller splits are custom-normal rounding).
4. To RizomUV after `apply_stack`: `modifiers='ignore'`, never `'apply'`, which bakes the viewport mesh and drops
   the Triangulate and Weighted Normal (12.59 deg off after export, measured; `rizomuv-uv-pipeline`).

`edges_select_sharp` selects edges by the angle between their faces, not by the edges marked sharp or the split
normals: it is the seam-by-angle tool on a stack, never a way to find hard edges (on a bevelled cylinder at 45 deg it
selected nothing, while the cylinder's hard edges were marked; 5.2.2). The reverse, every island border made sharp:
`uv.seams_from_islands(mark_sharp=True)`, right only for a plain hard-surface mesh (on a stack it changes the
designed normals). `uv_audit.audit(..., baking=True)` counts hard edges that are not seams on the evaluated mesh.

## Tangent space and triangulation

- Baker and engine must use the same tangent basis. Blender bakes tangent-space normal maps in MikkTSpace with a Y+
  (OpenGL-style) green channel; use an engine importer that computes MikkTSpace tangents, and flip green only if the
  engine expects Y- (DirectX-style). Per engine: `engine-notes.md`.
- Import the exported normals in the engine rather than recalculating them, so the hard edges you baked with survive.
- **Triangulate before baking and export the same triangles.** A quad split differently in the engine gives X-shaped
  shading errors, "a type of tangent space mismatch" (Marmoset tutorial). Use one Triangulate modifier (Minimum
  Vertices 4, Keep Normals on) for both: off in the viewport only while the UVs are laid out, then on for the bake
  and the export. A piece without one gets it directly above any Weighted Normal, never below it
  (`apply_stack(ob, add_triangulate=True)`): below it moved the normals 7.86 deg (12.55 with Keep Normals off), and
  Keep Normals off above it 0.74-12.59 deg.
- Mirrored islands are fine in an engine that stores the bitangent sign per vertex (MikkTSpace engines do:
  `engine-notes.md`), so a normal map baked with the mirror in place shades correctly. Flat normal is 128,128,255;
  127 shows a mirror seam (http://wiki.polycount.com/wiki/Normal_map).

## Cage and bake settings

- Bake with a smoothed (averaged) cage: it ignores the low poly's split normals for the projection direction, while an
  unsmoothed cage "results in gaps or seams at hard edge borders" (Marmoset tutorial). Without a cage the rays follow
  the split vertex normals and a seam shows along those edges; Adobe's fix is a cage that controls the ray direction,
  or merged normals (https://experienceleague.adobe.com/en/docs/substance-3d/bakers/common-issues/seam-visible-on-every-face).
- Blender: Bake > Selected to Active with a Cage object, or Extrusion; build the cage from the low-poly without
  split normals (https://docs.blender.org/manual/en/latest/render/cycles/baking.html).
- Remaining thin seams after a clean bake come from island borders that cut pixels at an angle and from low
  resolution: raise the resolution, straighten borders to the pixel grid
  (https://experienceleague.adobe.com/en/docs/substance-3d/bakers/common-issues/aliasing-on-uv-seams).

## Padding and dilation

- The bake writes colour past each island's border into the gap (Blender: `scene.render.bake.margin`, default
  16 px, `margin_type` default `ADJACENT_FACES`, verified on 5.2.2;
  https://docs.blender.org/api/current/bpy.types.BakeSettings.html). Without it, mips and filtering pull the
  background colour into the seams.
- Dilation only fills the gap the layout left: lay out with the gaps from SKILL.md section 7 first (`map_px / 64`),
  then bake with a margin of at least half the gap: the default 16 px covers maps up to 2048.

## Stacked and mirrored parts

- Stack identical parts and mirrored halves on one set of texels to save space; duplicates should be real copies
  so the UVs overlap exactly (http://wiki.polycount.com/wiki/Normal_map).
- **Only one copy may be inside 0-1 at bake time.** Move the others exactly one UV unit (any whole number) out:
  "Only one copy of the forward-facing UVs should remain in the 0-1 UV square at baking time"
  (http://wiki.polycount.com/wiki/Texture_Baking). Verified: a Cycles bake into a plain (non-UDIM) image wrote
  nothing for an island at +1 U and wrote the same island when it sat inside 0-1. A UDIM image would bake tile
  1002, so bake into a plain image. `uv_audit.layout(..., bake=True)` makes this move after its one pack, keeping
  an unmirrored copy inside 0-1; any pack afterwards would bring the copies back. `audit(..., baking=True)` reports
  stacked pairs left inside 0-1.
- Whole-unit offsets sample the same texels in the engine when the texture wraps (Repeat); Clamp would smear them.
- Blender's Mirror modifier stacks the mirrored half by default; its U Offset (`offset_u`, "Amount to shift mirrored
  UVs", any value) moves that copy: set it to 1 for a whole-tile copy
  (https://docs.blender.org/manual/en/latest/modeling/modifiers/generate/mirror.html). Applied with Merge on
  (the default), the two halves join on the axis into one island folded onto itself: `layout(..., bake=True)` moves
  the flipped half's face corners +1 U.
- Bake the **whole** mesh, mirrored half included; baking only one half bends the normals at the open edge
  (http://wiki.polycount.com/wiki/Normal_Map_Modeling).
- A mirror seam across the middle of a continuous surface usually shows as a lighting seam. Offset the mirror line
  to a less visible place, or map the centre strip uniquely (same page).
- AO on stacked parts is one shadow for every copy: unstack parts that are occluded differently.

## After the bake

- Do not move, rotate, mirror or rescale islands: "rotating or mirroring UVs after baking will cause the normal map
  not to match the tangent basis anymore" (http://wiki.polycount.com/wiki/Texture_Baking). Any UV change means a
  re-bake.
- The lightmap UV2 is separate: unstack everything there (SKILL.md section 9).
