# Substance Painter: hero props

Painter is the strongest tool for unique props: layered wear driven by baked mesh maps, smart materials and masks.
From Painter 11.1 its Python API can do the whole job, but an agent reaches it only through a bridge the user installs
(a community Painter MCP server, or a small Python plugin that listens for commands): check for one first (a Painter
tool among the session's MCP tools, or ask). The scripted route below is from the API documentation and was **not run
end to end** when this skill was written (2026-10-18, Painter 11.1.2 with no bridge); the user-assisted route works
with Painter alone.

## What the Python API offers (API 0.3.5, Painter 11.1.0 and later)

Sources: https://experienceleague.adobe.com/en/docs/substance-3d-dev/painter-python/api/substancepainter-package/baking,
https://experienceleague.adobe.com/en/docs/substance-3d-dev/painter-python/api/substancepainter-package/export and
https://experienceleague.adobe.com/en/docs/substance-3d-dev/painter-python/api/substancepainter-package/layerstack-module/edition,
checked 2026-10-18.

| Step | Module and calls |
|---|---|
| Open or create a project from the low poly | `substance_painter.project` (see its page for the creation settings, the normal map format among them) |
| Bake mesh maps | `substance_painter.baking`: `BakingParameters.from_texture_set_name(...)`, the common parameter `HipolyMesh` (a file URL), per-map settings through `baker(usage)`, `BakingParameters.set(...)`, then `bake_async(texture_set)`; progress through the baking events |
| Layers | `substance_painter.layerstack`: `insert_fill(position)`, `set_material_source(...)` with a resource found by `substance_painter.resource.search(...)`, `insert_smart_material(position, resource_id)`, `insert_smart_mask(...)` |
| Export | `substance_painter.export.export_project_textures(json_config)`: `exportPath`, `exportPresets` (each map's `fileName` and `channels`, mapping source maps to destination channels), `exportList`, `exportParameters` (`fileFormat`, `bitDepth`, `dithering`, `sizeLog2`, `paddingAlgorithm`, `dilationDistance`); `list_predefined_export_presets()` and each preset's `list_output_maps()` to find a Unity one |

For Unity's Built-in Standard, use the predefined preset whose output maps are an albedo, a metallic-smoothness and a
normal map (find it by its `list_output_maps()`, not by its name), with each map's `fileName` set to the
`T_<FAMILY>_<Name>_<Map>` name, PNG, 8-bit with dithering (16-bit for the normal master), a padding of at least half
the island gap. `pbr_check.py` accepts Painter's `AlbedoTransparency` name as base colour.

## The user-assisted route (works today)

1. Prepare: the low poly with final UV0 (seams on hard edges, padding: `uv-unwrapping`), triangulated as exported,
   and the high poly, both exported to FBX; or bake the mesh maps first (`references/baking.md`) and hand them over.
2. Tell the user exactly what to make: the material targets (values from `references/pbr-values.md`, art direction,
   wear story from `references/wear-and-variation.md`), the project's normal map format (OpenGL), the export preset
   and file names above, and where the files go. Fills that carry noise or a pattern use tri-planar projection, not
   UV projection, and hand painting happens on the mesh, so nothing breaks at a seam
   (`references/seamless-textures.md`).
3. Do not block other work on it: a planned world records it as a user action with a task the prop's later tasks
   depend on.
4. When the maps arrive, run `pbr_check.py`, `texture_seams.py` and a look-dev render before anything uses them, and
   keep the `.spp` beside the exports.
