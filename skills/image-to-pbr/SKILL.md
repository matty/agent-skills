---
name: image-to-pbr
description: Turn one image (photo, scan or generated pattern of rug, fabric, tiles, stone, wood) into a PBR material - base colour, normal, height, roughness, AO, metallic; a seamless texture that shows a seam, pattern squashed, maps too dark or shiny. Seam and repeat detection, delighting, DeepBump normals, value calibration. Hand-authored materials and bakes (pbr-texturing); formats and VRAM (vrchat-texture-and-vram).
---

# Image to PBR

Derive a full map set from a single image with `scripts/image_to_pbr.py`, then prove it tiles and holds PBR values
before anyone uses it. A single image carries colour, lighting and relief mixed together: the script separates what
it can, the presets supply what it cannot, and every guess is measured in the report. Engine-neutral.

## 1. Take stock of the source

| Check | How | Why |
|---|---|---|
| Does it tile? | The script measures each wrap edge (seam ratio, left-right and top-bottom); never trust a file name saying "seamless" | Measured 2026-10-25: a "seamless" rug image tiled left-right (ratio 1.19) but not top-bottom (2.8); its 541.5 px vertical repeat did not divide its 1254 px height |
| Is it a repeating pattern? | `--make-tileable` finds the repeat along each failing axis and crops to whole repeats | A whole-period crop keeps every motif intact; a cross-fade ghosts them |
| Lighting baked in? | Broad gradients, a hot spot, a shadow side | Delighting removes broad gradients only; hard cast shadows stay in the base colour: pick another image |
| Shot straight on? | Grout lines, planks or weave run straight and parallel, equal spacing from edge to edge | Perspective or lens distortion becomes stretching once tiled (*practice*): take the photo square to the surface, or rectify it before converting |
| Physical size | A ruler or an object of known size in the frame, or the scan's own scale | Record the size the source covers in metres: the tile's period along each axis is `tile_px` / `px` (both in the source record) x the source's metres along that axis, and the UV tiling and every grid-step check need it (section 5) |
| Resolution | The largest power of two that fits, up to 2048 | Upscaling adds no detail; the report notes it |
| Licence and origin | Record where it came from: stock licence, scan source, or the generator and its terms | The script writes a source record (section 4); the licence text is yours to add |

## 2. Normals: DeepBump or the built-in method

