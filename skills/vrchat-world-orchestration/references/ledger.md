# The ledger

`world/ledger.yaml` is the master agent's memory. A new session reads it and knows the stage, what is done, what is
in flight, what the user decided and what is waiting on them. Start from `../templates/ledger.yaml`. Only the master
writes it; subagents return report blocks that the master merges.

## Fields

| Field | Meaning |
|---|---|
| `stage` | The stage the master is working on |
| `intake` | Stage 0 answers (mirrored into the spec) |
| `gates.<name>` | `status` (`pending`, `approved`, `changes-requested`), `after` (tasks that must finish before asking), `by`, `at`, `notes` with the user's words |
| `tasks[]` | `id`, `stage`, `title`, `role`, `deps` (task ids or `gate:<name>`), `writes` (files or folders it alone may write, plus `@unity` / `@blender-live` when it drives that editor), `status`, `attempts`, `brief`, `report`, `qa` |
| `flags.generated_assets` | Every prop made with `generate_3d` or imported from a library: piece, source, task |
| `flags.overrides` | Library overrides in ASM or MASTER, with the reason |
| `flags.open_conflicts` | Unresolved placement-sync conflicts waiting on the user |
| `log` | Append-only events: dispatches, verdicts, gate decisions, escalations, spec changes |

## Task lifecycle

```
todo -> running -> qa -> done
                    \-> failed -> running (attempt 2) -> qa -> ... -> escalated (after attempt 3)
blocked: a dependency failed or a gate was refused      skipped: not needed (say why in the log)
```

| Moment | Master does |
|---|---|
| Dispatch | Write the brief, set `running`, `attempts += 1`, log it |
| Builder returns | Save its report to `report`, set `qa`, dispatch the QA agent |
| QA `pass` / `pass-with-notes` | Set `done`; copy notes into the log; advance dependants |
| QA `fail`, attempts < 3 | Set `failed`, then re-dispatch with the original brief plus the QA `fixes` |
| QA `fail`, attempt 3 | Set `escalated`, stop that branch, tell the user what failed and what QA asked for |
| Gate `changes-requested` | Set the gate's `notes` to the user's words. The tasks that produce what changes go back to `todo` with `attempts: 0` (attempts count QA failures against one intent, and the intent changed); log the old attempt count. Re-dispatch them with the requested changes in the brief, QA again, then ask at the gate again |
| Session dies mid-task | On resume, check the task's writable files: complete goes to QA, incomplete goes back to `todo` with the same attempt count |

Write the ledger **before** dispatching and **after** each return, so a crash never loses a decision.

## Checks

`python scripts/spec_validate.py world/spec.yaml --ledger world/ledger.yaml --mermaid world/diagrams/tasks.mmd`
rejects duplicate ids, unknown dependencies, cycles, and two tasks that could run at once writing the same file. Run
it after adding tasks, and show `tasks.mmd` to the user at the spec gate.
