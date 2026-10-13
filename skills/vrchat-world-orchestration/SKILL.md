---
name: vrchat-world-orchestration
description: Run a whole VRChat world build from brief to optimised Unity scene as a master agent that delegates every build step to subagents - intake questions, image mockups, a YAML world spec with generated SVG plans and elevations, a kit plan, greybox, kit modelling, UVs, texturing, assemblies, export, Unity assembly, lighting, Udon interactivity and an optimisation audit - with a master .blend that only links KIT and ASM .blend files, user approval gates, independent QA after every task, and a resumable ledger. Use when asked to build, plan, orchestrate or continue a VRChat world (or a large modular 3D environment) end to end, to split world-building work across agents, or to pick up a world build from its ledger; for a single step (just UVs, just an export, just a QA pass) load that step's skill instead.
---

# VRChat world orchestration

You are the **master agent**. You plan, brief, delegate, check and record. Subagents build. Every build task is
checked by a different agent before it counts, the user approves the decisions that are expensive to undo, and
everything you know about the build lives in files so any session can resume it.

## Rules that hold at every stage

1. **Delegate building.** The master writes the ledger, briefs and gate summaries, and runs intake. Modelling,
   unwrapping, texturing, exporting, Unity work and QA go to subagents with a brief
   (`references/subagent-briefs.md`). One level deep: subagents do not spawn their own.
2. **The spec is the source of truth.** `world/spec.yaml` (`references/world-spec.md`) holds every dimension, name,
   budget and placement agents build to; plans and elevations are generated from it, never drawn by hand. A change
   of intent is a spec change first, then a regenerate, then work.
3. **Files and editors have one writer.** Each brief lists the only files its agent may write; two tasks that
   write the same file never run at once (the validator enforces it on the ledger). The live editors are writers
   too: list `@blender-live` (Blender MCP) and `@unity` (Unity MCP, the one open Unity project) in `writes` for any
   task that drives them, so the validator serialises those tasks as well. Kit work runs headless (`blender -b`),
   one process per KIT file, and needs neither.
4. **Link, never append.** `MASTER.blend` holds layout only: linked instances of pieces from `KIT_*.blend` and
   assemblies from `ASM_*.blend`. Geometry is edited in its KIT file and nowhere else.
5. **Nothing is done until QA passes it.** After each build task, a separate QA subagent loads `vrchat-world-qa` and
   returns a verdict. Fail: send the fixes back to a builder (attempt 2, then 3). Third failure: stop that branch and
   ask the user.
6. **Gates are the user's.** Stop and wait for explicit approval at the **spec gate** (after stage 2) and the
   **greybox gate** (after stage 4). Present a short summary with the images, not the YAML.
7. **Record everything in the ledger** (`references/ledger.md`) before and after each step: task status, attempts,
   report and verdict paths, gate decisions, generated assets, overrides, open conflicts.

## Stages

Details, inputs, outputs, owners and QA checklists per stage: `references/stages.md`.

| # | Stage | Owner role | Ends with |
|---|---|---|---|
| 0 | Intake | master | Answers recorded, project folders created, tools and skills detected |
| 1 | Mockups (skipped when no image tool) | concept artist | Hero images per zone, key interiors, material swatches |
| 2 | Spec and diagrams | planner | `spec.yaml`, SVG plans and elevations, task graph. **Spec gate** |
| 3 | Kit plan | planner | Full piece list, families, materials, texel density, sockets |
| 4 | Greybox | kit modellers, integrator | Greybox pieces in KIT files, ASM and MASTER laid out from the plans. **Greybox gate** |
| 5 | Kit modelling | kit modellers (parallel, one per KIT file) | Final geometry, LODs, collision |
| 6 | UVs | UV artists | UV0 to the family's texel density, UV2 for lightmaps |
| 7 | Texturing | texture artist | Family materials, trim sheets, unique prop textures |
| 8 | Assemblies and dressing | integrator | ASM files and MASTER complete with final pieces |
| 9 | Export | exporter | One FBX per piece |
| 10 | Unity assembly | Unity integrator | Prefabs, materials, placements synced, VRChat scene set up, platform overrides in place |
| 11 | Lighting and bake | lighting artist | Baked lighting, probes or Light Volumes |
| 12 | Interactivity | Udon developer | The spec's interactive systems working |
| 13 | Optimisation audit and platform builds | optimiser | Every budget met on every platform build; PC and Android (and iOS) builds validated on one blueprint ID; ready for the user to upload |

Greybox pieces are the first version of each kit piece, in the same collection with the final name, so stages 5-7
improve pieces in place and MASTER never needs re-linking. Each piece collection carries a `kit_status` custom
property: `grey`, `modelled`, `uv`, `textured`, `exported`.

## Scale the pipeline to the world

Ask at intake, record as `world.scale` in the spec.

| | `full` (default) | `small` |
|---|---|---|
| Fits | Several zones, a kit of dozens of pieces, cross-platform | One zone or a few rooms, about 30 pieces or fewer |
| Stages 1-3 | Separate tasks, spec gate after 2 | One planning task (mockups, spec, kit plan), spec gate after it |
| KIT files | One per family | One `KIT_World.blend` may hold every family (pieces and `M_<FAMILY>_*` materials still named by family) |
| QA | One pass per task | One pass per stage, over all of that stage's tasks |
| Gates | Spec, greybox | Spec, greybox (never skipped: they are the cheap moments to change course) |
| Everything else | As written | As written: same names, same spec, same ledger, so a small world can grow into a full one |

## Stage 0: intake

Detect first, then ask the user to confirm or change, in one message:

| Question | Default | Detect by |
|---|---|---|
| Platforms | PC and Quest | - |
| Pipeline scale | `full`, or `small` for one zone and about 30 pieces or fewer | Size of the brief |
| Performance tier | Quest-safe | - |
| Generated or library assets for props (`generate_3d`, asset libraries) | **No** | - |
| Substance Designer / Painter | Use if present, else the Blender fallback | Substance MCP `sd_ping`, install folders |
| Blender CLI path | - | `bpy.app.binary_path` through Blender MCP, common install folders |
| Unity project path | - | Unity MCP `mcpforunity://instances` |
| Image tool for mockups | Use if the host has one, else skip stage 1 | The tools you have |

Also ask for the brief itself if it is thin: the place, mood, scale (how many zones, roughly how big), reference
images, and must-have interactions. Then create the project layout below, copy `templates/spec.yaml` and
`templates/ledger.yaml` into `world/`, record the answers in both, and check which skills are installed (next
section).

## Skills and tools to route to

Brief each subagent to load the skill for its step. If a skill is missing, use the fallback and note it in the
ledger. The pipeline still runs; that stage just gets less specialist guidance.

| Stage | Load | If it is not installed |
|---|---|---|
| 4, 5, 8, 9 | `blender-to-unity-vrchat` (kit files, export) | `scripts/kit_library.py` here, the kit rules in `references/world-spec.md` and the export settings in `references/stages.md` |
| 5 | `blender-mesh-topology` | Brief carries the topology checks from `vrchat-world-qa` |
| 6 | `uv-unwrapping`; `rizomuv-uv-pipeline` if RizomUV is installed | Blender Smart UV Project plus a manual texel-density pass, flagged for extra QA |
| 7 | Substance MCP; `references/texturing.md` | Blender procedural materials and bakes (`references/texturing.md`) |
| 10 | `blender-unity-placement-sync`, `unity-batching-and-instancing`, `vrchat-texture-and-vram`, `vrchat-world-sdk-setup` | Placement by hand through Unity MCP, flagged: user moves are not tracked. Scene setup from the official VRChat creator docs |
| 11 | `vrchat-lighting-and-baking` | Baked lighting with Unity defaults, flagged for extra QA |
| 12 | `udon-performance`; `vrchat-world-sdk-setup` for ClientSim and multi-client testing | Event-driven UdonSharp, manual sync, no `Update()` |
| 13 | `vrchat-world-optimization`; `vrchat-world-sdk-setup` for platform builds | `vrchat-world-qa` stage 13 checklist |
| every task | `vrchat-world-qa` for the QA agent | QA agent uses the stage's acceptance checks from the brief |

## Delegating in Claude Code and Codex

The same instructions work in both; the mechanics differ.

| | Claude Code | Codex |
|---|---|---|
| Spawn | `Agent` tool (`general-purpose` for builders and QA, `Explore` for read-only fact finding) | Ask for subagents in plain language; this skill's instructions count as the request. Built-in `worker` for builders, `explorer` for read-only |
| Run in parallel | Several `Agent` calls in one message | Ask to "delegate these N tasks in parallel"; Codex returns when all finish |
| Custom roles | `.claude/agents/<role>.md` | `~/.codex/agents/<role>.toml` (`name`, `description`, `developer_instructions`) |
| Continue a subagent | `SendMessage` to its id | Start a fresh subagent with the previous report in its brief |
| Result | The agent's final message: require the report block from the brief | Same |

Codex caps parallel threads (`agents.max_concurrent_threads_per_session`); queue the rest. Source:
https://developers.openai.com/codex/subagents (checked 2026-10-13).

## Project layout

```
<world>/
  world/
    spec.yaml  ledger.yaml
    mockups/       <view>.png + <view>.prompt.txt
    diagrams/      plan_*.svg, elevation_*.svg, tasks.mmd (generated; never hand-edited)
    briefs/        <task>.md
    reports/       <task>.yaml, qa/<task>/verdict.yaml + evidence
    placements/    placement-sync dumps, plans, snapshots
  blender/
    MASTER.blend
    kits/KIT_<FamilyName>.blend
    asm/ASM_<Name>.blend
    textures/  substance/
  export/fbx/<FAMILY>/<Piece>.fbx
```

The Unity project lives wherever the user keeps it (recorded in `tools.unity_project`); world content goes under
`Assets/World/`. Put `<world>/` under git if the user agrees, with `.blend` and textures in Git LFS.

## Scripts

| Script | Host | Use |
|---|---|---|
| `scripts/spec_validate.py` | Python + PyYAML | Validate `spec.yaml`; with `--ledger`, the task graph; `--mermaid` writes `tasks.mmd` |
| `scripts/spec_to_svg.py` | Python + PyYAML | Regenerate `world/diagrams/` from the spec |
| `scripts/kit_library.py` | Blender (bpy) | Create piece collections, link and place them, reload libraries, audit a KIT file (`-- --audit --module <m>`) |

PyYAML goes in a project venv (`python -m venv .venv`, `.venv/Scripts/pip install pyyaml`), not the system Python.
Run both after every spec change; a spec that does not validate blocks the stage.

## Resuming

1. Read `world/ledger.yaml`, then `world/spec.yaml`. Run `spec_validate.py` with `--ledger`.
2. Tasks left `running` from a dead session: check their writable files against the brief. If the output is
   complete, send it to QA. Otherwise reset the task to `todo` and keep its attempt count.
3. Tell the user where the build stands (stage, gates, open conflicts, escalations) in a few lines, then continue
   from the first task whose dependencies are `done`.

## Changing course

When the user changes their mind mid-build, edit the spec, regenerate the diagrams and re-validate. Mark the
tasks whose inputs changed as `todo` again. A change to anything before the spec gate also re-opens that gate.
Never patch a downstream file to match a new intent without changing the spec first.
