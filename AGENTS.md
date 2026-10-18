# AGENTS.md — agent-skills

Skills for Claude Code and Codex. Both agents read the same format, so nothing in
this repo is specific to either one.

Codex and Claude Code (2.1.277+, when no `CLAUDE.md` is present:
https://code.claude.com/docs/en/memory#agents-md, checked 2026-10-17) both read this file as the
project instructions. It overrides `~/.agents/AGENTS.md` where they disagree.

## Layout

```
skills/<skill-name>/
  SKILL.md          required — YAML frontmatter + the skill body
  references/*.md   optional — detail loaded on demand, one topic per file
  scripts/*         optional — runnable helpers the skill points at
  templates/*       optional — files the skill tells an agent to copy into a project
install.ps1         the installer (see below)
tools/check_conventions.py   checks conventions duplicated across skills still agree
tools/lint_skills.py         checks each skill is well formed (frontmatter, README row, ASCII, links, script headers)
tools/tests/                 plain-Python tests of the skills' scripts; tools/tests/blender/ for Blender-hosted ones
tools/run_checks.py          runs all of the above (CI runs it too: .github/workflows/checks.yml)
README.md           what each skill covers
AGENTS.md           this file
```

The folder name, the `name:` in frontmatter, and the skill's row in `README.md`'s tables must all match
(`tools/lint_skills.py` checks it).
`install.ps1` only treats a folder as a skill if it contains `SKILL.md`, so drafts can sit
in `skills/` without a `SKILL.md` and stay invisible to the installer.

## SKILL.md format

```markdown
---
name: kebab-case-matching-the-folder
description: When to use it (the words a user types), then what it covers, then which sibling wins. One line.
---

# Human readable title

Body.
```

The `description` is the only part an agent sees before deciding whether to load the
skill, so it carries the whole triggering burden. Lead with *when to use it*: the
symptoms and the words a user would actually type ("draw calls too high", "avatars
render black"), not an abstract summary. Then *what it covers*, briefly. Then, if two
skills overlap, which one wins; route from the entry-point skill rather than
duplicating the material.

Keep it under 500 characters, ASCII, with no angle brackets (`tools/lint_skills.py`
warns past 500; 1,024 is the hard limit). Both agents cut descriptions once all
installed skills pass a shared budget, and both say to put the key use case and
trigger words first:

- Claude Code truncates one description at 1,536 characters and, once the listing passes
  1% of the context window (8,000 characters as a fallback), drops the descriptions of
  the least-used skills: https://code.claude.com/docs/en/skills (checked 2026-10-17).
- Codex shortens descriptions first and may omit skills past 2% of the context window
  (8,000 characters as a fallback): https://learn.chatgpt.com/docs/build-skills (checked 2026-10-17).

## Making changes

1. Edit under `skills/`. With the default `link` install the change is live in the
   repo immediately — no reinstall step. Claude Code watches its skills folders and
   picks up added, edited or removed skills without a restart (run `/reload-skills` if
   one does not appear; restart after a rename). Codex reads skills at startup, so
   restart it after adding, renaming or deleting a skill.
2. Keep facts with a shelf life (Unity versions, platform limits, SDK APIs) next to a
   source URL in the skill, so a stale number is checkable rather than trusted.
3. Move anything long or narrow into `references/` and link to it from `SKILL.md`.
   `SKILL.md` should stay skimmable; depth lives one hop away.
4. Update `README.md`'s table when you add or rename a skill.
5. Run `python tools/run_checks.py` (add `--blender <path to blender.exe>` when you
   touched a Blender script) before committing. It runs `check_conventions.py`, which
   lists every copy of a shared fact that disagrees (update `CANON` in it when a fact
   really changes), the structure lint and the tests.
6. A script decision that can be tested without its host gets a plain-Python test in
   `tools/tests/test_<skill>_<topic>.py`; host behaviour gets a Blender test in
   `tools/tests/blender/` that builds its own fixtures in a temp folder. A bug found
   in a dry run gets a test that would have caught it.
7. Commit the skill and its README row together. One skill per commit where practical;
   commit messages are `<skill-name>: what changed`.

### Adding a skill

```pwsh
mkdir skills/my-skill
# write skills/my-skill/SKILL.md with name: my-skill
pwsh -File install.ps1 install -Skills my-skill
# Claude Code picks it up (or run /reload-skills); restart Codex
```

### Renaming or deleting one

Rename the folder and the `name:` together, then re-run with `-Prune` so the old
entry is cleaned out of the target folders:

```pwsh
pwsh -File install.ps1 install -Prune
```

Without `-Prune` the stale junction is left behind and the agent keeps offering a
skill that no longer exists.

## How installation works

`install.ps1` exposes selected skills to the agents. It never modifies the repo.

| Command | Effect |
|---|---|
| `list` | Every repo skill and its state in each target (`Link` / `Copy` / `Foreign` / `Missing`) |
| `install` | Install the selected skills |
| `update` | `git pull --ff-only` (skipped outside a git checkout), then refresh what is already installed |
| `uninstall` | Remove the selected skills |

```pwsh
pwsh -File install.ps1 list
pwsh -File install.ps1 install -Skills vrchat-*,blender-to-unity
pwsh -File install.ps1 install                       # all of them
pwsh -File install.ps1 update -Prune
pwsh -File install.ps1 uninstall -Skills vrchat-udon
pwsh -File install.ps1 install -WhatIf               # dry run
```

### Targets

| Target | Path | Read by |
|---|---|---|
| `claude` | `~/.claude/skills` | Claude Code |
| `agents` | `~/.agents/skills` | Codex (its documented user skills folder) |
| `codex` | `~/.codex/skills` | older Codex builds only |

Default is `-Targets claude,agents`. Don't add `codex` alongside `agents` for a current
Codex: it does not merge same-named skills, so each one would be listed twice. Source:
https://developers.openai.com/codex/skills (redirects to learn.chatgpt.com/docs/build-skills).
To move an existing machine off `codex`, install to `agents`, then
`pwsh -File install.ps1 uninstall -Targets codex`.

These folders also hold entries this repo doesn't own: Claude Code's `synced/` folder in
`~/.claude/skills`, Codex's `.system/` in `~/.codex/skills`, and skills installed by other
tools (which typically put the real folder in `~/.agents/skills` and link it into the
others). The installer only ever touches entries it manages; anything else is reported as
`Foreign` and skipped unless you pass `-Force`.

**A target root may itself be a link** (e.g. `~/.claude/skills` as a junction to
`~/.agents/skills`). The installer detects that, resolves it, and installs into the real
folder — writing per-skill links *inside* an unresolved junction would silently land
them somewhere else. It prints which folder it chose, and visits a folder once even when
two targets resolve to it.

### link vs copy

`-Mode auto` (default) picks `link` when `install.ps1` sits in a git checkout and `copy`
otherwise, so someone who downloads the zip, installs, and deletes the folder still has
working skills. `list` and `install` print which mode was chosen and why.

`-Mode link` makes a directory junction from the target to `skills/<name>` in this repo.
No admin rights, no duplication, and edits are live. It requires the repo to stay on
disk at that path; deleting or moving it leaves dangling junctions and the skills
silently disappear.

`-Mode copy` duplicates the files and writes `.agent-skills-source.json` recording the
commit it came from (`unknown` from a zip). Use it where the repo is not kept — a machine
that only consumes skills, or a sandbox. `update` re-copies these; for junctions `update`
has nothing to do beyond the `git pull`, and says so.

`install.ps1` needs PowerShell 7. A downloaded copy may be blocked by the execution
policy; run `Get-ChildItem -Recurse | Unblock-File` in the folder first, or use
`pwsh -ExecutionPolicy Bypass -File install.ps1 ...`.

### On a fresh machine

```pwsh
git clone https://github.com/matty/agent-skills.git ~/code/agent-skills
pwsh -File ~/code/agent-skills/install.ps1 install
```

Or without git: download the repo zip, unzip, unblock, run `install`, then delete the
folder (auto mode copies).

## Conventions

- Prose in `SKILL.md` is instruction to an agent, not documentation for a human: say what
  to do and in what order. Lead with the decision, then the reasoning.
- Prefer a table or a short checklist over paragraphs when the content is a lookup.
- Scripts under `scripts/` must run standalone and say at the top what host they need
  (Blender's `bpy`, plain Python, etc.) — a skill script is often run by an agent that
  has not read the surrounding skill.
- ASCII in prose; no em dashes in skill bodies, to match the existing files.
- **Skills are independent.** Each skill works when it is the only one installed: it carries the scripts,
  conventions and numbers it needs. A skill may *name* another skill ("for automated unwrapping, load
  `rizomuv-uv-pipeline`") but never points into another skill's `scripts/` or `references/` by path, since
  installs can be partial and folders move. When two skills need the same convention (piece naming, a budget
  table), each states it; keep them in agreement when one changes. Skills work together by routing: an
  orchestrating skill tells an agent which skill to load, and that skill uses its own files.
- **Technique skills stay engine-neutral.** A skill about a craft that is not tied to one platform (topology, UV
  unwrapping, RizomUV) is written for any engine. What a specific engine does goes in that skill's
  `references/engine-notes.md`, one section per engine, with sources. VRChat- and Unity-specific skills carry the
  platform in their name.
