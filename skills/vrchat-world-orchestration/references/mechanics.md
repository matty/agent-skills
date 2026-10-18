# Mechanics: spawning subagents, the project layout, running the scripts

## Spawning subagents in Claude Code and Codex

The same instructions work in both; the mechanics differ.

| | Claude Code | Codex |
|---|---|---|
| Spawn | The `Agent` tool (called `Task` before Claude Code 2.1.63): `general-purpose` for builders and QA, `Explore` for read-only fact finding | Ask in plain language ("spawn two agents", "delegate this in parallel"); this skill's instructions count as the request. Built-in `worker` for builders, `explorer` for read-only, `default` otherwise |
| Run in parallel | Several `Agent` calls in one message | Ask to delegate the N tasks in parallel; Codex returns when all finish |
| Custom roles | `.claude/agents/<role>.md` (project) or `~/.claude/agents/`: Markdown with YAML frontmatter, `name` and `description` required | `.codex/agents/<role>.toml` (project) or `~/.codex/agents/`: `name`, `description`, `developer_instructions` |
| Nesting | A subagent can spawn its own, up to three levels, unless `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1`; every brief says "do not spawn subagents" either way | Not documented: the brief says it |
| Continue a subagent | `SendMessage` to its id or name | Start a fresh subagent with the previous report in its brief |
| Result | The agent's final message: require the report block from the brief | Same |

Codex caps parallel threads (`agents.max_concurrent_threads_per_session`, a Codex-chosen default); queue the rest.
Sources (checked 2026-10-17): https://code.claude.com/docs/en/sub-agents and
https://learn.chatgpt.com/docs/agent-configuration/subagents (where https://developers.openai.com/codex/subagents now
redirects).

Subagents may not be able to read MCP resources such as `mcpforunity://editor/state` (seen in the 2026-10-16 dry run,
Claude Code subagents with MCP for Unity). Brief Unity subagents to read editor state through `execute_code` instead:
`EditorApplication.isCompiling`, `isPlaying`, and the active scene's `isDirty`.

## Project layout

```
<world>/                       recorded as intake.world_root in the ledger
  .venv/                       Python with PyYAML for the scripts
  world/
    spec.yaml  ledger.yaml
    mockups/       <view>.png + <view>.prompt.txt
    refs/          the user's reference and quality-bar images (the spec's look and pieces' ref)
    diagrams/      plan_*.svg, elevation_*.svg, tasks.mmd, lightmap_budget.txt (generated; never hand-edited)
    briefs/        <task>.md, draft-tasks.yaml, <task>.attempt<n>.md after a retry
    reports/       <task>.yaml, optimisation.md, build-<platform>.md, publish-fields.md
                   qa/<task>/verdict.yaml + evidence (small scale: qa/stage-<n>/), qa/<task>/pre/ snapshots
    placements/    placement-sync dumps, plans, snapshots
  blender/
    MASTER.blend
    kits/KIT_<FamilyName>.blend
    asm/ASM_<Name>_<Variant>.blend      one assembly per file
    textures/<FAMILY>/  substance/<FAMILY>/
  export/fbx/<FAMILY>/<Piece>.fbx
```

The Unity project lives wherever the user keeps it (`tools.unity_project`); world content goes under
`Assets/World/` (`Kits/`, `Assemblies/`, `PlacementSync/`, `Scenes/`, `Scripts/`, `Editor/`). Put `<world>/` under git
if the user agrees, with `.blend` files and textures in Git LFS.

## Running the scripts

Make the venv once in the world folder: `python -m venv .venv`, then `.venv/Scripts/pip install pyyaml`
(`.venv/bin/pip` outside Windows); never install into the system Python. Run every command from the world folder,
with the script's full path inside this skill:

| Command | Does |
|---|---|
| `.venv/Scripts/python <skill>/scripts/spec_validate.py world/spec.yaml` | Validates the spec; exit 1 on any ERROR |
| `... spec_validate.py world/spec.yaml --footprints world/diagrams/lightmap_budget.txt` | Writes each piece's planning footprint, its placements and the lightmap fill (omit the file to print it). It plans the fill only: stage 6 sizes UV2 gaps from each modelled mesh |
| `... spec_validate.py world/spec.yaml --ledger world/ledger.yaml --mermaid world/diagrams/tasks.mmd` | Also checks the task graph and draws it |
| `... spec_validate.py world/spec.yaml --ledger world/ledger.yaml --draft world/briefs/draft-tasks.yaml` | Checks the planner's draft tasks merged with the ledger, without writing either; a draft task replaces the ledger task with the same id |
| `.venv/Scripts/python <skill>/scripts/spec_to_svg.py world/spec.yaml --out world/diagrams` | Regenerates the plans and elevations; removes drawings of zones and elevations no longer in the spec |
| `blender -b --factory-startup --python-exit-code 1 <file.blend> --python <skill>/scripts/kit_library.py -- --audit --module <grid.module>` | Audits a KIT file's pieces (Blender's Python; no venv; `--module` is required) |

Run the validator and `spec_to_svg.py` after every spec change; a spec that does not validate blocks the stage.

Headless Blender for any task: `blender -b --factory-startup --python-exit-code 1 <file.blend> --python <script>.py`
(without `--python-exit-code 1` an uncaught exception still exits 0 and a failed run looks clean), the script in
the task's scratch folder outside the project, and it sets `bpy.context.preferences.filepaths.save_version = 0`
before saving (or saves with `kit_library.py`'s `save_file()`), so no `.blend1` backup appears beside the file.
