# Visual review against mockups and plans

Numbers catch broken meshes. They do not catch a facade with the windows in the wrong bays, a room that feels
cramped, or a material that reads as plastic. Check `G4` by putting the result next to the thing it was meant to
match, **from the same viewpoint**.

`look` in the checks means the Blender MCP `look` when it is connected; headless, render the same camera with
`qa_measure.py --view` (perspective) or `--render` (orthographic); every run on a file also takes
`--module <grid.module>`. Every `qa_measure` render leaves out collision
shells (`*_COL`) and every LOD but LOD0, in the file and inside collection instances, so a piece shows as players
see it: `--lod n` shows LOD n instead, `--show-collision` the shells, `--hide-object <glob>` hides more by name.

## Viewpoints come from the spec

The spec's `views` list holds named cameras (position, target, lens, and the mockup or diagram each one matches).
Use those, never a viewpoint chosen after seeing the result, so the comparison cannot be framed to flatter it.

| Comparing against | Render with | Settings |
|---|---|---|
| Plan SVG (`plan_<zone>.svg`) | `qa_measure.py --render top --center <zone centre> --extent <zone w> <zone h> --png <out>` | `--px-per-m` defaults to the SVG's `data-px-per-m`; add `--overlay plan_<zone>.svg` |
| Elevation SVG (`elevation_<id>.svg`) | `qa_measure.py --render front` (facade facing south; `back` north, `right` east, `left` west) | Centre on the facade's middle, extent = its width x height; `--overlay` the SVG |
| Interiors (plan or inside wall) | Same as above plus `--clip <m>` | Draws only geometry from `<m>` metres in front of the centre plane onward: a plan centred at floor level with `--clip 2` drops the ceiling; an inside elevation with `--clip` less than the room depth drops the wall behind you |
| A spec view (gates, G4, B5) | `qa_measure.py --view <px py pz tx ty tz lens> --png <view>.png`, or `look` from the same position; add `--hide-collection REF` except for scale checks (B5), so scale figures do not cover the view | Layout and greybox: the default random object colours with outlines. Stages 7+: `--color texture --light flat` (albedo as stored) and `--light studio` (a neutral light), plus `--light lookdev` (below) |
| Materials under light (X5, the look gate) | `qa_measure.py --view ... --light lookdev --png <view>_lookdev.png` from each spec view, and a close-up per material: `--isolate <Piece> --view <a point 1.5-2 m out at eye height, aimed at the piece>` | EEVEE with each material's own nodes, so roughness, metallic and normal maps show (Workbench draws base colour only); a neutral grey world, the scene's own lights hidden, one key light 45 deg above from behind the camera's left; Standard view transform at exposure 0. `--color` does not apply and `--wire` is refused. The same light for every material, so two renders compare fairly |
| Mockup image | `look` from the view's camera position, in material preview for stages 7+ and solid for greybox; headless, the textured `--view` above | Judge intent, not pixels (below) |
| One KIT piece (B1 facing, M3-M8, G4 for a KIT-only task) | In the KIT file (or a single MASTER, whose excluded `KIT` collection `--isolate` brings in for the render only), `qa_measure.py --isolate <Piece>` (every piece sits at the origin, so isolate it) with `--render front --center <x> <y> <z> --extent <w> <h> --px-per-m 200` (200 or more: the default 20 px/m draws a crate in 20 x 20 px) from the piece's `bounds_m`, or `--view` from about 45 deg and 2-3 m out; for G4's detail judgement also a `--view` from the piece's nearest walkable viewing distance at eye height (1.6-1.7 m), as a player first sees it | Add `--wire` for edges (light faces, near-black wire: M5 seams), `--lod n` per LOD (M7), `--show-collision` for the `_COL` shell (M8), `--color texture` from stage 7, `--light lookdev` for chamfers catching light and for materials. A face sealed inside a closed part needs a section, `--clip 0.05` with `--center` at a few depths through the piece (M3). Front is the -Y side: a Free piece's front faces the camera of `--render front`. Feature sizes from the spec's `detail` list: measure them on the 200 px/m orthographic render |
| A UV layer with a checker | A checker image on the material (a setup script, below), then `--color texture --uv-layer <name or index>` | Workbench samples each mesh's **active** UV layer, not its active render layer and not a UV Map node (Blender 5.2.2, measured 2026-10-17). `--uv-layer` makes the named layer active for the render; without it, texture renders draw each mesh through its active render layer (the one exports and bakes use); either way the file's own setting is restored |
| An FBX re-import (E2) | `qa_measure.py --import-fbx ... --render ...` or `--view ...` | `--color random` or `material`: a Path Mode Strip export carries no images, so a texture render has nothing to sample |
| Blender vs Unity (stage 10) | Blender `look` or `qa_measure.py --view` from the view; in Unity, a temporary camera at the same transform (Blender `(x, y, z)` is Unity `(-x, z, -y)`) rendered through `execute_code` to a RenderTexture and saved outside the project, then destroyed | Same field of view: Unity's vertical FOV for a Blender lens is `2 * atan(18 / lens * h / w)` degrees with the default 36 mm sensor (`qa_measure --view` renders 1280 x 720, so 24 mm gives 45.75). The Unity MCP's `manage_camera` positioned capture ignored the FOV, capped at 640 px and wrote into `Assets/Screenshots` (as used 2026-10-16: move the image out and delete the folder). Compare placement, not lighting |
| The final look (L7, after the bake) | The same temporary Unity camera at each spec view, in every lighting state (switched in Play mode with the world's own switch); in a PC world with post-processing, a copy of the reference camera's post-processing layer on it | Judge palette, light colour, contrast and mood against the mockups, `look.references` and `look.lighting_mood`; record `qa_measure.py --image-stats` for each render (luma percentiles, clipped and crushed shares) |

Anything a render needs that the file does not hold (a checker material, a UV layer made active, two pieces placed side
by side for M5's seam) goes in a setup script that runs first in the same session, never saved:
`blender -b --factory-startup <file> --python-exit-code 1 --python setup.py --python qa_measure.py -- ...`.

Before anything is built (planning stages), there is nothing to render: check the SVGs against the spec instead.
Read each piece's rectangle from the SVG text (`data-px-per-m` and `data-frame` give the scale and origin), recompute
every footprint from the spec's position, rotation and size, and save the comparison as a table. No SVG rasteriser
is needed.

The overlay (`--overlay ... --overlay-out x.svg`) crops a generated SVG to its drawn area (its `data-frame`) and
lays it at 50% over the render, so misplaced pieces stand out. Open it in a browser, or screenshot it headless for
the evidence folder with any Chromium browser: `msedge --headless=new --screenshot=<out>.png
--force-device-scale-factor=5 --window-size=<w>,<h> file:///<abs path>.svg`, with `<w>,<h>` the overlay SVG's own
width and height (it is small; the scale factor enlarges it). `chrome` takes the same flags (Edge and Chrome as of
2026-10-16). `qa_measure.py` has no rasteriser.

## What to judge

| Look for | Fail when |
|---|---|
| Layout | A wall, opening or piece is more than half a module from where the plan has it |
| Rhythm | Bays, windows, columns repeat at a different spacing from the elevation |
| Proportion | Storey heights, opening sizes or roof pitch visibly differ from the mockup |
| Silhouette | The skyline against the sky reads differently from the mockup |
| Detail (stage 5+, a piece) | A feature in the piece's `detail` list is missing or off its stated size by more than 10% (house guidance), or a chamfer that should catch light shows none from the nearest walkable distance |
| Materials (stage 7+) | Colour or value clearly differs from the mockup or `look.references` under flat or studio light, or roughness, metal or relief reads wrong under `--light lookdev` (a satin wall as glossy as glass, metal with no reflection, dents where the reference has bumps) |
| Repetition (stage 7+) | *Advisory*, a note only: a tiling texture or a kit piece repeats visibly in a wide view (the same stain, brick or panel recurring in a grid); suggest a variant, a decal, a detail map or a trim to break it |
| Final look (L7) | The lit Unity view's palette, light colour, contrast or mood clearly differs from the mockups, `look.references` and `look.lighting_mood` |
| Scale | A 1.6 m figure looks wrong against doors, railings, furniture |

Without mockups (`world.mockups: false`, views with `matches: null`), judge stages 7+ against the spec's
`look.references`, `look.materials` and `look.wear` when it has them, else `world.style` and the piece `desc`s, from
the spec views rendered with textures: headless, `qa_measure.py --view ... --color texture --light flat` for albedo as
stored and `--light studio` for a neutral light (Workbench with the Standard view transform, drawn through each mesh's
active render UV layer, UV0), plus `--light lookdev` (EEVEE) for roughness, metal and relief. Say in the verdict that
there was no mockup.

Mockups are generated images: they are not exact. Judge intent (rhythm, proportion, mood, palette), not pixel
agreement, and say in the verdict which mockup and view you compared.

Dark renders cannot be judged by eye: an image viewer may auto-level them. Record each render's pixel mean and max
(`qa_measure.py --image-stats <png>...` prints them on the 0-255 scale for any PNG, Unity renders included; its own
renders report them in `renders`), and judge seams and leaks on a brightened copy (`--gain 4` saves `<name>_x4.png`
next to it). To see a state the scene does not hold (a light on, a test capsule), add hidden temporary objects
(`HideFlags.HideAndDontSave`) and destroy them, rather than toggling the real ones; to see another lighting state,
switch to it in Play mode with the world's own switch. In Play mode create them without
the DontSave flags (those survive leaving Play and reopening the scene), and afterwards check
`Resources.FindObjectsOfTypeAll` that none is left.

## Recording

Save each render in the evidence folder (`world/reports/qa/<task>/`, or `world/reports/qa/stage-<n>/` for a whole
stage) named `<view>_<stage>.png`, plus the overlay or sheet, and cite the paths in the check's `evidence`.