DeepBump (https://github.com/HugoTini/DeepBump, GPL-3.0) is a machine-learning model that predicts a normal map from
a colour image. Use it when it is installed; download it when it is not. Its output is a guess and is never trusted
unmeasured: the converter gates every DeepBump map (below) and falls back to the built-in luminance method when it
cannot run or its map fails. Tell the user which one made the maps.

1. `python setup_deepbump.py --check`. Exit 0: installed and working.
2. Exit 1: run `python setup_deepbump.py`. It downloads DeepBump at a pinned commit (about 42 MB from GitHub), checks
   the model and the code it runs against pinned SHA-256 hashes, builds its own venv with numpy and onnxruntime from
   PyPI, and smoke-tests it. It installs into `%LOCALAPPDATA%/agent-skills/deepbump` (Windows) or
   `~/.cache/agent-skills/deepbump`, never into a project or this repo. Measured 2026-10-25: Python 3.14.8,
   onnxruntime 1.31.0, about 1 s per 1024 px map on CPU.
3. If setup fails (no network, no wheel for this Python, a hash mismatch), do not retry in a loop: tell the user
   DeepBump is unavailable and why (setup prints it), and carry on with the built-in method. A hash mismatch means
   the download is not the pinned code: never edit the pins to make it pass without the user's say-so.
4. The converter reports `normal_source` (`deepbump <commit>` or `builtin`) and `deepbump_gate` (the measurements
   below, `ok` and `reasons`). Always tell the user which one ran; any `DeepBump unavailable` or `DeepBump rejected`
   line goes to the user verbatim.

The gate, measured on DeepBump's raw map before it is scaled or used (`deepbump_gate()`). Any failure means the
built-in method makes the normal, height, AO and roughness maps:

| Measure | Fails when | What a failure means |
|---|---|---|
| Unit normals | over 0.1% face away, or mean length error over 0.05 | Broken output, not a surface |
| Raw 90th-percentile tilt | under 10 degrees | DeepBump found almost no relief; scaling it up to the preset's tilt amplifies noise |
| Integrable fraction | under 0.6 | Its X and Y slopes disagree: no height map produces them (1.0 for a real surface) |
| Seam (tiling maps) | its normal map shows a seam | It broke a tile the source made |

The thresholds are calibrated, not guessed: against the scanned normals of 17 CC0 materials (2026-10-28,
`references/method.md`), every material where DeepBump was more than 1.5 degrees further from the scan than the
built-in method failed the gate, and every one where it was more than 1.5 degrees closer passed; the five the gate
called the other way differed by 1.1 degrees or less. Gated, the mean error was 11.9 degrees against 12.4 for DeepBump
alone and 13.3 for the built-in alone. Do not loosen a threshold to get DeepBump through; re-measure with
`scripts/normals_benchmark.py` when the pin, a threshold or the built-in method changes, and record the result in
`references/method.md`.

| `--normals` | Uses | When DeepBump is missing, fails or is rejected |
|---|---|---|
| `auto` (default) | DeepBump when its map passes the gate, except for `fabric` | Built-in, with a NOTE |
| `deepbump` | DeepBump for any preset, still gated | Built-in, with a PROBLEM (exit 1) |
| `builtin` | The luminance method | n/a |

Why `auto` skips fabric: measured on the rug (2026-10-25), DeepBump embossed the dyed motifs as raised pillows and lost
the pile weave, a quilted look; on printed or woven textiles the colour pattern is dye, not relief. Where colour does
follow relief (stone, brick, ground, bark, plaster) DeepBump is the better guess; compare both on
`preview_lit.png` when in doubt. The gate backs the skip up: on the rug DeepBump's raw tilt was 9.0 degrees, so it
fails anyway. With DeepBump the height map is integrated from its normals, and its slopes are scaled to the preset's
tilt like the built-in ones (`deepbump_gate.raw_tilt_deg_p50_p90` in the report keeps its own).

A passing gate shows the map is a plausible surface, not that it is the right one: single-image normals from either
method correlate only weakly with a scan (mean slope correlation 0.2 gated). Still look at `preview_lit.png`.

Alternatives checked 2026-10-28 (detail and sources in `references/method.md`): PBRify NormalV3 (CC0, ONNX) is a
DirectX map that tracks the built-in method (slope correlation 0.55-0.88 with it) and was further from the scans
than either (mean error 13.9 degrees);
CHORD and RGB-X are research-only licences; Marigold and the diffusion models need a GPU-sized torch install and are
trained on scenes, not flat textures. None replaces DeepBump plus the built-in fallback, and no open model predicts
roughness or metallic for flat textures well enough to replace the presets.

## 3. Convert

```
python image_to_pbr.py <image> --out <textures>/<FAMILY> --family <FAMILY> --name <Name> --preset <preset> --make-tileable --preview
```

Host: plain Python with numpy (Pillow only for JPEG, WebP, TIFF and paletted PNG), or Blender's bundled Python.

| Preset | Median roughness | 90th-pct normal tilt | Height bands (fine, mid, broad) | Use for |
|---|---|---|---|---|
| `fabric` | 0.88 | 28 deg | 1.0, 0.35, 0.05 | Rugs, carpet, upholstery, canvas |
| `stone` | 0.75 | 35 deg | 0.5, 0.8, 0.6 | Flagstones, rock, concrete |
| `brick` | 0.82 | 35 deg | 0.4, 0.8, 0.8 | Brick and block with mortar |
| `plaster` | 0.85 | 15 deg | 0.6, 0.6, 0.3 | Walls, render, painted plaster |
| `wood` | 0.60 | 12 deg | 0.8, 0.5, 0.1 | Planks, veneer, furniture |
| `ground` | 0.90 | 40 deg | 0.5, 0.9, 0.7 | Soil, gravel, forest floor |
| `leather` | 0.55 | 15 deg | 1.0, 0.4, 0.1 | Leather, vinyl |
| `metal` | 0.40 | 10 deg | 0.8, 0.4, 0.1 | Bare metal (metallic 1; base colour must be 180-255 sRGB) |

The presets are starting points from practice, not measurements: override any value (`--roughness`, `--tilt-deg`,
`--bands`, `--ao-min`, `--metallic`) when a reference says otherwise, and say so in the report to the user. Where the
dark parts are the raised ones (dark grout proud of the tiles is rare; dark raised paint is not), `--invert-height`.

What it does, in order (detail in `references/method.md`):

1. Tiling: per-axis seam ratios; with `--make-tileable`, a whole-period crop with a narrow feathered overlap on each
   failing axis, a half-offset cross-fade only when there is no clear repeat. `--no-tiling` for a unique map.
2. Resample to a square power of two with a wrap-aware, antialiased filter. A non-square tile is recorded as
   `tile_aspect`: set the material's tiling or UV scale to it, or the pattern is squashed.
3. Base colour: divide out broad lighting in linear light, then bring luma into the dielectric 30-240 sRGB range,
   keeping chroma. Both act on luma only: a colour patch at tile scale survives (section 4, step 3).
4. Height from relative (log) luminance contrast in three bands, so a dark dye and a light dye give the same relief.
5. Normal (tangent space, OpenGL Y+, 16-bit; DeepBump's when it passes the gate, else from the height), scaled so
   the 90th-percentile slope hits the preset's tilt.
6. AO from cavities in the height map; roughness from the preset, rougher in cavities, smoother on peaks.
7. Writes `T_<FAMILY>_<Name>_<Map>.png` (BaseColor, Normal, Height, Roughness, AO, plus MetallicSmoothness for Unity
   or ORM for glTF with `--pack`), `image_to_pbr_report.json` and the source record.

## 4. Check before reporting

1. Exit 1 or any `PROBLEM` line blocks. `NOTE` lines are advisory, but say what each one means for this material.
2. Look at `preview_tile3x3.png` for seams, ghosting and repetition, and `preview_lit.png` for relief that reads the
   wrong way round (light motifs raised as ridges on a flat-pile rug is a wrong height map: lower the mid band).
3. If `pbr-texturing` is installed, load it and run its PBR checker and look-dev render on the maps: values against
   measured materials, the normal map's Y convention from the pixels, and the material under a studio HDRI. A tiling
   result also passes its tile-scale variation check (`pbr_check.py --tiling`, chroma included): a PROBLEM there
   blocks, and that skill's tile flattener on the whole map set fixes it.
4. Fine normal detail under low roughness sparkles in VR: keep `--tilt-deg` modest on smooth materials.

## 5. Provenance

`T_<FAMILY>_<Name>_source.json` records the source path, its SHA-256, its size, the tile actually used and the PNG
chunks it carried, including whether it holds a C2PA manifest (content credentials, the `caBX` chunk). The script
does not know the physical size: add it by hand (`source_m` and `tile_m`, each as width and height, from section 1).
Keep the source image and this record beside the maps, add the licence or the generator's terms, and pass both on
with the material. This skill does not remove, forge or evade provenance: no stripping of C2PA manifests for their
own sake, no attempts to defeat invisible watermarks such as SynthID. If a user asks for that, say so and carry on
with the conversion.

## Scripts

| Script | Host | Use |
|---|---|---|
| `scripts/image_to_pbr.py` | Plain Python with numpy, or Blender | `convert(src, out_dir, family, name, preset, ..., normals, deepbump)` returns the report; the CLI above; `load`, `write_png`, `seam_ratios`, `fit_period`, `crop_wrap`, `run_deepbump`, `deepbump_gate`, `integrable_fraction` and `height_from_normals` as a module |
| `scripts/setup_deepbump.py` | Plain Python, standard library; network | Installs DeepBump at a pinned commit with hash checks into a per-user folder and its own venv; `--check` reports whether it works |
| `scripts/normals_benchmark.py` | Plain Python with numpy (Pillow for most library PNGs); DeepBump installed | Scores DeepBump and the built-in normals against scanned ground truth (folders of colour + OpenGL normal maps) and checks the gate picks the closer one |

Worked example and measured numbers: `references/method.md`.
