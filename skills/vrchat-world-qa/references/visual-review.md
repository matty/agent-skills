# Visual review against mockups and plans

Numbers catch broken meshes. They do not catch a facade with the windows in the wrong bays, a room that feels
cramped, or a material that reads as plastic. Check `G4` by putting the result next to the thing it was meant to
match, **from the same viewpoint**.

## Viewpoints come from the spec

The spec's `views` list holds named cameras (position, target, lens, and the mockup or diagram each one matches).
Use those, never a viewpoint chosen after seeing the result, so the comparison cannot be framed to flatter it.

| Comparing against | Render with | Settings |
|---|---|---|
| Plan SVG (`plan_<zone>.svg`) | `qa_measure.py --render top --center <zone centre> --extent <zone w> <zone h>` | `--px-per-m` as the SVG's `data-px-per-m`; add `--overlay plan_<zone>.svg` |
| Elevation SVG (`elevation_<id>.svg`) | `qa_measure.py --render front` (facade facing south; `back` north, `right` east, `left` west) | Centre on the facade's middle, extent = its width x height, `--px-per-m` as the SVG's; `--overlay` the SVG |
| Interiors (plan or inside wall) | Same as above plus `--clip <m>` | Draws only geometry from `<m>` metres in front of the centre plane onward: a plan centred at floor level with `--clip 2` drops the ceiling; an inside elevation with `--clip` less than the room depth drops the wall behind you |
| A spec view (gates, G4, B5) | `qa_measure.py --view <px py pz tx ty tz lens> --png <view>.png`, or Blender MCP `look` from the same position; add `--hide-collection REF` except for scale checks (B5), so scale figures do not cover the view | Headless perspective render, objects in random colours with outlines; with mockups, compare stages 7+ in material preview through `look` |
| Mockup image | Blender MCP `look` from the view's camera position | Material preview for stages 7+, solid for greybox |
| A UV layer with a checker | Workbench, `color_type = 'TEXTURE'` | Workbench samples the mesh's **active render** UV layer, not a UV Map node: set `uv_layers[...].active_render = True` on the layer to check (and restore it), or a UV2 checker silently shows UV0 |
| Blender vs Unity (stage 10) | Blender `look` from the view; Unity MCP `manage_camera` screenshot from the same transform (Blender `(x, y, z)` is Unity `(-x, z, -y)`) | Same field of view; compare placement, not lighting |

Before anything is built (planning stages), there is nothing to render: check the SVGs against the spec instead.
Read each piece's rectangle from the SVG text (`data-px-per-m` and `data-frame` give the scale and origin), recompute
every footprint from the spec's position, rotation and size, and save the comparison as a table. No SVG rasteriser
is needed.

The overlay (`--overlay ... --overlay-out x.svg`) crops a generated SVG to its drawn area (its `data-frame`) and
lays it at 50% over the render, so misplaced pieces stand out. Open it in a browser, or screenshot it headless for
the evidence folder with any Chromium browser: `msedge --headless=new --screenshot=<out>.png
--force-device-scale-factor=5 --window-size=<w>,<h> file:///<abs path>.svg`, with `<w>,<h>` the overlay SVG's own
width and height (it is small; the scale factor enlarges it). `chrome` takes the same flags. `qa_measure.py` has no
rasteriser.

## What to judge

| Look for | Fail when |
|---|---|
| Layout | A wall, opening or piece is more than half a module from where the plan has it |
| Rhythm | Bays, windows, columns repeat at a different spacing from the elevation |
| Proportion | Storey heights, opening sizes or roof pitch visibly differ from the mockup |
| Silhouette | The skyline against the sky reads differently from the mockup |
| Materials (stage 7+) | Colour, value or roughness clearly differs from the mockup under neutral light |
| Scale | A 1.6 m figure looks wrong against doors, railings, furniture |

Without mockups (`world.mockups: false`, views with `matches: null`), judge stages 7+ against the spec's
`world.style` and the piece `desc`s, from the spec views rendered with textures: headless, a Workbench render with
`scene.display.shading.color_type = 'TEXTURE'` (it samples each mesh's active render UV layer: UV0) or a low-sample
EEVEE / Cycles render. Say in the verdict that there was no mockup.

Mockups are generated images: they are not exact. Judge intent (rhythm, proportion, mood, palette), not pixel
agreement, and say in the verdict which mockup and view you compared.

## Recording

Save each render under `world/reports/qa/<task>/` named `<view>_<stage>.png`, plus the overlay or sheet, and cite the
paths in the check's `evidence`.
