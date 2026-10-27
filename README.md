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

Claude Code picks up new skills without a restart (run `/reload-skills` if one does not
appear); restart Codex, which scans for skills at startup.

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
| `blender-kit-library` | Modular kits in Blender: by default one MASTER .blend with KIT, ASM and layout collections (separate KIT / ASM files on request), editing alongside the user (snapshots of what changed, work-file checkout and integrate), instancing instead of copying, piece naming, grid modules and pivots, `kit_status`, one writer per file, plus a create / place / snapshot / audit `bpy` script with a CLI |
| `blender-mesh-topology` | Clean low-count topology and finished form: a high and low poly for baking (shading that bakes clean, edge widths in texels, silhouette and skew measured, parts paired), headless sculpts and cloth, pick a path (hand-designed grid with 3-to-1, 4-to-2 or 5-to-3 reductions, Quad Remesher from Python with frozen borders, hard-surface chamfers and weighted normals), finishing a greybox piece (detail hierarchy, what is geometry and at what size from stereo relief and on-screen width, chamfers and joints, sourced real-world sizes), fair blend surfaces, validation, plus grid / remesh / hard-surface / detail-scale / audit / review-render scripts |
| `3d-form-design` | Props, furniture and hard-surface objects right first time, not AI-looking: every decision in a JSON form spec (parts with real sizes, material, build method, attachment, taper / splay / crown, an edge list with bevel tiers or sharp) validated before any geometry, validated templates (dining table, dining chair, sideboard, bookcase, sofa), profile-first modelling, bevel sizes by material with a cap and a pixel floor, furniture sizes and anatomy, Blender API for each technique, one verification pass, plus a spec validator / build checker and a form audit (bevel widths, contact bevels, box-like and floating parts, silhouettes) |
| `uv-unwrapping` | Entry point for UVs: tiling, trim, unique or lightmap UVs, tiling that continues across kit joints (a phase-exact box projection and check, tiles that divide the grid, corners, curves, slopes), seams and hard edges for baking, distortion gate, texel density by viewing distance (T2048 handheld to T64), detail maps for close range, padding in pixels per mip, stacking and mirroring, lightmap UV2 sized for its footprint, Blender UV operators from Python, engine notes (Unity), plus a UV audit / layout `bpy` script with per-purpose checks |
| `pbr-texturing` | Texturing and materials for real-time 3D: a material plan per surface (tiling, trim, unique, decal, detail map), measured PBR values (Adobe's guide, physicallybased.info), mesh-map bakes through the Substance 3D baker CLI or Blender Cycles, Substance Designer and Painter routes, wear, variation and repetition, trim sheets, foliage and alpha, engine notes (Unity Standard, VRChat's mobile shaders), plus a PBR map checker (values, normal-map Y convention, tiling seams and tile-scale variation that draws a grid, calibrated on library textures), a seam check for unique textures and kit joints (colour and normal maps), a tile flattener, a Cycles bake script and a look-dev renderer |
| `image-to-pbr` | One image (photo, scan or generated pattern) to a tiling PBR map set: per-axis seam measurement, repeat detection with whole-period crops, delighting, base colour held to the dielectric range, normals from DeepBump's ML model (downloaded on demand at a pinned, hash-checked commit) with a built-in luminance fallback, height, AO, roughness and metallic from material presets, Unity or ORM packing, previews and a source record (hash, C2PA presence), plus a numpy converter and a DeepBump setup script |
| `pbr-texture-sources` | Search and download free CC0 PBR materials from Poly Haven and ambientCG through their public APIs: one search across both (physical size, resolutions, maps), downloads at a chosen resolution and format with one map naming scheme (BaseColor, NormalGL / NormalDX, Roughness, Metallic, AO, Height), MD5 and zip checks, safe extraction, a `source.json` with the licence and credit, the sites' own glTF / blend / MaterialX bundles on request, each API's terms, plus a standard-library `search` / `info` / `get` script |
| `rizomuv-uv-pipeline` | RizomUV 2027 driven headless from Python (RizomUVLink): fileless transfer from Blender, seam presets, minimum-distortion unwrap with a distortion and layout gate, texel-density and footprint-sized lightmap packing, the undocumented Pack behaviour, plus launcher / unwrap / metrics / Blender bridge / supervised pool / smoke-test scripts |

