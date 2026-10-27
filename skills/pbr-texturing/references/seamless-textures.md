# Seamless textures on unique UVs and across kit joints

A UV seam is invisible only when the texture on both sides of it describes the same surface at the same point. That
holds when every signal in the texture comes from 3D space (the mesh, its position, a projection) and fails for any
signal laid out in UV space, because two islands that meet on the mesh sit far apart in the texture. This page is the
rule, the routes that follow it, and the check that proves it (`scripts/texture_seams.py`). UV layout itself (where
seams go, padding, tiling phase across kit joints) is `uv-unwrapping`'s.

## The rule

On a unique UV layout, every texture signal comes from one of these, never from UV coordinates:

| Signal | Seamless route | Measured (Blender 5.2.2, 512 px, `texture_seams.py`) |
|---|---|---|
| Mesh detail: normal, AO, curvature, thickness, position | A bake from the high poly with an averaged or fitted cage, MikkTSpace tangents, the low triangulated as it exports, and no island moved, turned or rescaled after the bake (`references/baking.md`) | A clean cage bake's normal map: p95 0.8, nothing showing; the same map after one island was turned 90 deg: 6.2 m of 18 m of seams showing |
| Procedural noise, grain, grunge, wear breakup | Blender nodes on Texture Coordinate > Object (or Generated), baked EMIT into the unique UVs (`references/blender-materials.md`) | Noise on Object coordinates: p50 1.0, p95 1.3, nothing showing; the same noise on UV coordinates: every seam showing, p50 8-14 |
| An image (a photo, a library or Designer tile) | Image Texture node with `projection = "BOX"`, `projection_blend` about 0.2-0.3 (*practice*), on Object coordinates through a Mapping node at the real size, baked; in Painter a fill with tri-planar projection | A smooth image Box-projected: p95 1.1-1.4, nothing showing; the same image on the UVs: every seam showing, p50 9-12 |
| Hand painting | Paint on the mesh in 3D (Painter, Blender's Texture Paint in the 3D viewport): the brush projects across seams | Not measured here |
| Tiling detail on a unique prop (wood grain at close range, fabric weave) | The engine's detail slot on its own tiling (`references/engine-notes.md`), not baked into the unique map through UV coordinates | - |

Painter's tri-planar fill "combines multiple planar projections together and blend them to cover the whole 3D mesh.
It works well for project noises and patterns without creating any visible seams" (Adobe, Substance 3D Painter
documentation, Tri-planar projection,
https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/fill-projections/tri-planar-projection,
checked 2026-10-27). Use UV projection in Painter only for content that follows the UVs on purpose: a trim strip, a
label, a stitched panel's weave.

## Directional materials

- **Wood.** A grain field per board in 3D: Object coordinates through a Mapping node turned so the grain axis runs
  along the board (one node group per board direction, or a face attribute holding each board's axis). End grain
  then shows rings by itself, the grain wraps round the board's edges, and the only seams that show are the real
  joints between boards. Never a grain image on the UVs of a turned or folded board: it jumps at every fold.
- **Fabric and leather.** The weave follows the sewn panels, so it may follow the UVs inside a panel; the panel
  borders are real seams: put the piping or stitching there (`3d-form-design` upholstery) and the UV seam under it.
- **Brushed metal, stone strata.** A direction in 3D (Object coordinates, a Mapping turn), as for wood.

## Tiling textures and kit joints

A tiling material is continuous across faces that face the same way when the UVs come from one box projection with
phase 0 at each piece's pivot (`uv-unwrapping`'s `tile_project`), and across kit joints when the tile divides the
placement step. It breaks at folds where the projection axis changes (corners: covered by a trim or a corner piece)
and anywhere a piece was projected on its own (Cube Projection centres on each selection). `texture_seams.joints`
measures what the player sees at the joints. A busy periodic texture hides a phase jump from it: a 0.1 m jump in
brick read ratios 1.4-2.7, under the limit of 3, yet showed as a zipper of long and short bricks (measured, 5.2.2).
So on tiling layouts the offset itself is the gate: `uv-unwrapping`'s tiling audit (each face's phase, and every seam
inside a surface opening by whole tiles) and QA's per-placement tile phase; `texture_seams` adds what UVs cannot show
(a texture that is not seamless, a bake). Joints whose edges only partly coincide (a T-junction) get a NOTE, not a
verdict: make the edges meet.

## Check: `scripts/texture_seams.py`

```python
import sys; sys.path.insert(0, r"<skill>/scripts")
import texture_seams as ts
ts.seams(ob, "textures/T_PROP_Chest_BaseColor.png")                   # every UV seam of the textured mesh
ts.seams(ob, "textures/T_PROP_Chest_Normal.png", kind="normal")       # in object space, through MikkTSpace
ts.joints(layout_instances, "textures/T_EXT_Brick_BaseColor.png")     # where placed pieces meet
```

Command line: `blender -b --factory-startup --python-exit-code 1 scene.blend --python texture_seams.py --
--objects "PROP_*" --image <map> [--kind normal] [--joints]` (exit 1 when a seam shows).

How it judges: at points along each seam edge it samples half a texel inside each of the two faces (one point in 3D,
two places in the texture) and compares the step across with the texture's own step between texels one apart, from
0.5 to 3.5 texels inside each face, never taken as less than the texture's median step (a busy texture cut at random
shows nothing). Over 3 times: the seam shows (an issue, `visible_m`); 2-3 times: look at it in a close render
(`look_m`); under the floor (0.01 mean absolute step, 2 deg for normals) it never counts. Joints compare each side
with the other side's texture continued across the joint, so a mortar line falling on a joint is not mistaken for a
jump. Edges where the mesh folds more than 89 deg are listed apart (`folds_m`). It samples the full-size map only:
whether the gutters hold at a distance is the padding rule (`uv-unwrapping`, map_px / 64).

| Shows | Cause | Fix |
|---|---|---|
| Colour, roughness or AO seams on a unique prop | A signal from UV space: UV noise, an image on the UVs, 2D painting across a seam | Re-make it from Object coordinates, Box projection or a tri-planar fill; bake again |
| Normal-map seams on smooth edges | An island moved, turned or scaled after the bake; a bake without a cage; tangents that differ from the engine's | Re-bake with the cage on the final UVs and the exported triangulation |
| Normal-map seams on hard edges | The hard edge is not a UV seam, or the bake used split normals for its rays | A seam on every hard edge; an averaged cage (`uv-unwrapping`, `references/baking.md`) |
| Kit joints | Tiling phase off (Cube Projection per piece, a tile that does not divide the grid), or different densities either side | `uv-unwrapping`'s `tile_project` and joint rule |
| Only `look_m` on a busy texture | A random cut through gravel or leaf litter | Look at a close render from where the player stands; move the seam to a fold if it reads |
