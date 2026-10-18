---
name: vrchat-world-orchestration
description: Build, plan, resume or continue a whole VRChat world or map end to end, from a brief or reference images to PC and Quest builds ready to upload - a master agent delegates spec, plans, kit, greybox, modelling, UVs, texturing, export, Unity, lighting, Udon and optimisation to subagents, with user gates, QA after every task and a resumable ledger. Whole builds only; one step goes to its skill (QA vrchat-world-qa, budgets vrchat-world-optimization, builds and upload vrchat-world-sdk-setup).
---

# VRChat world orchestration

You are the **master agent**. You plan, brief, delegate, check and record; subagents build. A different agent checks
every build task before it counts, the user approves the decisions that are expensive to undo, and everything about
the build lives in files, so any session can resume it.

## Start here

1. Find the world folder (it holds `world/`, `blender/` and `export/`; ask if unsure); if it has `world/ledger.yaml`, **Resume**.
2. Otherwise run **Stage 0**, then add the first tasks to the ledger: `T-SPEC-01` (after `T-MOCK-01` when
   `world.mockups` is true), or `T-PLAN-01` in `small` scale.
3. Run **the loop** until stage 13 is done, stopping at each gate and at every escalation.

## Rules that hold at every stage

1. **Delegate building.** The master runs intake, writes the ledger, briefs and gate summaries, and edits the spec
   only to record a decision (logged). Modelling, unwrapping, texturing, exporting, Unity work and QA go to
   subagents, one level deep: subagents do not spawn their own.
2. **The spec is the source of truth.** `world/spec.yaml` (`references/world-spec.md`) holds every dimension, name,
   budget and placement agents build to; plans and elevations are generated from it, never drawn by hand. A change
   of intent is a spec change first, then a regenerate, then work.
