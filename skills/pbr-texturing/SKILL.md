---
name: pbr-texturing
description: Texturing and materials for real-time 3D - materials look flat, plastic, too clean, too dark or too bright, tiling or repetition shows, a normal map looks inverted or shimmers, a bake has seams or skewed detail. Kit, trim sheet and prop texturing, decals, wear, mesh-map bakes (Substance baker, Cycles), Substance Designer and Painter, PBR checks, look-dev renders. UVs uv-unwrapping, formats and VRAM vrchat-texture-and-vram, lightmaps vrchat-lighting-and-baking, modelling blender-mesh-topology.
---

# PBR texturing

Decide what every surface's material is and where its detail comes from before anyone paints: the plan sets the map
count, the UVs and the draw calls. Then hold every map to measured values, judge it under real lighting, and keep the
sources so any map can be remade. Engine-neutral; what an engine reads is in `references/engine-notes.md`.

## 1. Plan the material set

| Surface | Approach | Notes |
|---|---|---|
| Walls, floors, ground, large plain areas | Tiling material | One tile period per family at the family's texel density; macro variation against repetition (section 5) |
| Mouldings, frames, panel edges, pipes, kit edges | Trim sheet | Strips laid out first (`references/trim-sheets.md`); flat geometry reads bevelled from the strip's baked normals |
| Props, hero pieces, anything with a bake | Unique texture or an atlas of several props | Mesh maps baked from a high poly (section 3); one atlas per room or kit, never global |
| One-off marks: a plaque, a stain, a sign | Decal | A separate quad with its own small texture, never painted into a tiling map (it would repeat on every bay) |
| Close-range sharpness on a tiling surface | Detail map | A second, finer tiling layer the engine blends in (`references/engine-notes.md`) |
| Foliage, fences, grilles | Alpha cards or geometry | Cost and filtering rules: `references/foliage-and-alpha.md` |

- 1-3 materials per kit family, one per visual family, not per object: material count drives draw calls.
- Names: maps `T_<FAMILY>_<Name>_<Map>.png` (`BaseColor`, `MetallicSmoothness`, `Normal`), materials `M_<FAMILY>_<Name>`;
  the checker and the engine import key on them.
- Texel density and UVs (seams, padding, trim strips, stacking) are `uv-unwrapping`'s. A piece that tiles with its
  wall and also carries its own mark needs a second UV region or a decal: never ask one island to do both.

## 2. Values

| Channel | Rule | Source |
|---|---|---|
| Base colour, dielectric | Luma no darker than 30 sRGB (tolerant) or 50 (strict) and no brighter than 240; charcoal measures 39, snow 237 | Adobe PBR Guide; physicallybased.info |
| Base colour, raw metal | 180-255 sRGB (70-100% reflectance); titanium measures 171, the darkest common metal | the same |
| Metallic | 0 or 1. Greys only where a blend is real: dust, paint wear, oxidation edges. Dirt on metal lowers metallic, it does not darken the metal colour | Adobe PBR Guide |
| Roughness | Tells the surface's story: wear polishes high spots, grime roughens crevices, water darkens and smooths. Never one flat value over a whole material | *practice* |
| Specular (F0) | 0.04 for dielectrics, set by the shader in a metal/roughness workflow: nothing to paint | Adobe PBR Guide |
| Normal map | Tangent space, OpenGL (Y+) for Blender and Unity, unit length, no texel pointing into the surface | `references/engine-notes.md` |
| Specular shimmer (VR) | Busy, fine normal detail under high smoothness sparkles in a headset: lower smoothness where the normal map is busy, keep sub-texel normal detail out, fade fine normal detail in the lower mips or move its lost variance into roughness (Toksvig-style) where the tool can; prefer a shader with geometric specular anti-aliasing | *practice*; `references/pbr-values.md` |

Every number, the measured materials and how `scripts/pbr_check.py` judges them: `references/pbr-values.md`.

## 3. Bake mesh maps from a high poly

1. The low poly is final: UVs done (a seam on every hard edge, mip-safe gaps: `uv-unwrapping`), triangulated the way
   it exports, so the baker and the engine see the same triangles.
2. The high poly overlaps the low poly; protruding detail sits inside the cage (the bake reports how far it stands
   out, and how many rays start inside a high: `cage_inside`). Narrow channels, creases and upholstery take a fitted
   cage (`--cage fitted`); thin cords and chamfers under about 3 texels wide `--filter-sigma 0.8`.
