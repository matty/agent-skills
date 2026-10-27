"""Validate a form spec (a JSON design for one piece) before any geometry is built, and check the built piece against it.

Host: plain Python 3.9+, standard library. measure_parts() at the bottom needs Blender (bpy, written for 4.2+; not
run in this repo's tests).

    python form_spec.py chair.json                    # problems in the spec, exit 1 on any that is not a warn_
    python form_spec.py templates/dining_chair.json   # the templates pass

    import form_spec as fs
    spec = fs.load("chair.json"); fs.validate(spec)                  # [(key, evidence)]
    fs.check_build(spec, {"seat": (460, 420, 20), ...})             # built sizes in mm against the spec
    ns["check_build"](spec, ns["measure_parts"](spec))               # in Blender, objects named after the parts

The spec format and every rule are in references/form-spec.md. In short: a piece has a type, a viewing distance,
bevel tiers in mm and a list of parts; each part has a name, role, size [x, y, z] in mm, made (material/process),
build (method), attach_to (another part, "floor", "wall", "ceiling" or "free"), optional shape (taper, splay, rake, crown) and an edge
list in which every edge is a tier or "sharp".
"""

import json
import math
import re
import sys

MATERIAL_MAX_MM = {          # the largest believable game bevel per material (references/bevels.md section 2)
    "cut_sheet": 1.0, "glass": 1.0, "machined_metal": 3.0, "extruded_aluminium": 2.0, "sheet_metal": 6.0,
    "cast_metal": 4.0, "moulded_plastic": 5.0, "wood": 6.0, "board": 3.0, "stone": 10.0, "concrete": 25.0,
    "upholstery": 0.0, "fabric": 0.0, "rubber": 4.0,
}
BUILDS = {"box", "extrude", "revolve", "sweep", "loft", "subd", "cloth", "sculpt", "boolean", "skin", "array"}
SOFT = {"upholstery", "fabric"}
HOLDERS = ("floor", "wall", "ceiling", "free")   # free: a pickup, carried or set down anywhere (its base is seen)
TIER_NAMES = ("primary", "secondary", "small")
DISPLAY_MM_PER_PX_PER_M = {"vr20": 1000.0 / 1150.0, "vr25": 1000.0 / 1437.5,
                           "screen1080": 2 * math.tan(math.radians(30)) / 1080 * 1000.0}
FLOOR_PX = 2.0
CAP = 0.25                  # a bevel at most a quarter of the part's thinnest side (the narrowest face's proxy)
BOARD = 0.25                # a box is fine when its thinnest side is at most a quarter of its middle side
NO_BEVEL_WORDS = ("floor", "bottom", "contact", "joint", "hidden", "wall", "underside", "inside joint", "buried")
BUILD_TOL_MM = 3.0
BUILD_TOL = 0.02

