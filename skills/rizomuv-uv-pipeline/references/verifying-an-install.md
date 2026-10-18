# Verifying an install

These checks test the pipeline itself, not a mesh. **Do not run them before an ordinary unwrap**: every unwrap
is graded as it runs, and its report line already says which pieces failed and why. Run them only when one of
these applies:

| Situation | Run |
|---|---|
| First use on a machine, or `import RizomUVLink` or the launch fails | `rizom_link.py` |
| RizomUV upgraded | `probe_pack_enums.py`, then the smoke test |
| Blender upgraded, or the scripts edited | the smoke test |
| `Pack` does nothing, packs land at the wrong size or density, or stretch maps come out one colour, on more than one mesh | `probe_pack_enums.py` |
| Parallel jobs return each other's meshes, or the session code in `rizom_link.py` was edited | `rizom_pool.py --selftest 3` |

`<python>` below is a Python 3.6-3.13, such as Blender's bundled one: `<blender>/<version>/python/bin/python.exe`
on Windows.

## Contents

- The checks
- Last measured run
- If a check fails
- Comparing runs
- What these checks guard against

## The checks

| Command | Time | Passes when |
|---|---|---|
| `<python> scripts/rizom_link.py` | a few seconds | it prints the executable, the RizomUVLink folder, the file version (2027.0.417 or later), the temp folder, the version and the port, then `quit ok` |
| `<python> scripts/probe_pack_enums.py` | a few seconds | every line says PASS (exit code 0) |
| `blender -b --factory-startup --python-exit-code 1 --python scripts/smoke_test_blender.py` | 40-60 s | `SMOKE TEST PASSED` and exit code 0 |
| `<python> scripts/rizom_pool.py --selftest 3` | about 12 s | three workers started at the same instant each get their own instance (distinct ports and PIDs), and every mesh comes back with its own corner count |

`rizom_link.py` finds the install, refuses a build too old for headless mode, launches RizomUV headless and quits
it. If it fails, nothing else will work.

`probe_pack_enums.py` re-checks the behaviour the pack and the stretch maps rely on: the `Scaling.Mode` and
`LayoutScalingMode` integers, the `Fill` default of `Scaling.Optimization` (and that `"None"` works in the top-level
call), `TexelDensity` being per 100 mesh units, an overflowing pack leaving the islands untouched without an error,
the rejected top-level `Global`, RizomUV grading stretch maps by linear scale (it decodes the PNGs itself), and
`Rotate.Initial` `"Vertical"` and `"Horizontal"` turning islands as directional packs need. RunRizomUV's launch lock
is not probed there: `rizom_pool.py --selftest` checks that parallel sessions each get their own instance.

`smoke_test_blender.py` builds a pointed-arch portal surround (hard preset, generator seams at the springing
lines and apex) and a revolved urn on a bevelled plinth (organic preset, auto seams only), unwraps both through
`blender_rizom.py` with a lightmap UV at a 20 texels/m footprint and grades every layer. Then it checks that a
texel-density pack lands on its target, that an impossible density writes nothing, that an imported first UV layer
does not end up in the lightmap slot, that a small piece's lightmap gaps are at least 2 texels at its footprint with
the under-64 px note, that linked duplicates with a Mirror are each unwrapped with `modifiers="apply"`, that planks
packed with `directional="grain"` all run along U, that a sign with `rizom_directional="upright"` reads world up as
+V, that a 1-segment chamfered box goes on to the organic preset instead of printing OK at 0.1-0.2 coverage, that a
bevelled 2.4 m strip at 512 px/m fits 2048 px through the organic preset, that a 3 m beam prints OK with a thin-piece
note, that a mesh shared by a full-size and a half-size object keeps 2-texel lightmap gaps at the smaller footprint,
that a plank whose half-size copy gets 3.3 px gets a lightmap UV packed for 64 px with the too-small note, that a
mitred window frame and a 5-step stair pass (one island per planar region is not confetti), and that a craggy
5120-face rock prints OK with its many-islands note and a UV2 packed for a larger footprint. Add
`-- --png <dir>` to also write both stretch maps and check they are mostly grey, `--keep out.blend` to keep the
scene. FAIL and REVIEW lines in an ordinary batch never set Blender's exit code; the smoke test raises on them, and
a batch of your own ends with `br.raise_on_failure(reps)`.

## Last measured run

RizomUV 2027.0.598 (file version 2027.0.598, `2027.0.598.g864535413`), Windows 11, Blender 5.2.2 and its Python
3.13, 17 Oct 2026:

