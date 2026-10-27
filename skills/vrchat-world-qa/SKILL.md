---
name: vrchat-world-qa
description: QA, review, check, verify or sign off a VRChat world stage - kit, piece, assembly, layout, export, scene, bake or platform build - may it advance or upload, does it match its mockup, plan and spec. Independent pass/fail checks with measured evidence; never fixes. To fix, or audit one craft without sign-off, the specialist skill wins; vrchat-world-orchestration calls it.
---

# VRChat world QA

QA is a separate pass by an agent that **did not build the thing**. It measures, compares against the spec and the
approved images, and returns a verdict the orchestrator can act on without re-reading the work. It changes nothing in
the files it checks: fixes go back to the builder.

## How to run a QA pass

1. **Read the inputs**: the QA brief (task, stage, attempt, dispatch time, the builder's writable files, master edits
   since the builder returned), the builder's brief and report, and the spec excerpt it worked to.
2. **Pick the checks**: the task's row in "Checks per task" in `references/checklists.md`, plus G1-G5 for every task.
   Run every one; never skip a check because the builder's report says it passed.
3. **Measure with tools**, not by eye. `scripts/qa_measure.py` measures Blender files and re-imported FBX files
   (names, triangles, topology, transforms, pivots, materials, images, UV layers, linking, placements) and makes the
   review renders: run it on every .blend the task wrote, with the stage's `--expect-status`. Texture maps go through
   its PBR check (`--pbr`, X8: base-colour and metal ranges, binary metallic, normal maps; with `--pbr-tiling`, X4:
   seams and the tile-scale variation that draws a grid). `scripts/texture_seams.py` measures every UV seam and kit
   joint of a textured mesh (X9). For depth, load the specialist skill a check names (UV audit and tiling phase:
   `uv-unwrapping`; joints, closed islands, high and low poly: `blender-mesh-topology`) and use its own tools; if it
   is not installed, use the check's fallback and say so in `evidence`.
4. **Look** (`references/visual-review.md`): render from the spec's views and compare with the mockups, plans,
   elevations and the spec's `look` references. Materials need a look-dev render (`--light lookdev`, EEVEE): the
   Workbench renders show base colour only, never roughness, metal or normal maps. After the bake, render the lit
   Unity views (L7). A thing that passes every number but does not look like the approved mockup or plan fails G4.
5. **Write the verdict** (below) and stop. Do not fix anything, even trivially: a QA agent that edits has become a
   second builder, and nobody checked its edit.