# Ranges by piece type (mm), references/furniture.md; key_dims outside them fail, missing ones warn.
TYPE_RULES = {
    "dining_table": dict(dims={"height": (710, 760), "apron_clearance": (610, None), "overhang": (25, 350)},
                         roles=[("top",), ("leg", "trestle", "pedestal"), ("apron", "stretcher", "rail")]),
    "desk": dict(dims={"height": (710, 760), "knee_clearance": (510, None)},
                 roles=[("top",), ("leg", "panel", "pedestal")]),
    "coffee_table": dict(dims={"height": (380, 460)}, roles=[("top",), ("leg", "panel", "pedestal")]),
    "dining_chair": dict(dims={"seat_height": (405, 460), "seat_depth": (380, 450), "back_angle_deg": (95, 105),
                               "back_height": (300, 510)},
                         roles=[("seat",), ("leg",), ("back", "back_rail", "slat")]),
    "stool": dict(dims={"seat_height": (405, 800)}, roles=[("seat",), ("leg",)]),
    "armchair": dict(dims={"seat_height": (380, 460), "back_angle_deg": (95, 120)},
                     roles=[("seat_cushion", "seat"), ("back_cushion", "back"), ("arm",), ("frame", "base", "leg")]),
    "sofa": dict(dims={"seat_height": (355, 480), "seat_depth": (455, 610), "back_angle_deg": (95, 115)},
                 roles=[("seat_cushion",), ("back_cushion", "back"), ("arm",), ("frame", "base")]),
    "bed": dict(dims={"mattress_top": (405, 610)}, roles=[("mattress",), ("frame", "rail"), ("headboard",)]),
    "bookcase": dict(dims={"depth": (250, 400), "shelf_span": (None, 900), "plinth": (50, 150)},
                     roles=[("side",), ("shelf",), ("back",)]),
    "sideboard": dict(dims={"height": (700, 1050), "front_gap": (1.5, 3.5), "plinth_setback": (20, 100)},
                      roles=[("top",), ("side", "carcass"), ("door", "drawer_front"), ("plinth", "leg")]),
    "kitchen_base": dict(dims={"worktop_height": (890, 915), "front_gap": (1.5, 3.5), "plinth_setback": (50, 100)},
                         roles=[("worktop",), ("carcass", "side"), ("door", "drawer_front"), ("plinth",)]),
    "wardrobe": dict(dims={"depth": (500, 650), "front_gap": (1.5, 3.5)},
                     roles=[("side", "carcass"), ("door",), ("plinth", "leg")]),
    "lamp": dict(dims={}, roles=[("base",), ("shade",)]),
}


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def floor_mm(spec):
    v = spec.get("view", {})
    per = DISPLAY_MM_PER_PX_PER_M.get(v.get("display", "vr20"))
    return FLOOR_PX * per * float(v.get("usual_m", 0)) if per else None


