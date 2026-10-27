# Blender UV tools: what each one is for, and how to call it from Python

Operator names, parameters and defaults below were read from Blender 5.2.2 LTS itself
(`bpy.ops.uv.<name>.get_rna_type()`, 10 Oct 2026) and match the 5.2 API reference
(https://docs.blender.org/api/current/bpy.ops.uv.html, checked 2026-10-17). Re-read them the same way after an upgrade
rather than trusting this page. Manual: https://docs.blender.org/manual/en/latest/modeling/meshes/editing/uv.html and
https://docs.blender.org/manual/en/latest/editors/uv/index.html

## Contents

- What changed between versions
- Running UV operators from a script
- Unwrapping and projecting
- Straightening and aligning
- Scaling and packing
- Seams
- Checking a layout
- Editor settings worth knowing

## What changed between versions

From the release notes (https://developer.blender.org/docs/release_notes/<version>/modeling/):

| Version | UV change |
|---|---|
| 3.3 | Average Islands Scale gains Scale UV and Shear (`scale_uv`, labelled Non-Uniform in 5.2; `shear`); Minimize Stretch unflips faces; UV Select Similar |
| 3.4 | exact packing margin (Fraction), Align Rotation, Randomize Islands |
| 3.5 | UV Copy and Paste (`uv.copy`, `uv.paste`); Select Similar gains Object and Winding (commit 2b4bafeac6, January 2023; the 3.6 notes list it again) |
| 3.6 | new packer: shape methods, Merge Overlapping, Pack To Original Bounding Box |
| 4.1 | Auto Smooth removed: sharpness is per edge (`sharp_edge`), Shade Smooth by Angle |
| 4.3 | `MINIMUM_STRETCH` (SLIM) unwrap method (the 4.3 notes still caption Angle Based as the default; the 5.2 API lists `method='CONFORMAL'`) |
| 5.0 | UV Sync Selection on by default; Pack To Custom Region; Arrange/Align Islands; Align gains Min/Max; Copy Mirrored UV Coordinates is `uv.copy_mirrored_faces` (4.2-4.5: `mesh.faces_mirror_uv`); a Geometry Nodes Array modifier beside the legacy one, which keeps the `offset_u` / `offset_v` UV offsets |
| 5.2 | Select by Winding, Unwrap Original Bounds, Select Linked can stop at seams |

## Running UV operators from a script

UV operators need the object in Edit Mode with the faces to work on selected. With UV Sync Selection on (the
default in 5.2, `tool_settings.use_uv_select_sync`), the mesh selection is the UV selection:

```python
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
ob.data.uv_layers.active = ob.data.uv_layers["UVMap"]      # the layer every UV operator writes to
bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.001)      # not 0: touching islands fuse across their seam
bpy.ops.object.mode_set(mode="OBJECT")                      # leave Edit Mode before reading ob.data
```

- Margin 0 lets islands land touching along their shared seam; their UVs then coincide and Blender treats them as one
  island (measured on 5.2.2: 7 of 10 random 12-box meshes fused 1-4 pairs; Smart UV Project with `island_margin=0`
  gave 5 charts for a 6-face wall). Unwrap with 0.001; `uv_audit.layout` and `pack` set the real gap afterwards.
  Smart UV Project can still join faces across a corner at 0.001: on a 2 x 3 m wall with a door it made 7 charts
  over four 90 deg edges at every `island_margin` from 0.001 to 0.02. A seam-based unwrap
  (`uv_audit.seams_from_hard_edges`, then `uv.unwrap`) gave 10 charts and none.
- To work on part of a mesh (one face group per `uv.align_rotation` axis, one island to `uv.copy`): Edit Mode, face
  select mode, `mesh.select_all(action="DESELECT")`, then select the group's faces (bmesh `select_set(True)`).
  With sync on, `uv.select_all(action="SELECT")` selects the whole mesh, and face flags written over a stale
  vertex selection pull neighbouring faces into the group.
- Several objects in Edit Mode at once are unwrapped and packed into one shared 0-1 space. Pack objects one at a
  time unless they share a texture.
- In 5.2 the per-corner UVs are `uv_layer.uv[i].vector` (`foreach_get("vector", ...)`); `uv_layer.data` is
  deprecated.
- All of these work headless (`blender -b`): only Project from View needs a 3D view.
- **Always pass `method` to `uv.unwrap`.** An unset operator option is taken from the last call in the scene
  (verified on 5.2.2: a fresh scene unwraps `ANGLE_BASED`, and after one `CONFORMAL` call a bare `uv.unwrap()`
  unwraps `CONFORMAL`), so a script without it depends on whatever ran before.

## Unwrapping and projecting

| Operator | Menu (UV editor or `U` in the 3D view) | Use for | Key parameters (5.2.2 default) |
|---|---|---|---|
| `uv.unwrap` | Unwrap | anything with seams marked: the normal choice | `method` (`ANGLE_BASED`, `CONFORMAL`, `MINIMUM_STRETCH`; listed default `CONFORMAL`, but an unset method is the scene's last one, `ANGLE_BASED` in a fresh scene), `fill_holes` (False), `correct_aspect` (True), `use_subsurf_data` (False), `use_original_bounds` (False: True keeps islands where they were instead of re-packing), `margin_method` (`SCALED`), `margin` (0.001), `no_flip` (False), `iterations` (10, Minimum Stretch only), `use_weights` / `weight_group` (`uv_importance`) / `weight_factor` |
| `uv.smart_project` | Smart UV Project | quick automatic unwraps of hard-surface and architectural pieces; a lightmap UV only with an audit after it (it can join charts across corners; the seam-based unwrap is the default) | `angle_limit` (radians, default 1.1519 = 66 deg; lower = more islands, less distortion), `island_margin` (0: pass 0.001), `margin_method`, `rotate_method` (`AXIS_ALIGNED_Y`), `area_weight` (0), `scale_to_bounds` |
| `uv.lightmap_pack` | Lightmap Pack | one island per face, packed: only for very simple lightmaps | `PREF_CONTEXT` (`SEL_FACES`), `PREF_PACK_IN_ONE` (True), `PREF_NEW_UVLAYER` (False), `PREF_BOX_DIV` (12), `PREF_MARGIN_DIV` (0.1) |
| `uv.follow_active_quads` | Follow Active Quads | straight grids from a quad strip: trims, belts, pipes, stairs (see below) | `mode` (`LENGTH`; `LENGTH_AVERAGE`; `EVEN`) |
| `uv.cube_project` | Cube Projection | one-off boxes and blocky geometry; not kit pieces: it centres on the selection's bounds, so pieces of different sizes start at different phases (5.2.2; `uv_audit.tile_project` instead) | `cube_size` (1.0), `correct_aspect`, `clip_to_bounds`, `scale_to_bounds` |
| `uv.cylinder_project` | Cylinder Projection | pipes, columns, cans, before a cleanup unwrap | `direction`, `align`, `pole`, `seam`, `radius`, `scale_to_bounds` |
| `uv.sphere_project` | Sphere Projection | domes and balls, as a starting point | `direction`, `align`, `pole`, `seam` |
| `uv.project_from_view` | Project from View (Bounds) | decals, flat faces seen head-on, matching a reference image | `orthographic`, `camera_bounds`, `scale_to_bounds` (needs a 3D view) |
| `uv.reset` | Reset | each face fills the whole 0-1 square | - |

Which unwrap method. Measured with `uv_audit.py` on 5.2.2, same seams for every method (from Smart UV Project at
66 deg), angular p95 / area p95 (lower is better for both):

| Mesh | `ANGLE_BASED` | `CONFORMAL` | `MINIMUM_STRETCH`, 10 it. | `MINIMUM_STRETCH`, 200 it. |
|---|---|---|---|---|
| UV sphere, 512 faces | 1.057 / 0.23 | 1.056 / 0.24 | 1.116 / 0.12 | 1.107 / 0.12 |
| Torus, 576 faces | 1.044 / 0.11 | 1.041 / 0.44 | 1.180 / 0.22 | 1.073 / 0.09 |
| Suzanne, subdivided once, 1968 faces | 1.072 / 0.25 | 1.071 / 0.71 | 1.246 / 0.25 | 1.105 / 0.10 |

- **`ANGLE_BASED` is the default to use.** It keeps shapes and spreads density reasonably evenly.
- `CONFORMAL` (the operator's listed default) keeps angles as well but spreads density unevenly on curved islands
  (area p95 up to 3x worse). Pass `method` explicitly in scripts.
- `MINIMUM_STRETCH` gives the most even density, at slightly more angular stretch, but only with enough iterations:
  at the default 10 it is worse than `ANGLE_BASED` on both counts. Use `iterations=100` to `200` (about 1 s at 2k
  faces) when even texel density inside islands matters more than exact shape.
- `uv.minimize_stretch` is not a reliable fix: on the sphere it raised angular p95 from 1.06 to 1.23. Measure
  before keeping its result.
- `fill_holes=True` stops an island with a hole (a window in a wall) from overlapping itself.
- `use_original_bounds=True` re-unwraps islands in place, so a packed layout is not thrown away.
- Pins (`uv.pin`) fix vertices during the next unwrap; Live Unwrap (`SpaceUVEditor.use_live_unwrap`) re-solves while
  you drag pinned vertices.

## Straightening and aligning

Rectangular strips packed straight waste no space and tile or trim without stair-stepping.

- **Follow Active Quads**: select a connected quad strip, make one well-shaped quad active, unwrap or square it
  first, then run `uv.follow_active_quads(mode="LENGTH")`. Every quad of the active quad's island follows it, giving
  a straight grid at each edge's own length; another island needs its own active quad. `LENGTH_AVERAGE` averages each
  edge loop with the unselected faces it runs on into: on an arch soffit cut from its spandrel it gave 0.87-1.31x
  along the arc where `LENGTH` gave 1.000 (measured, 5.2.2). Needs all-quad loops; triangles and n-gons stop it.
- **Align Rotation** (`uv.align_rotation`, `method="AUTO"|"EDGE"|"GEOMETRY"`, `axis`): rotates whole islands. With
  `GEOMETRY` it turns each selected island so the 3D `axis` points along +V, and leaves an island alone when the axis
  is its normal (measured on 5.2.2). For grain along U, pass the axis across the grain, one face group at a time
  (SKILL.md section 5).
- **Copy / Paste UVs** (`uv.copy`, `uv.paste`, 3.5+): copies the selected island's UVs onto the selected faces of an
  identical island, keeping its orientation. One island at a time: pasting 18 islands onto 54 at once collapsed
  faces (angular max 900, measured on 5.2.2). `uv_audit.stack_faces` does the same by face order for duplicated parts.
- **Align** (`uv.align`, `axis="ALIGN_X"|"ALIGN_Y"|"ALIGN_AUTO"|...`): lines selected UV vertices up on one line.
- **Arrange/Align Islands** (`uv.arrange_islands`): lines islands up in a row or column, for trim strips.
- **Snap** to pixels: `SpaceUVEditor.pixel_round_mode` (`CORNER`/`CENTER`) while editing.

## Scaling and packing

| Operator | Use | Key parameters (5.2.2 default) |
|---|---|---|
| `uv.average_islands_scale` | give every island the same texel density, from its 3D area | `scale_uv` (False: keep aspect), `shear` (False) |
| `uv.pack_islands` | fit the islands into the 0-1 tile | `rotate` (True), `rotate_method` (`ANY`; `CARDINAL` = 90 deg steps, `AXIS_ALIGNED`, `AXIS_ALIGNED_X/Y`), `scale` (True: False keeps island sizes), `margin_method` (`SCALED`; `ADD`; `FRACTION`), `margin` (0.001), `shape_method` (`CONCAVE`; `CONVEX`; `AABB`), `merge_overlap` (False: True keeps every overlapping group together, stacks and accidental overlaps alike), `pin` / `pin_method`, `udim_source` (`CLOSEST_UDIM`; 5.0+ `CUSTOM_REGION`) |
| `uv.minimize_stretch` | relax selected islands (can make angles worse: measure) | `fill_holes`, `blend`, `iterations` (0 = until stopped, interactive only: pass a number in scripts) |
| `uv.randomize_uv_transform` | random offset, rotation and scale per island. Only on separate objects (a scatter of loose stones); on a surface that continues across a seam or a kit joint every island jumps against its neighbour | - |

**Padding in pixels.** Measured on 5.2.2 by packing a cube's six islands at 1024 px:

| `margin_method` | `margin` = 8/1024 gives | Use |
|---|---|---|
| `FRACTION` | 8 px to the tile edge, 16 px between islands, exactly | pixel-exact padding: `margin = pad_px / (2 * map_px)` |
| `ADD` | about 8.4 px to the edge, 16.8 px between islands | near enough; depends on the final scale |
| `SCALED` (default) | about 1.6 px to the edge, 3.2 px between islands | relative to island size: avoid when padding matters |

`uv_audit.pack(objects, map_px, pad_px)` does the `FRACTION` conversion (gap `map_px / 64` by default) and packs
each object on its own; `uv_audit.layout` adds the density, stack and fit steps around one such pack.

`shape_method="CONCAVE"` nests islands into each other's gaps (tightest); `AABB` packs bounding boxes (fastest,
keeps straightened strips tidy).

**Rotation turns directional textures.** Measured on 5.2.2 (2026-10-17) with ten boards, five with the grain along U
and five along V: `rotate_method="CARDINAL"` turned 6 of them by 90 deg and `"AXIS_ALIGNED"` 6 (in three other
layouts `AXIS_ALIGNED` turned every board and `CARDINAL` none); `"ANY"` turned islands to any angle (44 and 180 deg).
Pack wood grain, fabric, brushed metal, text and decals with `rotate=False` (`uv_audit.pack` and `layout` default).
`CARDINAL` keeps non-directional straightened strips on the pixel grid; `ANY` packs tighter but steps pixels along
straight edges: organic, non-directional islands only.

## Seams

| Operator | Use |
|---|---|
| `mesh.mark_seam(clear=False)` | mark the selected edges as seams (Edge > Mark Seam, or `Ctrl E`) |
| `ob.data.set_sharp_from_angle(angle=...)`, `ob.data.shade_smooth()`, then `uv_audit.seams_from_hard_edges(objs)` | a plain piece: smooth the faces, keep edges above the angle hard, and seam every hard edge (the normal-map bake rule). The mesh methods (4.1+, checked on 5.2.2) touch this mesh only; the operator `object.shade_smooth_by_angle` re-shades every selected object. Never on a hard-surface stack (Weighted Normal, Harden Normals, custom normals): it moves the designed normals |
| `uv_audit.seams_by_angle(objs, angle=30)` then `uv_audit.seams_from_hard_edges(objs)` | a hard-surface stack, after `uv_audit.apply_stack`: seams by face angle without touching the normals, then on the stack's own hard edges |
| `uv.seams_from_islands(mark_seams=True, mark_sharp=False)` | turn an existing layout's island borders into seams, e.g. after Smart UV Project, before a cleaner `uv.unwrap` |
| `uv.mark_seam` | mark seams from a UV-editor edge selection |
| Select Sharp Edges (`mesh.edges_select_sharp`, `sharpness` in radians) | select candidate seams by face angle: with `mesh.mark_seam`, the seam-by-angle step on a hard-surface stack (`uv_audit.seams_by_angle` does the same without the selection). Never a way to find hard edges: it ignores the edges marked sharp, and finds nothing on a bevel whose segments turn less than the angle |
| `tool_settings.use_edge_path_live_unwrap` | re-unwrap as you draw seams with Select Shortest Path |

## Checking a layout

| Tool | What it shows |
|---|---|
| UV editor overlay Display Stretch (`SpaceUVEditor.show_stretch`, `display_stretch_type="ANGLE"` or `"AREA"`) | faces coloured blue (low) to red (high) by angle or area distortion |
| `uv.select_overlap` | selects UV faces that overlap other faces |
| `uv.select_by_winding(winding="NEGATIVE")` | selects flipped faces (mirrored islands, or folds) |
| `uv.select_similar(type="AREA" / "AREA_3D" / "WINDING" / ...)` | islands or faces like the selected one |
| A checker or colour-grid image (Image > New, `generated_type="UV_GRID"` or `"COLOR_GRID"`) on the material | stretch, density and orientation by eye; size it so a cell is a few centimetres where the player stands closest (*practice*: 2-5 cm for a prop seen within 1 m), or stretch hides inside one cell |
| `uv.export_layout(filepath=..., size=(1024, 1024), mode="PNG")` | the layout as an image, for review or for painting over |
| `scripts/uv_audit.py` | all of the above as numbers, plus texel density in px/m, padding in pixels and hard edges off seams |

## Editor settings worth knowing

- `tool_settings.use_uv_select_sync` (True by default in 5.2): mesh and UV selection are the same.
- `tool_settings.uv_select_mode` (`VERTEX`, `EDGE`, `FACE`) and `use_uv_select_island` for island selection.
- `SpaceUVEditor.show_pixel_coords`: UV coordinates in pixels of the image shown.
- `SpaceUVEditor.lock_bounds`: keep edits inside the image.
