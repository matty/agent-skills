# Trim sheets

A trim sheet is one texture of horizontal strips (mouldings, frame profiles, panel edges, bolts, flat fillers) that
many pieces map onto: every strip tiles along U, so a 6 m skirting and a 0.5 m door stop share it. It replaces unique
textures on architectural kits and lets flat geometry read as detailed. The UV side (straightened strips placed on
their rows) is `uv-unwrapping`'s; this page is the sheet.

## Lay the strips out first

Fix the layout before the trim family's UVs, write it down, and make the UV task work from the file:

1. List every trim the kit needs with its real height (the moulding's face, the frame's width) from the pieces.
2. Each strip's height in pixels = real height x the family's texel density (px/m), rounded to a whole pixel; within
   10% of it, so trims match the walls around them.
3. Put a mip-safe gap between strips: `map_px / 64` px (16 at 1024, the same rule as island gaps), filled by
   extending each strip's edge pixels, so mips never blend two strips.
4. Write the layout as a table, one row per strip, top to bottom: name, first and last pixel row, real height, the
   pieces that use it. A planned world keeps it at `blender/substance/<FAMILY>/layout.md`.
5. Check the rows add up to at most `map_px` and that no two overlap.

| Strip kind | What it is for | Height (at 512 px/m on a 1024 map) |
|---|---|---|
| Bevel strip | A 45 degree baked chamfer at one or both edges, flat between: the edges of panels, slabs, door linings | 16-32 px (3-6 cm) |
| Profile strip | A moulding or frame profile baked from its real cross-section | Its real height |
| Detail strip | Bolts, rivets, a groove, a seam line | 16-64 px |
| Flat filler | A plain band of the material for caps and returns | Whatever is left |

## Bevel strips: chamfers without geometry

A bevel strip stores the normal of a 45 degree chamfer across a few pixels at its edge. Map a flat piece's edge loop
onto it and the edge catches light like a modelled chamfer, with no extra faces and no sub-pixel geometry to shimmer
in VR. Use it where a real chamfer would be under about 2 px wide at the usual viewing distance (what that distance
allows is `blender-mesh-topology`'s rule); model the chamfer where it shows on the silhouette.

## Make the sheet

1. Model each strip's profile as a high poly lying on a plane, one strip above the other at the layout's rows (1 m of
   sheet per 1 m of texture at the sheet's density: a 1024 sheet at 512 px/m is a 2 x 2 m plane).
2. Low poly: the plane itself, UVs filling 0-1.
3. Bake normal, AO, curvature and height onto it (`references/baking.md`; with the Substance baker, a frontal distance
   above the tallest profile). Strips tile along U, so the profiles must run straight across the full width.
4. Texture the strips (Designer, Painter or Blender) using the baked maps as masks; keep each strip's material
   consistent with the tiling material it meets (brick wall, stone trim).
5. Check: `pbr_check.py --trim` on the sheet: the U seams must pass (strips tile in U), the V wrap is not judged, and
   variation along each strip gets a NOTE (a light patch in a skirting strip returns every period along a corridor).
   `--tiling` would judge the strips against each other and fail every sheet. Render a piece with the sheet applied before handing over (`scripts/lookdev_render.py --object ...`).

## Decals beside the sheet

Signs, stains, graffiti and other one-offs go on decal quads, 1-5 mm off the surface, with their own small texture
(an atlas of decals per kit). Opaque or cutout decals are cheapest; alpha blending only where soft edges matter, and
never stacked on mobile (`references/foliage-and-alpha.md`).
