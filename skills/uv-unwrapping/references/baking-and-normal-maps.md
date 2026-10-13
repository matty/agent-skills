# UVs for baked normal maps and AO

What the UV layout must do so a bake from a high-poly (or a Cycles bake of any map) comes out clean in the engine. What Unity specifically does (tangents, normal map convention, wrap
mode) is collected in `engine-notes.md`.
Sources are inline; "verified" means tested in Blender 5.2.2 on 10 Oct 2026.

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
| **Every hard edge (split normals) must be a UV seam.** If it is not, both faces bake onto the same texels along the edge and a line appears | Polycount, https://wiki.polycount.com/wiki/Normal_map ; Marmoset, https://marmoset.co/posts/toolbag-baking-tutorial/ |
| The reverse is not required: a UV seam may be smooth | Joe Wilson (EarthQuake), "Making sense of hard edges, UVs, normal maps and vertex counts", Polycount, Oct 2012 (read through web.archive.org) |
| Hardening UV-border edges that turn about 90 deg or more is still worth it on hard surface: weaker gradients in the normal map, better BC compression, fewer smoothing errors at small mips and on LODs | same thread; Marmoset tutorial |
| A hard edge on a UV seam costs no extra vertices: the vertex is split once for both | same thread; engines split vertices wherever normals, UVs or colours differ (Unity's wording: `engine-notes.md`) |

In Blender 4.1+ sharpness is per edge (`sharp_edge` attribute), set with `bpy.ops.object.shade_smooth_by_angle`,
`bpy.ops.mesh.set_sharpness_by_angle` or the Smooth by Angle modifier
(https://developer.blender.org/docs/release_notes/4.1/modeling/). Flat-shaded faces make every edge hard, so shade
smooth by angle first. To seam every hard edge: `uv_audit.seams_from_hard_edges(objs)` (reads the split normals
themselves). Do not rely on `mesh.edges_select_sharp(sharpness=...)`: it selects by face angle, not by the edges
marked sharp, and on a bevelled cylinder at 45 deg it selected nothing (tested on 5.2.2). The reverse, every island
border made sharp: `uv.seams_from_islands(mark_sharp=True)`, right only for hard surface.
`uv_audit.audit(..., baking=True)` counts hard edges that are not seams on the evaluated mesh, so sharpness from
modifiers is included.

## Tangent space and triangulation

- Baker and engine must use the same tangent basis. Blender bakes tangent-space normal maps in MikkTSpace with a Y+
  (OpenGL-style) green channel; use an engine importer that computes MikkTSpace tangents, and flip green only if the
  engine expects Y- (DirectX-style). Unity matches Blender: `engine-notes.md`.
- Import the exported normals in the engine rather than recalculating them, so the hard edges you baked with survive.
- **Triangulate before baking and export the same triangles.** A quad split differently in the engine gives X-shaped
  shading errors, "a type of tangent space mismatch" (Marmoset tutorial). Apply a Triangulate modifier before the
  bake and keep it for export.
- Mirrored islands are fine in an engine that stores the bitangent sign per vertex (MikkTSpace engines do; Unity's
  `tangent.w`: `engine-notes.md`), so a normal map baked with the mirror in place shades correctly. Flat normal is 128,128,255; 127 shows a mirror seam
  (https://wiki.polycount.com/wiki/Normal_map).

## Cage and bake settings

- Bake with an averaged (smoothed) projection cage. Projecting along split normals leaves gaps and lines at hard
  edges (Marmoset tutorial; https://experienceleague.adobe.com/en/docs/substance-3d/bakers/common-issues/seam-visible-on-every-face).
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
- Dilation only fills the gap the layout left: pack with the gaps from SKILL.md section 7 first, then bake with a
  margin of at least half the gap.

## Stacked and mirrored parts

- Stack identical parts and mirrored halves on one set of texels to save space; duplicates should be real copies
  so the UVs overlap exactly (https://wiki.polycount.com/wiki/Normal_map).
- **Only one copy may be inside 0-1 at bake time.** Move the others exactly one UV unit (any whole number) out:
  "Only one copy of the forward-facing UVs should remain in the 0-1 UV square at baking time"
  (https://wiki.polycount.com/wiki/Texture_Baking). Verified: a Cycles bake into a plain (non-UDIM) image wrote
  nothing for an island at +1 U and wrote the same island when it sat inside 0-1. A UDIM image would bake tile
  1002, so bake into a plain image.
- Whole-unit offsets sample the same texels in the engine when the texture wraps (Repeat, the usual default).
  Clamp would smear them.
- Blender's Mirror modifier stacks the mirrored half by default; its U Offset (`offset_u`) moves that copy by whole
  units (https://docs.blender.org/manual/en/latest/modeling/modifiers/generate/mirror.html).
- Bake the **whole** mesh, mirrored half included; baking only one half bends the normals at the open edge
  (https://wiki.polycount.com/wiki/Normal_Map_Modeling).
- A mirror seam across the middle of a continuous surface usually shows as a lighting seam. Offset the mirror line
  to a less visible place, or map the centre strip uniquely (same page).
- AO on stacked parts is one shadow for every copy: unstack parts that are occluded differently.

## After the bake

- Do not move, rotate, mirror or rescale islands: "rotating or mirroring UVs after baking will cause the normal map
  not to match the tangent basis anymore" (https://wiki.polycount.com/wiki/Texture_Baking). Any UV change means a
  re-bake.
- The lightmap UV2 is separate: unstack everything there (SKILL.md section 9).
