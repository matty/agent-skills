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
install.ps1         the installer (see below)
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
5. Commit the skill and its README row together. One skill per commit where practical;
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
| `update` | `git pull --ff-only`, then refresh what is already installed |
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

| Target | Path |
|---|---|
| `claude` | `~/.claude/skills` |
| `codex` | `~/.codex/skills` |
| `agents` | `~/.agents/skills` |

Default is `-Targets claude,codex`.

**A target root may itself be a link.** On this machine `~/.claude/skills` is a junction
to `~/.agents/skills`. The installer detects that, resolves it, and installs into the
real folder — writing per-skill links *inside* an unresolved junction would silently
land them somewhere else. It prints which folder it chose, and visits a folder once
even when two targets resolve to it.

That hub layout is why `~/.agents/skills` can also hold skills that are not in this repo
(the Marvelous Designer ones, and the `synced/` folder). The installer only ever touches
entries it manages; anything else is reported as `Foreign` and skipped unless you pass
`-Force`.

### link vs copy

`-Mode link` (default) makes a directory junction from the target to `skills/<name>` in
this repo. No admin rights, no duplication, and edits are live. It requires the repo to
stay on disk at that path.

`-Mode copy` duplicates the files and writes `.agent-skills-source.json` recording the
commit it came from. Use it where the repo is not kept — a machine that only consumes
skills, or a sandbox. `update` re-copies these; for junctions `update` has nothing to do
beyond the `git pull`, and says so.

### On a fresh machine

```pwsh
gh repo clone matty/agent-skills ~/code/agent-skills
pwsh -File ~/code/agent-skills/install.ps1 install
```

## Conventions

- Prose in `SKILL.md` is instruction to an agent, not documentation for a human: say what
  to do and in what order. Lead with the decision, then the reasoning.
- Prefer a table or a short checklist over paragraphs when the content is a lookup.
- Scripts under `scripts/` must run standalone and say at the top what host they need
  (Blender's `bpy`, plain Python, etc.) — a skill script is often run by an agent that
  has not read the surrounding skill.
- ASCII in prose; no em dashes in skill bodies, to match the existing files.
