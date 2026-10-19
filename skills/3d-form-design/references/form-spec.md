# The form spec: every decision written and checked before building

Scope: the JSON design that SKILL.md section 1 asks for, what `scripts/form_spec.py` checks in it, and how the
build follows it. The point is to make every design decision where it is cheap to change (a line of JSON) and
checkable (a validator), so the build is execution and the first build is the right one. Research on agents
modelling in Blender found explicit per-part measurements nearly halved shape error, and that render-and-critique
loops fix less than they claim (`review-loop.md`): decide up front, verify once.

## Start from a template

`templates/` holds specs that pass the validator: `dining_table.json`, `dining_chair.json`, `sideboard.json`,
`bookcase.json`, `sofa.json`. Copy the nearest, change it to the reference (sizes, style, material, parts), and
validate. For another piece, write one in the same shape; `type` outside the built-in list gets a warning and no
range checks, so check its sizes against `furniture.md` or the reference by hand.

## Format

```json
{
 "piece": "Dining chair, beech, slatted back",
 "type": "dining_chair",
 "reference": "Mid-century beech dining chair: trapezoid seat, three slats, curved top rail",
 "view": {"usual_m": 1.5, "nearest_m": 0.7, "display": "vr20"},
 "tris_budget": 2000,
 "bevel_tiers_mm": {"primary": 5, "secondary": 3, "small": 2},
 "key_dims": {"seat_height": 450, "seat_depth": 420, "back_angle_deg": 100, "back_height": 420},
 "parts": [
  {"name": "front_leg", "role": "leg", "count": 2, "size": [38, 38, 428], "made": "wood", "build": "box",
   "attach_to": "floor",
   "shape": {"taper": {"faces": "inside two", "from_mm": 38, "to_mm": 28}, "splay_deg": 4},
   "notes": "free text the builder follows",
   "edges": [{"where": "four vertical corners", "tier": "secondary"},
             {"where": "foot edges on the floor", "tier": "sharp"}]}
 ]
}
```

| Field | Meaning |
| --- | --- |
| `type` | One of `dining_table`, `desk`, `coffee_table`, `dining_chair`, `stool`, `armchair`, `sofa`, `bed`, `bookcase`, `sideboard`, `kitchen_base`, `wardrobe`, `lamp`, or your own (no range checks) |
| `view.display` | `vr20` (Quest 2 and 3S), `vr25` (Quest 3) or `screen1080` (1080 px, 60 deg vertical): sets the 2 px floor with `usual_m` |
| `bevel_tiers_mm` | The three widths reused on every edge; an edge may override with `"mm"` |
| `key_dims` | The type's checked dimensions (table below), in mm or degrees |
| `parts[].size` | The part's own bounding box [x, y, z] in mm, in its own axes |
| `parts[].made` | `wood`, `board` (plywood, MDF, veneered panel), `machined_metal`, `sheet_metal`, `extruded_aluminium`, `cast_metal`, `moulded_plastic`, `glass`, `cut_sheet`, `stone`, `concrete`, `rubber`, `upholstery`, `fabric` |
| `parts[].build` | `box`, `extrude`, `revolve`, `sweep`, `loft`, `subd`, `cloth`, `sculpt`, `boolean`, `skin`, `array` (`blender-techniques.md`) |
| `parts[].attach_to` | Another part's name, `floor` or `wall`: what holds it |
| `parts[].shape` | `taper` (`faces`, `from_mm`, `to_mm`), `splay_deg`, `rake_deg`, `crown_pct`, `dish_mm`, `plan_radius_mm`, `box_ok` (why a plain block is right), anything else the build needs |
| `parts[].edges` | Every edge group with a tier (`primary`, `secondary`, `small`) or `sharp` |

## What the validator fails

`python scripts/form_spec.py spec.json`; exit 1 on any key without `warn_`. Fix the spec, never the check.

