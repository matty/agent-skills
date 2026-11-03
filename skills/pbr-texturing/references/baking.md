# Baking mesh maps from a high poly

Three routes, all measured on the same fixture: a 1 m low-poly cube (12 triangles, hard edges, each face its own UV
island) and a bevelled, subdivided high-poly cube with half-sunk spheres standing 6 cm proud (11,136 triangles),
exported from Blender 5.2.2 with the kit FBX settings (Tangent Space off). Routes A and B were measured on 2026-10-18,
Route C on 2026-11-03 (the fixture is `build_fixture()` in `tools/tests/blender/test_pbr_texturing_bake.py`). UV
rules for a clean bake (a seam on every hard edge, stacked copies moved out of 0-1, padding per mip) are
`uv-unwrapping`'s: this page is the bake itself.

## Choosing a baker

One rule, in `scripts/bakers.py` (`choose_baker`) and applied by `bake_maps.py --engine auto`:

1. **Detect what works, never assume it** (`detect_bakers()`, or `python bakers.py --maps ...`). Toolbag counts
   only once a probe script ran in it (`toolbag_bake.py --probe`: licence active, desktop session present); the
   Substance baker when `substance3d_baker --help` runs; Cycles always.
2. **The project's baker** wins when it fits the job: the world spec's `tools.mesh_baker` (`toolbag`, `substance`,
   `cycles` or `auto`), set at intake from what was detected; the user's word overrides it. With none, or `auto`:
   Toolbag, then the Substance baker, then Cycles (fastest first, then native features).
3. **The job filters first.** An unattended run (CI, a scheduled task, SSH: no desktop) cannot use Toolbag. A baker
   that lacks a map, or was not measured for it, is skipped: the Substance baker's texture transfer is not
   measured, so base colour, roughness and metallic go to Toolbag or Cycles. With no project baker, thin parts close
   to other surfaces prefer a baker that skips back faces natively (Toolbag, Substance) over Cycles' resolver (1,616 s
   of a 2,241 s bake on a cauldron set).
4. **One baker per texture set or atlas.** Bakers differ slightly in tangents, padding and AO falloff; mixed in one
   atlas the islands show it. A set already baked with one keeps it (`atlas_baker=`).
5. **The same gate for every baker** (`check_outputs()`): the asked size, 16-bit normal and height maps, the
   `<name>_<Suffix>.png` names, and an OpenGL normal map (`pbr_check.py` reads it). A baker that fails, or whose
   maps fail the gate, hands over to the next in the order; the bake report records `baker`, `reason` and
   `fallback`.

| Baker | Maps (measured) | Needs | Fixture time |
|---|---|---|---|
| Marmoset Toolbag (Route C) | normal, AO, curvature, thickness, height; base colour, roughness, metallic transferred | Toolbag 5, a desktop session, FBX in | 1.5 s for the whole job at 512 (0.2 s of baking) |
| Substance 3D baker (Route A) | normal, AO, curvature, thickness, position, ID, world normal, bent normals | Designer installed | under a second per map |
| Blender Cycles (Route B) | normal, AO, curvature; base colour, roughness, metallic copied | Blender | seconds to minutes (the resolver dominates) |

## Before any route

1. Low poly final and triangulated as it exports (a Triangulate modifier with Keep Normals, live during the bake), so
   baker and engine split quads the same way; its custom normals (weighted normals) are part of the tangent basis.
2. High poly overlapping it; floaters (bolts, panels lying on the surface) are fine for raytraced bakes.
3. Rays must start outside the high poly: a cage, or a frontal distance larger than the tallest protrusion. A cage
   that does not enclose it starts rays inside the detail: domes bake as rings and AO comes out black there
   (measured with a 2 cm cage against 6 cm bumps). One that reaches past a narrow gap starts rays inside the
   neighbour: normals pointing into the surface along every channel (a fitted cage, below).
