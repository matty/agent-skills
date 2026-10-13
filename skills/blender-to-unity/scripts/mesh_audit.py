"""Audit a Blender scene for VRChat world export problems.

Reports, per mesh object (modifiers evaluated):
  triangles, material slots, UV channels, n-gons, unapplied scale/rotation,
  negative scale, loose geometry

and scene-wide:
  total triangles, total unique materials, and groups of objects that SHARE a
  mesh datablock (linked duplicates) - those are exactly the objects that can
  collapse into one GPU-instanced draw call in Unity.

Usage: run from the Text Editor, or paste through the Blender MCP
`execute_blender_code`. Output goes to the system console / MCP result.
"""

import bpy

TRI_WARN = 20000        # per-object triangle count worth a second look
SLOT_WARN = 3           # material slots per object


def evaluated_stats(ob, depsgraph):
    eval_ob = ob.evaluated_get(depsgraph)
    mesh = eval_ob.to_mesh()
    try:
        tris = sum(max(len(p.vertices) - 2, 0) for p in mesh.polygons)
        ngons = sum(1 for p in mesh.polygons if len(p.vertices) > 4)
        uvs = len(mesh.uv_layers)
        verts = len(mesh.vertices)
    finally:
        eval_ob.to_mesh_clear()
    return tris, ngons, uvs, verts


def main():
    depsgraph = bpy.context.evaluated_depsgraph_get()
    objects = [ob for ob in bpy.context.scene.objects if ob.type == "MESH"]
    if not objects:
        print("no mesh objects in scene")
        return

    total_tris = 0
    materials = set()
    shared = {}
    rows = []

    for ob in objects:
        tris, ngons, uvs, verts = evaluated_stats(ob, depsgraph)
        total_tris += tris
        slots = len(ob.material_slots)
        for slot in ob.material_slots:
            if slot.material:
                materials.add(slot.material.name)
        shared.setdefault(ob.data.name, []).append(ob.name)

        flags = []
        if tuple(round(v, 4) for v in ob.scale) != (1.0, 1.0, 1.0):
            flags.append("scale%s" % (tuple(round(v, 3) for v in ob.scale),))
        if any(round(r, 4) != 0.0 for r in ob.rotation_euler):
            flags.append("rotation")
        if ob.scale.x * ob.scale.y * ob.scale.z < 0:
            flags.append("NEGATIVE-SCALE")
        if uvs == 0:
            flags.append("no-uv")
        elif uvs == 1:
            flags.append("no-uv2")
        if ngons:
            flags.append("ngons:%d" % ngons)
        if tris > TRI_WARN:
            flags.append("heavy")
        if slots > SLOT_WARN:
            flags.append("slots:%d" % slots)
        if not ob.data.polygons:
            flags.append("EMPTY-MESH")

        rows.append((tris, ob.name, verts, slots, uvs, " ".join(flags)))

    rows.sort(reverse=True)

    print("=" * 96)
    print("%-34s %9s %9s %6s %5s  %s" % ("OBJECT", "TRIS", "VERTS", "SLOTS", "UVs", "FLAGS"))
    print("-" * 96)
    for tris, name, verts, slots, uvs, flags in rows:
        print("%-34s %9d %9d %6d %5d  %s" % (name[:34], tris, verts, slots, uvs, flags))

    print("-" * 96)
    print("objects: %d   total triangles: %d   unique materials: %d"
          % (len(objects), total_tris, len(materials)))

    dupes = {mesh: names for mesh, names in shared.items() if len(names) > 1}
    if dupes:
        print("\nLinked duplicates (instanceable in Unity - same mesh + same material"
              " = one instanced draw call):")
        for mesh, names in sorted(dupes.items(), key=lambda kv: -len(kv[1])):
            print("  %-28s x%-4d  %s" % (mesh, len(names),
                                         ", ".join(names[:6]) + (" ..." if len(names) > 6 else "")))
    else:
        print("\nNo linked duplicates found. If you have repeated props, duplicate with"
              " Alt+D (linked) instead of Shift+D so they can share a mesh and instance.")

    print("\nBudget reference: Quest world ~250k tris total, PC 500k-1M. See the"
          " vrchat-world-optimization skill for the full table.")
    print("=" * 96)


main()
