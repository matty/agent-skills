# How image_to_pbr.py derives each map, and a measured run

## Tiling

- Seam ratio, per axis: the mean luma difference across the wrap edge divided by the mean difference between
  neighbouring interior columns (rows). A seam is reported only when the ratio is above 1.5 **and** above the 99th
  percentile of the map's own interior neighbour pairs. Sparse maps (AO that is mostly white) have a wide spread:
  measured on the rug run, AO's wrap edge read 1.58 against an interior p99 of 1.75, and showed no seam.
- Repeat detection (`fit_period`): the mean difference between the image and itself shifted by d, for every d
  between an eighth and seven eighths of the side. Shifts scoring under 0.6 of the mean are repeats; the longest one
  is the crop length (a whole number of periods), refined to the minimum within 2 px.
- Crop (`crop_wrap`): the crop starts where the row after its end best matches its first row, and takes
  `max(8, length / 32)` extra rows from the next repeat, blended into the first rows with a smoothstep. Those rows are
  at the same pattern phase, so only detail that does not repeat (pile, grain, noise) is averaged.
- Fallback (`make_tileable`): cross-fade with a copy offset by half the image, the copy covering the borders. It
  ghosts any large feature crossing the blend, so it is for irregular textures (stone, ground, plaster), not
  patterns.

## Base colour

1. sRGB to linear; divide by the luma blurred at sigma = size / 8 (wrapping when the map tiles), times the mean.
   This removes gradients and hot spots, not cast shadows.
2. Back to sRGB; if the 0.5th-99.5th percentile luma falls outside 30-240 (Adobe's PBR Guide part 2, the tolerant
   dielectric range: https://www.adobe.com/learn/substance-3d-designer/web/the-pbr-guide-part-2), remap it
   affinely into the range and clip, scaling RGB by the luma ratio so the hue survives.
3. 8-bit sRGB, dithered.

## DeepBump route

- `setup_deepbump.py` pins commit `fad19ba87dae` (2025-03-17) and the SHA-256 of `deepbump256.onnx`,
  `module_color_to_normals.py` and `utils_inference.py`. `.py` files are hashed with LF line endings: a `git clone`
  on Windows with `core.autocrlf=true` checks them out with CRLF, and raw hashes then differ from GitHub's zip.
- `run_deepbump` saves the image as a `.npy`, runs DeepBump's `module_color_to_normals.apply(img, "LARGE", None)` in
  DeepBump's venv as a separate process, and loads the result. DeepBump turns the image grey, splits it into 256 px
  tiles with wrap padding (so a tiling input gives a tiling map) and blends the predicted tiles.
- DeepBump prints U+2192 arrows: under a Windows cp1252 console that raises UnicodeEncodeError, so the subprocess
  runs with `PYTHONUTF8=1` (measured 2026-10-25).
- Its output is OpenGL (green up): checked with pbr-texturing's checker, which infers the convention from the
  map, and by a positive correlation of both channels with the built-in OpenGL map on the rug.
- Height: the normals integrated by least squares through the FFT (mirrored first for maps that do not tile).

## Height, normal, AO, roughness

- Height: log of linear luma, split into bands by Gaussian blurs at 1, 4, 16 and 64 px (scaled with the map size
  from 1024): fine = image - blur(4), mid = blur(1) - blur(16), broad = blur(4) - blur(64). Each band is normalised
  to unit deviation and weighted by the preset. Log contrast makes the relief independent of the dye: a weave reads
  the same in indigo and in cream. The 0.5th-99.5th percentiles map to 0-1, 0.5 at the mean surface; 16-bit.
- Normal: central differences of the height with wrap, scaled so the 90th-percentile slope is the preset's tilt,
  tangent space, OpenGL (green = up the image). 16-bit, so no banding.
- AO: how far each texel sits below its 2 px and 8 px neighbourhood, scaled so the 2nd percentile is `ao_min`.
- Roughness: the preset's median, plus up to its spread toward rough in cavities and smooth on peaks.
- Metallic: 0 or 1 from the preset. Unity's MetallicSmoothness puts smoothness = 1 - roughness in alpha; ORM puts
  AO, roughness, metallic in R, G, B for glTF.

## Measured run: Seamless Persian-Inspired Indigo Rug Pattern (2026-10-25)

Source: a 1254 x 1254 8-bit RGB PNG carrying a C2PA manifest (`caBX` chunk, 23,654 bytes).

```
python image_to_pbr.py "Seamless Persian-Inspired Indigo Rug Pattern.png" --out rug --family RUG --name PersianIndigo --preset fabric --make-tileable --preview
```

| Step | Result |
|---|---|
| Source seam ratio | left-right 1.19 (tiles: 1254 px = 2 x 627 px repeats), top-bottom 2.8 (does not tile) |
| Repeat found | rows 1083 px (2 x 541.5 px) from row 134, shift score 0.52; columns untouched |
| Output | 1024 px square; tile aspect 1.158, so the material's V tiling is 1.158 times its U |
| Base colour luma p0.5 / median / p99.5 | 31.4 / 85.5 / 185.4 sRGB: inside 30-240, no remap needed |
| Normal tilt p50 / p90 / p99 | 14.0 / 28.0 / 38.4 degrees |
| Roughness p2 / p50 / p98 | 0.81 / 0.85 / 0.95 |
| Output seam ratios | base colour 1.21, normal 0.86, height 1.38, AO 1.58 (within its interior spread): no seam |
| pbr-texturing's checker | 0 problems; normal map read as OpenGL; note: dark dye p1 34 is under the strict 50 |
| Look-dev (EEVEE, studio HDRI) | Matte woven fabric, pile relief visible, no specular sheen |
| `--normals deepbump` instead | 0.8 s inference; raw tilt p50 / p90 4.0 / 9.0 degrees, scaled to 28 at p90; normal seam 1.19; checker 0 problems, OpenGL. Visually wrong for this rug: the motifs come out as raised pillows (quilted) and the pile ribs are gone, hence `auto` keeps fabric on the built-in method |
| Time | about 6 s on an i9-14900K, numpy 2.2, PNG read without Pillow |

Two script faults this run found and fixed: a single fixed seam threshold flagged sparse maps, and a plain
whole-period crop still showed a seam (1.50) because the pile weave does not repeat with the pattern, which the
feathered overlap fixed (1.21).