3. **One writer per file and per editor.** Each brief lists the only files its agent may write, and two tasks that
   write the same file or drive the same editor never run at once (the validator enforces it on the ledger):

   | Work | Runs in | Its `writes` list |
   |---|---|---|
   | KIT files | Headless Blender, one process per KIT file | The KIT file |
   | MASTER and ASM files | The live Blender when the Blender MCP is connected (`tools.blender_mcp`), else headless | The `.blend`, plus `@blender-live` when live |
   | Unity work | Unity MCP, the one open Unity project | Its folders, plus `@unity` |
   | QA that drives an editor (Unity checks, the Blender MCP's `look`) | That editor, read-only | Not a ledger task: the master starts no task listing that editor until the QA returns |

   Never run headless on a file that is open in the live Blender.
4. **Link, never append.** `MASTER.blend` holds layout only: linked instances of pieces from `KIT_*.blend` and of
   the one assembly in each `ASM_*.blend`. Geometry is edited in its KIT file and nowhere else.
5. **Nothing is done until QA passes it**, checked by an agent that did not build it.
6. **Gates are the user's.** Stop and wait for explicit approval; never approve one yourself.

## Stage 0: intake

Detect first, then ask the user to confirm or change, in one message:

| Question | Default | Detect by |
|---|---|---|
| World folder | The current folder | - |
| Platforms | `pc` and `quest` (the Android build); `ios` when asked for | - |
| Pipeline scale | `full`, or `small` for one zone and about 30 pieces or fewer | Size of the brief |
| Quality tier (`world.quality`) | `pc_lead` when PC and a mobile platform are both in: PC gets its own budgets and source sizes, mobile its import overrides; `parity` when PC should ship what mobile ships | - |
| Generated or library assets: props (`generate_3d`, asset libraries), CC0 materials and HDRIs (Poly Haven, ambientCG) | **No**; when yes, each one's source and licence goes in `flags.generated_assets` | Blender MCP `search_assets` lists the libraries it reaches |
| Substance Designer / Painter | Use if present, else the Blender fallback. Painter is user-assisted unless a Painter bridge (an MCP or plugin) answers | Substance MCP `sd_ping`, install folders |
| Blender CLI path | - | `bpy.app.binary_path` through the Blender MCP; else `blender` on PATH, `Program Files\Blender Foundation\*`, portable unzips such as `~/.blender/blender-*`, Steam's `common\Blender`; else ask. A missing Blender MCP does not block the build: kit work is headless |
| Blender MCP connected | - | A call to it answers (`tools.blender_mcp`) |
| Unity project path | - | Unity MCP: `mcpforunity://instances` lists the open projects as `Name@hash`; the path is probably in `mcpforunity://project/info` (unverified: read both, and confirm the path with the user) |
| Packages the plan may lean on (VRC Light Volumes, Bakery, LTCGI, Post Processing for PC) and the Android / iOS build modules | Plan only with what is installed; anything else is a user install, asked now | `Packages/vpm-manifest.json` and `Packages/manifest.json`; `BuildPipeline.IsBuildTargetSupported` through Unity MCP. UdonSharp and ClientSim ship inside the Worlds SDK since 3.4.0 (https://creators.vrchat.com/releases/release-3-4-0, checked 2026-10-17): never detect or add them as packages |
| Image tool for mockups | Skip stage 1 unless the user confirms a tool | A tool that makes whole-scene concept art to a file; texture, sprite and engine-asset generators (Unity MCP `generate_image`) do not count (`references/mockups.md`) |

Also ask for the brief if it is thin: the place, mood, scale (zones, rough size), reference images, must-have
interactions, how worn the place is, and two or three images of finished work at the quality they want (the spec's
`look`, `references/world-spec.md`; images go in `world/refs/`). Then create the project layout
(`references/mechanics.md`), copy `templates/spec.yaml` and `templates/ledger.yaml` into `world/`, record the answers
in the spec's `world` and `tools` and the brief, folder and verbatim replies in the ledger's `intake`, and check which
skills are installed (routing table below). Strongly recommend `vrchat-world-qa` (without it QA has only the minimum
checks in `references/stages.md`) and `uv-unwrapping` (without it U1 and U5 are skipped by the user's choice); record
a declined skill in `intake.skills_declined`.

## The loop

For each task whose dependencies are `done` (`small` scale: a same-stage one waiting in `qa` counts) and whose gates,
reached through them, are approved (under a pending gate a task is held in `todo`; one already running when its gate
re-opens finishes):

1. **Brief**: write `world/briefs/<task>.md` from `references/subagent-briefs.md`: skills to load, spec excerpt, the
   only files it may write, steps, checks, the report block.
2. **Dispatch**: set `running` and log the UTC time from the clock; `attempts` goes up by 1 on the first dispatch and
   after a QA fail only (a re-dispatch after a crash or a `partial` or `blocked` return keeps it). Spawn the subagent
   with the brief as its prompt (`references/mechanics.md`). Tasks whose `writes` do not overlap may run in parallel.
3. **Report**: save its report block to `world/reports/<task>.yaml`. `complete`: set `qa`. `partial` with the gap the
   builder's own: re-dispatch at once with the gap listed. `partial` or `blocked` on something only the user can do:
   set `blocked`, add it to `flags.user_actions`, and re-dispatch once it is done (`references/ledger.md`).
4. **QA**, on a complete report only: a separate subagent loads `vrchat-world-qa` and checks the task (QA brief in
   `references/subagent-briefs.md`; the checks per stage in `references/stages.md`): per task in `full` scale, once
   per stage in `small` scale after the stage's last task returns.
5. **Verdict**: `pass` or `pass-with-notes` makes the task `done` (notes into the log). `fail` sends it back with
   QA's fixes for attempt 2, then 3; a third fail is `escalated`: stop that branch and ask the user. `incomplete`
   (nothing failed, but QA's session could not run some blocking checks): the builder is not at fault; the task
   stays in `qa` (never `blocked`), attempts unchanged, and QA, never the builder, is re-dispatched with what its
   `not_run` entries need. If this environment cannot provide it, tell the user (`flags.user_actions`); the task and
   its dependants wait.
6. **Next**: when every task a gate waits on is `done`, stop at the gate; otherwise take the next task.

Write the ledger before each dispatch and after each return. Run `scripts/spec_validate.py` after any change to the
spec or the task list; a spec that does not validate blocks the stage.

## Gates

| Gate | When | Show the user |
|---|---|---|
| **spec** | After stage 2 (`small`: after `T-PLAN-01`), once the drafted tasks are merged into the ledger | Plans, elevations and mockups side by side; platforms and budgets; the zone list; `tasks.mmd`; every assumption |
| **greybox** | After stage 4 (`T-GREY-MASTER` done) | Walkthrough renders from every view, plan and elevation overlays: the last cheap moment to change layout or scale |
| **look** | After the lead family's texturing (`look.lead_family`; `small`: `T-TEX-WORLD`) passes QA | QA's X5 look-dev renders (the family's materials on its pieces and from the spec views, in neutral and in mood light) and X8 numbers, beside the mockups or `look.references`: the last cheap moment to change the material direction, before every other family copies it |

Present a short summary with the images, not the YAML, and wait for explicit approval; on approval keep the spec as
`world/spec.approved.yaml` for later diffs. "Changes requested": record the user's words, send the tasks that produce
what changes back with them (`references/ledger.md`), QA again, ask again. Every gate holds in `small` scale too.

## Stages

Inputs, outputs, task ids, write paths and QA checks per stage: `references/stages.md`.

| # | Stage | Owner role | Ends with |
|---|---|---|---|
| 0 | Intake | master | Answers recorded, project folders created, tools and skills detected |
| 1 | Mockups (skipped when no image tool) | concept artist | Hero images per zone, key interiors, material swatches |
| 2 | Spec and diagrams | planner | `spec.yaml`, SVG plans and elevations, drafted tasks. **Spec gate** |
| 3 | Kit plan | planner | Full piece list, families, materials, texel density, assemblies, sockets |
| 4 | Greybox | kit modellers, integrator | Greybox pieces in KIT files, ASM and MASTER laid out from the plans. **Greybox gate** |
| 5 | Kit modelling | kit modellers (parallel, one per KIT file) | Final geometry to each piece's detail list and references, LODs, collision |
| 6 | UVs | UV artists | UV0 to the family's texel density, UV2 with gaps of 2 texels at each piece's worst-case lightmap square |
| 7 | Texturing | texture artist | The lead family first, then the **look gate**, then the other families' materials, trim sheets, unique prop textures |
| 8 | Assemblies and dressing | integrator | ASM files and MASTER complete with final pieces |
| 9 | Export | exporter | One FBX per piece |
| 10 | Unity assembly | Unity integrator | Prefabs, materials, placements synced, VRChat scene set up, Android and iOS overrides in place |
| 11 | Lighting and bake | lighting artist | Baked lighting, light probes (plus Light Volumes when installed) |
| 12 | Interactivity | Udon developer | The spec's interactive systems working |
| 13 | Optimisation audit and platform builds | optimiser | Every budget met on every platform; each platform built and validated; ready for the user to upload (PC first for a new world, then the others on its blueprint ID) |

Greybox pieces are the first version of each kit piece, in the same collection with the final name, so stages 5-7
improve pieces in place and MASTER never needs re-linking. Each piece collection carries a `kit_status` custom
property: `grey`, `modelled`, `uv`, `textured`, `exported`.

## Scale the pipeline to the world

Ask at intake, record as `world.scale` in the spec.

| | `full` (default) | `small` |
|---|---|---|
| Fits | Several zones, a kit of dozens of pieces, cross-platform | One zone or a few rooms, about 30 pieces or fewer |
| Stages 1-3 | Separate tasks, spec gate after 2 | One planning task, `T-PLAN-01` (mockups, spec, kit plan), spec gate after it |
| KIT files | One per family | One `KIT_World.blend` may hold every family (pieces and `M_<FAMILY>_*` materials still named by family) |
| QA | One pass per task | One pass per stage, after its last task returns: one verdict per task in `world/reports/qa/stage-<n>/verdict.yaml`. Until then a task waits in `qa`, which its same-stage dependants accept; later stages wait for `done` |
| Gates | Spec, greybox, look | Spec, greybox, look (never skipped: they are the cheap moments to change course) |
| Everything else | As written | As written: same names, same spec, same ledger, so a small world can grow into a full one |

## Skills to route to

Brief each subagent to load the skill for its step. If a skill is missing, use the fallback, note it in the ledger,
and say so in the QA brief. The pipeline still runs with less specialist guidance. A check that needs a skill the user
declined is not-run, owner user, and the task passes with notes; one that needs a skill missing but not declined makes
QA return `incomplete` (owner qa) until the user installs or declines it.

| Stage | Load | If it is not installed |
|---|---|---|
| 2-3 | `vrchat-lighting-and-baking` when the brief has a light players switch (`zones[].lighting_states`) | Plan a baked copy per state (`references/world-spec.md`, "Lightmap check") |
| 4, 5, 8, 9 | `blender-kit-library` (kit files), `blender-to-unity` (export) | `scripts/kit_library.py` here, the kit rules in `references/world-spec.md` and the export settings in `references/stages.md` |
| 5 | `blender-mesh-topology` (finishing each piece's form to its detail list, and clean topology) | Brief carries the stage 5 minimum checks (`references/stages.md`) |
| 6 | `uv-unwrapping`; `rizomuv-uv-pipeline` if RizomUV is installed | Blender Smart UV Project with `margin_method='FRACTION'` and `island_margin` = half the UV2 gap, sized from each modelled mesh's real area (`references/stages.md`, stage 6; it leaves the full gap between islands and half of it, 1 texel, at the tile edge); UV0 of atlas and unique maps packed with Margin Method Fraction 1/128 (islands `map_px / 64` apart, `map_px / 128` from the edge); a manual texel-density pass |
| 7 | `pbr-texturing` (values, bakes, Designer, Painter, wear, trim sheets); the Substance MCP when it answers | `references/texturing.md`: Blender procedural materials and bakes, the channel plan |
| 10 | `blender-unity-placement-sync`, `unity-batching-and-instancing`, `vrchat-texture-and-vram`, `vrchat-world-sdk-setup` | Placement by hand through Unity MCP (user moves are not tracked); scene setup from the official VRChat creator docs |
| 11 | `vrchat-lighting-and-baking` | Baked lighting with Unity defaults and the footprint table |
| 12 | `vrchat-udon`; `vrchat-world-sdk-setup` for ClientSim and multi-client testing; `vrchat-lighting-and-baking` for a light switch | Event-driven UdonSharp, manual sync, no `Update()` |
| 13 | `vrchat-world-optimization`; `vrchat-world-sdk-setup` for platform builds | The stage 13 minimum checks (`references/stages.md`) |
| every task | `vrchat-world-qa` for the QA agent (strongly recommended) | The minimum acceptance checks in `references/stages.md` |

## Resume

1. Read `world/ledger.yaml`, then `world/spec.yaml`. Run `spec_validate.py` with `--ledger`.
2. Check the live editors first: a dead task may have left Unity (unsaved scene, Play mode) or the live Blender
   (unsaved MASTER or ASM file) dirty. Do not save or discard on a guess: tell the user what you found and ask.
3. Then go through the tasks by status:

   | Status | Do |
   |---|---|
   | `running` (from the dead session) | Check its writable files against the brief. Complete: write a report for it yourself (`status: complete`, `recovered: true`, what you found), set `qa`, and tell QA that G5 is n/a. Not complete: re-dispatch with the same attempt number and a "Found on disk from the previous run" section (`references/subagent-briefs.md`); if a gate it waits for is pending, set it to `todo` instead (same attempt) and re-dispatch it after approval |
   | `qa` with a verdict file the ledger has not applied | Apply it now (the loop's step 5). A file saying `verdict: incomplete` counts as applied: wait for what it needs, then re-dispatch QA |
   | `qa` with no verdict | `full` scale: dispatch QA again. `small` scale: dispatch it only if the stage's last task has returned; otherwise it is rightly waiting |
   | `failed` | Re-dispatch with the QA `fixes` (attempt + 1) |
   | `blocked` | Its `flags.user_actions` entry done (ask the user if unsure): remove it, log it and re-dispatch, same attempt number. Still open: leave it |
4. Tell the user where the build stands (stage, gates, conflicts, `flags.user_actions`, escalations); continue.

## Change course

When the user changes their mind mid-build, edit the spec, re-validate and regenerate the diagrams. Through stage 4,
send the tasks whose inputs changed back to `todo` (attempts 0, old count logged); after it, add a task limited to the
change (`T-RENAME-<PIECE>`, or one in a resized piece's latest stage), never re-run a finished one. Gate re-opening:
`references/world-spec.md` ("Changing the spec"); ledger steps: `references/ledger.md`. Change the spec first, always.

## References and scripts

| File | Holds |
|---|---|
| `references/stages.md` | Per stage: inputs, outputs, task ids, the write table, QA checks, parallelism |
| `references/subagent-briefs.md` | Builder and QA brief templates, the essentials of every task's brief |
| `references/ledger.md` | Ledger fields, the task lifecycle, what the master does at each moment |
| `references/world-spec.md`, `references/example-spec.yaml` | Spec schema, the look, the quality tier, the lightmap check, kit rules (files, names, pivots), changing the spec; a complete spec that validates |
| `references/mechanics.md` | Spawning subagents in Claude Code and Codex, the project layout, running the scripts |
| `references/mockups.md`, `references/texturing.md` | Stage 1 and stage 7 |
| `scripts/spec_validate.py` (Python + PyYAML) | Validates the spec and the task graph; `--footprints` for lightmap planning, `--draft` for drafted tasks, `--mermaid` for `tasks.mmd` |
| `scripts/spec_to_svg.py` (Python + PyYAML) | Regenerates `world/diagrams/` from the spec |
| `scripts/kit_library.py` (Blender) | Piece collections, linking and placing, reloading libraries, auditing a KIT file |
| `templates/spec.yaml`, `templates/ledger.yaml` | Copied into `world/` at stage 0 |
