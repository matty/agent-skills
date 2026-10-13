# Mockups (stage 1)

Mockups fix intent before anyone models: mood, palette, rhythm, proportion. They are made with whatever
image-generation tool the host provides (an MCP image tool such as Unity MCP's `generate_image`, or a host's own
image model). If there is none, skip the stage (`world.mockups: false`) and plan from the user's reference images.

Mockups are references, not blueprints. The spec and its generated plans and elevations are what agents build to.

## What to make

| Image | Purpose | Notes |
|---|---|---|
| Hero view per zone | Mood, lighting, overall massing | Eye height 1.7 m, the lens you will reuse in `views` |
| Key interiors | Scale and furnishing density | One per distinct room type |
| Facade, straight on | Bay rhythm and storeys, which become the elevation | Orthographic-looking: "flat front elevation, no perspective, centred" |
| Material swatches per family | Colour, value, wear, so the texturing has a target | "square material swatch sheet, flat lighting, 4 tiles" |
| Props sheet (optional) | Silhouettes for the PROP family | Several props on a neutral ground |

## Prompting for consistency

- Put a **style block** (from `world.style`) at the start of every prompt, word for word: era, materials, palette,
  time of day, weather. Consistency comes from repeating it, not from describing it differently each time.
- Ask for what a modular kit can build: "repeating bays", "consistent storey height", "simple roof lines". Avoid
  details no budget can afford, like ornate one-off carvings everywhere.
- Name the camera: "eye level, 24 mm lens, looking north along the square". Then record the same camera as a spec
  `view`.
- For VR, ask for generous spaces: wide doorways, high ceilings, clear sight lines. Generated rooms tend to be
  cramped.
- Generate 2-4 variants per view, pick one, and keep the prompt. Regenerate a rejected view with a changed prompt
  rather than patching the image.

## Files

`world/mockups/<view>.png` and `<view>.prompt.txt` (full prompt, tool, seed if any, date). The view id matches the
spec's `views[].id`.

## Hand-off

Show the user the set. Note their feedback in the ledger log; the planner reads it with the images in stage 2.
