# The ledger

`world/ledger.yaml` is the master agent's memory. A new session reads it and knows the stage, what is done, what is
in flight, what the user decided and what is waiting on them. Start from `../templates/ledger.yaml`. Only the master
writes it; subagents return report blocks that the master merges. Write it **before** each dispatch and **after** each
return, so a crash never loses a decision.

## Fields

| Field | Meaning |
|---|---|
| `version` | `1` |
| `world` | The world's name (`world.name` in the spec) |
| `stage` | The stage the master is working on |
| `updated` | UTC time of the last write |
| `intake` | What the spec does not hold: `world_root` (the folder with `world/`, `blender/`, `export/`), `brief` (the user's request in their words), `answers` (their intake replies, verbatim), `skills_declined` (skills the user chose not to install, such as `uv-unwrapping`: QA marks the checks that need them not-run, owner user), `blend_layout` (`single`, the default: KIT pieces, assemblies and layout as collections in `blender/MASTER.blend`; `split`: separate KIT and ASM files, only when the user explicitly asked, with their words in `blend_layout_by`). The validator checks the spec's family and assembly files against it. The answers themselves live once, in the spec's `world` and `tools` |
| `gates.<name>` | `spec`, `greybox` and `look` (`SKILL.md`, "Gates"): `status` (`pending`, `approved`, `changes-requested`), `after` (tasks that must be done before asking: for `look`, the `T-TEX-<FAMILY>` of the spec's `look.lead_family`, or `T-TEX-WORLD` in `small` scale, which the master sets when it merges the drafted tasks), `by`, `at`, `notes` with the user's words, `history` (earlier decisions, kept when the gate re-opens), `reopened_by` (the task whose output re-opened it, which may run under it; null otherwise). On approval the master also copies `world/spec.yaml` to `world/spec.approved.yaml`, so a re-open can be diffed |
| `tasks[]` | `id`, `stage`, `title`, `role`, `deps` (task ids or `gate:<name>`), `writes`, `status`, `attempts` (the attempt number: 1 at the first dispatch, +1 after each QA fail; a crash or a `partial` or `blocked` return does not count), `brief`, `report`, `qa` (the verdict file; `false` only for a task that builds nothing, such as a skill test, and the validator warns on it) |
| `flags.generated_assets` | Every prop made with `generate_3d` or imported from a library, and every library material or HDRI a texture uses: piece or material, source, licence, task |
| `flags.overrides` | Library overrides in ASM or MASTER files (`split` layout), with the reason |
| `flags.open_conflicts` | Unresolved placement-sync conflicts waiting on the user |
| `flags.user_actions` | What only the user can do, open until done: installs, sign-in, uploads, on-device tests, decisions to review: `{what, why, task, since}` |
| `log` | Append-only events: dispatches, returns, verdicts, gate decisions, escalations, spec changes, user actions. Every `at` is read from the system clock in UTC (`date -u +%Y-%m-%dT%H:%M:%SZ`, or `Get-Date -AsUTC -Format o`), never estimated: QA compares file modification times against it |

`writes` lists the files and folders the task alone may write (folders end in `/`; the validator treats a folder as
holding every path inside it either way), plus `@unity` / `@blender-live` when it drives that editor. Paths are
relative to the world folder, or to the Unity project for `Assets/` and `ProjectSettings/`; the per-stage paths are
in `stages.md`.

## Task lifecycle

```
todo -> running -> qa -> done
                    \-> failed -> running (attempt 2) -> qa -> ... -> escalated (after attempt 3)
blocked: a dependency was escalated, or its builder waits on a user action (in flags.user_actions);
         a held task (under a gate that is pending or changes-requested) stays todo, and a task whose QA came back
         incomplete stays qa
skipped: not needed (say why in the log)
```

A task may start when every dependency is `done` and every gate it reaches through its dependencies is `approved`.
Under a gate that is `pending` or `changes-requested`, every task downstream that has not started is **held**: it
stays `todo` and nothing new is dispatched, except the gate's `reopened_by` task, which is re-dispatched with the
requested changes. A task already running when its gate re-opens finishes (report and QA as usual; its dependants stay
held); one whose session died goes back to `todo` with the same attempt number until the user approves. The validator
warns while such a task runs, as a reminder of this rule. In `small` scale, a dependency in the same stage that is
waiting in `qa` also counts, because QA runs once per stage (below), writing `world/reports/qa/stage-<n>/verdict.yaml`
for the tasks' `stage` (`T-PLAN-01` is stage 2, so its pass writes `qa/stage-2/`).

| Moment | Master does |
|---|---|
| Dispatch | Write the brief; set `running`; `attempts += 1` only on the first dispatch and after a QA fail; log it. Unity task in a project without git: first copy `ProjectSettings/*.asset` and the scenes it writes to `world/reports/qa/<task>/pre/`, so QA can tell a real change from a re-save |
| Re-dispatch after a crash or a `partial` or `blocked` return | Same attempt number. Keep what the previous run left: rename its brief and any report to `world/briefs/<task>.attempt<n>-interrupted.md` and `world/reports/<task>.attempt<n>-interrupted.yaml` (`-interrupted-2` the next time). The new brief gets a "Found on disk from the previous run" section: what exists, what is half done, what to redo or keep |
| Builder returns `complete` | Save its report block to `report`, set `qa`. Dispatch QA now (`full`), or when the stage's last task returns (`small`). List in the QA brief any edit the master made to the task's outputs since it returned |
| Builder returns `partial`, the gap its own | Save the report, log the gap, and re-dispatch at once with the gap listed in the brief (same attempt) |
| Builder returns `partial` or `blocked` on something only the user can do (an install, a sign-in, a permission refusal, a file only they can export) | Save the report, set `blocked`, add the action to `flags.user_actions`, log it. QA runs only on a complete report, so nothing goes to QA yet |
| Follow-up in the same attempt | Before QA, the master may send the builder more work (`SendMessage`, or a fresh subagent with the report in its brief): log it; attempts unchanged; QA counts the result as the builder's |
| Writes change mid-task | Edit the task's `writes`, re-run the validator with `--ledger`, then let the builder continue |
| QA dispatch | Only on a `complete` report. A QA pass that drives a live editor (Unity checks, Blender MCP `look`) holds it like a task: dispatch it only when no running task lists that `@unity` / `@blender-live`, start no such task until it returns, and log both |
| QA `pass` / `pass-with-notes` | Set `done`; copy notes into the log; advance dependants |
| QA `incomplete` | Nothing failed, but QA's session could not run some blocking checks (`not_run` entries with `owner: qa`). The builder is not at fault: keep the task in `qa` with its attempt count unchanged, log the `not_run` list, and re-dispatch QA with what each entry `needs` (the Unity or Blender editor, a skill, a drivable Play mode). If this environment cannot provide it, tell the user what is missing (a `flags.user_actions` entry); the task and its dependants wait. A missing skill is the user's to install or decline: once declined (`intake.skills_declined`), QA marks its checks not-run, owner user, and the task can pass with notes. Never `done` on `incomplete`, never `blocked`, and never back to its builder. Rename the file to `verdict.incomplete-<n>.yaml` before QA runs again, so the record stays |
| QA `fail`, attempts < 3 | Set `failed`. Keep the attempt's files: rename the brief and report to `world/briefs/<task>.attempt<n>.md` and `world/reports/<task>.attempt<n>.yaml`, and move its QA evidence into an `attempt<n>/` folder inside the QA folder. Then re-dispatch with the original brief plus the QA `fixes` (attempt n + 1) |
| QA `fail`, attempt 3 | Set `escalated`, stop that branch, tell the user what failed and what QA asked for |
| Deviation accepted | The user (or the master as their authorised proxy) accepts a result outside a check: log `{at, event: "deviation accepted: <task> <check>: <what>, by <who>: '<their words>'"}` and list it in the next QA brief; QA marks that check `waived`, citing the entry's `at` |
| Stage QA `fail` (`small`) | Send that task back as above; same-stage tasks that already used what changed go back to `todo` (attempts unchanged) |
| Gate approved | Set `status: approved`, `by`, `at`, `notes`; copy `world/spec.yaml` to `world/spec.approved.yaml`; clear `reopened_by`; release the held tasks |
| Gate `changes-requested` | Set the gate's `notes` to the user's words. The tasks that produce what changes go back to `todo` with `attempts: 0` (attempts count QA failures against one intent, and the intent changed); log the old count. Re-dispatch them with the requested changes in the brief (a task the gate's `after` lists, or its `reopened_by` task, does not wait on the gate), QA again, then ask at the gate again. After stage 4 a finished task is never sent back: the change gets new tasks (`world-spec.md`, "Changing the spec") |
| Gate re-opened (a later change touches what it approved: `world-spec.md`, "Changing the spec") | Append `{status, by, at, notes}` to the gate's `history`, set `status: pending` and `reopened_by` to the task whose output re-opened it, and ask the user with the change (`diff world/spec.approved.yaml world/spec.yaml`). Every task downstream that has not started is held; a running one finishes, a crashed one goes back to `todo` (same attempt). On approval, apply "Changing the spec" in `world-spec.md`: through stage 4, tasks whose inputs changed go back to `todo` (`attempts: 0`, the old count logged); after it, finished tasks stay done and the change gets new tasks |
| A piece renamed after stage 4 | A `T-RENAME-<PIECE>` task (`stages.md`: its id, writes and ordering): `single`, rename its collection in MASTER (every instance follows); `split`, rename it in the KIT file, link the renamed collection in each ASM and MASTER file and re-point the existing instances. Then the FBX and the Unity asset once they exist, and a placement merge, so placement ids survive (QA B2-B3, M9, and N4-N5 after stage 10) |
| The user changed MASTER | Found by a task's `changes_since` (or at resume): the task keeps the user's edits and reports them; when it would have to change the same thing, it returns `blocked` and the master asks the user (`flags.user_actions`). Log what the user changed |
| User action done | Remove it from `flags.user_actions` and log it. A task `blocked` on it: re-dispatch its builder (same attempt number, with what the earlier run left in the brief). A task in `qa` after an `incomplete` verdict: re-dispatch QA, never the builder |
| Session dies | `SKILL.md`, "Resume" |

## Checks

From the world folder, with the venv that has PyYAML (`mechanics.md`):

```
.venv/Scripts/python <this skill>/scripts/spec_validate.py world/spec.yaml --ledger world/ledger.yaml --mermaid world/diagrams/tasks.mmd
```

It rejects duplicate ids, unknown dependencies or gates, cycles, and two tasks that could run at once writing the
same file or folder, and warns when a task of stage 4 or later does not wait for `gate:spec` (stage 5 or later:
`gate:greybox`; stage 9 or later, and every texture task but the lead family's and `T-TEX-TRIM-LAYOUT`:
`gate:look`), directly or through its dependencies. Run it after every change to the task list. Before the spec
gate, check the planner's draft merged in memory with `--draft world/briefs/draft-tasks.yaml`, then merge it into the
ledger and show `tasks.mmd` at the gate. A later re-draft (after the kit plan, or a gate's "changes requested") is
checked the same way: a draft task replaces the ledger task with the same id, with a NOTE.
