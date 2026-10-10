# Verifying an install

These checks test the pipeline itself, not a mesh. **Do not run them before an ordinary unwrap**: every unwrap
is graded as it runs, and its report line already says which pieces failed and why. Run them only when one of
these applies:

| Situation | Run |
|---|---|
| First use on a machine, or `import RizomUVLink` or the launch fails | `rizom_link.py` |
| RizomUV upgraded | `probe_pack_enums.py`, then the smoke test |
| Blender upgraded, or the scripts edited | the smoke test |
| `Pack` does nothing, or packs land at the wrong size or density, on more than one mesh | `probe_pack_enums.py` |
| Parallel jobs return each other's meshes, or the session code in `rizom_link.py` was edited | `rizom_pool.py --selftest 3` |

`<python>` below is a Python 3.6-3.13, such as Blender's bundled one: `<blender>/<version>/python/bin/python.exe`
on Windows.

## Contents

- The checks
- If a check fails
- Comparing runs
- What these checks guard against

## The checks

| Command | Time | Passes when |
|---|---|---|
| `<python> scripts/rizom_link.py` | a few seconds | it prints the executable, the RizomUVLink folder, the version and the port, then `quit ok` |
| `<python> scripts/probe_pack_enums.py` | a few seconds | every line says PASS (exit code 0) |
| `blender -b --factory-startup --python scripts/smoke_test_blender.py` | about 10 s | exit code 0 |
| `<python> scripts/rizom_pool.py --selftest 3` | about 10 s | each of three workers, started at the same instant, gets its own mesh back from its own instance |

`rizom_link.py` finds the install, launches RizomUV headless and quits it. If it fails, nothing else will work.

`probe_pack_enums.py` re-checks the undocumented behaviour the pack relies on: the `Scaling.Mode` and
`LayoutScalingMode` integers, the `Fill` default of `Scaling.Optimization`, `TexelDensity` being per 100 mesh
units, an overflowing pack leaving the islands untouched without an error, and the rejected top-level `Global`.

`smoke_test_blender.py` builds a pointed-arch portal surround (hard preset, generator seams at the springing
lines and apex) and a revolved urn on a bevelled plinth (organic preset, auto seams only), unwraps both through
`blender_rizom.py`, grades them, checks that a texel-density pack lands on its target and that an impossible
density writes nothing. Expected on RizomUV 2027.0.598: arch angular 1.00 and coverage about 0.60; urn angular
p95 about 1.09 and area p95 about 0.10; no overlaps, flips, padding or margin breaches. Add `-- --png <dir>` to
also write and check both stretch maps, `-- --keep out.blend` to keep the scene.

## If a check fails

| Failing check | Likely cause | Fix |
|---|---|---|
| `rizom_link.py`: `import RizomUVLink` | Python 3.14+, or the package was not found | Blender's bundled Python; `RIZOMUVLINK_DIR` pointing at `<install>/RizomUVLink` |
| `rizom_link.py`: executable not found | not installed where the registry or the default paths say | `RIZOMUV_EXE` pointing at `rizomuv.exe` |
| `rizom_link.py`: times out | no logged-in desktop session (a service, a scheduled task, SSH), or a first launch slowed by antivirus | run it in the logged-in session; run it again |
| `probe_pack_enums.py`: an enum check | RizomUV renumbered the Pack enums | update `SCALING_*` and `LAYOUT_*` at the top of `rizom_uv.py` and the tables in `api-cheatsheet.md`, then run the smoke test |
| `probe_pack_enums.py`: Fill, per-100-units or overflow check | RizomUV changed or fixed that behaviour | adjust `rizom_uv.pack` and `pack_spec`, then update `api-cheatsheet.md` and the traps in `SKILL.md` |
| smoke test: distortion or coverage numbers | preset behaviour changed with the RizomUV version | rerun the sweep in `distortion-and-quality.md` before changing `PRESETS` |
| `--selftest`: a worker got another worker's mesh | sessions sharing a port | do not use RizomUVLink's `RunRizomUV` for parallel work; see "Running several instances" in `api-cheatsheet.md` |

## Comparing runs

RizomUV is not bit-deterministic on every mesh: an organic Suzanne came back with 76-79 islands across calls and
processes, while the arch, the urn and a torus were bit-identical, and the grades held (angular p95 identical to 4
decimals). Regression checks compare metrics with tolerances, never hashes of the UVs: islands within about 5%,
angular p95 within 0.01, coverage within 0.02, texel density exact.

## What these checks guard against

Each of these failed silently once while the skill was being built:

- The first run's UVs came back at metre scale: `Pack` had done nothing, because after a fileless load no island
  is in a tile.
- The default `Fill` made a texel-density pack look as if it had worked: every island had one density, just not
  the one asked for.
- Three processes launched together all ended up on one RizomUV instance and swapped meshes without an error:
  RizomUVLink's launch lock makes the loser join the winner.
- Fan triangulation graded one folded quad on Suzanne at 13.3 and the same quad with its corners rotated at 1.4.
  A grade must not depend on where a polygon starts.
- A checker looked fine in a viewport while angular p95 was 1.44.
