"""Hard-surface stack helpers (references/hard-surface.md): a Smooth by Angle placed in the stack without touching other
objects, and the hand-off of a finished stack to UV work.

Host: Blender (bpy; tested on 5.2.2), live or headless.
Load in Blender:  ns = {}; exec(open(r"<skill>/scripts/hard_surface.py", encoding="utf-8").read(), ns)

    sba = ns["smooth_by_angle_first"](ob, 10)      # below any leading Mirror or Array, above everything else
    ns["apply_for_uv_work"](ob)                    # before seams: apply the stack from the top (see below)
    ns["apply_before_layout"](ob)                  # just before the UV layout: apply the Mirrors left live

apply_for_uv_work and apply_before_layout behave exactly like uv-unwrapping's apply_stack (first call, then
keep_mirror=False): the same topology-changing modifiers, the same refusals, the same Mirror handling. A repo test
(tools/tests/blender/test_cross_hardsurface_handoff.py) runs both on the same stacks.
"""

import math

import bpy

# Modifiers that change the topology; Geometry Nodes modifiers other than Smooth by Angle count too (a node tree can
# rebuild the mesh). Kept identical to uv-unwrapping's TOPOLOGY_TYPES.
TOPOLOGY_TYPES = frozenset({"ARRAY", "BEVEL", "BOOLEAN", "BUILD", "DECIMATE", "EDGE_SPLIT", "MASK", "MIRROR",
                            "MULTIRES", "REMESH", "SCREW", "SKIN", "SOLIDIFY", "SUBSURF", "WELD", "WIREFRAME"})
LEADING = ("MIRROR", "ARRAY")      # they go first in the stack, above the Bevel


def _smooth_by_angle(m):
    return m.type == "NODES" and m.node_group is not None and "Smooth by Angle" in m.node_group.name


def _changes_topology(m):
    return m.type in TOPOLOGY_TYPES or (m.type == "NODES" and not _smooth_by_angle(m))


def smooth_by_angle_first(ob, angle_deg):
    """A Smooth by Angle as ob's first modifier after any leading Mirror or Array (below them it sees the whole mesh,
    folds on the mirror plane included), at angle_deg, shading ob smooth. No other object is touched and a rerun gives
    the same stack. Runs in Object Mode only: raises RuntimeError, changing nothing, in any other mode."""
    if bpy.context.mode != "OBJECT":
        raise RuntimeError("smooth_by_angle_first needs Object Mode (Blender is in %s): run "
                           "bpy.ops.object.mode_set(mode='OBJECT') first, then call again" % bpy.context.mode)
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob],
                                   selected_editable_objects=[ob]):
        bpy.ops.object.shade_auto_smooth(angle=math.radians(angle_deg))
        sba = next(m for m in ob.modifiers if _smooth_by_angle(m))
        sba.use_pin_to_last = False
        index = 0
        for m in ob.modifiers:
            if m == sba:
                continue
            if m.type not in LEADING:
                break
            index += 1
        bpy.ops.object.modifier_move_to_index(modifier=sba.name, index=index)
    return sba


def _hand_off(ob, keep_mirror, add_triangulate):
    if ob.type != "MESH":
        raise ValueError("%s is not a mesh" % ob.name)
    mods = list(ob.modifiers)
    tri_i = next((i for i, m in enumerate(mods) if m.type == "TRIANGULATE"), len(mods))
    below = [m.name for m in mods[tri_i + 1:] if _changes_topology(m)]
    if below:
        raise ValueError("%s: %s sits below the Triangulate; move it above the Triangulate (Mirror and Array go first "
                         "in the stack, above the Bevel), then call again" % (ob.name, ", ".join(below)))
    topo = [i for i in range(tri_i) if _changes_topology(mods[i])]
    live = []
    while keep_mirror and topo and mods[topo[-1]].type == "MIRROR":
        live.insert(0, mods[topo.pop()].name)
    last = topo[-1] if topo else -1
    off = [m.name for m in mods[:last + 1] if not m.show_viewport]
    if off:
        raise ValueError("%s: %s is off in the viewport (Blender would apply it anyway); turn it on or delete it, then "
                         "call again" % (ob.name, ", ".join(off)))
    if last >= 0 and ob.data.shape_keys:
        raise ValueError("%s has shape keys: Blender cannot apply its modifiers" % ob.name)
    if last >= 0 and ob.data.users > 1:
        raise ValueError("%s shares its mesh with other objects: applying would split it from them; make it single "
                         "user first" % ob.name)
    applied = []
    was_edit = bpy.context.mode == "EDIT_MESH"
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob],
                                   selected_editable_objects=[ob]):
        if was_edit:
            bpy.ops.object.mode_set(mode="OBJECT")
        for _ in range(last + 1):
            name = ob.modifiers[0].name
            bpy.ops.object.modifier_apply(modifier=name)
            if ob.modifiers and ob.modifiers[0].name == name:
                raise ValueError("%s: Blender did not apply %s" % (ob.name, name))
            applied.append(name)
        tri = next((m for m in ob.modifiers if m.type == "TRIANGULATE"), None)
        if tri is None and add_triangulate:
            tri = ob.modifiers.new("Triangulate", "TRIANGULATE")
            tri.min_vertices, tri.keep_custom_normals = 4, True
            wn = next((i for i, m in enumerate(ob.modifiers) if m.type == "WEIGHTED_NORMAL"), None)
            if wn is not None:
                bpy.ops.object.modifier_move_to_index(modifier=tri.name, index=wn)
        if was_edit:
            bpy.ops.object.mode_set(mode="EDIT")
    if tri is not None:
        tri.show_viewport = False
    return {"applied": applied, "mirrors_live": live, "triangulate": tri.name if tri is not None else None}


def apply_for_uv_work(ob, add_triangulate=False):
    """Before seams: apply ob's stack from the top, in stack order, down to and including the last topology-changing
    modifier above the Triangulate (a Smooth by Angle or anything else above it goes with it), never a lower one
    alone. Mirrors at the end of that run (nothing but Mirrors changes topology below them) stay live, so their
    halves share UVs, until apply_before_layout; a Mirror with a Bevel below it is applied now (unique UVs). The
    stack's Triangulate is never applied: it is switched off in the viewport until after the layout (turn it back on
    then); a Weighted Normal stays live. add_triangulate=True gives a piece without a Triangulate one (Minimum
    Vertices 4, Keep Normals on) directly above any Weighted Normal. Refuses (ValueError, nothing applied): a
    topology change below the Triangulate, a modifier to apply that is off in the viewport, shape keys, a mesh shared
    with other objects. Returns {"applied", "mirrors_live", "triangulate"}."""
    return _hand_off(ob, True, add_triangulate)


def apply_before_layout(ob):
    """Just before the UV layout: apply the Mirrors apply_for_uv_work left live (first in the stack by then), with the
    same rules and refusals."""
    return _hand_off(ob, False, False)