| Check | Result |
|---|---|
| `rizom_link.py` | launched in 1.7-3.2 s on port 61000, tied to the host by a Job Object, quit ok; also with a 150-character temp folder (RizomUV and the link object were given `%LOCALAPPDATA%\Temp`) |
| `probe_pack_enums.py` | 19 of 19 PASS; stretch grey share 1.00 with the linear neutral, 0.00 with the area ratio; `Rotate.Initial` Vertical and Horizontal as documented |
| smoke test | PASSED in 17-39 s (the longer with other jobs on the machine): arch 22 islands, angular p95 1.00, area p95 0, coverage 0.59; urn 18 islands, angular p95 1.09, area p95 0.10, coverage 0.55 (its 48 px footprint prints the under-64 note); 300 px/m asked, 300.0 got; 5000 px/m on 256 px reported and nothing written; the 0.41 m box's footprint 28.4 px at its measured bounding-box share, closest lightmap gap 3.1 texels; 24 of 24 plank faces along U; the sign's world up at +V; the chamfered box OK through the organic preset at coverage 0.62; the bevelled strip OK through the organic preset at 512 px/m on 2048 px; the beam OK at coverage 0.158 with its thin-piece note; the shared mesh's footprints 67.5 and 33.7 px, graded at 33.7, closest gap 2.9 texels; the plank's lightmap UV packed for 64 px (its copy gets 3.3 px); the frame 16 islands and the stair 14, both OK; the rock 499 islands at coverage 0.21, OK with its notes and a UV2 packed for 256 px (46 px own footprint); both duplicates unwrapped; 48 s on 18 Oct 2026 |
| `rizom_pool.py --selftest 3` | PASSED in 8.5-16.4 s: 3 workers on ports 61000/61002/61004, 6 meshes |
| forty 1 m cubes, default UV2, one call | 30.2 s: 0.51-0.85 s per object (median 0.68), all OK |
| RizomUV killed as the 2nd of 4 objects started | that object FAIL (`RizomUV is not responding`, 2.0 s), restart, the other three OK |
| a 1 s timeout on a 22k-quad organic unwrap | FAIL `timed out after 1 s; RizomUV restarted`, the next object OK |
| an 8 s timeout during an 82k-face auto-seam (158 s uninterrupted on a busy machine; 26-29 s idle) | killed mid-command from the deadline process: FAIL after 10.1 s, the next object OK |
| that timeout, then an object with a Mirror modifier | the modifier refusal reported (not "timed out"), no second restart |
| three Blender jobs started on one .blend | one unwrapped and saved; the other two stopped at once (`held by another Blender job`), exit 1; no lock file left |
| the pool's host killed mid-batch | no worker and no rizomuv.exe left |
| ports 61000 (listening) and 61003 (bound) taken | the session took 61004 |

## If a check fails