4. Bake at twice the output size and filter down (or the baker's 2 x 2 supersampling): edges of baked detail alias
   otherwise. A plain box filter still steps thin detail at a slight slope to the texel grid: features narrower than
   about 3 texels need a Gaussian pre-filter (below) or a higher texel density.
5. 16-bit output for normal and height maps; padding (dilation) of at least half the island gap.

## Route A: the Substance 3D baker CLI

`substance3d_baker` (`.exe` on Windows) ships with Designer, beside `sbsrender`, in Designer's install folder (it
replaced the old `sbsbaker`). Find it, never assume it: on PATH first (`where substance3d_baker` on Windows, `which`
elsewhere; Adobe's examples assume the tools are on PATH); then Designer's install folder, by default
`C:/Program Files/Adobe/Adobe Substance 3D Designer/` for a Creative Cloud install on Windows (users can install
elsewhere, and a Steam copy lives in its folder under `steamapps/common/`); otherwise ask the user where Designer is.
Measured with version 16.0.7 (build 11787). `--help` lists the commands; `<command> --help` lists each one's options.
On an RTX 3090 Ti every map of the fixture baked in under a second at 512 px on the default GPU backend ("SAL";
`--cpu` forces Embree or SoRa).

The normal map, as it must be run for Blender and Unity:

```text
substance3d_baker Normal.Raytraced --inputs low.fbx --high_scene_paths high.fbx
    --output_path bake --output_name "{scenename}_{bakername}" --output_size 2048,2048
    --output_texture_orientation opengl --output_texture_space tangent_space --recompute_tangents true
    --projection.max_height 0.08 --projection.max_depth 0.08 --projection.normalized_distance false
    --projection.sampling_rate 2x2 --padding_radius 16
```

| Option | Default | Use |
|---|---|---|
| `--output_texture_orientation` | **`directx`** | `opengl` for Blender and Unity. The default bake measured r = -0.63 in `pbr_check.py` (DirectX), the OpenGL one +0.72 |
| `--padding_radius` | **2** px | At least half the island gap (16 at 2048 with 32 px gaps); a diffusion fill (`--enable_mip_diffusion true`) then covers the rest of the gutter |
| `--projection.sampling_rate` | `none` | `2x2` (or `4x4` for fine detail) |
| `--projection.max_height`, `--projection.max_depth` | 0.01, as a share of the bounding box (`--projection.normalized_distance true`) | Absolute scene units with `--projection.normalized_distance false`: the frontal one above the tallest protrusion, the rear one below the deepest recess |
| `--use_cage true --cage_scene_path cage.fbx` | off | A cage mesh instead of the two distances, for awkward shapes |
| `--recompute_tangents` | false | `true`: MikkT tangents, as Unity calculates them on import (the kit FBX carries no tangents) |
| `--projection.smooth_normals` | true | Rays follow averaged normals: no seams at hard edges |
| `--projection.mesh_match_mode` | `match_all` | `match_mesh_name` with `_low` / `_high` suffixes when parts are close enough to catch each other's rays |
| `--output_format`, `--output_size` | `png`, 2048,2048 | PNGs come out 16-bit: RGBA for normal, position and ID maps, grey for AO, curvature and thickness (measured) |

The other maps take the same inputs, output and projection options:

| Map | Command and its own options | Measured on the fixture |
|---|---|---|
| Ambient occlusion | `AmbientOcclusion.Raytraced` (`--secondary.sample_count` 64, `--secondary.max_distance` 1 of the bounding box, `--attenuation linear`, `--enable_ground_plane`) | Contact shadow rings round the bumps, 1.0 on open faces |
| Curvature | `Curvature.Raytraced` (`--secondary.sampling_radius` 0.001 of the bounding box, `--auto_minmax true`) | Flat 0.50, convex bevels 0.81: convex reads **brighter**, although `--help` says concave is brighter |
| Thickness | `Thickness.Raytraced` (rays cast inward; `--maximize_range min_max`) | Faces 1.0, bevels 0.81 |
| Position | `Position.Raytraced` (`--mode all_axes`, `--normalization bsphere`; `--mode single_axis --axis z` for a height gradient) | RGB = XYZ in the bounding sphere |
| World-space normal | `Normal.Raytraced --output_texture_space world_space --output_texture_orientation opengl` (the high poly's), or `Normal.TangentToWorld` (the low poly's, plus an optional normal map) | RGB = XYZ |
| ID | `Color.Raytraced --color_source mesh_index` (one colour per element; `mesh_color` reads FBX material colours, `vertex` vertex colours, `scene_id` one per mesh) | One flat colour per part |
| Height, bent normals, opacity, texture transfer | `Height.Raytraced`, `Normal.BentNormals`, `Opacity.Raytraced`, `TextureTransfer.Raytraced` | Not run here |

`substance3d_baker info low.fbx` lists the meshes, UV sets and bounds the baker sees; `run plan.json` executes a plan
exported from Designer's baking window. Every run prints a harmless USD deprecation warning.

## Route B: Blender Cycles with `scripts/bake_maps.py`

```text
blender -b --factory-startup prop.blend --python-exit-code 1 --python bake_maps.py --
        --low PROP_Crate_Free_A --high Crate_high --size 2048 --out blender/substance/PROP/bake
        --name T_PROP_Crate --maps normal,ao,curvature [--size 1024x2048] [--cage fitted] [--filter-sigma 0.8]
```

What it does, and what was measured (Blender 5.2.2, CPU, 256 px with 2x supersampling: normal 0.08 s, AO 0.31 s,
curvature 0.10 s):

- **Low and highs in the view layer.** An object in an excluded or disabled collection (where bake highs often
  live) is not evaluated: its matrix_world is stale, identity after a load. The script refuses one by name; include
  its collection for the bake.
- **Uniform cage** (default). A copy of the low poly as evaluated, each vertex pushed along its averaged normal. The
  push is measured, not guessed: for each point of the high poly outside the low (its vertices and as many points
  spread over its faces), its distance divided by the share of an averaged-normal push that moves that point of
  the face out (its corners' cosines between vertex and face normal, weighted by where it lies), the largest of
  those, times 1.1. On the fixture: 0.060 out, 0.577 on every cube face, 0.114. Per point, not the mesh's sharpest
  corner: dividing by one global minimum made it 2-3x too deep on upholstery lows (10-12 mm of protrusion got
  23.5-32.8 mm, and the creases and welts tore). The report gives `high_outside` and `high_outside_p99` next to
  the push, so overshoot shows. `--extrusion` overrides it; too small reproduces the rings and black AO above.
- **Fitted cage** (`--cage fitted`, `cage="fitted"`): a push per vertex, for narrow channels (channel-tufted backs,
  pads 10-20 mm apart), concave creases (a seat into its back) and pieces whose high stands far off in places and
  close in others. Per vertex: the protrusion over its faces x 1.15 + 1.5 mm, at least 2 mm, dilated twice; a ray
  marched along its normal raises it past its own high's last exit and caps it half way to the other side of a
  channel (an entry whose nearest low surface faces back along the ray), marching through detail on its own side
  (piping, floaters); then the bake's own rays are traced at seven points of every cage triangle and the culprit
  vertex of any ray starting inside a high is shrunk or grown. Measured on two slabs 12 mm apart with highs 5 mm
  proud on the facing sides (2 mm between them) and a cord floating over one top: a 10 mm uniform cage baked 6,711
  inward-pointing texels (z < 0) on the facing sides, the fitted cage none, with the cord intact. On a 2,400-face
  cushion low against a 153k-vertex high it took 3 s.
- **Cage check.** Every uniform or fitted bake reports `cage_inside`: of the rays traced at seven points per cage
  triangle, how many start inside a high that stands off the low (`neighbour`: the cage reaches across a gap,
  normals point into the surface) or inside the low's own high (`own`: rings, black AO). Both should be 0; `own`
  above 0 means a larger push, `neighbour` above 0 a fitted cage. What is still above 0 after that, the resolver
  fixes (next).
- **Resolver: the texels no cage can bake** (on by default, `resolve=False` to turn it off). Cycles casts one ray
  per texel, from the cage to the low, and keeps its first hit even on a back face; it has no "ignore back faces"
  switch, which the Marmoset Toolbag and Substance bakers both have. Where a thin part sits close to another
  surface (a handle by its body, legs under a pot, two slabs 2 mm apart), no push works: far enough to clear the
  part's own high puts the cage inside its neighbour's. So the faulty texels are re-baked by `resolve_faults()`, the
  way those bakers do. In order:
  1. **Find them two ways.** The polygons where a traced cage ray starts inside a high, grown by one ring (seven
     rays per triangle miss faults between them). Plus the polygons where a 1-sample Cycles normal pre-pass actually
     came out pointing into the surface (the result, not a prediction).
  2. **Re-cast each texel.** Along the averaged normal, from the cage push in front of the low to the same distance
     behind it, back faces stepped over. The first front-facing hit wins; not the one nearest the low, because a bump
     welded onto a body hides the body's surface inside it.
     - No front face in that window: once more, three times wider.
     - Still none: the nearest surface.
     - If even that faces away (the low spans air, between a cauldron's legs): its colour and a flat normal, never
       an inward one.
  3. **Shade the maps itself.** The normal comes from the high's corner normals in the low's MikkTSpace frame, AO
     from 24 cosine rays, and base colour, roughness and metallic from the image or value feeding the high's
     Principled input (through a glTF import's Separate Color too).
  4. **Write them over Cycles' texels, then rebuild the gutter.** Cycles' adjacent-faces margin copies each faulty
     value 16 px out past the island edge, so the gutter beside every resolved polygon, or a polygon next to one, is
     rebuilt from the nearest island-edge texel. Any normal-map gutter texel still pointing into the surface (it has
     no surface of its own, so it can only be a copied fault) takes the nearest edge value.

  Curvature, a node-chain input and the high's own normal-map detail keep Cycles' value, and the report's
  `resolved` lists them under `left_to_cycles`. *Measured* (2026-11-02):
  - **A sphere with every texel re-baked:** the resolver matched Cycles to within the test's tolerances (normals
    median under 1.5 degrees, base colour within 0.02).
  - **The 10 mm uniform cage across the 2 mm slab gap above:** 6,711 inward texels became 0.
  - **A generated cauldron's handle and legs, baked alone at 1024:** inward-pointing texels at each step:

    | Step | Inward texels |
    | --- | --- |
    | Cycles alone | 21,703 |
    | + cage-ray resolver | 5,938 |
    | + wider retry | 5,296 |
    | + one-ring growth | 3,630 |
    | + self-detection pre-pass | 2,374 |
    | + nearest-surface and flat fallback | 1,160 |
    | + gutter clean | **189** |

    Of those 189, 5 are on the surface, 4 of them where the high really turns more than 90 degrees from the low (only
    geometry in the low changes those); 184 are gutter continuing them. In all, 99% fewer.
  - **A four-prop 2048 atlas at supersample 2:** inward texels 48,538 with Cycles alone, 133 with everything above
    (99.7% fewer). It took 2.3 million texels re-baked in 1,616 s of a 2,241 s bake. The resolver is the price of a
    clean bake; turn it off for a draft.

  It runs in Python, one texel at a time (about 0.7 ms each), so it can cost more than the Cycles bake.
  `RESOLVE["grow"] = 0` re-bakes about a third of the texels. `RESOLVE["detect"] = False` skips the pre-pass. A
  first look can bake with `resolve=False`. `cage_inside` keeps counting the cage's faults, and `resolved` says how
  many texels were re-baked, how many fell back to the nearest surface or a flat normal, and how many found nothing.
- **Normal map.** Selected to Active, tangent space, swizzle +X +Y +Z (OpenGL), the low poly's MikkTSpace tangents
  from its active render UV map (or `--uv-layer`). `pbr_check.py` read the bakes as OpenGL, r +0.53 to +0.59, and a
  green-flipped copy as DirectX.
- **AO.** Cycles' AO bake at the world's AO distance, set to `--ao-distance` (default 10% of the low poly's diagonal)
  and restored. AO sees every render-visible object, so `bake()` hides all but the low, its highs and the cage while
  it bakes (an unrelated box over a low took its AO from 0.99 to 0.70, measured) and puts them back; `occluders=`
  keeps the ones whose shadow belongs in the map (a floor under a piece that always stands on it).
- **Curvature.** The high poly's Pointiness through an Emission bake, re-centred on 0.5 and scaled so the 99th
  percentile reaches the ends (`--curvature-gain` fixes the gain, so every piece of a set matches). Pointiness is per
  vertex and sees only connected topology: it needs a dense high poly, and floaters or unapplied booleans show no
  crease where they meet the body (the Substance baker's raytraced curvature does). A plain bevelled or boolean high
  is too sparse: its flat panels read 0.63 instead of 0.5 (measured on a crate), so cut it to a grid of about 2 bake
  texels before its bevels and booleans (the normal map does not need this; curvature does). A gain shared across
  sets saturates a sparser set (every fitting of a crate read all-edge and textured as bare steel): the report gives
  `saturated_share` and a note over 5%. Convex reads brighter, as in route A.
- **Filter.** Baked into Non-Color float images, Gaussian pre-filtered at `--filter-sigma` output texels (default
  0.5; 0 is a plain box) in the supersampled image, then box-filtered down (normals renormalised). A box filter
  alone steps a thin edge at a slight slope by up to a texel (baked piping read as a dashed cord, and moving the
  seams did not help), and a higher supersample barely changes that: on a sharp edge at 1 in 37, sampled 3 x 3 per
  supersample texel as Cycles' jittered samples are, the 50% crossing was off its true line by 0.072 texels rms from
  2x and 0.065 from 4x with a box, 0.043 with sigma 0.5 (edge 1.5 texels wide) and 0.030 with 0.8 (2.2 texels).
  Use 0.8 for upholstery piping and other features under about 3 texels wide (a 0.8-texel Gaussian on the final
  normal and AO maps kept a cord one continuous line without visibly softening the rest of an upholstery map,
  reported 2026-10-24). Cycles does jitter within a pixel when baking: 16 samples gave 17 levels on a sharp edge, 1
  sample 2.
- **Maps.** `--size 1024` or `--size 1024x2048` (`size=(1024, 2048)`): a tall or wide unique piece gets a map of
  its shape, not a square that wastes two thirds or halves the density (a 0.25 x 0.775 m pierced grille baked
  continuous chamfer highlights at 1024 x 2048 and dotted ones at 512 x 1024).
- **Output.** Written straight to 16-bit PNG (`--bits 8`: triangular-dithered 8-bit), no colour management
  involved. `save_png` writes 1-4 channels (grey, grey + alpha, RGB, RGBA: an alpha-cutout card's colour and
  coverage in one map) from rows top to bottom, as `_image_array` returns them: Blender's `Image.pixels` run bottom
  to top, and writing them unflipped turns the map upside down. Everything it adds (images, materials, image nodes,
  the cage) is removed, and the render engine, samples, selection and active object restored.
- **A textured high (a scan, a generated model, a high with its own node material).** `--maps
  normal,ao,basecolor,roughness,metallic` copies what feeds each high's Principled BSDF onto the low through the
  same cage, as Emission bakes: base colour is written sRGB-encoded (baked as linear light, so a linear 0.214 is
  stored 0.5), roughness and metallic as one-channel data; a material with no Principled BSDF bakes the neutral
  value and a note. Cycles' normal bake includes the high's own normal map, so a generated model's normal detail
  carries over. *Measured* on a generated stump (2026-11-02): five maps at 1024, supersample 2, fitted cage, 46 s
  on the CPU; the low with the baked maps read the same as the high from 1.5 m. Pack metallic and 1 - roughness
  into the engine's map afterwards (Unity: MetallicSmoothness).

Blender facts behind it, measured on 5.2.2: `Image.save()` of a float image writes a 16-bit PNG; a 16-bit PNG loaded
under the default sRGB tag is linearised (a stored 0.5 reads 0.214), so read data maps as Non-Color.

## Route C: Marmoset Toolbag

From Blender, one call does it all: export, cage, textures, bake, gate:

```text
blender -b --factory-startup scene.blend --python-exit-code 1 --python bake_maps.py --
        --low PROP_Crate_Free_A --high Crate_high --size 2048 --out blender/substance/PROP/bake
        --name T_PROP_Crate_Free_A --maps normal,ao,curvature --engine toolbag     (or --engine auto --prefer toolbag)
```

On FBX files already exported, `python toolbag_bake.py --low x_low.fbx --high x_high.fbx --cage 0.08 ...`;
`python toolbag_bake.py --probe` checks that Toolbag runs scripts on this machine. Find Toolbag, never assume it:
`TOOLBAG_EXE`, then PATH, then `C:/Program Files/Marmoset/Toolbag 5/toolbag.exe`; otherwise ask the user.

Measured with Toolbag 5.0.3.3 (2026-11-03, Windows 11, RTX 3090 Ti) by introspecting the installed `mset` module and
baking the fixture and a generated rug:

| Fact | Consequence in the scripts |
|---|---|
| `toolbag.exe -hide script.py <args>` runs the script (`sys.argv` = `['toolbag', <args>...]`); the launch returns before the script ends; `mset.quit(code)` closes Toolbag; `__file__` is undefined inside it | `toolbag_job.py` takes the job and result paths from argv; `toolbag_bake.run_job` waits for the result file (written to a temp name, then renamed) |
| Toolbag needs a logged-in desktop session (it opens a window, even with `-hide`) | `choose_baker(unattended=True)` skips it |
| The baker's quick loader (`BakerObject.importModel`) groups by name: `<stem>_low`, `<stem>_high`, one group per stem with Low and High children; several high files with one stem share one High | `bake_maps` exports the low as `tbbake_low` and each high as `tbbake_high`, one FBX each |
| `mset.importModel` plus parenting under High baked the high at the wrong scale (bounds +-56 against 0.56 m: the cube lost its bevels, domes grew) | every mesh goes through the quick loader |
| A `.glb` is not read: the quick loader skips it, `mset.importModel` reports "not found" | FBX only, kit export settings; `build_job` refuses anything else |
| FBX textures do not arrive (`Albedo Map` empty: a transfer bake comes out flat white). `setField("Albedo Map", path)` with a string is ignored without an error | `bake_maps` writes each high material's base colour, roughness and metallic to PNG (`transfer_textures`); the job assigns them as `mset.Texture(path)`, albedo `sRGB = True` |
| The cage is `minOffset` / `maxOffset` on the Low group (`BakerTargetObject`), in scene units: an FBX scene is in centimetres (`getSceneUnitScale()` 0.01). The default (-1000000, automatic) did not enclose the fixture's 6 cm bumps: they baked as crescents; 8 cm baked whole domes | the job converts metres to scene units; `bake_maps` sizes the push with `cage_extrusion()` (0.114 m on the fixture), inward the same |
| Normal maps come out OpenGL (`pbr_check`: opengl, mean length 0.999) with `tangentSpace = "Mikk"` on each mesh by default | no flip; the job sets Mikk and clears the flips explicitly |
| Output: `<outputPath stem>_<suffix>.png`, 16-bit RGB at `outputBits = 16` (AO and curvature too); `getMapPath()` takes display names (`Normals`, `Ambient Occlusion`), not suffixes | the job renames each map's suffix to ours (`T_X_Normal.png`) and checks the files itself |
| `edgePadding = "Custom"` with `edgePaddingSize` is accepted (the help text lists only None, Moderate, Extreme) | the job uses Custom with `--margin`, Extreme if a build refuses it |
| Maps by default suffix: `normal`, `ao`, `curve`, `thickness`, `height`, `albedo`, `roughness`, `metalness` (31 in all, incl. `bentnormal`, `position`, IDs) | `TOOLBAG_MAPS` in `toolbag_bake.py` |

Timings: the fixture, normal, AO and curvature at 512, 0.17 s of baking, 1.5 s for the whole job from Blender
including Toolbag's start; normal and AO at 2048, 0.54 s. A generated rug (a 700k-triangle high onto a 192-triangle
low) baked normal, AO and transferred albedo at 2048 in about 1 s, where Cycles had not finished after 10 minutes.

## Parts that sit close together: an exploded bake

A low made of parts close to one another (a lid on its box, a drawer in its carcass, a bracket on a plank) shares one
cage: where the cage reaches across the gap, rays start inside the other part's high and bake its surface, inverted,
onto this part. Bake every map exploded, AO included: assembled, AO's rays land in the neighbour's high just the
same, and a contact shadow is not worth a wrong surface:

1. One low object, a vertex group per part (`Body`, `Lid`); each high object named `<Part>_high` (floaters
   `<Part>_high_rivets`): `parts_by_name(low, highs)` pairs them and refuses a high with no group. Other vertex
   groups on the low (a wear mask) are ignored. A high may be parented to its own part's high (it moves with it),
   never to another part's: clear that parent, keeping the transform, first (the bake refuses it).
2. `bake_exploded(low, parts, maps=("normal", "ao", "curvature"), size=..., out_dir=..., name=...)`: part k and its
   highs move k x twice the low's diagonal along +X for the maps in `explode` (all of them by default), the bake
   runs, every vertex and object goes back exactly; maps left out of `explode` bake assembled. The default cage floor
   and AO distance are sized from the assembled low (`reference_size`), never from the spread-out parts. Leave "ao" out for
   its contact shadows only when that assembled pass reports `cage_inside` neighbour 0 (parts further apart than the
   cage reaches). CLI: `--explode`, every map exploded.
3. The command line writes the report to `<out>/<name>_bake.json` beside the maps (from a script, save the returned
   `report` there): QA reads `cage_inside` in every pass under `passes`.

Measured (Blender 5.2.2, 2026-10-27): a body and a lid 3 mm apart, highs 1 mm proud and a bump elsewhere that made the
uniform cage 16.5 mm: assembled, 212 of 1,512 traced cage rays started inside the other part's high (`cage_inside`
neighbour); exploded, none, and every vertex and high came back to its exact position. Building the parts and their
highs: `blender-mesh-topology`.

Exploding loses the contact shadow between parts (a bracket on a lid reads placed on, not attached). Put it back in
the material instead: an AO or Ambient Occlusion node in the Blender material bake (`blender-materials.md`), which
sees the assembled parts, or a separate assembled AO pass with each part's own highs only, multiplied in.
Neighbour faults that remain after exploding come from shells that pass into each other inside one part (a hinge
leaf through its knuckle): `--cage fitted` made them worse on a crate (20 to 30 rays); join the shells (a boolean
union, then clean the slivers it leaves) or split them into parts of their own.

## Symptom, cause, fix

| Symptom | Cause | Fix |
|---|---|---|
| Domes bake as rings, AO black on protruding detail | Rays start inside the high poly: cage or frontal distance too small | Enlarge it past the tallest protrusion (`bake_maps.py` measures it; `cage_inside.own` counts the rays) |
| Normals pointing into the surface (black streaks, z < 0) along channels, gaps or creases | The cage reaches past the gap and starts rays inside the neighbouring high (`cage_inside.neighbour` above 0), and Cycles records the back face it hits | `--cage fitted` (the resolver re-bakes what it cannot fix, on by default); in the Substance baker Ignore Backface, a cage mesh, or a frontal distance under half the gap |
| A thin cord or chamfer highlight bakes as a dashed or stepped line | A box filter steps detail under about 3 texels wide at a slight slope; more supersampling barely helps | `--filter-sigma 0.8` (or a 0.8-texel Gaussian on the final map, normals renormalised), or a higher texel density |
| A line along every hard edge | Rays follow split normals (no cage, `smooth_normals` off), or a hard edge without a UV seam | Averaged cage; a seam on every hard edge (`uv-unwrapping`) |
| Normal map lit from below in the engine | Wrong Y convention | OpenGL for Blender and Unity; `pbr_check.py` reports it |
| Detail skewed near the silhouette | Ray directions bend with the averaged normals on a coarse low poly | More support geometry on the low poly, a cage that follows the surface, or the Substance baker's skew map |
| X-shaped shading or seams only in the engine | Baker and engine triangulated or computed tangents differently | Triangulate before baking; MikkT tangents on both sides |
| Colour bleeding at island edges at a distance | Padding smaller than the mips need | `--padding_radius` / `--margin` at least half the island gap |
| Floating parts cast AO shadows on the surface below | AO rays hit the floaters | Bake AO with name matching (`match_mesh_name`) or without the floaters |
| One part's surface shows on its neighbour (a lid's underside on the box top, normals pointing in along a gap) | The parts share a cage that reaches across the gap | `bake_exploded`, or the Substance baker's `match_mesh_name` with `_low` / `_high` names |
| Banding in the normal map's gradients | 8-bit master | 16-bit masters; dithered 8-bit exports |
| A panel line or groove reads as paint, flat in the normal map | Square walls and sharp rims: every ray lands on a face parallel to the low (a 3 mm groove baked exactly 0, 0, 1 across) | Groove walls under about 45 deg (a V or a rounded section) or rims rounded at least 3 texels wide |
| AO darkened by something that is not the piece | Another object rendered during the bake (a second texture set, a floor, a design leftover) | `bake()` hides it; pass `occluders=` only for what should shadow the map |
| Toolbag: domes bake as crescents | Its automatic cage does not reach past the protrusion | Set the cage (`bake_maps` sizes it; `toolbag_bake.py --cage` in metres) |
| Toolbag: transferred base colour is flat white | The high's FBX textures never arrive, or a texture was set as a path string | `bake_maps --engine toolbag` writes and assigns them; by hand `setField(field, mset.Texture(path))` |
| Toolbag: the high bakes oversized, bevels missing | The high came in through `mset.importModel` and was parented under High | Quick-load every file, named `<stem>_low` / `<stem>_high` |
| Toolbag: no result, the launcher times out | A licence or crash dialog, or no desktop session | Run `toolbag_bake.py --probe` with the user at the machine; bake unattended with Cycles |
