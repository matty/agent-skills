# agent-skills

Personal skills for Claude Code and Codex. Both agents read the same folder format
(`SKILL.md` with YAML frontmatter, plus optional `references/` and `scripts/`), so each
skill works in either one.

## Install

```pwsh
pwsh -File install.ps1 list                          # what's here, and where it's installed
pwsh -File install.ps1 install                       # all skills, into Claude Code + Codex
pwsh -File install.ps1 install -Skills vrchat-*      # a subset
pwsh -File install.ps1 update -Prune                 # git pull, refresh, drop removed skills
```

Restart Claude Code / Codex afterwards — both scan for skills at startup.

By default the installer creates directory junctions (no admin rights, no duplication)
pointing back at this repo, so editing a skill here takes effect immediately. Use
`-Mode copy` on a machine where this repo isn't kept. See [AGENTS.md](AGENTS.md) for the
full installer reference and for how to add or change a skill.

## VRChat world creation (Blender + Unity)

| Skill | Covers |
|---|---|
| `vrchat-world-optimization` | Entry point: profiling order, budgets, pre-upload audit, routing to the rest |
| `unity-batching-and-instancing` | GPU instancing, static/dynamic batching, MaterialPropertyBlocks, atlasing, `VRCGraphics.DrawMeshInstanced`, instancing-ready shader code |
| `vrchat-lighting-and-baking` | Lightmap baking, lightmap UVs and texel density, VRC Light Volumes, probes, reflection probes, LTCGI, mirrors, occlusion culling |
| `vrchat-texture-and-vram` | Compression formats, VRAM maths, download size, the Quest 100 MB limit, mesh/audio import settings |
| `blender-to-unity-vrchat` | Scale/axis conventions, FBX export settings, UV2 authoring, modular kits, LODs, collision, plus batch-export / UV2 / mesh-audit `bpy` scripts |
| `udon-performance` | UdonSharp cost model, event-driven design, sync budgets, ownership, late joiners, pooling |

Facts with a shelf life (VRChat's required Unity version, platform limits, SDK APIs)
carry a source link in the skill — re-check those rather than trusting the number.
