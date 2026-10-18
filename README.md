# agent-skills

Personal skills for Claude Code and Codex. Both agents read the same folder format
(`SKILL.md` with YAML frontmatter, plus optional `references/` and `scripts/`), so each
skill works in either one.

## Install

Needs PowerShell 7 (`pwsh`); Windows PowerShell 5.1 won't run it.

```pwsh
pwsh -File install.ps1 list                          # what's here, and where it's installed
pwsh -File install.ps1 install                       # all skills, into Claude Code + Codex
pwsh -File install.ps1 install -Skills vrchat-*      # a subset
pwsh -File install.ps1 update -Prune                 # git pull, refresh, drop removed skills
```

Restart Claude Code / Codex afterwards — both scan for skills at startup.

Skills go to `~/.claude/skills` (Claude Code) and `~/.agents/skills` (Codex). Add
`-Targets claude,agents,codex` only for an older Codex that still reads `~/.codex/skills`;
current Codex lists a skill twice if it finds it in both.

**From a git clone** the installer creates directory junctions (no admin rights, no
duplication) pointing back at the repo, so editing a skill here takes effect immediately.
Keep the clone where it is: deleting it breaks the junctions.

**From a downloaded zip** it copies the files instead, so you can delete the unzipped
folder afterwards. Windows may block a script downloaded from the internet, so either
unblock it first or bypass the policy for this one run:

```pwsh
Get-ChildItem -Recurse | Unblock-File                # once, in the unzipped folder
pwsh -File install.ps1 install
# or
pwsh -ExecutionPolicy Bypass -File install.ps1 install
```

To update a zip install, download the new zip and run `install` (or `update`) from it.

`-Mode link` / `-Mode copy` override the automatic choice. See [AGENTS.md](AGENTS.md)
for the full installer reference and for how to add or change a skill.

## General 3D in Blender (any engine)

| Skill | Covers |
|---|---|
| `blender-kit-library` | Modular kits across .blend files: KIT / ASM (one assembly per file) / MASTER files, linking instead of appending, piece naming, grid modules and pivots, `kit_status`, one writer per file, plus a create / link / place / audit `bpy` script with an audit CLI |
| `blender-mesh-topology` | Clean low-count topology: pick a path (hand-designed grid with 3-to-1, 4-to-2 or 5-to-3 reductions, Quad Remesher from Python with frozen borders, hard-surface chamfers and weighted normals), fair blend surfaces, validation, plus grid / remesh / hard-surface (`scripts/hard_surface.py`: Smooth by Angle first, the stack's hand-off to UV work) / audit / review-render `bpy` scripts |
| `uv-unwrapping` | Entry point for UVs: tiling, trim, unique or lightmap UVs, seams and hard edges for baking, distortion, texel density, padding in pixels per mip, stacking and mirroring, lightmap UV rules, Blender UV operators from Python, engine notes (Unity), plus a UV audit / texel-density / pack `bpy` script |
| `rizomuv-uv-pipeline` | RizomUV driven headless from Python (RizomUVLink): fileless transfer from Blender, seam presets, minimum-distortion unwrap with a measured quality gate, texel-density and lightmap packing, the undocumented Pack behaviour, plus launcher / unwrap / metrics / Blender bridge / process pool / smoke-test scripts |

## Blender and Unity

| Skill | Covers |
|---|---|
| `blender-to-unity` | Scale/axis conventions, FBX export settings, UV0/UV2 channel rules, atlasing, per-piece Unity folders, prefabs and shared materials, LODs, collision, VRChat notes, plus batch-export / mesh-audit `bpy` scripts |
| `blender-unity-placement-sync` | Two-way layout sync between MASTER/ASM .blend files and Unity: stable placement ids, three-way merge against the last synced snapshot, conflict / duplicate / deletion handling, plus `bpy` dump/apply, plain-Python merge and Unity editor scripts |

## VRChat world creation (Blender + Unity)

| Skill | Covers |
|---|---|
| `vrchat-world-optimization` | Entry point: profiling order, budgets, pre-upload audit, routing to the rest |
| `vrchat-world-orchestration` | Master-agent pipeline for a whole world build: intake, mockups, YAML world spec with generated SVG plans/elevations, KIT/ASM/MASTER .blend structure, greybox and user gates, subagent briefs, QA after every task, resumable ledger, plus spec validator and SVG generator scripts |
| `unity-batching-and-instancing` | GPU instancing, static/dynamic batching, MaterialPropertyBlocks, atlasing, `VRCGraphics.DrawMeshInstanced`, instancing-ready shader code |
| `vrchat-lighting-and-baking` | Lightmap baking, lightmap UVs and texel density, VRC Light Volumes, probes, reflection probes, LTCGI, mirrors, occlusion culling |
| `vrchat-texture-and-vram` | Compression formats, VRAM maths, download size, the Quest 100 MB limit, mesh/audio import settings |
| `vrchat-world-qa` | Independent stage-by-stage QA for world builds: pass/fail checklists from spec to optimisation, a fixed verdict block, visual review against mockups and plans, plus a `bpy` measurement / ortho-render / overlay script |
| `vrchat-world-sdk-setup` | Worlds SDK setup and testing: Creator Companion project and Unity version, scene descriptor, reserved and free layers, allowlisted components, ClientSim and multi-client Build & Test, publish fields, cross-platform PC / Android / iOS builds on one blueprint ID |
| `vrchat-udon` | Udon / UdonSharp scripting: cost model, event-driven design, sync budgets, ownership, late joiners, pooling |

Facts with a shelf life (VRChat's required Unity version, platform limits, SDK APIs)
carry a source link in the skill — re-check those rather than trusting the number.
