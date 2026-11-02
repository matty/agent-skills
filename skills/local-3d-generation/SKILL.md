---
name: local-3d-generation
description: Generate a 3D model locally from an image or prompt - TRELLIS.2 or Pixal3D in ComfyUI, image-to-3D, a generated GLB with awful dense topology, making the input image, running ComfyUI headless. Input-image recipe, engine settings, GLB intake to a sized high poly. Low poly, UVs and bake go to blender-mesh-topology, uv-unwrapping, pbr-texturing.
---

# Local 3D generation (image to a high poly)

A generated mesh is a **high poly**, never the game mesh: hundreds of thousands of triangles, no edge flow, its own
UVs and textures at an arbitrary scale. The work that makes it usable is building the low poly, unwrapping and
baking, done by the skills named in step 6. Generation is the quick half.

*Measured* means run on ComfyUI 0.43.2 (Comfy Desktop, standalone, Windows) on an RTX 3090 Ti, 24 GB, on
2026-11-02.

## Pick the route

| Starting point | Route |
| --- | --- |
| A text idea | Steps 1-6: make the image with a text-to-image model first (the engines take images, not text) |
| The user's photo, render or concept art of one object | Check it against `references/input-images.md` section 1, fix or crop, then step 3 |
| Several views of one object, or a soft or symmetric object whose back and sides matter (cushions, sacks, toys) | Multi-view (step 3b): front, left, back, right views into `3d_pixal3d_multi_views`. *Measured* on a cushion: the true lens-shaped profile from four views, a lopsided one with an invented flat back from one |
| A modular kit piece, furniture with exact sizes, anything hard-surface with straight edges | Do not generate: model it (`3d-form-design`). Generated hard edges are soft and uneven, and rebuilding the low costs more than modelling it |

Good candidates: organic or worn props seen from a distance (barrels, rocks, stumps, sacks, statues, food,
creatures as set dressing). Poor ones: thin parts (wire, rope, leaves, spindles), glass, mirrors, text.

## 1. Server

`scripts/comfy.py` is plain Python and talks to ComfyUI over HTTP (`--server`, default `http://127.0.0.1:8188`, or
`COMFY_URL`).

```pwsh
python scripts/comfy.py status            # fails: not running
python scripts/comfy.py launch-cmd        # Comfy Desktop installs: the headless command, with its model folders
```

Run the printed command in the background, or ask the user to open Comfy Desktop (its UI also listens on 8188).
Either way the same models folder is used. Wait until `status` answers (*measured*: about 20 s).

## 2. Workflows and models

Use the server's own templates, converted to API prompts by `comfy.py`. Conversion reads the running server's node
definitions, so it stays in step with the installed version.

```pwsh
python scripts/comfy.py templates 3d                        # find a template
python scripts/comfy.py models tpl:image_z_image_turbo_int8 # ok / MISSING per model, with URL
python scripts/comfy.py models tpl:image_z_image_turbo_int8 --download   # into the server's models folder
python scripts/comfy.py convert tpl:3d_pixal3d_trellis2_image_to_model -o gen3d.json
python scripts/comfy.py nodes gen3d.json                    # ids, classes, titles, widget values
```

Ask before downloading: these are 10-40 GB each, and check the model's licence first
(`references/input-images.md` section 6; the image-to-3D engines in `references/engines.md`). `WARN ... using
default` on conversion means the template predates an input; the server's default is used, which is normally right.

## 3. Make the input image

Follow `references/input-images.md`: one whole object, three-quarter view from above, plain grey background, flat
light. Generate four or more seeds and pick against its checklist; look at each image.

```pwsh
python scripts/comfy.py convert tpl:image_z_image_turbo_int8 -o t2i.json
python scripts/comfy.py run t2i.json --set "CLIPTextEncode.text=<prompt>" --set KSampler.seed=1 `
    --set SaveImage.filename_prefix=gen/barrel_s1 --out work/img
