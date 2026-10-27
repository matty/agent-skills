---
name: 3d-form-design
description: Model props, furniture and hard-surface objects right first time, not AI-looking - blocky models of scaled cubes and cylinders, every edge chamfered, soap-bar or melted bevels, one bevel width everywhere, floating parts, wrong proportions, tables, chairs, sofas or shelves that look fake. A validated form spec and furniture templates, profile-first modelling, bevel sizes by material, a form audit. Wins for form and bevel sizing; topology and normals blender-mesh-topology, textures pbr-texturing.
---

# Form design: right the first time

Two signatures give away a model an agent made: it is **scaled primitives touching each other** (a table is a box on
four boxes), and **one Bevel modifier on every edge** (every edge the same soft width, small parts melted, the
underside rounded). Both come from designing while building, or not designing at all. So this skill moves every
decision before the first vertex: write a spec, validate it, build each part once from it, verify once. Fixing
afterwards is the expensive path and the unreliable one: agents' render critiques report differences that are not
there and miss small ones (`references/review-loop.md`).

Engine- and tool-neutral; the Blender API for each technique is in `references/blender-techniques.md`.

## The signatures, and the spec field that prevents each

| You would see | Prevented by |
| --- | --- |
| Parts are boxes and cylinders butted together | `build` per part: a profile (extrude, revolve, sweep, loft); `box` only for boards and panels (`primitive_box`) |
| Everything axis-aligned, parallel, the same thickness | `shape`: taper, splay, rake, crown, dish, at real values |
| Every edge rounded the same width; small parts like soap | `bevel_tiers_mm` and an edge list per part, capped by material and part thickness |
| Bottom edges and joints rounded | Contact, joint, hidden and wall edges `sharp` (`contact_bevelled`) |
| Parts hover or miss each other | `attach_to` on every part, down to the floor or a wall (`floating_part`) |
| Proportions off; the chair feels child-sized | `size` from real dimensions and `key_dims` checked against ranges |
| A table without aprons, a cabinet without a plinth | Roles the type needs (`missing_anatomy`) |
| Doors and drawers one flush block | Fronts as parts with `front_gap` 1.5-3.5 mm |

## 1. Write the spec

Copy the nearest template from `templates/` (dining table, dining chair, sideboard, bookcase, sofa) or write one in
the same shape. Fill in, from the reference and `references/furniture.md`, never from a guess at "about right":
- `reference`: the real object (era, style, material, maker) or the image you are matching. With text only, name a
  real one.
- `view`: usual and nearest viewing distance and the display; `tris_budget`.
- `key_dims` for the type, and the sums that must agree (leg length + top = table height; doors + gaps = carcass
  width), written in the parts' `notes`.
- Every part: `size` in mm, `made`, `build`, `attach_to`, `shape`, and an `edges` list where each edge group is a tier
  or `sharp`. Design rules for these choices are in sections 2-4.

Format and every field: `references/form-spec.md`.

## 2. Validate it, fix it, validate again

`python scripts/form_spec.py spec.json` must exit 0. Change the spec, never the check; for a warning, either change
the spec or write in the part's `notes` why the reference really is that way. Then check by eye what the validator
cannot: that the parts add up (section 1) and that the side, front and top profiles you will build match the
reference. Only then open the modelling tool.

## 3. Design rules the spec encodes

**Form** (`references/form-principles.md`):
- Build from profiles. Revolve turned parts (legs, lamp bases, knobs), sweep sections along paths (rails, bent back
  legs, handles, piping, mouldings), extrude sections at real thickness (boards, tops, aprons).
- Taper, draft, splay: table legs on the inside faces only, from just below the apron; chair legs rake and splay
  5-15 deg; cast and moulded parts 1-3 deg of draft.
- Crown big soft or moulded surfaces (0.5-2% of the span, *practice*; cushions more); upholstery is cloth, subd or
  sculpt, with seams and piping, never a bevelled box.
- Hierarchy: big, medium, small forms; about 70% of the surface quiet, detail clustered where the object is joined,
  handled or worn. Parts overlap or seat into each other (a leg under an apron, a panel in a groove), not touch
  face to face.

**Edges** (`references/bevels.md`):
1. Sharp, always: on the floor or a wall, meeting another part, hidden, cut sheet, glass, and any edge whose bevel
   would pass a quarter of the part's thinnest side. A pickup has no floor side: its base is seen in the hand.
2. The rest by material, in three tiers (silhouette 1x, part edges 0.5x, small 0.25x, *practice*). Real edges are
   0.2-6 mm; a 2 cm bevel on a chair has no counterpart.