| Key | Fails when | Rule from |
| --- | --- | --- |
| `missing_field`, `units`, `view`, `part_size`, `part_made`, `part_build`, `part_names`, `edge_tier`, `taper` | The spec is incomplete or malformed | |
| `floating_part` | A part's `attach_to` is not another part, `floor` or `wall`, or nothing reaches the floor or a wall | Floating parts are the commonest failure in agent-built models |
| `primitive_box` | `build: box` for a part that is not a board or panel (thinnest side over a quarter of the middle one) and has no taper or `box_ok` | Scaled primitives |
| `flat_upholstery`, `upholstery_build` | Upholstery without `crown_pct`, or built other than cloth, subd or sculpt (swept piping excepted) | `furniture.md` section 3 |
| `edges_undecided` | A part without an edge list | Bevel per edge, never all |
| `contact_bevelled` | A bevelled edge whose `where` names the floor, bottom, contact, a joint, hidden, a wall, the underside | `bevels.md` section 4 |
| `soft_bevelled` | A bevel on upholstery | Seams and piping instead |
| `over_material` | A width over the material's believable maximum (wood 6, board 3, machined metal 3, cast 4, moulded plastic 5, extruded aluminium 2, sheet metal 6, glass and cut sheet 1, stone 10, concrete 25 mm) | `bevels.md` section 2 |
| `over_cap` | A width over a quarter of the part's thinnest side | `bevels.md` section 3 |
| `tier_order`, `one_bevel_width` | Tiers that do not shrink, or all equal | Tiers 1x, 0.5x, 0.25x |
| `key_dim_range` | A key dimension outside the type's range | `furniture.md` section 2 |
| `missing_anatomy` | No part with a role the type needs (a table without an apron, stretcher or rail; casework without a plinth or legs) | `furniture.md` sections 1 and 3 |

Warnings: `warn_no_reference`, `warn_under_floor` (a bevel under 2 px at the usual distance: widen it or make the
edge sharp), `warn_no_sharp_edge`, `warn_untapered_leg`, `warn_straight_chair_leg`, `warn_key_dim` (not given),
`warn_type`.

Key dimensions by type (mm unless degrees):

| Type | Ranges |
| --- | --- |
| `dining_table` | height 710-760, apron_clearance >= 610, overhang 25-350; roles top, leg / trestle / pedestal, apron / stretcher / rail |
| `desk` | height 710-760, knee_clearance >= 510 |
| `coffee_table` | height 380-460 |
| `dining_chair` | seat_height 405-460, seat_depth 380-450, back_angle_deg 95-105, back_height 300-510; roles seat, leg, back / back_rail / slat |
| `stool` | seat_height 405-800 |
| `armchair` | seat_height 380-460, back_angle_deg 95-120 |
| `sofa` | seat_height 355-480, seat_depth 455-610, back_angle_deg 95-115; roles seat_cushion, back_cushion / back, arm, frame / base |
| `bed` | mattress_top 405-610; roles mattress, frame / rail, headboard |
| `bookcase` | depth 250-400, shelf_span <= 900, plinth 50-150; roles side, shelf, back |
| `sideboard` | height 700-1050, front_gap 1.5-3.5, plinth_setback 20-100; roles top, side / carcass, door / drawer_front, plinth / leg |
| `kitchen_base` | worktop_height 890-915, front_gap 1.5-3.5, plinth_setback 50-100 |
| `wardrobe` | depth 500-650, front_gap 1.5-3.5 |
| `lamp` | roles base, shade |

The validator checks the spec's consistency with the rules, not that the sizes add up (seat height against leg
length, door widths against the carcass): add those up yourself and write the sums in `notes`.

## Building from the spec

- One Blender object per part, named exactly as the part (`front_leg`, `front_leg.001` for its copies), so
  `check_build(spec, measure_parts(spec))` can find them. Join them for export only after the check.
- Build each part completely once, in this order: its profile and build method, its shape (taper, splay, crown,
  dish) as part of the construction rather than a later fix, its edges by tier (bevel weights per tier from the
  edge list, `blender-techniques.md`), then place it against what it attaches to.
- Work through the parts from what touches the floor upwards, so each part is placed on something already there.
- After the last part: `check_build` (every part present, counted and within 3 mm or 2% of its size), `form_audit`
  on the joined piece, and the render set (SKILL.md section 5).
