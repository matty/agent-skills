---
name: 3d-form-design
description: Model props, furniture and hard-surface objects that do not look AI-made - blocky models of scaled cubes and cylinders, every edge chamfered, soap-bar or melted bevels, one bevel width everywhere, floating parts, wrong proportions, tables, chairs, sofas or shelves that look fake. Shape hierarchy, profile-first modelling, bevel sizes by material, furniture sizes and anatomy, a form audit. Wins for form and bevel sizing; topology and normals blender-mesh-topology, textures pbr-texturing.
---

# Form design: models that do not look blocky or over-bevelled

Two signatures give away a model an agent made: it is **scaled primitives touching each other** (a table is a box on
four boxes), and **one Bevel modifier on every edge** (every edge the same soft width, small parts melted, the
underside rounded). Both come from skipping design: no reference sizes, no profile, no idea how the thing is made.
This skill is that design step, done in order, then checked with numbers and renders. Engine- and tool-neutral; the
Blender API for each technique is in `references/blender-techniques.md`.

## The signatures and their fixes

| You see | Cause | Fix (section) |
| --- | --- | --- |
| Parts are boxes and cylinders butted together | Built from primitives, no profiles | Profiles first, then extrude, revolve, sweep or loft (2) |
| Everything is axis-aligned, parallel and the same thickness | No taper, draft, crown or splay | Refine the primaries (3) |
| Every edge rounded the same width; small parts look like soap | Bevel on all edges (Limit Method None), one width | Bevel tiers by material, by weight, capped (5) |
| The bottom edges and joints are rounded | Contact, joint and hidden edges bevelled | Those stay sharp (5) |
| Parts hover or miss each other | No contact check | Every part touches what holds it (4, 7) |
| Proportions look off; a chair feels child-sized | Guessed sizes | A dimensions table from real sizes (1, `references/furniture.md`) |
| Detail is spread evenly, all one size, evenly spaced | No hierarchy | Big, medium, small; 70/30 rest; grouped spacing (3, 4) |
| Doors, drawers and panels are one flush block | No gaps or reveals | 2-3 mm gaps and real recesses (4) |

## 1. Brief before geometry

Write this down before the first vertex, and put it in your report:
- **Reference**: images or a description of a real one. With text only, describe the real object you are modelling
  (era, style, material) and work towards that.
- **A parts table**: each part with its real size in mm, its material and how it is made (machined, cast, moulded,
  sheet, turned wood, sawn timber, upholstered), what holds it on, what touches the floor or a neighbour. Sizes come
  from the reference, the brief or `references/furniture.md`; never from a guess at "about right".
- **Viewing distance** (usual and nearest), screen or headset, and the triangle budget.

Agents given explicit per-part dimensions build far closer to the target than agents given only a picture
(`references/review-loop.md`).

## 2. Primary forms from profiles

- Draw each part's **profile** (side, front or top section) as a 2D point list, then build the solid from it:
  extrude a section, revolve a turned profile (legs, lamp bases, bottles, knobs), sweep a section along a path (rails,
  handles, cables, piping, mouldings), loft between sections. A scaled cube is right only for a part that really is a
  sawn board or panel, at its real thickness.
- Join parts the way they are joined: a leg meets the apron under the top, a tenon goes into a mortise, a panel sits
  in a groove. Overlap or interpenetrate slightly instead of touching face to face at one plane.
- Gate: black silhouettes from the front, side, top, two three-quarter views and one low view must each read as the
  object. A silhouette that is its bounding box from front and side is still a block.

## 3. Refine the primaries

- **Taper, draft, splay**: table legs taper on the inside faces only, starting just below the apron; chair legs rake
  and splay 5-15 deg; cast and moulded parts carry 1-3 deg of draft. Straight, parallel sides are a choice, not a
  default.
- **Crown big planes** that are not floors, glass or tiling surfaces: a sag of 0.5-2% of the span (*practice*) on a
  cushion, a car panel, a moulded shell. Upholstery is always crowned and seamed, never a bevelled box.
- **Hierarchy**: three size tiers (big, medium, small), each about 2x apart or more; about 70% of the surface quiet,
  30% carrying detail, clustered where the object is handled, joined or worn. Proportions about 1:1.6 or 1:2, not 1:1,
  unless the real thing is square.
- **Asymmetry with intent**: keep the symmetry the object really has, break it on at least one secondary feature;
  repeated instances vary by 0.5-2 deg and a few mm (*practice*), never on joint faces.

Rules, sources and the critique vocabulary reviewers use: `references/form-principles.md`.

## 4. Secondary forms where function puts them

