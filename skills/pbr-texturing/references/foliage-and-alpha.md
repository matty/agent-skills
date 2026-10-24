# Foliage, cards and alpha

Alpha is the most expensive thing a texture can ask for on mobile GPUs and the easiest way to make distant foliage
vanish. Decide what really needs it, then make it cheap and keep its coverage. Engine specifics (import settings,
which shaders support what) are in `references/engine-notes.md`.

## Geometry, cutout or blend

| Use | When | Cost |
|---|---|---|
| Opaque geometry | Chunky shapes: thick fence bars, large leaves seen up close, bushes far enough to read as a mass | Triangles only |
| Alpha cutout (alpha test) cards | Thin detail: grass, leaves, chain-link, grilles | Every covered pixel runs the shader; a discard defeats the hidden-surface optimisations of tile-based mobile GPUs, and overlapping cards multiply it (overdraw) |
| Alpha blend | Soft edges only: glass, smoke, soft decal edges | Worst: sorting problems and full overdraw; never stacked on mobile |

- Fit card outlines to the opaque shape (a few more vertices, far fewer transparent pixels): overdraw usually costs
  more than the vertices.
- Fewer, larger cards beat many small overlapping ones.

## Keep coverage in the distance

An alpha-tested texture thins out in its smaller mips: averaging alpha with the transparent pixels around a leaf pulls
it under the cutoff, and trees go bald with distance. Fix it in the mips:

- Coverage-preserving mips rescale each mip's alpha so the share of pixels above the cutoff stays the same; the
  importer needs the material's cutoff value to do it.
- Dilate colour into the transparent pixels (bake margin, or a dilation filter) so filtering at the edges blends with
  leaf colour, not with black: dark halos round every leaf mean the transparent pixels' RGB is black. Ship it as one
  RGBA base-colour map (RGB the dilated colour, A the coverage): `bake_maps.save_png` writes 1-4 channels (grey,
  grey + alpha, RGB, RGBA) from rows top to bottom.
- Alpha-to-coverage, where the shader and MSAA allow it, turns alpha into smooth anti-aliased edges instead of
  stair-stepped cutout edges.

## Shading foliage

- Card normals point every which way, so a canopy shades as a pile of flat cards: transfer normals from a sphere or
  hull around the canopy (Blender's Data Transfer modifier with a proxy) so it lights as one volume.
- Two-sided cards need either a two-sided shader or duplicated back faces with flipped normals.
- Thin cards lightmap badly (tiny charts, leaks): light foliage with light probes, not lightmaps (the lighting skill
  for the engine decides).
- Wind moves vertices in the shader (weights in vertex colour or a UV channel): only with a shader that does it.

## Distance

- LODs that thin the card count, then a billboard or impostor (a card with the tree baked onto it, lit to match) for
  the far distance; a hard switch pops in VR, so cross-fade where the shader supports it or switch where it is hidden.
- Skyline trees and treelines: cards at the low texel classes, no per-leaf detail.