| Failing check | Likely cause | Fix |
|---|---|---|
| `rizom_link.py`: `import RizomUVLink` | Python 3.14+, or the package was not found | Blender's bundled Python; `RIZOMUVLINK_DIR` pointing at `<install>/RizomUVLink` |
| `rizom_link.py`: executable not found | not installed where the registry or the default paths say | `RIZOMUV_EXE` pointing at `rizomuv.exe` (Linux: the AppDir's `AppRun`) |
| `rizom_link.py`: "cannot run headless" | RizomUV older than 2027.0.417 | upgrade it, or use `headless=False`, or the `uv-unwrapping` skill |
| `rizom_link.py`: "exited before opening port" | no licence (a headless instance answers the dialog "no" and exits), or an unknown flag | start RizomUV once with its window to activate it; read the end of `<Documents>/RizomUV/<major>/logs/CommandLog.py` |
| `rizom_link.py`: "running but did not open port" | an old build showing a usage box, a reserved port, no logged-in desktop session (a service, a scheduled task, SSH), or a first launch slowed by antivirus | run it in the logged-in session; `netsh int ipv4 show excludedportrange protocol=tcp`; run it again |
| the host aborts with a libzmq assertion | the temp folder is still too long for libzmq | set TMP and TEMP to a folder path under about 90 characters |
| `probe_pack_enums.py`: an enum check | RizomUV renumbered the Pack enums | update `SCALING_*` and `LAYOUT_*` at the top of `rizom_uv.py` and the tables in `api-cheatsheet.md`, then run the smoke test |
| `probe_pack_enums.py`: Fill, per-100-units or overflow check | RizomUV changed or fixed that behaviour | adjust `rizom_uv.pack` and `pack_spec`, then update `api-cheatsheet.md` and the traps in it |
| `probe_pack_enums.py`: the stretch-map check | RizomUV now grades area, as its docstring says | set the neutral to UV area / 3D area in `rizom_uv.stretch_map`, band 1.25 squared |
| smoke test: distortion or coverage numbers | preset behaviour changed with the RizomUV version | rerun the sweep in `distortion-and-quality.md` before changing `PRESETS` |
| `--selftest`: a mesh came back with another's corner count, or two workers share a port | sessions sharing a port | do not use RizomUVLink's `RunRizomUV` for parallel work; see "Running several instances" in `api-cheatsheet.md` |

## Comparing runs

RizomUV is not bit-deterministic on every mesh: an organic Suzanne came back with 76-79 islands across calls and
processes, while the arch, the urn and a torus were bit-identical, and the grades held (angular p95 identical to 4
decimals). Regression checks compare metrics with tolerances, never hashes of the UVs: islands within about 5%,
angular p95 within 0.01, coverage within 0.02, texel density exact.

## What these checks guard against

Each of these failed silently once while the skill was being built or reviewed:

- The first run's UVs came back at metre scale: `Pack` had done nothing, because after a fileless load no island
  is in a tile.
- The default `Fill` made a texel-density pack look as if it had worked: every island had one density, just not
  the one asked for.
- Three processes launched together all ended up on one RizomUV instance and swapped meshes without an error:
  RizomUVLink's launch lock makes the loser join the winner.
- Fan triangulation graded one folded quad on Suzanne at 13.3 and the same quad with its corners rotated at 1.4.
  A grade must not depend on where a polygon starts.
- A checker looked fine in a viewport while angular p95 was 1.44.
- A 115-character temp folder (an agent's scratch folder) made RizomUV exit at start and the host abort inside
  `Connect`; 79 characters worked.
- `modifiers="apply"` on linked duplicates unwrapped the first copy and reported the others SHARED with their old
  UVs.
- An imported mesh's only UV layer slid to index 1, the lightmap channel, when no lightmap UV was written.
- A fixed 128 px lightmap pack left 0.7-texel gaps on 1 m2 pieces at 20 texels/m.
- Killing a pool's host left its workers, their RizomUV instances and their licence tokens running.
- `Rotate.Step` 0 alone, the old "directional" pack, left 39 of 76 plank faces with their grain along V.
- 1-segment chamfered boxes packed at 0.10-0.22 coverage under the hard preset and still printed OK.
- A crate of 19 planks (one island per face, 6 per box) went to REVIEW for fragmentation counted over the whole
  mesh instead of per shell.
- A Blender batch whose RizomUV could not start printed the error, wrote no report and exited 0: without
  `--python-exit-code 1` Blender ignores Python errors (FAIL and REVIEW lines never set it either).
- Three parallel Blender jobs saved one .blend: all printed OK, and only the last job's UVs were in the file.
- A per-object timeout was a thread timer, which cannot run while a RizomUVLink call holds the GIL: an 8 s timeout
  fired after 78 s, when the auto-seam returned.
- A bevelled strip packed at a texel density did not fit under `hard`, and the ladder stopped without trying the
  organic preset, which fits.
- A 3 m beam and a plank went to REVIEW for coverage that their shape cannot beat.
- A plank's half-size copy got a 3.3 px lightmap footprint: its charts were squeezed into a 1152 px overlap, and
  the overlapping lightmap UV was written.
- A linked mesh with the same name as a local one printed SHARED instead of FAIL, and a library-override mesh
  printed OK while its UVs were lost on reload.
- After a timeout, the next object refused by `check_object` was reported "timed out" and RizomUV restarted again.
- A UV2 re-run at a lower texel density left the old `UVMap_Lightmap` at index 1, packed for the old footprint.
- Three chamfered cubes 5 m apart in one object read a shape limit of 0.14 over the whole object and printed OK as a
  "thin piece" at 0.33; per shell the limit is 1 and the organic preset gives 0.57.
- A round table top, a washer, a hoop and an L bracket went to REVIEW with advice about chamfers they do not have.
- The many-islands row said "a bigger map", which cannot help: the gap cap scales with the map.
- A LOD1 mesh's UV2 was packed for LOD0's footprint, twice what Unity gives it.
- `modifiers="apply"` on a hard-surface piece after uv-unwrapping's `apply_stack` baked the viewport mesh and dropped
  its Triangulate and Weighted Normal: normals 12.59 deg off after the kit FBX export. The Triangulate, off in the
  viewport, had also been refused as a modifier.
- A craggy 5120-face rock went to REVIEW as "one sprawling island" and ended with no UV2: its 64 px fallback failed
  too. A mitred frame and a 5-step stair went to REVIEW as confetti, counted against faces.
