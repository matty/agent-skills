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

Both steps work on luma: the delighting gain is one value per pixel, from the blurred luma, applied to R, G and B
alike, and the remap scales RGB by a luma ratio (`base_colour()`). Brightness is flattened at the blur's scale and
above; hue is not, so a greener or redder patch the size of a tile survives, and so does any patch, light or dark,
smaller than the blur. In a tiling map such patches repeat as a grid: the `pbr-texturing` skill's tile-scale
variation check (`pbr_check.py --tiling`, which weighs chroma) gates the result, and its tile flattener removes
them from the whole map set.

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

## DeepBump gate

`deepbump_gate(raw, tiles)` measures DeepBump's raw map before anything uses it; a failure hands the whole relief
(normal, height, AO, roughness) to the built-in method.

- Unit normals: decoded vectors with z <= 0 over 0.1% of texels, or a mean | length - 1 | over 0.05. DeepBump's real
  output measured 0 and 0.000 on all 17 materials below; this catches a broken install or model, not a bad guess.
- Raw tilt: the 90th-percentile angle from straight up, before scaling. Under 10 degrees DeepBump saw almost no
  relief, and scaling that to the preset's 12-40 degrees multiplies its noise by 2-10x.
- Integrable fraction (`integrable_fraction`): the slopes (dh/dx, dh/drow) are projected onto the nearest gradient
  field in the Fourier domain, using the same central-difference operator `normal_map` uses, and the fraction of
  energy kept is reported. Normals made from any height map score 1.000 (the built-in method did on every material);
  slopes whose X and Y disagree (curl) score lower. Non-tiling maps are mirrored first, as for integration.
- Seam: `seam_visible` on the raw map when the source tiles. DeepBump pads with wrap, so this only fires if that
  breaks.

## Normals benchmark against scans (2026-10-28)

`scripts/normals_benchmark.py` on 17 CC0 materials at 1k PNG (Poly Haven and ambientCG through `pbr-texture-sources`,
colour map as the input, the site's OpenGL normal map as the truth). Slope correlation is scale-free (1 = the same
relief, negative = inverted); error is the mean angle after matching the 90th-percentile tilt. DeepBump commit
fad19ba87dae, onnxruntime 1.31.0 on CPU, about 1 s per map.

| Material | Preset | Built-in corr / err | DeepBump corr / err | DB tilt p90 | DB integrable | Gate |
|---|---|---|---|---|---|---|
| ambientCG Concrete034 | plaster | +0.78 / 4.0 | +0.38 / 7.0 | 4.5 | 0.73 | built-in |
| ambientCG Fabric086 | fabric | +0.32 / 10.0 | +0.01 / 12.9 | 3.5 | 0.27 | built-in |
| ambientCG Leather037 | leather | +0.53 / 6.6 | +0.19 / 9.4 | 2.3 | 0.37 | built-in |
| Poly Haven wood_table_worn | wood | +0.48 / 3.5 | +0.25 / 4.2 | 23.9 | 0.41 | built-in |
| ambientCG Tiles141 | stone | +0.28 / 0.9 | +0.15 / 1.1 | 9.5 | 0.79 | built-in |
| Poly Haven painted_plaster_wall | plaster | -0.34 / 9.7 | -0.13 / 9.4 | 6.1 | 0.73 | built-in |
| Poly Haven rust_coarse_01 | metal | -0.04 / 5.9 | -0.01 / 5.8 | 7.1 | 0.80 | built-in |
| Poly Haven red_brick_03 | brick | -0.15 / 19.2 | +0.67 / 10.1 | 29.5 | 0.79 | DeepBump |
| ambientCG Rock064 | stone | -0.00 / 22.5 | +0.36 / 17.1 | 26.7 | 0.90 | DeepBump |
| Poly Haven bark_brown_02 | ground | +0.04 / 23.1 | +0.06 / 18.0 | 35.3 | 0.98 | DeepBump |
| Poly Haven forest_ground_04 | ground | +0.28 / 24.4 | +0.45 / 21.3 | 25.6 | 0.94 | DeepBump |
| Poly Haven medieval_blocks_03 | brick | +0.00 / 38.5 | -0.01 / 36.2 | 16.4 | 0.95 | DeepBump |
| Poly Haven coast_sand_rocks_02 | stone | +0.20 / 24.8 | +0.29 / 23.4 | 14.9 | 0.93 | DeepBump |
| ambientCG WoodFloor064 | wood | -0.63 / 0.7 | -0.31 / 0.6 | 36.5 | 0.78 | DeepBump |
| ambientCG Ground106 | ground | +0.09 / 16.7 | +0.04 / 17.8 | 13.1 | 0.78 | DeepBump |
| Poly Haven metal_plate | metal | -0.21 / 11.9 | -0.12 / 12.1 | 35.2 | 0.66 | DeepBump |
| Poly Haven floor_tiles_06 | stone | +0.00 / 4.2 | -0.04 / 4.3 | 28.7 | 0.90 | DeepBump |

