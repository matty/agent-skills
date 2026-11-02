# From a generated high to a baked low: a measured run

One whole run on 2026-11-02 (Blender 5.2.2, RizomUV 2027.0.598, ComfyUI 0.43.2, RTX 3090 Ti): a tree stump from a
text prompt to a 2.3k-triangle low with baked maps, viewed at 1.5 m. Each step used the owning skill's own scripts;
this file records what worked and what did not, so the next run starts from the working route.

| Step | Skill and call | Time |
| --- | --- | --- |
| Four input images, one picked by the checklist (one rejected for moss the prompt excluded) | `comfy.py run` (Z-Image-Turbo) | 4 s each |
| Pixal3D, `RemeshMesh.sign_mode=solid` | `comfy.py run` | 252 s |
| Intake: welded, levelled (27.3 degrees), 0.5 m high; one closed manifold shell, thin gaps 0.066 | `glb_intake.py --upright` | 12 s |
| Low, UVs, bake (normal, AO, base colour, roughness, metallic, 1024, fitted cage) | the three skills below | 74 s |

## 1. The low poly and its UVs

Two routes on the same high (700k triangles):

| | Decimate + Smart UV Project | QuadriFlow + RizomUV `organic` |
| --- | --- | --- |
| Low | `blender-mesh-topology` organic route, Decimate to 3k: 2,982 triangles | Decimate to 60k first (QuadriFlow on 700k is slow), then `quadriflow_remesh(target_faces=1500)`: 2,320 triangles |
| `high_low_gap` at 1.5 m | low outside 4.2 mm (limit 2.6), relief p99 4.6 mm (limit 31) | low outside 8.1 mm (the sharp rim of the cut top rounded off), relief p99 16.9 mm |
| UVs | 583 islands, 25% of the map, 485 px/m, angular p95 1.41 | 94 islands, 46% of the map, 710 px/m, angular p95 1.08 (RizomUV's grade), passed on its second attempt |
| `bake_skew` against the low's faces | 67% over 15 degrees, p95 60 | 43%, p95 40 |

Decimate's long thin triangles shatter Smart UV Project into hundreds of islands and lean the bake's rays.
A third route, the same day: **Quad Remesher** on a clean 83k-quad remesh of the high (`blender-mesh-topology`'s
`quad_remesh(pts, faces, TargetQuadCount=1180, ExactQuadCount=1)`; its `patch_input` refuses closed meshes, the
engine call does not):

| Low at a matched count | QuadriFlow | Quad Remesher |
| --- | --- | --- |
| Triangles | 2,320 | 2,162 |
| `bake_skew` against its own faces | 43%, p95 40 | 24%, p95 29 |
| `high_low_gap`: low outside max / relief p99 | 8.1 / 16.9 mm | 7.2 / 10.4 mm |
| RizomUV `organic` | 94 islands, 46%, second attempt | 46 islands, 52%, first attempt |
| Time | 8 s (plus the 60k decimate) | 23 s (plus 77 s for the 83k remesh of the high it ran on) |

Use **Quad Remesher with `ExactQuadCount=1`, then RizomUV `organic`**; QuadriFlow where Quad Remesher is not
installed. Adaptive count overshoots a budget: 1,300 quads asked gave 3,622 (7,148 triangles). Without RizomUV,
`uv-unwrapping`'s organic workflow (hidden seams, minimum-stretch unwrap). Where the low's outline must hold a
sharp edge (the cut top's rim), add loops there or raise the count: the budget for a stump is 2-5k triangles
(`blender-mesh-topology`).

Delete the faces that always sit on the ground before the UVs (organic route): their seams are free, and their
texels are not wasted. The cut leaves an open bottom; that is expected on a prop that never leaves the ground.

## 2. Improving the high: remesh and subdivide only when it fails the matcap check

Tested: Quad Remesher on the 700k-triangle high to a clean quad cage (60k asked, 83,240 given, 77 s), then
Subdivision Surface level 2 (2.66M triangles), with and without a Shrinkwrap back onto the original.

- Matcap: the original `solid` output was already clean (no ripples, facets or voxel steps: its remesh smooths with
  Taubin passes). Subdivided, the bark plates melted (p99 3.7 mm of the original's relief lost); Shrinkwrapped back
  it was the original surface again, within 1-2 mm, at four times the triangles.
- Baked onto the same low: the subdivided high gave a visibly softer normal map; the original and the Shrinkwrapped
  one baked the same.

So check the high first (`blender-mesh-topology`'s reflective matcap close-up). Remesh and subdivide only when it shows
lumps, facets, voxel steps or holes (fill holes first), which is likeliest on smooth subjects (ceramic, metal,
plastic) and on `udf` outputs. Detail lives in the original: bake base colour, roughness and metallic from the
original either way, since the remesh has none of its UVs or textures.

**Where it pays: a smooth subject.** A velvet cushion (multi-view Pixal3D, `solid`) failed the matcap: concentric
ripple rings about 25 mm apart across both faces, from the generator's voxel stages, and crumpled edges. They baked
straight into the normal map. The cage size decides whether the fix works:

| High (Quad Remesher cage, then Subdivision Surface) | Quads in the cage (asked) | Ripples in the matcap and the bake | Form vs the original, p99 |
| --- | --- | --- | --- |
| 64,046 (60,000), level 2 | about 2-3 mm edges | kept: the cage follows them | 0.5 mm |
| 6,614 (4,000), level 3 | about 9 mm edges | nearly gone, soft wrinkles near the edges kept | 1.3 mm |
| 2,165 (1,500), level 3 | about 16 mm edges | gone: a clean, puffy cushion | 2.4 mm |
| Corrective Smooth on the original | | kept: it restores its rest shape, which is the rippled one | 0 |

Size the cage so its edges are at least a third of the fault's spacing, then subdivide back to a dense high; look
at the matcap again. Quad Remesher overshoots the asked count by 40-65% at these sizes (adaptive count).

**The cushion's low passed every gate** (Quad Remesher, `ExactQuadCount=1`, 600 asked, 725 quads, 1,450 triangles,
at 1.5 m): low outside 2.5 mm (limit 2.6), `bake_skew` 4% over 15 degrees against its own faces (a smooth convex form
behaves like hard surface here), RizomUV 19 islands on 51% at angular p95 1.02 on its first attempt.

## 3. The bake

**Colour.** The generated base colour is shifted: the cushion's input views measured hue 2 degrees (dusty rose) and
its baked base colour hue 34.7 (tan), so the shift is in the generator's texture stage, not the image. After the bake,
`scripts/colour_match.py` against the four views moved it to hue 2.2 at saturation 0.27 (views 0.29), lightness
unchanged.


`pbr-texturing`'s `bake_maps.py` with `maps=("normal", "ao", "basecolor", "roughness", "metallic")` and
`cage="fitted"`: the material maps copy the generated textures (4096) onto the low's UVs through the same cage, so
the colour lines up with the baked relief. 46 s on the CPU for five maps at 1024 with supersample 2; the fitted cage
reported 9 own and 2 neighbour rays starting inside the high out of 16,240.

Cycles' normal bake includes the high's own normal map, so the generated normal detail (baked by the generator
from its 17M-face mesh) reaches the low too.

## 4. The gate on an organic generated prop

- **Look first.** Rendered with `pbr-texturing`'s look-dev renderer, high (its own material) beside low (the baked
  maps), from the player's views: from 1.5 m the low read the same as the high; at 0.4 m it was softer (1024 against
  the generated 4096) and its root tips rounder.
- **Seams**: `texture_seams.py` on the base colour: no seam shows. On the normal map: 0.11 m of 19.5 m of seams
  over the limit, the worst between two roots at the front, visible only in a 0.4 m close-up. Move that seam
  under the root or accept it for a prop seen from 1.5 m.
- **`bake_skew` limits are for hard surface.** On bark the measure against the high reads the furrows' own slopes
  (64% over 15 degrees, a "shift" of 112 mm on a 0.5 m stump whose bake rendered correctly), and against the low's
  own faces any smooth-shaded organic low with few faces reads high (43% for QuadriFlow). Use it to compare two lows,
  not as a pass mark; the close render and the seam check are the gate here.
- **Density**: 710 px/m fits T512 (1.5-3 m). For a prop seen within 0.75-1.5 m, bake at 2048.

## 5. A set of props to FBX: a market stall (2026-11-02)

Four props from four Codex turnaround sheets in one shared style: a terracotta pot (open top), a cast-iron cauldron
with a bail handle and three legs, a burlap sack tied with rope, a wooden crate (the negative test: hard surface).
Multi-view Pixal3D, then into one KIT file with `blender-to-unity`'s structure and its export and audit scripts.

| Step | Result |
| --- | --- |
| Generation | Pot 566 s, crate 591 s, cauldron 187 s, sack 229 s: the time follows the raw mesh before the remesh (35M and 40M faces against 12M and 16M), not a model reload |
| Open vessels | Pot and cauldron came out **open**, interior modelled, although no level view shows inside: `solid` remesh does not cap a real opening (the barrel's sealed cavity was a closed generated shape) |
| Thin parts | The cauldron's bail handle came out whole and attached; at 1,470 triangles its round bar is visibly faceted, and its strip-like UV islands carried most of the bake faults below |
| Colour | Corrected per prop on each high's own texture before the bake (one atlas cannot be matched per prop): sack hue 48.9 to 30.1 (views 29.9), cauldron 31.6 to 27.8, crate 30.0 to 28.5, pot 22.1 to 22.9 |
| Matcap | Pot ripple rings and cauldron facets: smoothed (2,000 and 2,500-quad cages, subdivision 3); sack and crate kept |
| Lows | Quad Remesher, `ExactQuadCount=1`: pot 1,000, cauldron 1,470, sack 834, crate 790 triangles (4,093 for the set); LOD1 by Decimate 0.5 keeps both UV maps |
| Atlas | One 2048 map, all LOD0s at 640 px/m (`uv_audit.layout(..., together=True)`, the first density that fitted, from 1024 down); **31% of the map used** (second pass: 49%, below) |
| Bake | One bake of the joined LOD0s (pairs 1.2 m apart): 237 s. The fitted cage reported 2.1% own and 1.3% neighbour rays starting inside the highs, on thin parts (rims, legs, the handle), which baked as rainbow and back-facing (olive) texels in their small islands. Not visible at 1.5 m; the gate (zero) fails (second pass: the resolver, below) |
| Export | `batch_export_fbx.py --kit`: one FBX per piece collection with LOD0, LOD1 and `_COL`; the sanity test (re-import with `bake_space_transform`) gave rotation 0, scale 1 and the intended sizes |

Mistakes made on the way, now rules:

- **Keep the Triangulate on the lows through export.** The bake triangulated; the exported pieces did not, and
  `mesh_audit.py` flagged 255-602 non-planar quads per LOD0, which Unity would split its own way under the baked
  normals (`blender-mesh-topology`: triangulated as it exports).
- **Collision shells: `blender-to-unity`'s `collision_shell.py`.** `bmesh.ops.convex_hull` keeps the input faces
  beside the hull unless only its `geom` is kept; the first shells were 145-436 triangles and non-manifold, over
  Unity's 255-triangle limit for a convex MeshCollider. The second try hulled a 64-vertex Decimate of the LOD0 and
  the cauldron's shell floated 44 mm over the floor: decimation had dropped its leg tips. The script keeps the
  extremes: 124 triangles, closed, on the floor, the mesh at most 6-11 mm outside it, 96-99% of the full hull.
- **Thin gaps alone cannot tell a thin real wall from a double sheet.** The open cauldron read 0.65 thin gaps
  (cast-iron walls a few mm thick), as many as a udf double skin. What differs is whether the inner surface can be
  seen from outside: `sheets.hidden_fraction` read 0.09 on the cauldron against 0.52 and 0.78 on udf barrels (0.0
  on the solid one), so the intake now gives a `verdict` (SKILL.md step 5).

### Second pass: the four faults fixed (2026-11-02)

The same props, lows and colour, rebuilt with what the first pass lacked:

| Fault | Fix | Result |
| --- | --- | --- |
| Bake faults on thin parts (rays starting inside the high at rims, legs, the handle) | `pbr-texturing`'s bake now re-bakes those texels itself with back faces ignored (its resolver, on by default: Cycles has no such switch; the Toolbag and Substance bakers do) | Cauldron alone at 1024: inward-pointing normal texels 21,703 with Cycles alone, 189 with the resolver (99% fewer; 5 on the surface, 4 of them where the high really faces away from the low). The set's 2048 atlas: 48,538 before, 133 after, on 1.5 times as many texels (the denser pack). It costs time: 1,616 s of a 2,241 s bake |
| Atlas 31% used | `rizomuv-uv-pipeline`'s `pack_shared`: one RizomUV pack of the whole set, the density by bisection, every try graded for overlap | 792 px/m on 49% of the 2048 map (from 640 px/m on 31%), padding and margin kept |
| Silhouette gate failing at 5-11 mm | Measured instead as the rendered outline from the player (`blender-mesh-topology`'s `outline_error`, 1.5 m, 20 ppd) | The low's bulges were 0-4 px; the 3D number was counting faces across concave inner walls and the low over the pot's inner floor. The real fault was the other way: parts the low lost (cauldron leg tip and handle lugs, crate feet, sack ears: bands up to 18 px). A Quad Remesher density map painted on those parts (same budget) cut the worst band to 10-14 px; reaching 2 px needs about twice the triangles on these props |
| `sheets` read thin iron walls as double sheets | `hidden_fraction` and a verdict (above) | cauldron 0.09: `thin walls`; udf barrels 0.52 and 0.78: `double sheets or hidden walls` |

Tried and not kept: centring the low on the high (each vertex moved by the mean signed distance of its faces) cut
the pot's worst bulge from 8.4 to 5.9 mm, but did nothing for the sack and crate and drifted on the cauldron's
handle, where a thin part's nearest surface is often the wrong side.

Still open: the outline at 2 px needs more triangles than these budgets (a decision per prop, from its viewing
distance), and the resolver leaves texels where the high itself turns more than 90 degrees from the low (the sides of
the cauldron's legs): model such parts in the low or accept them.
