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
   (OpenGL), and a metallic-smoothness map, per the channel plan below, or whatever the spec's channel plan says.
3. Trim sheet: `T-TEX-TRIM-LAYOUT` fixes the strip layout first (heights in pixels, which strip is which trim),
   writes it to `blender/substance/<FAMILY>/layout.md` for the trim family, and the UV task works from it.
4. Export maps as PNG at `map_px` into `blender/textures/<FAMILY>/` (`T_<FAMILY>_<Name>_<Map>.png`). If the MCP cannot
   export bitmaps (the community Designer MCP's tools export a package `.sbsar` but no bitmaps, as of 2026-10-17),
   export the `.sbsar` and render its outputs with `sbsrender`, which ships in Designer's install folder:
   `sbsrender render --input <pkg>.sbsar --output-path blender/textures/<FAMILY> --output-format png --set-value
   "$outputsize@10,10"` (10 = log2 of 1024; name the files with `--output-name`, or rename them after). Blender
   cannot read a `.sbsar` without Adobe's add-on, so there is no Blender route. Only without `sbsrender`, ask the
   user to export the outputs from Designer. Checked 2026-10-17 against `sbsrender render --help`, Designer 16.0.7.
5. Build `M_<FAMILY>_<Name>` in the KIT file from those images, so the FBX carries the material name and Unity can
   remap it to the shared material.

## Painter (unique props, user-assisted)

Prepare: low-poly with final UV0, a high-poly or bake cage if needed, exported to
`blender/substance/PROP/<Piece>/`. Add the painting to `flags.user_actions`, give it a ledger task with role `user`
that the prop's later tasks depend on, and wait for the textures. Do not block the other families on it.

## Blender fallback

Procedural node materials per family, baked to images at `map_px` (Cycles bake: route each signal, colour,
metallic, roughness, through an Emission shader and bake EMIT, which gives the exact values with no lighting; or
the DIFFUSE colour-only and ROUGHNESS bake types), then packed per the channel plan below. Tiling materials: bake
one tile of the family's UV0 layout (on a `map_px` map at `texel_density` px/m one tile covers `map_px /
texel_density` metres: 2 x 2 m at 512 px/m on 1024), with patterns that repeat a whole number of times per tile,
then check that 3 x 3 repeats show no seam. Save the node setup in
`blender/substance/<FAMILY>/<FAMILY>_materials.blend` so it can be re-baked.

## Channel plan for Unity's Built-in Render Pipeline

VRChat worlds use the Built-in pipeline's Standard shader (PC) and VRChat's mobile shaders (Quest and iOS). Pack for
what they read, not for a glTF-style ORM map, which Standard wires up wrong:

| Map | Channels | Colour space | Unity slot |
|---|---|---|---|
| `T_<FAMILY>_<Name>_BaseColor.png` | RGB colour, A unused (or opacity for cutout) | sRGB | Albedo |
| `T_<FAMILY>_<Name>_MetallicSmoothness.png` | R metallic, A smoothness (1 - roughness); G and B unused | linear | Metallic, Smoothness Source: Metallic Alpha |
| `T_<FAMILY>_<Name>_Normal.png` (only if the material needs one) | OpenGL (Y+), as Blender bakes it | linear, import as Normal map | Normal Map |
| Occlusion | Usually skipped in a baked world: the lightmap carries it. If used, its own map; Standard reads G | linear | Occlusion |

Source for the Standard slots: https://docs.unity3d.com/2022.3/Documentation/Manual/StandardShaderMaterialParameterMetallic.html
(checked 2026-10-16). Mobile: `VRChat/Mobile/Lightmapped` reads only the base colour (and the lightmap);
`VRChat/Mobile/Standard Lite` reads more, the metallic-smoothness map among them. Check the chosen shader's inputs in
`vrchat-world-sdk-setup` before baking maps it ignores (`vrchat-texture-and-vram` for their import settings).

## Unique detail on a tiling family

A tiling material repeats everything in its tile, so a one-off mark (a seam around a jib door, a plaque, a stain on
one wall) cannot go into the tiling map: it would appear on every bay. Plan it before UVs, in the spec or the brief:
give that face its own UV0 region outside the tiled area and a second material or a trim strip for it, or use a
decal (a separate quad with its own small texture). Never ask the UV task for an island that both "tiles with the
wall" and "carries its own detail": the two conflict.

## Rules that save rework

- Texel density comes from the spec; never "make it look sharp" by raising map size past `map_px`.
- One normal-map convention throughout (OpenGL, as Blender uses; Unity reads it).
- Colour space is decided by the importer, not the file: Blender's PNG writer tags every PNG sRGB and Unity
  ignores the tag (measured 2026-10-16, Blender 5.2.2 / Unity 2022.3.22f1). Unity: sRGB on for base colour, off for
  every linear map (normal, metallic-smoothness, AO), with Alpha Source: Input Texture Alpha for the smoothness.
  Blender: load linear maps as Non-Color.
- Keep source files (`.sbs`, `.spp`, `.blend` node setups) next to the exports; stage 7 QA checks for them.