Mean error: built-in 13.33, DeepBump 12.40, gated 11.87, the better of the two per material 11.76 degrees. Every
difference over 1.5 degrees was called right; the five calls that went the other way differed by 0.1-1.1 degrees.
The rug (above) fails on tilt, 9.0 degrees, with integrable fraction 0.92.

What it shows, and its limits:

- DeepBump wins where relief is large and colour follows it (brick, rock, bark, forest floor); the built-in method
  wins on fine, low relief (concrete, leather, fabric, worn wood), where DeepBump sees little and invents the rest.
- The built-in method's typical failure is inverted relief (red brick -0.15: the light mortar reads as raised);
  `--invert-height` is the fix when `preview_lit.png` shows it.
- Both correlate weakly with the scans overall (gated mean 0.20). A single image does not hold the relief; these
  maps are plausible, not measured.
- The inputs are the libraries' delit albedo maps, an easier input than a photo with lighting baked in. 17 materials
  is a small set: the 10-degree threshold sits between 9.5 (Tiles141, a near tie) and 13.1 (Ground106, a near tie),
  and the rug at 9.0 is close to it.

## Alternatives checked (2026-10-28)

| Candidate | Outputs | Licence | Verdict |
|---|---|---|---|
| PBRify_Remix NormalV3, RoughnessV2, Height (https://github.com/Kim2091/PBRify_Remix; ONNX at https://huggingface.co/fernandotonon/QtMeshEditor-models, revision 726f9825) | normal, roughness, height | CC0 | Measured above on the same 17: its normal map is DirectX (X matched the scans, Y was inverted). With Y flipped it correlated 0.55-0.88 with the built-in method, so it is a learned version of it, and was further from the scans: mean error 13.88 degrees (built-in 13.33, DeepBump 12.40), mean slope correlation 0.06; closer than the built-in on 4 of 17. Trained on ambientCG and Poly Haven, so even that is flattering. Not added |
| Marigold IID-Appearance / Normals v1.1 (https://github.com/prs-eth/Marigold) | albedo, roughness, metallic; normals | Apache-2.0 code, Open RAIL++-M weights | The only open roughness-and-metallic model, but about 0.9B parameters on torch and diffusers, slow on CPU, trained on indoor scenes rather than flat textures. Unmeasured here |
| Ubisoft CHORD (https://huggingface.co/Ubisoft/ubisoft-laforge-chord, arXiv 2509.09952) | base colour, normal, roughness, metalness | Ubisoft ML License, research only, gated | Made for tileable textures, but the licence rules it out |
| RGB-X (https://github.com/zheng95z/rgbx) | albedo, roughness, metallic, normal | Adobe Research, non-commercial | Ruled out by licence; 12 GB GPU |
| Material Palette, StableMaterials, MatFuse, StableNormal, DSINE, PBRFusion4 | various | mixed | Generators rather than estimators, scene and object normals, unpinnable weights or GPU-only |
| Materialize, AwesomeBump, NormalMap-Online, Laigter | normal, height, AO from filters | various | The same luminance-gradient maths as the built-in method |

Roughness and metallic stay preset-driven: no permissive, CPU-friendly model trained on flat textures was found.

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
| `--normals deepbump` instead | 0.8 s inference; raw tilt p50 / p90 4.0 / 9.0 degrees, scaled to 28 at p90; normal seam 1.19; checker 0 problems, OpenGL. Visually wrong for this rug: the motifs come out as raised pillows (quilted) and the pile ribs are gone, hence `auto` keeps fabric on the built-in method. Since 2026-10-28 the gate rejects it too (raw tilt p90 9.0 < 10), so `--normals deepbump` now falls back with a PROBLEM |
| Time | about 6 s on an i9-14900K, numpy 2.2, PNG read without Pillow |

Two script faults this run found and fixed: a single fixed seam threshold flagged sparse maps, and a plain
whole-period crop still showed a seam (1.50) because the pile weave does not repeat with the pattern, which the
feathered overlap fixed (1.21).