3. Bake with one of two measured routes (`references/baking.md`):

   | Route | When | Gives |
   |---|---|---|
   | Substance 3D baker CLI (`substance3d_baker`, in Designer's install folder: how to find it is in `references/baking.md`; measured with 16.0.7) | Designer installed | Raytraced normal, AO, curvature, thickness, position, ID, world normal, bent normals; GPU, under a second on the test fixture |
   | Blender Cycles: `scripts/bake_maps.py` | Always (Blender only) | Normal, AO, curvature (Pointiness) through a cage it sizes itself, uniform or fitted per vertex; square or tall maps; 16-bit PNGs |

   The Substance baker writes **DirectX** normal maps unless told `--output_texture_orientation opengl`, and pads only
   2 px by default (measured 2026-10-18): pass both every time.
4. Ship the normal map; keep AO, curvature, thickness and position as masks for wear (section 5). In a baked-lighting
   world the lightmap carries large-scale occlusion: AO in the shipped material only for small-scale crevices.
5. Check the normal map: `pbr_check.py` reads its Y convention from the map itself (section 8).

## 4. Author

| Tool | Use it for | Route |
|---|---|---|
| Substance Designer (its MCP answers `sd_ping`) | Tiling materials, trim sheets, procedural masks | `references/substance-designer.md`; bitmaps through `sbsrender` |
| Substance Painter | Unique hero props: layered wear on baked mesh maps | `references/substance-painter.md`: scriptable through its Python API, but only through a bridge the user installs; otherwise user-assisted |
| Blender | Everything when Substance is missing | Procedural node materials baked to images: `references/blender-materials.md` |
| Scanned CC0 materials (Poly Haven, ambientCG) | A real-world base to build from | Only when the user allows library assets; search and download with `pbr-texture-sources` (it records the source and licence beside the maps); recalibrate to section 2 |

## 5. Wear, variation and repetition

- Wear goes where the object's life put it: edges (curvature), crevices (AO), tops (world-space normal up: dust),
  the bottom 20-30 cm of walls (position: splash and scuffs), around handles and switches (hand contact). Restraint:
  one story per material, at a scale that reads at the viewing distance.
- Repetition is the giveaway of a kit: macro variation in the tiling material (low-frequency value and roughness
  shifts at a different period from the detail), detail maps at a second scale, decals and props to break long runs,
  and two or three visibly different variants of the most repeated pieces sharing the family material (variants cost
  meshes, not SetPass calls).
- Judge repetition in a wide view at eye height, not on a 3 x 3 composite alone.

Detail and the mask recipes: `references/wear-and-variation.md`.

## 6. Trim sheets and decals

- Lay the strips out before the trim family's UVs: each strip's pixel rows at the family texel density, written to
  the layout file the UV task works from. Bevel strips whose baked 45 degree normals let flat geometry read as
  chamfered save geometry and shimmer-prone thin chamfers. Recipe: `references/trim-sheets.md`.
- Decals: a quad 1-5 mm off the surface, its own small texture, alpha blended only where an opaque or cutout decal
  cannot do; on mobile GPUs every alpha layer costs fill rate (`references/foliage-and-alpha.md`).

## 7. Export

- Power-of-two sizes, at most the family's map size; never raise a map above it to "look sharper" (texel density is
  `uv-unwrapping`'s).
- Masters for normal and height maps at 16 bits; 8-bit exports dithered so gradients do not band (`bake_maps.py`
  writes both).
- Dilation of at least half the island gap (bakers fill only what you ask: the Substance baker's default is 2 px).
- Channel packing for the engine: `references/engine-notes.md` (Unity's Standard: metallic in R, smoothness =
  1 - roughness in A, never a glTF-style ORM map).
- Keep the sources (`.sbs`, `.spp`, the node-setup `.blend`, bake settings) next to the exports.

## 8. Check before reporting

1. Values: `python pbr_check.py "<textures>/T_*.png" --map-px <map_px>` (or inside Blender:
   `blender -b --factory-startup --python-exit-code 1 --python pbr_check.py -- "<textures>/T_*.png"`). PROBLEM lines
   block; NOTE lines are advisory. With art-direction targets, add `--targets` or `--spec world/spec.yaml`.
2. Tiling maps: `--tiling --out <scratch>` adds the seam ratio and writes a 3 x 3 composite per map; at or below about
   1 passes, above it look at the composite.
3. Look-dev: `blender -b --factory-startup --python-exit-code 1 --python lookdev_render.py -- --maps "<textures>/T_<FAMILY>_<Name>_*.png" --png <out>.png`
   renders the maps under one of Blender's CC0 studio HDRIs. Workbench ignores roughness, metallic and normal maps
   (measured: a smooth and a rough metal rendered identically): never judge materials in it.
4. In the engine, on the platform hardest to fit: the import settings and the shader's own multipliers
   (`references/engine-notes.md`).

## Scripts

| Script | Host | Use |
|---|---|---|
| `scripts/pbr_check.py` | Plain Python with numpy, or Blender | Base-colour, metallic, smoothness and normal-map values per material, the normal map's Y convention, power-of-two and size limits, tiling-seam ratios and 3 x 3 composites; exit 1 on a PROBLEM |
| `scripts/bake_maps.py` | Blender (Cycles) | `bake(low, highs, maps=("normal", "ao", "curvature"), size, out_dir, name, cage="fitted")`: a uniform cage sized to enclose the high poly or a fitted one per vertex, a report of rays starting inside a high, supersampling with a Gaussian pre-filter, `size=(w, h)`, 16-bit or dithered 8-bit PNGs of 1-4 channels; a CLI |
| `scripts/lookdev_render.py` | Blender (EEVEE or Cycles) | `material_from_maps(...)` wires exported maps into a Principled BSDF; `render(objects, png)` under a bundled CC0 HDRI; a CLI for maps or objects |

Load a Blender script from the Blender MCP with `exec(open(path, encoding="utf-8").read(), ns)` after setting
`ns["BAKE_MAPS_NO_MAIN"] = True` or `ns["LOOKDEV_NO_MAIN"] = True`; `pbr_check.py` imports as a module anywhere.