## Blender and Unity

| Skill | Covers |
|---|---|
| `blender-to-unity` | An ordered export pipeline: scale/axis conventions, one annotated FBX settings table, UV0/UV2 channel rules, atlasing, per-piece Unity folders, prefab variants and shared materials, LODs, collision, VRChat notes, plus batch-export / mesh-audit `bpy` scripts and a Unity import postprocessor (`KitImport.cs`) |
| `blender-unity-placement-sync` | Two-way layout sync between a MASTER .blend (its layout and assemblies, or split MASTER/ASM files) and Unity: stable placement ids, three-way merge against the last synced snapshot, conflict / duplicate / deletion handling with safety refusals (empty or mismatched dumps, mass deletions), plus `bpy` dump/apply, plain-Python merge and Unity editor scripts with a preflight check |

## VRChat world creation (Blender + Unity)

| Skill | Covers |
|---|---|
| `vrchat-world-optimization` | Entry point: profiling order, budgets (PC, and mobile = Android and iOS), pre-upload audit, routing to the rest |
| `vrchat-world-orchestration` | Master-agent pipeline for a whole world build: intake (with a PC-lead or parity quality tier), mockups or reference images, YAML world spec with the art direction (`look`), tiling tiles that divide the grid (validated), pieces marked for a high-poly bake, per-piece detail lists and generated SVG plans/elevations, a single MASTER .blend by default (KIT/ASM/MASTER collections; split files on request) kept in step with the user's own edits, spec, greybox and look gates, subagent briefs, QA after every task, resumable ledger, plus spec validator (with lightmap footprints) and SVG generator scripts |
| `unity-batching-and-instancing` | GPU instancing, static/dynamic batching, MaterialPropertyBlocks, atlasing, `VRCGraphics.DrawMeshInstanced`, plus an instanced UdonSharp field and an instancing-ready shader |
| `vrchat-lighting-and-baking` | Plan, bake, verify: lightmap footprints and capacity, bake settings, light probes plus VRC Light Volumes, reflection probes, LTCGI, Quest/iOS lighting, switchable lights, mirrors, occlusion culling; the final look (directional lightmaps for normal maps, a final-quality bake, lighting design, PC post-processing), plus a lightmap budget script |
| `vrchat-texture-and-vram` | Two procedures (download too big, VRAM too high), a per-map format table (BC7 / DXT / BC5 / ASTC), crunch limits, mip streaming and coverage, VRAM maths, the mobile 100 MB limit, mesh/audio import settings (mesh compression measured) |
| `vrchat-world-qa` | Independent stage-by-stage QA for world builds: pass/fail checklists from spec to platform builds (high and low poly, tiling phase, texture seams and kit joints, tile-scale repetition and repetition in the world among them), a fixed verdict block with not-run and waived results, visual review against mockups, plans and the spec's look, look-dev renders and PBR value checks for materials, the final lit look in Unity, plus a `bpy` measurement / render / overlay script |
| `vrchat-world-sdk-setup` | Worlds SDK setup and testing: Creator Companion project and Unity version, layers and collision matrix first, scene descriptor, allowlisted components, ClientSim and multi-client Build & Test, publish fields, cross-platform PC / Android / iOS builds on one blueprint ID, SDK behaviour observed in 3.10.5 |
| `vrchat-udon` | Udon / UdonSharp scripting: cost model, event-driven design, sync modes and budgets, `[NetworkCallable]` events, ownership, late joiners, pooling, debugging sync, compiled examples |

Facts with a shelf life (VRChat's required Unity version, platform limits, SDK APIs)
carry a source link in the skill — re-check those rather than trusting the number.

## Checks

```pwsh
python tools/run_checks.py                                   # conventions, structure lint, plain-Python tests
python tools/run_checks.py --blender "C:/path/to/blender.exe"   # plus the Blender-hosted tests
```

The plain tests use numpy and PyYAML when they are installed and skip what needs them
otherwise. CI runs the same command on every push (`.github/workflows/checks.yml`).
See [AGENTS.md](AGENTS.md) for when to add a test.
