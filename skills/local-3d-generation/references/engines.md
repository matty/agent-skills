# Image-to-3D engines and the template's settings

*Measured* means run on ComfyUI 0.43.2 (Comfy Desktop, templates 0.11.100) on an RTX 3090 Ti, 24 GB, on
2026-11-02. Template: `3d_pixal3d_trellis2_image_to_model`.

## 1. Which engine

| Engine | Licence | In the template | Notes |
| --- | --- | --- | --- |
| TRELLIS.2 (Microsoft) | MIT: https://github.com/microsoft/TRELLIS.2 | `Boolean (Switch to Trellis2).value=true` | Conditioning on the image only |
| Pixal3D | MIT (since June 2026; check the card): https://huggingface.co/Comfy-Org/Pixal3D | `value=false`, the template's default | Pixel-aligned: estimates the camera field of view with MoGe and conditions on it, so the model lines up with the image |

Both share TRELLIS.2's shape and texture VAEs and the DINOv3 image encoder (`dino_v3_L_naf_fp32`), which carries
Meta's own DINOv3 licence: read it before commercial use.

Ruled out on this setup: Hunyuan3D 2.x (Tencent's licence excludes the UK, EU and South Korea; check where the user
is before offering it, even though ComfyUI ships templates for it).

*Measured* on one input (a barrel, `references/input-images.md`), template defaults, after the models were loaded:

| | TRELLIS.2 | Pixal3D |
| --- | --- | --- |
| Time | 692 s (the 1536 upsample stage alone about 27 s per step, 12 steps) | 284 s |
| Raw mesh before remesh (`GetMeshInfo`) | 47.7M faces | 15.0M faces |
| Orientation | Upright, centred | **Tilted to the camera**: 18.6 degrees about X for a view from about 20 degrees above. `glb_intake.py --upright` levels it |
| Shape | Round in plan, crisp rivets and lid; invented two bung holes on the top | Round once levelled, softer rivets and lid |
| Inside (default `udf` remesh) | A hollow closed vessel: outer skin and an inner cavity wall, each a double sheet (section 3), plus a loose disc inside the base. 10.7 m2 of surface for about 3 m2 of outside | One closed double sheet, no cavity: 4.0 m2 |
| Base colour vs the input | About 15% darker and less saturated (HSV S 0.39 vs 0.48, V 0.35 vs 0.40) | similar |

