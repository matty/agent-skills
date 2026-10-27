# Baking mesh maps from a high poly

Two routes, both measured on 2026-10-18 on the same fixture: a 1 m low-poly cube (12 triangles, hard edges, each
face its own UV island) and a bevelled, subdivided high-poly cube with half-sunk spheres standing 6 cm proud (11,136
triangles), exported from Blender 5.2.2 with the kit FBX settings (Tangent Space off). UV rules for a clean bake (a
seam on every hard edge, stacked copies moved out of 0-1, padding per mip) are `uv-unwrapping`'s: this page is the
bake itself.

## Before either route

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
  above 0 means a larger push, `neighbour` above 0 a fitted cage.
- **Normal map.** Selected to Active, tangent space, swizzle +X +Y +Z (OpenGL), the low poly's MikkTSpace tangents
  from its active render UV map (or `--uv-layer`). `pbr_check.py` read the bakes as OpenGL, r +0.53 to +0.59, and a
  green-flipped copy as DirectX.
- **AO.** Cycles' AO bake at the world's AO distance, set to `--ao-distance` (default 10% of the low poly's diagonal)
  and restored.
- **Curvature.** The high poly's Pointiness through an Emission bake, re-centred on 0.5 and scaled so the 99th
  percentile reaches the ends (`--curvature-gain` fixes the gain, so every piece of a set matches). Pointiness is per
  vertex and sees only connected topology: it needs a dense high poly, and floaters or unapplied booleans show no
  crease where they meet the body (the Substance baker's raytraced curvature does). Convex reads brighter, as in
  route A.
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

Blender facts behind it, measured on 5.2.2: `Image.save()` of a float image writes a 16-bit PNG; a 16-bit PNG loaded
under the default sRGB tag is linearised (a stored 0.5 reads 0.214), so read data maps as Non-Color.

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
   runs, every vertex and object goes back exactly; maps left out of `explode` bake assembled. Leave "ao" out for
   its contact shadows only when that assembled pass reports `cage_inside` neighbour 0 (parts further apart than the
   cage reaches). CLI: `--explode`, every map exploded.
3. The command line writes the report to `<out>/<name>_bake.json` beside the maps (from a script, save the returned
   `report` there): QA reads `cage_inside` in every pass under `passes`.

Measured (Blender 5.2.2, 2026-10-27): a body and a lid 3 mm apart, highs 1 mm proud and a bump elsewhere that made the
uniform cage 16.5 mm: assembled, 212 of 1,512 traced cage rays started inside the other part's high (`cage_inside`
neighbour); exploded, none, and every vertex and high came back to its exact position. Building the parts and their
highs: `blender-mesh-topology`.

## Symptom, cause, fix

| Symptom | Cause | Fix |
|---|---|---|
| Domes bake as rings, AO black on protruding detail | Rays start inside the high poly: cage or frontal distance too small | Enlarge it past the tallest protrusion (`bake_maps.py` measures it; `cage_inside.own` counts the rays) |
| Normals pointing into the surface (black streaks, z < 0) along channels, gaps or creases | The cage reaches past the gap and starts rays inside the neighbouring high (`cage_inside.neighbour` above 0) | `--cage fitted`; in the Substance baker a cage mesh, or a frontal distance under half the gap |
| A thin cord or chamfer highlight bakes as a dashed or stepped line | A box filter steps detail under about 3 texels wide at a slight slope; more supersampling barely helps | `--filter-sigma 0.8` (or a 0.8-texel Gaussian on the final map, normals renormalised), or a higher texel density |
| A line along every hard edge | Rays follow split normals (no cage, `smooth_normals` off), or a hard edge without a UV seam | Averaged cage; a seam on every hard edge (`uv-unwrapping`) |
| Normal map lit from below in the engine | Wrong Y convention | OpenGL for Blender and Unity; `pbr_check.py` reports it |
| Detail skewed near the silhouette | Ray directions bend with the averaged normals on a coarse low poly | More support geometry on the low poly, a cage that follows the surface, or the Substance baker's skew map |
| X-shaped shading or seams only in the engine | Baker and engine triangulated or computed tangents differently | Triangulate before baking; MikkT tangents on both sides |
| Colour bleeding at island edges at a distance | Padding smaller than the mips need | `--padding_radius` / `--margin` at least half the island gap |
| Floating parts cast AO shadows on the surface below | AO rays hit the floaters | Bake AO with name matching (`match_mesh_name`) or without the floaters |
| One part's surface shows on its neighbour (a lid's underside on the box top, normals pointing in along a gap) | The parts share a cage that reaches across the gap | `bake_exploded`, or the Substance baker's `match_mesh_name` with `_low` / `_high` names |
| Banding in the normal map's gradients | 8-bit master | 16-bit masters; dithered 8-bit exports |