Frames, rails, aprons, stretchers, panels in grooves, lips, flanges, plinth recesses, fasteners, hinges, handles.
Ask of every part: what holds it on, where it is touched, where it wears; put the detail there and nowhere else.
Doors, drawers and lids get **2-3 mm gaps** to their neighbours and a real recess where the reference has one;
plinths are set back about 75 mm. Whether a feature is geometry or a normal map depends on the viewing distance and
the silhouette: geometry when it is on the outline, deeper than the stereo threshold in VR (about 0.014 x d^2 m at 20
pixels per degree) or seen at grazing angles; otherwise the texture (`pbr-texturing`).

## 5. Edges: decide per edge, never all at once

1. **Sharp, always**: faces resting on the floor or a wall, faces meeting a neighbouring piece (two bevels make a
   groove at every joint), edges hidden inside another part, cut sheet, glass, blades, and any edge where the bevel
   would pass a quarter of the narrowest flat face beside it.
2. **Bevel the rest by what it is made of** (table below), in three tiers: silhouette and outer edges 1x, part and
   panel edges 0.5x, small detail 0.25x (*practice*). Real edges are 0.2-6 mm; a 2 cm bevel on a chair has no
   real-world counterpart.
3. **Visible floor**: a bevel narrower than about 2 px at the usual distance shimmers or vanishes. One pixel is
   about 1 mm per metre of distance on a 1080p, 60 deg screen and 0.9 mm per metre on a 20 ppd headset, so the floor
   is about 2 mm x d. If the floor is over the cap, leave the edge sharp and put the highlight in the texture or a
   trim bevel.
4. **Segments**: 1 for chamfers and most props; 2-3 only for big rounds seen up close; more only on real cylinders.

| Made as | Real edge | Bevel |
| --- | --- | --- |
| Cut sheet, glass, blade | Sharp, with a burr | None, or the smallest tier seen within 1 m |
| Machined metal | 0.2-0.5 mm break, 0.5-1 mm x 45 deg chamfers | 1-segment chamfer, 1-3 mm |
| Bent sheet metal | Inside radius >= sheet thickness t, outside = inside + t | Round, 2-3 segments, t to 2t outside |
| Extruded aluminium | 0.5-1 mm corners | 1-segment chamfer, 1-2 mm |
| Cast metal | Fillets >= 1.6 mm inside, 1-3 deg draft | Round, 2 segments, 2-4 mm |
| Moulded plastic | Outside radius about 1.5 x wall (3-5 mm on a 2-3 mm wall) | Round, 2-3 segments, 3-5 mm |
| Furniture wood | Eased edges 1-3 mm; tabletop roundovers 3-6 mm | Chamfer 2-3 mm; tops 2-3 segment round 3-6 mm |
| Concrete, stone | 20-25 mm chamfers on cast corners; 5 mm pencil round on stone | Chamfer at real size |

In Blender: Limit Method **Weight** (bevel weights on the chosen edges, one modifier per tier) or Angle, width in
metres (Offset or Width, never Percent), scale applied first. The modifier stack and normals (Harden Normals or
Weighted Normal, Triangulate) are `blender-mesh-topology`'s. Sizes, sources and the full edge checklist:
`references/bevels.md`.

## 6. Tertiary detail goes to textures

Grain, scratches, stitching, fabric weave, small dents: `pbr-texturing`. Do not model them, and do not add noise to
primary forms.

## 7. Audit and review, then iterate a few rounds

1. `form_audit` (below) on the finished piece: over-bevelled sections, bevelled contact faces, one width on parts of
   very different size, every edge bevelled, box-like parts, floating parts, size tiers, box silhouettes.
2. Renders from the views in section 2 at the usual distance, a lit three-quarter close-up, and a flat black
   silhouette set, beside the reference.
3. Critique against the parts table: missing parts first, then floating or disconnected, proportions, alignment,
   detail. Check each critique item on its own after the fix; agents report differences that are not there and
   miss small ones.
4. Revert any round that makes it worse. Stop after about three rounds and report what is left.

`references/review-loop.md` has the loop and the research behind it; `references/form-audit.md` the metrics.

## Scripts

| Script | What it gives |
| --- | --- |
| `scripts/form_audit.py` | Plain Python core: `audit(verts, faces)` (metres, Z up), `problems(report)`, `format_report(report)`, `bevel_sections`, `tiers`, `size_tiers`, `silhouette(verts, faces, view)`, `read_obj(path, y_up)`. In Blender: `audit_object(obj)` (modifiers and scale applied, plus Bevel modifier notes), `mesh_from_object(obj)`. CLI: `python form_audit.py piece.obj [--y-up] [--json]`, exit 1 on a failing problem |

Load it in Blender with `exec(open(path, encoding="utf-8").read(), ns)`. It reads and reports; `audit_object` only
switches Triangulate modifiers off for the reading and back on. Bevels are found on quads, so audit before
triangulating. Problem keys starting `warn_` are calls for the renders; the rest are fixed unless the reference
really looks like that, which you then say in the report.