```

`--set TARGET.input=VALUE`: TARGET is a node id from `nodes`, or a class or title that names one node. VALUE is
read as JSON when it parses (numbers, true/false), otherwise as a string.

### 3b. Views for multi-view

Ask the image generator for **one turnaround sheet** (front, left, back, right in one row, level camera, long lens,
the same scale, plain background, flat light): one image keeps the object consistent across the views, which four
separate generations do not. Then split it by outline and wire the views into the template
(`references/input-images.md` section 5 has the prompt and the generator's limits):

```pwsh
python scripts/multiview.py split sheet.png work/views --prefix cushion     # square, same-scale views by outline
python scripts/comfy.py models tpl:3d_pixal3d_multi_views --download       # its own 5.6 GB model
python scripts/comfy.py convert tpl:3d_pixal3d_multi_views -o mv.json
python scripts/multiview.py wire mv.json mv_views.json --front work/views/cushion_front.png `
    --left work/views/cushion_left.png --back work/views/cushion_back.png --right work/views/cushion_right.png
python scripts/comfy.py run mv_views.json --upload work/views/cushion_front.png ... --out work/3d
```

The multi-view template already remeshes with `solid`; its model comes posed to the level front view, so skip
`--upright` at intake. *Measured*: 211 s for the cushion.

## 4. Generate the model

```pwsh
python scripts/comfy.py run gen3d.json --upload work/img/barrel.png --set LoadImage.image=barrel.png `
    --set RemeshMesh.sign_mode=solid --set Save3DAdvanced.filename_prefix=3d/barrel --out work/3d
```

- **Always set `RemeshMesh.sign_mode=solid`.** The template's `udf` default leaves every surface as two sheets a
  few mm apart, plus hidden inner walls: *measured* 10.7 m2 of surface on a barrel with 3 m2 of outside, against
  one clean skin with `solid` (`references/engines.md` section 3).
- Engine: Pixal3D is the template default (284 s for the barrel, its models come tilted to the camera, so use
  `--upright` at intake); TRELLIS.2 (`--set "Boolean (Switch to Trellis2).value=true"`, 692 s) gives sharper
  small detail. Settings and costs: `references/engines.md`.
- The template removes the background, crops to the object, generates, remeshes, decimates to 700k faces,
  unwraps and bakes PBR maps into a GLB. A run takes minutes: start it in the background. If the client dies,
  `comfy.py fetch PROMPT_ID` collects the outputs.

## 5. Intake in Blender

```pwsh
blender -b --factory-startup --python-exit-code 1 --python scripts/glb_intake.py -- work/3d/barrel.glb --height 0.9 `
    --upright --name BARREL_high --save work/barrel_high.blend --json work/barrel_intake.json
```

In order, it:

1. Joins the meshes and **welds by position**. glTF splits vertices along every UV seam; unwelded, a generated
   model reads as hundreds of loose parts and tens of thousands of open edges (*measured*: 335 and 66,294 on one
   GLB, one closed shell once welded).
2. Reports triangles, loose parts, open and non-manifold edges, textures, and `sheets`: seeded lines through the
   model (`thin_gap_fraction`: surfaces closer than 0.5% of its size) and `hidden_fraction`, the share of the
   surface no ray from outside reaches. Read `sheets.verdict`: **`double sheets or hidden walls`** (hidden 0.2 or
   more: regenerate with `solid`, step 4), `thin walls` (thin gaps, little hidden: an open vessel's real walls,
   keep it) or `clean`. *Measured*: udf barrels hid 0.52 and 0.78, the solid barrel 0.0; an open cast-iron cauldron
   had 0.65 thin gaps but hid 0.09.
3. With `--upright`, levels a tilted single-image Pixal3D model on its largest flat base (*measured* 19.3 and 27.3
   degrees). It leaves the model alone (`rotated: false`) when there is no clear base, such as a cushion on its
   rounded edge: then give `--rotate X,Y,Z` (degrees, set by eye). A model with no base is a reason to use
   multi-view, which arrives upright.
4. Scales uniformly to the real height (or `--longest`), origin at the bottom centre on Z=0. The size comes from
   the brief or `blender-mesh-topology`'s real-world sizes; a generated model has no scale of its own.

Then render it from the front, three-quarter, back and top next to the input image and look. The back and
underside are invented: judge them from where the player stands. Loose parts are often real (a nail, a handle);
`--drop-floaters 0.001` deletes parts under 0.1% of the triangles once the report shows they are noise.

## 6. Low poly, UVs, bake

The intake result is the high poly for a normal high-to-low bake. Check its `sheets` verdict first: `double
sheets or hidden walls` means regenerate with `solid` (cheap, step 4) before building a low poly. Then:

| Step | Skill |
| --- | --- |
| Low poly: **Quad Remesher** from a cleaner Quad Remesher cage of the high (`quad_remesh_to_budget(..., CurvatureAdaptivness=20.0)`, `SymAxis` when symmetric); LOD1 by `lod_quads`; QuadriFlow without it (decimate to about 60k first); budget from the world; a hand-built low around it for hard-surface | `blender-mesh-topology` (organic route and high/low gate) |
| UVs for the low: **RizomUV `organic`**; without RizomUV, hidden seams and a minimum-stretch unwrap, never Smart UV Project | `rizomuv-uv-pipeline`, `uv-unwrapping` |
| Bake from the high: normal and AO, plus its own textures (`bake_maps.py` maps `basecolor`, `roughness`, `metallic` copy the generated material through the cage); PBR values, look-dev | `pbr-texturing` |
| Formats and memory in the engine | `vrchat-texture-and-vram` for VRChat |

*Measured* on a whole run (`references/post-processing.md`): Decimate plus Smart UV Project gave 583 islands on 25% of
the map; QuadriFlow plus RizomUV gave 94 islands on 46% and a bake that read the same as the high from 1.5 m;
Quad Remesher at a matched count beat QuadriFlow on skew, fit and UVs. Remeshing and subdividing the high pays only
where its matcap check fails, and only with a cage coarse enough not to follow the fault: a cushion's ripple rings
(about 25 mm apart) survived a 64k-quad cage and went with a 2-7k one; on a clean stump it only softened the bake.
A set of props (`references/post-processing.md` section 5): correct each high's colour before baking a shared
atlas, pack the atlas with `rizomuv-uv-pipeline`'s `pack_shared` (49% of the map against 31%), keep the lows
triangulated through export, and build `_COL` shells with `blender-to-unity`'s `collision_shell.py`. Judge a generated low's
silhouette by `blender-mesh-topology`'s `outline_error` (pixels from the player), not the 3D bulge number: the
real fault is parts the low lost (leg tips, lugs), fixed with triangles there (a Quad Remesher density map).
Thin parts near other surfaces bake clean through `pbr-texturing`'s resolver (on by default).
`bake_skew`'s 10% limit is for hard surface: on bark it fails a bake that renders right, so judge an organic
generated prop by the side-by-side look-dev render and `pbr-texturing`'s seam check.

**Correct the base colour after the bake.** The generators' texture stage shifts colour: *measured* a dusty-rose
cushion (hue 2 degrees) came back tan (hue 35) although the views fed in measured hue 2, and a barrel 15% darker.
Match the baked map's chroma to the input image(s):

```pwsh
blender -b --factory-startup --python-exit-code 1 --python scripts/colour_match.py -- `
    --texture maps/T_PROP_Cushion_BaseColor.png --reference work/views/cushion_front.png `
    --reference work/views/cushion_back.png --out maps/T_PROP_Cushion_BaseColor.png --json colour.json
```

It moves hue and saturation only (*measured*: hue 34.7 to 2.2 against 2.0, lightness unchanged), since the input's
lightness includes its studio lighting; check the result in `pbr-texturing`'s look-dev.

## Scripts

| Script | Host | Does |
| --- | --- | --- |
| `scripts/comfy.py` | Python 3.10+, standard library, ComfyUI server over HTTP | `status`, `launch-cmd`, `templates`, `convert` (UI to API: subgraphs, reroutes, bypass, dynamic combos, `control_after_generate`), `models [--download]`, `nodes`, `run` (upload, `--set`, wait, download outputs, JSON summary) |
| `scripts/glb_intake.py` | Blender 4.2+ (`bpy`), headless or live | `intake(path, height=, longest=, name=, drop=, stand=, turn=)`, `report(ob)` (with `sheet_check`: thin gaps, `hidden_fraction`, verdict), `upright(ob)`, `rotate(ob, xyz)`, `drop_floaters(ob, fraction)`, `size_and_ground(ob, ...)` |
| `scripts/multiview.py` | Python 3.10+ and the ffmpeg CLI | `split` a turnaround sheet into square same-scale views by outline; `wire` view images into the multi-view template's API prompt |
| `scripts/colour_match.py` | Blender 4.2+ (`bpy`, numpy) | `match(texture, references, out, lightness=False)`: Lab chroma transfer from the input images' object pixels |