def validate(spec):
    """[(key, evidence)] for a spec. Keys starting warn_ are judgement calls; fix the rest before building."""
    out = []

    def bad(k, msg):
        out.append((k, msg))

    for k in ("piece", "type", "view", "parts", "bevel_tiers_mm"):
        if k not in spec:
            bad("missing_field", "spec has no %r" % k)
    if out:
        return out
    if spec.get("units", "mm") != "mm":
        bad("units", "sizes are in mm")
    view = spec["view"]
    if view.get("display", "vr20") not in DISPLAY_MM_PER_PX_PER_M:
        bad("view", "display %r is not one of %s" % (view.get("display"), sorted(DISPLAY_MM_PER_PX_PER_M)))
    if not view.get("usual_m"):
        bad("view", "no usual viewing distance (view.usual_m)")
    if not spec.get("reference"):
        bad("warn_no_reference", "no reference: name the real object (era, style, maker) or the image you work from")

    tiers = spec["bevel_tiers_mm"]
    fl = floor_mm(spec) or 0.0
    vals = [tiers.get(t) for t in TIER_NAMES if tiers.get(t) is not None]
    if vals != sorted(vals, reverse=True):
        bad("tier_order", "bevel tiers must shrink: primary >= secondary >= small (%s)" % tiers)
    if len(set(vals)) == 1 and len(vals) > 1:
        bad("one_bevel_width", "every tier is %.1f mm: one width everywhere" % vals[0])

    parts = spec["parts"]
    names = {p.get("name") for p in parts}
    if len(names) != len(parts):
        bad("part_names", "part names must be unique")
    grounded = False
    roles = set()
    for p in parts:
        n = p.get("name", "?")
        roles.add(p.get("role"))
        size = p.get("size")
        if not (isinstance(size, list) and len(size) == 3 and all(isinstance(s, (int, float)) and s > 0
                                                                   for s in size)):
            bad("part_size", "%s: size must be [x, y, z] in mm, all positive" % n)
            continue
        made, build = p.get("made"), p.get("build")
        if made not in MATERIAL_MAX_MM:
            bad("part_made", "%s: made %r is not one of %s" % (n, made, sorted(MATERIAL_MAX_MM)))
            continue
        if build not in BUILDS:
            bad("part_build", "%s: build %r is not one of %s" % (n, build, sorted(BUILDS)))
        att = p.get("attach_to")
        if att in HOLDERS:
            grounded = True
        elif att not in names or att == n:
            bad("floating_part", "%s: attach_to %r is not another part or one of %s" % (n, att, ", ".join(HOLDERS)))
        sd = sorted(size)
        shape = p.get("shape", {})
        if build == "box" and sd[0] > BOARD * sd[1] and not (shape.get("taper") or shape.get("box_ok")):
            bad("primitive_box", "%s: a %s box %s with no taper: give it a profile (extrude, revolve, sweep), a "
                "taper, or shape.box_ok with the reason the real one is a plain block" % (n, made, size))
        if made in SOFT and build != "sweep":     # piping is a swept tube
            if not shape.get("crown_pct"):
                bad("flat_upholstery", "%s: upholstery needs shape.crown_pct (a crowned, filled surface)" % n)
            if build not in ("cloth", "subd", "sculpt"):
                bad("upholstery_build", "%s: upholstery is built with cloth, subd or sculpt, not %s" % (n, build))
        if p.get("role") == "leg" and spec["type"] in ("dining_table", "desk", "coffee_table") and \
                build in ("box", "extrude") and not shape.get("taper") and not shape.get("box_ok"):
            bad("warn_untapered_leg", "%s: table legs usually taper on the inside faces; set shape.taper or box_ok" % n)
        if p.get("role") == "leg" and spec["type"] in ("dining_chair", "stool") and \
                not (shape.get("rake_deg") or shape.get("splay_deg") or shape.get("box_ok")):
            bad("warn_straight_chair_leg", "%s: chair and stool legs rake or splay 5-15 deg" % n)
        taper = shape.get("taper")
        if taper and not (0 < taper.get("to_mm", 0) < taper.get("from_mm", 0)):
            bad("taper", "%s: taper needs from_mm > to_mm > 0" % n)

        edges = p.get("edges")
        if not edges:
            bad("edges_undecided", "%s: no edge list; decide every edge (a tier or sharp)" % n)
            continue
        for e in edges:
            where, tier = str(e.get("where", "")).lower(), e.get("tier")
            if tier != "sharp" and tier not in TIER_NAMES:
                bad("edge_tier", "%s / %s: tier %r is not sharp or %s" % (n, where, tier, "/".join(TIER_NAMES)))
                continue
            if tier == "sharp":
                continue
            if any(w in where for w in NO_BEVEL_WORDS):
                bad("contact_bevelled", "%s / %s: contact, joint, hidden and wall edges stay sharp" % (n, where))
            w = tiers.get(tier)
            if w is None:
                bad("edge_tier", "%s / %s: tier %s has no width in bevel_tiers_mm" % (n, where, tier))
                continue
            w = float(e.get("mm", w))
            if made in SOFT:
                bad("soft_bevelled", "%s / %s: upholstery has seams and piping, not bevels" % (n, where))
            elif w > MATERIAL_MAX_MM[made]:
                bad("over_material", "%s / %s: %.1f mm is over the %.1f mm a %s edge reaches" %
                    (n, where, w, MATERIAL_MAX_MM[made], made))
            if w > CAP * sd[0]:
                bad("over_cap", "%s / %s: %.1f mm is over a quarter of the part's %.1f mm thinnest side" %
                    (n, where, w, sd[0]))
            if fl and w < fl:
                bad("warn_under_floor", "%s / %s: %.1f mm is under 2 px (%.1f mm) at %.1f m: widen it, or make it "
                    "sharp and leave the highlight to the texture" % (n, where, w, fl, view.get("usual_m", 0)))
        if att != "free" and all(e.get("tier") != "sharp" for e in edges):
            bad("warn_no_sharp_edge", "%s: every edge bevelled; which rest on something or meet a neighbour?" % n)
    if not grounded:
        bad("floating_part", "no part attaches to the floor, a wall or the ceiling, or is free (a pickup)")

    rules = TYPE_RULES.get(spec["type"])
    if rules is None:
        bad("warn_type", "type %r has no built-in ranges (%s); check its sizes by hand" %
            (spec["type"], ", ".join(sorted(TYPE_RULES))))
    else:
        kd = spec.get("key_dims", {})
        for k, (lo, hi) in rules["dims"].items():
            if k not in kd:
                bad("warn_key_dim", "key_dims.%s not given (expected %s-%s)" % (k, lo, hi))
                continue
            v = kd[k]
            if (lo is not None and v < lo) or (hi is not None and v > hi):
                bad("key_dim_range", "%s %s is outside %s-%s for a %s" % (k, v, lo, hi, spec["type"]))
        for alts in rules["roles"]:
            if not roles.intersection(alts):
                bad("missing_anatomy", "a %s needs a part with role %s" % (spec["type"], " or ".join(alts)))
    return out