Typical runs (absolute paths; `<ev>` is the evidence folder, `<skill>` this skill's folder). Keep
`--python-exit-code 1`: without it a crashed run exits 0. A measuring run prints a `[qa] role ...` line and writes its
JSON; one that did not is unfinished, never clean: fix the command and run it again. `--module` (the spec's
`grid.module`) is required on every run that opens a .blend or imports FBX. A `--lightmap-texels` run (U4) takes
`--lightmapper bakery` when the spec's `lighting.baker` is `bakery`: Bakery sizes lightmaps differently.

    blender -b --factory-startup blender/kits/KIT_<Family>.blend --python-exit-code 1
            --python <skill>/scripts/qa_measure.py -- --module <grid.module> --expect-status modelled
            --piece-tris '{"EXT": 800}' --json <ev>/kit.json
    blender -b --factory-startup blender/MASTER.blend --python-exit-code 1 --python <skill>/scripts/qa_measure.py --
            --module <grid.module> --sub-module <grid.sub_module> --expect-status textured --json <ev>/master.json
    blender -b --factory-startup --python-exit-code 1 --python <skill>/scripts/qa_measure.py --
            --module <grid.module> --import-fbx "export/fbx/<FAMILY>/*.fbx" --json <ev>/fbx.json

In a single MASTER (the default layout, `kit_layout = "single"`), the kit run is on `blender/MASTER.blend` with
`--pieces "<FAMILY>_*"` for the task's family, and B2, B3, M9, A1-A3 read as `references/checklists.md` says. When the
live Blender has MASTER open, measure it there through the MCP without saving (its disk copy may be older).

## Rules while checking

- **Read-only Blender**: open every .blend headless (`blender -b --factory-startup <file> --python-exit-code 1
  --python <script>.py -- ...`) and never save; `--factory-startup` keeps the user's add-ons out of the run. If the
  live Blender holds the file, use the Blender MCP and do not save.
- **Transforms in your own scripts**: Blender evaluates only what the view layer shows. An object in an excluded
  collection (bake highs, retained sources, a single MASTER's `KIT` and `ASM`) or one disabled in viewports keeps a
  stale `matrix_world`, identity after a headless load (measured on Blender 5.2.2: `location` (4, 4, 0),
  `matrix_world.translation` (0, 0, 0)), and its bounds and mesh leave out its modifiers. Compare `matrix_basis`
  (after checking `parent is None` and no constraints), or include the collection for the reading and restore it,
  as `qa_measure` does for pieces; never `matrix_world` of an excluded or disabled object. A QA run that read it
  reported bake highs "at the origin" and failed a correct task twice.
- **Read-only Unity**: no saves, no asset changes, no build-target switch, with one exception: at stage 13, QA may
  switch to each platform it measures (O1) or validates (O5), then switches back to the target it found. After Play
  mode, reopen the scene from disk. To see a state the scene does not hold (a light on, a test capsule), add hidden temporary objects
  and destroy them (`references/visual-review.md`).
- **Write only the evidence folder** (below), and save every raw output there so the verdict can cite it.

## Verdict

### Where it goes

| Pass | Evidence and verdict |
|---|---|
| One task | `world/reports/qa/<task>/`; the block in `verdict.yaml` there |
| A whole stage at once (the pipeline's `small` scale) | Each task's evidence in `world/reports/qa/stage-<n>/<task>/`; one `world/reports/qa/stage-<n>/verdict.yaml` holding a YAML list with one block per task (`- qa: {task: ...}`), so a failure sends back only that task |
| A retry of a task | The master keeps the failed attempt: the builder's brief and report become `<task>.attempt<n>.*`, and that task's QA evidence moves into `attempt<n>/` inside its own folder (`qa/<task>/attempt<n>/`, or `qa/stage-<n>/<task>/attempt<n>/` with its old block as `verdict.yaml` there). If it has not moved yet, move only that task's files, never another task's; in a stage pass replace only its block in `verdict.yaml` |

End your final message with the same block or list.

### The block

```yaml
qa:
  task: T-MOD-EXT                # the task id from the QA brief
  stage: 5
  attempt: 1                     # the attempt number from the QA brief (the ledger's count)
  verdict: fail                  # pass | pass-with-notes | incomplete | fail
  checks:
    - id: M2
      result: fail               # pass | fail | n/a | not-run | waived
      measured: "EXT_Wall_2x3_A LOD0 1,248 tris"
      expected: "<= 800 (spec budgets.piece_tris.EXT)"
      evidence: world/reports/qa/T-MOD-EXT/kit.json      # a path, or a list of paths
      not_run: []                # parts of this check that could not run here (below)
      waived_by: ""              # result waived: the ledger log entry where the deviation was accepted
  fixes:                         # one entry per failed blocking check
    - "M2: EXT_Wall_2x3_A - remove the bevel loops on the back face (never seen) to get under 800 tris"
  notes: []                      # advisory failures, the user's not-run parts, waivers (each with who must act), observations
```

A check, or part of one, that could not run here names what it needs and whose it is:

```yaml
    - id: L4
      result: not-run
      measured: "no Unity editor in this session"
      expected: "light probes cover every walkable area"
      evidence: []
      not_run:
        - {part: "capsule renders and probe samples", needs: "the Unity editor through Unity MCP", owner: qa}
      waived_by: ""
```

`owner: qa` when QA's own session lacked something a QA agent normally has: Unity or Blender reachable, or a drivable
Play mode. `owner: user` when the part is the user's: signing in, devices and other VRChat clients, uploading, a
missing build module (Android or iOS support is a user install), anything the user excluded. A part that needs a
specialist skill which is not installed (`references/checklists.md`, "Tools", lists them) takes its owner from whether
the user declined that skill (the QA brief lists the declined skills, from the ledger's `intake.skills_declined`):

> declined: not-run, owner user, passes with notes; missing but not declined: incomplete (owner qa) until the user installs or declines it.

| Result | Use when |
|---|---|
| `pass` | Measured and within the check. A check that ran in part passes on what ran, with the rest in `not_run` |
| `fail` | Measured and outside the check. An *advisory* check that fails goes in `notes`, not `fixes` |
| `n/a` | The check does not apply to this task or world; say why in `measured` |
| `not-run` | Nothing of the check could run here; each missing part in `not_run` with `needs` and `owner` |
| `waived` | Measured and outside the check, but the user, or the master as the user's proxy, accepted it in the ledger: `waived_by` cites the log entry |

An estimate in place of a measurement (a download size without a build) goes in `not_run`, never in a plain pass.

| Verdict | Means (the first that applies) |
|---|---|
| `fail` | At least one blocking check failed. `fixes` has one entry per failed blocking check, written so a fresh builder with no memory of this attempt can apply it; `notes` may still carry observations |
| `incomplete` | Nothing failed, but a blocking check, or part of one, could not run in QA's session (`owner: qa`): the task is unverified. Each such part is in `not_run` with what it needs, so the master can re-dispatch QA where it can run |
| `pass-with-notes` | Nothing failed and everything QA owns ran; `notes` lists what is left: advisory failures, the user's `not_run` parts (`owner: user`), waivers, and observations worth acting on (a question for the user, a risk for a later stage) |
| `pass` | Every check `pass` or `n/a`, with nothing in any `not_run` |

## Escalation

QA only judges. The orchestrator owns retries: a failed task goes back to its builder with the `fixes` list, up to 2
more attempts, then to the user. An `incomplete` task goes back to QA, not to its builder.

## Standalone use

Outside the pipeline ("QA this kit"), ask which stage's checks apply if it is not obvious. Without a project spec, ask
the user for what the checks would read from it:

- The grid module, for `--module` (required on every `qa_measure` run that opens a .blend). If nobody knows it,
  derive it from a grid piece's bounds and Size token (a 2 m wide `..._2x3_A` wall means a 1 m module), and say so.
- `texels_per_m`, for U4's footprints, and the lightmapper (Unity's Progressive or Bakery, for `--lightmapper`).
  Without `texels_per_m`, U4's texel gaps are `not-run`, owner user.
- The budgets: triangles per piece or family for M2, and the world budgets. Failing those, use the platform targets
  at the end of `references/checklists.md`, and say which in `expected`.

Run `qa_measure` without `--expect-status`: outside the pipeline nothing set `kit_status` to the stage you picked, so
it would flag every piece's status. Without it, the n-gon, empty-slot and UV2 rules follow each piece's own
`kit_status`, and all apply to a piece that has none. Write the evidence to `qa/<what>-<YYYY-MM-DD>/` next to the files
checked (or a folder the user names). In the block, `task` is a short name for what was checked and `attempt` is 1.
`stage` is the stage whose checks you ran; when they came from several stages, use the latest and name the others in
`notes`. Without a brief, G1, G2 and G5 are `n/a`, and G4 compares with whatever the user gave (images, plans) or,
failing that, with the piece names' Size and kind. Give the verdict block plus a short plain-language summary.
