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
   (measured with a 2 cm cage against 6 cm bumps).
4. Bake at twice the output size and box-filter down (or the baker's 2 x 2 supersampling): edges of baked detail
   alias otherwise.
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
        --name T_PROP_Crate --maps normal,ao,curvature
```

What it does, and what was measured (Blender 5.2.2, CPU, 256 px with 2x supersampling: normal 0.08 s, AO 0.31 s,
curvature 0.10 s):

- **Cage.** A copy of the low poly as evaluated, each vertex pushed along its averaged normal. The push is measured,
  not guessed: how far the high poly stands outside the low surface (0.060 on the fixture), divided by the smallest
  cosine between a vertex's averaged normal and its faces (0.577 at a cube corner), times 1.1: 0.114. `--extrusion`
  overrides it; too small reproduces the rings and black AO above.
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
- **Output.** Baked into Non-Color float images, box-filtered down (normals renormalised) and written straight to
  16-bit PNG (`--bits 8`: triangular-dithered 8-bit), no colour management involved. Everything it adds (images,
  materials, image nodes, the cage) is removed, and the render engine, samples, selection and active object restored.

Blender facts behind it, measured on 5.2.2: `Image.save()` of a float image writes a 16-bit PNG; a 16-bit PNG loaded
under the default sRGB tag is linearised (a stored 0.5 reads 0.214), so read data maps as Non-Color.

## Symptom, cause, fix

| Symptom | Cause | Fix |
|---|---|---|
| Domes bake as rings, AO black on protruding detail | Rays start inside the high poly: cage or frontal distance too small | Enlarge it past the tallest protrusion (`bake_maps.py` measures it) |
| A line along every hard edge | Rays follow split normals (no cage, `smooth_normals` off), or a hard edge without a UV seam | Averaged cage; a seam on every hard edge (`uv-unwrapping`) |
| Normal map lit from below in the engine | Wrong Y convention | OpenGL for Blender and Unity; `pbr_check.py` reports it |
| Detail skewed near the silhouette | Ray directions bend with the averaged normals on a coarse low poly | More support geometry on the low poly, a cage that follows the surface, or the Substance baker's skew map |
| X-shaped shading or seams only in the engine | Baker and engine triangulated or computed tangents differently | Triangulate before baking; MikkT tangents on both sides |
| Colour bleeding at island edges at a distance | Padding smaller than the mips need | `--padding_radius` / `--margin` at least half the island gap |
| Floating parts cast AO shadows on the surface below | AO rays hit the floaters | Bake AO with name matching (`match_mesh_name`) or without the floaters |
| Banding in the normal map's gradients | 8-bit master | 16-bit masters; dithered 8-bit exports |
