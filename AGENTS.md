# AGENTS.md — agent-skills

Skills for Claude Code and Codex. Both agents read the same format, so nothing in
this repo is specific to either one.

`AGENTS.md` and `CLAUDE.md` are the same file in spirit — an agent working in this repo
should read this one. It overrides `~/.agents/AGENTS.md` where they disagree.

## Layout

```
skills/<skill-name>/
  SKILL.md          required — YAML frontmatter + the skill body
  references/*.md   optional — detail loaded on demand, one topic per file
  scripts/*         optional — runnable helpers the skill points at
  templates/*       optional — files the skill tells an agent to copy into a project
install.ps1         the installer (see below)
tools/check_conventions.py   checks conventions duplicated across skills still agree
README.md           what each skill covers
AGENTS.md           this file
```

The folder name, the `name:` in frontmatter, and the heading in `README.md` must all match.
`install.ps1` only treats a folder as a skill if it contains `SKILL.md`, so drafts can sit
in `skills/` without a `SKILL.md` and stay invisible to the installer.

## SKILL.md format

```markdown
---
name: kebab-case-matching-the-folder
description: What it covers, then when to use it. One paragraph, no line breaks.
---

# Human readable title

Body.
```

The `description` is the only part an agent sees before deciding whether to load the
skill, so it carries the whole triggering burden. Write it as *what it covers* followed
by *when to use it* — name the symptoms and the words a user would actually type
("draw calls too high", "avatars render black"), not an abstract summary. If two skills
overlap, say in each which one wins, and route from the entry-point skill rather than
duplicating the material.

## Making changes

1. Edit under `skills/`. With the default `link` install the change is live in the
   repo immediately — no reinstall step. Restart the agent only when you add, rename
   or delete a whole skill, since both agents enumerate skills at startup.
2. Keep facts with a shelf life (Unity versions, platform limits, SDK APIs) next to a
   source URL in the skill, so a stale number is checkable rather than trusted.
3. Move anything long or narrow into `references/` and link to it from `SKILL.md`.
   `SKILL.md` should stay skimmable; depth lives one hop away.
4. Update `README.md`'s table when you add or rename a skill.
5. Run `python tools/check_conventions.py` if you touched a naming pattern, a budget number, the FBX export
   settings, the axis conversion, `kit_status`, or `kit_library.py` (shipped in two skills). It lists every copy
   that disagrees; update `CANON` in it when a fact really changes.
6. Commit the skill and its README row together. One skill per commit where practical;
   commit messages are `<skill-name>: what changed`.

### Adding a skill

```pwsh
mkdir skills/my-skill
# write skills/my-skill/SKILL.md with name: my-skill
pwsh -File install.ps1 install -Skills my-skill
# restart Claude Code / Codex
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
pwsh -File install.ps1 install -Skills vrchat-*,udon-performance
pwsh -File install.ps1 install                       # all of them
pwsh -File install.ps1 update -Prune
pwsh -File install.ps1 uninstall -Skills udon-performance
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
