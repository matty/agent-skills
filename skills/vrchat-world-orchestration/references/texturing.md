# Texturing (stage 7)

Minimal guidance until texturing has its own skill. The goal is the material plan in the spec: 1-3 materials per
family named `M_<FAMILY>_<Name>`, at the family's `map_px`, matching the mockup swatches.

## Pick the tool

| Situation | Use |
|---|---|
| Substance Designer installed and its MCP answers `sd_ping` | Designer for tiling materials and trim sheets |
| Substance Painter installed | Unique hero props only. Painter has no automation here: the agent prepares bake-ready meshes and the user paints, or the prop falls back to Designer or Blender |
| Neither | Blender procedural materials baked to images |

## Designer (tiling and trim)

1. `sd_get_capabilities` first: what this build of the MCP can do, including whether it can export bitmaps. Never
   guess node definitions or properties; look them up (`sd_search_library`, `sd_list_node_definitions`,
   `sd_list_node_properties`).
2. One package per family in `blender/substance/<FAMILY>/`, one graph per material, outputs base colour, normal
   (OpenGL), and a packed ORM-style map, or whatever the spec's channel plan says.
3. Trim sheet: fix the strip layout first (heights in pixels, which strip is which trim), write it to
   `blender/substance/TRIM/layout.md`, and give it to the UV task.
4. Export maps as PNG at `map_px` into `blender/textures/<FAMILY>/` (`T_<FAMILY>_<Name>_<Map>.png`). If the MCP cannot
   export bitmaps, export the `.sbsar` and either ask the user to export outputs from Designer, or bake the `.sbsar`
   through the Blender fallback.
5. Build `M_<FAMILY>_<Name>` in the KIT file from those images, so the FBX carries the material name and Unity can
   remap it to the shared material.

## Painter (unique props, user-assisted)

Prepare: low-poly with final UV0, a high-poly or bake cage if needed, exported to
`blender/substance/PROP/<Piece>/`. Record a ledger task with role `user` and wait for the textures. Do not block the
other families on it.

## Blender fallback

Procedural node materials per family, baked to images at `map_px` (Cycles bake: diffuse colour only, normal,
roughness, AO), then packed. Tiling materials: bake on a 1 x 1 m plane with tiling UVs, then check that 3 x 3 repeats
show no seam. Save the node setup in `blender/substance/<FAMILY>/<FAMILY>_materials.blend` so it can be re-baked.

## Rules that save rework

- Texel density comes from the spec; never "make it look sharp" by raising map size past `map_px`.
- One normal-map convention throughout (OpenGL, as Blender uses; Unity reads it).
- Linear data (normal, roughness, metallic, AO) saved without colour management; base colour in sRGB.
- Keep source files (`.sbs`, `.spp`, `.blend` node setups) next to the exports; X6 checks for them.