3. At least 2 px at the usual distance: about 2 mm per metre (0.87 mm per px per metre on a 20 ppd headset, 1.07 at
   1080p and 60 deg). Under it, make the edge sharp and leave the highlight to the texture.
4. Segments: 1 for chamfers and most props; 2-3 for rounds seen up close.

| Made as | Real edge | Bevel |
| --- | --- | --- |
| Cut sheet, glass, blade | Sharp | None, or 1 mm seen within 1 m |
| Machined metal | 0.2-0.5 mm break, 0.5-1 mm x 45 deg chamfers | 1-segment chamfer, 1-3 mm |
| Bent sheet metal | Inside radius >= thickness t, outside = inside + t | Round, 2-3 segments, t to 2t |
| Extruded aluminium | 0.5-1 mm | Chamfer 1-2 mm |
| Cast metal | Fillets >= 1.6 mm, 1-3 deg draft | Round, 2 segments, 2-4 mm |
| Moulded plastic | Outside about 1.5 x wall | Round, 2-3 segments, 3-5 mm |
| Furniture wood | Eased 1-3 mm; tabletop roundovers 3-6 mm | Chamfer 2-3 mm; tops round 3-6 mm |
| Board (MDF, ply, veneer) | Eased about 1-2 mm | Chamfer up to 3 mm, or sharp |
| Concrete, stone | 20-25 mm chamfers; 5 mm pencil round | At real size |

**Geometry or texture**: geometry when it is on the silhouette, seen at grazing angles, or deeper than the stereo
threshold in VR (about 0.014 x d^2 m at 20 ppd); otherwise the texture (`pbr-texturing`). Grain, scratches,
stitching and weave are always texture.

## 4. Build each part once, from the spec

- One object per part, named as in the spec (`front_leg`, `front_leg.001`), so the build can be measured.
- Per part, in order: the profile and build method, the shape as part of the construction (taper the inside faces
  while building the leg, not later), bevel weights per tier from its edge list (Limit Method Weight, width in
  metres, scale applied), then place it against what it attaches to.
- Go from the floor up, so each part lands on something already built.
- Look up any API call you have not used in this Blender version (`references/blender-techniques.md` lists the 4.x-5.x
  traps) instead of falling back to a primitive. Never "fix" a failing call by deleting the step.
- The modifier stack and normals that make the bevels shade cleanly (Harden Normals or Weighted Normal, Triangulate)
  are `blender-mesh-topology`'s. A prop that takes a bake (carving, rivets, upholstery folds, a hero piece seen within
  1 m) is built twice, a high and a low: `blender-mesh-topology`'s high-and-low-poly reference, before any bake. A
  part that moves (a lid, a door, a drawer) keeps the faces it reveals: an openable inside counts as seen; a lid that
  only looks hinged and never opens is one closed body with the hinge and a cut parting line, no inside.

## 5. Verify once

1. `check_build(spec, measure_parts(spec))`: every part present, counted, within 3 mm or 2% of its size.
2. `form_audit` on the joined piece: no `over_bevelled`, `contact_bevelled`, `one_bevel_width`, `floating_parts`, and
   `blocky` only where the spec says boards.
3. One render set beside the reference: black silhouettes front, side, top, two three-quarter and one low view; a lit
   three-quarter at the usual distance. Answer written yes/no questions from the spec ("do the back legs rake about 8
   deg?", "are there 3 mm gaps between the doors?").
4. A failure points at a spec line or a build step. Correct that line, rebuild that part only, and re-run the check
   that failed. If the spec itself was wrong, fix it and re-validate. Report every check with its measured value.

## Scripts and templates

| File | What it gives |
| --- | --- |
| `scripts/form_spec.py` | Plain Python: `load`, `validate(spec)`, `check_build(spec, measured_mm)`, `floor_mm(spec)`; in Blender `measure_parts(spec)`. CLI `python form_spec.py spec.json`, exit 1 on a failing problem |
| `scripts/form_audit.py` | Plain Python: `audit(verts, faces)` (metres, Z up), `problems`, `format_report`, `bevel_sections`, `silhouette`, `read_obj`; in Blender `audit_object(obj)` with Bevel modifier notes. CLI `python form_audit.py piece.obj [--y-up] [--json]` |
| `templates/*.json` | Validated specs: `dining_table`, `dining_chair`, `sideboard`, `bookcase`, `sofa` |

Load a script in Blender with `exec(open(path, encoding="utf-8").read(), ns)`. Both read and report;
`audit_object` only switches Triangulate modifiers off for its reading and back on (bevels are found on quads). The
Blender functions have not been run in this repo's tests; the plain-Python cores are tested. Audit details and blind
spots: `references/form-audit.md`.
