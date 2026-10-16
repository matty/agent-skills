# Subagent briefs

A subagent starts with nothing: no conversation, no ledger, no memory of earlier attempts. The brief is everything
it knows. Write it to `world/briefs/<task>.md` and pass the whole text as the subagent's prompt.

## Template

```markdown
# <task id>: <title>

## Goal
<one or two sentences: what exists when you are done>

## Load these skills first
- <skill name>: <what for>
(If a skill is not available, say so in your report and follow the fallback below.)

## Inputs (read only)
- world/spec.yaml: sections <...>. Excerpt:
  <paste the relevant YAML: the family, the pieces, budgets, grid>
- <files, diagrams, mockups to work from>

## You may write ONLY
- <exact files or folders>
- <@unity / @blender-live if this task owns that editor for its duration; otherwise do not touch it>
Anything else is out of bounds, including files you think need fixing. Report those instead.

## Steps
1. ...

## Tools and hosts
- Blender CLI: <path>. Run headless: blender -b --factory-startup <file> --python <script>.py, and save at the end
  (set bpy.context.preferences.filepaths.save_version = 0 first, so no .blend1 backup is written).
- <Blender MCP / Unity MCP / Substance MCP if this task owns them>

## Acceptance checks (QA will run these; run them yourself first)
- <check id and plain words, with numbers from the spec>

## Fallbacks
- <what to do if a skill or tool is missing>

## Report
End your final message with exactly this block, and nothing after it:

    report:
      task: <task id>
      attempt: <n>
      status: complete | partial | blocked
      outputs: [<files written>]
      measurements: {<check id>: "<measured value>"}
      skills_used: [<names>]
      fallbacks_used: [<what and why>]
      issues: [<anything QA or the master should know>]
```

On a retry, add a `## Previous attempt` section with the QA verdict's `fixes`, word for word, and say that this is
attempt N of 3.

## QA brief

```markdown
# QA <task id> (attempt <n>)

Load `vrchat-world-qa`. You did not build this and must not change it.
Stage: <n>. Checklist: <letter> plus G1-G5.
Builder's brief: world/briefs/<task>.md   Builder's report: world/reports/<task>.yaml
Spec excerpt: <same as the builder's>
Writable files of the builder (for G2): <list>. Dispatched at: <UTC time from the ledger log>
Master edits since the builder returned (not the builder's doing): <file and what changed, or none>
Views and diagrams to compare (G4): <view ids, svg paths>
Save evidence under world/reports/qa/<task>/ and end with the verdict block from vrchat-world-qa.
```

## Filled example: stage 5, one KIT file

```markdown
# T-MOD-EXT: Model the exterior kit

## Goal
Every EXT piece in blender/kits/KIT_Arch_Exterior.blend has final geometry in place of its greybox, inside the
same collection, with the same name, pivot and extents. kit_status = modelled on each piece collection.

## Load these skills first
- blender-mesh-topology: clean low-count topology for the window and door surrounds
- blender-kit-library: kit piece rules
- blender-to-unity: mesh hygiene before export

## Inputs (read only)
- world/spec.yaml excerpt:
    grid: {module: 1.0}
    families: {EXT: {thickness: 0.3, materials: [M_EXT_Brick, M_EXT_Stone]}}
    budgets: {piece_tris: {EXT: 800}}
    pieces: [EXT_Wall_2x3_A (box), EXT_Window_2x3_A (box), EXT_Door_2x3_A (box)]
- world/mockups/hero_square.png, world/diagrams/elevation_square_north_row.svg

## You may write ONLY
- blender/kits/KIT_Arch_Exterior.blend

## Steps
1. Open the file headless. For each piece, model the final mesh at the collection origin, replacing the greybox
   mesh data; keep the object name.
2. Keep the footprint exactly 2 x 0.3 x 3 m; window and door openings where the greybox has them.
3. Assign M_EXT_Brick and M_EXT_Stone only. Apply transforms. Set coll["kit_status"] = "modelled". Save.

## Tools and hosts
- Blender CLI: C:/Users/me/.blender/blender-5.2.2/blender.exe (headless only; the live Blender belongs to the
  integrator)

## Acceptance checks
- M1 names, identity transforms, pivot at the bottom-left corner, extents match Size
- M2 LOD0 <= 800 tris per piece
- M3 no n-gons, no edges shared by 3+ faces, no loose vertices
- M5 the three pieces share boundary vertices when snapped side by side

## Fallbacks
- No blender-mesh-topology: plain quads, no n-gons, merge by distance, and keep bevels to the front face only.

## Report
(the block above)
```

## Filled essentials for the other stages

Expand each into the template: these are the parts that differ per stage.

