# Blender materials: the fallback route and look-dev wiring

When Substance is not installed, Blender makes the maps: procedural node materials baked to images. The same page
covers wiring exported maps back into a material for a look-dev render. Measured on Blender 5.2.2, 2026-10-18.

## Procedural materials baked to images

1. One node setup per material, in its own file next to the exports (a planned world keeps
   `blender/substance/<FAMILY>/<FAMILY>_materials.blend`) so the maps can be re-baked.
2. Bake each signal on its own through an Emission shader and bake type EMIT: it gives the exact values with no
   lighting. The image's colour space decides what is stored (measured): an sRGB-tagged image stores sRGB codes (a
   linear 0.5 becomes 0.735), a Non-Color image stores the value itself. So base colour bakes into an sRGB image;
   metallic, roughness, height and masks into Non-Color images. The DIFFUSE bake (colour pass only) and the ROUGHNESS
   bake type work too.
3. Float images save as 16-bit PNGs with `Image.save()` (measured); keep those as masters.
4. Tiling materials: bake one tile of the family's UV0 layout. At `map_px` pixels and `texel_density` px/m one tile
   covers `map_px / texel_density` metres (2 x 2 m at 512 px/m on 1024): every pattern must repeat a whole number of
   times across it. Check with `pbr_check.py --tiling --out <scratch>` and look at the 3 x 3 composite.
5. Pack the engine's maps from the baked greys. Unity's Standard and VRChat's Standard Lite read metallic from R and
   smoothness (1 - roughness) from A:

```python
import bpy, numpy as np
def grey(img):                                  # a baked Non-Color image -> (height, width) array, rows bottom-up
    w, h = img.size
    px = np.empty(w * h * 4, np.float32); img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)[:, :, 0]
metal, rough = grey(bpy.data.images["bake_metallic"]), grey(bpy.data.images["bake_roughness"])
h, w = metal.shape
out = bpy.data.images.new("T_EXT_Brick_MetallicSmoothness", w, h, alpha=True, float_buffer=True)
out.colorspace_settings.name = "Non-Color"
rgba = np.zeros((h, w, 4), np.float32); rgba[:, :, 0] = metal; rgba[:, :, 3] = 1.0 - rough
out.pixels.foreach_set(rgba.ravel())
out.filepath_raw = export_path                  # .../textures/EXT/T_EXT_Brick_MetallicSmoothness.png
out.file_format = "PNG"
out.save()                                      # a 16-bit RGBA PNG
```

6. Run `pbr_check.py` on the exports before reporting.

## Wiring exported maps into a material (look-dev)

`scripts/lookdev_render.py`'s `material_from_maps(name, base_color=..., metallic_smoothness=..., normal=...)` builds
this; by hand:

| Map | Image node colour space | Into the Principled BSDF |
|---|---|---|
| `T_*_BaseColor` | sRGB | Base Color |
| `T_*_MetallicSmoothness` | Non-Color (alpha mode Channel Packed) | Separate Color R -> Metallic; the image's Alpha through Math Subtract (1 - x) -> Roughness |
| `T_*_Normal` | Non-Color | Normal Map node, Tangent Space, on the mesh's UV map -> Normal (OpenGL, as Blender bakes) |

- Measured: a Non-Color image keeps its RGB under alpha 0 in every alpha mode (a Cycles EMIT bake read R = 1 where
  alpha was 0), so a rough metal (smoothness 0) keeps its metallic; Channel Packed states the intent anyway.
- Judge in EEVEE or Cycles with the Standard view transform: factory settings use AgX (measured), which compresses
  highlights and shifts saturation, while an engine without post-processing shows plain sRGB.
- Never judge materials in Workbench: it shows the base colour texture but ignores roughness, metallic and normal maps
  (measured: a smooth and a rough metal rendered pixel-identical, while EEVEE showed a 0.185 mean difference).
- Light with one of Blender's bundled CC0 studio HDRIs (`datafiles/studiolights/world`: studio, interior, courtyard,
  city, forest, night, sunrise, sunset, from Poly Haven); `lookdev_render.py --hdri` picks one.
