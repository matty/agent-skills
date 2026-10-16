---
name: vrchat-world-qa
description: Independent quality checks for VRChat world assets and builds, stage by stage - spec and diagrams, greybox scale, kit naming and pivots, topology, UV0 and UV2, textures and texel density, FBX export and Unity packaging, placement sync, lighting bakes and the performance budget - each a pass/fail checklist with measured evidence from its own measurement and render script (routing to the UV, topology and export skills for deeper audits when installed) plus a visual comparison against the mockups and plans, ending in a fixed verdict block. Use when asked to QA, review, check, verify or sign off a kit, piece, assembly, layout, export or world stage, when a subagent's work needs checking by someone other than its builder, or when deciding whether a stage may advance; the build pipeline that calls this is vrchat-world-orchestration.
---

# VRChat world QA

QA is a separate pass by an agent that **did not build the thing**. It measures, compares against the spec, and
returns a verdict the orchestrator can act on without re-reading the work. It changes nothing in the files it
checks; fixes go back to the builder.

## How to run a QA pass

1. **Read the inputs**: the builder's brief and report, the spec excerpt it worked to (budgets, grid, names,
   materials), and the files it was allowed to write. Anything else it touched is a fail on its own (`G2`).
2. **Pick the checklist** for the stage from `references/checklists.md`. Run every check; never skip one because the
   builder's report says it passed.
3. **Measure with tools**, not by eye. `scripts/qa_measure.py` covers names, triangles, materials, UV layers,
   transforms, pivots, extents, placements and linking on its own. For depth, load the specialist skill named in
   the check (UV audit from `uv-unwrapping`, joint matching from `blender-mesh-topology`, export checks from
   `blender-to-unity`) and use its own tools; if it is not installed, use the check's fallback and say so in
   the evidence. Save raw outputs under `world/reports/qa/<task>/` and cite them.
4. **Look**: render the result from the views the spec and mockups define and compare (`references/visual-review.md`).
   A thing that passes every number but does not look like the approved mockup or plan still fails `G4`.
5. **Write the verdict** (below) and stop. Do not fix anything, even trivially; a QA agent that edits has become a
   second builder and nobody checked its edit.

Headless rule: open KIT and ASM files read-only (`blender -b --factory-startup <file> --python <check>.py` without saving). If the
live Blender holds the file, use Blender MCP and do not save.

## Verdict block

Return exactly this YAML (the orchestrator merges it into the ledger):

```yaml
qa:
  task: T-EXT-03                 # the task id from the brief
  stage: 5                       # stage number
  attempt: 1                     # 1 for the first check, +1 each time the same task returns
  verdict: pass                  # pass | pass-with-notes | fail
  checks:
    - id: M2
      result: fail               # pass | fail | n/a
      measured: "EXT_Wall_2x3_A LOD0 1,248 tris"
      expected: "<= 800 (spec budgets.piece_tris.EXT)"
      evidence: world/reports/qa/T-EXT-03/topology.json
  fixes:                         # one instruction per failed check, specific enough to act on without QA's notes
    - "M2: EXT_Wall_2x3_A - remove the bevel loops on the back face (never seen) to get under 800 tris"
  notes: []                      # any verdict: advisory results and observations worth acting on that do not block
```

A pass over several tasks at once (the pipeline's `small` scale QA's a whole stage together) writes one block per
task, as a YAML list (`- qa: {task: ...}` per task) in one `verdict.yaml`, so a failure sends back only the task
that failed.

| Verdict | Means |
|---|---|
| `pass` | Every check passed or is `n/a` with a reason |
| `pass-with-notes` | Every blocking check passed, and `notes` lists something to act on: an *advisory* check that did not pass, or an observation outside the checklist (a question for the user, a risk for a later stage) |
| `fail` | At least one blocking check failed. `fixes` has one line per failure; `notes` may still carry observations |

## General checks (every stage)

| Id | Check | How |
|---|---|---|
| G1 | Outputs listed in the brief exist and are where it said | List files |
| G2 | Nothing outside the brief's writable files changed (edits the QA brief lists as the master's do not count) | `git status` in a git project; otherwise modification times newer than the dispatch time in the QA brief (UTC; convert local file times to UTC before comparing) or, failing that, the builder brief's own modification time. A follow-up the master asked for within the same attempt counts as the builder's work |
| G3 | Names follow the convention: `<FAMILY>_<Type>_<Size>_<Variant>`, `ASM_<Name>_<Variant>`, `M_<FAMILY>_<Name>` | `qa_measure` (`name_ok`), spec validator |
| G4 | Matches the approved mockup / plan / elevation (for planning stages: the diagrams match the spec and the spec matches the brief) | `references/visual-review.md` |
| G5 | The builder's report block is complete and its claims match what you measured | Compare |

## Escalation

QA only judges. The orchestrator owns retries: a failed task goes back to its builder with the `fixes` list, up to
2 more attempts, then to the user. Write fixes so a fresh builder agent, with no memory of the first attempt, can
apply them.

## Standalone use

Outside the pipeline ("QA this kit"), ask which stage's checklist applies if it is not obvious, take budgets from the
project's spec if there is one, otherwise from the platform targets at the end of `references/checklists.md`, and
give the verdict block plus a short plain-language summary.
