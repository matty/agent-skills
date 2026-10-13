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

## VRChat world creation (Blender + Unity)

| Skill | Covers |
|---|---|
| `vrchat-world-optimization` | Entry point: profiling order, budgets, pre-upload audit, routing to the rest |
| `unity-batching-and-instancing` | GPU instancing, static/dynamic batching, MaterialPropertyBlocks, atlasing, `VRCGraphics.DrawMeshInstanced`, instancing-ready shader code |
| `vrchat-lighting-and-baking` | Lightmap baking, lightmap UVs and texel density, VRC Light Volumes, probes, reflection probes, LTCGI, mirrors, occlusion culling |
| `vrchat-texture-and-vram` | Compression formats, VRAM maths, download size, the Quest 100 MB limit, mesh/audio import settings |
| `blender-to-unity-vrchat` | Scale/axis conventions, FBX export settings, UV2 authoring, modular kits as KIT / ASM / MASTER .blend files with linked collections, piece naming and pivots, per-piece Unity folders and prefabs, LODs, collision, plus batch-export / UV2 / mesh-audit / kit-library `bpy` scripts |
| `blender-unity-placement-sync` | Two-way layout sync between MASTER/ASM .blend files and Unity: stable placement ids, three-way merge against the last synced snapshot, conflict / duplicate / deletion handling, plus `bpy` dump/apply, plain-Python merge and Unity editor scripts |
| `udon-performance` | UdonSharp cost model, event-driven design, sync budgets, ownership, late joiners, pooling |
| `blender-mesh-topology` | Clean low-count topology: hand-designed grids with 3-to-1 reductions, fair blend surfaces, Quad Remesher from Python with frozen borders, plus grid / remesh / audit / review-render `bpy` scripts |
| `uv-unwrapping` | Entry point for UVs: tiling, trim, unique or lightmap UVs, seams and hard edges for baking, distortion, texel density, padding in pixels per mip, stacking and mirroring, lightmap UV2 rules, Blender UV operators from Python, plus a UV audit / texel-density / pack `bpy` script |
| `rizomuv-uv-pipeline` | RizomUV driven headless from Python (RizomUVLink): fileless transfer from Blender, seam presets, minimum-distortion unwrap with a measured quality gate, texel-density and lightmap packing, the undocumented Pack behaviour, plus launcher / unwrap / metrics / Blender bridge / process pool / smoke-test scripts |

Facts with a shelf life (VRChat's required Unity version, platform limits, SDK APIs)
carry a source link in the skill — re-check those rather than trusting the number.