**Stage 1, T-MOCK-01 (concept artist).** Goal: hero view per zone, key interiors, one swatch sheet per family idea,
a straight-on view of each kit facade. Load: none (see `mockups.md` in this skill, pasted into the brief). Writes:
`world/mockups/`. Checks: C1-C4. Fallback: none; the stage is skipped without an image tool.

**Stage 2, T-SPEC-01 (planner).** Goal: a `spec.yaml` that validates, diagrams generated, stage 3-13 tasks drafted.
Load: none (paste `world-spec.md`). Inputs: brief, intake answers, mockups. Writes: `world/spec.yaml`,
`world/diagrams/`, `world/briefs/draft-tasks.yaml` (the master copies tasks into the ledger). Checks: S1-S7.

**Stage 3, T-KIT-PLAN (planner).** Goal: complete `pieces`, `families`, `assemblies`, with corners, ends and trims.
Writes: `world/spec.yaml`. Checks: P1-P4, S1, S3.

**Stages 1-3 in small mode, T-PLAN-01 (planner).** The three briefs above merged: mockups if `world.mockups` is true,
then a validating spec with pieces, families and assemblies complete, diagrams generated, stage 4-13 tasks drafted.
Load: none (paste `world-spec.md`, and `mockups.md` when there are mockups). Writes: `world/spec.yaml`,
`world/diagrams/`, `world/briefs/draft-tasks.yaml`, plus `world/mockups/` when there are mockups. Checks: S1-S7,
P1-P4, plus C1-C4 with mockups.

**Stage 4, T-GREY-EXT (kit modeller).** Goal: every EXT piece as a collection of box geometry at its exact extents,
pivot bottom-left, openings cut, `kit_status = grey`. Load: `blender-kit-library`. Writes:
`blender/kits/KIT_Arch_Exterior.blend`. Checks: B1. Fallback: the kit rules in `world-spec.md`.

**Stage 4, T-GREY-MASTER (integrator, live Blender or headless without the Blender MCP).** Goal: MASTER laid out from `zones[].placements` with linked
pieces and assemblies, relative paths, scale figures per zone. Writes: `blender/MASTER.blend`. Checks: B2-B7, with
overlays against `plan_<zone>.svg` and `elevation_<id>.svg`.

**Stage 6, T-UV-EXT (UV artist).** Goal: UV0 tiling at 512 px/m, UV2 non-overlapping with padding for a 1024 map,
`kit_status = uv`. Load: `uv-unwrapping` (+ `rizomuv-uv-pipeline` if RizomUV is installed). Writes: the KIT file.
Checks: U1-U6. Fallback: Smart UV Project + texel scaling, flagged for extra QA.

**Stage 7, T-TEX-EXT (texture artist).** Goal: `M_EXT_Brick`, `M_EXT_Stone` with base colour, normal and packed
metallic-smoothness maps at 1024 (channel plan in `texturing.md`), matching the swatch mockups. Load: none (paste `texturing.md`); Substance MCP if available.
Writes: `blender/textures/EXT/`, `blender/substance/EXT/`, the materials in the KIT file. Checks: X1-X6.

**Stage 8, T-DRESS-square (integrator).** Goal: props and trims placed from the spec, plus dressing within budget.
Writes: `blender/MASTER.blend`. Checks: A1-A5.

**Stage 9, T-EXP-EXT (exporter).** Goal: one FBX per EXT piece in `export/fbx/EXT/`, `kit_status = exported`.
Load: `blender-to-unity`. Writes: `export/fbx/EXT/`, the KIT file (status only). Checks: E1-E4. Fallback:
the export settings listed in `stages.md`.

**Stage 10, T-UNITY-SYNC-MASTER (Unity integrator).** Goal: Unity's MASTER root matches Blender's MASTER, snapshot
committed. Load: `blender-unity-placement-sync`. Writes: the world scene, `world/placements/`, and MASTER.blend
only through the sync's apply step. Checks: N4, N5. Conflicts go to the master, who asks the user.

**Stage 11, T-LIGHT (lighting artist).** Goal: baked lighting within `budgets.lightmap`, avatars lit everywhere.
Load: `vrchat-lighting-and-baking`. Writes: the world scene's lighting objects, lighting settings, lightmap assets.
Checks: L1-L5.

**Stage 12, T-UDON-shop_doors (Udon developer).** Goal: the interaction as described in the spec, synced as
specified, no `Update()`. Load: `vrchat-udon`. Writes: `Assets/World/Scripts/`, the objects it adds
behaviours to. Checks: I1-I4.

**Stage 13, T-OPT (optimiser).** Goal: every budget measured per platform and met; a report of the numbers. Load:
`vrchat-world-optimization`. Writes: Unity import and quality settings, `world/reports/optimisation.md`; geometry
or UV problems are reported back as new tasks, not fixed here. Checks: O1-O4.