Pick Pixal3D by default for set dressing (under half the time, no cavity, matches the input's proportions) and
TRELLIS.2 when its sharper small detail matters; run both on a hero piece and compare the four-view renders.

Multi-view (`3d_pixal3d_multi_views`, its own `pixal3d_multiview_int8_convrot`, 5.6 GB, Comfy-Org/Pixal3D): the
conditioning node takes any of front, left, back, right, each square, on a plain or black background, "the same
scale in every view", at a horizontal field of view of 20 degrees by default (long-lens or orthographic views). The
template reads one turnaround sheet through fixed crop boxes; `scripts/multiview.py wire` replaces them with one
image per view. It remeshes with `solid` by default and poses the model to the level front view. *Measured* on a
cushion from a generated turnaround: 211 s, against 175 s for single-image Pixal3D from a three-quarter view of the
same cushion; the multi-view model had the drawn lens-shaped side profile, the single-image one a lopsided profile
with an invented flatter back.

## 2. Settings worth changing

Targets for `comfy.py run --set` (by class when one node has it, else the node id from `comfy.py nodes`; ids are
the template's and can change with a template update):

| Setting | Node (template id) | Default | Effect |
| --- | --- | --- | --- |
| Engine | `Boolean (Switch to Trellis2).value` | false (Pixal3D) | see section 1 |
| Input image | `LoadImage.image` | | a file in the server's input folder; `--upload` puts it there |
| Remove background | `Switch: Remove background.switch` | true | false only when the image already has a clean alpha |
| Crop margin | `ImageCropToMask.pad_factor` | 1.1 | the object's box times this, resized to 1024 |
| Shape detail | `Trellis2UpsampleStage.target_resolution` | 1536 | 1024-2048; the slow stage (see section 1 timings) |
| Seeds | `KSampler` nodes 3 (structure), 18 (shape), 23 (texture), 12 | 56, 42, 42, 43 | change one stage's seed to vary only that stage |
| **Remesh mode** | `RemeshMesh.sign_mode` | `udf` | **set `solid`** (section 3): one closed skin instead of double sheets and hidden walls. `comfy.py` fills the option's own inputs with their defaults |
| Remesh density | `RemeshMesh.resolution` | 768 | voxel grid for the cleaned surface; 512 is about 1M faces before decimation |
| Face count | `DecimateMesh.target_face_count` | 700000 | the GLB's triangles |
| Texture size | `Texture Resolution.value` | 4096 | base colour and metallic-roughness; normal 2048 and AO 1024 are set on their bake nodes |
| Output name | `Save3DAdvanced.filename_prefix` | `3d/ComfyUI` | relative to the server's output folder |

For a high poly that only feeds a bake, the defaults are more than enough: the low poly's own bake, not the
generated textures, makes the final maps. A lower `DecimateMesh.target_face_count` (200k-300k) keeps Blender
responsive; keep about four faces across the smallest feature that should reach the bake
(`blender-mesh-topology`, high-and-low-poly reference).

## 3. What the GLB holds, and the remesh mode

*Measured* with `glb_intake.py` on the barrel from both engines and on two earlier template outputs:

- One mesh, `DecimateMesh`'s triangle count (about 699,000 for 700,000), its own UVs (`UnwrapMesh`, charts for a
  2048 atlas), one material. Maps: base colour 4096, metallic-roughness 4096, normal 2048.
- As imported, vertices are split along every UV seam (glTF stores one vertex per UV): 383,029 vertices, 335
  loose parts and 66,294 open edges on one GLB. Welded by position (the intake does this) it was one closed
  shell. Always weld before judging a generated mesh.
- Size: about 1 unit on its largest axis, no real scale. Y-up in the file; Blender's importer makes it Z-up.
  Pixal3D's are tilted to the camera (section 1).
- Generation is not bit-repeatable: the same seeds gave 47.65M and 47.09M raw faces on two TRELLIS.2 runs.

**Double sheets.** The template's `RemeshMesh` runs in `udf` mode (unsigned distance), which wraps every surface
in two sheets one band apart: rays through the default TRELLIS.2 barrel crossed surfaces in pairs 2.4 mm apart,
and its hollow interior added an inner wall, so a line through it met 8.7 surfaces on average and 64% of the gaps
were thin (`sheets` in the intake report). Hidden surfaces are harmless to a bake from outside, but a low poly
made by reducing this mesh spends most of its budget on them.

| `RemeshMesh` setting (TRELLIS.2 barrel) | Time | Surface | Crossings per line | Thin gaps | Parts |
| --- | --- | --- | --- | --- | --- |
| `udf` (template default) | 692 s | 10.7 m2 | 8.7 | 0.64 | 7 |
| `udf` with `drop_inverted_components` and `drop_enclosed_components` | 694 s | 11.2 m2 | 8.8 | 0.64 | 5 (only the loose disc went) |
| **`solid`** (fill 20) | 107 s (generation cached, remesh onward only) | 2.7 m2 | 2.06 | 0.03 | 1 |

The drops do nothing useful because the sheets are joined at non-manifold edges into one component. `solid`
(an inside/outside graph cut) gives one closed skin and fills the cavity; the look is unchanged. Use it:

```pwsh
python scripts/comfy.py run gen3d.json ... --set RemeshMesh.sign_mode=solid
```

Changing only settings downstream of generation (remesh, decimate, unwrap, texture size) re-runs from that node
when the previous prompt had the same upstream inputs: queue the variants back to back.
