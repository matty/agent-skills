# Bevels and chamfers: which edges, how wide, how many segments

Scope: sizing and choosing edges (SKILL.md section 3, the spec's edge lists). The Blender modifier stack and custom normals that make a
bevel shade cleanly are `blender-mesh-topology`'s; this file decides what to bevel and how much. Sources checked
2026-10-19. No authoritative source gives a numeric game bevel width: the caps, tiers and pixel floor below are
*practice* (this skill's rules) built on the sourced principles, and are settled by the renders.

## 1. What the sources agree on

| Principle | Source |
| --- | --- |
| Too thin, the bevel "shimmers or disappears"; too wide, "the object looks rounded". Width comes from the intended highlight size | https://www.seeles.ai/features/tools/dcc-weighted-normals-hard-surface-bevel-guide |
| "Too much bevel softens the silhouette and ruins the hard surface look. Too little bevel causes unrealistic, razor-sharp edges" | https://hyper-casual.games/blog/blender-hard-surface-modeling |
| Work at real-world scale and compare bevel values with real measurements; apply scale first, since non-uniform scale stretches bevels | https://3dskillup.art/mastering-bevels-in-blender/ |
| A "uniform bevel radius across a model will make it look unconvincing"; separate widths by material, plastics softer than metals | https://marmoset.co/posts/toolbags-bevel-shader-in-action-3-artists-weigh-in/ |
| A common mistake is "beveling everything equally"; bevel exposed edges and those that would wear; keep one width per group of similar edges | https://novedge.com/blogs/design-news/cinema-4d-tip-beveling-best-practices-for-realistic-hard-surface-modeling |
| Pick small, medium and large bevel sizes and reuse the exact values | Polycount, https://polycount.com/discussion/comment/2716374 (search summary) |
| Woodwork: "Do too little, and your furniture won't look or feel finished. Overdo it, and your heavily rounded edges will look like unskilled factory work" | https://www.finewoodworking.com/2011/07/28/how-to-break-an-edge |
| Face-weighted normals blend the shading across "the smaller bevel faces": the bevel must stay small beside its flats; bevels also make "long thin triangles" | http://wiki.polycount.com/wiki/Face_weighted_normals |
| Bevel the focal and most noticeable parts, not everything; drop fine bevels at lower LODs | Polycount threads 160751 and 225647 (search summaries); https://blenderartists.org/t/how-to-bake-bevels-for-game-asset-models/1278148 |

## 2. Real edges by how the part is made

| Process | Numbers | Source |
| --- | --- | --- |
| Sheet metal bends | Inside radius >= 1 x thickness for 1-6 mm sheet, 1.5t for 6-12 mm, 2-3t for 12-25 mm; outside radius = inside + t | https://xometry.pro/en-eu/articles/sheet-metal-bend-radius-table/ ; Protolabs standard tooling 0.76 mm inside, "keep all the bend radii the same": https://www.protolabs.com/resources/design-tips/8-ways-to-improve-sheet-metal-parts/ |
| Sheared or laser-cut sheet | No designed radius: rollover, burnish, fracture, burr | https://www.thefabricator.com/thefabricator/article/bending/improving-blank-edge-conditions |
| Machined parts | "Break sharp edges" 0.2-0.5 mm; dimensioned chamfers 0.5 x 45 or 1.0 x 45 deg; inside corners keep the cutter radius (R3 from a 6 mm end mill) | https://www.gdandtbasics.com/break-edges-note/ , https://werk24.io/knowledge-base/edges , https://www.clarwe.com/articles/designing-cnc-milled-parts-fillets-wall-thickness-and-tool-access-explained |
| Injection-moulded plastic | Inside radius >= 0.5 x wall; outside about 1.5 x wall | https://www.protolabs.com/resources/design-tips/cutting-corners-on-injection-molded-parts/ |
| Die casting | Inside fillets >= 1.6 mm common; 0.4 mm fillets "barely noticeable even on outside edges", 0.8 mm "seldom evident except on close inspection"; draft 1-3 deg | https://diecasting.zinc.org/?p=263 ; draft: https://www.wevolver.com/article/die-casting-design-tips |
| Extruded aluminium | Corners 0.5-1 mm, outside no less than about 0.2 mm | https://www.shapesbyhydro.com/en/industries/extrusion-quick-guide-for-designing-with-aluminium/ |
| Furniture wood | A break chamfer "doesn't need to be more than about 1/32 in." (0.8 mm); heavier roundovers on tabletops; UK joiners use 1.5-3 mm arris radii; table edges commonly 1/4 in (6.4 mm) roundover | https://www.finewoodworking.com/2011/07/28/how-to-break-an-edge , https://ukworkshop.co.uk/threads/what-radius-arris.138778/post-1604284 |
| Concrete | Chamfer strips 10-30 mm, 20-25 mm common; about 19 mm on exposed corners in one municipal spec | https://colliervilletn.gov/home/showpublisheddocument/926/637505315301900000 |
| Stone | 5 mm pencil round on a nosing (one heritage drawing) | https://camdocs.camden.gov.uk/CMWebDrawer/Record/5769813/file/document |

Nearly every real edge is 0.2-6 mm. Game bevels are exaggerated upward to stay visible (section 3), but a bevel of
several centimetres on a crate or a chair has no counterpart: that is the over-bevel signature.

## 3. The width of one bevel (*practice*)

Take the smallest of these, after deciding the edge is bevelled at all (section 4):

1. **The material's believable maximum** (section 2; `form_spec.py` holds the numbers it checks).
2. **The tier**: silhouette and outer shell edges 1x, part and panel edges 0.5x, small detail and trim 0.25x. Name the
   three widths as constants and reuse them across a set of pieces.
3. **The cap**: a quarter of the narrowest flat face beside the edge (a face bevelled on both sides keeps half its
   width flat). Past the cap the face reads melted. `form_audit` fails a bevel over half of the flat left beside it
   and warns past a quarter.

Then check the **floor**: at least 2 px at the usual viewing distance d. One pixel spans about d x 2 tan(fov/2) /
screen height: 1.07 mm per metre at 1080 px and 60 deg vertical field of view, 0.87 mm per metre (d / 1150) on a 20
pixel-per-degree headset. So the floor is about 2 mm x d. A floor over the cap means the edge stays sharp and its
highlight goes to the texture or a trim sheet's bevel strip.

Worked: an oak chair seat 20 mm thick seen from 1.5 m. Floor 3 mm; cap a quarter of 20 = 5 mm; wood tops 3-6 mm. A
3-4 mm round on the top edge, 2 mm on the legs (tier 0.5x), nothing on the leg feet or where the legs meet the seat.

## 4. Which edges

| Edge | Do | Why |
| --- | --- | --- |
| Rests on the floor, a wall or a neighbouring piece | Sharp | Unseen, and a bevel opens a dark gap or a groove at every joint |
| Buried in another part (a tenon, a leg under a top) | Sharp | Unseen, wasted faces |
| Cut sheet, glass, blade, thin plate | Sharp or the smallest tier | Real ones are sharp |
| Would pass the cap | Sharp | Melts the face |
| Exterior corner that catches light (table top, frame, case) | Tier width, chamfer for cut, machined or wooden parts, round for cast, moulded or bent | The highlight line sells the edge |
| Interior corner | Fillet only on cast or moulded parts (they have one); otherwise sharp | A concave game bevel adds faces and little highlight |
| Hard 90 deg edges kept sharp on big panels | Sharp edge, split normals | Keeps the panel flat |

Leave some hard edges: a model with no sharp edge anywhere usually has its contact and joint edges bevelled
(`form_audit` warns).

## 5. Segments and profile

- 1 segment: chamfers, and most props with weighted or hardened normals.
- 2-3 segments: rounds wider than about 20-30 px at the nearest view (tabletops, moulded shells, bent sheet).
- More: only on cylinders and handles, where the chord rule decides (`blender-mesh-topology`).
- Profile 0.5 is circular; a Bevel's Shape has no effect under 2 segments.
- Drop bevel segments at lower LODs.

## 6. In Blender

Sources: the Blender manual's Bevel modifier page
(https://docs.blender.org/manual/en/latest/modeling/modifiers/generate/bevel.html) and the API
(https://docs.blender.org/api/current/bpy.types.BevelModifier.html), Blender 5.2 docs.

- Apply scale first; widths are in object space.
- `limit_method`: `WEIGHT` with the `bevel_weight_edge` attribute on chosen edges (one Bevel modifier per tier, each
  reading its own edges) or `ANGLE` (default 30 deg). Never `NONE`, which bevels every edge, contact and joint edges
  included.
- `offset_type`: `OFFSET` or `WIDTH`, in metres. `PERCENT` follows each edge's length, so widths vary by accident.
- `use_clamp_overlap` (on by default) only stops bevels crossing each other, which allows up to half a face: it is not
  the cap. Turning `loop_slide` off "can lead to more even bevel widths" (manual).
- `bmesh.ops.bevel` differs from the modifier: `affect` defaults to `VERTICES` and `segments` to 0; pass
  `affect="EDGES"`, `segments=1` and an `offset_type`.
- `bevel_modifier_notes()` in `scripts/form_audit.py` reports Limit Method None, Percent widths, vertex bevels,
  many segments on tiny bevels and non-uniform scale.