def is_part(obj_name, part):
    """True when an object is the part or a copy of it: part, part.001, part_1, part_low, part_low.001. Never another
    part that starts with the same word (handle_bracket is not a handle) or a bake high (part_high...)."""
    return re.fullmatch(re.escape(part) + r"(?:_low)?(?:[._]\d+)?", obj_name) is not None


def check_build(spec, measured, tol_mm=BUILD_TOL_MM, tol=BUILD_TOL):
    """[(key, evidence)] comparing built part sizes (name -> (x, y, z) mm, in the part's own axes) with the spec.
    A part with count N is matched as name, name.001 ... or name_1 ... (any of them may be given; is_part). Sizes are compared
    sorted, so a part modelled lying another way round still matches; its orientation is the renders' job."""
    out = []
    for p in spec["parts"]:
        n = p["name"]
        hits = {k: v for k, v in measured.items() if is_part(k, n)}
        want = int(p.get("count", 1))
        if not hits:
            out.append(("part_missing", "%s: not built" % n))
            continue
        if len(hits) < want:
            out.append(("part_count", "%s: %d built, spec says %d" % (n, len(hits), want)))
        exp = sorted(p["size"])
        for k, dims in hits.items():
            got = sorted(dims)
            off = [abs(g - e) for g, e in zip(got, exp)]
            if any(o > max(tol_mm, tol * e) for o, e in zip(off, exp)):
                out.append(("part_size", "%s: built %s mm, spec %s mm" %
                            (k, [round(g, 1) for g in got], [round(e, 1) for e in exp])))
    return out


def measure_parts(spec):
    """Sizes in mm of the Blender objects named after the spec's parts (name, name.001, name_1 ...), each in its own
    axes with its modifiers and scale applied. Needs bpy."""
    import bpy
    deps = bpy.context.evaluated_depsgraph_get()
    out = {}
    names = [p["name"] for p in spec["parts"]]
    for ob in bpy.data.objects:
        if ob.type != "MESH" or not any(is_part(ob.name, n) for n in names):
            continue
        ev = ob.evaluated_get(deps)
        me = ev.to_mesh()
        try:
            s = ob.matrix_world.to_scale()
            if not me.vertices:
                continue
            lo = [min(v.co[k] for v in me.vertices) for k in range(3)]
            hi = [max(v.co[k] for v in me.vertices) for k in range(3)]
            out[ob.name] = tuple((hi[k] - lo[k]) * s[k] * 1000.0 for k in range(3))
        finally:
            ev.to_mesh_clear()
    return out


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python form_spec.py spec.json")
        return 2
    spec = load(args[0])
    probs = validate(spec)
    print("%s (%s): %d part(s), floor %.1f mm at %s m" % (spec.get("piece"), spec.get("type"),
                                                         len(spec.get("parts", [])), floor_mm(spec) or 0,
                                                         spec.get("view", {}).get("usual_m")))
    for k, ev in probs:
        print("%s: %s" % (k, ev))
    if not probs:
        print("spec ok")
    return 1 if any(not k.startswith("warn_") for k, _ in probs) else 0


if __name__ == "__main__":
    sys.exit(main())
