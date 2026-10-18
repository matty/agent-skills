# Substance Designer: tiling materials and trim sheets through its MCP

Designer is the strongest route for tiling materials, trim sheets and procedural masks. Agents drive it through a
Designer MCP server (the community Substance-3D-Designer-MCP, tested here with Designer 16.0.7); bitmaps come out
through `sbsrender`, which ships in Designer's install folder. The route below was not run end to end for this skill
(Designer was closed): the tool names are the server's, the `sbsrender` options are checked against its `--help`
(16.0.7, 2026-10-18).

## Order of work

1. `sd_ping`: the server, the bridge and the plugin must all answer; Designer must be running with the plugin loaded.
2. `sd_get_capabilities` before anything else. Observed with this server: graph, node, connection and parameter
   capabilities report available only once a graph with a node is open (they are probed on the current graph), which
   is not an incompatibility.
3. Never guess a node definition, property or library URL: find them with `sd_search_library`,
   `sd_list_node_definitions` and `sd_list_node_properties`, then build with `sd_create_package`, `sd_create_graph`,
   `sd_create_node` / `sd_create_instance_node`, `sd_connect_nodes`, `sd_set_node_parameter` and
   `sd_create_graph_output`. For many edits at once, `sd_validate_graph_patch` then `sd_apply_graph_patch`.
4. One package per family, one graph per material; outputs named after the map they become (`BaseColor`,
   `MetallicSmoothness`, `Normal`), so the export can name files from them.
5. Pack for the engine inside the graph: metallic into R and smoothness (an inverted roughness) into A of one output
   (`references/engine-notes.md`); look up the merge and invert nodes rather than naming them from memory.
6. The normal output must be OpenGL for Blender and Unity: find the format parameter on the normal node with
   `sd_list_node_properties` (the baker that ships with Designer defaults to DirectX, measured) and confirm the
   exported map with `pbr_check.py`, which reads the convention from the pixels.
7. Mesh maps for trims and props come from the Substance baker (`references/baking.md`); bring them in with
   `sd_import_bitmap`.
8. Save (`sd_save_package` / `sd_save_package_as`) and keep the `.sbs` next to the exports.

## Export bitmaps

The community server exports a package to `.sbsar` (`sd_export_package_sbsar`) but no bitmaps (as of 2026-10-17), so
render the `.sbsar` with `sbsrender`:

```text
sbsrender render --input <pkg>.sbsar --output-path blender/textures/<FAMILY>
    --output-name 'T_<FAMILY>_<Name>_{outputNodeName}' --output-format png --output-bit-depth 16
    --set-value '$outputsize@10,10'
```

- `$outputsize@10,10` is log2 of the size per axis (10 = 1024). Keep it in **single** quotes: in PowerShell and in
  bash, `"$outputsize@10,10"` expands `$outputsize` as an (empty) variable and passes only `@10,10`.
- `--output-name` takes the `{outputNodeName}` pattern (the default is `{inputName}_{inputGraphUrl}_{outputNodeName}`);
  `--input-graph` picks one graph of a package with several, `--input-graph-output` (or `--input-graph-output-usage`)
  one output.
- `--output-bit-depth` takes `8`, `16` or float depths; 16 for normal and height masters.
- Blender cannot read a `.sbsar` without Adobe's add-on, so the PNGs are what the material is built from.
- Without `sbsrender`, ask the user to export the outputs from Designer.
